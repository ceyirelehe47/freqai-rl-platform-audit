#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 有界 PPO smoke:预约→bank→learn(≤2,048)→保存→同进程/新进程
冷读对拍。全部消耗走 ReservationLedger(执行前预约,fail closed);
运行目录 create-only。ENGINEERING_ONLY,不做学习结论。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from rl_posctl import profiles
from rl_posctl.banks import QuotaLedger, domain_seed, episode_seed
from rl_posctl.budget import ReservationLedger, create_only_dir
from rl_posctl.curriculum import spec_for
import rl_posctl.env as _envmod
from rl_posctl.env import HybridPositionEnv
from rl_posctl.experiments import (
    EpisodeBankEnv, FailureAwareStop, build_train_bank,
    train_course_spec)
from rl_posctl.policy import (
    load_posctl_model, make_posctl_ppo, save_posctl_model)
from rl_posctl.series_models import mlp_policy_kwargs

import torch as th


def main() -> int:
    import os as _os
    if _os.environ.get("POSCTL_ALLOW_LEGACY_R1") != "1":
        print("REFUSED: R1 入口已被 R2 取代(bank/learn 先于预约;"
              "R2 用 posctl_r2_smoke.py);如确需复跑历史入口设 "
              "POSCTL_ALLOW_LEGACY_R1=1 显式确认", flush=True)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--steps", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=2001)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    out_dir = create_only_dir(
        Path(args.out_root) /
        time.strftime("smoke_%Y%m%dT%H%M%S"))
    ledger = ReservationLedger(Path(args.ledger))
    quota = QuotaLedger(out_dir / "gen_quota.jsonl")
    spec = train_course_spec(profiles.TRAIN_COURSE,
                             profiles.MASTER_SEED)
    bank = build_train_bank(profiles.TRAIN_COURSE,
                            profiles.MASTER_SEED, 8, quota)
    eval_bank = []
    ds = domain_seed(profiles.MASTER_SEED, "eval")
    for i in range(4):
        quota.record(gen_calls=1, episodes=1,
                     bank="posctl_r1_eval", domain="eval")
        from rl_posctl.curriculum import generate_episode
        eval_bank.append(generate_episode(
            spec, episode_seed(ds, i)))
    env = EpisodeBankEnv(bank, fee=spec.fee, window_size=1)
    model = make_posctl_ppo(
        env, policy_kwargs=mlp_policy_kwargs(128), seed=args.seed,
        n_steps=profiles.ROLLOUT, batch_size=profiles.BATCH,
        n_epochs=profiles.N_EPOCHS, gamma=profiles.GAMMA,
        ent_coef=profiles.ENT_COEF, device=args.device)
    stop = FailureAwareStop()
    rid = ledger.reserve("smoke_r1", ppo_learn_attempts=1,
                         ppo_steps=int(args.steps))
    t0 = time.time()
    model.learn(total_timesteps=int(args.steps),
                callback=stop.cb)
    actual = int(model.num_timesteps)
    ledger.commit(rid, "smoke_r1", ppo_learn_attempts=1,
                  ppo_steps=actual)
    elapsed = time.time() - t0
    save_posctl_model(model, out_dir / "smoke.zip")
    # 同进程冷读对拍(确定性口径):
    # 1) 权重逐张量回读一致(冷载等价的实质);
    # 2) deterministic=True(分布 mode,无采样)输出一致——
    #    随机 forward 是两次独立抽样,结构上不可能相等,不得
    #    用作对拍(reviewer 反例修正)。
    m2 = load_posctl_model(out_dir / "smoke.zip", env)
    sd1 = model.policy.state_dict()
    sd2 = m2.policy.state_dict()
    state_parity = (set(sd1) == set(sd2)) and all(
        bool(th.equal(sd1[k], sd2[k])) for k in sd1)
    obs = env.reset()[0]
    with th.no_grad():
        a0, _, _ = model.policy(th.as_tensor(
            obs, dtype=th.float32).unsqueeze(0), deterministic=True)
        a1, _, _ = m2.policy(th.as_tensor(
            obs, dtype=th.float32).unsqueeze(0), deterministic=True)
    same_proc_parity = bool(th.equal(a0, a1)) and state_parity
    # 父进程基线必须与子进程同 obs:eval bank 第 0 集(子进程
    # 用同一确定性种子域构造)
    from rl_posctl.env import HybridPositionEnv as _HPE
    p0, f0, _ = eval_bank[0]
    _env0 = _HPE(features=f0, prices=p0, fee=spec.fee,
                 window_size=1)
    obs0 = th.as_tensor(_env0.reset()[0],
                        dtype=th.float32).unsqueeze(0)
    with th.no_grad():
        a0b, _, _ = model.policy(obs0, deterministic=True)
    parent_action = [float(x) for x in a0b[0]]
    # 新进程冷读(独立解释器;PYTHONPATH 指向被测源)
    import rl_posctl as _rp
    src = str(Path(_rp.__file__).resolve().parent.parent)
    code = (
        "import json,sys\n"
        "import torch as th\n"
        "from rl_posctl.policy import load_posctl_model\n"
        "spec=json.load(open({sp!r}))\n"
        "import numpy as np, pandas as pd\n"
        "from rl_posctl.curriculum import (generate_episode, "
        "spec_for)\n"
        "from rl_posctl.banks import episode_seed, domain_seed\n"
        "from rl_posctl import profiles\n"
        "sp=spec_for(profiles.TRAIN_COURSE, "
        "seed=profiles.MASTER_SEED, horizon=64, "
        "**profiles.TRAIN_SPEC_OVERRIDES)\n"
        "prices, feats, _ = generate_episode(sp, "
        "episode_seed(domain_seed(profiles.MASTER_SEED,'eval'),0))\n"
        "from rl_posctl.env import HybridPositionEnv\n"
        "env=HybridPositionEnv(features=feats, prices=prices, "
        "fee=sp.fee, window_size=1)\n"
        "m=load_posctl_model(spec['path'], env)\n"
        "o=th.as_tensor(env.reset()[0],dtype=th.float32)"
        ".unsqueeze(0)\n"
        "with th.no_grad():\n"
        "    a,v,lp=m.policy(o, deterministic=True)\n"
        "print(json.dumps({{'action':[float(x) for x in a[0]]}}))\n"
    )
    spec_path = out_dir / "cold_spec.json"
    spec_path.write_text(json.dumps(
        {"path": str(out_dir / "smoke.zip")}), encoding="utf-8")
    script = out_dir / "cold_load.py"
    script.write_text(code.format(sp=str(spec_path)),
                      encoding="utf-8")
    import os
    r = subprocess.run(
        [sys.executable, str(script)], capture_output=True,
        text=True, timeout=600,
        env={**os.environ, "PYTHONPATH": src,
             "PYTHONDONTWRITEBYTECODE": "1"})
    new_proc = {"rc": r.returncode,
                "stdout": r.stdout.strip()[-400:],
                "stderr": r.stderr.strip()[-400:]}
    if r.returncode == 0:
        got = json.loads(r.stdout.strip().splitlines()[-1])
        new_proc["action"] = got["action"]
        new_proc["parent_deterministic_action"] = parent_action
        # 子进程确定性输出 == 父进程同一 obs 的确定性输出
        new_proc["deterministic_parity"] = bool(
            got["action"] == parent_action)
    # 评估步计费(env 计数差 = 本进程全部交互,保守记 eval_steps)
    env_steps = int(_envmod.ENV_STEP_COUNT)
    rid2 = ledger.reserve("smoke_r1_env_steps",
                          eval_steps=env_steps)
    ledger.commit(rid2, "smoke_r1_env_steps",
                  eval_steps=env_steps)
    rec = {
        "run": "smoke_r1", "steps_requested": int(args.steps),
        "steps_actual": actual, "elapsed_s": round(elapsed, 2),
        "status": "RUN_INVALID" if stop.failure else "OK",
        "economic_failure": stop.failure,
        "same_process_cold_load_parity": same_proc_parity,
        "new_process_cold_load": new_proc,
        "env_steps_total": env_steps,
        "budget_snapshot": ledger.snapshot(),
        "gen_quota_cum": {"gen_calls": quota.gen_calls,
                          "episodes": quota.episodes},
    }
    (out_dir / "smoke_record.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    rec["state_dict_parity"] = state_parity
    (out_dir / "smoke_record.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0 if (same_proc_parity and state_parity
                 and r.returncode == 0
                 and new_proc.get("deterministic_parity")
                 and not stop.failure) else 1


if __name__ == "__main__":
    raise SystemExit(main())
