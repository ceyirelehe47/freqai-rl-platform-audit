# -*- coding: utf-8 -*-
"""对比 c3 难度阶梯:R12 正式 vs R13 rt/rt2 rehearsal 语料。"""
import json

import numpy as np

RUNGS = ["D0", "D1", "D2", "D3"]


def ladder(path, role, fam="c3_cost"):
    pt = json.load(open(path + f"pair_evidence_table_{role}.json"))
    rows = pt[fam]["rows"]
    means, ses = {}, {}
    for ru in RUNGS:
        sel = [r for r in rows if r["rung"] == ru]
        d = np.array([r["returns"]["reference"]
                      - r["returns"]["always_flat"] for r in sel])
        means[ru] = float(d.mean())
        ses[ru] = float(d.std(ddof=1) / np.sqrt(len(d)))
    return means, ses


SRC = {
    "R12-main": ("/mnt/e/trading/freqai-rl-audit/stage2_6_1/"
                 "artifacts/repair12/", "main"),
    "R12-hold": ("/mnt/e/trading/freqai-rl-audit/stage2_6_1/"
                 "artifacts/repair12/", "holdout"),
    "rt2-main": ("/home/cryptorl/projects/crypto_rl/artifacts/"
                 "route_c_stage2_6_1_repair13/real_artifact_rehearsal/",
                 "main"),
    "rt2-hold": ("/home/cryptorl/projects/crypto_rl/artifacts/"
                 "route_c_stage2_6_1_repair13/real_artifact_rehearsal/",
                 "holdout"),
}
for name, (path, role) in SRC.items():
    m, s = ladder(path, role)
    gaps = [f"{m[RUNGS[k]] - m[RUNGS[k + 1]]:.5f}"
            for k in range(3)]
    ses = [f"{s[r]:.5f}" for r in RUNGS]
    print(f"{name}: means=" + "/".join(f"{m[r]:.5f}" for r in RUNGS)
          + f" gaps=" + "/".join(gaps)
          + f" ses=" + "/".join(ses))
