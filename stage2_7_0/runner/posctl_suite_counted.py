#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""posctl 套件计数 wrapper:pytest 主进程内跑完后读取
ENV_STEP_COUNT/GEN_CALL_COUNT 并按实际值记入预约账本(R1 计量:
测试内环境交互不隐式免计)。
"""

from __future__ import annotations

import argparse
import json

import pytest

import rl_posctl.env as _envmod
import rl_posctl.curriculum as _currmod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ledger", required=True)
    args = ap.parse_args()
    rc = pytest.main([
        "tests/route_c_posctl", "-q", "--no-header",
        "-p", "no:cacheprovider",
        f"--junitxml={args.out}"])
    steps = int(_envmod.ENV_STEP_COUNT)
    gens = int(_currmod.GEN_CALL_COUNT)
    rec = {"env_steps": steps, "gen_calls_module": gens,
           "pytest_rc": int(rc)}
    if args.ledger:
        from rl_posctl.budget import ReservationLedger
        led = ReservationLedger(args.ledger)
        rid = led.reserve("posctl_suite_env_steps", eval_steps=steps)
        led.commit(rid, "posctl_suite_env_steps", eval_steps=steps)
        rec["budget_effective"] = led.effective()
    print("SUITE_COUNTS " + json.dumps(rec))
    return int(rc)


if __name__ == "__main__":
    raise SystemExit(main())
