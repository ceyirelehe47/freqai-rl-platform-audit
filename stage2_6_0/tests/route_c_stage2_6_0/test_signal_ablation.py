"""工作包 H.7/H.8/H.9/H.10/H.11:消融、注入、置乱、镜像与成本单调。"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    test_cost_monotonicity,
    test_irrelevant_feature_injection,
    test_irrelevant_feature_shuffle,
    test_signal_ablation,
    test_trend_direction_mirror,
)
from rl_curriculum.policies import (
    OracleSegmentedDriftPolicy,
    PeriodicCheaterPolicy,
    RuleTrendPolicy,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def _eps(gen_a, seeds=(91, 92, 93, 94, 95)):
    return [gen_a.generate(TRAIN_PARAMS, seed=s) for s in seeds]


def test_signal_ablation_drops_advantage(gen_a, cfg):
    eps = _eps(gen_a)
    r = test_signal_ablation(RuleTrendPolicy(ma_threshold=0.001), eps, cfg)
    assert r.pass_, r.reason
    assert r.extra["median_advantage_drop"] > 0


def test_signal_ablation_detects_uninformed_policy(gen_a, cfg):
    """不读真信号的策略:置乱真信号后优势不降 -> 测试应标记失败。"""
    eps = _eps(gen_a, seeds=(91, 92))
    r = test_signal_ablation(PeriodicCheaterPolicy(6), eps, cfg)
    assert not r.pass_


def test_irrelevant_injection_no_improvement(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=96)
    r = test_irrelevant_feature_injection(
        RuleTrendPolicy(ma_threshold=0.001), ep, cfg)
    assert r.pass_, r.reason


def test_irrelevant_shuffle_no_change(gen_a, cfg):
    ep = gen_a.generate(TRAIN_PARAMS, seed=97)
    r = test_irrelevant_feature_shuffle(
        RuleTrendPolicy(ma_threshold=0.001), ep, cfg, column="vol_24")
    assert r.pass_, r.reason


def test_trend_mirror_direction_capture(gen_a, cfg):
    eps = _eps(gen_a)
    r = test_trend_direction_mirror(RuleTrendPolicy(ma_threshold=0.001), eps, cfg)
    assert r.pass_, r.reason
    assert r.extra["capture_base_median"] > 0
    assert r.extra["capture_mirror_median"] > 0


def test_trend_mirror_flags_uninformed_policy(gen_a, cfg):
    eps = _eps(gen_a, seeds=(91, 92, 93))
    r = test_trend_direction_mirror(PeriodicCheaterPolicy(6), eps, cfg)
    assert not r.pass_


def test_cost_monotonicity_holds(gen_a, cfg):
    # 多 seed 中位数:成本升 -> 净值系统性不升
    import numpy as np
    per_cost = [[], [], []]
    for seed in (98, 99, 100):
        ep = gen_a.generate(TRAIN_PARAMS, seed=seed)
        r = test_cost_monotonicity(RuleTrendPolicy(ma_threshold=0.001), ep, cfg)
        assert r.pass_, (seed, r.reason)
        for i, net in enumerate(r.base["net_returns"]):
            per_cost[i].append(net)
    meds = [float(np.median(c)) for c in per_cost]
    assert meds[0] >= meds[1] >= meds[2]  # 成本档升高 -> 中位净值非增


def test_oracle_mirror_capture(gen_a, cfg):
    eps = _eps(gen_a, seeds=(91, 92, 93))
    r = test_trend_direction_mirror(OracleSegmentedDriftPolicy(), eps, cfg)
    assert r.pass_, r.reason
