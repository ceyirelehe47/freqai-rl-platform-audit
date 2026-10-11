#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""W2/W5 正确性 smoke + 容量/时序 pilot 主执行器。

阶段(--stage):
- smoke:8×2048=16,384 步真实新接口 PPO 更新/重载预算(跨设备
  小规模冒烟;失败也计入);
- capacity:4 宽度 × 3 seed × 65,536(CPU;预注册配置);
- series:窗口 MLP-16 与 LSTM-16 × 3 seed × 32,768(CPU)。
全部 ENGINEERING_ONLY;经济失败 -> RUN_INVALID 停止不重抽。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rl_posctl import profiles
from rl_posctl.banks import QuotaLedger
from rl_posctl.experiments import (
    build_train_bank, count_params, run_pilot)
from rl_posctl.policy import make_posctl_ppo
from rl_posctl.series_models import lstm_policy_kwargs, \
    mlp_policy_kwargs

RUNNER_ROOT = Path("/home/cryptorl/projects/crypto_rl")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True,
                    choices=["smoke", "capacity", "series",
                             "params"])
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()
    out_root = Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    ledger = profiles.UsageLedger(out_root / "usage_ledger.jsonl")
    quota = QuotaLedger(out_root / "gen_quota.jsonl")

    if args.stage == "params":
        # 6 候选的逐参数统计(不训练;实际模型读取)
        from rl_posctl.curriculum import CourseSpec, \
            generate_episode
        spec = CourseSpec(course=profiles.TRAIN_COURSE,
                          seed=profiles.MASTER_SEED)
        prices, feats, _ = generate_episode(spec, 12345)
        from rl_posctl.env import HybridPositionEnv
        rows = []
        for w in profiles.MLP_WIDTHS:
            env = HybridPositionEnv(
                features=feats, prices=prices, fee=spec.fee,
                window_size=1)
            m = make_posctl_ppo(
                env, policy_kwargs=mlp_policy_kwargs(w), seed=1001,
                device="cpu")
            rows.append({"candidate": f"mlp_{w}_w1",
                         **count_params(m),
                         "obs_dim": int(env.observation_space.shape[0])})
        for name, kw, win in (
                ("window_mlp_128_w16", mlp_policy_kwargs(128), 16),
                ("lstm_128_w16", lstm_policy_kwargs(
                    env_obs_features(spec)), 16)):
            env16 = HybridPositionEnv(
                features=feats, prices=prices, fee=spec.fee,
                window_size=16)
            m = make_posctl_ppo(
                env16, policy_kwargs=kw, seed=1001, device="cpu")
            rows.append({"candidate": name, **count_params(m),
                         "obs_dim": int(
                             env16.observation_space.shape[0])})
        (out_root / "param_stats.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0

    window = 1
    lstm = args.stage == "series"
    if lstm:
        window = 16
    bank = build_train_bank(
        profiles.TRAIN_COURSE, profiles.MASTER_SEED,
        profiles.TRAIN_BANK_EPISODES, quota, window=window)

    if args.stage == "smoke":
        recs = []
        for i in range(8):
            kw = mlp_policy_kwargs(128)
            r = run_pilot(
                name=f"smoke_{i}", course=profiles.TRAIN_COURSE,
                window=1, policy_kwargs=kw, seed=2000 + i,
                total_steps=profiles.ROLLOUT, bank=bank,
                master_seed=profiles.MASTER_SEED,
                out_dir=out_root / "smoke", ledger=ledger,
                device=args.device)
            recs.append(r)
            if r["status"] != "OK":
                break
        print(json.dumps(recs, ensure_ascii=False, indent=1))
        return 0

    if args.stage == "capacity":
        recs = []
        for w in profiles.MLP_WIDTHS:
            for seed in profiles.MODEL_SEEDS:
                recs.append(run_pilot(
                    name=f"mlp{w}_s{seed}",
                    course=profiles.TRAIN_COURSE, window=1,
                    policy_kwargs=mlp_policy_kwargs(w), seed=seed,
                    total_steps=profiles.CAPACITY_STEPS, bank=bank,
                    master_seed=profiles.MASTER_SEED,
                    out_dir=out_root / "capacity", ledger=ledger,
                    device=args.device))
        (out_root / "capacity" / "all_records.json").write_text(
            json.dumps(recs, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps(recs, ensure_ascii=False, indent=1))
        return 0

    if args.stage == "series":
        n_feat = env_obs_features(None)
        recs = []
        for name, kw in (
                ("wmlp16",
                 mlp_policy_kwargs(128)),
                ("lstm16", lstm_policy_kwargs(n_feat))):
            for seed in profiles.MODEL_SEEDS:
                recs.append(run_pilot(
                    name=f"{name}_s{seed}",
                    course=profiles.TRAIN_COURSE, window=16,
                    policy_kwargs=kw, seed=seed,
                    total_steps=profiles.SERIES_STEPS, bank=bank,
                    master_seed=profiles.MASTER_SEED,
                    out_dir=out_root / "series", ledger=ledger,
                    device=args.device))
        (out_root / "series" / "all_records.json").write_text(
            json.dumps(recs, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps(recs, ensure_ascii=False, indent=1))
        return 0
    return 0


def env_obs_features(_spec) -> int:
    """课程特征维数(生成器固定 5 列:s/c/q/g/q_step)。"""
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
