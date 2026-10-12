# -*- coding: utf-8 -*-
"""R3-03 参考缓存适用性与细化证据校验(FiniteRepair R3)。

纯数学小规格(horizon 小、网格小,秒级);不重跑全尺寸 DP。
覆盖 reviewer F3:暖缓存非零滑点拒绝(假设检查先于缓存)、合法
缓存可复用、退化细化(单级/重复/倒退/非法数值)不得产出零误差、
错规格 err_bound 不得经手填 qualified、经验差与证明界分型。
"""

from __future__ import annotations

import math

import pytest

from rl_posctl.curriculum import (
    CourseSpec, _DP_CACHE, _dp_key, error_report,
    initial_value, reference_policy, spec_for, tier_validity,
    validate_refinements)

TINY = dict(n_dense=9, n_ext=4, m_quad=4)


def _tiny_spec(**over):
    base = dict(course="c4d2", horizon=3, seed=7)
    base.update(over)
    return CourseSpec(**base)


@pytest.fixture(autouse=True)
def _clean_cache():
    _DP_CACHE.clear()
    yield
    _DP_CACHE.clear()


class TestCacheApplicability:
    def test_slippage_rejected_warm_and_cold(self):
        """F3-a:先用零滑点求参考,再把滑点改 10bps——暖缓存也
        拒绝(假设检查先于缓存;冷缓存同拒,行为一致)。"""
        spec0 = _tiny_spec()
        pol = reference_policy(spec0, **TINY)      # 零滑点,暖缓存
        assert _DP_CACHE
        spec10 = _tiny_spec(slippage_bps=10.0)
        with pytest.raises(ValueError, match="slippage_bps=0"):
            reference_policy(spec10, **TINY)
        # 冷缓存(清空后)同样拒绝
        _DP_CACHE.clear()
        with pytest.raises(ValueError, match="slippage_bps=0"):
            reference_policy(spec10, **TINY)

    def test_cache_key_binds_slippage(self):
        """缓存键绑定全部影响语义/适用性的参数(含 slippage_bps)。"""
        a, b = _tiny_spec(), _tiny_spec(slippage_bps=5.0)
        ka = _dp_key(a, a.horizon, 9, 4, 4, 0.05, 20.0)
        kb = _dp_key(b, b.horizon, 9, 4, 4, 0.05, 20.0)
        assert ka != kb

    def test_legal_cache_reuse_still_works(self):
        """相同合法输入复用缓存照常工作(命中同一对象)。"""
        spec = _tiny_spec()
        p1 = reference_policy(spec, **TINY)
        p2 = reference_policy(spec, **TINY)
        assert p1 is p2

    def test_different_grid_params_not_confused(self):
        """不同网格/求积参数不互相污染(键绑定数值参数)。"""
        spec = _tiny_spec()
        p1 = reference_policy(spec, **TINY)
        p2 = reference_policy(spec, n_dense=17, n_ext=8, m_quad=8)
        assert p1 is not p2
        assert p2["solver_meta"]["n_dense"] == 17


class TestRefinementValidation:
    @pytest.mark.parametrize("bad", [
        (),                                            # 空
        ((321, 64, 40),),                              # 单级
        ((321, 64, 40), (321, 64, 40)),                # 重复
        ((321, 64, 40), (161, 32, 24)),                # 倒退
        ((321, 64, 40), (321, 64, 41), (321, 64, 40)),  # 回落
        ((0, 16, 12), (81, 16, 12)),                   # 非正
        ((81, 16), (161, 32, 24)),                     # 形状
        ((81, 16, 12, 9), (161, 32, 24, 9)),           # 形状
        ((True, 16, 12), (81, 16, 12)),                # bool
        ((81, 16, 12.5), (161, 32, 24)),               # 非整数
        ((81, float("nan"), 12), (161, 32, 24)),       # NaN
        ((81, float("inf"), 12), (161, 32, 24)),       # inf
        ((161, 64, 24), (161, 32, 24)),                # 单维倒退
    ])
    def test_degenerate_refinements_refused(self, bad):
        with pytest.raises(ValueError):
            validate_refinements(bad)
        with pytest.raises(ValueError):
            error_report(_tiny_spec(), refinements=bad)

    def test_no_new_comparison_is_not_zero_error(self):
        """重复级别 = 没做新比较,拒绝而不是 err_bound=0
        (旧:重复 (321,64,40) 两次得 err_bound=0 冒充精确)。"""
        with pytest.raises(ValueError, match="重复"):
            error_report(
                _tiny_spec(),
                refinements=((9, 4, 4), (9, 4, 4)))

    def test_valid_chain_reports_empirical_kind(self):
        rep = error_report(
            _tiny_spec(),
            refinements=((9, 4, 4), (17, 8, 8), (33, 16, 16)))
        assert len(rep["values"]) == 3
        assert len(rep["adjacent_diffs"]) == 2
        assert rep["err_bound"] == max(rep["adjacent_diffs"])
        assert rep["err_bound_kind"] == "empirical_adjacent_diff"
        assert "不是已证明" in rep["err_bound_note"]
        assert all(math.isfinite(v) for v in rep["values"])


class TestQualificationGate:
    def test_err_bound_bad_values_rejected(self):
        """错规格证据(NaN/inf/负/bool)结构性拒绝(R4:bool 也拒)。"""
        spec = _tiny_spec()
        for bad in (float("nan"), float("inf"), -1e-9):
            with pytest.raises(ValueError, match="err_bound"):
                tier_validity(spec, n_episodes=0, err_bound=bad)
        with pytest.raises(ValueError, match="布尔"):
            tier_validity(spec, n_episodes=0, err_bound=False)

    def test_naked_scalar_is_diagnostic_only(self):
        """R4-B:裸标量(含手填 0)只作诊断——qualified=False,
        NOT_ESTABLISHED;不再冒充 empirical_adjacent_diff。"""
        spec = _tiny_spec()
        val = initial_value(spec, **TINY)
        for naked in (0.0, abs(val) / 2, abs(val) * 2 + 1e-9):
            st = tier_validity(spec, n_episodes=0, err_bound=naked)
            assert st["qualified"] is False
            assert st["err_bound_kind"] == "diagnostic_only"
            assert "NOT_ESTABLISHED" in st["qualification_note"]
            assert "dp_err_bound" not in st

    def test_report_object_gives_conditional_judgement(self):
        """完整报告对象(最细级=判定网格)→ 复算绑定通过,
        qualified = value−err>0 的有条件数值开发判断。"""
        spec = _tiny_spec()
        rep = error_report(
            spec, refinements=((81, 16, 12), (161, 32, 24),
                               (321, 64, 40)))
        st = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert st["err_bound_kind"] == "empirical_adjacent_diff"
        assert st["dp_err_bound"] == pytest.approx(
            rep["err_bound"], rel=1e-12)
        assert st["qualified"] == bool(
            st["dp_initial_value"] - rep["err_bound"] > 0.0)
        assert "不构成一般误差保证" in st["qualification_note"]
        assert st["err_evidence"]["verified_by"] == (
            "tier_validity._verify_error_report")
