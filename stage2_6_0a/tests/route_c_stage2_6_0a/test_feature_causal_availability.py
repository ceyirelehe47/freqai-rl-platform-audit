"""工作包 K1/K2:特征因果可用时点(前缀重算一致)与全槽位前缀比对。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    GeneratorError,
)
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


class _FutureLeakGenerator(BaseMarketGenerator):
    """使用未来窗口的特征(中心化滚动均值)——必须被因果校验发现。"""

    family = "future_leak_features"
    family_version = "leak-v1"
    feature_columns = ["centered_ma"]
    hidden_columns = []

    def _generate(self, params, seed, rng):
        n = int(params.get("episode_bars", 48))
        return rng.normal(0, 0.001, n), pd.DataFrame(index=range(n)), {}

    def _attach_features(self, df):
        out = df.copy()
        # centered rolling mean:窗口含未来行 -> 非因果
        out["centered_ma"] = (
            df["close"].rolling(5, center=True, min_periods=1).mean())
        return out


def test_future_dependent_feature_detected():
    with pytest.raises(GeneratorError, match="因果"):
        _FutureLeakGenerator().generate({"episode_bars": 48}, seed=1,
                                        timeframe="15m")


def test_causal_features_pass_prefix_recompute(gen_a):
    """探针特征在任意前缀重算逐位一致(因果可用时点成立)。"""
    from rl_curriculum.generator_api import _verify_feature_causality

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=111, timeframe="15m")
    issues = _verify_feature_causality(ep, gen_a)
    assert issues == []


def test_causal_declaration_in_schema(schema):
    """K1:每个特征声明因果可用时点/最大历史窗口/信号组/nuisance 旗标。"""
    for f in schema.features:
        assert f.available_at == "close_of_bar_t"
        assert f.max_history_bars >= 1
        assert f.signal_group in ("momentum", "trend", "volatility",
                                  "nuisance")
        assert isinstance(f.nuisance, bool)
    assert schema.nuisance_slot_count == 3


def test_prefix_observation_all_slots(gen_a, cfg, schema):
    """K2:共同前缀内逐决策完整 observation(含账户槽位)一致。"""
    from rl_curriculum.counterfactual import (
        splice_prefix_suffix,
        test_common_prefix_future_suffix,
    )
    from rl_curriculum.policies import RuleTrendPolicy

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=112, timeframe="15m")
    r = test_common_prefix_future_suffix(
        gen_a, RuleTrendPolicy(), ep, cfg, schema)
    assert r.pass_
    assert r.extra["prefix_obs_all_slots_match"] is True
    assert r.extra["prefix_obs_mismatch_step"] is None


def test_nuisance_prefix_stable(gen_a):
    """nuisance 槽位前缀逐位稳定(counter-hash 与行索引绑定)。"""
    from rl_curriculum.generators import fill_nuisance_slots

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=113, timeframe="15m")
    cut = 40
    partial = fill_nuisance_slots(
        ep.df.iloc[:cut][["open", "high", "low", "close", "volume"]],
        family=ep.spec.family, family_version=ep.family_version,
        params=ep.spec.params, seed=ep.spec.seed)
    for slot in ("nuisance_0", "nuisance_1", "nuisance_2"):
        np.testing.assert_array_equal(
            partial[slot].to_numpy(),
            ep.df[slot].iloc[:cut].to_numpy())
