#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2/R3 计数套件 wrapper(FiniteRepair R2→R3)。

R1 缺陷(posctl_suite_counted.py):pytest.main 已返回后才预约——
套件工作已发生,门禁形同虚设。R2 顺序(fail closed,工作叶之前):
  1. 校验参数(账本存在且绑定;上限为正整数)→ 拒绝写 rejected_*
     目录,零额度消耗;
  2. **先预约**整套件的上限(eval_steps/gen_calls;持久,崩溃
     保守保留全额);
  3. 进程内跑 pytest.main(套件内 learn 经 conftest r2_learn 精确
     记 ppo,登记 suite_ppo_registry.jsonl);
  4. 结算:eval 实耗 = 进程计数 − 会话 ppo 步(不双计);实耗超
     预约即 fail closed 抛出(不事后扩约);提交实耗;
  5. 输出 SUITE_COUNTS(原字节含在 RunLog 的 run_output.raw.txt)。

R3(FiniteRepair R3 / R3-01,reviewer F1-c/F1-d):
- **全部参数预约前解析**:--pytest-args shlex 语法错、--junit 路径
  父目录不可写、pytest 参数内嵌 --junitxml 冲突,均在预约前拒绝;
- **测试环境账本一致或先拒绝**:POSCTL_R{2,3}_LEDGER 环境变量若
  指向别的账本 → 拒绝;未设置 → 由本 wrapper 注入 --ledger 同一
  路径(测试不得部分有账本部分无账本地跑);
- **执行中硬限**:pytest 前设置 env.ENV_STEP_LIMIT /
  curriculum.GEN_CALL_LIMIT(= 调用方上限;learn 步按 ppo 豁免),
  超限的工作叶在执行前被截停——cap=1 时第二叶不执行,不是 commit
  结算时才发现;套件结束恢复不限,不外泄到后续运行;
- 账本按头部任务身份打开(R2/R3 面均可),预约走该任务面。
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402

import rl_posctl.curriculum as _currmod  # noqa: E402
import rl_posctl.env as _envmod  # noqa: E402
from rl_posctl.budget import open_task_ledger  # noqa: E402
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402

LEDGER_ENV_VARS = ("POSCTL_R3_LEDGER", "POSCTL_R2_LEDGER")


def _registry_len(ledger_path: Path) -> int:
    reg = ledger_path.parent / "suite_ppo_registry.jsonl"
    if not reg.exists():
        return 0
    return sum(1 for line in reg.read_text(
        encoding="utf-8").splitlines() if line.strip())


