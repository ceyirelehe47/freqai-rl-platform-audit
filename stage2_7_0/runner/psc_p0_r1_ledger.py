#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 任务账本(显式创建/状态;create-only)。

R1 面 = POSCTL_PSC_P0_R1_BUDGET(有限工程验证额度;零上限键显式
fail closed)。主 Agent、reviewer 与全部 R1 runner 共用同一账本文件;
旧 P0 账本只读关联,不退回/不重置。

用法:
    python psc_p0_r1_ledger.py --init [--ledger <jsonl>]
    python psc_p0_r1_ledger.py --status [--ledger <jsonl>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl.budget import TaskLedger  # noqa: E402
from rl_posctl.versions import (  # noqa: E402
    POSCTL_PSC_P0_R1_TASK_ID)

R1_ROOT = Path("/mnt/f/trading/acceptance/PSC_P0_R1_20261014")
DEFAULT_LEDGER = R1_ROOT / "runs" / "psc_p0_r1_ledger.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    args = ap.parse_args()
    if not (args.init or args.status):
        print("需要 --init 或 --status", file=sys.stderr)
        return 2
    if args.init:
        Path(args.ledger).parent.mkdir(parents=True, exist_ok=True)
        led = TaskLedger.create(
            args.ledger, POSCTL_PSC_P0_R1_TASK_ID,
            binding={"round": "PSC_P0_v1_FiniteRepair_R1",
                     "runbook": "RUNBOOK_AND_BUDGET.md 表(2026-10-14)",
                     "scope": ("F1-F3 有限工程修复的唯一小额验证额度;"
                               "主Agent/reviewer/测试共用;"
                               "旧 P0 账本只读关联")})
        print(json.dumps({"created": str(args.ledger),
                          "task_id": led.task_id},
                         ensure_ascii=False))
    snap = TaskLedger(args.ledger, POSCTL_PSC_P0_R1_TASK_ID).snapshot()
    print(json.dumps(snap, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
