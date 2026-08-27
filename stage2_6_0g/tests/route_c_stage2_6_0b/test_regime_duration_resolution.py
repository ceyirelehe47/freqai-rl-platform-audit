"""工作包 A3:课程级时间字段的可扩展解析机制(声明 -> bar 参数)。"""

from __future__ import annotations

import pytest

from rl_curriculum.param_resolution import (
    TIME_FIELD_BINDINGS,
    TIME_FIELD_KINDS,
    ParamResolutionError,
    TimeFieldBinding,
    register_time_field_binding,
    resolve_generator_params,
    resolve_time_field,
    resolved_parameter_semantics_hash,
)


def test_bindable_kinds_cover_curriculum_time_fields():
    for kind in ("episode_total", "regime_duration_range",
                 "feature_window", "decision_interval",
                 "delayed_reward_phase", "drawdown_phase"):
        assert kind in TIME_FIELD_KINDS


def test_default_bindings_are_registered_and_hashable():
    for field in ("duration_hours", "regime_duration_hours_range",
                  "feature_window_hours", "decision_interval_minutes",
                  "delayed_reward_phase_hours", "drawdown_phase_hours"):
        assert field in TIME_FIELD_BINDINGS
    h = resolved_parameter_semantics_hash()
    assert h.startswith("rps-") and len(h) == 68


def test_binding_registry_change_changes_semantics_hash():
    from rl_curriculum.param_resolution import TIME_FIELD_BINDINGS

    before = resolved_parameter_semantics_hash()
    register_time_field_binding(TimeFieldBinding(
        real_time_field="custom_phase_hours",
        target_param="custom_phase_bars", kind="drawdown_phase"))
    after = resolved_parameter_semantics_hash()
    assert before != after
    # 清理注册(阶段 2.6.0f:全局注册表泄漏会改变 rps-/duration 合同哈希,
    # 污染同进程后续阶段测试的承诺对账)
    TIME_FIELD_BINDINGS.pop("custom_phase_hours", None)
    assert resolved_parameter_semantics_hash() == before


def test_delayed_reward_phase_resolution():
    r = resolve_generator_params(
        {"episode_bars": 96, "delayed_reward_phase_hours": 2.0}, "15m")
    assert r.effective_params["delayed_reward_phase_bars"] == 8


def test_feature_window_resolution():
    r = resolve_generator_params(
        {"episode_bars": 96, "feature_window_hours": 6.0}, "5m")
    assert r.effective_params["feature_window_bars"] == 72


def test_range_field_requires_pair():
    with pytest.raises(ParamResolutionError):
        resolve_time_field(
            TIME_FIELD_BINDINGS["regime_duration_hours_range"],
            {"regime_duration_hours_range": 3.0}, "15m")


def test_unknown_kind_rejected():
    with pytest.raises(ParamResolutionError):
        register_time_field_binding(TimeFieldBinding(
            real_time_field="x_hours", target_param="x_bars",
            kind="not_a_kind"))


def test_rounding_rules_enter_trace():
    r = resolve_generator_params(
        {"duration_hours": 1.1, "duration_rounding": "floor"}, "1h")
    assert r.duration["rounding_rule"] == "floor"
    assert r.duration["resolved_bars"] == 1
    r2 = resolve_generator_params(
        {"duration_hours": 1.1, "duration_rounding": "ceil"}, "1h")
    assert r2.duration["resolved_bars"] == 2
    with pytest.raises(ParamResolutionError):
        resolve_generator_params(
            {"duration_hours": 1.1, "duration_rounding": "raise"}, "1h")
