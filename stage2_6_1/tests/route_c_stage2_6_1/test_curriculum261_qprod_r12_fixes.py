# QProd 返修轮12(R12)钉测试:R11 后 Q1 判据与声明依赖分离(第十一次 NOT_CLOSED)。
# addendum (10) 不变量:原始支撑充分(model 110xK=1 / validation 110xK=4,
# 均值/直方图/冻结界 0.05 全在场,真实差 3)时,实际一致性门的真假不得由
# "冗余差值副本(k_abs_diff)/声明容限是否提供"控制——完整/只删 k_abs_diff/
# 再删 k_tolerance 均须拒;4/1 对称同样;相同删项作用于合法 1/1(真差 0)
# 正例仍须通过;k_modes_consistent=True 在门失败时是坏声明;无 fixture
# 缺必需字段继续拒;R10 三反例(-0.02/0.02/0.5)行为保持。零原生/零生成。
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "route_c_stage2_6_2"))

from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES,
    recompute_audit_semantics_from_report as rec,
)


def _legal_report(kv_val: float) -> dict:
    kv_hist = str(int(kv_val)) if float(kv_val).is_integer() \
        else str(kv_val)
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
                "aggregate": {
                    "k_mean": (1.0 if n == "model" else kv_val),
                    "n_detected": 1, "n_events": 110,
                    "k_histogram": (
                        {"1": 110} if n == "model"
                        else {kv_hist: 110})},
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
            "k_mean_model": 1.0, "k_mean_validation": kv_val,
            "k_abs_diff": abs(1.0 - kv_val), "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES},
    }


def _run(mutate, kv_val=4.0, fixture=True) -> dict:
    r = _legal_report(kv_val)
    mutate(r)
    if fixture:
        r["engineering_fixture"] = True
    return rec(r)


def _del_kad(r):
    r["once_vs_attempts"].pop("k_abs_diff", None)


def _del_kt(r):
    r["once_vs_attempts"].pop("k_tolerance", None)


def _bad_declare(r):
    r["once_vs_attempts"]["k_abs_diff"] = 0.0
    r["once_vs_attempts"]["k_modes_consistent"] = True


def _swap(r):
    ova = r["once_vs_attempts"]
    ova["k_mean_model"], ova["k_mean_validation"] = 4.0, 1.0
    dg = r["direct_generator"]
    dg["model"]["aggregate"].update(
        k_mean=4.0, k_histogram={"4": 110})
    dg["validation"]["aggregate"].update(
        k_mean=1.0, k_histogram={"1": 110})
    ova["k_abs_diff"] = 3.0


def _both(m1, m2):
    def m(r):
        m1(r)
        m2(r)
    return m


def test_r12a_gate_failure_1_over_4_rejects_all_deletions():
    """1/4 真差 3>0.05: 完整(声明 3)/只删 k_abs_diff/再删声明容限
    均拒——门由在场来源重算,与声明副本是否提供无关。"""
    out_full = _run(lambda r: None)
    assert out_full["recomputed"][
        "once_vs_attempts_consistent"] is False
    out_del = _run(_del_kad)
    assert out_del["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("3.0 > k_tolerance 界" in d
               for d in out_del["threshold_discrepancies"])
    out_both = _run(_both(_del_kad, _del_kt))
    assert out_both["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("声明副本是否提供无关" in d
               for d in out_both["threshold_discrepancies"])


def test_r12b_gate_failure_4_over_1_symmetric():
    """4/1 对称: 完整声明 3 拒;删 k_abs_diff 仍拒(门与方向无关)。"""
    assert _run(_swap)["recomputed"][
        "once_vs_attempts_consistent"] is False

    def m(r):
        _swap(r)
        _del_kad(r)
    assert _run(m)["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r12c_legal_1_over_1_same_deletions_pass():
    """合法 1/1 真差 0: 完整 kad=0/删 k_abs_diff/再删声明容限——
    门过(0<=0.05),缺件如实委托,工程委托通过。"""
    assert _run(lambda r: None, kv_val=1.0)[
        "all_consistent"] is True
    out = _run(_del_kad, kv_val=1.0)
    assert out["all_consistent"] is True
    assert any("k_abs_diff" in k for k in out["fixture_delegated"])
    out2 = _run(_both(_del_kad, _del_kt), kv_val=1.0)
    assert out2["all_consistent"] is True
    assert any("k_tolerance" in k for k in out2["fixture_delegated"])


def test_r12d_bad_declaration_flagged_on_gate_failure():
    """门失败(1/4 删 kad)+k_modes_consistent=True 在场:
    坏声明被记矛盾;若另带 k_abs_diff=0 假声明则同时拒。"""
    out = _run(_del_kad)
    assert any("k_modes_consistent=True" in d
               for d in out["threshold_discrepancies"])
    out2 = _run(_bad_declare)
    assert out2["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("K 派生差值矛盾" in d
               for d in out2["threshold_discrepancies"])


def test_r12e_no_fixture_missing_required_rejects():
    """无 fixture: 1/4 删 k_abs_diff 缺必需字段仍拒(工程测试不
    冒充正式授权);合法 1/1 删件无 fixture 亦拒。"""
    assert _run(_del_kad, fixture=False)["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert _run(_del_kad, kv_val=1.0, fixture=False)["recomputed"][
        "once_vs_attempts_consistent"] is False


def test_r12f_r10_triple_counterexamples_hold():
    """R10 三反例(-0.02/0.02/0.5)在删副本变体下保持拒绝
    (R11 来源回退+负绝对差语义不回滚);合法 kad=0 缺件保持通过。"""
    for bad, deleter in ((-0.02, _del_kad), (0.02, _del_kad),
                         (0.5, _both(_del_kad, _del_kt))):
        def m(r, bad=bad, deleter=deleter):
            deleter(r)
            r["once_vs_attempts"]["k_abs_diff"] = bad
        out = _run(m, kv_val=1.0)
        assert out["recomputed"][
            "once_vs_attempts_consistent"] is False, bad
    out0 = _run(lambda r: (
        r["once_vs_attempts"].__setitem__("k_abs_diff", 0.0)),
        kv_val=1.0)
    assert out0["all_consistent"] is True


def test_r12g_independent_sources_sufficient_for_gate():
    """ova 派生均值双删而 dg 原始来源 1/4 在场: 门仍拒
    (支撑=来源侧可得即可,不依赖 ova 副本)。"""
    def m(r):
        del r["once_vs_attempts"]["k_mean_model"]
        del r["once_vs_attempts"]["k_mean_validation"]
        r["once_vs_attempts"]["k_abs_diff"] = 3.0
    out = _run(m)
    assert out["recomputed"][
        "once_vs_attempts_consistent"] is False
    assert any("3.0 > k_tolerance 界" in d
               for d in out["threshold_discrepancies"])
