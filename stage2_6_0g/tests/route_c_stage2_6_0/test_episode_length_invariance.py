"""工作包 H.4/H.5/H.6:Episode 长度不变性、时间平移与 regime 顺序随机化。

阶段 2.6.0a 更新:探针走独立协议;全部考试绑定 schema;generate 显式
timeframe;长度考试比较完整 observation 槽位。
阶段 2.6.0b 更新:market_unresponsive 判定要求重排后动作序列完全不变;
随机 regime 场景可能恰好全为非正方向(Oracle 动作恒 0 而被误判"不响
应"),响应性断言改用显式混合方向 regimes 构造确定性场景。
"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    test_episode_length_invariance,
    test_regime_order_randomization,
    test_time_shift_invariance,
)
from rl_curriculum.policies import (
    OracleSegmentedDriftPolicy,
    RuleTrendPolicy,
)
from rl_curriculum.probes import PeriodicCheaterProbe, StepCounterCheaterProbe

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
# 显式混合方向 regimes(+1/0/-1 交错):重排必然改变逐 bar 方向序列,
# 读市场观察的策略(Oracle/规则)动作必然响应(确定性场景)
RESPONSIVE_REGIMES_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [10.0, 12.0],
    "initial_price": 100.0,
    "regimes": [[1, 25.0, 24], [0, 0.0, 24], [-1, 25.0, 24], [1, 25.0, 24]],
}


def test_rule_length_invariant(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=61, timeframe="15m")
    r = test_episode_length_invariance(
        gen_a, RuleTrendPolicy(ma_threshold=0.001), ep, cfg, schema)
    assert r.pass_, r.reason
    assert r.extra["prefix_obs_all_slots_match"] is True


def test_oracle_length_invariant(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=62, timeframe="15m")
    r = test_episode_length_invariance(
        gen_a, OracleSegmentedDriftPolicy(), ep, cfg, schema)
    assert r.pass_, r.reason


def test_step_counter_fails_length_invariance(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=63, timeframe="15m")
    r = test_episode_length_invariance(
        gen_a, StepCounterCheaterProbe(), ep, cfg, schema)
    assert not r.pass_
    assert r.first_divergence_step is not None


def test_time_shift_invariant_for_market_policies(gen_a, cfg, schema):
    for pol in (RuleTrendPolicy(ma_threshold=0.001),
                OracleSegmentedDriftPolicy(),
                StepCounterCheaterProbe()):
        ep = gen_a.generate(TRAIN_PARAMS, seed=64, timeframe="15m")
        r = test_time_shift_invariance(pol, ep, cfg, schema)
        assert r.pass_, (pol.name, r.reason)


def test_regime_shuffle_keeps_market_responsive(gen_a, cfg, schema):
    params = dict(RESPONSIVE_REGIMES_PARAMS)
    ep = gen_a.generate(params, seed=65, timeframe="15m")
    for pol in (RuleTrendPolicy(ma_threshold=0.001),
                OracleSegmentedDriftPolicy()):
        r = test_regime_order_randomization(gen_a, pol, ep, cfg, schema)
        assert r.pass_, (pol.name, r.reason)
        assert r.extra["market_unresponsive"] is False


def test_step_counter_unresponsive_to_regime_shuffle(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=66, timeframe="15m")
    r = test_regime_order_randomization(
        gen_a, StepCounterCheaterProbe(), ep, cfg, schema)
    assert not r.pass_
    assert r.extra["market_unresponsive"] is True


def test_periodic_cheater_unresponsive_and_periodic(gen_a, cfg, schema):
    ep = gen_a.generate(TRAIN_PARAMS, seed=67, timeframe="15m")
    r = test_regime_order_randomization(
        gen_a, PeriodicCheaterProbe(6), ep, cfg, schema)
    assert not r.pass_
    assert r.extra["action_period"] == 12


def test_regime_shuffle_preserves_regime_multiset(gen_a):
    """重排只改顺序不改段集合(同类 regime,不同顺序)。"""
    from collections import Counter

    ep = gen_a.generate(TRAIN_PARAMS, seed=68, timeframe="15m")
    regimes = [tuple(r) for r in ep.meta["regimes"]]
    shuffled = [tuple(r) for r in regimes[1:] + regimes[:1]]
    params = dict(TRAIN_PARAMS)
    params["regimes"] = [list(r) for r in shuffled]
    ep2 = gen_a.generate(params, seed=68, timeframe="15m")
    assert Counter(regimes) == Counter(
        tuple(r) for r in ep2.meta["regimes"])
