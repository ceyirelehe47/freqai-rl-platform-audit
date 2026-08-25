#!/usr/bin/env python
"""阶段 2.5.2a 实验入口:完整指纹(含执行合同) -> 双层缓存守卫 ->
freqtrade backtesting(市场订单策略) -> 缓存内容清单落盘+自检(失败致命)。

在阶段 2.5.2 runner 基础上改造:
1. 工作包 I:route_c 键改为 execution_mode / simulated_slippage_bps;
   指纹与 manifest 记录执行合同(execution_mode/滑点/tick 取整版本/
   终端清算/订单类型/amount_epsilon/环境成交模块代码哈希);
   任何执行模式、滑点、tick、终端清算方式变化都会改变 config,
   从而改变指纹与 identifier;
2. 工作包 G:回测成功后生成缓存内容 manifest 并立即自检,
   只有 self_check == COMPLETE 整轮实验才算成功;
   生成或自检失败 -> 写入原始错误、backtesting_predictions 整体
   quarantine(不删除模型)、本轮 manifest 标记 invalid、退出码 4,
   后续运行按 NONE 全窗重推理,不得复用被隔离的缓存。

用法(WSL,conda freqtrade-rl 环境):
    python experiments/freqai_rl_stage2_5_2a/run_experiment.py \
        --timerange 20260601-20260701 [--seed 42] [--simulated-slippage-bps 0] \
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
    quarantine_predictions_dir,
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
    sha256_file,
)
from rl_platform.guards import assert_conv_width  # noqa: E402
from rl_platform.market_execution import (  # noqa: E402
    EXECUTION_MODE,
    TICK_ROUNDING_VERSION,
)
from rl_platform.ppo_params import resolve_ppo_params  # noqa: E402

DATA_FILE = PROJ_ROOT / "user_data" / "data" / "binanceus" / "BTC_USDT-1h.feather"
TEMPLATE = Path(__file__).parent / "configs" / "config_stage252a.template.json"
RUNTIME_DIR = Path(__file__).parent / "runtime"
IDENTIFIER_PREFIX = "stage252a-rc"
PAIR = "BTC/USDT"
TIMEFRAME_SECS = 3600

# 缓存后处理失败专用退出码(工作包 G;区别于守卫中止的 3)
CACHE_PIPELINE_EXIT_CODE = 4

# 与模板 ppo 段一致的烟雾参数(测试构造模型配置时复用)
PPO_SMOKE_PARAMS = {
    "n_steps": 128,
    "batch_size": 64,
    "n_epochs": 10,
    "learning_rate": 0.00025,
    "gamma": 0.90,
    "gae_lambda": 0.95,
    "clip_range": 0.20,
    "ent_coef": 0.0,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "normalize_advantage": True,
    "net_arch": [32, 32],
}


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


def build_execution_contract_manifest(route_c: dict) -> dict:
    """工作包 I:执行合同记录(进入 manifest 与指纹 parts)。"""
    return {
        "execution_mode": route_c.get("execution_mode", EXECUTION_MODE),
        "simulated_slippage_bps": float(route_c.get("simulated_slippage_bps", 0.0)),
        "price_tick": float(route_c.get("price_tick", 0.0)),
        "tick_rounding_version": TICK_ROUNDING_VERSION,
        "tick_rounding_rule": "买入 ceil_to_tick 向上取整,卖出 floor_to_tick 向下取整",
        "terminal_liquidation_mode": "close_market_sell_with_slippage_and_fee",
        "terminal_liquidation_rule": (
            "最后一个执行周期结束于 close[last],以与普通市场卖出完全相同的"
            " simulated_slippage_bps、tick 取整、卖出手续费清算,最终全现金"
        ),
        "order_type": "market(entry/exit 均市场订单;回测以 open[t+1] 成交)",
        "amount_epsilon": float(route_c.get("amount_epsilon", 1e-12)),
        "causality": (
            "成交价只依赖 open[t+1]/方向/simulated_slippage_bps/price_tick/fee;"
            "不依赖执行 K 线 high/low/close 或后续 K 线"
        ),
        "live_fill_boundary": (
            "Freqtrade live 使用交易所真实回报价格;simulated_slippage_bps "
            "只属于训练与离线压力环境,不改变 live 市场订单价格"
        ),
        "env_slippage_enabled": float(route_c.get("simulated_slippage_bps", 0.0)) > 0.0,
        "env_execution_module_sha256": sha256_file(
            PROJ_ROOT / "src" / "rl_platform" / "market_execution.py"),
        "legacy_note": (
            "bar_executable_price(bar 内调价)已废弃为 "
            "legacy_noncausal_not_for_training,仅历史测试,不在生产调用路径"
        ),
    }


def render_config(args) -> dict:
    conf = json.loads(TEMPLATE.read_text())
    conf["timerange"] = args.timerange
    conf["fee"] = args.fee
    rc = conf["freqai"]["route_c"]
    rc["simulated_slippage_bps"] = args.simulated_slippage_bps
    rc["price_tick"] = args.price_tick
    rc["seed"] = args.seed
    # 工作包 A/B:唯一允许的执行模式(配置显式冻结,不得启用 legacy)
    rc["execution_mode"] = EXECUTION_MODE
    # 检查点 1/4:配置渲染阶段 conv_width 守卫(不得自动降级)
    assert_conv_width(conf["freqai"]["conv_width"], source="run_experiment 配置渲染")
    # PPO 冲突检测(唯一来源 freqai.route_c.ppo;渲染阶段 strict=未经 schema 填充)
    resolve_ppo_params(conf["freqai"], strict=True)
    if float(args.price_tick) < 0:
        raise ValueError(f"price_tick 不得为负,收到 {args.price_tick}")
    if float(args.simulated_slippage_bps) < 0:
        raise ValueError(
            f"simulated_slippage_bps 不得为负,收到 {args.simulated_slippage_bps}")
    return conf


def position_mapping_manifest() -> dict:
    """任务书五节:manifest 必须记录当前仓位映射规则。"""
    return {
        "mapping": dict(MODEL_POSITION_MAP),
        "semantics": {
            "model_position": "0=无实际成交暴露,1=存在正的实际成交暴露",
            "filled_amount": (
                "trade.amount(已关闭订单汇总)+ 活动入场单累计成交"
                "(safe_amount_after_fee 口径)- 活动退出单累计成交"
            ),
            "INCONSISTENT": "无映射:fail closed,不调用模型,不生成订单,不静默选择",
        },
        "resolved_from": "Trade.get_trades_proxy(is_open=True) + Order 实时状态",
        "amount_epsilon_source": "freqai.route_c.amount_epsilon(模型与策略同源)",
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
        "execution_contract": build_execution_contract_manifest(
            conf["freqai"]["route_c"]),
        "position_mapping": position_mapping_manifest(),
    }


def post_backtest_cache_pipeline(
    *,
    identifier: str,
    fingerprint: str,
    windows: list,
    pred_dir: Path,
    content_manifest_path: Path,
    manifest: dict,
    manifest_path: Path,
) -> int:
    """工作包 G:回测成功后的缓存内容 manifest 生成 + 立即自检。

    只有 self_check == COMPLETE 才算成功;生成或自检失败:
    写入原始错误 -> backtesting_predictions 整体 quarantine(不删模型)
    -> 本轮 manifest 标记 invalid -> 退出码 4;Freqtrade 的退出码 0
    不得覆盖后处理失败。
    """
    try:
        content = build_cache_content_manifest(
            pred_dir, windows, PAIR, TIMEFRAME_SECS,
            fingerprint=fingerprint, identifier=identifier,
        )
        content_manifest_path.write_text(
            json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
        cstate, cissues = verify_cache_content(
            pred_dir, windows, PAIR, TIMEFRAME_SECS, content, fingerprint)
        if cstate != "COMPLETE":
            raise CacheContentError(
                f"缓存内容自检 {cstate},问题清单:\n" + "\n".join(cissues)
            )
    except Exception as exc:  # noqa: BLE001 - 后处理任何失败都必须致命
        quarantine = None
        quarantine_err = None
        try:
            if pred_dir.is_dir():
                quarantine = quarantine_predictions_dir(pred_dir)
        except Exception as qexc:  # noqa: BLE001
            quarantine_err = repr(qexc)
        manifest["cache_content_manifest"] = {
            "error": repr(exc),
            "invalid": True,
            "self_check": "INCONSISTENT",
            "quarantine": str(quarantine) if quarantine else None,
            "quarantine_error": quarantine_err,
            "models_dir_kept": True,
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False))
        print(
            f"[run_experiment] 缓存内容 manifest 生成/自检失败,整轮实验失败"
            f"(退出码 {CACHE_PIPELINE_EXIT_CODE}): {exc!r}",
            file=sys.stderr,
        )
        return CACHE_PIPELINE_EXIT_CODE
    manifest["cache_content_manifest"] = {
        "path": str(content_manifest_path),
        "files": len(content["files"]),
        "self_check": cstate,
        "invalid": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[run_experiment] 缓存内容清单已生成,自校验={cstate}")
    return 0


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
    ap.add_argument("--simulated-slippage-bps", type=float, default=0.0)
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

    execution_contract = build_execution_contract_manifest(conf["freqai"]["route_c"])
    parts = {
        "freqtrade_commit": freqtrade_commit(),
        "code_tree": code_tree_hash(PROJ_ROOT)["tree_hash"],
        "config": normalize_config(conf),
        "data_scope": conf["_data_scope"],
        "eval_slice": conf["_eval_slice"],
        "dependencies": dependency_versions(),
        "resolved_ppo_params": resolved_ppo,
        "conv_width": conf["freqai"]["conv_width"],
        "execution_contract": execution_contract,
    }
    fingerprint = compute_fingerprint(parts)
    identifier = build_identifier(IDENTIFIER_PREFIX, fingerprint)
    print(f"[run_experiment] fingerprint={fingerprint}")
    print(f"[run_experiment] identifier={identifier}")
    print(f"[run_experiment] data_scope={conf['_data_scope']}")
    print(f"[run_experiment] execution_mode={execution_contract['execution_mode']} "
          f"simulated_slippage_bps={execution_contract['simulated_slippage_bps']}")

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

    # --------------------------------- 第二层缓存守卫(内容级)
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

    # ------------- 成功运行后生成缓存内容清单+自检(失败致命,工作包 G)
    if ret == 0 and pred_dir.is_dir():
        pipeline_rc = post_backtest_cache_pipeline(
            identifier=identifier,
            fingerprint=fingerprint,
            windows=windows,
            pred_dir=pred_dir,
            content_manifest_path=content_manifest_path,
            manifest=manifest,
            manifest_path=manifest_path,
        )
        if pipeline_rc != 0:
            return pipeline_rc  # Freqtrade 的退出码 0 不得覆盖后处理失败
    else:
        manifest["cache_content_manifest"] = {
            "state": "SKIPPED",
            "reason": f"freqtrade 退出码 {ret} 或无预测目录",
        }

    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[run_experiment] manifest -> {manifest_path}")
    if manifest["post_run"]["action_distribution"]:
        print(f"[run_experiment] 动作分布 {manifest['post_run']['action_distribution']}")
    return ret


if __name__ == "__main__":
    raise SystemExit(main())
