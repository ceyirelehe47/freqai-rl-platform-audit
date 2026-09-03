# -*- coding: utf-8 -*-
"""对照诊断:R12 正式 calibration 语料的 c3 margin/gap 量级。"""
import json

import numpy as np

from rl_curriculum.curriculum261_r6_pairs import ROBUSTNESS_KAPPA_R6
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES

KAPPA = ROBUSTNESS_KAPPA_R6
RUNGS = ["D0", "D1", "D2", "D3"]


def cluster_stats(xs):
    xs = np.asarray(xs, dtype=float)
    return float(xs.mean()), float(xs.std(ddof=1) / np.sqrt(len(xs)))


B = ("/mnt/e/trading/freqai-rl-audit/stage2_6_1/artifacts/repair12/")
for role in ("main", "holdout"):
    pt = json.load(open(B + f"pair_evidence_table_{role}.json"))
    for fam in ("c1_opportunity", "c3_cost"):
        rows = pt[fam]["rows"]
        means, ses = {}, {}
        for ru in RUNGS:
            sel = [r for r in rows if r["rung"] == ru]
            diffs = [r["returns"]["reference"]
                     - r["returns"]["always_flat"] for r in sel]
            means[ru], ses[ru] = cluster_stats(diffs)
        gap01 = means["D0"] - means["D1"]
        se01 = float(np.sqrt(ses["D0"] ** 2 + ses["D1"] ** 2))
        out = [f"gapD0-D1 {gap01:.5f} vs {KAPPA * se01:.5f}"]
        for b in REQUIRED_BASELINES[fam]:
            worst = None
            for ru in RUNGS:
                sel = [r for r in rows if r["rung"] == ru]
                m, se = cluster_stats(
                    [r["returns"]["reference"] - r["returns"][b]
                     for r in sel])
                ratio = m / (KAPPA * se) if se > 0 else float("inf")
                if worst is None or ratio < worst[1]:
                    worst = (f"{b}/{ru} m={m:.5f} vs "
                             f"{KAPPA * se:.5f}", ratio)
            out.append(f"worst-margin {worst[0]} ratio={worst[1]:.2f}")
        print(f"R12-{role}/{fam}: " + " | ".join(out))
