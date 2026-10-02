# QProd 返修轮11(R11)钉测试:R10 后 Q1 派生差值依赖复验(第十次 NOT_CLOSED)。
# addendum (9) 不变量:原始两语料 k_mean=1/直方图 {"1":110}/n_events=110 在场
# 即可算绝对差 0 与冻结 K 容限——ova 派生均值(k_mean_*)只是冗余副本,
# 删一个副本(或再删自报 k_tolerance)不得屏蔽在场矛盾 k_abs_diff;
# k_abs_diff=0 相同缺件为合法工程委托须通过。零原生/零生成。
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


def _run(mutate, fixture=True) -> dict:
    r = _legal_report()
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    return rec(r)


def _kad(v):
    def m(r):
        r["once_vs_attempts"]["k_abs_diff"] = v
    return m


def _del_kv(r):
    del r["once_vs_attempts"]["k_mean_validation"]


def _del_km(r):
    del r["once_vs_attempts"]["k_mean_model"]


def _del_kt(r):
    del r["once_vs_attempts"]["k_tolerance"]


def _both(m1, m2):
    def m(r):
        m1(r)
        m2(r)
    return m


def test_r11a_negative_abs_diff_rejected_despite_missing_copy():
    """k_abs_diff=-0.02: 完整字段拒;只删 k_mean_validation(或
    k_mean_model)仍拒——负绝对差自身非法且来源侧可重算 0。"""
    for deleter in (_del_kv, _del_km):
        out = _run(_both(_kad(-0.02), deleter))
        assert out["recomputed"][
            "once_vs_attempts_consistent"] is False
        ds = " ".join(out["threshold_discrepancies"])
        assert "k_abs_diff=-0.02" in ds
    out_full = _run(_kad(-0.02))
    assert out_full["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r11b_small_contradiction_rejected_despite_missing_copy():
    """k_abs_diff=0.02 与来源实际差值 0 矛盾:完整拒;删任一侧
    派生均值仍拒(回退 direct_generator 原始来源重算)。"""
    for deleter in (_del_kv, _del_km):
        out = _run(_both(_kad(0.02), deleter))
        assert out["recomputed"][
            "once_vs_attempts_consistent"] is False
        assert any(
            "0.02" in d and "派生差值矛盾" in d
            for d in out["threshold_discrepancies"])
    assert _run(_kad(0.02))["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r11c_large_contradiction_survives_tolerance_deletion():
    """k_abs_diff=0.5: 完整拒;删派生 validation 均值+自报
    k_tolerance 仍拒——冻结界可从直方图重算,自报缺失不改变界,
    在场矛盾不得变 PASS。"""
    def m(r):
        _kad(0.5)(r)
        _del_kv(r)
        _del_kt(r)
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("0.5" in d for d in out["threshold_discrepancies"])
    assert _run(_kad(0.5))["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r11d_legal_zero_abs_diff_delegation_passes():
    """k_abs_diff=0 相同缺件:合法既有工程委托通过(单侧删除/
    再删自报容限);两侧顺序无关。"""
    out = _run(_both(_kad(0.0), _del_kv))
    assert out["all_consistent"] is True
    out2 = _run(_both(_kad(0.0), _del_km))
    assert out2["all_consistent"] is True

    def m(r):
        _kad(0.0)(r)
        _del_kv(r)
        _del_kt(r)
    out3 = _run(m)
    assert out3["all_consistent"] is True
    assert any("k_tolerance" in k
               for k in out3["fixture_delegated"])


def test_r11e_no_fixture_missing_required_still_rejects():
    """无 fixture 缺必需字段(k_mean_validation)仍拒;工程测试
    不冒充正式授权。"""
    out = _run(_both(_kad(0.5), _del_kv), fixture=False)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    out2 = _run(_kad(0.02), fixture=False)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False

def test_r11f_both_sources_missing_delegates_or_rejects():
    """k_abs_diff 在场而 ova 副本+dg 原始来源双侧缺件:fixture
    如实委托(derivation_missing);无 fixture 拒(缺失≠True);
    判定不以缺件采信声明值。"""
    def m(r):
        del r["once_vs_attempts"]["k_mean_validation"]
        del (r["direct_generator"]["validation"]["aggregate"]
             ["k_mean"])
        # 删自报 k_tolerance:排除旧自洽检查
        # (k_abs_diff<=k_tolerance) 对本用例的先行拦截,
        # 精确覆盖双侧来源缺件的重算委托路径。
        del r["once_vs_attempts"]["k_tolerance"]
        r["once_vs_attempts"]["k_abs_diff"] = 0.4
    out = _run(m, fixture=True)
    # 双侧真缺=无法重算,fixture 如实委托并按声明值采信
    # (R5 双重态语义;dg 在场时缺副本不再屏蔽矛盾=上方各测)
    assert out["all_consistent"] is True
    assert any("derivation_missing" in k
               for k in out["fixture_delegated"])
    out2 = _run(m, fixture=False)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r11g_prior_rounds_hold():
    """前轮反例不退化:R10 六洞(no-ova 坏直方图/单键 NaN/
    负 n_events)+合法完整正例。"""
    assert _run(lambda r: None)["all_consistent"] is True
    assert _run(lambda r: None, fixture=False)[
        "all_consistent"] is True

    def m1(r):
        del r["once_vs_attempts"]
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"4": 110}
    assert _run(m1)["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m2(r):
        r["once_vs_attempts"]["k_mean_model"] = float("nan")
    assert _run(m2)["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m3(r):
        r["direct_generator"]["validation"]["aggregate"][
            "n_events"] = -1
        del (r["direct_generator"]["validation"]["aggregate"]
             ["k_histogram"])
    assert _run(m3)["recomputed"][
        "once_vs_attempts_consistent"] is False
