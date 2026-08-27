"""工作包 A:以真实时间半衰期定义的 gamma 在 5m/15m/1h 下等价。"""

from __future__ import annotations

import math

import pytest

from rl_curriculum.timebase import (
    discounted_value_at_real_time,
    duration_to_bars,
    gamma_from_half_life,
)

HALF_LIVES = (6.0, 24.0, 72.0, 168.0)
CHECK_TIMES = (2.0, 6.0, 12.0, 36.0, 72.0, 168.0)


@pytest.mark.parametrize("hl", HALF_LIVES)
@pytest.mark.parametrize("t", CHECK_TIMES)
def test_discount_curves_match_across_timeframes(hl, t):
    analytic = discounted_value_at_real_time(t, hl)
    for tf in ("5m", "15m", "1h"):
        g = gamma_from_half_life(hl, tf)
        bars = duration_to_bars(t, tf)
        assert abs(g ** bars - analytic) < 1e-12, f"{tf} hl={hl} t={t}"


def test_gamma_half_life_semantics():
    g = gamma_from_half_life(24.0, "1h")  # 24 根 1h bar 后折扣一半
    assert abs(g ** 24 - 0.5) < 1e-12
    g15 = gamma_from_half_life(24.0, "15m")
    assert abs(g15 ** 96 - 0.5) < 1e-12


def test_gamma_values_differ_per_step_but_agree_over_time():
    g5, g15, g1h = (gamma_from_half_life(72.0, tf) for tf in ("5m", "15m", "1h"))
    assert g1h < g15 < g5 < 1.0  # 步长越短每步折扣越接近 1
    # 3 小时(=36×5m=12×15m=3×1h)折扣一致
    assert abs(g5 ** 36 - g15 ** 12) < 1e-12
    assert abs(g15 ** 12 - g1h ** 3) < 1e-12


def test_invalid_half_life():
    with pytest.raises(Exception):
        gamma_from_half_life(0.0, "15m")
    with pytest.raises(Exception):
        discounted_value_at_real_time(6.0, -1.0)


def test_mechanism_frozen_not_value():
    # 只冻结机制:公式 exp(log(0.5)*step/hl),数值不冻结
    g = gamma_from_half_life(10.0, "15m")
    assert math.isclose(g, math.exp(math.log(0.5) * 0.25 / 10.0))
