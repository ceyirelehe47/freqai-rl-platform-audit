"""工作包 A:timeframe 转换与真实时间表达。"""

from __future__ import annotations

import pytest

from rl_curriculum.timebase import (
    TimebaseError,
    bars_to_duration_hours,
    duration_to_bars,
    gamma_from_half_life,
    timebase_manifest,
    timeframe_to_minutes,
    timeframe_to_seconds,
)


def test_timeframe_to_minutes_and_seconds():
    assert timeframe_to_minutes("5m") == 5
    assert timeframe_to_minutes("15m") == 15
    assert timeframe_to_minutes("1h") == 60
    assert timeframe_to_seconds("15m") == 900
    with pytest.raises(TimebaseError):
        timeframe_to_minutes("4h")


@pytest.mark.parametrize("tf,expected", [("5m", 72), ("15m", 24), ("1h", 6)])
def test_6h_conversions(tf, expected):
    assert duration_to_bars(6.0, tf) == expected


def test_24h_7d_conversions_no_off_by_one():
    assert duration_to_bars(24.0, "15m") == 96
    assert duration_to_bars(24.0, "5m") == 288
    assert duration_to_bars(24.0, "1h") == 24
    assert duration_to_bars(24.0 * 7, "15m") == 672
    assert duration_to_bars(24.0 * 7, "5m") == 2016
    assert duration_to_bars(24.0 * 7, "1h") == 168


def test_roundtrip_bars_duration():
    for tf in ("5m", "15m", "1h"):
        for hours in (6.0, 24.0, 168.0):
            bars = duration_to_bars(hours, tf)
            assert abs(bars_to_duration_hours(bars, tf) - hours) < 1e-9


def test_non_integer_duration_rules():
    # 1 小时在 15m 下 = 4 bars(整数);5 小时在 1h 下 = 5;7 小时在 1h 下 = 7
    with pytest.raises(TimebaseError):
        duration_to_bars(6.5, "1h", rounding="raise")
    assert duration_to_bars(6.5, "1h", rounding="ceil") == 7
    assert duration_to_bars(6.5, "1h", rounding="floor") == 6
    with pytest.raises(TimebaseError):
        duration_to_bars(6.0, "1h", rounding="bad")


def test_manifest_contains_conversions():
    m = timebase_manifest("15m", 72.0)
    assert m["timeframe_minutes"] == 15
    assert m["reference_conversions"]["24h"]["15m"] == 96
    assert m["reference_conversions"]["7d"]["15m"] == 672
    assert "gamma_by_timeframe" in m and "ceil" in m["bars_rounding_rule"]
