#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BC 表达能力诊断(可选额度:≤4 fit;本轮 1 次,≤20 epoch)。

目的:分层结论——PPO 评估平坦收缩时,用监督信号判断网络**能否
表达**参考行为(分支/目标),以区分"表达能力不足"与"优化/信号
不足"。真实标签只走本诊断入口,不进入 PPO 环境或奖励。
数据:train 域 bank(与 pilot 同源同序);标签 = reference_action
(只读当前可观察特征行 + 当前比例)。指标:branch 准确率、
REBALANCE 行的目标均值 E[w] MAE、平均 log-prob。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch as th

from rl_posctl import profiles
from rl_posctl.banks import QuotaLedger, domain_seed, episode_seed
from rl_posctl.curriculum import CourseSpec, reference_action, \
    generate_episode
from rl_posctl.env import HybridPositionEnv
from rl_posctl.policy import make_posctl_ppo
from rl_posctl.series_models import mlp_policy_kwargs


def collect(spec, bank, n_episodes):
    xs, ys = [], []
    ds = domain_seed(profiles.MASTER_SEED, "train")
    for i in range(n_episodes):
        prices, feats, _ = bank[i]
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee, window_size=1)
        env.reset()
        done = False
        while not done:
            t = env._current_tick
            row = env._feature_row(t)
            eq = env.ledger.equity(env._close[t])
            ratio = (env.ledger.exposure_ratio(env._close[t])
                     if eq > 0 else 0.0)
            act = reference_action(spec, row, ratio)
            xs.append(env.get_observation())
            ys.append(act)
            _, _, term, trunc, _ = env.step(act)
            done = term or trunc
    return np.asarray(xs, np.float32), np.asarray(
        ys, np.float64)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--epochs", type=int, default=20)
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    quota = QuotaLedger(out_dir / "gen_quota.jsonl")
    ledger = profiles.UsageLedger(out_dir / "usage_ledger.jsonl")
    spec = CourseSpec(course=profiles.TRAIN_COURSE,
                      seed=profiles.MASTER_SEED, horizon=64,
                      **profiles.TRAIN_SPEC_OVERRIDES)
    # 数据生成复用 pilot 的 bank 生成规则(train 域,同 master seed)
    from rl_posctl.experiments import build_train_bank
    bank = build_train_bank(
        profiles.TRAIN_COURSE, profiles.MASTER_SEED, 64, quota,
        window=1)
    x, y = collect(spec, bank, 64)
    n = len(x)
    env = HybridPositionEnv(features=bank[0][1],
                            prices=bank[0][0], fee=spec.fee,
                            window_size=1)
    model = make_posctl_ppo(
        env, policy_kwargs=mlp_policy_kwargs(128), seed=3001,
        device="cpu")
    pol = model.policy
    opt = th.optim.Adam(pol.parameters(), lr=3e-4)
    xt = th.as_tensor(x)
    yt = th.as_tensor(y, dtype=th.float32)
    n_upd = 0
    hist = []
    for ep in range(args.epochs):
        perm = th.randperm(n)
        for i in range(0, n - 255, 256):
            idx = perm[i:i + 256]
            dist = pol._get_action_dist_from_latent(
                pol.mlp_extractor.forward_actor(
                    pol.extract_features(xt[idx])))
            lp = dist.log_prob(yt[idx]).mean()
            loss = -lp
            opt.zero_grad()
            loss.backward()
            opt.step()
            n_upd += 1
            if n_upd >= 2000:
                break
        with th.no_grad():
            d = pol._get_action_dist_from_latent(
                pol.mlp_extractor.forward_actor(
                    pol.extract_features(xt)))
            lp_all = d.log_prob(yt)
            mode = d.mode()
            bacc = float((mode[:, 0] == yt[:, 0]).float().mean())
            reb = yt[:, 0] == 1.0
            if bool(reb.any()):
                wmae = float((mode[reb, 1] - yt[reb, 1]).abs().mean())
            else:
                wmae = None
            hist.append({"epoch": ep + 1, "mean_logp": float(
                lp_all.mean()), "branch_acc": bacc,
                "rebal_w_mae": wmae})
        if n_upd >= 2000:
            break
    ledger.charge(eval_steps=n, tag="bc_diagnostic")
    rec = {"n_samples": int(n), "n_updates": n_upd,
           "epochs_run": len(hist), "history": hist,
           "final": hist[-1] if hist else None,
           "budget": "bc_fits<=4 used:1"}
    (out_dir / "bc_diagnostic.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(rec["final"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
