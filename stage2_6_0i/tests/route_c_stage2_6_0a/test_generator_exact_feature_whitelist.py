"""工作包 K:generate() 自动执行 observation 精确 whitelist。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    GeneratedEpisode,
    GeneratorError,
    verify_episode,
)
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _LeakyGenerator(BaseMarketGenerator):
    """声明 whitelist 却输出额外列的坏生成器。"""

    family = "leaky_extra"
    family_version = "leaky-v1"
    feature_columns = ["ret_1", "nuisance_0"]
    hidden_columns = ["h1"]
    nuisance_slot_names = ("nuisance_0",)

    def _generate(self, params, seed, rng):
        n = int(params.get("episode_bars", 32))
        returns = rng.normal(0, 0.001, n)
        hidden = pd.DataFrame({"h1": np.zeros(n)})
        return returns, hidden, {}

    def _attach_features(self, df):
        out = df.copy()
        out["ret_1"] = 0.0
        out["factor_x"] = 0.0  # 命名无害,但不在 whitelist
        return out


class _MissingGenerator(_LeakyGenerator):
    family = "leaky_missing"
    nuisance_slot_names = ()  # 不由基类补齐 nuisance -> 真缺列

    def _attach_features(self, df):
        out = df.copy()
        out["ret_1"] = 0.0  # 缺 nuisance_0
        return out


def test_extra_column_generator_fails_at_generate():
    with pytest.raises(GeneratorError, match="额外特征列"):
        _LeakyGenerator().generate({"episode_bars": 32}, seed=1,
                                   timeframe="15m")


def test_missing_column_generator_fails_at_generate():
    with pytest.raises(GeneratorError, match="缺少 whitelist"):
        _MissingGenerator().generate({"episode_bars": 32}, seed=1,
                                     timeframe="15m")


def test_hidden_overlap_rejected(gen_a):
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=101, timeframe="15m")
    bad = GeneratedEpisode(
        spec=ep.spec, df=ep.df.copy(),
        hidden=pd.DataFrame(
            {"ma_ratio": np.zeros(len(ep.df))}),  # 隐藏列撞观察列
        family_version=ep.family_version, timeframe=ep.timeframe,
        is_null=ep.is_null, generator_fingerprint=ep.generator_fingerprint,
        declared_feature_columns=ep.declared_feature_columns)
    with pytest.raises(GeneratorError, match="隐藏列进入 observation"):
        verify_episode(bad)


def test_nuisance_must_be_in_feature_columns():
    class _BadNuisance(BaseMarketGenerator):
        family = "bad_nuisance"
        family_version = "v1"
        feature_columns = ["ret_1"]
        hidden_columns = []
        nuisance_slot_names = ("not_in_list",)

        def _generate(self, params, seed, rng):
            n = 32
            return rng.normal(0, 0.001, n), pd.DataFrame(), {}

        def _attach_features(self, df):
            out = df.copy()
            out["ret_1"] = 0.0
            return out

    with pytest.raises(GeneratorError, match="nuisance 槽位"):
        _BadNuisance().generate({"episode_bars": 32}, seed=1,
                                timeframe="15m")


def test_all_registered_generators_verify(gen_a):
    """generate() 内置 verify_episode:每个注册族都能生成(白名单齐整)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    for fam, gen in DEFAULT_GENERATOR_REGISTRY.items():
        ep = gen.generate({"episode_bars": 48}, seed=7, timeframe="15m")
        assert set(ep.observation_columns()) == set(gen.feature_columns)
        assert ep.declared_feature_columns == tuple(gen.feature_columns)
