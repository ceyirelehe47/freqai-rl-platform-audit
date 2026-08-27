"""工作包 H.2/H.3:价格尺度不变性与初始价格不变性。

阶段 2.6.0a 更新:作弊探针走独立协议;全部考试绑定 schema;generate
显式 timeframe。
"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    test_initial_price_invariance,
    test_price_scale_invariance,
)
from rl_curriculum.policies import (
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
)
from rl_curriculum.probes import AbsolutePriceCheaterProbe

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def test_rule_policy_scale_invariant(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=51, timeframe="15m")
    r = test_price_scale_invariance(
        RuleTrendPolicy(ma_threshold=0.001), ep, cfg, schema)
    assert r.pass_, r.reason


def test_oracle_scale_invariant(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=52, timeframe="15m")
    r = test_price_scale_invariance(
        OracleSegmentedDriftPolicy(), ep, cfg, schema)
    assert r.pass_, r.reason


def test_absolute_price_cheater_detected(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=53, timeframe="15m")
    r = test_price_scale_invariance(
        AbsolutePriceCheaterProbe(), ep, cfg, schema)
    assert not r.pass_
    assert r.action_match_rate < 0.999


def test_rule_policy_initial_price_invariant(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=54, timeframe="15m")
    r = test_initial_price_invariance(
        gen_a, RuleTrendPolicy(ma_threshold=0.001), ep, cfg, schema)
    assert r.pass_, r.reason


def test_absolute_price_cheater_initial_price_detected(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=55, timeframe="15m")
    r = test_initial_price_invariance(
        gen_a, AbsolutePriceCheaterProbe(), ep, cfg, schema)
    assert not r.pass_


def test_probe_features_are_scale_invariant_by_construction(gen_a):
    """特征列为比率/对数收益:价格整体缩放不改变特征(nuisance 同)。"""
    import numpy as np

    ep = gen_a.generate(TRAIN_PARAMS, seed=56, timeframe="15m")
    scaled = ep.df.copy()
    for col in ("open", "high", "low", "close"):
        scaled[col] = scaled[col] * 100.0
    feats = ["ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio",
             "nuisance_0", "nuisance_1", "nuisance_2"]
    assert np.allclose(
        ep.df[feats].to_numpy(), scaled[feats].to_numpy(), atol=1e-12
    )
