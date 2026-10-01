# -*- coding: utf-8 -*-
"""R9 independent reviewer probe (C19 bytes, WSL deploy tree).
Independent base report (values differ from REPRO_R9_PRE_FIX.py).
Covers addendum (7) S1/S2 + reviewer-devised masking combinations.
Records fixture_mode for every direct-helper call. Zero generation.
"""
import math
import sys

sys.path.insert(0, "src")
import numpy as np

from rl_curriculum.curriculum261_r17_cue_contract import (
    recompute_audit_semantics_from_report as rec,
    AUDIT_REQUIRED_CHECK_NAMES,
)

P = 0.62
KMEAN = 2.0
HIST1 = {"2": 110}          # mean 2.0, total 110 == n_events
RECALL_TOL = 3.0 * math.sqrt(0.02 ** 2 + 0.02 ** 2)   # se=0.02 both
KTOL_FLOOR = 0.05


def frozen_ktol(hm, hv, n):
    def vals(h):
        out = []
        for k, c in h.items():
            out.extend([float(k)] * int(c))
        return out
    a, b = vals(hm), vals(hv)
    pooled = math.sqrt(float(np.var(np.array(a), ddof=1)) / len(a)
                       + float(np.var(np.array(b), ddof=1)) / len(b))
    return max(3.0 * pooled, 0.05)


def base_report(ktol=KTOL_FLOOR, hm=None, hv=None,
                kmean=KMEAN, nev=110):
    hm = HIST1 if hm is None else hm
    hv = HIST1 if hv is None else hv
    return {
        "p_contract": P,
        "monte_carlo": {"p_hat": P, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": 0.02, "ci95": [0.56, 0.68]},
                "empirical_recall": P,
                "analytic_conditional": P,
                "diff_tolerance": 0.06,
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {"k_mean": kmean, "n_detected": 1,
                              "n_events": nev, "k_histogram": hm
                              if n == "model" else hv},
                "tail": {"n_events": 0},
            } for n in ("model", "validation")},
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": True,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")}},
        "global_k_audit": {
            "contract_version": "v1", "contract_digest": "d",
            "graph_integrity_ok": True, "n_eligible_cells": 4,
            "T_obs": 1.5, "argmax_cell": "m/v1",
            "final": {"tier": "tier2", "verdict": "PASS",
                      "indeterminate": False},
            "verdict": "PASS", "pass": True},
        "once_vs_attempts": {
            "model_mode": "once", "validation_mode": "attempts",
            "first_pass_bitwise_check": {
                "n_blocks_checked": 2, "n_mismatches": 0,
                "bitwise_ok": True},
            "recall_model": P, "recall_validation": P,
            "abs_diff": 0.0, "tolerance": RECALL_TOL,
            "recall_modes_consistent": True,
            "k_mean_model": KMEAN, "k_mean_validation": KMEAN,
            "k_abs_diff": 0.0, "k_tolerance": ktol,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }


RESULTS = []


def run(tag, expect, fixture=False, _mut=None, **kw):
    r = base_report(**kw)
    if _mut is not None:
        _mut(r)
    if fixture:
        r["engineering_fixture"] = True
    out = rec(r)
    ok = (out["all_consistent"] == (expect == "PASS"))
    false_gates = sorted(k for k, v in out["recomputed"].items()
                         if v is False)
    d1 = out["threshold_discrepancies"][0][:72] \
        if out["threshold_discrepancies"] else "-"
    RESULTS.append((tag, expect, out["fixture_mode"],
                    out["all_consistent"], ok,
                    ";".join(out["fixture_delegated"]) or "-",
                    d1))
    return out


# ---------- A. positive controls ----------
run("P1 legal nofixture", "PASS")
run("P2 legal fixture", "PASS", fixture=True)
o3 = None
_HM3 = {"1": 40, "2": 30, "3": 40}
run("P3 multik legal", "PASS", fixture=False,
    ktol=frozen_ktol(_HM3, _HM3, 110), hm=_HM3, hv=_HM3)
run("P4 multik reorder", "PASS", fixture=False,
    ktol=frozen_ktol(_HM3, _HM3, 110), hm=_HM3, hv=_HM3,
    _mut=lambda r: r["direct_generator"]["validation"]["aggregate"]
    .__setitem__("k_histogram", {"3": 40, "1": 40, "2": 30}))
run("P5 single-key floor 0.05", "PASS", fixture=False,
    ktol=KTOL_FLOOR)
run("P6 ova-derived-del legal fixture", "PASS", fixture=True,
    _mut=lambda r: r["once_vs_attempts"].pop("k_mean_model"))
run("P6b ova-derived-del nofixture", "REJECT",
    _mut=lambda r: r["once_vs_attempts"].pop("k_mean_model"))
run("P7 both-hists-del double-delegate fixture", "PASS",
    fixture=True,
    _mut=lambda r: [r["direct_generator"][n]["aggregate"]
                    .pop("k_histogram") for n in ("model", "validation")])
run("P7b both-hists-del nofixture", "REJECT",
    _mut=lambda r: [r["direct_generator"][n]["aggregate"]
                    .pop("k_histogram") for n in ("model", "validation")])
run("P8 src-missing delegate fixture", "PASS", fixture=True,
    _mut=lambda r: r["direct_generator"]["model"]["aggregate"]
    .pop("k_mean"))

