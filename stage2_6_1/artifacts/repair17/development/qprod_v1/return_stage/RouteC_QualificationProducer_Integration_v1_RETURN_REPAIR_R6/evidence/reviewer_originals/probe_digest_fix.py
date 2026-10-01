import sys
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    cue_contract_audit_digest,
    recompute_audit_semantics_from_report as rec)
r = {
    "format": "cur261-r17-cue-contract-audit-v1",
    "contract_version": "C2CueDetectionSemanticContract-v2",
    "audit_namespaces": {"model": "m", "validation": "v"},
    "audit_blocks_per_corpus": 2, "audit_rng_seed": 1,
    "frozen_detector": {}, "mirror_bound_v2": True, "margin_log": [],
    "p_contract": 0.6, "monte_carlo": {"p_hat": 0.6, "tolerance": 0.001},
    "noninferiority": {"delta": 0.02},
    "direct_generator": {
        n: {"n_unique_positive_cues": 10, "empirical_recall": 0.6,
            "block_cluster": {"point": 0.6, "se": 0.02,
                              "lcb95": 0.5, "ci95": [0.5, 0.7]},
            "analytic_conditional": 0.6,
            "tail": {"n_events": 0, "empirical_recall": None,
                     "analytic_conditional": None},
            "max_replay_abs_error": 0.0}
        for n in ("model", "validation")},
}
d1 = cue_contract_audit_digest(r)
r["audit_digest"] = d1
ok = cue_contract_audit_digest(r) == d1
# 篡改 ova(K 来源声明):digest 不变(不绑定 ova),但重算层捕获
r["once_vs_attempts"] = {
    "k_mean_model": 0.25, "k_mean_validation": 3.0,
    "k_abs_diff": 0.0, "k_tolerance": 0.05,
    "k_modes_consistent": True,
    "recall_model": 0.6, "recall_validation": 0.6,
    "abs_diff": 0.0, "tolerance": 0.08485281374238571,
    "recall_modes_consistent": True,
    "first_pass_bitwise_check": {"bitwise_ok": True}}
d2 = cue_contract_audit_digest(r)
out = rec(r)
print("digest-stable-under-ova-tamper:", d1 == d2,
      "| legal-digest-recompute:", ok,
      "| ova-tamper-caught-by-recompute:", not out["all_consistent"])
