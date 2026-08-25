#!/usr/bin/env python
"""阶段 2.5 实验入口:指纹 -> 渲染 config -> freqtrade backtesting。

用法(在 WSL,conda freqtrade-rl 环境内):
    python experiments/freqai_rl_stage2_5/run_experiment.py \
        --timerange 20260601-20260701 [--seed 42] [--slippage-bps 0] \
        [--suffix base] [--export signals] [--extract-actions]

流程:
1. 计算实验指纹(freqtrade commit/自有代码哈希/奖励与费用配置/特征清单/
   timerange/裁剪后数据哈希/seed/模型类型/关键训练参数);
2. identifier = stage25-rc-<指纹前 10 位>,写入渲染后的 config;
3. 保存 manifest(完整指纹输入)到 runtime/;
4. 调用 freqtrade backtesting --strategy RouteCStrategy --freqaimodel RouteCModel;
5. --extract-actions 时从导出的 signals feather 提取目标仓位序列 CSV
   (用于 reload determinism 对比)。
"""

import argparse
import glob
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))

from rl_platform.fingerprint import (  # noqa: E402
    build_identifier,
    collect_code_hashes,
    compute_fingerprint,
)

DATA_FILE = PROJ_ROOT / "user_data" / "data" / "binanceus" / "BTC_USDT-1h.feather"
TEMPLATE = Path(__file__).parent / "configs" / "config_stage25.template.json"
RUNTIME_DIR = Path(__file__).parent / "runtime"
IDENTIFIER_PREFIX = "stage25-rc"

FEATURE_LIST = ["%-ret-1", "%-ret-4", "%-vol-24", "%-price-ma-ratio"]


def timerange_bounds(timerange: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    parts = timerange.split("-")
    start = pd.Timestamp(pd.to_datetime(parts[0], format="%Y%m%d"), tz="UTC")
    stop = pd.Timestamp(pd.to_datetime(parts[1], format="%Y%m%d"), tz="UTC")
    return start, stop


def sliced_data_sha256(timerange: str) -> dict:
    """半开区间 [start, stop) 裁剪真实数据并计算规范化哈希。"""
    df = pd.read_feather(DATA_FILE)
    start, stop = timerange_bounds(timerange)
    sl = df[(df["date"] >= start) & (df["date"] < stop)]
    if sl.empty:
        raise RuntimeError(f"裁剪后数据为空:{timerange}")
    payload = sl[["date", "open", "high", "low", "close", "volume"]].to_csv(
        index=False, date_format="%Y-%m-%dT%H:%M:%S%z"
    )
    return {
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "bars": int(len(sl)),
        "first": str(sl["date"].min()),
        "last": str(sl["date"].max()),
        "source_file": str(DATA_FILE.name),
    }


def git_commit() -> str:
    return subprocess.run(
        ["git", "-C", str(PROJ_ROOT / "vendor" / "freqtrade"), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timerange", default="20260601-20260701")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--slippage-bps", type=float, default=0.0)
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--suffix", default="base")
    ap.add_argument("--export", default="signals")
    ap.add_argument("--extract-actions", action="store_true")
    args = ap.parse_args()

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    data_info = sliced_data_sha256(args.timerange)
    parts = {
        "freqtrade_commit": git_commit(),
        "code_sha256": collect_code_hashes(PROJ_ROOT),
        "reward": {"type": "log_equity_return", "scale": 1.0},
        "fee": args.fee,
        "slippage_bps": args.slippage_bps,
        "features": FEATURE_LIST,
        "pair": "BTC/USDT",
        "timeframe": "1h",
        "trading_mode": "spot",
        "timerange": args.timerange,
        "data_slice": data_info,
        "seed": args.seed,
        "model_type": "PPO",
        "policy_type": "MlpPolicy",
        "train_params": {
            "net_arch": [32, 32],
            "train_cycles": 1,
            "learning_rate": 0.00025,
            "gamma": 0.9,
            "initial_cash": 100.0,
            "device": "cpu",
        },
    }
    fingerprint = compute_fingerprint(parts)
    identifier = build_identifier(IDENTIFIER_PREFIX, fingerprint)
    print(f"[run_experiment] fingerprint={fingerprint}")
    print(f"[run_experiment] identifier={identifier}")
    print(f"[run_experiment] data_slice={data_info}")

    manifest = {"identifier": identifier, "fingerprint": fingerprint, "inputs": parts}
    manifest_path = RUNTIME_DIR / f"manifest_{identifier}_{args.suffix}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(f"[run_experiment] manifest -> {manifest_path}")

    conf = json.loads(TEMPLATE.read_text())
    conf["freqai"]["identifier"] = identifier
    conf["fee"] = args.fee
    conf["freqai"]["route_c"]["slippage_bps"] = args.slippage_bps
    conf["freqai"]["route_c"]["seed"] = args.seed
    config_path = RUNTIME_DIR / f"config_{identifier}_{args.suffix}.json"
    config_path.write_text(json.dumps(conf, indent=4))
    print(f"[run_experiment] config -> {config_path}")

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

    if args.extract_actions:
        results_dir = PROJ_ROOT / "user_data" / "backtest_results"
        cands = sorted(
            glob.glob(str(results_dir / "*.signals.feather")),
            key=os.path.getmtime,
        )
        if not cands:
            print("[run_experiment] 未找到 signals feather,无法提取动作序列", file=sys.stderr)
            return ret or 1
        latest = cands[-1]
        sig = pd.read_feather(latest)
        out = sig[["date", "&-target_position", "do_predict"]].copy()
        out_path = RUNTIME_DIR / f"actions_{identifier}_{args.suffix}.csv"
        out.to_csv(out_path, index=False)
        dist = out["&-target_position"].value_counts().to_dict()
        print(f"[run_experiment] signals={latest}")
        print(f"[run_experiment] actions -> {out_path} (分布 {dist})")

    return ret


if __name__ == "__main__":
    raise SystemExit(main())
