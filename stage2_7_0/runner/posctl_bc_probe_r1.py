#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 BC 正确性诊断:非平凡内部目标的表达能力(1 fit ≤20 epochs
≤320 minibatch;只用训练分区;先公开标签分布)。

上轮缺陷:训练面参考退化为全清仓,BC 只需拟合零动作——不能支持
表达充分。本轮断言教师(DP 参考)标签含双侧非零内部目标,再拟合;
采样→确定性预测行为一致性由 mode 对拍给出。不做 PPO 学习结论。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch as th

from rl_posctl import profiles
from rl_posctl.banks import QuotaLedger, domain_seed, episode_seed
from rl_posctl.budget import ReservationLedger, create_only_dir
from rl_posctl.curriculum import generate_episode, reference_action
from rl_posctl.env import ENV_STEP_COUNT, HybridPositionEnv
from rl_posctl.experiments import train_course_spec
from rl_posctl.policy import make_posctl_ppo
from rl_posctl.series_models import mlp_policy_kwargs


def collect(spec, bank):
    xs, ys_branch, ys_w = [], [], []
    for prices, feats, _ in bank:
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee,
            window_size=1)
        env.reset()
        done = False
        while not done:
            t = env._current_tick
            row = env._feature_row(t)
            eq = env.ledger.equity(env._close[t])
            ratio = (env.ledger.exposure_ratio(env._close[t])
                     if eq > 0 else 0.0)
            act = reference_action(
                spec, row, ratio, steps_left=env.n_rows - 1 - t)
            xs.append(env.get_observation())
            ys_branch.append(float(act[0]))
            ys_w.append(float(act[1]))
            _, _, term, trunc, _ = env.step(act)
            done = term or trunc
    return (np.asarray(xs, np.float32),
            np.asarray(ys_branch, np.float64),
            np.asarray(ys_w, np.float64))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--episodes", type=int, default=8)
    args = ap.parse_args()
    out_dir = create_only_dir(
        Path(args.out_root) /
        time.strftime("bc_probe_%Y%m%dT%H%M%S"))
    ledger = ReservationLedger(Path(args.ledger))
    quota = QuotaLedger(out_dir / "gen_quota.jsonl")
    spec = train_course_spec(profiles.TRAIN_COURSE,
                             profiles.MASTER_SEED)
    from rl_posctl.experiments import build_train_bank
    bank = build_train_bank(profiles.TRAIN_COURSE,
                            profiles.MASTER_SEED,
                            args.episodes, quota)
    x, y_branch, y_w = collect(spec, bank)
    # BC 数据收集的环境交互保守记 eval_steps
    rid = ledger.reserve("bc_collect_env_steps",
                         eval_steps=int(ENV_STEP_COUNT))
    ledger.commit(rid, "bc_collect_env_steps",
                  eval_steps=int(ENV_STEP_COUNT))
    # 标签分布先公开(事前;不得只拟合零动作宣称充分)
    n = len(x)
    label_stats = {
        "n_samples": int(n),
        "hold_share": float(np.mean(y_branch == 0)),
        "rebal_share": float(np.mean(y_branch == 1)),
        "w_nonzero_share": float(np.mean(np.abs(y_w) > 1e-9)),
        "w_interior_share": float(np.mean(
            (np.abs(y_w) > 1e-9) & (np.abs(y_w) < 1 - 1e-9))),
        "w_pos_share": float(np.mean(y_w > 1e-9)),
        "w_neg_share": float(np.mean(y_w < -1e-9)),
        "w_range": [float(y_w.min()), float(y_w.max())],
        "w_abs_mean": float(np.abs(y_w).mean()),
    }
    assert label_stats["w_interior_share"] > 0.02, \
        f"教师标签无内部目标(退化):{label_stats}"
    assert (label_stats["w_pos_share"] > 0.01
            and label_stats["w_neg_share"] > 0.01), \
        f"教师标签缺双侧:{label_stats}"
    (out_dir / "label_stats.json").write_text(
        json.dumps(label_stats, ensure_ascii=False, indent=1),
        encoding="utf-8")
    # 模型:与 PPO 同一 policy 头(BC 只作表达能力诊断)
    env0 = HybridPositionEnv(
        features=bank[0][1], prices=bank[0][0], fee=spec.fee,
        window_size=1)
    model = make_posctl_ppo(env0, policy_kwargs=mlp_policy_kwargs(
        128), seed=3001, device="cpu")
    pol = model.policy
    opt = th.optim.Adam(pol.parameters(), lr=3e-4)
    xt = th.as_tensor(x)
    bt = th.as_tensor(y_branch.astype(np.float32)).unsqueeze(1)
    wt = th.as_tensor(y_w.astype(np.float32)).unsqueeze(1)
    rid_fit = ledger.reserve(
        "bc_fit", bc_fits=1, bc_epochs=min(args.epochs, 20),
        bc_minibatch_updates=320)
    batch = 256
    rng = np.random.default_rng(7)
    n_updates = 0
    hist = []
    done_all = False
    for epoch in range(min(args.epochs, 20)):
        if done_all:
            break
        perm = rng.permutation(n)
        for s in range(0, n, batch):
            if n_updates >= 320:
                done_all = True
                break
            idx = perm[s:s + batch]
            xb = xt[idx]
            bb = bt[idx]
            wb = wt[idx]
            dist = pol.get_distribution(xb)
            # BC 目标:teacher 动作在该策略下的 −logp 均值
            acts = th.cat(
                [bb, th.where(bb < 0.5, th.zeros_like(wb),
                              wb)], dim=1)
            lp = dist.log_prob(acts)
            loss = -lp.mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            n_updates += 1
            hist.append(float(loss))
    ledger.commit(rid_fit, "bc_fit", bc_fits=1,
                  bc_epochs=min(args.epochs, 20) if not done_all
                  else min(args.epochs, 20),
                  bc_minibatch_updates=n_updates)
    # 评估:deterministic mode vs teacher 标签(行为一致性)
    with th.no_grad():
        acts = pol.get_distribution(xt).mode()
    pred_b = acts[:, 0].numpy()
    pred_w = acts[:, 1].numpy()
    res = {
        "run": "bc_probe_r1", "label_stats": label_stats,
        "n_updates": int(n_updates),
        "final_loss": hist[-1] if hist else None,
        "loss_first": hist[0] if hist else None,
        "branch_acc": float(np.mean(
            (pred_b > 0.5) == (y_branch > 0.5))),
        "w_mae": float(np.mean(np.abs(pred_w - y_w))),
        "w_mae_nonzero_teacher": float(np.mean(np.abs(
            pred_w[np.abs(y_w) > 1e-9]
            - y_w[np.abs(y_w) > 1e-9]))) if np.any(
                np.abs(y_w) > 1e-9) else None,
        "mode_pos_share": float(np.mean(pred_w > 1e-9)),
        "mode_neg_share": float(np.mean(pred_w < -1e-9)),
        "budget_snapshot": ledger.snapshot(),
    }
    (out_dir / "bc_probe_record.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
