"""工作包 C/D:生成器确定性、合法 OHLCV、NaN/非法 fail closed。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rl_curriculum.generator_api import (
    GeneratedEpisode,
    GeneratorError,
    determinism_check,
    validate_ohlcv,
    verify_episode,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def test_same_seed_same_episode_all_generators(gen_a, gen_b, gen_c):
    for gen, params in ((gen_a, TRAIN_PARAMS),
                        (gen_b, {"episode_bars": 64}),
                        (gen_c, dict(TRAIN_PARAMS))):
        assert determinism_check(gen, params, 21,
                                timeframe="15m")["pass"], gen.family


def test_different_seed_different_episode(gen_a):
    e1 = gen_a.generate(TRAIN_PARAMS, seed=1, timeframe="15m")
    e2 = gen_a.generate(TRAIN_PARAMS, seed=2, timeframe="15m")
    assert not e1.df["close"].equals(e2.df["close"])


def test_generator_fingerprint_changes_with_version(gen_a):
    h1 = gen_a.fingerprint()
    old = gen_a.family_version
    gen_a.family_version = old + "-x"
    h2 = gen_a.fingerprint()
    gen_a.family_version = old
    assert h1 != h2


@pytest.mark.parametrize("gen_name", ["probe_segmented_drift",
                                      "probe_smooth_latent_drift",
                                      "probe_null_control"])
def test_episodes_are_legal_ohlcv(gen_a, gen_b, gen_c, gen_name):
    gen = {"probe_segmented_drift": gen_a,
           "probe_smooth_latent_drift": gen_b,
           "probe_null_control": gen_c}[gen_name]
    for seed in (1, 2, 3):
        ep = gen.generate(TRAIN_PARAMS if gen is not gen_b
                          else {"episode_bars": 64}, seed=seed,
                          timeframe="15m")
        assert validate_ohlcv(ep.df) == []
        verify_episode(ep)  # 不抛


def test_nan_features_fail_closed(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=5, timeframe="15m")
    df = ep.df.copy()
    df.loc[3, "ret_1"] = np.nan
    bad = GeneratedEpisode(
        spec=ep.spec, df=df, hidden=ep.hidden, family_version=ep.family_version,
        timeframe=ep.timeframe, is_null=ep.is_null,
        generator_fingerprint=ep.generator_fingerprint,
        declared_feature_columns=ep.declared_feature_columns)
    with pytest.raises(GeneratorError, match="NaN"):
        verify_episode(bad)


def test_illegal_ohlcv_detected(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=6, timeframe="15m")
    df = ep.df.copy()
    df.loc[10, "high"] = df.loc[10, "close"] * 0.5  # high < close
    issues = validate_ohlcv(df)
    assert any("high" in i for i in issues)
    bad = GeneratedEpisode(
        spec=ep.spec, df=df, hidden=ep.hidden, family_version=ep.family_version,
        timeframe=ep.timeframe, is_null=ep.is_null,
        generator_fingerprint=ep.generator_fingerprint,
        declared_feature_columns=ep.declared_feature_columns)
    with pytest.raises(GeneratorError, match="非法"):
        verify_episode(bad)


def test_time_discontinuity_detected(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=7, timeframe="15m")
    df = ep.df.copy()
    df.loc[20, "open"] = df.loc[20, "open"] * 1.5  # open != close[t-1]
    assert any("连续" in i for i in validate_ohlcv(df))


def test_hidden_frame_length_mismatch_fails(gen_a):
    ep = gen_a.generate(TRAIN_PARAMS, seed=8, timeframe="15m")
    bad = GeneratedEpisode(
        spec=ep.spec, df=ep.df, hidden=ep.hidden.iloc[:-1],
        family_version=ep.family_version, timeframe=ep.timeframe,
        is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint)
    with pytest.raises(GeneratorError, match="hidden 行数"):
        verify_episode(bad)


def test_episode_bars_minimum_enforced(gen_a):
    with pytest.raises(GeneratorError, match="过短"):
        gen_a.generate({"episode_bars": 8}, seed=1, timeframe="15m")


def test_probe_b_independent_code_path(gen_a, gen_b):
    """探针 B 与 A 的机制差异:B 无分段边界,隐藏为连续潜在漂移。"""
    eA = gen_a.generate(TRAIN_PARAMS, seed=9, timeframe="15m")
    eB = gen_b.generate({"episode_bars": 96}, seed=9, timeframe="15m")
    assert list(eB.hidden.columns) == ["latent_drift_bps"]
    # A 的隐藏为分段常数方向;B 的隐藏为连续值(存在非整数漂移)
    assert eB.hidden["latent_drift_bps"].nunique() > 10
    assert "regime_direction" not in eB.hidden.columns
