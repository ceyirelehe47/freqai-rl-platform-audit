#!/usr/bin/env python
"""阶段 2.5.2 实验入口:完整指纹 -> 缓存守卫(名称+内容双层) ->
freqtrade backtesting -> 缓存内容清单落盘 -> manifest 回填。

在阶段 2.5.1 runner 基础上新增(工作包 D/E 联动):
1. route_c.price_tick / amount_epsilon 进入配置与指纹;
2. manifest 记录模型观察仓位映射规则(任务书五节);
3. 缓存守卫双层:cache_guard(名称/行数,四态)通过后再做
   cache_content 内容级校验(sha256/日期序列/列哈希/指纹绑定),
   INCONSISTENT 默认中止(退出码 3),--repair-partial-cache 整体 quarantine;
4. 成功运行后生成 cache_content_manifest.json(模型目录,与缓存同级),
   供下次启动做内容级 COMPLETE 判定。

用法(WSL,conda freqtrade-rl 环境):
    python experiments/freqai_rl_stage2_5_2/run_experiment.py \
        --timerange 20260601-20260701 [--seed 42] [--slippage-bps 5] \
        [--fee 0.001] [--price-tick 0.01] [--suffix smoke] \
        [--repair-partial-cache] [--skip-backtest]
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

from rl_platform.cache_content import (  # noqa: E402
    CACHE_MANIFEST_NAME,
    CacheContentError,
    build_cache_content_manifest,
    enforce_cache_content,
    verify_cache_content,
)
from rl_platform.cache_guard import (  # noqa: E402
    PartialCacheError,
    classify_cache_state,
    derive_expected_windows,
    enforce_cache_state,
)
from rl_platform.execution_state import MODEL_POSITION_MAP  # noqa: E402
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
TEMPLATE = Path(__file__).parent / "configs" / "config_stage252.template.json"
RUNTIME_DIR = Path(__file__).parent / "runtime"
IDENTIFIER_PREFIX = "stage252-rc"
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
    rc["price_tick"] = args.price_tick
    rc["seed"] = args.seed
    # 检查点 1/4:配置渲染阶段 conv_width 守卫(不得自动降级)
    assert_conv_width(conf["freqai"]["conv_width"], source="run_experiment 配置渲染")
    # PPO 冲突检测(唯一来源 freqai.route_c.ppo;渲染阶段 strict=未经 schema 填充)
    resolve_ppo_params(conf["freqai"], strict=True)
    if float(args.price_tick) <= 0:
        raise ValueError(
            "阶段 2.5.2 执行合同要求 price_tick > 0(工作包 D;"
            f"收到 {args.price_tick})"
        )
    return conf


def position_mapping_manifest() -> dict:
    """任务书五节:manifest 必须记录当前仓位映射规则。"""
    return {
        "mapping": dict(MODEL_POSITION_MAP),
        "semantics": {
            "model_position": "0=无实际成交暴露,1=存在正的实际成交暴露",
            "filled_amount": (
                "trade.amount(已关闭订单汇总)+ 活动入场单累计成交 "
                "- 活动退出单累计成交"
            ),
            "INCONSISTENT": "无映射:fail closed,不生成订单,不静默选择",
        },
        "resolved_from": "Trade.get_trades_proxy(is_open=True) + Order 实时状态",
    }


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
        "execution_contract": {
            "price_tick": conf["freqai"]["route_c"]["price_tick"],
            "amount_epsilon": conf["freqai"]["route_c"]["amount_epsilon"],
            "rule": (
                "请求滑点价触及当根 high/low 时按 tick 向 bar 内移动一格;"
                "bar 容纳不下内部价时 fallback open(bar 内一 tick 执行合同,工作包 D)"
            ),
        },
        "position_mapping": position_mapping_manifest(),
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
    ap.add_argument("--price-tick", type=float, default=0.01)
    ap.add_argument("--suffix", default="base")
    ap.add_argument("--export", default="signals")
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

    # ------------------------------------------- 第一层缓存守卫(名称/行数)
    models_dir = PROJ_ROOT / "user_data" / "models" / identifier
    pred_dir = models_dir / "backtesting_predictions"
    quarantine_path = None
    try:
        result, quarantine = enforce_cache_state(
            pred_dir, windows, PAIR, TIMEFRAME_SECS, repair=args.repair_partial_cache
        )
        quarantine_path = str(quarantine) if quarantine else None
        print(f"[run_experiment] 缓存状态(名称/行数)={result.state}"
              + (f" (quarantine -> {quarantine})" if quarantine else ""))
    except PartialCacheError as e:
        print(f"[run_experiment] {e}", file=sys.stderr)
        manifest["cache_guard"] = {"state": classify_cache_state(
            pred_dir, windows, PAIR, TIMEFRAME_SECS).state, "aborted": True}
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 3
    manifest["cache_guard"] = {"state": result.state, "quarantine": quarantine_path}

    # --------------------------------- 第二层缓存守卫(内容级,工作包 E)
    content_manifest_path = models_dir / CACHE_MANIFEST_NAME
    content_manifest = None
    if content_manifest_path.is_file():
        content_manifest = json.loads(content_manifest_path.read_text())
    if result.state == "COMPLETE":
        try:
            cstate, cissues, cquarantine = enforce_cache_content(
                pred_dir, windows, PAIR, TIMEFRAME_SECS, content_manifest,
                fingerprint, repair=args.repair_partial_cache,
            )
            print(f"[run_experiment] 缓存状态(内容级)={cstate} issues={len(cissues)}")
            manifest["cache_content_guard"] = {
                "state": cstate,
                "issues": cissues,
                "quarantine": str(cquarantine) if cquarantine else None,
            }
        except CacheContentError as e:
            print(f"[run_experiment] {e}", file=sys.stderr)
            manifest["cache_content_guard"] = {
                "state": "INCONSISTENT", "aborted": True, "error": str(e),
            }
            manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
            return 3
    else:
        manifest["cache_content_guard"] = {
            "state": "SKIPPED", "reason": f"名称/行数层为 {result.state},无缓存可校验",
        }

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

    # ------------------------- 成功运行后生成缓存内容清单(下次内容级 COMPLETE)
    if ret == 0 and pred_dir.is_dir():
        try:
            content = build_cache_content_manifest(
                pred_dir, windows, PAIR, TIMEFRAME_SECS,
                fingerprint=fingerprint, identifier=identifier,
            )
            content_manifest_path.write_text(
                json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
            manifest["cache_content_manifest"] = {
                "path": str(content_manifest_path),
                "files": len(content["files"]),
            }
            # 立即自校验一次(生成即可验证)
            cstate, cissues = verify_cache_content(
                pred_dir, windows, PAIR, TIMEFRAME_SECS, content, fingerprint)
            manifest["cache_content_manifest"]["self_check"] = cstate
            print(f"[run_experiment] 缓存内容清单已生成,自校验={cstate}")
        except Exception as exc:  # noqa: BLE001
            manifest["cache_content_manifest"] = {"error": repr(exc)}

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[run_experiment] manifest -> {manifest_path}")
    if manifest["post_run"]["action_distribution"]:
        print(f"[run_experiment] 动作分布 {manifest['post_run']['action_distribution']}")
    return ret


if __name__ == "__main__":
    raise SystemExit(main())
