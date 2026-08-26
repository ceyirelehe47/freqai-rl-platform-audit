"""工作包 C + 阶段 2.6.0a 工作包 K:隐藏状态严格隔离。

阶段 2.6.0a 语义变化:主隔离机制从"字段命名黑名单"升级为"精确
whitelist"(verify_episode 在 generate() 内自动执行,whitelist 之外
的任何列 fail closed,无论命名);命名黑名单仅作辅助报告。
观察字段断言更新为含 nuisance 槽位的完整 whitelist。
"""

from __future__ import annotations

import pytest

from rl_curriculum.generator_api import (
    FORBIDDEN_OBSERVATION_PATTERNS,
    GeneratedEpisode,
    GeneratorError,
    audit_observation_isolation,
    verify_episode,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def test_probe_a_isolation(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=11, timeframe="15m")
    r = audit_observation_isolation(ep, gen_a)
    assert r["pass"], r["issues"]
    assert "regime_direction" in r["declared_hidden_fields"]
    assert "regime_direction" not in r["observation_fields"]
    # 完整 whitelist:市场特征 + 预注册 nuisance 槽位
    assert r["observation_fields"] == [
        "ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio",
        "nuisance_0", "nuisance_1", "nuisance_2"]


def test_probe_b_isolation(gen_b):
    ep = gen_b.generate({"episode_bars": 64}, seed=11, timeframe="15m")
    r = audit_observation_isolation(ep, gen_b)
    assert r["pass"], r["issues"]
    assert "latent_drift_bps" in r["declared_hidden_fields"]


def test_probe_c_isolation(gen_c):
    ep = gen_c.generate(dict(TRAIN_PARAMS), seed=11, timeframe="15m")
    r = audit_observation_isolation(ep, gen_c)
    assert r["pass"], r["issues"]


def test_forbidden_patterns_covered():
    for name in ("regime", "future", "latent", "steps_to", "episode_length",
                 "seed", "generator_state", "exam_type", "drift"):
        assert name in FORBIDDEN_OBSERVATION_PATTERNS


def test_leaky_observation_field_detected(gen_a):
    """构造含隐藏命名字段的观察 -> 审计必须发现(泄漏 fail closed)。"""
    ep = gen_a.generate(TRAIN_PARAMS, seed=12, timeframe="15m")
    leaky = ep.df.copy()
    leaky["regime_direction"] = ep.hidden["regime_direction"].to_numpy()
    bad = GeneratedEpisode(
        spec=ep.spec, df=leaky, hidden=ep.hidden,
        family_version=ep.family_version, timeframe=ep.timeframe,
        is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint,
        declared_feature_columns=ep.declared_feature_columns)
    r = audit_observation_isolation(bad, gen_a)
    assert not r["pass"]
    assert "regime_direction" in r["leaked_fields"]


def test_future_named_field_detected(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=13, timeframe="15m")
    leaky = ep.df.copy()
    leaky["future_return_1"] = 0.0
    bad = GeneratedEpisode(
        spec=ep.spec, df=leaky, hidden=ep.hidden,
        family_version=ep.family_version, timeframe=ep.timeframe,
        is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint,
        declared_feature_columns=ep.declared_feature_columns)
    r = audit_observation_isolation(bad, gen_a)
    assert not r["pass"]
    assert any("future_return_1" in i for i in r["issues"])


def test_benign_named_extra_column_still_rejected(gen_a):
    """阶段 2.6.0a 核心:whitelist 之外的列一律拒绝,与命名无关。

    factor_x / signal_quality / state_7 这类"看起来无害"的命名,
    只要不在预注册 whitelist 中,verify_episode 即 GeneratorError。
    """
    ep = gen_a.generate(TRAIN_PARAMS, seed=15, timeframe="15m")
    for name in ("factor_x", "signal_quality", "state_7"):
        extra = ep.df.copy()
        extra[name] = 0.0
        bad = GeneratedEpisode(
            spec=ep.spec, df=extra, hidden=ep.hidden,
            family_version=ep.family_version, timeframe=ep.timeframe,
            is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint,
            declared_feature_columns=ep.declared_feature_columns)
        with pytest.raises(GeneratorError, match="whitelist"):
            verify_episode(bad)


def test_hidden_not_accessible_from_standard_observation(gen_a, schema):
    """评估器构造的标准 observation 只含特征窗口 + 仓位,无隐藏。"""
    import numpy as np

    from rl_platform.env import AlignedLongFlatEnv

    ep = gen_a.generate(TRAIN_PARAMS, seed=14, timeframe="15m")
    env = AlignedLongFlatEnv(
        features=ep.df[list(schema.feature_names)],
        prices=ep.df[["open", "high", "low", "close"]],
    )
    obs, _ = env.reset(seed=0)
    assert obs.shape == (schema.observation_dim,)  # 8 特征 + 仓位
    assert np.all(np.isfinite(obs))
