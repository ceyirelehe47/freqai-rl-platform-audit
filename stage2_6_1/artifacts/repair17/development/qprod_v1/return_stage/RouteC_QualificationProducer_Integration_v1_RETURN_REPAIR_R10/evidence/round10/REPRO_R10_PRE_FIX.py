# R10 pre-fix repro (C20=52e70a17 bytes): three same-root holes
# H1: once_vs_attempts deleted entirely -> in-present bad histogram escapes
# H2: single ova derived mean NaN with other side present/absent
# H3: n_events=-1 with same-side histogram deleted
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


def run(tag, m, fixture=False):
    r = base_report()
    m(r)
    if fixture:
        r["engineering_fixture"] = True
    o = rec(r)
    g = {k: v for k, v in o["recomputed"].items() if v is False}
    print("%s fix=%s all=%s false=%s" % (
        tag, fixture, o["all_consistent"], list(g)))


# --- hole 1: delete whole once_vs_attempts, keep bad histogram
def del_ova(r):
    del r["once_vs_attempts"]


def bad_nan_key(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"nan": 110}


def bad_hist_mean4(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"4": 110}


def bad_nev_frac(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = 110.5


def c1a(r):
    del_ova(r); bad_nan_key(r)
def c1b(r):
    del_ova(r); bad_hist_mean4(r)
def c1c(r):
    del_ova(r); bad_nev_frac(r)


run("H1a no-ova+nan-key", c1a)
run("H1b no-ova+hist-mean4", c1b)
run("H1c no-ova+nev-110.5", c1c)

# --- hole 2: single ova derived mean NaN (other side present then absent)
def c2a(r):
    r["once_vs_attempts"]["k_mean_model"] = float("nan")
run("H2a km-model-nan(other present)", c2a)
def c2b(r):
    c2a(r)
    del r["once_vs_attempts"]["k_mean_validation"]
run("H2b km-model-nan(other deleted)", c2b)
def c2c(r):
    r["once_vs_attempts"]["k_mean_validation"] = "nan"
    del r["once_vs_attempts"]["k_mean_model"]
run("H2c kv-nan-str(other deleted)", c2c)

# --- hole 3: n_events=-1, histogram present then same-side deleted
def c3a(r):
    r["direct_generator"]["validation"]["aggregate"]["n_events"] = -1
run("H3a nev--1(hist present)", c3a)
def c3b(r):
    c3a(r)
    del r["direct_generator"]["validation"]["aggregate"]["k_histogram"]
run("H3b nev--1(same-side hist deleted)", c3b)

# --- controls
run("ctl legal", lambda r: None)
run("ctl legal fixture", lambda r: None, fixture=True)
run("ctl-r9 bad-hist-ova-present", bad_hist_mean4)
run("ctl no-ova legal", del_ova)
run("ctl no-ova legal fixture", del_ova, fixture=True)
