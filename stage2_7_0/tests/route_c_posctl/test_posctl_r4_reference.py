# -*- coding: utf-8 -*-
"""R4-B C4 数值证据消费(FiniteRepair R4)。

C1:tier_validity 不再凭裸标量(含手填 0/False)给出
qualified=true + empirical_adjacent_diff;证据必须绑定可复算
报告(细化链/规格指纹/判定网格/重算一致)。正例(合法真实
报告)继续产出有条件数值判断,不为拒伪造而封死。
纯数学(horizon3 小规格+一次 321 级),零生成零训练零 env 步。
"""

from __future__ import annotations

import copy

import pytest

from rl_posctl.curriculum import (
    CourseSpec, _DP_CACHE, error_report, initial_value,
    tier_validity)


def _tiny_spec(**over):
    base = dict(course="c4d2", horizon=3, seed=7)
    base.update(over)
    return CourseSpec(**base)


@pytest.fixture(autouse=True)
def _clean_cache():
    _DP_CACHE.clear()
    yield
    _DP_CACHE.clear()


def _valid_report(spec):
    return error_report(
        spec, refinements=((81, 16, 12), (161, 32, 24),
                           (321, 64, 40)))


class TestNakedScalarRejectedAsEvidence:
    def test_handfill_zero_not_qualified(self):
        """probe handfill_zero 反例:err_bound=0.0 无任何细化
        证据 → 不再 qualified=true / 贴 empirical 标签。"""
        st = tier_validity(_tiny_spec(), n_episodes=0,
                           err_bound=0.0)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "diagnostic_only"
        assert "NOT_ESTABLISHED" in st["qualification_note"]
        assert "dp_err_bound" not in st

    def test_handfill_bool_refused(self):
        """probe handfill_bool 反例:False 不是误差证据,拒绝。"""
        with pytest.raises(ValueError, match="布尔"):
            tier_validity(_tiny_spec(), n_episodes=0,
                          err_bound=False)
        with pytest.raises(ValueError, match="布尔"):
            tier_validity(_tiny_spec(), n_episodes=0,
                          err_bound=True)

    def test_nonfinite_negative_refused(self):
        for bad in (float("nan"), float("inf"), -1e-12):
            with pytest.raises(ValueError, match="err_bound"):
                tier_validity(_tiny_spec(), n_episodes=0,
                              err_bound=bad)

    def test_positive_naked_scalar_also_diagnostic(self):
        """任意手填正数同样只作诊断(不知道来自哪个规格/细化)。"""
        val = initial_value(_tiny_spec())
        st = tier_validity(_tiny_spec(), n_episodes=0,
                           err_bound=abs(val) / 2)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "diagnostic_only"


class TestReportEvidenceBinding:
    def test_valid_report_gives_conditional_judgement(self):
        """正例:真实 error_report(最细级=判定网格)→ 复算绑定
        通过,qualified = value−err>0 的有条件数值开发判断。"""
        spec = _tiny_spec()
        rep = _valid_report(spec)
        st = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert st["err_bound_kind"] == "empirical_adjacent_diff"
        assert st["dp_err_bound"] == pytest.approx(
            rep["err_bound"], rel=1e-12)
        expected = bool(
            st["dp_initial_value"] - rep["err_bound"] > 0.0)
        assert st["qualified"] is expected
        ev = st["err_evidence"]
        assert ev["judged_grid"] == [321, 64, 40]
        assert ev["n_levels"] == 3
        assert ev["verified_by"] == (
            "tier_validity._verify_error_report")

    def test_tampered_err_bound_not_established(self):
        """手改 err_bound(与值序列复算不符)→ NOT_ESTABLISHED。"""
        spec = _tiny_spec()
        rep = _valid_report(spec)
        tampered = copy.deepcopy(rep)
        tampered["err_bound"] = 0.0
        st = tier_validity(spec, n_episodes=0,
                           err_bound=tampered)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "unverified_report"
        assert "err_bound 与 max|相邻差| 复算不符" in (
            st["qualification_note"])

    def test_tampered_diffs_not_established(self):
        spec = _tiny_spec()
        rep = _valid_report(spec)
        tampered = copy.deepcopy(rep)
        tampered["adjacent_diffs"] = [0.0, 0.0]
        st = tier_validity(spec, n_episodes=0,
                           err_bound=tampered)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "unverified_report"

    def test_wrong_spec_report_not_establishished(self):
        """错规格证据:别的 spec 的报告不得给本规格结论。"""
        rep = _valid_report(_tiny_spec(seed=99))
        st = tier_validity(_tiny_spec(), n_episodes=0,
                           err_bound=rep)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "unverified_report"
        assert "spec_key" in st["qualification_note"]

    def test_finest_level_not_judging_grid_not_established(self):
        """细化链最细级 ≠ 判定网格(321/64/40):误差基准与被
        判定值不同 → NOT_ESTABLISHED(不冒充覆盖)。"""
        spec = _tiny_spec()
        rep = error_report(
            spec, refinements=((9, 4, 4), (17, 8, 8),
                               (33, 16, 16)))
        st = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "unverified_report"
        assert "最细级" in st["qualification_note"]

    def test_incomplete_report_structure_not_established(self):
        """结构残缺(非 error_report 输出)→ NOT_ESTABLISHED。"""
        st = tier_validity(_tiny_spec(), n_episodes=0,
                           err_bound={"err_bound": 0.0})
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "unverified_report"
        assert "结构不完整" in st["qualification_note"]

    def test_report_values_must_be_finite(self):
        spec = _tiny_spec()
        rep = _valid_report(spec)
        rep["values"][0] = float("nan")
        st = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert st["qualified"] is False
        assert st["err_bound_kind"] == "unverified_report"
