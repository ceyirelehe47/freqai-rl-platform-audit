# -*- coding: utf-8 -*-
"""R10 independent reviewer probe (OMP reviewer, glm-5.3-flash).

Independent content acceptance for QProd R10 (C21=da5655b5), addendum (8)
same-root invariants. Written independently of the main agent's fixtures:
own legal report (multi-key histogram, se=0.02, own ova values).

Zero native / zero generation / zero MC research / zero fit / zero
optimizer / zero model load. Direct calls of the real public entry
recompute_audit_semantics_from_report on synthetic report dicts only.

Every case records: real input (sanitized JSON), fixture_mode echo,
all_consistent, recomputed 8 keys, full discrepancy list, delegation list.
"""
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (  # noqa: E402
    recompute_audit_semantics_from_report as rec,
    AUDIT_REQUIRED_CHECK_NAMES,
)

OUT = sys.argv[1] if len(sys.argv) > 1 else "probe_out"
os.makedirs(OUT, exist_ok=True)

# --- my own legal multi-key histogram (NOT the main agent's {"1": 110})
HM = {"1.0": 60, "2.0": 50}          # 110 events, mean 160/110
NEV = 110
KM = 160.0 / NEV                      # 1.4545454545454546
SE = 0.02
RECALL_TOL = max(3.0 * math.sqrt(SE * SE + SE * SE), 0.005)
DIFF_TOL = max(3.0 * SE, 0.005)       # per-corpus frozen formula


def _vals(h):
    out = []
    for k, c in h.items():
        out.extend([float(k)] * int(c))
    return out


def frozen_k_tol(hm, hv):
    """max(3*pooled_se, 0.05) -- module-documented frozen formula."""
    a, b = np.array(_vals(hm)), np.array(_vals(hv))
    pooled = math.sqrt(
        float(np.var(a, ddof=1)) / len(a)
        + float(np.var(b, ddof=1)) / len(b))
    return max(3.0 * pooled, 0.05)


K_TOL = frozen_k_tol(HM, HM)


def legal_report():
    return {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": SE, "ci95": [0.44, 0.56]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": DIFF_TOL,
                "replay_ok": True,
                "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {
                    "k_mean": KM, "n_detected": NEV, "n_events": NEV,
                    "k_histogram": dict(HM),
                },
                "tail": {"n_events": 0},
            } for n in ("model", "validation")
        },
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": True,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")
            },
        },
        "global_k_audit": {
            "contract_version": "v1", "contract_digest": "d",
            "graph_integrity_ok": True, "n_eligible_cells": 4,
            "T_obs": 1.5, "argmax_cell": "m/v1",
            "final": {"tier": "tier2", "verdict": "PASS",
                      "indeterminate": False},
            "verdict": "PASS", "pass": True,
        },
        "once_vs_attempts": {
            "model_mode": "once", "validation_mode": "attempts",
            "first_pass_bitwise_check": {
                "n_blocks_checked": 2, "n_mismatches": 0,
                "bitwise_ok": True},
            "recall_model": 0.5, "recall_validation": 0.5,
            "abs_diff": 0.0, "tolerance": RECALL_TOL,
            "recall_modes_consistent": True,
            "k_mean_model": KM, "k_mean_validation": KM,
            "k_abs_diff": 0.0, "k_tolerance": K_TOL,
            "k_modes_consistent": True,
        },
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }


RESULTS = []
FAILURES = []


