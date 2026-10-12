#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 有界 PPO 接口 smoke(FiniteRepair R2;取代 posctl_smoke_r1)。

R1 缺陷:bank/learn/冷读在预约**之前**已执行(reviewer F1);env 步
计数到末段才入账。R2 顺序(fail closed;单次 learn ≤128 实际步):
  1. 参数校验(steps∈(0,128] 且 batch 整除;账本绑定)→ 拒绝留痕;
  2. 上界先预约:gen(bank 4 + eval 1 + 子进程同 seed 重建 1 = 6 次
     调用/episode)、ppo(1 次 learn×steps)、
  3. RunLog 原字节保全;learn 的 env 步记 ppo(计数器快照差),
     其余交互为零(reset/纯前向不计 env.step);
  4. 冷读:同进程 state_dict 逐张量回读 + 确定性前向对拍;新进程
     同 obs 重建(同 seed 重建计生成,由父进程预先入账);
  5. 实结/异常 abandon。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rl_posctl.env as _envmod  # noqa: E402
from rl_posctl import profiles  # noqa: E402
from rl_posctl.banks import QuotaLedger, domain_seed, episode_seed  # noqa: E402
from rl_posctl.budget import TaskLedger  # noqa: E402
from rl_posctl.curriculum import generate_episode, spec_for  # noqa: E402
from rl_posctl.experiments import (  # noqa: E402
    EpisodeBankEnv, FailureAwareStop, train_course_spec)
from rl_posctl.policy import (  # noqa: E402
    load_posctl_model, make_posctl_ppo, save_posctl_model)
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.series_models import mlp_policy_kwargs  # noqa: E402
from rl_posctl.versions import POSCTL_R2_TASK_ID  # noqa: E402

import torch as th  # noqa: E402

