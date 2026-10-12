#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 计数套件 wrapper(FiniteRepair R2 / FINDINGS R2-01)。

R1 缺陷(posctl_suite_counted.py):pytest.main 已返回后才预约——
套件工作已发生,门禁形同虚设(reviewer 反例:预置 76,432 的账本在
pytest 替身执行一次后才拒绝新增 5 步)。

R2 顺序(fail closed,全部工作叶之前):
  1. 校验参数(账本存在且绑定 R2 任务;上限为正整数;上限 ≤ 剩余
     预算面)——任何拒绝写 rejected_* 目录,零额度消耗;
  2. **先预约**整套件的上限(eval_steps/gen_calls;持久,崩溃保守
     保留全额);
  3. 进程内跑 pytest.main(套件内 learn 经 conftest r2_learn 精确
     记 ppo,登记 suite_ppo_registry.jsonl);
  4. 结算:eval 实耗 = 进程计数 − 会话 ppo 步(不双计);实耗超
     预约即 fail closed 抛出(不事后扩约);提交实耗;
  5. 输出 SUITE_COUNTS(原字节含在 RunLog 的 run_output.raw.txt)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

import rl_posctl.curriculum as _currmod  # noqa: E402
import rl_posctl.env as _envmod  # noqa: E402
from rl_posctl.budget import TaskLedger  # noqa: E402
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.versions import POSCTL_R2_TASK_ID  # noqa: E402


def _session_ppo(ledger_path: Path) -> dict:
    reg = ledger_path.parent / "suite_ppo_registry.jsonl"
    ppo_steps = 0
    attempts = 0
    if reg.exists():
        for line in reg.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                ppo_steps += int(rec.get("ppo_steps", 0))
                attempts += int(rec.get("learn_attempts", 0))
    return {"ppo_steps": ppo_steps, "learn_attempts": attempts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--junit", required=True)
    ap.add_argument("--cap-eval", type=int, default=26_000,
                    help="整套件无梯度 env 步预约上限(须 ≥ 实耗)")
    ap.add_argument("--cap-gen", type=int, default=900,
                    help="整套件生成调用预约上限(须 ≥ 实耗)")
    ap.add_argument("--pytest-args", default="")
    args = ap.parse_args()
    out_root = Path(args.out_root)
    ledger_path = Path(args.ledger)

    # ---- 1) 前置校验(任何工作之前;拒绝留痕零额度) ----
    problems = []
    if not ledger_path.exists():
        problems.append(f"任务账本不存在:{ledger_path}"
                        "(由 posctl_r2_task_ledger.py --init 创建)")
    if args.cap_eval <= 0 or args.cap_gen <= 0:
        problems.append("cap-eval/cap-gen 必须为正整数")
    if problems:
        d = write_rejection(out_root, "posctl_r2_suite",
                            "; ".join(problems), sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    try:
        led = TaskLedger(ledger_path, POSCTL_R2_TASK_ID)
    except RuntimeError as exc:
        d = write_rejection(out_root, "posctl_r2_suite",
                            f"账本绑定校验失败:{exc}", sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2

    out_dir = out_root / time.strftime("suite_%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=False)
    with RunLog(out_dir, argv=sys.argv,
                meta_extra={"runner": "posctl_r2_suite"}) as rl:
        # ---- 2) 先预约(整套件上限;崩溃保守保留;被拒=pytest 前) ----
        try:
            rid = led.reserve(
                "posctl_r2_suite_blanket",
                eval_steps=int(args.cap_eval),
                gen_calls=int(args.cap_gen))
        except Exception as exc:
            d = write_rejection(
                out_root, "posctl_r2_suite",
                f"套件预约被拒(先于 pytest):{exc}", sys.argv,
                extra={"ledger_effective": led.effective(),
                       "cap_eval": args.cap_eval,
                       "cap_gen": args.cap_gen})
            print(f"REJECTED {d}/rejection.json", flush=True)
            rl.rc = 2
            return 2
        rl.rc = None
        # ---- 3) 进程内 pytest(先校验和预占后执行) ----
        pytest_argv = [
            "tests/route_c_posctl", "-q", "--no-header",
            "-p", "no:cacheprovider",
            f"--junitxml={args.junit}"]
        if args.pytest_args:
            import shlex
            pytest_argv.extend(shlex.split(args.pytest_args))
        rc = int(pytest.main(pytest_argv))
        # ---- 4) 结算(实耗 ≤ 预约;分类不双计) ----
        env_total = int(_envmod.ENV_STEP_COUNT)
        gen_total = int(_currmod.GEN_CALL_COUNT)
        sess = _session_ppo(ledger_path)
        eval_actual = env_total - sess["ppo_steps"]
        gen_actual = gen_total
        rec = {
            "run": "posctl_r2_suite",
            "env_steps_total": env_total,
            "session_ppo": sess,
            "eval_steps_actual": eval_actual,
            "gen_calls_module": gen_actual,
            "pytest_rc": rc,
            "cap_eval": int(args.cap_eval),
            "cap_gen": int(args.cap_gen),
            "run_id": rl.run_id,
        }
        try:
            led.commit(rid, "posctl_r2_suite_blanket",
                       eval_steps=eval_actual,
                       gen_calls=gen_actual)
            rec["committed"] = True
        except Exception as exc:      # 实耗>预约 = 违规,fail closed
            rec["committed"] = False
            rec["commit_error"] = repr(exc)
            print("SUITE_COUNTS " + json.dumps(rec), flush=True)
            raise
        rec["budget_effective"] = led.effective()
        rec["budget_snapshot"] = led.snapshot()
        (out_dir / "suite_record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print("SUITE_COUNTS " + json.dumps(rec), flush=True)
        rl.rc = rc
        return rc


if __name__ == "__main__":
    raise SystemExit(main())