def run(tag, mutate, fixture, expect_consistent,
        need_snippets=(), expect_delegated=None):
    """Run one case; record real input/return; assert semantics."""
    r = legal_report()
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    o = rec(r)
    ok = True
    notes = []
    # fixture_mode echo of the persistent entry object
    if o["fixture_mode"] is not bool(r.get("engineering_fixture")):
        ok = False
        notes.append("fixture_mode echo mismatch")
    if o["all_consistent"] is not expect_consistent:
        ok = False
        notes.append(
            "all_consistent=%r expected %r"
            % (o["all_consistent"], expect_consistent))
    disc = o["threshold_discrepancies"]
    for s in need_snippets:
        if not any(s in d for d in disc):
            ok = False
            notes.append("missing discrepancy snippet %r" % s)
    deg = o["fixture_delegated"]
    if fixture:
        if deg != sorted(set(deg)):
            ok = False
            notes.append("delegation list not dedup-sorted")
        if expect_delegated is not None and deg != expect_delegated:
            ok = False
            notes.append("delegated=%r expected %r" % (deg,
                                                       expect_delegated))
    else:
        if deg:
            ok = False
            notes.append("formal mode must not delegate: %r" % deg)
    status = "OK" if ok else "FAIL"
    RESULTS.append({
        "tag": tag, "fixture": bool(fixture), "expect": expect_consistent,
        "got_all_consistent": o["all_consistent"],
        "fixture_mode": o["fixture_mode"],
        "recomputed": o["recomputed"],
        "discrepancies": disc, "fixture_delegated": deg,
        "notes": notes, "status": status,
    })
    if not ok:
        FAILURES.append(tag)
    print("%-44s fix=%-5s all=%-5s deg=%d disc=%d %s"
          % (tag, bool(fixture), o["all_consistent"], len(deg), len(disc),
             status))
    return o


BOTH = (False, True)


def del_ova(r):
    del r["once_vs_attempts"]


def bad_val_hist_mean4(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"4.0": NEV}


def bad_val_hist_nanos(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"nan": NEV}


