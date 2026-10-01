import sys, math
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest,
    recompute_audit_semantics_from_report as rec)
SE = 0.02
RECALL_TOL = max(3.0 * math.sqrt(2 * SE * SE), 0.005)

def legal():
    dgc = {}
    for n in ("model", "validation"):
        dgc[n] = {
            "n_unique_positive_cues": 10,
            "block_cluster": {"point": 0.6, "se": SE, "lcb95": 0.5,
                              "ci95": [0.5, 0.7]},
            "empirical_recall": 0.6, "analytic_conditional": 0.6,
            "diff_tolerance": 0.06,
            "replay_ok": True, "bounds_ok": True,
            "cue_table_consistent_across_rungs": True,
            "max_replay_abs_error": 0.0,
            "aggregate": {"k_mean": 3.0, "n_detected": 6, "n_events": 10},
            "tail": {"n_events": 0, "empirical_recall": None,
                     "analytic_conditional": None}}
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
        "checks": {}, "format": "cur261-r17-cue-contract-audit-v1",
        "contract_version": "C2CueDetectionSemanticContract-v2",
        "audit_namespaces": {"model": "m", "validation": "v"},
        "audit_blocks_per_corpus": 2, "audit_rng_seed": 1,
        "frozen_detector": {}, "mirror_bound_v2": True,
        "margin_log": [], "noninferiority": {"delta": 0.02}}

def digest_ok_report(r):
    d = cue_contract_audit_digest(r)
    r["audit_digest"] = d
    return cue_contract_audit_digest(r) == d

# N13: 删除 dg 两语料 aggregate 子键(digest 不读 aggregate→不破坏
# digest),ova K 链自洽但来源缺失
r = legal()
print("digest-ok-with-aggregate:", digest_ok_report(r))
del r["direct_generator"]["model"]["aggregate"]
del r["direct_generator"]["validation"]["aggregate"]
print("digest-ok-after-aggregate-removed:",
      digest_ok_report(r) is not None)
r["checks"] = {k: True for k in
               __import__("rl_curriculum.curriculum261_r17_cue_contract",
                          fromlist=["AUDIT_REQUIRED_CHECK_NAMES"]
                          ).AUDIT_REQUIRED_CHECK_NAMES}
out = rec(r)
print("N13 aggregate-absent-source: all_consistent =",
      out["all_consistent"], "| ova gate =",
      out["recomputed"]["once_vs_attempts_consistent"])
print("disc:", out["threshold_discrepancies"])

# N14: 同形态但 K 声明与(已删除前的)真实来源矛盾——攻击者改声明
r2 = legal()
r2["once_vs_attempts"]["k_mean_model"] = 1.0
r2["once_vs_attempts"]["k_mean_validation"] = 1.0
del r2["direct_generator"]["model"]["aggregate"]
del r2["direct_generator"]["validation"]["aggregate"]
r2["checks"] = {k: True for k in
                __import__("rl_curriculum.curriculum261_r17_cue_contract",
                           fromlist=["AUDIT_REQUIRED_CHECK_NAMES"]
                           ).AUDIT_REQUIRED_CHECK_NAMES}
out2 = rec(r2)
print("N14 forged-k-decl-source-absent: all_consistent =",
      out2["all_consistent"])
print("disc:", out2["threshold_discrepancies"])
