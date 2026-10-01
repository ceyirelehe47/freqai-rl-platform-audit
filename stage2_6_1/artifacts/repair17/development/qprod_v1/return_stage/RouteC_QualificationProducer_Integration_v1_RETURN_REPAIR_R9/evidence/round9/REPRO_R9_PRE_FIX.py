# R9 pre-fix repro: missing-piece must not mask in-present bad support;
# non-finite K; exact n_events total (C18=cec19ae5 bytes)
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


def bad_hist(r):
    # 与 k_mean=1.0 矛盾的 validation 直方图(R8 已单独可拒)
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"4": 110}


def run(tag, mutate, fixture=False):
    r = base_report()
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    out = rec(r)
    gate = {k: v for k, v in out["recomputed"].items() if v is False}
    print("%s fixture=%s all=%s false_gates=%s" % (
        tag, fixture, out["all_consistent"], gate))


# r1: 同一坏直方图 + 删除另一语料(model)直方图, fixture(工程排练
# 自动加标志) —— 缺件不得屏蔽在场坏件
def r1(r):
    bad_hist(r)
    del r["direct_generator"]["model"]["aggregate"]["k_histogram"]
run("r1 bad-hist+other-missing", r1, fixture=True)
run("r1b bad-hist+other-missing nofix", r1)

# r2: 删除一个 ova 派生均值(k_mean_model) —— 派生字段缺失不得
# 跳过仍在场的两份原始直方图闭合
def r2(r):
    bad_hist(r)
    del r["once_vs_attempts"]["k_mean_model"]
run("r2 bad-hist+ova-derived-missing", r2)
run("r2b same with fixture", r2, fixture=True)

# r3: JSON 字符串键 "nan" —— float("nan") 可解析,NaN 比较静默 False
def r3(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"nan": 110}
run("r3 nan-key-hist", r3)
run("r3b nan-key-hist fixture", r3, fixture=True)

# r3c: float('nan') 字面量键(json.loads NaN)
def r3c(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {float("nan"): 110}
run("r3c NaN-float-key", r3c)

# r4: n_events=110.5 —— int() 截断吞小数,不得当 110 相等
def r4(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = 110.5
run("r4 n_events-fractional", r4)

# r5: n_events="110" 字符串 —— 非数值总量不得静默 int()
def r5(r):
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"]["n_events"] = "110"
run("r5 n_events-string", r5)

# r6: k_mean 源为 "nan" —— 直方图有限但源非有限
def r6(r):
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = "nan"
run("r6 k_mean-source-nan", r6)

# r7: ova k_mean_model=NaN —— 派生对 NaN 比较静默绕过
def r7(r):
    r["once_vs_attempts"]["k_mean_model"] = float("nan")
    r["once_vs_attempts"]["k_abs_diff"] = float("nan")
run("r7 ova-km-nan", r7)

# r8: ova k_tolerance=NaN —— 界比较静默 False
def r8m(r):
    r["once_vs_attempts"]["k_tolerance"] = float("nan")
run("r8 ova-ktol-nan", r8m)

# 控制保持
run("ctl legal", lambda r: None)
run("ctl legal fixture", lambda r: None, fixture=True)


def ctl_multi(r):
    import math
    for n in ("model", "validation"):
        r["direct_generator"][n]["aggregate"][
            "k_histogram"] = {"2": 10, "1": 100}
        r["direct_generator"][n]["aggregate"][
            "k_mean"] = (1 * 100 + 2 * 10) / 110
    ova = r["once_vs_attempts"]
    ova["k_mean_model"] = ova["k_mean_validation"] = (
        1 * 100 + 2 * 10) / 110
    v = [1.0] * 100 + [2.0] * 10
    mu = sum(v) / 110
    var = sum((x - mu) ** 2 for x in v) / 109
    ova["k_tolerance"] = max(
        3 * math.sqrt(var / 110 + var / 110), 0.05)


run("ctl multi-key", ctl_multi)
# R8 反例保持
run("ctl-r8 h1 hist-mean-mismatch", bad_hist)
