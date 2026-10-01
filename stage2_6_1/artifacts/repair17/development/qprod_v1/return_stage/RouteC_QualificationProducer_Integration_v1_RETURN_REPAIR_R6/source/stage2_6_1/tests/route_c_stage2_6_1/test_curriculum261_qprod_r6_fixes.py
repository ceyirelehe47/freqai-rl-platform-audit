# QProd 返修轮6(R6)钉测试:第六次 NOT_CLOSED,Q1 同根五洞。
# 无 fixture 纯判定路径(直调 recompute_audit_semantics_from_report,
# fixture_mode=False)一般规则:
# (a) ova K 链完整对账:k_mean_model/validation 必须等于 direct_
#     generator.<corpus>.aggregate.k_mean(来源),k_abs_diff 必须等于
#     |k_mean_model-k_mean_validation|(派生),重算差值>k_tolerance 拒;
#     来源 1/1 而派生 1/4、差值 0 的声明矛盾不得 PASS;
# (b) 无 fixture 缺必需子键(recall_*/abs_diff/tolerance/k_*/
#     fpb.bitwise_ok)不得视为 True(C14 语义回归:bitwise_ok 缺失、
#     ova 只余 mode 键,C15 放行=退化);fixture 双重态下缺失键如实
#     列入 fixture_delegated,在场键仍对账;
# (c) tail per_corpus 布尔子依据(exact_noise_replay_ok/
#     bounds_ok_all_positions)缺失≠True,不能只靠 ok=True;
# (d) gk 分层一致:pass==(verdict=="PASS")(生产规则),final.verdict
#     在场须等顶层 verdict;FAIL+pass=True 拒;缺 verdict/pass 拒。
# 合法对照全键在场通过;R5 三反例+R4 四反例不退化。零原生/零生成。
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "route_c_stage2_6_2"))

from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES,
    recompute_audit_semantics_from_report as rec,
)


