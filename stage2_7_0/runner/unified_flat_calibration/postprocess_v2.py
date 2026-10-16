# -*- coding: utf-8 -*-
"""UNIFIED_FLAT_CALIBRATION_V1 后处理 v2(仅冻结 Q 上的再分析)。

修正浮点边界:drift 用 **Fraction 精确有理坐标** -1+2i/(n-1) 比较
(相等=通过,仅 > 粗间距/2 拒);禁止改 Q/新增收益 epsilon/松门槛。
amplitude_status:candidate_act 的次优间隙 ≤ 原误差 proxy →
not_established;课程门恒 not_frozen。原 analysis.json 不动。
"""
import json
import math
import os
import sys
from fractions import Fraction

SRC = "/mnt/f/trading/freqai-rl-audit/stage2_7_0/src"
sys.path.insert(0, SRC)

OUT = sys.argv[1]


def load_tier(tier, out=None):
    out = out or OUT
    with open(os.path.join(
            out, "tier_%s.json" % tier),
            encoding="utf-8") as f:
        d = json.load(f)
    tm = d["tier_meta"]
    acts = [float(x) for x in tm["actions"]]
    accs = [float(x) for x in tm["accounts"]]

    def dec(x):
        return (math.inf if x == "+inf"
                else -math.inf if x == "-inf"
                else float(x))

    rows = []
    for e in d["questions"]:
        r = {k: v for k, v in e.items()
             if k != "q_rebals"}
        r["account"] = {
            k: (math.inf if v == "+inf" else v)
            for k, v in e["account"].items()}
        r["q_hold"] = dec(e["q_hold"])
        r["q_rebals"] = {
            float(k): dec(v)
            for k, v in e["q_rebals"].items()}
        rows.append(r)
    return tm, acts, accs, rows


def rehydrate(tier, tm, acts, accs,
              out=None):
    import numpy as np
    V = np.load(os.path.join(
        out or OUT, "V_%s.npy" % tier))
    from rl_posctl.skill_p0 import (
        unified_ref_adapter as ur)
    tables = {
        "V": V,
        "accounts": np.asarray(accs),
        "actions": np.asarray(acts),
        "gl": tm["gl"], "bars": tm["bars"],
        "tier": tier,
        "solver": ur.SOLVER_VERSION,
        "dp_key": tm["dp_key"],
        "completed": tm["completed"]}
    return tables, ur


def frac_coord(i, n):
    """linspace(-1,1,n) 第 i 点的精确有理坐标。"""
    return Fraction(-1) + Fraction(2 * i, n - 1)


def drift_ok_exact(best_indices, ns):
    """drift ≤ 最粗档间距/2 时通过(相等通过;仅严格大于拒)。"""
    coords = [frac_coord(i, n) for i, n in
              zip(best_indices, ns)]
    drift = max(coords) - min(coords)
    coarse = Fraction(2, ns[0] - 1)
    return drift <= coarse / 2, drift, coarse / 2


