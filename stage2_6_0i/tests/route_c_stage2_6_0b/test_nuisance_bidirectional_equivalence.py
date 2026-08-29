"""工作包 D:nuisance 双边等价检验(行为/收益/换手/仓位四维稳定)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.counterfactual import (
    NuisanceEquivalenceSpec,
    test_nuisance_slot_injection,
    test_nuisance_slot_shuffle,
)
from rl_curriculum.generator_api import EpisodeSpec
from rl_curriculum.generators import ProbeSegmentedDriftGenerator
from rl_curriculum.policy_api import ObservableBaselinePolicy
from rl_curriculum.policies import RuleTrendPolicy


@pytest.fixture(scope="module")
def ext_episodes():
    gen = ProbeSegmentedDriftGenerator()
    params = {"episode_bars": 96,
              "drift_bps_range": [30.0, 45.0],
              "vol_bps_range": [32.0, 50.0]}
    return [gen.generate(dict(params), s, split="param_extrapolation",
                         timeframe="15m") for s in (301, 302, 303)]


@pytest.fixture(scope="module")
def fast_spec():
    return NuisanceEquivalenceSpec(n_transform_seeds=3, bootstrap_iters=400)


def test_rule_trend_ignoring_nuisance_passes_both_modes(
        ext_episodes, schema, cfg, fast_spec):
    policy = RuleTrendPolicy()
    for fn in (test_nuisance_slot_injection, test_nuisance_slot_shuffle):
        r = fn(policy, ext_episodes, cfg, schema, spec=fast_spec)
        assert r.pass_, f"{fn.__name__}: {r.reason}"
        assert r.extra["observation_shape"] == list(
            schema.observation_shape())
        assert r.extra["n_pairs"] == len(ext_episodes) * 3
        assert r.action_match_rate == 1.0


def test_equivalence_spec_is_preregistered_and_hashable(fast_spec):
    payload = fast_spec.canonical_payload()
    for key in ("delta_return", "action_match_min", "turnover_abs_tol",
                "position_abs_tol", "n_transform_seeds", "bootstrap_iters",
                "bootstrap_alpha"):
        assert key in payload
    assert fast_spec.spec_hash().startswith("ne-")
    other = NuisanceEquivalenceSpec(delta_return=0.001)
    assert fast_spec.spec_hash() != other.spec_hash()


def test_market_features_bitwise_untouched(ext_episodes, schema, cfg,
                                            fast_spec):
    from rl_curriculum.counterfactual import _nuisance_variant_df

    ep = ext_episodes[0]
    before = ep.df[ep.df.columns[:8]].copy()
    _nuisance_variant_df(ep, schema, transform=lambda a, r: r.permutation(a),
                         seed=1)
    after = ep.df[ep.df.columns[:8]]
    assert before.equals(after), "nuisance 考试触碰了正式市场特征"
    assert len(ep.df.columns) == len(schema.feature_names) + 6  # date+OHLCV


def test_observation_shape_constant_under_variants(ext_episodes, schema):
    from rl_curriculum.counterfactual import _nuisance_variant_df

    expected = schema.observation_shape()
    for ep in ext_episodes:
        df = _nuisance_variant_df(
            ep, schema, transform=lambda a, r: r.standard_normal(len(a)),
            seed=5)
        assert df.shape == ep.df.shape
        assert list(df.columns) == list(ep.df.columns)
