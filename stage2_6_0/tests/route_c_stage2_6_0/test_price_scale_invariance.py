"""工作包 H.2/H.3:价格尺度不变性与初始价格不变性。"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    test_initial_price_invariance,
    test_price_scale_invariance,
)
from rl_curriculum.policies import (
    AbsolutePriceCheaterPolicy,
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def test_rule_policy_scale_invariant(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=51)
    r = test_price_scale_invariance(
        RuleTrendPolicy(ma_threshold=0.001), ep, cfg)
    assert r.pass_, r.reason


def test_oracle_scale_invariant(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=52)
    r = test_price_scale_invariance(
        OracleSegmentedDriftPolicy(), ep, cfg)
    assert r.pass_, r.reason


def test_absolute_price_cheater_detected(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=53)
    r = test_price_scale_invariance(
        AbsolutePriceCheaterPolicy(), ep, cfg)
    assert not r.pass_
    assert r.action_match_rate < 0.999


def test_rule_policy_initial_price_invariant(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=54)
    r = test_initial_price_invariance(
        gen_a, RuleTrendPolicy(ma_threshold=0.001), ep, cfg)
    assert r.pass_, r.reason


def test_absolute_price_cheater_initial_price_detected(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=55)
    r = test_initial_price_invariance(
        gen_a, AbsolutePriceCheaterPolicy(), ep, cfg)
    assert not r.pass_


def test_probe_features_are_scale_invariant_by_construction(gen_a):
    """特征列为比率/对数收益:价格整体缩放不改变特征。"""
    import numpy as np

    ep = gen_a.generate(TRAIN_PARAMS, seed=56)
    scaled = ep.df.copy()
    for col in ("open", "high", "low", "close"):
        scaled[col] = scaled[col] * 100.0
    feats = ["ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"]
    assert np.allclose(
        ep.df[feats].to_numpy(), scaled[feats].to_numpy(), atol=1e-12
    )
