"""工作包 E2:EpisodeSpec 显式绑定 timeframe。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.generator_api import EpisodeSpec, GeneratorError
from rl_curriculum.timebase import SUPPORTED_TIMEFRAMES


@pytest.mark.parametrize("tf", SUPPORTED_TIMEFRAMES)
def test_timeframe_accepted(gen_a, tf):
    ep = gen_a.generate({"episode_bars": 48}, seed=1, timeframe=tf)
    assert ep.spec.timeframe == tf
    assert ep.timeframe == tf


def test_missing_timeframe_rejected(gen_a):
    with pytest.raises(TypeError):
        gen_a.generate({"episode_bars": 48}, seed=1)  # timeframe 必填
    with pytest.raises(GeneratorError, match="timeframe"):
        EpisodeSpec("f", {"episode_bars": 48}, 1, "train", timeframe="")


def test_unknown_timeframe_rejected():
    with pytest.raises(GeneratorError, match="timeframe"):
        EpisodeSpec("f", {"episode_bars": 48}, 1, "train", timeframe="4h")
    with pytest.raises(GeneratorError, match="timeframe"):
        EpisodeSpec("f", {"episode_bars": 48}, 1, "train", timeframe=None)


def test_canonical_includes_timeframe():
    a = EpisodeSpec("f", {"episode_bars": 48}, 1, "train", timeframe="15m")
    b = EpisodeSpec("f", {"episode_bars": 48}, 1, "train", timeframe="5m")
    assert a.canonical() != b.canonical()
    assert json.loads(a.canonical())["timeframe"] == "15m"


def test_timeframe_affects_date_axis(gen_a):
    e15 = gen_a.generate({"episode_bars": 48}, seed=5, timeframe="15m")
    e1h = gen_a.generate({"episode_bars": 48}, seed=5, timeframe="1h")
    step_15 = (e15.df["date"].iloc[1] - e15.df["date"].iloc[0]).total_seconds()
    step_1h = (e1h.df["date"].iloc[1] - e1h.df["date"].iloc[0]).total_seconds()
    assert step_15 == 900 and step_1h == 3600
