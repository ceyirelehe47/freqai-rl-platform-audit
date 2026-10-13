#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 任务账本显式创建/状态(镜像 posctl_r3_task_ledger 模式)。

账本必须由任务身份显式创建(首行 task_bind 绑定 PSC_P0_v1 预算面);
旧 R1–R5 账本只读,不自动新建、不改写为 P0 面。

用法:
    python psc_p0_task_ledger.py --init [--path <jsonl>]
    python psc_p0_task_ledger.py --status [--path <jsonl>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl.budget import TaskLedger  # noqa: E402
from rl_posctl.runlog import write_rejection  # noqa: E402
from rl_posctl.skill_p0.p0run import DEFAULT_LEDGER  # noqa: E402
from rl_posctl.skill_p0.p0spec import TASK_ID  # noqa: E402

BINDING = {
    "task": "RouteC_ProgressiveSkillCurriculum_P0_v1",
    "scope": ("本包 SCOPE_AND_BUDGET P0 面执行(主Agent/reviewer/测试/"
              "失败中断共享;分项独立生效不可挪额;派生总项 ppo_total="
              "854,016/learn_total=12/economic_total=1,378,304;不另开"
              "账本绕开总量;旧 R1–R5 账本只读不作为余额来源)"),
    "repo_branch": "route-c-stage2-6-1-repair17",
    "package_sha256": "e213a79be3a6fc27fa5ad1f3d8d5617cf655f6c9e2"
                      "720085b40a93dae6a3aacc",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--path", default=str(DEFAULT_LEDGER))
    args = ap.parse_args()
    path = Path(args.path)
    if args.init:
        led = TaskLedger.create(path, TASK_ID, binding=BINDING)
        print(json.dumps({"created": str(path), "task_id": TASK_ID,
                          "budget_face": led.limits},
                         ensure_ascii=False, indent=1))
        return 0
    if args.status:
        led = TaskLedger(path, TASK_ID)
        print(json.dumps(led.snapshot(), ensure_ascii=False, indent=1))
        return 0
    write_rejection(path.parent, "psc_p0_task_ledger",
                    "需要 --init 或 --status 之一", sys.argv)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