def _legal_report() -> dict:
    """支撑完整的正式式报告(无 fixture 标记,生产端真实键形态)。"""
    return {
        "p_contract": 0.5,
        "monte_carlo": {"p_hat": 0.5, "tolerance": 0.001},
        "direct_generator": {
            n: {
                "block_cluster": {"se": 0.01, "ci95": [0.45, 0.55]},
                "empirical_recall": 0.5,
                "analytic_conditional": 0.5,
                "diff_tolerance": 0.03,
                "aggregate": {"k_mean": 1.0, "n_detected": 1,
                              "n_events": 2,
                              "k_histogram": {"1": 2}},
                "replay_ok": True, "bounds_ok": True,
                "cue_table_consistent_across_rungs": True,
                "max_replay_abs_error": 0.0,
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


def _run(mutate) -> dict:
    r = _legal_report()
    mutate(r)
    return rec(r)


def test_r6_legal_control_passes():
    out = rec(_legal_report())
    assert out["all_consistent"] is True, out[
        "threshold_discrepancies"]
    assert out["fixture_mode"] is False
    assert out["fixture_delegated"] == []


def test_r6a_k_source_and_derived_mismatch_rejected():
    """来源 k_mean 1/1、派生声明 1/4、差值 0 → K 链矛盾拒。"""
    def m(r):
        ova = r["once_vs_attempts"]
        ova["k_mean_model"] = 0.25
        ova["k_abs_diff"] = 0.0  # 与 |0.25-1.0|=0.75 矛盾
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    drift = " ".join(out["threshold_discrepancies"])
    assert "K 来源不一致" in drift or "K 派生差值矛盾" in drift


def test_r6a_k_diff_recomputed_beyond_tolerance_rejected():
    """k_abs_diff/k_modes_consistent 自洽但来源均值差超容差 → 拒。"""
    def m(r):
        ova = r["once_vs_attempts"]
        ova["k_mean_validation"] = 0.5
        ova["k_abs_diff"] = 0.5  # =|1.0-0.5| 派生自洽
        r["direct_generator"]["validation"]["aggregate"][
            "k_mean"] = 0.5  # 来源也自洽
        # 但重算差值 0.5 > k_tolerance 0.05 → 数值判据拒
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("k_tolerance" in d
               for d in out["threshold_discrepancies"])


def test_r6b_bitwise_ok_missing_rejected_no_fixture():
    """无 fixture:fpb 在场但 bitwise_ok 键缺失 → 拒(缺失≠True)。"""
    def m(r):
        r["once_vs_attempts"]["first_pass_bitwise_check"] = {
            "n_blocks_checked": 2, "n_mismatches": 0}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("bitwise_ok" in d and "缺" in d
               for d in out["threshold_discrepancies"])


def test_r6b_ova_only_mode_keys_rejected_no_fixture():
    """无 fixture:ova 只余 mode 键(部分支撑) → 拒。"""
    def m(r):
        r["once_vs_attempts"] = {
            "model_mode": "once", "validation_mode": "attempts"}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("缺必需子依据" in d
               for d in out["threshold_discrepancies"])


def test_r6b_tail_bool_subkeys_missing_rejected():
    """tail per_corpus 布尔子依据缺失+ok=True → 拒。"""
    def m(r):
        for sub in r["tail_mirror_bound_integrity"][
                "per_corpus"].values():
            del sub["exact_noise_replay_ok"]
    out = _run(m)
    assert out["recomputed"][
        "tail_mirror_bound_integrity_pass"] is False


def test_r6c_gk_verdict_fail_pass_true_rejected():
    """gk verdict=FAIL 而 pass=True/final PASS → 分层矛盾拒。"""
    def m(r):
        gk = r["global_k_audit"]
        gk["verdict"] = "FAIL"
        gk["final"]["verdict"] = "PASS"
    out = _run(m)
    assert out["recomputed"]["global_k_audit_pass"] is False
    assert any("生产规则" in d or "分层矛盾" in d
               for d in out["threshold_discrepancies"])


def test_r6c_gk_missing_verdict_pass_rejected_no_fixture():
    """无 fixture:gk 缺 verdict/pass → 缺件拒。"""
    def m(r):
        gk = r["global_k_audit"]
        del gk["verdict"]
        del gk["pass"]
    out = _run(m)
    assert out["recomputed"]["global_k_audit_pass"] is False


def test_r6c_gk_indeterminate_still_rejected():
    """INDETERMINATE 拒控制保留(不是不决≠已经 PASS)。"""
    def m(r):
        gk = r["global_k_audit"]
        gk["verdict"] = "INDETERMINATE"
        gk["pass"] = False
        gk["final"]["verdict"] = "INDETERMINATE"
    out = _run(m)
    assert out["recomputed"][
        "global_k_audit_not_indeterminate"] is False
    assert out["recomputed"]["global_k_audit_pass"] is False


def test_r6_fixture_delegation_lists_missing_keys():
    """fixture 双重态:ova 缺件如实列入 fixture_delegated(标注,
    不是静默换 True);在场键仍对账。"""
    r = _legal_report()
    r["engineering_fixture"] = True
    del r["once_vs_attempts"]["k_mean_model"]
    out = rec(r)
    assert "once_vs_attempts.k_mean_model" in out[
        "fixture_delegated"]
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is True


def test_r6_fixture_cannot_mask_inreport_k_contradiction():
    """fixture 下在场 K 矛盾数值仍拒(委托不可掩盖在场坏数值)。"""
    r = _legal_report()
    r["engineering_fixture"] = True
    r["once_vs_attempts"]["k_mean_model"] = 0.25  # 与来源 1.0 矛盾
    out = rec(r)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False


# ---------------------------------------------------------------- R7
def test_r7_k_source_deleted_forged_rejected():
    """R7(review F1):k_mean 声明在场而 dg.aggregate.k_mean 缺件
    → 无 fixture 拒(不静默跳过来源对账);伪造 K 声明不得 PASS。"""
    def m(r):
        for n in ("model", "validation"):
            del r["direct_generator"][n]["aggregate"]["k_mean"]
        ova = r["once_vs_attempts"]
        ova["k_mean_model"] = 0.0
        ova["k_mean_validation"] = 0.0
        ova["k_abs_diff"] = 0.0
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("K 来源缺失" in d or "缺件" in d
               for d in out["threshold_discrepancies"])


def test_r7_k_tolerance_pinned_to_frozen_formula():
    """R7(review F2):k_tolerance 必须等于冻结公式 max(3*pooled_se,
    0.05)(pooled se 由 k_histogram 重算,ddof=1 与生产同式);膨胀
    容差漂移拒,重算差值以冻结值为界。"""
    def m(r):
        for n, km, hist in (("model", 3.0, {"3": 2}),
                            ("validation", 2.5, {"2": 1, "3": 1})):
            agg = r["direct_generator"][n]["aggregate"]
            agg["k_mean"] = km
            agg["k_histogram"] = hist
        ova = r["once_vs_attempts"]
        ova["k_mean_model"] = 3.0
        ova["k_mean_validation"] = 2.5
        ova["k_abs_diff"] = 0.5  # 派生自洽
        ova["k_tolerance"] = 1.0  # 膨胀(冻结公式值小得多)
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("K 容差漂移" in d
               for d in out["threshold_discrepancies"])


def test_r7_k_histogram_missing_rejected_no_fixture():
    """R7:k_histogram 缺件 → 冻结公式无法重算,无 fixture 拒。"""
    def m(r):
        for n in ("model", "validation"):
            del r["direct_generator"][n]["aggregate"][
                "k_histogram"]
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("k_histogram" in d
               for d in out["threshold_discrepancies"])


def test_r7_fixture_k_source_missing_delegated():
    """fixture 双重态:K 来源/histogram 缺件如实委托,不静默拒。"""
    r = _legal_report()
    r["engineering_fixture"] = True
    for n in ("model", "validation"):
        del r["direct_generator"][n]["aggregate"]["k_mean"]
        del r["direct_generator"][n]["aggregate"]["k_histogram"]
    out = rec(r)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is True
    assert any("source_missing" in k
               for k in out["fixture_delegated"])
    assert any(k.endswith("k_tolerance_frozen")
               for k in out["fixture_delegated"])
