import sys, json
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    recompute_audit_semantics_from_report as rec)

def base_report():
    """支撑完整的正式式报告(无 fixture 标记)。"""
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
                              "n_events": 2,
                              "k_histogram": {"1": 2}},
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
        "checks": {},
    }

from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES)

def run(tag, mutate):
    r = base_report()
    mutate(r)
    r["checks"] = {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}
    out = rec(r)
    print("%s: fixture=%s all_consistent=%s" % (
        tag, out["fixture_mode"], out["all_consistent"]))
    for k, v in out["recomputed"].items():
        if v is False:
            print("   FALSE gate:", k)
    return out

def c1(r):
    ova = r["once_vs_attempts"]
    ova["k_mean_model"] = 0.25  # 派生 1/4 vs 来源 1/1
    ova["k_abs_diff"] = 0.0     # 与 |0.25-1.0|=0.75 矛盾
run("c1 k-source-derived-mismatch", c1)

def c2(r):
    r["once_vs_attempts"]["first_pass_bitwise_check"] = {
        "n_blocks_checked": 2, "n_mismatches": 0}  # bitwise_ok 删
run("c2 bitwise_ok-missing", c2)

def c3(r):
    r["once_vs_attempts"] = {
        "model_mode": "once", "validation_mode": "attempts"}
run("c3 ova-only-mode-keys", c3)

def c4(r):
    for sub in r["tail_mirror_bound_integrity"][
            "per_corpus"].values():
        del sub["exact_noise_replay_ok"]  # 必要子依据缺失+ok=True
run("c4 tail-subkey-missing", c4)

def c5(r):
    gk = r["global_k_audit"]
    gk["verdict"] = "FAIL"; gk["pass"] = True
    gk["final"]["verdict"] = "PASS"
run("c5 gk-verdict-FAIL-pass-True", c5)

ctl = run("ctl legal-complete", lambda r: None)

print("--- ctl diagnosis ---")
r = base_report()
r["checks"] = {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}
out = rec(r)
print(json.dumps(out["threshold_discrepancies"], indent=1,
                 ensure_ascii=False))
print(json.dumps(out["declared_vs_recomputed"], indent=1)[:600])
