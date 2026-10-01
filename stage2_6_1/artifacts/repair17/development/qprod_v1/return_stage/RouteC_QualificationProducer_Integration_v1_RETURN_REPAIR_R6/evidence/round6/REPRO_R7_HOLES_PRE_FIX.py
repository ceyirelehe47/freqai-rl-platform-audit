import sys, json
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    recompute_audit_semantics_from_report as rec,
    AUDIT_REQUIRED_CHECK_NAMES)
from collections import Counter

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
                              "n_events": 2, "k_histogram": {"1": 2}},
                "tail": {"n_events": 0},
            } for n in ("model", "validation")},
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {n: {"ok": True, "violations": [],
                               "n_violations": 0,
                               "exact_noise_replay_ok": True,
                               "bounds_ok_all_positions": True}
                           for n in ("model", "validation")}},
        "global_k_audit": {
            "final": {"verdict": "PASS"},
            "verdict": "PASS", "pass": True},
        "once_vs_attempts": {
            "first_pass_bitwise_check": {"bitwise_ok": True},
            "recall_model": 0.5, "recall_validation": 0.5,
            "abs_diff": 0.0, "tolerance": 0.042426406871192854,
            "recall_modes_consistent": True,
            "k_mean_model": 1.0, "k_mean_validation": 1.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }

def run(tag, mutate):
    r = base_report(); mutate(r)
    out = rec(r)
    print(tag, "all_consistent=%s ova=%s" % (
        out["all_consistent"],
        out["recomputed"]["once_vs_attempts_consistent"]))

# F1: 删 dg.aggregate.k_mean -> 来源对账静默跳过, 伪造 K 声明
def f1(r):
    for n in ("model", "validation"):
        del r["direct_generator"][n]["aggregate"]["k_mean"]
    ova = r["once_vs_attempts"]
    ova["k_mean_model"] = 0.0   # 伪造(真实 k_mean 被删)
    ova["k_mean_validation"] = 0.0
    ova["k_abs_diff"] = 0.0
run("F1 k-source-deleted-forged", f1)

# F2: k 来源真实(3.0/2.5), 派生自洽, k_tolerance 膨胀到 1.0
def f2(r):
    for n, km in (("model", 3.0), ("validation", 2.5)):
        agg = r["direct_generator"][n]["aggregate"]
        agg["k_mean"] = km
        agg["k_histogram"] = {"3": 2} if km == 3.0 else {"2": 1, "3": 1}
    ova = r["once_vs_attempts"]
    ova["k_mean_model"] = 3.0; ova["k_mean_validation"] = 2.5
    ova["k_abs_diff"] = 0.5   # 派生自洽
    ova["k_tolerance"] = 1.0   # 膨胀(冻结公式 max(3*pooled_se,0.05) 小得多)
run("F2 k-tolerance-inflated", f2)
run("ctl", lambda r: None)
