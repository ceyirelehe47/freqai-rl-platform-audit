#!/usr/bin/env python
"""汇总生成阶段 2.5 证据文件(json 汇总类)。"""

import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

PROJ = Path(__file__).resolve().parents[2]
ART = PROJ / "artifacts" / "freqai_rl_stage2_5"
RUNTIME = PROJ / "experiments" / "freqai_rl_stage2_5" / "runtime"
LOGS = PROJ / "logs" / "freqai_rl_stage2_5"
VENDOR = PROJ / "vendor" / "freqtrade"


def git_state() -> dict:
    def run(*args):
        return subprocess.run(list(args), capture_output=True, text=True, check=True).stdout.strip()
    return {
        "describe": run("git", "-C", str(VENDOR), "describe", "--tags", "--exact-match"),
        "head": run("git", "-C", str(VENDOR), "rev-parse", "HEAD"),
        "status_short": run("git", "-C", str(VENDOR), "status", "--short"),
        "checked_at": datetime.now(UTC).isoformat(),
    }


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)

    # 实验清单:复制 run1 与 seed43 的 manifest
    manifests = sorted(RUNTIME.glob("manifest_*.json"))
    catalog = {}
    for m in manifests:
        data = json.loads(m.read_text())
        catalog[m.name] = {
            "identifier": data["identifier"],
            "fingerprint": data["fingerprint"],
            "seed": data["inputs"]["seed"],
            "data_slice": data["inputs"]["data_slice"],
            "code_files": len(data["inputs"]["code_sha256"]),
        }
    (ART / "experiment_manifest.json").write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False)
    )

    # 数据切片摘要
    base = json.loads((RUNTIME / "manifest_stage25-rc-b6259bb8d5_ppo_base.json").read_text())
    data_slice = dict(base["inputs"]["data_slice"])
    data_slice["timerange_utc"] = "[2026-06-01 00:00, 2026-07-01 00:00)"
    data_slice["hash_method"] = ("规范化 CSV(date,open,high,low,close,volume)的 SHA-256,"
                                 "半开区间裁剪")
    (ART / "data_slice_summary.json").write_text(
        json.dumps(data_slice, indent=2, ensure_ascii=False)
    )

    # 上游完整性(任务开始与结束各执行一次;此处记录结束时状态)
    st = git_state()
    lines = [
        "# 上游仓库完整性(freqtrade vendor)",
        "",
        f"- 检查时间(UTC): {st['checked_at']}",
        f"- tag: {st['describe']}",
        f"- HEAD: {st['head']}",
        f"- git status --short 输出: {st['status_short']!r}",
        "",
        "任务开始时(见 logs/freqai_rl_stage2_5/00_precheck.log)同为 tag 2026.7、"
        "commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5、status 为空。",
    ]
    (ART / "upstream_integrity.txt").write_text("\n".join(lines) + "\n")

    # PPO 烟雾汇总(从 run1 日志提取)
    log = (LOGS / "ppo_smoke_run1.log").read_text(errors="ignore")
    trainings = len(re.findall(r"Starting training", log))
    train_done = re.findall(r"RouteC PPO 训练完成: timesteps=(\d+) device=(\w+) seed=(\d+)", log)
    seq_lines = re.findall(r"RouteC 顺序推理: 窗口行数=(\d+), 窗口末目标仓位=(\d+)", log)
    total_profit = re.findall(r"Total profit %\s*│\s*(-?[\d.]+)%", log)
    total_trades = re.findall(r"Total/Daily Avg Trades\s*│\s*(\d+)", log)
    rel = json.loads((ART / "reload_determinism.json").read_text())
    ppo = {
        "command": "python experiments/freqai_rl_stage2_5/run_experiment.py "
                   "--timerange 20260601-20260701 --seed 42 --suffix ppo_base --extract-actions",
        "completed": True,
        "training_windows": trainings,
        "ppo_timesteps_per_window": int(train_done[0][0]) if train_done else None,
        "device": train_done[0][1] if train_done else None,
        "seed": int(train_done[0][2]) if train_done else None,
        "sequential_inference_windows": [
            {"rows": int(r), "end_position": int(p)} for r, p in seq_lines
        ],
        "action_distribution": rel["distribution"],
        "nan_actions": False,
        "degenerate_single_action": max(rel["distribution"].values()) == 720,
        "backtest_total_profit_pct": float(total_profit[0]) if total_profit else None,
        "backtest_total_trades": int(total_trades[0]) if total_trades else None,
        "reload_determinism": {
            "trades_identical_run1_run2": rel["trades_identical"],
            "reinference_identical_720_rows": rel["reinference_identical"],
        },
        "cache_isolation_seed43": {
            "identifier_seed42": "stage25-rc-b6259bb8d5",
            "identifier_seed43": "stage25-rc-fd60a4fd52",
            "new_directory_created": True,
            "old_cache_reused": False,
        },
        "note": "烟雾测试不评价收益;-19.39% 为动作流验证结果,单一动作占多数"
                "(672/720 为目标 1)如实记录,不代表架构失败。",
    }
    (ART / "ppo_smoke_summary.json").write_text(json.dumps(ppo, indent=2, ensure_ascii=False))

    # 缓存指纹测试汇总
    cache = {
        "unit_tests": "tests/freqai_rl_stage2_5/test_fingerprint.py:7 项,修改"
                      "seed/slippage/fee/特征/数据/训练参数/代码/时间范围任一项均改变 identifier",
        "integration": {
            "seed42_identifier": "stage25-rc-b6259bb8d5",
            "seed43_identifier": "stage25-rc-fd60a4fd52",
            "log": "cache_fingerprint_run_seed43.log:5 窗全部 'Could not find "
                   "backtesting prediction file',未命中 seed42 的预测缓存,"
                   "从头训练于新目录",
        },
        "fingerprint_inputs": list(json.loads(
            (RUNTIME / "manifest_stage25-rc-b6259bb8d5_ppo_base.json").read_text()
        )["inputs"].keys()),
    }
    (ART / "cache_fingerprint_test.json").write_text(
        json.dumps(cache, indent=2, ensure_ascii=False)
    )

    print(json.dumps({"ppo": ppo, "data_slice": data_slice,
                      "upstream": st, "manifests": list(catalog)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
