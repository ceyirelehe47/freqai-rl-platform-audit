# QProd 返修轮10(R10)钉测试:R9 后 Q1 缺件组合复验(第九次 NOT_CLOSED)。
# addendum (8) 同根不变量:
# (a) 基础检查不依赖无关字段是否提供——删除整个 once_vs_attempts
#     (fixture 委托缺件)时,在场坏直方图("nan" 键/均值矛盾/小数
#     n_events)仍必须拒绝;
# (b) ova 单个派生均值 NaN/Inf 在场即拒(另一侧在场或被删除都拒),
#     "两个齐全才检查"不是单字段合法性;
# (c) n_events=-1 是 len(events) 计数语义,直方图在场拒,删除同侧
#     直方图仍拒(有限整数检查不能代替合法计数检查);
# (d) 合法缺 ova/缺单侧派生值/缺 hist 的既有工程委托保持,委托
#     只覆盖真正未提供的部分,不清除在场坏输入。
# 零原生/零生成。
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


def test_r10_legal_controls_both_modes():
    assert _run(lambda r: None)["all_consistent"] is True
    assert _run(lambda r: None, fixture=True)[
        "all_consistent"] is True


def test_r10a_no_ova_does_not_mask_bad_histogram():
    """删除整个 once_vs_attempts(fixture 委托缺 ova)时,在场坏
    validation 直方图("nan" 字符串键/重算均值 4 对来源 1/n_events
    小数 110.5)仍必须拒绝;基础检查不依赖无关字段是否提供。"""
    def m_base(r):
        del r["once_vs_attempts"]

    def m_nan(r):
        m_base(r)
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"nan": 110}
    out = _run(m_nan, fixture=True)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("结构/频数非法" in d
               for d in out["threshold_discrepancies"])

    def m_mean4(r):
        m_base(r)
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"4": 110}
    out2 = _run(m_mean4, fixture=True)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("重算均值" in d
               for d in out2["threshold_discrepancies"])

    def m_frac(r):
        m_base(r)
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "n_events"] = 110.5
    out3 = _run(m_frac, fixture=True)
    assert out3["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("110.5" in d for d in out3["threshold_discrepancies"])


def test_r10b_single_ova_derived_mean_nonfinite_rejected():
    """ova 单个派生均值 NaN("nan" 字符串/NaN 字面量)在场即拒:
    另一侧在场或被删除均拒——单字段合法性不以另一字段提供
    为前提。"""
    def m_km(r):
        r["once_vs_attempts"]["k_mean_model"] = float("nan")
    out = _run(m_km, fixture=True)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m_km_del(r):
        m_km(r)
        del r["once_vs_attempts"]["k_mean_validation"]
    out2 = _run(m_km_del, fixture=True)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("k_mean_model" in d and "非有限" in d
               for d in out2["threshold_discrepancies"])

    def m_kv_del(r):
        r["once_vs_attempts"]["k_mean_validation"] = "nan"
        del r["once_vs_attempts"]["k_mean_model"]
    out3 = _run(m_kv_del, fixture=True)
    assert out3["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r10c_negative_n_events_rejected_both_ways():
    """n_events=-1: 直方图在场拒;删除同侧直方图(缺件委托)仍拒
    ——len(events) 计数语义,有限整数检查不能代替合法计数。"""
    def m_base(r):
        r["direct_generator"]["validation"]["aggregate"][
            "n_events"] = -1
    out = _run(m_base, fixture=True)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m_del_hist(r):
        m_base(r)
        del (r["direct_generator"]["validation"]["aggregate"]
             ["k_histogram"])
    out2 = _run(m_del_hist, fixture=True)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("负计数" in d and "-1" in d
               for d in out2["threshold_discrepancies"])


def test_r10d_legal_delegations_preserved():
    """合法缺 ova/缺单侧派生值 fixture 委托保持;无 fixture 缺件
    拒;委托不清除在场坏输入(坏件+缺 ova 组合仍拒)。"""
    def m_no_ova(r):
        del r["once_vs_attempts"]
    out = _run(m_no_ova, fixture=True)
    assert out["all_consistent"] is True
    assert any("once_vs_attempts" in k
               for k in out["fixture_delegated"])
    assert _run(m_no_ova)["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m_single_km(r):
        del r["once_vs_attempts"]["k_mean_model"]
    out2 = _run(m_single_km, fixture=True)
    assert out2["all_consistent"] is True

    def m_bad_plus_no_ova(r):
        m_no_ova(r)
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"4": 110}
    out3 = _run(m_bad_plus_no_ova, fixture=True)
    assert out3["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r10e_prior_rounds_hold():
    """R8/R9 反例不退化(ova 在场的坏直方图/非有限键/小数总量
    /缺件屏蔽组合)。"""
    def m_bad_hist(r):
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"4": 110}
    assert _run(m_bad_hist)["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m_mask(r):
        m_bad_hist(r)
        del (r["direct_generator"]["model"]["aggregate"]
             ["k_histogram"])
    assert _run(m_mask, fixture=True)["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m_frac(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "n_events"] = 110.5
    assert _run(m_frac)["recomputed"][
        "once_vs_attempts_consistent"] is False