BANK_EPS = 4
EVAL_EPS = 1
COLD_REBUILDS = 1                # 子进程同 seed 重建(计生成)
GEN_UB = BANK_EPS + EVAL_EPS + COLD_REBUILDS


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--steps", type=int, default=128)
    ap.add_argument("--seed", type=int, default=21001)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    out_root = Path(args.out_root)
    ledger_path = Path(args.ledger)

    # ---- 1) 前置校验(零工作叶) ----
    problems = []
    cap = profiles.BUDGET["ppo_steps_single"]
    if not (0 < args.steps <= cap):
        problems.append(f"--steps 必须∈(0,{cap}](预算面单次上限)")
    if not ledger_path.exists():
        problems.append(f"任务账本不存在:{ledger_path}")
    if problems:
        d = write_rejection(out_root, "posctl_r2_smoke",
                            "; ".join(problems), sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    try:
        led = TaskLedger(ledger_path, POSCTL_R2_TASK_ID)
    except RuntimeError as exc:
        d = write_rejection(out_root, "posctl_r2_smoke",
                            f"账本绑定校验失败:{exc}", sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2

    # ---- 2) 上界先预约(持久;崩溃保守保留) ----
    try:
        rid_gen = led.reserve("posctl_r2_smoke_gen",
                              gen_calls=GEN_UB, episodes=GEN_UB)
        rid_ppo = led.reserve("posctl_r2_smoke_ppo",
                              ppo_learn_attempts=1,
                              ppo_steps=int(args.steps))
    except Exception as exc:
        # 预约被拒 = 零工作叶前拒绝(额度不足/超限;留痕不消耗额度)
        d = write_rejection(
            out_root, "posctl_r2_smoke",
            f"预约被拒(先于任何生成/learn):{exc}", sys.argv,
            extra={"ledger_effective": led.effective(),
                   "steps": args.steps, "gen_ub": GEN_UB})
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2

    out_dir = out_root / time.strftime("smoke_%Y%m%dT%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=False)
    quota = QuotaLedger(out_dir / "gen_quota.jsonl", task_ledger=led)
    with RunLog(out_dir, argv=sys.argv,
                meta_extra={"runner": "posctl_r2_smoke",
                            "steps": args.steps}) as rl:
        try:
            spec = train_course_spec(profiles.TRAIN_COURSE,
                                     profiles.MASTER_SEED)
            # bank(生成经任务账本逐次先预约)
            from rl_posctl.experiments import build_train_bank
            bank = build_train_bank(profiles.TRAIN_COURSE,
                                    profiles.MASTER_SEED, BANK_EPS,
                                    quota)
            ds = domain_seed(profiles.MASTER_SEED, "eval")
            eval_bank = []
            for i in range(EVAL_EPS):
                quota.record(gen_calls=1, episodes=1,
                             bank="posctl_r2_eval", domain="eval")
                eval_bank.append(generate_episode(
                    spec, episode_seed(ds, i)))
            env = EpisodeBankEnv(bank, fee=spec.fee, window_size=1)
            model = make_posctl_ppo(
                env, policy_kwargs=mlp_policy_kwargs(128),
                seed=args.seed, n_steps=int(args.steps),
                batch_size=min(128, int(args.steps)),
                n_epochs=profiles.N_EPOCHS, gamma=profiles.GAMMA,
                ent_coef=profiles.ENT_COEF, device=args.device)
            stop = FailureAwareStop()
            t0 = time.time()
            env_before = int(_envmod.ENV_STEP_COUNT)
            model.learn(total_timesteps=int(args.steps),
                        callback=stop.cb)
            actual_steps = int(model.num_timesteps)
            env_during_learn = int(_envmod.ENV_STEP_COUNT) - env_before
            elapsed = time.time() - t0
            # learn 的 env 步实结为 ppo(分类正确;实耗 ≤ 预约)
            led.commit(rid_ppo, "posctl_r2_smoke_ppo",
                       ppo_learn_attempts=1,
                       ppo_steps=int(actual_steps))
            save_posctl_model(model, out_dir / "smoke.zip")
            # ---- 冷读(同进程) ----
            m2 = load_posctl_model(out_dir / "smoke.zip", env)
            sd1 = model.policy.state_dict()
            sd2 = m2.policy.state_dict()
            state_parity = (set(sd1) == set(sd2)) and all(
                bool(th.equal(sd1[k], sd2[k])) for k in sd1)
            obs = env.reset()[0]
            with th.no_grad():
                a0, _, _ = model.policy(th.as_tensor(
                    obs, dtype=th.float32).unsqueeze(0),
                    deterministic=True)
                a1, _, _ = m2.policy(th.as_tensor(
                    obs, dtype=th.float32).unsqueeze(0),
                    deterministic=True)
            same_proc_parity = bool(th.equal(a0, a1)) and state_parity
            # 父进程基准 obs:eval 集 0(子进程同 seed 重建)
            from rl_posctl.env import HybridPositionEnv as _HPE
            p0, f0, _ = eval_bank[0]
            _env0 = _HPE(features=f0, prices=p0, fee=spec.fee,
                         window_size=1)
            obs0 = th.as_tensor(_env0.reset()[0],
                                dtype=th.float32).unsqueeze(0)
            with th.no_grad():
                a0b, _, _ = model.policy(obs0, deterministic=True)
            parent_action = [float(x) for x in a0b[0]]
            # ---- 子进程冷读前的重建预约(同 seed 重建计生成) ----
            quota.record(gen_calls=1, episodes=1,
                         bank="posctl_r2_cold_rebuild", domain="eval")
            import rl_posctl as _rp
            src = str(Path(_rp.__file__).resolve().parent.parent)
            code = (
                "import json,sys\n"
                "import torch as th\n"
                "from rl_posctl.policy import load_posctl_model\n"
                "spec=json.load(open({sp!r}))\n"
                "import numpy as np\n"
                "from rl_posctl.curriculum import (generate_episode,"
                " spec_for)\n"
                "from rl_posctl.banks import episode_seed, "
                "domain_seed\n"
                "from rl_posctl import profiles\n"
                "sp=spec_for(profiles.TRAIN_COURSE, "
                "seed=profiles.MASTER_SEED, horizon=64, "
                "**profiles.TRAIN_SPEC_OVERRIDES)\n"
                "prices, feats, _ = generate_episode(sp, "
                "episode_seed(domain_seed(profiles.MASTER_SEED,"
                "'eval'),0))\n"
                "from rl_posctl.env import HybridPositionEnv\n"
                "env=HybridPositionEnv(features=feats, prices=prices,"
                " fee=sp.fee, window_size=1)\n"
                "m=load_posctl_model(spec['path'], env)\n"
                "o=th.as_tensor(env.reset()[0],dtype=th.float32)"
                ".unsqueeze(0)\n"
                "with th.no_grad():\n"
                "    a,v,lp=m.policy(o, deterministic=True)\n"
                "print(json.dumps({{'action':[float(x) for x in "
                "a[0]]}}))\n"
            )
            spec_path = out_dir / "cold_spec.json"
            spec_path.write_text(json.dumps(
                {"path": str(out_dir / "smoke.zip")}),
                encoding="utf-8")
            script = out_dir / "cold_load.py"
            script.write_text(code.format(sp=str(spec_path)),
                              encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(script)], capture_output=True,
                text=True, timeout=600,
                env={**os.environ, "PYTHONPATH": src,
                     "PYTHONDONTWRITEBYTECODE": "1"})
            new_proc = {"rc": r.returncode,
                        "stdout": r.stdout.strip()[-400:],
                        "stderr": r.stderr.strip()[-400:]}
            if r.returncode == 0:
                got = json.loads(
                    r.stdout.strip().splitlines()[-1])
                new_proc["action"] = got["action"]
                new_proc["parent_deterministic_action"] = parent_action
                new_proc["deterministic_parity"] = bool(
                    got["action"] == parent_action)
            # ---- 生成实结 ----
            gen_actual = quota.gen_calls
            led.commit(rid_gen, "posctl_r2_smoke_gen",
                       gen_calls=gen_actual, episodes=gen_actual)
            # 冷载次数单列(纯前向;不隐含 env.step/重生成)
            rec = {
                "run": "posctl_r2_smoke",
                "steps_requested": int(args.steps),
                "steps_actual": actual_steps,
                "env_steps_during_learn": env_during_learn,
                "elapsed_s": round(elapsed, 2),
                "status": "RUN_INVALID" if stop.failure else "OK",
                "economic_failure": stop.failure,
                "same_process_cold_load_parity": same_proc_parity,
                "state_dict_parity": state_parity,
                "new_process_cold_load": new_proc,
                "cold_load_forward_count": 3,
                "gen_quota_cum": {"gen_calls": quota.gen_calls,
                                  "episodes": quota.episodes},
                "budget_snapshot": led.snapshot(),
            }
            (out_dir / "smoke_record.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=1),
                encoding="utf-8")
            print(json.dumps(rec, ensure_ascii=False, indent=1))
            rl.rc = 0 if (same_proc_parity and state_parity
                          and r.returncode == 0
                          and new_proc.get("deterministic_parity")
                          and not stop.failure) else 1
            return rl.rc
        except BaseException as exc:
            led.abandon(rid_ppo, "posctl_r2_smoke",
                        note=f"learn 异常中止(保守保留):{exc!r}")
            led.abandon(rid_gen, "posctl_r2_smoke",
                        note=f"生成异常中止(保守保留):{exc!r}")
            raise


if __name__ == "__main__":
    raise SystemExit(main())
