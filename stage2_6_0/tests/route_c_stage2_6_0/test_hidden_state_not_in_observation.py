"""工作包 C:隐藏状态严格隔离(字段审计 + FutureLeak 观察审计)。"""

from __future__ import annotations

import pytest

from rl_curriculum.generator_api import (
    FORBIDDEN_OBSERVATION_PATTERNS,
    GeneratedEpisode,
    audit_observation_isolation,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def test_probe_a_isolation(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=11)
    r = audit_observation_isolation(ep, gen_a)
    assert r["pass"], r["issues"]
    assert "regime_direction" in r["declared_hidden_fields"]
    assert "regime_direction" not in r["observation_fields"]
    assert r["observation_fields"] == [
        "ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"]


def test_probe_b_isolation(gen_b):
    ep = gen_b.generate({"episode_bars": 64}, seed=11)
    r = audit_observation_isolation(ep, gen_b)
    assert r["pass"], r["issues"]
    assert "latent_drift_bps" in r["declared_hidden_fields"]


def test_probe_c_isolation(gen_c):
    ep = gen_c.generate(dict(TRAIN_PARAMS), seed=11)
    r = audit_observation_isolation(ep, gen_c)
    assert r["pass"], r["issues"]


def test_forbidden_patterns_covered():
    for name in ("regime", "future", "latent", "steps_to", "episode_length",
                 "seed", "generator_state", "exam_type", "drift"):
        assert name in FORBIDDEN_OBSERVATION_PATTERNS


def test_leaky_observation_field_detected(gen_a):
    """构造含隐藏命名字段的观察 -> 审计必须发现(泄漏 fail closed)。"""
    ep = gen_a.generate(TRAIN_PARAMS, seed=12)
    leaky = ep.df.copy()
    leaky["regime_direction"] = ep.hidden["regime_direction"].to_numpy()
    bad = GeneratedEpisode(
        spec=ep.spec, df=leaky, hidden=ep.hidden,
        family_version=ep.family_version, timeframe=ep.timeframe,
        is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint)
    r = audit_observation_isolation(bad, gen_a)
    assert not r["pass"]
    assert "regime_direction" in r["leaked_fields"]


def test_future_named_field_detected(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=13)
    leaky = ep.df.copy()
    leaky["future_return_1"] = 0.0
    bad = GeneratedEpisode(
        spec=ep.spec, df=leaky, hidden=ep.hidden,
        family_version=ep.family_version, timeframe=ep.timeframe,
        is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint)
    r = audit_observation_isolation(bad, gen_a)
    assert not r["pass"]
    assert any("future_return_1" in i for i in r["issues"])


def test_hidden_not_accessible_from_standard_observation(gen_a):
    """评估器构造的标准 observation 只含特征窗口 + 仓位,无隐藏。"""
    import numpy as np

    from rl_platform.env import AlignedLongFlatEnv

    ep = gen_a.generate(TRAIN_PARAMS, seed=14)
    env = AlignedLongFlatEnv(
        features=ep.df[["ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"]],
        prices=ep.df[["open", "high", "low", "close"]],
    )
    obs, _ = env.reset(seed=0)
    assert obs.shape == (6,)  # 5 特征 + 仓位
    assert np.all(np.isfinite(obs))
