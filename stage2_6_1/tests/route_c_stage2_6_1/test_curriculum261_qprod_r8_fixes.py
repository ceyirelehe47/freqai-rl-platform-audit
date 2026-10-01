# QProd 返修轮8(R8)钉测试:第七次 NOT_CLOSED 后 Q1 同根收口。
# 无 fixture 纯判定路径(直调 recompute_audit_semantics_from_report,
# fixture_mode=False)一般规则:
# (a) K 输入闭合: histogram 在场时频数须非负整数,Σ频数==aggregate.
#     n_events(生产端每 unique event 恰计一次),histogram 加权均值
#     ==aggregate.k_mean(K 均值与直方图来源共用同一支撑);
# (b) 在场非法≠未提供: 结构/频数非法 histogram 即使 fixture 在场
#     也不得委托为 True(缺高成本叶与坏支撑不是一件事);合法手工
#     输入(含键序重排+全自洽容差)fixture 与无 fixture 均可通过;
# (c) gk 子门支撑: graph_integrity_ok=False 与 verdict=PASS 并存拒
#     (生产规则完整性失败即 FAIL 早退);无 fixture PASS 缺 final
#     必需依据拒(生产端 PASS 必经 tier1/tier2);
# (d) tail 语料覆盖: 预期语料集合=direct_generator 上下文,不由
#     per_corpus 自身键集合自列;缺整份语料支撑无 fixture 拒,
#     fixture 如实委托。
# 旧 R5/R6/R7 反例不退化;零原生/零生成。
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "route_c_stage2_6_2"))

from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES,
    recompute_audit_semantics_from_report as rec,
)


def _legal_report() -> dict:
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


def _run(mutate, fixture=False) -> dict:
    r = _legal_report()
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    return rec(r)


def test_r8_legal_control_both_modes():
    assert rec(_legal_report())["all_consistent"] is True
    out = _run(lambda r: None, fixture=True)
    assert out["all_consistent"] is True
    assert out["fixture_delegated"] == []


def test_r8a_hist_mean_mismatch_rejected():
    """validation 直方图 {4:110} 而声明 k_mean 1/ova 1/差 0/容限
    .05——直方图重算均值 4.0 与来源矛盾,拒。"""
    def m(r):
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"4": 110}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("重算均值" in d
               for d in out["threshold_discrepancies"])


def test_r8a_hist_total_mismatch_rejected():
    """直方图频数总量 109 != n_events 110(含 {1:109})——拒。"""
    def m(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "k_histogram"] = {"1": 109}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("频数总量" in d
               for d in out["threshold_discrepancies"])


def test_r8a_negative_count_rejected():
    """负频数 {1:110, 2:-1} 结构非法——拒(fixture 在场同样拒)。"""
    def m(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "k_histogram"] = {"1": 110, "2": -1}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("频数非法" in d
               for d in out["threshold_discrepancies"])
    # fixture 在场非法同样拒(在场非法≠未提供)
    out_f = _run(m, fixture=True)
    assert out_f["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r8b_fixture_cannot_delegate_illegal_hist():
    """{"not-a-number":110} 无 fixture 拒;fixture 在场同样拒,
    不得委托为 True。"""
    def m(r):
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"not-a-number": 110}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    out_f = _run(m, fixture=True)
    assert out_f["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("在场非法" in d
               for d in out_f["threshold_discrepancies"])


def test_r8b_legal_manual_input_passes_fixture():
    """合法手工输入(双键直方图+冻结容差精确同步)fixture 可通过
    ——不一律拒绝 fixture。"""
    def m(r):
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
        import math
        ova["k_tolerance"] = max(
            3 * math.sqrt(var / 110 + var / 110), 0.05)
    out = _run(m)
    assert out["all_consistent"] is True, out[
        "threshold_discrepancies"]
    out_f = _run(m, fixture=True)
    assert out_f["all_consistent"] is True
    # 键序重排(dict 插入序不同)语义等价
    def m2(r):
        m(r)
        r["direct_generator"]["model"]["aggregate"][
            "k_histogram"] = {"1": 100, "2": 10}
    assert _run(m2)["all_consistent"] is True


def test_r8c_gk_integrity_false_with_pass_rejected():
    """graph_integrity_ok=False 与 verdict=PASS/pass=True/final
    PASS 并存——生产规则完整性失败即 FAIL 早退,拒。"""
    def m(r):
        r["global_k_audit"]["graph_integrity_ok"] = False
    out = _run(m)
    assert out["recomputed"]["global_k_audit_pass"] is False
    assert any("fail closed" in d
               for d in out["threshold_discrepancies"])


def test_r8c_gk_pass_missing_final_rejected():
    """无 fixture 的 PASS 缺 final 必需依据——拒(生产端 PASS 必经
    tier1/tier2);fixture 缺失如实委托。"""
    def m(r):
        del r["global_k_audit"]["final"]
    out = _run(m)
    assert out["recomputed"]["global_k_audit_pass"] is False
    assert any("缺 final" in d
               for d in out["threshold_discrepancies"])
    out_f = _run(m, fixture=True)
    assert "global_k_audit.final" in out_f["fixture_delegated"]


def test_r8c_gk_fail_without_final_allowed():
    """FAIL 早退可无 final(生产端 fail-closed 分支),不因缺 final
    加拒(其他 FAIL 语义照常拒)。"""
    def m(r):
        gk = r["global_k_audit"]
        del gk["final"]
        gk["verdict"] = "FAIL"
        gk["pass"] = False
    out = _run(m)
    assert out["recomputed"]["global_k_audit_pass"] is False
    assert not any("缺 final" in d for d in out[
        "threshold_discrepancies"])


def test_r8d_tail_missing_corpus_rejected():
    """报告两语料而 tail.per_corpus 仅 model——缺整份 validation
    支撑拒;fixture 如实委托。"""
    def m(r):
        del r["tail_mirror_bound_integrity"]["per_corpus"][
            "validation"]
    out = _run(m)
    assert out["recomputed"][
        "tail_mirror_bound_integrity_pass"] is False
    assert any("缺整份 validation" in d
               for d in out["threshold_discrepancies"])
    out_f = _run(m, fixture=True)
    assert any("per_corpus[validation]" in k
               for k in out_f["fixture_delegated"])


def test_r8d_tail_inreport_bad_subkey_still_rejected():
    """在场语料的坏子依据不受语料覆盖检查影响(既有 R5/R6 语义
    保持)。"""
    def m(r):
        r["tail_mirror_bound_integrity"]["per_corpus"][
            "validation"]["exact_noise_replay_ok"] = False
    out = _run(m)
    assert out["recomputed"][
        "tail_mirror_bound_integrity_pass"] is False