def _session_ppo(ledger_path: Path, since_line: int = 0) -> dict:
    """本套件 run 的 ppo 分类(F1 修复:只计 since_line 之后的
    注册表行——跨 run 累计注册表不得把别的 run 的 ppo 步读成
    本 run 的豁免/分类)。"""
    reg = ledger_path.parent / "suite_ppo_registry.jsonl"
    ppo_steps = attempts = 0
    if reg.exists():
        for line in reg.read_text(
                encoding="utf-8").splitlines()[since_line:]:
            if not line.strip():
                continue
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
                    help="整套件无梯度 env 步授权上限(执行中硬限)")
    ap.add_argument("--cap-gen", type=int, default=900,
                    help="整套件生成调用授权上限(执行中硬限)")
    ap.add_argument("--pytest-args", default="")
    args = ap.parse_args()
    out_root = Path(args.out_root)
    ledger_path = Path(args.ledger)
    junit_path = Path(args.junit)

    # ---- 1) 前置校验(R3:全部参数预约前解析;零额度) ----
    problems = []
    if not ledger_path.exists():
        problems.append(f"任务账本不存在:{ledger_path}"
                        "(由 posctl_r{2,3}_task_ledger.py --init 创建)")
    if args.cap_eval < 0 or args.cap_gen < 0:
        problems.append("cap-eval/cap-gen 必须为非负整数"
                        "(0=本批不授权该类工作;额度面剩余不足时"
                        "按 0 分批)")
    # R3-01/F1-d:pytest 参数 shlex 语法在预约前解析
    try:
        extra_argv = (shlex.split(args.pytest_args)
                      if args.pytest_args else [])
    except ValueError as exc:
        problems.append(f"--pytest-args shlex 语法错误:{exc}")
        extra_argv = []
    for a in extra_argv:
        if a.startswith("--junitxml"):
            problems.append(
                "--pytest-args 内嵌 --junitxml 与 --junit 冲突;"
                "junit 路径由 wrapper 统一管理")
    # junit 输出路径可写性(父目录存在或可创建;文件不得已存在=不覆盖)
    if junit_path.exists():
        problems.append(f"--junit 输出已存在,拒绝覆盖:{junit_path}")
    else:
        try:
            junit_path.parent.mkdir(parents=True, exist_ok=True)
            probe = junit_path.parent / ".suite_probe_write"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(f"--junit 路径不可写:{exc}")
    # R3-01:测试环境所用账本必须与 --ledger 一致或先拒绝
    for var in LEDGER_ENV_VARS:
        v = os.environ.get(var, "").strip()
        if v and Path(v) != ledger_path:
            problems.append(
                f"环境变量 {var}={v} 与 --ledger {ledger_path} 不一致"
                ";测试账本必须与套件授权同一账本,拒绝(不部分无预算"
                "运行)")
    if problems:
        d = write_rejection(out_root, "posctl_r2_suite",
                            "; ".join(problems), sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    try:
        led = open_task_ledger(ledger_path)
    except RuntimeError as exc:
        d = write_rejection(out_root, "posctl_r2_suite",
                            f"账本绑定校验失败:{exc}", sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    # 注入与账本任务面匹配的环境变量(conftest 读同一账本)
    env_var = ("POSCTL_R3_LEDGER"
               if led.task_id.endswith("R3_20261013")
               else "POSCTL_R4_LEDGER" if led.task_id.endswith(
                   "R4_20261013")
               else "POSCTL_R2_LEDGER")
    os.environ[env_var] = str(ledger_path)

    out_dir = out_root / time.strftime("suite_%Y%m%dT%H%M%S")
    if out_dir.exists():
        d = write_rejection(out_root, "posctl_r2_suite",
                            f"运行目录已存在:{out_dir}", sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    out_dir.mkdir(parents=True, exist_ok=False)
    with RunLog(out_dir, argv=sys.argv,
                meta_extra={"runner": "posctl_r2_suite"}) as rl:
        # ---- 2) 先预约(整套件上限;崩溃保守保留;被拒=pytest 前)
        reg_before = _registry_len(ledger_path)
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
        # ---- 3) 执行中硬限(R3:cap 之内的工作才发生) ----
        base_eval_used = (int(_envmod.ENV_STEP_COUNT)
                          - int(_envmod.PPO_EXEMPT_STEPS))
        _envmod.ENV_STEP_LIMIT = base_eval_used + int(args.cap_eval)
        gen0 = int(_currmod.GEN_CALL_COUNT)
        _currmod.GEN_CALL_LIMIT = gen0 + int(args.cap_gen)
        try:
            # ---- 进程内 pytest(先校验/预占/硬限后执行) ----
            # 显式路径目标(--pytest-args 提供测试文件)时不再追加
            # 默认目录(batchA1 教训:目录+文件叠加=跑全目录)。
            _OPTION_FLAGS = {"-k", "-m", "-x", "--maxfail",
                             "--junitxml", "--timeout",
                             "--deselect", "-p", "--rootdir"}
            has_target = any(
                not a.startswith("-")
                and (i == 0 or extra_argv[i - 1]
                     not in _OPTION_FLAGS)
                for i, a in enumerate(extra_argv))
            base_argv = ([f"--junitxml={args.junit}", "-q",
                          "--no-header", "-p", "no:cacheprovider"]
                         + (["tests/route_c_posctl"]
                            if not has_target else []))
            rc = int(pytest.main(base_argv + extra_argv))
        finally:
            _envmod.ENV_STEP_LIMIT = None
            _currmod.GEN_CALL_LIMIT = None
        # ---- 4) 结算(实耗 ≤ 预约;分类不双计) ----
        env_total = int(_envmod.ENV_STEP_COUNT)
        gen_total = int(_currmod.GEN_CALL_COUNT)
        sess = _session_ppo(ledger_path, since_line=reg_before)
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
