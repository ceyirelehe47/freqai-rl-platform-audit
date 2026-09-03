# -*- coding: utf-8 -*-
"""R13 rehearsal 诊断:识别 pair 返回的 baseline 键集与 margins 重算。"""
import json

import numpy as np

from rl_curriculum.curriculum261_r6_pairs import ROBUSTNESS_KAPPA_R6

B = ("/home/cryptorl/projects/crypto_rl/artifacts/"
     "route_c_stage2_6_1_repair13/real_artifact_rehearsal/")
KAPPA = ROBUSTNESS_KAPPA_R6
RUNGS = ["D0", "D1", "D2", "D3"]

pt = json.load(open(B + "pair_evidence_table_main.json"))
rows = pt["c1_opportunity"]["rows"]
keys = [k for k in rows[0]["returns"] if k != "reference"]
print("returns keys:", keys)
for k in keys:
    vals = [r["returns"][k] - r["returns"]["reference"] for r in rows]
    print(f"  {k} - reference: mean={np.mean(vals):+.5f}")

print()
for role in ("main", "holdout"):
    pt = json.load(open(B + f"pair_evidence_table_{role}.json"))
    for fam in ("c1_opportunity", "c3_cost"):
        rows = pt[fam]["rows"]
        bad = []
        for k in keys:
            for ru in RUNGS:
                sel = [r for r in rows if r["rung"] == ru]
                m = np.array(
                    [r["returns"]["reference"] - r["returns"][k]
                     for r in sel], dtype=float)
                se = m.std(ddof=1) / np.sqrt(len(m))
                if not (m.mean() > 0 and m.mean() >= KAPPA * se):
                    bad.append(f"{k}/{ru}: {m.mean():+.5f} "
                               f"vs {KAPPA * se:.5f}")
        print(f"{role}/{fam}: margin_fail={len(bad)}")
        for x in bad[:6]:
            print("   ", x)