def bad_nev_frac(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = 110.5


# ====== baseline: legal complete formal report must PASS ==============
run("A0 legal complete report (formal)", lambda r: None, False, True,
    expect_delegated=[])
# fixture mode with ALL fields present: nothing is missing, so an empty
# delegation ledger is correct (delegation covers only truly-missing parts)
run("A0f legal complete report (fixture)", lambda r: None, True, True,
    expect_delegated=[])

# ==== item 1: bad validation histogram; ova present reject; ===========
# ==== delete whole once_vs_attempts -> SAME bad hist still rejects ====
for fx in BOTH:
    run("A1 bad-val-hist mean4 (ova present)", bad_val_hist_mean4, fx,
        False, need_snippets=("重算均值",))
    run("A2a no-ova + 'nan' key hist",
        lambda r: (del_ova(r), bad_val_hist_nanos(r)), fx, False,
        need_snippets=("结构/频数非法", "'nan'"))
    run("A2b no-ova + mean4 hist",
        lambda r: (del_ova(r), bad_val_hist_mean4(r)), fx, False,
        need_snippets=("重算均值",))
    run("A2c no-ova + n_events=110.5",
        lambda r: (del_ova(r), bad_nev_frac(r)), fx, False,
        need_snippets=("110.5",))


def a2d(r):
    del_ova(r)
    bad_val_hist_mean4(r)


for fx in BOTH:
    o = run("A2d no-ova+mean4 [core invariant]", a2d, fx, False,
            need_snippets=("重算均值",))
    if fx:
        # P3 (C22=1361b4bb): ledger decoupled from the and-short-circuit;
        # rejected path must now KEEP the delegation entry while the
        # verdict stays False (delegation never cleanses bad input).
        if "once_vs_attempts" not in o["fixture_delegated"]:
            FAILURES.append("A2d-ledger-missing")
            print("A2d fixture ledger missing -> FAIL")
        else:
            print("A2d fixture: rejected AND ledger=%r (P3 fix verified)"
                  % (o["fixture_delegated"],))


def a2e(r):
    del_ova(r)
    r["direct_generator"]["model"]["aggregate"][
        "k_histogram"] = {"4.0": NEV}


for fx in BOTH:
    run("A2e no-ova + model-side mean4", a2e, fx, False,
        need_snippets=("重算均值",))

# ==== item 2: single ova derived mean NaN/Inf rejects regardless ======
for fx in BOTH:
    run("B1 ova.k_mean_model=NaN (other present)",
        lambda r: r["once_vs_attempts"].__setitem__(
            "k_mean_model", float("nan")), fx, False,
        need_snippets=("k_mean_model", "非数值/非有限"))
    run("B2 km-model NaN + other side deleted",
        lambda r: (r["once_vs_attempts"].__setitem__(
            "k_mean_model", float("nan")),
            r["once_vs_attempts"].pop("k_mean_validation")), fx, False,
        need_snippets=("k_mean_model", "非数值/非有限"))
    run("B3 kv='nan' str + model side deleted",
        lambda r: (r["once_vs_attempts"].__setitem__(
            "k_mean_validation", "nan"),
            r["once_vs_attempts"].pop("k_mean_model")), fx, False,
        need_snippets=("k_mean_validation", "非数值/非有限"))
    run("B4 km-model=Inf (other present)",
        lambda r: r["once_vs_attempts"].__setitem__(
            "k_mean_model", float("inf")), fx, False,
        need_snippets=("k_mean_model", "非数值/非有限"))


def b2fx(r):
    r["once_vs_attempts"]["k_mean_model"] = float("nan")
    r["once_vs_attempts"].pop("k_mean_validation")


o = run("B2f km-NaN other-del [fixture delegation]",
        b2fx, True, False,
        need_snippets=("k_mean_model",),
        expect_delegated=["once_vs_attempts.k_mean_validation"])
print("B2f: delegation listed AND rejected (delegation != cleansing)")


def b5(r):
    r["once_vs_attempts"].pop("k_mean_validation")


run("B5 legal single-side deletion (fixture)", b5, True, True,
    expect_delegated=["once_vs_attempts.k_mean_validation"])
run("B5f legal single-side deletion (formal)", b5, False, False,
    need_snippets=("缺必需子依据",))

# ==== item 3: n_events=-1 len(events) count semantics =================
def c1(r):
    r["direct_generator"]["validation"]["aggregate"]["n_events"] = -1


def c2(r):
    c1(r)
    del r["direct_generator"]["validation"]["aggregate"]["k_histogram"]


def c3(r):
    c1(r)
    del_ova(r)


for fx in BOTH:
    run("C1 n_events=-1 (hist present, ova present)", c1, fx, False,
        need_snippets=("负计数",))
    run("C2 n_events=-1 + same-side hist deleted", c2, fx, False,
        need_snippets=("负计数",))
    run("C3 n_events=-1 + ova deleted", c3, fx, False,
        need_snippets=("负计数",))


o = run("C2f n_events=-1 hist-del [fixture delegation]", c2, True, False,
        need_snippets=("负计数",))
if "once_vs_attempts.k_tolerance_frozen" in o["fixture_delegated"]:
    print("C2f: hist delegated AND negative count rejected (OK)")
else:
    FAILURES.append("C2f-delegation")
    print("C2f delegation missing -> FAIL")

# ==== item 4: legal delegations preserved =============================
run("D1 legal no-ova (fixture)", del_ova, True, True,
    expect_delegated=["once_vs_attempts"])
run("D2 legal no-ova (formal)", del_ova, False, False,
    need_snippets=("once_vs_attempts_consistent",))


def d4(r):
    del r["direct_generator"]["validation"]["aggregate"]["k_histogram"]


run("D4 legal val-hist missing (fixture)", d4, True, True,
    expect_delegated=["once_vs_attempts.k_tolerance_frozen"])
run("D5 legal val-hist missing (formal)", d4, False, False,
    need_snippets=("缺件",))


def d6(r):
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = None


run("D6 legal k_mean source missing (fixture)", d6, True, True,
    expect_delegated=["once_vs_attempts.k_mean_validation.source_missing"])
run("D7 legal k_mean source missing (formal)", d6, False, False,
    need_snippets=("K 来源缺失",))

# ==== item 5/6: multi-key / rearrangement / finiteness / drift ========
def e1(r):
    for n in ("model", "validation"):
        h = r["direct_generator"][n]["aggregate"]["k_histogram"]
        r["direct_generator"][n]["aggregate"]["k_histogram"] = {
            "2.0": h["2.0"], "1.0": h["1.0"]}


run("E1 legal rearranged histogram keys", e1, False, True,
    expect_delegated=[])


def e2(r):
    del_ova(r)
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"][
            "k_histogram"] = {"1.0": 60, "9.0": 50}


