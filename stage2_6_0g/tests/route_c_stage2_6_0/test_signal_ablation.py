"""工作包 H.7-H.11 + 阶段 2.6.0a 工作包 I:消融、nuisance 注入/置乱、
镜像与成本单调。

阶段 2.6.0a 语义变化(旧断言与新断言差异见报告第 24 节):
- irrelevant_feature_injection/shuffle 更名为 nuisance_slot_injection/
  nuisance_slot_shuffle:只修改预注册 nuisance 槽位内容,不新增 DataFrame
  列,observation shape 恒定(旧实现加列会改变固定维度 PPO 的输入);
- vol_24 不再被当作"无关特征"置乱(它是正式市场特征);
- signal_ablation 按章程 signal_groups 分组消融(trend 组)。
"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    test_cost_monotonicity,
    test_nuisance_slot_injection,
    test_nuisance_slot_shuffle,
    test_signal_ablation,
    test_trend_direction_mirror,
)
from rl_curriculum.policies import (
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
)
from rl_curriculum.probes import PeriodicCheaterProbe

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def _eps(gen_a, seeds=(91, 92, 93, 94, 95)):
    return [gen_a.generate(TRAIN_PARAMS, seed=s, timeframe="15m")
            for s in seeds]


def test_signal_ablation_drops_advantage(gen_a, cfg, schema):
    eps = _eps(gen_a)
    r = test_signal_ablation(RuleTrendPolicy(ma_threshold=0.001), eps, cfg,
                             schema, signal_group="trend")
    assert r.pass_, r.reason
    assert r.extra["median_advantage_drop"] > 0
    assert r.extra["is_cheat_evidence"] is False  # 不构成作弊证据


def test_signal_ablation_detects_uninformed_policy(gen_a, cfg, schema):
    """不读真信号的策略:消融真信号后优势不降 -> FAIL(非作弊)。"""
    eps = _eps(gen_a, seeds=(91, 92))
    r = test_signal_ablation(PeriodicCheaterProbe(6), eps, cfg, schema,
                             signal_group="trend")
    assert not r.pass_
    assert r.extra["is_cheat_evidence"] is False


def test_signal_ablation_unknown_group_invalid(gen_a, cfg, schema):
    eps = _eps(gen_a, seeds=(91,))
    r = test_signal_ablation(RuleTrendPolicy(ma_threshold=0.001), eps, cfg,
                             schema, signal_group="no_such_group")
    assert not r.pass_
    assert "未在 schema 预注册" in r.reason


def test_nuisance_injection_no_improvement(gen_a, cfg, schema):
    eps = _eps(gen_a, seeds=(96, 97))
    r = test_nuisance_slot_injection(
        RuleTrendPolicy(ma_threshold=0.001), eps, cfg, schema)
    assert r.pass_, r.reason
    assert list(r.extra["observation_shape"]) == [schema.observation_dim]
    assert r.extra["nuisance_slots"] == ["nuisance_0", "nuisance_1",
                                         "nuisance_2"]


def test_nuisance_shuffle_no_improvement(gen_a, cfg, schema):
    eps = _eps(gen_a, seeds=(97, 98))
    r = test_nuisance_slot_shuffle(
        RuleTrendPolicy(ma_threshold=0.001), eps, cfg, schema)
    assert r.pass_, r.reason
    # 正式市场特征未被触碰(vol_24 属 volatility 信号组)
    assert "vol_24" in r.extra["market_features_untouched"]


def test_trend_mirror_direction_capture(gen_a, cfg, schema):
    eps = _eps(gen_a)
    r = test_trend_direction_mirror(RuleTrendPolicy(ma_threshold=0.001),
                                    eps, cfg, schema)
    assert r.pass_, r.reason
    assert r.extra["capture_base_median"] > 0
    assert r.extra["capture_mirror_median"] > 0


def test_trend_mirror_flags_uninformed_policy(gen_a, cfg, schema):
    eps = _eps(gen_a, seeds=(91, 92, 93))
    r = test_trend_direction_mirror(PeriodicCheaterProbe(6), eps, cfg, schema)
    assert not r.pass_


def test_cost_monotonicity_holds(gen_a, cfg, schema):
    # 多 seed 中位数:成本升 -> 净值系统性不升
    import numpy as np

    per_cost = [[], [], []]
    for seed in (98, 99, 100):
        ep = gen_a.generate(TRAIN_PARAMS, seed=seed, timeframe="15m")
        r = test_cost_monotonicity(RuleTrendPolicy(ma_threshold=0.001), ep,
                                   cfg, schema)
        assert r.pass_, (seed, r.reason)
        for i, net in enumerate(r.base["net_returns"]):
            per_cost[i].append(net)
    meds = [float(np.median(c)) for c in per_cost]
    assert meds[0] >= meds[1] >= meds[2]  # 成本档升高 -> 中位净值非增


def test_oracle_mirror_capture(gen_a, cfg, schema):
    eps = _eps(gen_a, seeds=(91, 92, 93))
    r = test_trend_direction_mirror(OracleSegmentedDriftPolicy(), eps, cfg,
                                    schema)
    assert r.pass_, r.reason
