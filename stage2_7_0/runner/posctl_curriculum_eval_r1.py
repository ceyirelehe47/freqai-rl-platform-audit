#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 课程有效性评估:四档+ C1–C3 参考统计、参考 vs 基线(固定
bank 重放,不重复生成)、DP 精确期望值。评估步走预约账本。
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from rl_posctl import profiles
from rl_posctl.banks import QuotaLedger, domain_seed, episode_seed
from rl_posctl.budget import ReservationLedger, create_only_dir
from rl_posctl.curriculum import (
    baseline_policies, generate_episode, initial_value, spec_for,
    tier_validity)
import rl_posctl.env as _envmod
from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize
from rl_posctl.experiments import train_course_spec


def replay_stats(spec, episodes, seed0, policy_fn, quota):
    tot = 0.0
    rows = []
    for i in range(episodes):
        quota.record(gen_calls=1, episodes=1,
                     bank=f"posctl_{spec.course}_replay",
                     domain="eval")
        prices, feats, _ = generate_episode(spec, seed0 + i)
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee,
            window_size=1)
        infos = run_policy(env, policy_fn)
        s = summarize(infos)
        tot += (s["net_log_return"] or 0.0)
        rows.append({
            "episode": i,
            "net_log": (s["net_log_return"] if
                        s["net_log_return_valid"] else None),
            "hold_share": s["hold_share"],
            "interior": (s["model_action_fees"] >= 0),
            "fees": s["total_fees"],
            "failure": s["economic_failure"]})
    return tot, rows


def main() -> int:
    import os as _os
    if _os.environ.get("POSCTL_ALLOW_LEGACY_R1") != "1":
        print("REFUSED: R1 入口已被 R2 取代(工作后预约/末段入账为"
              "R1 两次 5,632 步事故根因;R2 用 posctl_r2_eval.py);"
              "如确需复跑历史入口设 POSCTL_ALLOW_LEGACY_R1=1 显式"
              "确认", flush=True)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--tier-episodes", type=int, default=16)
    ap.add_argument("--c123-episodes", type=int, default=8)
    ap.add_argument("--replay-episodes", type=int, default=8)
    ap.add_argument("--baseline", action="append", default=None,
                    help="对照策略子集(可重复;缺省=全部)")
    args = ap.parse_args()
    out_dir = create_only_dir(
        Path(args.out_root) /
        time.strftime("curriculum_eval_%Y%m%dT%H%M%S"))
    ledger = ReservationLedger(Path(args.ledger))
    quota = QuotaLedger(out_dir / "gen_quota.jsonl")
    result = {"run": "curriculum_eval_r1", "tiers": {},
              "c123": {}, "baselines_c4d2": {}}
    courses = ("c4d0", "c4d1", "c4d2", "c4d3")
    for course in courses:
        spec = spec_for(course, seed=profiles.MASTER_SEED,
                        horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        st = tier_validity(spec, n_episodes=args.tier_episodes,
                           quota=quota)
        result["tiers"][course] = {
            "stats": st,
            "dp_initial_value_exact": initial_value(spec),
        }
    for course in ("c1", "c2", "c3"):
        spec = spec_for(course, seed=profiles.MASTER_SEED,
                        horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        st = tier_validity(spec, n_episodes=args.c123_episodes,
                           quota=quota)
        result["c123"][course] = {
            "stats": st,
            "dp_initial_value_exact": initial_value(spec)}
    # 参考 vs 基线(c4d2 训练面;固定 seed 域重放)
    spec = train_course_spec(profiles.TRAIN_COURSE,
                             profiles.MASTER_SEED)
    from rl_posctl.curriculum import reference_action

    def ref(row, w, sl):
        return reference_action(spec, row, w, steps_left=sl)

    bases_all = baseline_policies()
    bases = ({k: bases_all[k] for k in args.baseline}
             if args.baseline else bases_all)
    ref_tot, ref_rows = replay_stats(
        spec, args.replay_episodes, 5000, ref, quota)
    result["baselines_c4d2"]["reference"] = {
        "total_net_log": ref_tot, "rows": ref_rows}
    for name, fn in bases.items():
        tot, _ = replay_stats(
            spec, args.replay_episodes, 5000, fn, quota)
        result["baselines_c4d2"][name] = {"total_net_log": tot}
    # 生成调用计费(quota 已在 generate 处逐次计;此处汇总)
    from rl_posctl.curriculum import GEN_CALL_COUNT
    result["gen_quota_cum"] = {
        "gen_calls": quota.gen_calls, "episodes": quota.episodes}
    result["gen_call_count_module"] = int(GEN_CALL_COUNT)
    env_steps = int(_envmod.ENV_STEP_COUNT)
    rid = ledger.reserve("curriculum_eval_env_steps",
                         eval_steps=env_steps)
    ledger.commit(rid, "curriculum_eval_env_steps",
                  eval_steps=env_steps)
    result["env_steps_total"] = env_steps
    result["budget_snapshot"] = ledger.snapshot()
    (out_dir / "curriculum_eval_r1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(
        {k: v for k, v in result.items()
         if k in ("tiers", "gen_quota_cum", "env_steps_total")},
        ensure_ascii=False, indent=1)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
