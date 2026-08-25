"""工作包 E/M:课程资格的基线排序(Oracle > 规则 > trivial)。"""

from __future__ import annotations

from rl_curriculum.evaluator import EvalConfig, evaluate_policy
from rl_curriculum.policies import (
    AlwaysFlatPolicy,
    AlwaysLongPolicy,
    HighTurnoverPolicy,
    OneStepGreedyPolicy,
    OracleSegmentedDriftPolicy,
    PeriodicTogglePolicy,
    RandomPolicy,
    RuleTrendPolicy,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
CFG = EvalConfig(fee=0.001)
SEEDS = (101, 102, 103, 104, 105, 106, 107, 108)


def _evaluate(gen, params, policy):
    eps = [gen.generate(params, seed=s, split="train") for s in SEEDS]
    return evaluate_policy(policy, eps, CFG)


def test_oracle_beats_rule_and_trivial(gen_a):
    o = _evaluate(gen_a, TRAIN_PARAMS, OracleSegmentedDriftPolicy())["overall"]
    r = _evaluate(gen_a, TRAIN_PARAMS, RuleTrendPolicy(ma_threshold=0.001))["overall"]
    t_random = _evaluate(gen_a, TRAIN_PARAMS, RandomPolicy(seed=0))["overall"]
    t_periodic = _evaluate(
        gen_a, TRAIN_PARAMS, PeriodicTogglePolicy(8))["overall"]
    t_flat = _evaluate(gen_a, TRAIN_PARAMS, AlwaysFlatPolicy())["overall"]
    assert o["median"] > r["median"] > t_flat["median"]
    assert r["median"] > t_random["median"]
    assert r["median"] > t_periodic["median"]


def test_rule_beats_greedy_and_high_turnover(gen_a):
    r = _evaluate(gen_a, TRAIN_PARAMS, RuleTrendPolicy(ma_threshold=0.001))["overall"]
    greedy = _evaluate(
        gen_a, TRAIN_PARAMS, OneStepGreedyPolicy())["overall"]
    ht = _evaluate(gen_a, TRAIN_PARAMS, HighTurnoverPolicy())["overall"]
    assert r["median"] > greedy["median"]
    assert ht["median"] < 0  # 高频扣费必亏


def test_always_long_not_passing_everywhere(gen_a):
    """Always Long 中位可能不差,但最差分位深亏 -> 不能通过所有考试。"""
    long_ = _evaluate(gen_a, TRAIN_PARAMS, AlwaysLongPolicy())["overall"]
    assert long_["q10"] < 0
    assert long_["worst"] < -0.02


def test_always_flat_not_top(gen_a):
    flat = _evaluate(gen_a, TRAIN_PARAMS, AlwaysFlatPolicy())["overall"]
    o = _evaluate(gen_a, TRAIN_PARAMS, OracleSegmentedDriftPolicy())["overall"]
    assert o["median"] > flat["median"]


def test_oracle_reads_hidden_only(gen_a):
    pol = OracleSegmentedDriftPolicy()
    assert pol.reads_hidden is True
    rule = RuleTrendPolicy(ma_threshold=0.001)
    assert rule.reads_hidden is False


def test_null_family_flat_is_strong(gen_a, gen_c):
    """Null 环境中 Always Flat 应是强基线:超额收益全部 <= 0 显著。"""
    from rl_curriculum.counterfactual import test_null_control

    eps = [gen_c.generate(dict(TRAIN_PARAMS), seed=s, split="null_control")
           for s in SEEDS]
    r = test_null_control(AlwaysFlatPolicy(), eps, CFG)
    assert r.pass_
    assert r.extra["excess_median"] == 0.0