for fx in BOTH:
    run("E2 multi-key bad mean, no-ova", e2, fx, False,
        need_snippets=("重算均值",))


def e3(r):
    del_ova(r)
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {float("nan"): NEV}


run("E3 NaN-float-literal histogram key, no-ova", e3, False, False,
    need_snippets=("结构/频数非法",))


def e4(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"1.0": -5, "2.0": 55}


def e5(r):
    r["direct_generator"]["model"]["aggregate"]["n_events"] = "abc"


def e6(r):
    r["once_vs_attempts"]["k_tolerance"] = 0.05


def e8(r):
    r["direct_generator"]["model"]["aggregate"]["k_mean"] = float("inf")


def e10(r):
    bad_val_hist_mean4(r)
    r["once_vs_attempts"]["k_modes_consistent"] = True


for fx in BOTH:
    run("E4 negative histogram count (ova present)", e4, fx, False,
        need_snippets=("结构/频数非法",))
    run("E5 n_events='abc' non-numeric", e5, fx, False,
        need_snippets=("非数值",))
    run("E6 k_tolerance drift vs frozen formula", e6, fx, False,
        need_snippets=("容差漂移",))
    run("E8 dg k_mean=Inf (model)", e8, fx, False,
        need_snippets=("k_mean",))
    run("E10 bad hist + k_modes_consistent=True lie", e10, fx, False,
        need_snippets=("重算均值", "k_modes_consistent=True"))

# ==== fixture_mode persistence on the same entry object ===============
rp = legal_report()
o1 = rec(rp)
assert o1["fixture_mode"] is False, "persistence step1"
rp["engineering_fixture"] = True
o2 = rec(rp)
assert o2["fixture_mode"] is True, "persistence step2"
assert o2["fixture_delegated"] == [], "all-present fixture: no delegation"
del rp["engineering_fixture"]
o3 = rec(rp)
assert o3["fixture_mode"] is False, "persistence step3"
print("persistence: same dict object toggles fixture_mode "
      "False->True->False OK")
RESULTS.append({
    "tag": "P0 fixture_mode persistence on same object",
    "fixture_mode_sequence": [o1["fixture_mode"], o2["fixture_mode"],
                              o3["fixture_mode"]],
    "status": "OK",
})

# ==== persist all records =============================================
with open(os.path.join(OUT, "cases.jsonl"), "w", encoding="utf-8") as f:
    for rec_json in RESULTS:
        f.write(json.dumps(rec_json, ensure_ascii=False, default=repr)
                + "\n")
with open(os.path.join(OUT, "legal_input_fixture_false.json"), "w",
          encoding="utf-8") as f:
    json.dump(legal_report(), f, ensure_ascii=False, indent=1)
lx = legal_report()
lx["engineering_fixture"] = True
with open(os.path.join(OUT, "legal_input_fixture_true.json"), "w",
          encoding="utf-8") as f:
    json.dump(lx, f, ensure_ascii=False, indent=1)

print("K_TOL frozen formula value:", K_TOL)
print("SUMMARY cases=%d failures=%d %s"
      % (len(RESULTS), len(FAILURES), FAILURES if FAILURES else "ALL OK"))
sys.exit(1 if FAILURES else 0)
