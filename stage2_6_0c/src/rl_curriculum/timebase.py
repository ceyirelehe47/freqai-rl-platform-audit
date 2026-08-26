"""工作包 A:统一真实时间尺度。

课程和审计基础设施以真实时间表达参数(3 小时趋势 / 24 小时波动窗口 /
7 天 Episode / 72 小时奖励半衰期),并能在 5m / 15m / 1h 下保持近似
相同的真实时间折扣,避免在课程定义中硬编码 24 根 / 96 根 / 288 根。

规则:
- timeframe 字符串 -> 分钟/秒;
- 真实时长 -> bars:非整数时默认向上取整(ceil,保证覆盖至少该时长),
  也支持显式 floor / raise;调用方必须把所用规则写入 manifest;
- bars -> 真实时长(小时);
- gamma = exp(log(0.5) * step_duration / reward_half_life):
  以真实时间半衰期定义折扣,在任意 timeframe 下相同真实时间点的
  累计折扣一致(本阶段只冻结机制,不冻结最终 gamma 数值)。
"""

from __future__ import annotations

import math

SUPPORTED_TIMEFRAMES = ("5m", "15m", "1h")

_TIMEFRAME_MINUTES = {"5m": 5, "15m": 15, "1h": 60}


class TimebaseError(ValueError):
    """时间尺度转换错误(未知 timeframe / 非整数 bars 且 rounding=raise)。"""


def timeframe_to_minutes(timeframe: str) -> int:
    if timeframe not in _TIMEFRAME_MINUTES:
        raise TimebaseError(
            f"不支持的 timeframe {timeframe!r}:仅支持 {SUPPORTED_TIMEFRAMES}")
    return _TIMEFRAME_MINUTES[timeframe]


def timeframe_to_seconds(timeframe: str) -> int:
    return timeframe_to_minutes(timeframe) * 60


def duration_to_bars(
    hours: float, timeframe: str, rounding: str = "ceil"
) -> int:
    """真实时长(小时)-> bars 数。

    非整数时的取整规则(必须进入 manifest):
    - ceil(默认):向上取整,Episode 至少覆盖指定时长;
    - floor:向下取整,不超过指定时长;
    - raise:非整数即报错。
    """
    if rounding not in ("ceil", "floor", "raise"):
        raise TimebaseError(f"未知取整规则 {rounding!r}(ceil/floor/raise)")
    minutes = timeframe_to_minutes(timeframe)
    exact = float(hours) * 60.0 / minutes
    if math.isclose(exact, round(exact), rel_tol=0.0, abs_tol=1e-9):
        return int(round(exact))
    if rounding == "ceil":
        return math.ceil(exact)
    if rounding == "floor":
        return math.floor(exact)
    raise TimebaseError(
        f"{hours} 小时在 {timeframe} 下为 {exact} bars(非整数),"
        f"rounding=raise 拒绝转换"
    )


def bars_to_duration_hours(bars: int, timeframe: str) -> float:
    """bars -> 真实时长(小时)。"""
    if bars < 0:
        raise TimebaseError(f"bars 不得为负,收到 {bars}")
    return bars * timeframe_to_minutes(timeframe) / 60.0


def gamma_from_half_life(half_life_hours: float, timeframe: str) -> float:
    """以真实时间半衰期计算每步折扣 gamma。

    gamma = exp(log(0.5) * step_duration / reward_half_life)
    5m/15m/1h 下相同半衰期的折扣曲线在相同真实时间点一致:
    gamma^n_bars(t) == 0.5^(t / half_life)。
    """
    if half_life_hours <= 0:
        raise TimebaseError(f"半衰期必须为正(小时),收到 {half_life_hours}")
    step_hours = timeframe_to_minutes(timeframe) / 60.0
    return math.exp(math.log(0.5) * step_hours / float(half_life_hours))


def discounted_value_at_real_time(
    t_hours: float, half_life_hours: float
) -> float:
    """真实时间 t 处的折扣因子(与 timeframe 无关的解析参照)。"""
    if half_life_hours <= 0:
        raise TimebaseError(f"半衰期必须为正(小时),收到 {half_life_hours}")
    if t_hours < 0:
        raise TimebaseError(f"t 不得为负,收到 {t_hours}")
    return 0.5 ** (float(t_hours) / float(half_life_hours))


def timebase_manifest(timeframe: str, half_life_hours: float | None = None) -> dict:
    """时间尺度转换记录(进入实验 manifest)。"""
    out = {
        "timeframe": timeframe,
        "timeframe_minutes": timeframe_to_minutes(timeframe),
        "supported_timeframes": list(SUPPORTED_TIMEFRAMES),
        "bars_rounding_rule": "ceil(非整数时长向上取整,Episode 至少覆盖指定时长)",
        "reference_conversions": {
            "6h": {
                tf: duration_to_bars(6.0, tf) for tf in SUPPORTED_TIMEFRAMES
            },
            "24h": {
                tf: duration_to_bars(24.0, tf) for tf in SUPPORTED_TIMEFRAMES
            },
            "7d": {
                tf: duration_to_bars(24.0 * 7, tf) for tf in SUPPORTED_TIMEFRAMES
            },
        },
    }
    if half_life_hours is not None:
        out["reward_half_life_hours"] = half_life_hours
        out["gamma_by_timeframe"] = {
            tf: gamma_from_half_life(half_life_hours, tf)
            for tf in SUPPORTED_TIMEFRAMES
        }
        out["gamma_formula"] = "exp(log(0.5) * step_duration / reward_half_life)"
    return out
