#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 任务账本显式创建(FiniteRepair R2)。

R2 账本必须由任务身份显式创建(首行 task_bind 绑定预算面);
正常入口读到不存在/无绑定的账本一律拒绝,不自动新建、不自动把
R1 耗尽账本改写为 R2 面(SCOPE_AND_BUDGET)。

用法:
    python posctl_r2_task_ledger.py --init [--path <jsonl>]
    python posctl_r2_task_ledger.py --status [--path <jsonl>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "src"))

from rl_posctl.budget import TaskLedger  # noqa: E402
from rl_posctl.runlog import write_rejection  # noqa: E402
from rl_posctl.versions import POSCTL_R2_TASK_ID  # noqa: E402

DEFAULT_PATH = Path.home() / "posctl_r2_runs" / "r2_task_ledger.jsonl"
BINDING = {
    "task": "RouteC_PositionControl_FiniteRepair_R2",
    "scope": ("SCOPE_AND_BUDGET.md R2 面执行(主Agent/reviewer/新增"
              "测试共享;分项各自生效不可挪额;synthetic_total 派生"
              "总项)"),
    "repo_branch": "route-c-stage2-6-1-repair17",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--path", default=str(DEFAULT_PATH))
    args = ap.parse_args()
    path = Path(args.path)
    if args.init:
        led = TaskLedger.create(path, POSCTL_R2_TASK_ID,
                                binding=BINDING)
        print(json.dumps({"created": str(path),
                          "task_id": POSCTL_R2_TASK_ID,
                          "budget_face": led.limits},
                         ensure_ascii=False, indent=1))
        return 0
    if args.status:
        led = TaskLedger(path, POSCTL_R2_TASK_ID)
        print(json.dumps(led.snapshot(), ensure_ascii=False,
                         indent=1))
        return 0
    write_rejection(path.parent, "posctl_r2_task_ledger",
                    "需要 --init 或 --status 之一", sys.argv)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