def main():
    tm0, _, _, _ = load_tier("L0")
    per_rows = {}
    tiers_data = {}
    per_tier_full = {}
    for tier in ("L0", "L1", "L2"):
        tm, acts, accs, rows = load_tier(tier)
        tiers_data[tier] = (tm, acts, accs, rows)
        per_rows[tier] = {
            r["id"]: r for r in rows}
    _tm, _acts, _accs, _rows = tiers_data["L0"]
    tables0, ur = rehydrate(
        "L0", _tm, _acts, _accs)
    for tier in ("L0", "L1", "L2"):
        tm, acts, accs, rows = tiers_data[tier]
        tables, _ = rehydrate(tier, tm, acts, accs)
        tables["questions"] = rows
        per_tier_full[tier] = tables
    # 64×3 身份/数值/键完整校验(冻结原件)
    ur.validate_tier_outputs(per_tier_full)

    ns = {t: len(tiers_data[t][1])
          for t in ("L0", "L1", "L2")}
    with open(os.path.join(
            OUT, "analysis.json"),
            encoding="utf-8") as f:
        old = json.load(f)["analysis"]

    out = {}
    diff_rows = []
    for qid in sorted(per_rows["L0"]):
        rows = {t: per_rows[t][qid]
                for t in ("L0", "L1", "L2")}
        best_idx = {}
        for t, r in rows.items():
            qr = r["q_rebals"]
            best_idx[t] = max(
                range(len(tiers_data[t][1])),
                key=lambda i: qr[
                    tiers_data[t][1][i]])
        ok, drift, thr = drift_ok_exact(
            [best_idx[t] for t in
             ("L0", "L1", "L2")],
            [ns[t] for t in
             ("L0", "L1", "L2")])
        diffs = {t: {
            w: q - rows[t]["q_hold"]
            for w, q in rows[t]["q_rebals"].items()}
            for t in rows}
        bests = {t: max(d, key=d.get)
                 for t, d in diffs.items()}
        margins = {t: max(d.values())
                   for t, d in diffs.items()}
        common = set(diffs["L0"])
        for t in ("L1", "L2"):
            common &= set(diffs[t])
        val_dev = 0.0      # 原分析口径:原始 Q 值偏差
        for t in ("L0", "L1"):
            for w in common:
                val_dev = max(
                    val_dev,
                    abs(rows[t]["q_rebals"][w]
                        - rows["L2"]["q_rebals"][w]))
        cross = (max(margins.values())
                 - min(margins.values()))
        unc = max(cross, val_dev, 1e-12)
        m_final = margins["L2"]
        signs = {math.copysign(1.0, b)
                 for b in bests.values() if b != 0}
        # 次优间隙(最终档):最佳与次佳动作差
        dvals = sorted(
            diffs["L2"].values(), reverse=True)
        sub_gap = (dvals[0] - dvals[1]
                   if len(dvals) > 1
                   else float("inf"))
        if any(v == -math.inf
               for d in diffs.values()
               for v in d.values()) or \
                any(r["q_hold"] == -math.inf
                    for r in rows.values()):
            status = "not_established"
            reason = "non-finite Q"
        elif len(signs) > 1:
            status = "not_established"
            reason = "best-action sign changed"
        elif not ok:
            status = "not_established"
            reason = ("best_w drifted (exact %s > %s)"
                      % (drift, thr))
        elif m_final <= 0.0:
            status = "no_act"
        elif m_final > unc:
            status = "act"
        else:
            status = "not_established"
            reason = "margin<=uncertainty"
        rec = {
            "status": status,
            "best_w": bests,
            "margin_final": m_final,
            "uncertainty_q_units": unc,
            "drift_exact": {"drift": str(drift),
                            "threshold":
                                str(thr),
                            "pass": bool(ok)},
            "suboptimal_gap_final":
                sub_gap,
            "near_opt_points_final": sorted(
                w for w, d in
                diffs["L2"].items()
                if d >= m_final - 1e-12),
            "near_opt_note": (
                "numerical max-tie set only"),
        }
        if status == "act":
            rec["amplitude_status"] = (
                "not_established"
                if sub_gap <= unc
                else "established_candidate")
            rec["course_gate"] = "not_frozen"
        out[qid] = rec
        o = old.get(qid, {})
        if o.get("status") != status:
            diff_rows.append({
                "qid": qid,
                "old_status":
                    o.get("status"),
                "new_status": status,
                "old_reason":
                    o.get("reason"),
                "new_reason":
                    rec.get("reason"),
                "drift_exact":
                    rec["drift_exact"],
                "margin_final": m_final,
                "unc": unc})

    summary = {}
    for v in out.values():
        summary[v["status"]] = (
            summary.get(v["status"], 0) + 1)
    doc = {
        "analysis_v2": out,
        "summary": summary,
        "changed_rows": diff_rows,
        "method": {
            "drift": ("Fraction-exact argmax indices "
                      "-1+2i/(n-1); drift <= coarse/"
                      "2 passes (equality passes); "
                      "no Q edits, no epsilon, no "
                      "threshold loosening"),
            "amplitude": ("suboptimal_gap <= "
                          "uncertainty proxy -> "
                          "not_established; course "
                          "gate stays not_frozen")},
        "course_gate": "not_frozen"}
    with open(os.path.join(
            OUT, "analysis_v2.json"), "w",
            encoding="utf-8") as f:
        json.dump(doc, f, indent=1,
                  allow_nan=False)
    print("summary", summary)
    print("changed", [
        (d["qid"], d["old_status"],
         d["new_status"]) for d in diff_rows])


if __name__ == "__main__":
    main()
