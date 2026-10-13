# -*- coding: utf-8 -*-
"""R5-B 整条细化证据 + 资源前拒绝(FiniteRepair R5;reviewer C4)。

反例源:_verify_error_report 只绑定最细级值,前级来件值直接
参与差复算——保持末级真实、改写粗级的自洽报告(伪零差/伪大
差)被接纳;diffs 数组无逐元素有限性检查(NaN 借比较语义
False 逃逸);tier_validity 样本循环先于 err_bound 检查执行
(错误输入先做生成/env 工作)。

R5:全部级别由真实数学路径复算(身份绑定 _DP_CACHE 只含真实
求解产物,来件值不回填);diffs/judged_grid 数字槽位逐元素
类型与有限性校验;证据核验先于任何生成/env 工作。零真实
生成、零 env 步:合法路径可达性用记录型哨兵替身证明。
"""

from __future__ import annotations

import copy
import json
import math

import pytest

import rl_posctl.curriculum as c
from rl_posctl.curriculum import (
    CourseSpec, _DP_CACHE, error_report, initial_value, tier_validity)

TINY = dict(course="c4d2", horizon=3, seed=7)
REFS = ((81, 16, 12), (161, 32, 24), (321, 64, 40))


def _tiny_spec(**over):
    base = dict(TINY)
    base.update(over)
    return CourseSpec(**base)


@pytest.fixture(autouse=True)
def _clean_cache():
    _DP_CACHE.clear()
    yield
    _DP_CACHE.clear()


def _valid_report(spec):
    return error_report(spec, refinements=REFS)


class TestForgedCoarseLevelsRejected:
    """保持最细级真实、改写前级 → 不得作为可信证据(整链复算)。"""

    def _forged(self, spec, rep):
        v = rep["values"][-1]
        f = copy.deepcopy(rep)
        f.update(values=[v, v, v], adjacent_diffs=[0.0, 0.0],
                 err_bound=0.0)
        return f

    def test_coarse_set_to_finest_zero_gap_rejected(self):
        spec = _tiny_spec()
        st = tier_validity(
            spec, n_episodes=0,
            err_bound=self._forged(spec, _valid_report(spec)))
        assert st["err_bound_kind"] == "unverified_report"
        assert st["qualified"] is False
        assert "dp_err_bound" not in st
        assert "复算" in st["qualification_note"]

    def test_coarse_large_gap_cannot_flip_verdict(self):
        """伪大差也不得改写判定方向(不只是假阳性)。"""
        spec = _tiny_spec()
        rep = _valid_report(spec)
        v = rep["values"][-1]
        f = copy.deepcopy(rep)
        f.update(values=[v + 1.0, v, v], adjacent_diffs=[1.0, 0.0],
                 err_bound=1.0)
        st = tier_validity(spec, n_episodes=0, err_bound=f)
        assert st["err_bound_kind"] == "unverified_report"
        assert "复算" in st["qualification_note"]

    def test_forged_attempt_does_not_poison_trust_cache(self):
        """被拒伪造件不得把值灌进可信缓存:伪造尝试后,真实报告
        复核结果与伪造前逐位一致(冷/暖一致,来件值非数值来源)。"""
        spec = _tiny_spec()
        rep = _valid_report(spec)
        before = tier_validity(spec, n_episodes=0, err_bound=rep)
        bad = self._forged(spec, rep)
        st_bad = tier_validity(spec, n_episodes=0, err_bound=bad)
        assert st_bad["err_bound_kind"] == "unverified_report"
        after = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert after["dp_err_bound"] == before["dp_err_bound"]
        assert after["qualified"] == before["qualified"]


class TestNumericSlotValidation:
    """数字槽位逐元素类型/有限性;合法布尔字段(spec_key 内)不误拒。"""

    def test_nonfinite_diffs_rejected(self):
        spec = _tiny_spec()
        rep = _valid_report(spec)
        for bad in ([float("nan"), 0.0], [0.0, float("inf")]):
            r = copy.deepcopy(rep)
            r["adjacent_diffs"] = bad
            st = tier_validity(spec, n_episodes=0, err_bound=r)
            assert st["err_bound_kind"] == "unverified_report"
            assert "逐元素" in st["qualification_note"]

    def test_bool_and_string_diffs_rejected(self):
        spec = _tiny_spec()
        rep = _valid_report(spec)
        for bad in ([True, 0.0], ["0.0", 0.0]):
            r = copy.deepcopy(rep)
            r["adjacent_diffs"] = bad
            st = tier_validity(spec, n_episodes=0, err_bound=r)
            assert st["err_bound_kind"] == "unverified_report"
            assert "逐元素" in st["qualification_note"]

    def test_judged_grid_strict_integer_slots(self):
        """旧 int() 强转:"321"/321.5/True 借截断比较通过 → 拒。"""
        spec = _tiny_spec()
        for bad in (["321", 64, 40], [321.5, 64, 40],
                    [True, 64, 40], [float("nan"), 64, 40]):
            rep = _valid_report(spec)
            rep["judged_grid"] = bad
            st = tier_validity(spec, n_episodes=0, err_bound=rep)
            assert st["err_bound_kind"] == "unverified_report"
            assert "类型非法" in st["qualification_note"]

    def test_judged_grid_integral_floats_accepted(self):
        """数值等价的整数值浮点(321.0)不是伪数字,仍通过。"""
        spec = _tiny_spec()
        rep = _valid_report(spec)
        rep["judged_grid"] = [321.0, 64.0, 40.0]
        st = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert st["err_bound_kind"] == "empirical_adjacent_diff"

    def test_genuine_spec_key_bool_field_not_rejected(self):
        """spec_key 内含课程合法布尔字段(sigma_regime=False),
        按元组相等比较,不得因"槽位验数"一刀切误拒。"""
        rep = _valid_report(_tiny_spec())
        assert any(isinstance(x, bool) for x in rep["spec_key"])
        st = tier_validity(_tiny_spec(), n_episodes=0, err_bound=rep)
        assert st["err_bound_kind"] == "empirical_adjacent_diff"


