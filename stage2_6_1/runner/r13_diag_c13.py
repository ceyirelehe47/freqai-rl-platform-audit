# -*- coding: utf-8 -*-
"""R13 rehearsal 失败诊断:从 pair evidence table 重算 c13 kappa 条件。"""
import json

import numpy as np

from rl_curriculum.curriculum261_r6_pairs import ROBUSTNESS_KAPPA_R6

B = ("/home/cryptorl/projects/crypto_rl/artifacts/"
     "route_c_stage2_6_1_repair13/real_artifact_rehearsal/")
KAPPA = ROBUSTNESS_KAPPA_R6
RUNGS = ["D0", "D1", "D2", "D3"]

for role in ("main", "holdout"):
    pt = json.load(open(B + f"pair_evidence_table_{role}.json"))
    for fam in ("c1_opportunity", "c3_cost"):
        rows = pt[fam]["rows"]
        by_rung = {}
        for r in rows:
            ret = r["returns"]
            diff = ret["reference"] - ret["always_flat"]
            by_rung.setdefault(r["rung"], []).append(diff)
        means = {ru: float(np.mean(by_rung[ru])) for ru in RUNGS}
        ses = {ru: float(np.std(by_rung[ru], ddof=1)
                         / np.sqrt(len(by_rung[ru]))) for ru in RUNGS}
        order_ok = (means["D0"] > means["D1"] > means["D2"]
                    > means["D3"])
        d3_ok = (means["D3"] >= KAPPA * ses["D3"]
                 and means["D3"] > 0)
        gaps_ok = True
        gap_txt = []
        for k in range(3):
            hi, lo = RUNGS[k], RUNGS[k + 1]
            d = np.array(by_rung[hi]) - np.array(by_rung[lo])
            gap = float(d.mean())
            se = float(d.std(ddof=1) / np.sqrt(len(d)))
            ok = gap > 0 and gap >= KAPPA * se
            gaps_ok = gaps_ok and ok
            gap_txt.append(
                f"{hi}-{lo}: {gap:.5f} vs {KAPPA * se:.5f} "
                f"{'OK' if ok else 'FAIL'}")
        bl = [k for k in rows[0]["returns"]
              if k not in ("reference", "always_flat")]
        marg_bad = []
        for bk in bl:
            for ru in RUNGS:
                sel = [r for r in rows if r["rung"] == ru]
                m = np.array(
                    [r["returns"]["reference"] - r["returns"][bk]
                     for r in sel], dtype=float)
                se = m.std(ddof=1) / np.sqrt(len(m))
                if not (m.mean() > 0 and m.mean() >= KAPPA * se):
                    marg_bad.append(
                        f"{bk}/{ru}: {m.mean():.5f} vs {KAPPA * se:.5f}")
        print(f"{role}/{fam}: order={order_ok} "
              f"d3={means['D3']:.5f} vs {KAPPA * ses['D3']:.5f} "
              f"= {d3_ok} gaps={gaps_ok}")
        for g in gap_txt:
            print("   ", g)
        if marg_bad:
            print("    margins FAIL:", marg_bad[:4])
        else:
            print("    margins OK")
