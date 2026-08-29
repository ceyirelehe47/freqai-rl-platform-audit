"""工作包 E/M:课程资格的基线排序(Oracle > 规则 > trivial)。

阶段 2.6.0a 更新:所有策略经 obs-only/Oracle 独立接口评估(不再有
ActContext/ctx.df 路径);generate 显式 timeframe;评估绑定 schema。
"""

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


def _evaluate(gen, params, policy, schema):
    eps = [gen.generate(params, seed=s, split="train", timeframe="15m")
           for s in SEEDS]
    return evaluate_policy(policy, eps, CFG, schema)


def test_oracle_beats_rule_and_trivial(gen_a, schema):
    o = _evaluate(gen_a, TRAIN_PARAMS, OracleSegmentedDriftPolicy(),
                  schema)["overall"]
    r = _evaluate(gen_a, TRAIN_PARAMS, RuleTrendPolicy(ma_threshold=0.001),
                  schema)["overall"]
    t_random = _evaluate(gen_a, TRAIN_PARAMS, RandomPolicy(), schema)["overall"]
    t_periodic = _evaluate(
        gen_a, TRAIN_PARAMS, PeriodicTogglePolicy(8), schema)["overall"]
    t_flat = _evaluate(gen_a, TRAIN_PARAMS, AlwaysFlatPolicy(), schema)["overall"]
    assert o["median"] > r["median"] > t_flat["median"]
    assert r["median"] > t_random["median"]
    assert r["median"] > t_periodic["median"]


def test_rule_beats_greedy_and_high_turnover(gen_a, schema):
    r = _evaluate(gen_a, TRAIN_PARAMS, RuleTrendPolicy(ma_threshold=0.001),
                  schema)["overall"]
    greedy = _evaluate(
        gen_a, TRAIN_PARAMS, OneStepGreedyPolicy(), schema)["overall"]
    ht = _evaluate(gen_a, TRAIN_PARAMS, HighTurnoverPolicy(), schema)["overall"]
    assert r["median"] > greedy["median"]
    assert ht["median"] < 0  # 高频扣费必亏


def test_always_long_not_passing_everywhere(gen_a, schema):
    """Always Long 中位可能不差,但最差分位深亏 -> 不能通过所有考试。"""
    long_ = _evaluate(gen_a, TRAIN_PARAMS, AlwaysLongPolicy(), schema)["overall"]
    assert long_["q10"] < 0
    assert long_["worst"] < -0.02


def test_always_flat_not_top(gen_a, schema):
    flat = _evaluate(gen_a, TRAIN_PARAMS, AlwaysFlatPolicy(), schema)["overall"]
    o = _evaluate(gen_a, TRAIN_PARAMS, OracleSegmentedDriftPolicy(),
                  schema)["overall"]
    assert o["median"] > flat["median"]


def test_oracle_reads_hidden_only(gen_a, schema):
    pol = OracleSegmentedDriftPolicy()
    assert pol.reads_hidden is True
    rule = RuleTrendPolicy(ma_threshold=0.001)
    assert rule.reads_hidden is False


def test_null_family_flat_is_strong(gen_a, gen_c, schema):
    """Null 环境中 Always Flat 应是强基线:超额收益全部 <= 0 显著。"""
    from rl_curriculum.counterfactual import test_null_control

    eps = [gen_c.generate(dict(TRAIN_PARAMS), seed=s, split="null_control",
                          timeframe="15m")
           for s in SEEDS]
    r = test_null_control(AlwaysFlatPolicy(),
                          {"probe_null_control": eps}, CFG, schema)
    assert r.pass_
    per = r.extra["per_family"]["probe_null_control"]
    assert per["excess_median"] == 0.0
