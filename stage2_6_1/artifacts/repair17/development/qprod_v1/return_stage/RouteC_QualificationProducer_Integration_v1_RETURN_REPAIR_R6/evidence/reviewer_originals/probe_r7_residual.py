import sys, math
sys.path.insert(0, "src")
import numpy as np
from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES,
    recompute_audit_semantics_from_report as rec)
SE = 0.02
RECALL_TOL = max(3.0 * math.sqrt(2 * SE * SE), 0.005)
def legal():
    dgc = {}
    for n in ("model", "validation"):
        dgc[n] = {
            "block_cluster": {"se": SE, "ci95": [0.5, 0.7]},
            "empirical_recall": 0.6, "analytic_conditional": 0.6,
            "diff_tolerance": 0.06,
            "replay_ok": True, "bounds_ok": True,
            "cue_table_consistent_across_rungs": True,
            "max_replay_abs_error": 0.0,
            "aggregate": {"k_mean": 3.0, "n_detected": 6,
                          "n_events": 10, "k_histogram": {"3": 10}},
            "tail": {"n_events": 0}}
    return {
        "p_contract": 0.6,
        "monte_carlo": {"p_hat": 0.6, "tolerance": 0.001},
        "direct_generator": dgc,
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
            "first_pass_bitwise_check": {"n_blocks_checked": 3,
                                         "n_mismatches": 0,
                                         "bitwise_ok": True},
            "recall_model": 0.6, "recall_validation": 0.6,
            "abs_diff": 0.0, "tolerance": RECALL_TOL,
            "recall_modes_consistent": True,
            "k_mean_model": 3.0, "k_mean_validation": 3.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}}
r = legal()
o = r["once_vs_attempts"]
for n in ("model", "validation"):
    r["direct_generator"][n]["aggregate"]["k_histogram"] = {
        "1": 5, "5": 5}
r["direct_generator"]["validation"]["aggregate"]["k_mean"] = 2.5
o["k_mean_validation"] = 2.5
o["k_abs_diff"] = 0.5
ks = np.array([1.0]*5 + [5.0]*5)
pooled = math.sqrt(float(np.var(ks, ddof=1))/10 * 2)
o["k_tolerance"] = max(3.0*pooled, 0.05)
out = rec(r)
print("RESIDUAL(ddof=1 exact): pooled=%.6f declared_tol=%.6f "
      "all_consistent=%s" % (pooled, o["k_tolerance"],
                             out["all_consistent"]))
print("disc:", out["threshold_discrepancies"])
