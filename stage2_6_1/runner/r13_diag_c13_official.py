# -*- coding: utf-8 -*-
"""R13 rehearsal 诊断:按官方口径(corpus_conditions_r5 语义)重算 c13。"""
import json

import numpy as np

from rl_curriculum.curriculum261_r6_pairs import ROBUSTNESS_KAPPA_R6
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES

B = ("/home/cryptorl/projects/crypto_rl/artifacts/"
     "route_c_stage2_6_1_repair13/real_artifact_rehearsal/")
KAPPA = ROBUSTNESS_KAPPA_R6
RUNGS = ["D0", "D1", "D2", "D3"]


def cluster_stats(xs):
    xs = np.asarray(xs, dtype=float)
    return float(xs.mean()), float(xs.std(ddof=1) / np.sqrt(len(xs)))


for role in ("main", "holdout"):
    pt = json.load(open(B + f"pair_evidence_table_{role}.json"))
    for fam in ("c1_opportunity", "c3_cost"):
        rows = pt[fam]["rows"]
        fails = []
        # ladder(难度 = reference - always_flat)
        means, ses = {}, {}
        for ru in RUNGS:
            sel = [r for r in rows if r["rung"] == ru]
            diffs = [r["returns"]["reference"]
                     - r["returns"]["always_flat"] for r in sel]
            means[ru], ses[ru] = cluster_stats(diffs)
        if not (means["D0"] > means["D1"] > means["D2"] > means["D3"]):
            fails.append("ordering")
        if not (means["D3"] > 0 and means["D3"] >= KAPPA * ses["D3"]):
            fails.append(f"d3:{means['D3']:.5f} vs {KAPPA * ses['D3']:.5f}")
        for k in range(3):
            hi, lo = RUNGS[k], RUNGS[k + 1]
            gap = means[hi] - means[lo]
            se = float(np.sqrt(ses[hi] ** 2 + ses[lo] ** 2))
            if not (gap > 0 and gap >= KAPPA * se):
                fails.append(f"gap {hi}-{lo}: {gap:.5f} vs "
                             f"{KAPPA * se:.5f}")
        # margins(官方固定基线)
        for b in REQUIRED_BASELINES[fam]:
            for ru in RUNGS:
                sel = [r for r in rows if r["rung"] == ru]
                m, se = cluster_stats(
                    [r["returns"]["reference"] - r["returns"][b]
                     for r in sel])
                if not (m > 0 and m >= KAPPA * se):
                    fails.append(f"margin {b}/{ru}: {m:.5f} vs "
                                 f"{KAPPA * se:.5f}")
        # oracle 全 rung 为正
        for ru in RUNGS:
            sel = [r for r in rows if r["rung"] == ru]
            o = float(np.mean([r["returns"]["oracle"] for r in sel]))
            if o <= 0:
                fails.append(f"oracle {ru}: {o:.5f}")
        status = "PASS" if not fails else "FAIL"
        print(f"{role}/{fam}: {status}")
        for x in fails[:8]:
            print("   ", x)
