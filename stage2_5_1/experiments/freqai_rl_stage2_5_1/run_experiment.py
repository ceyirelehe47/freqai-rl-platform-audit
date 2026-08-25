#!/usr/bin/env python
"""阶段 2.5.1 实验入口:完整指纹 -> 缓存守卫 -> freqtrade backtesting -> manifest 回填。

用法(在 WSL,conda freqtrade-rl 环境内,先 source scripts/proxy-on.sh):
    python experiments/freqai_rl_stage2_5_1/run_experiment.py \
        --timerange 20260601-20260701 [--seed 42] [--slippage-bps 5] [--fee 0.001] \
        [--suffix smoke] [--repair-partial-cache] [--artifacts]

流程(工作包 D/E + 各包联动):
1. 渲染配置(检查点 1:conv_width 守卫;PPO 冲突检测);
2. 完整指纹:freqtrade commit + 第一方代码 tree hash + 完整规范化配置
   (移除 identifier 避免自指) + 全量数据范围哈希(date < 评估结束,覆盖
   训练/预热) + 依赖版本 + resolved PPO 参数;
3. identifier = stage251-rc-<指纹前 10 位> 写入最终配置;
4. 缓存守卫(fail closed):PARTIAL/INCONSISTENT 中止(退出码 3);
   --repair-partial-cache 时整体 quarantine 后全窗口重推理;
5. freqtrade backtesting 子进程;
6. 后处理:拼接预测缓存动作序列、读取每窗 ppo_budget.json、回填 manifest
   (退出码/模型目录/缓存文件/每窗实际起止/动作分布)。
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))

from rl_platform.cache_guard import (  # noqa: E402
    PartialCacheError,
    classify_cache_state,
    derive_expected_windows,
    enforce_cache_state,
)
from rl_platform.fingerprint import (  # noqa: E402
    build_identifier,
    code_tree_hash,
    compute_fingerprint,
    config_hash,
    data_scope_hash,
    dependency_versions,
    eval_slice_info,
    normalize_config,
)
from rl_platform.guards import assert_conv_width  # noqa: E402
from rl_platform.ppo_params import resolve_ppo_params  # noqa: E402

DATA_FILE = PROJ_ROOT / "user_data" / "data" / "binanceus" / "BTC_USDT-1h.feather"
TEMPLATE = Path(__file__).parent / "configs" / "config_stage251.template.json"
RUNTIME_DIR = Path(__file__).parent / "runtime"
ARTIFACTS_DIR = PROJ_ROOT / "artifacts" / "freqai_rl_stage2_5_1"
IDENTIFIER_PREFIX = "stage251-rc"
PAIR = "BTC/USDT"
TIMEFRAME_SECS = 3600


def timerange_bounds(timerange: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    parts = timerange.split("-")
    start = pd.Timestamp(pd.to_datetime(parts[0], format="%Y%m%d"), tz="UTC")
    stop = pd.Timestamp(pd.to_datetime(parts[1], format="%Y%m%d"), tz="UTC")
    return start, stop


def freqtrade_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJ_ROOT / "vendor" / "freqtrade"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def render_config(args) -> dict:
    conf = json.loads(TEMPLATE.read_text())
    conf["timerange"] = args.timerange
    conf["fee"] = args.fee
    rc = conf["freqai"]["route_c"]
    rc["slippage_bps"] = args.slippage_bps
    rc["seed"] = args.seed
    # 检查点 1/4:配置渲染阶段 conv_width 守卫(不得自动降级)
    assert_conv_width(conf["freqai"]["conv_width"], source="run_experiment 配置渲染")
    # PPO 冲突检测(唯一来源 freqai.route_c.ppo;渲染阶段 strict=未经 schema 填充)
    resolve_ppo_params(conf["freqai"], strict=True)
    return conf


def build_manifest(conf: dict, fingerprint: str, identifier: str,
                    resolved_ppo: dict, windows: list) -> dict:
    return {
        "identifier": identifier,
        "fingerprint": fingerprint,
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "freqtrade_commit": freqtrade_commit(),
        "code_tree": code_tree_hash(PROJ_ROOT),
        "config_normalized": normalize_config(conf),
        "config_hash": config_hash(conf),
        "data_scope": conf["_data_scope"],
        "eval_slice": conf["_eval_slice"],
        "dependencies": dependency_versions(),
        "resolved_ppo_params": resolved_ppo,
        "expected_windows": windows,
    }


def post_run_collect(identifier: str, args) -> dict:
    """运行后回填:动作序列、模型预算记录、每窗实际起止、动作分布。"""
    models_dir = PROJ_ROOT / "user_data" / "models" / identifier
    pred_dir = models_dir / "backtesting_predictions"
    frames, pred_meta = [], []
    if pred_dir.is_dir():
        for f in sorted(pred_dir.glob("cb_btc_*_prediction.feather"),
                        key=lambda p: int(p.name.split("_")[2])):
            df = pd.read_feather(f)
            frames.append(df[["date", "&-target_position", "do_predict"]])
            pred_meta.append({
                "file": f.name,
                "rows": int(len(df)),
                "first_date": str(df["date"].min()),
                "last_date": str(df["date"].max()),
            })
    actions_csv = None
    action_dist = None
    if frames:
        full = pd.concat(frames, ignore_index=True).sort_values("date")
        actions_csv = RUNTIME_DIR / f"actions_{identifier}_{args.suffix}.csv"
        actions_csv.parent.mkdir(parents=True, exist_ok=True)
        full.to_csv(actions_csv, index=False)
        action_dist = {str(k): int(v) for k, v in
                       Counter(full["&-target_position"].astype(int)).items()}
    budgets = []
    for d in sorted(models_dir.glob("sub-train-*")):
        bj = d / "ppo_budget.json"
        if bj.is_file():
            rec = json.loads(bj.read_text())
            rec["model_dir"] = d.name
            budgets.append(rec)
    return {
        "prediction_files": pred_meta,
        "actions_csv": str(actions_csv) if actions_csv else None,
        "action_distribution": action_dist,
        "ppo_budgets": budgets,
        "model_dirs": [d.name for d in sorted(models_dir.glob("sub-train-*"))],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timerange", default="20260601-20260701")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--suffix", default="base")
    ap.add_argument("--export", default="signals")
    ap.add_argument("--extract-actions", action="store_true")
    ap.add_argument("--repair-partial-cache", action="store_true")
    ap.add_argument("--skip-backtest", action="store_true",
                    help="只渲染指纹与 manifest,不启动 freqtrade(测试用)")
    args = ap.parse_args()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    conf = render_config(args)
    eval_start, eval_end = timerange_bounds(args.timerange)
    conf["_data_scope"] = data_scope_hash(DATA_FILE, eval_end)
    conf["_eval_slice"] = eval_slice_info(DATA_FILE, eval_start, eval_end)
    resolved_ppo = resolve_ppo_params(conf["freqai"])

    parts = {
        "freqtrade_commit": freqtrade_commit(),
        "code_tree": code_tree_hash(PROJ_ROOT)["tree_hash"],
        "config": normalize_config(conf),
        "data_scope": conf["_data_scope"],
        "eval_slice": conf["_eval_slice"],
        "dependencies": dependency_versions(),
        "resolved_ppo_params": resolved_ppo,
        "conv_width": conf["freqai"]["conv_width"],
    }
    fingerprint = compute_fingerprint(parts)
    identifier = build_identifier(IDENTIFIER_PREFIX, fingerprint)
    print(f"[run_experiment] fingerprint={fingerprint}")
    print(f"[run_experiment] identifier={identifier}")
    print(f"[run_experiment] data_scope={conf['_data_scope']}")

    conf["freqai"]["identifier"] = identifier
    config_path = RUNTIME_DIR / f"config_{identifier}_{args.suffix}.json"
    slim = {k: v for k, v in conf.items() if not k.startswith("_")}
    config_path.write_text(json.dumps(slim, indent=4))

    train_days = conf["freqai"]["train_period_days"]
    bt_days = conf["freqai"]["backtest_period_days"]
    windows = derive_expected_windows(args.timerange, train_days, bt_days)
    print(f"[run_experiment] 预期窗口数={len(windows)}")

    manifest = build_manifest(conf, fingerprint, identifier, resolved_ppo, windows)
    manifest_path = RUNTIME_DIR / f"manifest_{identifier}_{args.suffix}.json"

    # ---------------------------------------------------------- 缓存守卫
    models_dir = PROJ_ROOT / "user_data" / "models" / identifier
    pred_dir = models_dir / "backtesting_predictions"
    quarantine_path = None
    try:
        result, quarantine = enforce_cache_state(
            pred_dir, windows, PAIR, TIMEFRAME_SECS, repair=args.repair_partial_cache
        )
        quarantine_path = str(quarantine) if quarantine else None
        print(f"[run_experiment] 缓存状态={result.state}"
              + (f" (quarantine -> {quarantine})" if quarantine else ""))
    except PartialCacheError as e:
        print(f"[run_experiment] {e}", file=sys.stderr)
        manifest["cache_guard"] = {"state": classify_cache_state(
            pred_dir, windows, PAIR, TIMEFRAME_SECS).state, "aborted": True}
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 3
    manifest["cache_guard"] = {"state": result.state, "quarantine": quarantine_path}

    if args.skip_backtest:
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        print(f"[run_experiment] skip-backtest, manifest -> {manifest_path}")
        return 0

    cmd = [
        "freqtrade", "backtesting",
        "--config", str(config_path),
        "--userdir", str(PROJ_ROOT / "user_data"),
        "--strategy", "RouteCStrategy",
        "--freqaimodel", "RouteCModel",
        "--timerange", args.timerange,
        "--cache", "none",
        "--export", args.export,
    ]
    print("[run_experiment] " + " ".join(cmd))
    ret = subprocess.run(cmd).returncode
    print(f"[run_experiment] freqtrade 退出码 {ret}")

    manifest["post_run"] = post_run_collect(identifier, args)
    manifest["post_run"]["exit_code"] = ret
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[run_experiment] manifest -> {manifest_path}")
    if manifest["post_run"]["action_distribution"]:
        print(f"[run_experiment] 动作分布 {manifest['post_run']['action_distribution']}")
    return ret


if __name__ == "__main__":
    raise SystemExit(main())