# ---------- B. addendum counterexamples (must REJECT both modes) ----------
def _bad_v(r):
    r["direct_generator"]["validation"]["aggregate"]["k_histogram"] = {
        "9": 110}


run("B1 badhist nofixture", "REJECT", _mut=_bad_v)
run("B1f badhist fixture", "REJECT", fixture=True, _mut=_bad_v)


def _c2(r):
    _bad_v(r)
    r["direct_generator"]["model"]["aggregate"].pop("k_histogram")


run("B2 badhist+other-missing nofixture", "REJECT", _mut=_c2)
run("B2f badhist+other-missing fixture", "REJECT", fixture=True,
    _mut=_c2)   # addendum S1 case1


def _c3(r):
    _bad_v(r)
    r["once_vs_attempts"].pop("k_mean_model")


run("B3 badhist+ova-del nofixture", "REJECT", _mut=_c3)
run("B3f badhist+ova-del fixture", "REJECT", fixture=True,
    _mut=_c3)   # addendum S1 case2


def _c4(r):
    r["direct_generator"]["validation"]["aggregate"]["k_histogram"] = {
        "nan": 110}


run("B4 nan-str-key nofixture", "REJECT", _mut=_c4)
run("B4f nan-str-key fixture", "REJECT", fixture=True, _mut=_c4)
run("B5 nan-float-key", "REJECT",
    _mut=lambda r: r["direct_generator"]["validation"]["aggregate"]
    .__setitem__("k_histogram", {float("nan"): 110}))


def _c6(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = 110.5


run("B6 n_events=110.5", "REJECT", _mut=_c6)


def _c7(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = "110"


run("B7 n_events='110'", "REJECT", _mut=_c7)


def _c8(r):
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = "nan"


run("B8 kmean-src 'nan'", "REJECT", _mut=_c8)
run("B9 ova-km NaN+absdiff NaN", "REJECT",
    _mut=lambda r: r["once_vs_attempts"].__setitem__(
        "k_mean_model", float("nan"))
    or r["once_vs_attempts"].__setitem__("k_abs_diff", float("nan")))
run("B10 ova-ktol NaN", "REJECT",
    _mut=lambda r: r["once_vs_attempts"].__setitem__(
        "k_tolerance", float("nan")))


def _c11(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = 111


run("B11 n_events=111 != 110", "REJECT", _mut=_c11)


def _c12(r):
    r["direct_generator"]["validation"]["aggregate"]["k_histogram"] = {
        "2": 109.5}


run("B12 fractional count", "REJECT", _mut=_c12)
run("B13 'inf' key", "REJECT",
    _mut=lambda r: r["direct_generator"]["validation"]["aggregate"]
    .__setitem__("k_histogram", {"inf": 110}))
run("B14 kmean-src +inf", "REJECT",
    _mut=lambda r: r["direct_generator"]["validation"]["aggregate"]
    .__setitem__("k_mean", float("inf")))

# ---------- H. reviewer-devised masking combinations ----------
def _h1(r):
    r["direct_generator"]["model"]["aggregate"].pop("k_histogram")
    r["direct_generator"]["model"]["aggregate"]["k_mean"] = "nan"


run("H1 nan-src masked by missing-hist FIXTURE", "REJECT",
    fixture=True, _mut=_h1)
run("H1b same nofixture", "REJECT", _mut=_h1)


def _h2(r):
    r["direct_generator"]["validation"]["aggregate"].pop("k_histogram")
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = "nan"


run("H2 nan-src masked (validation) FIXTURE", "REJECT",
    fixture=True, _mut=_h2)


def _h3(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"].pop("k_histogram")
        r["direct_generator"][n]["aggregate"]["k_mean"] = "nan"


run("H3 both-src nan masked FIXTURE", "REJECT", fixture=True,
    _mut=_h3)


def _h4(r):
    r["once_vs_attempts"]["k_abs_diff"] = float("nan")
    r["once_vs_attempts"].pop("k_tolerance")


run("H4 ova-absdiff-NaN ktol-missing FIXTURE", "REJECT",
    fixture=True, _mut=_h4)
run("H4b same nofixture", "REJECT", _mut=_h4)


def _h5(r):
    r["direct_generator"]["model"]["aggregate"].pop("k_histogram")
    r["direct_generator"]["model"]["aggregate"]["n_events"] = 110.5


run("H5 frac-n_events masked by missing-hist FIXTURE", "REJECT",
    fixture=True, _mut=_h5)
run("H7 absdiff-NaN ktol-present", "REJECT",
    _mut=lambda r: r["once_vs_attempts"].__setitem__(
        "k_abs_diff", float("nan")))

# ---------- report ----------
print("%-46s %-6s fx=%-5s %-5s %-4s delegated" % (
    "case", "expect", "mode", "all", "ok"))
fails = 0
for tag, expect, fx, allc, ok, dele, d1 in RESULTS:
    if not ok:
        fails += 1
    print("%-46s %-6s fx=%-5s %-5s %-4s [%s] %s" % (
        tag, expect, fx, allc, "OK" if ok else "FAIL", dele, d1))
print("TOTAL=%d FAILS=%d" % (len(RESULTS), fails))
sys.exit(1 if fails else 0)