class TestEvidenceCheckBeforeWork:
    """错误证据在生成/env 工作前拒绝;n_episodes=0 不算资源前检查。"""

    def test_invalid_scalar_inputs_zero_generation_work(self,
                                                        monkeypatch):
        calls = []

        def tripwire(*a, **kw):
            calls.append(1)
            raise AssertionError("不得在证据校验前进入生成边界")

        monkeypatch.setattr(c, "generate_episode", tripwire)
        for bad in (False, float("nan")):
            calls.clear()
            with pytest.raises(ValueError, match="err_bound"):
                tier_validity(_tiny_spec(), n_episodes=1,
                              err_bound=bad)
            assert calls == []

    def test_empty_report_zero_work_not_established(self,
                                                    monkeypatch):
        calls = []

        def tripwire(*a, **kw):
            calls.append(1)
            raise AssertionError("不得在证据校验前进入生成边界")

        monkeypatch.setattr(c, "generate_episode", tripwire)
        st = tier_validity(_tiny_spec(), n_episodes=1, err_bound={})
        assert calls == []
        assert st["err_bound_kind"] == "unverified_report"
        assert st["qualified"] is False
        assert "NOT_ESTABLISHED" in st["qualification_note"]

    def test_unverified_report_short_circuits_zero_work(
            self, monkeypatch):
        """已通过结构/规格检查但整链复算失败的报告:同样零工作。"""
        spec = _tiny_spec()
        rep = _valid_report(spec)
        v = rep["values"][-1]
        rep.update(values=[v, v, v], adjacent_diffs=[0.0, 0.0],
                   err_bound=0.0)
        calls = []

        def tripwire(*a, **kw):
            calls.append(1)
            raise AssertionError("伪造报告不得触发任何生成工作")

        monkeypatch.setattr(c, "generate_episode", tripwire)
        st = tier_validity(spec, n_episodes=1, err_bound=rep)
        assert calls == []
        assert st["err_bound_kind"] == "unverified_report"

    def test_verified_report_reaches_generation_boundary(
            self, monkeypatch):
        """合法路径可达性(明示记录型哨兵,不真实生成):证据通过后
        样本循环确实到达生成边界(与拒绝路径形成时序对照)。"""

        class Sentinel(Exception):
            pass

        calls = []

        def sentinel(*a, **kw):
            calls.append(1)
            raise Sentinel("record-only boundary reached")

        spec = _tiny_spec()
        rep = _valid_report(spec)
        monkeypatch.setattr(c, "generate_episode", sentinel)
        with pytest.raises(Sentinel):
            tier_validity(spec, n_episodes=1, err_bound=rep)
        assert calls == [1]


class TestLegitimateReportFlow:
    """合法真实报告:序列化/重载仍获正确条件性判断;冷暖一致。"""

    def test_serialized_reload_conditional_judgement(self):
        spec = _tiny_spec()
        rep = _valid_report(spec)
        reloaded = json.loads(json.dumps(rep))
        assert reloaded["values"] == rep["values"]
        st = tier_validity(spec, n_episodes=0, err_bound=reloaded)
        assert st["err_bound_kind"] == "empirical_adjacent_diff"
        assert st["dp_err_bound"] == pytest.approx(
            rep["err_bound"], rel=1e-12)
        expected = bool(
            st["dp_initial_value"] - rep["err_bound"] > 0.0)
        assert st["qualified"] is expected
        ev = st["err_evidence"]
        assert ev["judged_grid"] == [321, 64, 40]
        assert ev["n_levels"] == 3
        assert "level_values_recomputed" in ev
        for rv, cv in zip(reloaded["values"],
                          ev["level_values_recomputed"]):
            assert math.isclose(rv, cv, rel_tol=1e-9)

    def test_cold_and_warm_cache_consistent(self):
        spec = _tiny_spec()
        rep = _valid_report(spec)      # 暖缓存(含全部细化级)
        warm = tier_validity(spec, n_episodes=0, err_bound=rep)
        _DP_CACHE.clear()              # 冷缓存(全部重新求解)
        cold = tier_validity(spec, n_episodes=0, err_bound=rep)
        assert cold["dp_err_bound"] == warm["dp_err_bound"]
        assert cold["qualified"] == warm["qualified"]
        assert cold["err_evidence"][
            "level_values_recomputed"] == warm["err_evidence"][
            "level_values_recomputed"]
