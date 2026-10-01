# R8 pre-fix repro: K-histogram closure / in-report illegal / gate subevidence
import sys
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    recompute_audit_semantics_from_report as rec,
    AUDIT_REQUIRED_CHECK_NAMES,
)

def base_report():
    return {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": 0.03,
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
                "aggregate": {"k_mean": 1.0, "n_detected": 1,
                              "n_events": 110,
                              "k_histogram": {"1": 110}},
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
            "recall_model": 0.5, "recall_validation": 0.5,
            "abs_diff": 0.0, "tolerance": 0.042426406871192854,
            "recall_modes_consistent": True,
            "k_mean_model": 1.0, "k_mean_validation": 1.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }

def run(tag, mutate, fixture=False):
    r = base_report(); mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    out = rec(r)
    gate = {k: v for k, v in out["recomputed"].items() if v is False}
    print("%s fixture=%s all=%s false_gates=%s" % (
        tag, fixture, out["all_consistent"], gate))

# h1: validation histogram {4:110} but k_mean 1.0 declared everywhere
def h1(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"4": 110}
run("h1 hist-mean-mismatch", h1)

# h2: histogram total 109 vs n_events 110
def h2(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"][
            "k_histogram"] = {"1": 109}
run("h2 hist-total-mismatch", h2)

# h3: negative count
def h3(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"][
            "k_histogram"] = {"1": 110, "2": -1}
run("h3 negative-count", h3)

# h4: gk graph_integrity_ok False + PASS
def h4(r):
    r["global_k_audit"]["graph_integrity_ok"] = False
run("h4 gk-integrity-false-pass", h4)

# h5: gk PASS without final
def h5(r):
    del r["global_k_audit"]["final"]
run("h5 gk-pass-no-final", h5)

# h6: tail per_corpus missing validation
def h6(r):
    del r["tail_mirror_bound_integrity"]["per_corpus"][
        "validation"]
run("h6 tail-missing-validation", h6)

# h7: fixture + in-report illegal histogram
def h7(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"not-a-number": 110}
run("h7 fixture-illegal-hist", h7, fixture=True)

# ctl: legal complete, no fixture
run("ctl legal", lambda r: None)
# ctl2: legal complete, fixture
run("ctl legal-fixture", lambda r: None, fixture=True)
# ctl3: permuted key order, fully self-consistent (frozen tol recomputed)
def ctl3(r):
    import math as _m
    for n_ in ("model", "validation"):
        r["direct_generator"][n_]["aggregate"]["k_histogram"] = {"2": 10, "1": 100}
        r["direct_generator"][n_]["aggregate"]["k_mean"] = (1*100 + 2*10) / 110
    ova = r["once_vs_attempts"]
    km = (1*100 + 2*10) / 110
    ova["k_mean_model"] = ova["k_mean_validation"] = km
    v = [1.0]*100 + [2.0]*10
    mu = sum(v)/110
    var = sum((x-mu)**2 for x in v)/109
    pooled = _m.sqrt(var/110 + var/110)
    ova["k_tolerance"] = max(3*pooled, 0.05)
run("ctl3 permuted-order", ctl3)
