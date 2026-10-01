# QProd 返修轮9(R9)钉测试:R8 后 K 判定限定复验(第八次 NOT_CLOSED)。
# 无 fixture 纯判定路径(直调 recompute_audit_semantics_from_report,
# fixture_mode=False)与 fixture(工程排练自动补标志)双模式一般规则:
# (a) 缺件不可屏蔽在场坏件: 每份在场 K 支撑先独立验证(基础合法性/
#     内部关系)再处理缺件/跨语料完整性——同一坏直方图在删除另一
#     语料直方图(fixture 委托缺件)或删除 ova 派生均值后仍必须因
#     在场坏数据拒绝;委托不传染到在场坏输入;
# (b) 非有限数: JSON 字符串键 "nan"/NaN 字面量/k_mean 源 "nan"/
#     ova 派生均值或容差 NaN/Inf 不得使比较式静默 False 绕过;
# (c) 精确总量: Σ频数==n_events 用精确比较,int() 截断不得吞小数
#     (110.5 拒),非数值 n_events(字符串)拒;
# (d) 合法完整/多键/键序重排正控制与 R8 反例保持;明确缺失的高
#     成本输入 fixture 委托保持(k_tolerance_frozen 委托名与 R7 兼容)。
# 零原生/零生成。
from __future__ import annotations

import math
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


def _bad_hist(r):
    r["direct_generator"]["validation"]["aggregate"][
        "k_histogram"] = {"4": 110}


def _run(mutate, fixture=False) -> dict:
    r = _legal_report()
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    return rec(r)


def test_r9_legal_controls_both_modes():
    assert rec(_legal_report())["all_consistent"] is True
    out = _run(lambda r: None, fixture=True)
    assert out["all_consistent"] is True
    assert out["fixture_delegated"] == []


def test_r9a_missing_other_does_not_mask_bad_hist():
    """同一坏直方图({4:110} 对 k_mean 1)+删除另一语料(model)
    直方图——fixture(工程排练自动加标志)与无 fixture 均必须因
    在场坏数据拒绝;缺件委托不传染到在场坏输入。"""
    def m(r):
        _bad_hist(r)
        del (r["direct_generator"]["model"]["aggregate"]
             ["k_histogram"])
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("重算均值" in d
               for d in out["threshold_discrepancies"])
    out_f = _run(m, fixture=True)
    assert out_f["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("重算均值" in d
               for d in out_f["threshold_discrepancies"])


def test_r9a_ova_derived_missing_does_not_skip_hists():
    """删除 ova.k_mean_model 派生均值——不得跳过仍在场的两份
    原始直方图闭合(坏件仍拒;合法件不误伤)。"""
    def m(r):
        _bad_hist(r)
        del r["once_vs_attempts"]["k_mean_model"]
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("重算均值" in d
               for d in out["threshold_discrepancies"])
    out_f = _run(m, fixture=True)
    assert out_f["recomputed"][
        "once_vs_attempts_consistent"] is False
    # 合法直方图+删派生均值: fixture 委托保持,不误伤
    def m2(r):
        del r["once_vs_attempts"]["k_mean_model"]
    out2 = _run(m2, fixture=True)
    assert out2["all_consistent"] is True
    assert any("k_mean_model" in k
               for k in out2["fixture_delegated"])


def test_r9b_nonfinite_key_rejected_both_modes():
    """JSON 字符串键 "nan" 与 NaN 字面量键——float() 可解析但
    非有限,不得使比较式静默 False 绕过;fixture 亦拒。"""
    def m_str(r):
        r["direct_generator"]["validation"]["aggregate"][
            "k_histogram"] = {"nan": 110}
    out = _run(m_str)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("非有限" in d
               for d in out["threshold_discrepancies"])
    out_f = _run(m_str, fixture=True)
    assert out_f["recomputed"][
        "once_vs_attempts_consistent"] is False
    out2 = _run(lambda r: r["direct_generator"]["validation"]
                ["aggregate"].__setitem__(
                    "k_histogram", {float("nan"): 110}))
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r9b_nonfinite_k_mean_source_rejected():
    """直方图有限但 k_mean 源为 "nan"——来源非有限拒。"""
    out = _run(lambda r: r["direct_generator"]["validation"]
               ["aggregate"].__setitem__("k_mean", "nan"))
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("非有限" in d or "非数值" in d
               for d in out["threshold_discrepancies"])


def test_r9b_nonfinite_ova_values_rejected():
    """ova k_mean_model/k_tolerance NaN——声明门与来源对账先验
    非有限,比较式不得静默 False。"""
    def m_km(r):
        r["once_vs_attempts"]["k_mean_model"] = float("nan")
        r["once_vs_attempts"]["k_abs_diff"] = float("nan")
    out = _run(m_km)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    out2 = _run(lambda r: r["once_vs_attempts"].__setitem__(
        "k_tolerance", float("nan")))
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r9c_fractional_n_events_rejected():
    """直方图总数 110 与 n_events=110.5——精确比较,int() 截断
    不得吞小数当相等。"""
    def m(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "n_events"] = 110.5
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("频数总量" in d and "n_events=110.5" in d
               for d in out["threshold_discrepancies"])


def test_r9c_string_n_events_rejected():
    """n_events="110" 字符串——非数值总量不得静默 int() 通过。"""
    def m(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "n_events"] = "110"
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r9c_integer_111_control_rejected():
    """整数 111 不等控制(总量 110 对 111)拒。"""
    def m(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "n_events"] = 111
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r9d_fractional_count_rejected():
    """小数频数 {1:109.5}——非整数频数拒。"""
    def m(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "k_histogram"] = {"1": 109.5}
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    out_f = _run(m, fixture=True)
    assert out_f["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r9d_legal_multirkey_controls_pass():
    """合法多键(冻结容差同步)与键序重排双模式通过;明确缺失的
    高成本输入 fixture 委托保持(k_tolerance_frozen 名与 R7 兼容)。"""
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
        ova["k_tolerance"] = max(
            3 * math.sqrt(var / 110 + var / 110), 0.05)
    assert _run(m)["all_consistent"] is True
    assert _run(m, fixture=True)["all_consistent"] is True
    # 键序重排语义等价
    def m2(r):
        m(r)
        r["direct_generator"]["model"]["aggregate"][
            "k_histogram"] = {"1": 100, "2": 10}
    assert _run(m2)["all_consistent"] is True

    def mdel(r):
        for n in ("model", "validation"):
            del (r["direct_generator"][n]["aggregate"]
                 ["k_histogram"])
    out_f = _run(mdel, fixture=True)
    assert out_f["all_consistent"] is True
    assert "once_vs_attempts.k_tolerance_frozen" in \
        out_f["fixture_delegated"]
    assert _run(mdel)["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r9e_r8_regressions_hold():
    """R8 反例不退化:均值矛盾/总量不符/负频数(含 fixture)。"""
    out = _run(_bad_hist)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    def m_neg(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "k_histogram"] = {"1": 110, "2": -1}
    out2 = _run(m_neg)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert _run(m_neg, fixture=True)["recomputed"][
        "once_vs_attempts_consistent"] is False
    def m_tot(r):
        for n in ("model", "validation"):
            r["direct_generator"][n]["aggregate"][
                "k_histogram"] = {"1": 109}
    assert _run(m_tot)["recomputed"][
        "once_vs_attempts_consistent"] is False
