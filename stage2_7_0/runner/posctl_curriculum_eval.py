#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课程参考/失败对照评估工件(无梯度;eval 域;报告用)。

输出每课程(训练面规格 + 有效性规格)下 reference 与全部基线的
均值/中位/失败数/HOLD 比例/平均敞口/费用——学习结果解释的对照锚。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from rl_posctl import profiles
from rl_posctl.curriculum import (
    CourseSpec, baseline_policies, reference_action)
from rl_posctl.banks import domain_seed, episode_seed, \
    generate_episode
from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize


def eval_policy(spec, fn, n, master):
    ds = domain_seed(master, "eval")
    logs, fails, holds, exps, fees = [], 0, [], [], 0.0
    for i in range(n):
        prices, feats, _ = generate_episode(
            spec, episode_seed(ds, i))
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee,
            window_size=1)
        infos = run_policy(env, fn)
        s = summarize(infos)
        if s["net_log_return"] is None or s["economic_failure"]:
            fails += 1
        else:
            logs.append(s["net_log_return"])
        holds.append(s["hold_share"])
        exps.append(s["mean_abs_exposure"])
        fees += s["total_fees"]
    return {
        "mean_net_log_return": float(np.mean(logs)) if logs else None,
        "median_net_log_return": float(np.median(logs))
        if logs else None,
        "n_episodes": n, "n_economic_failures": fails,
        "mean_hold_share": float(np.mean(holds)),
        "mean_abs_exposure": float(np.mean(exps)),
        "total_fees": fees,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--ledger")
    args = ap.parse_args()
    ledger = None
    if args.ledger:
        ledger = profiles.UsageLedger(Path(args.ledger))
    master = profiles.MASTER_SEED
    faces = {
        "train_face_c4d2": CourseSpec(
            course="c4d2", seed=master, horizon=64,
            **profiles.TRAIN_SPEC_OVERRIDES),
        "validity_c4d0": CourseSpec(
            course="c4d0", seed=master, horizon=64,
            mu_max=0.03, sigma_lo=0.15, sigma_hi=0.22),
        "validity_c1": CourseSpec(
            course="c1", seed=master, horizon=64),
        "validity_c2": CourseSpec(
            course="c2", seed=master, horizon=64),
        "validity_c3": CourseSpec(
            course="c3", seed=master, horizon=64),
    }
    out = {}
    for face, spec in faces.items():
        if ledger is not None:
            ledger.charge(eval_steps=args.n * 65 * 10,
                          tag=f"curriculum_eval:{face}")
        ref = lambda row, w, s=spec: reference_action(s, row, w)  # noqa: E731
        rows = {"reference": eval_policy(spec, ref, args.n, master)}
        for name, fn in baseline_policies().items():
            rows[name] = eval_policy(spec, fn, args.n, master)
        out[face] = rows
        print(face, json.dumps({
            k: v["mean_net_log_return"]
            for k, v in rows.items()}, ensure_ascii=False))
    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
