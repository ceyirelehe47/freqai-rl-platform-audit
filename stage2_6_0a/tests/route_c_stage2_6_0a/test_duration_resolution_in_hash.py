"""工作包 E2:真实时长与解析 bars 进入考试包哈希。"""

from __future__ import annotations

import pytest

from rl_curriculum.charter import charter_hash
from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
from rl_curriculum.generator_api import GeneratorError, resolve_duration
from rl_curriculum.probe_charter import audit_probe_charter
from rl_platform.versions import spec_versions


def test_duration_hours_resolves_with_rounding():
    r = resolve_duration({"duration_hours": 6.0}, "5m")
    assert r["resolved_bars"] == 72 and r["source"] == "duration_hours"
    assert r["rounding_rule"] == "ceil"
    r2 = resolve_duration(
        {"duration_hours": 6.0, "duration_rounding": "floor"}, "5m")
    assert r2["resolved_bars"] == 72  # 整除时一致
    r3 = resolve_duration({"duration_hours": 1.0}, "5m")
    assert r3["resolved_bars"] == 12
    r4 = resolve_duration({"duration_hours": 0.5}, "5m")  # 0.5h=6 bars
    assert r4["resolved_bars"] == 6


def test_bars_direct_resolution():
    r = resolve_duration({"episode_bars": 96}, "15m")
    assert r["resolved_bars"] == 96
    assert abs(r["resolved_real_hours"] - 24.0) < 1e-12
    assert r["source"] == "episode_bars_direct"


def test_inconsistent_duration_and_bars_rejected():
    with pytest.raises(GeneratorError, match="不一致"):
        resolve_duration(
            {"duration_hours": 6.0, "episode_bars": 100}, "15m")


def test_no_duration_info_rejected():
    with pytest.raises(GeneratorError, match="episode_bars 或 duration_hours"):
        resolve_duration({"initial_price": 100.0}, "15m")


def _pack(episodes, timeframe="15m"):
    return ExamPack(
        name="d", version="v1", visibility="public",
        charter_hash=charter_hash(audit_probe_charter()),
        spec_versions=spec_versions(), episodes=episodes,
        timeframe=timeframe)


def test_resolved_durations_in_pack_hash_payload():
    a = _pack([EpisodeSpec("probe_segmented_drift",
                           {"episode_bars": 96}, 1, "train",
                           timeframe="15m")])
    b = _pack([EpisodeSpec("probe_segmented_drift",
                           {"duration_hours": 24.0}, 1, "train",
                           timeframe="15m")])
    # 相同 resolved bars(96)但原始表达不同 -> 原始值入哈希 -> 哈希不同
    assert a.resolved_durations()[0]["resolved_bars"] == \
        b.resolved_durations()[0]["resolved_bars"] == 96
    assert a.pack_hash() != b.pack_hash()
    import json as j

    payload = j.loads(a.canonical())
    rd = payload["resolved_durations"][0]
    for key in ("timeframe", "source", "requested_real_hours",
                "rounding_rule", "resolved_bars", "resolved_real_hours"):
        assert key in rd


def test_timeframe_change_changes_pack_hash():
    a = _pack([EpisodeSpec("probe_segmented_drift", {"episode_bars": 96},
                           1, "train", timeframe="15m")])
    b = _pack([EpisodeSpec("probe_segmented_drift", {"episode_bars": 96},
                           1, "train", timeframe="1h")], timeframe="1h")
    assert a.pack_hash() != b.pack_hash()


def test_materialize_respects_spec_timeframe():
    """物化使用 spec 自带 timeframe(5m spec 生成 5m 日期轴)。"""
    from rl_curriculum.exam_pack import materialize_pack
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    pack = _pack([EpisodeSpec("probe_segmented_drift", {"episode_bars": 48},
                              1, "train", timeframe="5m")], timeframe="5m")
    eps = materialize_pack(pack, DEFAULT_GENERATOR_REGISTRY)
    assert eps[0].spec.timeframe == "5m"
    step = (eps[0].df["date"].iloc[1] -
            eps[0].df["date"].iloc[0]).total_seconds()
    assert step == 300
