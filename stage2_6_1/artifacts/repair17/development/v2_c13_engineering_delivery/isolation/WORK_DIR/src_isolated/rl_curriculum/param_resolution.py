"""阶段 2.6.0b 工作包 A:课程真实时间参数 -> 生成器 bars 参数的统一解析。

阶段 2.6.0a 的问题:duration_hours 虽被 resolve_duration 解析并进入
考试包哈希,但生成器 _generate 内部仍执行 params.get("episode_bars", 96)
——真实声明只进了 manifest,实际 Episode 长度退回默认 96 根。

本模块建立"声明即物化"的唯一解析通道:

    原始课程参数 + timeframe
        -> resolve_generator_params()(统一解析全部真实时间字段)
        -> effective params(已含解析后的 bars)
        -> 实际生成器(_generate 只读取 effective params,无默认值)

解析规则(A1-A4):
- episode 总时长(duration_hours)-> episode_bars,取整规则入 trace;
- 课程可声明其他真实时间字段(regime 持续时长范围/特征窗口时长/
  决策间隔/延迟收益阶段/回撤阶段),经预注册 TIME_FIELD_BINDINGS
  映射到对应 bar 参数,不得在每个生成器里散落手工换算;
- 声明了真实时间字段但其解析结果未能进入 effective params -> 直接
  失败(禁止静默丢弃);
- 同时给出真实时长与 bars 且不一致 -> 直接失败;
- 生成器实际行数与 resolved bars 不一致 -> generate() 内 GeneratorError
  (见 generator_api.BaseMarketGenerator.generate)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from rl_curriculum.timebase import (
    SUPPORTED_TIMEFRAMES,
    TimebaseError,
    duration_to_bars,
    timeframe_to_minutes,
)


class ParamResolutionError(RuntimeError):
    """真实时间字段解析失败(fail closed,静默默认被禁止)。"""


# 时间字段类别(可扩展;每类声明"这个真实时间字段应解析到哪个 bar 参数")
TIME_FIELD_KINDS: tuple[str, ...] = (
    "episode_total",          # Episode 总时长 -> episode_bars
    "regime_duration_range",  # regime 持续时间范围 -> regime_len_range
    "feature_window",         # 特征滚动窗口时长 -> 特定窗口 bar 参数
    "decision_interval",      # 决策间隔(校验 = timeframe,本身不产生 bars)
    "delayed_reward_phase",   # 延迟收益阶段时长
    "drawdown_phase",         # 回撤阶段时长
)


@dataclass(frozen=True)
class TimeFieldBinding:
    """预注册的真实时间字段 -> bar 参数绑定(课程章程可审计的换算声明)。"""

    real_time_field: str        # 课程声明的真实时间参数名(原始参数键)
    target_param: str           # 解析结果写入的 bar 参数键("" 表示仅校验)
    kind: str                   # TIME_FIELD_KINDS 之一
    rounding: str = "ceil"      # 非整数时长的取整规则
    allow_range: bool = False   # 真实字段允许 [lo, hi] 小时范围

    def canonical(self) -> dict[str, Any]:
        return {
            "real_time_field": self.real_time_field,
            "target_param": self.target_param,
            "kind": self.kind,
            "rounding": self.rounding,
            "allow_range": self.allow_range,
        }


#: 默认时间字段绑定注册表(生成器/章程可声明更多,但必须在生成前注册)
TIME_FIELD_BINDINGS: dict[str, TimeFieldBinding] = {
    b.real_time_field: b for b in (
        TimeFieldBinding(
            real_time_field="duration_hours", target_param="episode_bars",
            kind="episode_total"),
        TimeFieldBinding(
            real_time_field="regime_duration_hours_range",
            target_param="regime_len_range", kind="regime_duration_range",
            allow_range=True),
        TimeFieldBinding(
            real_time_field="feature_window_hours",
            target_param="feature_window_bars", kind="feature_window"),
        TimeFieldBinding(
            real_time_field="decision_interval_minutes", target_param="",
            kind="decision_interval"),
        TimeFieldBinding(
            real_time_field="delayed_reward_phase_hours",
            target_param="delayed_reward_phase_bars",
            kind="delayed_reward_phase"),
        TimeFieldBinding(
            real_time_field="drawdown_phase_hours",
            target_param="drawdown_phase_bars", kind="drawdown_phase"),
    )
}


def register_time_field_binding(binding: TimeFieldBinding) -> None:
    """课程/生成器注册额外时间字段绑定(必须在解析前完成)。"""
    if binding.kind not in TIME_FIELD_KINDS:
        raise ParamResolutionError(
            f"时间字段类别 {binding.kind!r} 不在 {TIME_FIELD_KINDS}")
    TIME_FIELD_BINDINGS[binding.real_time_field] = binding


def resolve_duration(params: dict[str, Any], timeframe: str) -> dict[str, Any]:
    """Episode 真实时长解析(原始值与解析结果全部可进入哈希)。

    - params 含 duration_hours:按 rounding 规则(默认 ceil)解析为 bars;
    - params 含 episode_bars:bars 即原始值,反推真实时长;
    - 两者同给必须一致,否则 ParamResolutionError(A4)。
    """
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ParamResolutionError(
            f"timeframe 必须属于 {SUPPORTED_TIMEFRAMES},收到 {timeframe!r}")
    has_dur = params.get("duration_hours") is not None
    has_bars = params.get("episode_bars") is not None
    if not has_dur and not has_bars:
        raise ParamResolutionError(
            f"Episode 参数必须含 episode_bars 或 duration_hours 之一:"
            f"{dict(params)!r}")
    if has_dur:
        hours = float(params["duration_hours"])
        if hours <= 0:
            raise ParamResolutionError(
                f"duration_hours 必须为正,收到 {hours}")
        rounding = str(params.get("duration_rounding", "ceil"))
        try:
            bars = duration_to_bars(hours, timeframe, rounding=rounding)
        except TimebaseError as exc:
            raise ParamResolutionError(str(exc)) from exc
        if has_bars and int(params["episode_bars"]) != bars:
            raise ParamResolutionError(
                f"duration_hours={hours} 在 {timeframe} 下按 {rounding} 解析为 "
                f"{bars} bars,与显式 episode_bars={params['episode_bars']} 不一致"
                f"(禁止静默取其一)")
        return {
            "timeframe": timeframe,
            "source": "duration_hours",
            "requested_real_hours": hours,
            "rounding_rule": rounding,
            "resolved_bars": int(bars),
            "resolved_real_hours": _bars_to_hours(bars, timeframe),
        }
    bars = int(params["episode_bars"])
    if bars <= 0:
        raise ParamResolutionError(f"episode_bars 必须为正,收到 {bars}")
    return {
        "timeframe": timeframe,
        "source": "episode_bars_direct",
        "requested_real_hours": _bars_to_hours(bars, timeframe),
        "rounding_rule": "none(bars 直接给定)",
        "resolved_bars": bars,
        "resolved_real_hours": _bars_to_hours(bars, timeframe),
    }


def _bars_to_hours(bars: int, timeframe: str) -> float:
    return bars * timeframe_to_minutes(timeframe) / 60.0


def _resolve_hours_value(value: Any, *, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ParamResolutionError(
            f"真实时间字段 {field!r} 的值 {value!r} 无法转为小时(float)"
        ) from exc
    if out <= 0:
        raise ParamResolutionError(
            f"真实时间字段 {field!r} 必须为正小时数,收到 {value!r}")
    return out


def resolve_time_field(
    binding: TimeFieldBinding, params: dict[str, Any], timeframe: str,
) -> dict[str, Any]:
    """解析单个时间字段(范围字段解析为 [bars_lo, bars_hi])。"""
    raw = params[binding.real_time_field]
    record: dict[str, Any] = {
        "field": binding.real_time_field,
        "target_param": binding.target_param,
        "kind": binding.kind,
        "timeframe": timeframe,
        "rounding": binding.rounding,
        "raw_value": raw,
    }
    if binding.kind == "decision_interval":
        minutes = float(raw)
        if minutes <= 0:
            raise ParamResolutionError(
                f"decision_interval_minutes 必须为正分钟数,收到 {raw!r}")
        tf_minutes = timeframe_to_minutes(timeframe)
        if minutes != tf_minutes:
            raise ParamResolutionError(
                f"decision_interval_minutes={minutes:g} 与 timeframe "
                f"{timeframe!r}({tf_minutes:g} 分钟)不一致"
                f"(决策间隔由 timeframe 决定,二者必须一致)")
        record["resolved_bars"] = 1
        record["note"] = "校验通过:决策间隔 == timeframe 步长(不产生独立参数)"
        return record
    if binding.allow_range:
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            raise ParamResolutionError(
                f"范围时间字段 {binding.real_time_field!r} 必须为 [lo, hi] 小时,"
                f"收到 {raw!r}")
        lo_h = _resolve_hours_value(raw[0], field=binding.real_time_field)
        hi_h = _resolve_hours_value(raw[1], field=binding.real_time_field)
        if lo_h > hi_h:
            raise ParamResolutionError(
                f"范围时间字段 {binding.real_time_field!r} 的 lo > hi: {raw!r}")
        try:
            lo_b = duration_to_bars(lo_h, timeframe, rounding=binding.rounding)
            hi_b = duration_to_bars(hi_h, timeframe, rounding=binding.rounding)
        except TimebaseError as exc:
            raise ParamResolutionError(str(exc)) from exc
        lo_b = max(lo_b, 1)
        hi_b = max(hi_b, lo_b)
        record["resolved_bars_range"] = [int(lo_b), int(hi_b)]
        record["resolved_real_hours_range"] = [
            _bars_to_hours(int(lo_b), timeframe),
            _bars_to_hours(int(hi_b), timeframe),
        ]
        return record
    hours = _resolve_hours_value(raw, field=binding.real_time_field)
    try:
        bars = duration_to_bars(hours, timeframe, rounding=binding.rounding)
    except TimebaseError as exc:
        raise ParamResolutionError(str(exc)) from exc
    record["resolved_bars"] = int(max(bars, 1))
    record["resolved_real_hours"] = _bars_to_hours(int(max(bars, 1)), timeframe)
    return record


@dataclass(frozen=True)
class ResolvedParams:
    """generate() 实际使用的参数与解析 trace(进入 episode.meta)。"""

    effective_params: dict[str, Any]
    duration: dict[str, Any]
    field_traces: dict[str, dict[str, Any]] = field(default_factory=dict)

    def trace(self) -> dict[str, Any]:
        """A2:原始参数与解析参数的分离记录(逐字段可审计)。"""
        return {
            "duration": dict(self.duration),
            "fields": {k: dict(v) for k, v in self.field_traces.items()},
        }


def resolve_generator_params(
    params: dict[str, Any], timeframe: str,
) -> ResolvedParams:
    """统一参数解析入口:任何 _generate 调用前必须先经过本函数。

    - episode 总时长解析并注入 effective["episode_bars"];
    - 所有已声明的其他真实时间字段逐个解析并注入对应 bar 参数;
    - 声明了真实时间字段但目标 bar 参数已显式存在且值不一致 -> 失败;
    - 返回 (effective_params, duration, field_traces)。
    """
    duration = resolve_duration(params, timeframe)
    effective: dict[str, Any] = dict(params)
    effective["episode_bars"] = int(duration["resolved_bars"])
    field_traces: dict[str, dict[str, Any]] = {}

    for field_name, binding in sorted(TIME_FIELD_BINDINGS.items()):
        if field_name == "duration_hours":
            continue  # episode 总时长已由 resolve_duration 处理
        if params.get(field_name) is None:
            continue
        record = resolve_time_field(binding, params, timeframe)
        field_traces[field_name] = record
        target = binding.target_param
        if not target:
            continue  # decision_interval:仅校验,不写参数
        if binding.allow_range:
            resolved = record["resolved_bars_range"]
            explicit = params.get(target)
            if explicit is not None:
                if (not isinstance(explicit, (list, tuple))
                        or len(explicit) != 2
                        or [int(explicit[0]), int(explicit[1])] != resolved):
                    raise ParamResolutionError(
                        f"时间字段 {field_name!r} 解析为 {resolved} bars,"
                        f"与显式 {target}={explicit!r} 不一致(禁止静默取其一)")
            effective[target] = [int(resolved[0]), int(resolved[1])]
        else:
            resolved = int(record["resolved_bars"])
            explicit = params.get(target)
            if explicit is not None and int(explicit) != resolved:
                raise ParamResolutionError(
                    f"时间字段 {field_name!r} 解析为 {resolved} bars,"
                    f"与显式 {target}={explicit!r} 不一致(禁止静默取其一)")
            effective[target] = resolved

    return ResolvedParams(
        effective_params=effective,
        duration=duration,
        field_traces=field_traces,
    )


def resolved_parameter_semantics_hash() -> str:
    """解析语义指纹:绑定注册表 + 取整规则(进入 sealed commitment)。"""
    payload = {
        "kinds": list(TIME_FIELD_KINDS),
        "bindings": [b.canonical() for _, b in sorted(
            TIME_FIELD_BINDINGS.items())],
        "episode_rounding_default": "ceil",
    }
    return "rps-" + __import__("hashlib").sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()
