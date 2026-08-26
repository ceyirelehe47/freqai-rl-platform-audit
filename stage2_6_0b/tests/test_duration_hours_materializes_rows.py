"""工作包 A5:duration_hours 实际物化为行数(端到端)。"""

from __future__ import annotations

import pytest

from rl_curriculum.generator_api import GeneratorError
from rl_curriculum.generators import ProbeSegmentedDriftGenerator


CASES = [
    ("15m", 48.0, 192),
    ("5m", 48.0, 576),
    ("1h", 48.0, 48),
]


@pytest.mark.parametrize("timeframe,hours,expected_rows", CASES)
def test_duration_hours_materializes_exact_rows(
        gen_a, timeframe, hours, expected_rows):
    ep = gen_a.generate({"duration_hours": hours}, 7, timeframe=timeframe)
    assert len(ep.df) == expected_rows
    assert len(ep.hidden) == expected_rows
    # 不回退到 96 行默认值(除 1h+48h 恰为 48)
    assert ep.meta["resolution"]["duration"]["resolved_bars"] == expected_rows
    assert ep.meta["resolution"]["actual_rows"] == expected_rows
    assert ep.meta["resolution"]["rows_match_resolved"] is True


@pytest.mark.parametrize("timeframe,hours,expected_rows", CASES)
def test_date_axis_spacing_matches_timeframe(
        gen_a, timeframe, hours, expected_rows):
    import pandas as pd

    ep = gen_a.generate({"duration_hours": hours}, 7, timeframe=timeframe)
    deltas = ep.df["date"].diff().dropna().unique()
    assert len(deltas) == 1
    minutes = {"5m": 5, "15m": 15, "1h": 60}[timeframe]
    assert pd.Timedelta(deltas[0]) == pd.Timedelta(minutes=minutes, unit="m")


def test_episode_real_duration_matches_declaration(gen_a):
    ep = gen_a.generate({"duration_hours": 48}, 9, timeframe="15m")
    real_hours = (ep.df["date"].iloc[-1] - ep.df["date"].iloc[0]
                  ).total_seconds() / 3600.0
    # 192 根 15m bar 覆盖 (192-1)*0.25 = 47.75h;resolved_real_hours
    # 以 bars*step 计(192*0.25=48h),两者语义一致地记录在 trace 中
    assert ep.meta["resolution"]["duration"]["resolved_real_hours"] == 48.0
    assert abs(real_hours - 47.75) < 1e-9


def test_different_timeframes_produce_different_pack_hashes():
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec
    from rl_platform.versions import spec_versions

    packs = []
    for tf in ("5m", "15m", "1h"):
        spec = EpisodeSpec(family="probe_segmented_drift",
                           params={"duration_hours": 48.0}, seed=7,
                           split="train", timeframe=tf)
        packs.append(ExamPack(
            name=f"p_{tf}", version="v", visibility="public",
            charter_hash="c", spec_versions=spec_versions(),
            episodes=[spec], timeframe=tf))
    hashes = [p.pack_hash() for p in packs]
    assert len(set(hashes)) == 3
    # resolved params 不同(96 默认不存在:192/576/48 互异)
    bars = [p.resolved_durations()[0]["resolved_bars"] for p in packs]
    assert bars == [576, 192, 48]


def test_inconsistent_duration_and_bars_fails_closed(gen_a):
    with pytest.raises(GeneratorError):
        gen_a.generate(
            {"duration_hours": 48.0, "episode_bars": 96},
            7, timeframe="15m")


def test_raw_and_resolved_params_recorded_separately(gen_a):
    ep = gen_a.generate({"duration_hours": 24.0}, 5, timeframe="15m")
    # 原始参数保留在 spec(duration_hours),解析参数进入 resolution
    assert ep.spec.params["duration_hours"] == 24.0
    res = ep.meta["resolution"]
    assert res["duration"]["source"] == "duration_hours"
    assert res["duration"]["requested_real_hours"] == 24.0
    assert res["duration"]["resolved_bars"] == 96
    assert res["effective_params"]["episode_bars"] == 96
