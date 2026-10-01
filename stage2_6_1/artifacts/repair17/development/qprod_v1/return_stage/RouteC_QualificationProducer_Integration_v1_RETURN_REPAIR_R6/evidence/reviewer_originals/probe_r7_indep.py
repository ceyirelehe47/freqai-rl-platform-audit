# 独立 reviewer R7 探针:F1(来源缺件)/F2(容差冻结锚)修后行为 +
# R6 全部反例不退化 + 残余观察。自构报告,fixture_mode=False 直调。
import sys, math
sys.path.insert(0, "src")
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

def run(tag, mutate=None, fixture=False, expect=None):
    r = legal()
    if fixture:
        r["engineering_fixture"] = True
    if mutate:
        mutate(r)
    out = rec(r)
    verdict = "True" if out["all_consistent"] else "False"
    ok = "?" if expect is None else (
        "OK" if verdict == expect else "UNEXPECTED")
    print(f"[{ok}] {tag}: all_consistent={verdict} "
          f"fixture_mode={out['fixture_mode']}")
    for d in out["threshold_discrepancies"]:
        print("    disc:", d[:130])
    if out["fixture_delegated"]:
        print("    delegated:", out["fixture_delegated"])
    return out

run("ctl legal-with-histogram", expect="True")
run("ctl-fixture", fixture=True, expect="True")

# R6 五反例不退化
def c1ex(r):
    r["once_vs_attempts"]["k_mean_model"] = 0.25
run("R6-C1EX k 1/1 vs 1/4 diff0", c1ex, expect="False")
def c2(r):
    r["once_vs_attempts"]["first_pass_bitwise_check"] = {
        "n_blocks_checked": 3, "n_mismatches": 0}
run("R6-C2 bitwise-missing", c2, expect="False")
def c3(r):
    r["once_vs_attempts"] = {"model_mode": "once",
                             "validation_mode": "attempts"}
run("R6-C3 mode-only", c3, expect="False")
def c4(r):
    for s in r["tail_mirror_bound_integrity"][
            "per_corpus"].values():
        del s["exact_noise_replay_ok"]
run("R6-C4 tail-subkey-missing", c4, expect="False")
def c5(r):
    g = r["global_k_audit"]
    g["verdict"] = "FAIL"; g["pass"] = True
    g["final"]["verdict"] = "PASS"
run("R6-C5 gk FAIL+pass=True", c5, expect="False")

# F1:来源缺件(k_mean 声明在场,aggregate.k_mean 删,k_histogram 留)
def f1(r):
    del r["direct_generator"]["model"]["aggregate"]["k_mean"]
run("F1 source-k_mean-absent", f1, expect="False")

# F1 变体:整个 aggregate 删(R6-N13 形态,现 histogram 也缺)
def f1b(r):
    del r["direct_generator"]["model"]["aggregate"]
    del r["direct_generator"]["validation"]["aggregate"]
run("F1b aggregate-fully-absent", f1b, expect="False")

# F1 fixture:来源缺件如实委托
def f1f(r):
    del r["direct_generator"]["model"]["aggregate"]["k_mean"]
run("F1-fixture source-absent-delegated", f1f, fixture=True)

# F2:声明容差膨胀(来源/派生自洽,差值 0.5 真实超界)
def f2(r):
    o = r["once_vs_attempts"]
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = 2.5
    o["k_mean_validation"] = 2.5
    o["k_abs_diff"] = 0.5
    o["k_tolerance"] = 1.0
run("F2 inflated-declared-tolerance", f2, expect="False")

# F2 变体:直方图缺件
def f2b(r):
    del r["direct_generator"]["model"]["aggregate"]["k_histogram"]
run("F2b histogram-absent", f2b, expect="False")

# F2 变体:直方图非法
def f2c(r):
    r["direct_generator"]["model"]["aggregate"]["k_histogram"] = {
        "a": "x"}
run("F2c histogram-malformed", f2c, expect="False")

# F2 变体:样本不足(每语料须>1)
def f2d(r):
    r["direct_generator"]["model"]["aggregate"]["k_histogram"] = {
        "3": 1}
run("F2d histogram-single-sample", f2d, expect="False")

# F2 fixture:直方图缺件如实委托
def f2e(r):
    del r["direct_generator"]["model"]["aggregate"]["k_histogram"]
run("F2e fixture-histogram-absent", f2e, fixture=True)

# 残余观察:自洽伪造 K 子系统(直方图方差膨胀,均值不变)
def res(r):
    o = r["once_vs_attempts"]
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["k_histogram"] = {
            "1": 5, "5": 5}  # mean 3.0 不变,var(ddof=1)=8
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = 2.5
    o["k_mean_validation"] = 2.5
    o["k_abs_diff"] = 0.5
    pooled = math.sqrt(8 / 10 + 8 / 10)
    o["k_tolerance"] = max(3.0 * pooled, 0.05)
run("RESIDUAL consistent-k-forgery", res)
