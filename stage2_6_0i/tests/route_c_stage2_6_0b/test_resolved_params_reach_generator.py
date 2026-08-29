"""工作包 A1/A3/A4:resolved params 真实传入生成器;时间字段可扩展解析;
禁止静默默认。"""

from __future__ import annotations

import pytest

from rl_curriculum.generator_api import GeneratorError
from rl_curriculum.generators import ProbeSegmentedDriftGenerator
from rl_curriculum.param_resolution import (
    ParamResolutionError,
    TimeFieldBinding,
    register_time_field_binding,
    TIME_FIELD_BINDINGS,
    resolve_generator_params,
)


def test_resolved_episode_bars_reach_effective_params():
    r = resolve_generator_params(
        {"duration_hours": 48, "regimes": [[1, 20.0, 64], [-1, 18.0, 64],
                                           [0, 0.0, 64]]},
        "15m")
    assert r.effective_params["episode_bars"] == 192
    assert "duration_hours" in r.effective_params  # 原始声明保留
    # 显式给出不一致 bars -> 拒绝(静默取其一被禁止)
    with pytest.raises(ParamResolutionError):
        resolve_generator_params(
            {"duration_hours": 48, "episode_bars": 96}, "15m")


def test_regime_duration_hours_range_resolves_to_bars(gen_a):
    params = {
        "duration_hours": 48,
        "regime_duration_hours_range": [1.0, 4.0],
        "n_regimes_range": [4, 8],
    }
    ep = gen_a.generate(params, 21, timeframe="15m")
    res = ep.meta["resolution"]
    assert res["fields"]["regime_duration_hours_range"][
        "resolved_bars_range"] == [4, 16]
    assert res["effective_params"]["regime_len_range"] == [4, 16]
    # 实际 regime 长度落在解析范围内
    for _d, _s, length in ep.meta["regimes"]:
        assert 4 <= length <= 16


def test_regime_range_conflict_with_explicit_bars_fails():
    with pytest.raises(ParamResolutionError):
        resolve_generator_params(
            {"duration_hours": 48,
             "regime_duration_hours_range": [1.0, 4.0],
             "regime_len_range": [12, 40]},
            "15m")


def test_declared_time_field_without_resolution_fails(monkeypatch):
    """A4:声明了真实时间字段但目标 bar 参数无法解析 -> 直接失败。"""
    from rl_curriculum import param_resolution as pr

    # 注入一个目标参数无法物化的绑定(目标参数生成器不读)。
    # drawdown_phase_hours 是 param_resolution 模块级预注册绑定:
    # 测试结束后必须恢复原绑定(删除会改变 rps-/duration 合同哈希,
    # 污染同进程后续阶段测试的承诺对账——阶段 2.6.0f)
    _saved = TIME_FIELD_BINDINGS.get("drawdown_phase_hours")
    register_time_field_binding(TimeFieldBinding(
        real_time_field="drawdown_phase_hours",
        target_param="drawdown_phase_bars", kind="drawdown_phase"))
    r = resolve_generator_params({"episode_bars": 96,
                                  "drawdown_phase_hours": 2.0}, "15m")
    # 解析通道必须把它写进 effective params(否则视为静默丢弃)
    assert r.effective_params["drawdown_phase_bars"] == 8
    assert pr.resolved_parameter_semantics_hash().startswith("rps-")
    # 恢复预注册绑定(不是删除)
    if _saved is None:
        pr.TIME_FIELD_BINDINGS.pop("drawdown_phase_hours", None)
    else:
        pr.TIME_FIELD_BINDINGS["drawdown_phase_hours"] = _saved


def test_decision_interval_must_match_timeframe():
    r = resolve_generator_params(
        {"episode_bars": 96, "decision_interval_minutes": 15}, "15m")
    assert r.field_traces["decision_interval_minutes"]["resolved_bars"] == 1
    with pytest.raises(ParamResolutionError):
        resolve_generator_params(
            {"episode_bars": 96, "decision_interval_minutes": 5}, "15m")


def test_generator_missing_bars_key_fails_closed():
    """生成器不提供静默默认:直接调用 _generate 缺 episode_bars 即失败。"""
    gen = ProbeSegmentedDriftGenerator()
    import numpy as np

    with pytest.raises(KeyError):
        gen._generate({"drift_bps_range": [18, 30]}, 1,
                      np.random.default_rng(0))


def test_generator_row_mismatch_is_generator_error():
    """A2:实际行数 != resolved bars -> EXAM_INVALID 级失败。"""

    class BadGen(ProbeSegmentedDriftGenerator):
        family = "bad_short_generator"
        family_version = "bad-v1"

        def _generate(self, params, seed, rng):
            returns, hidden, meta = super()._generate(params, seed, rng)
            # 故意截断:96 声明只生成 48 行
            return (returns[:48], hidden.iloc[:48], meta)

    with pytest.raises(GeneratorError, match="resolved"):
        BadGen().generate({"episode_bars": 96}, 3, timeframe="15m")
