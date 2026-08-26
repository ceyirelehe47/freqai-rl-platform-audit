"""工作包 J:周期作弊需要"高分 + 反事实优势崩溃"双证据。"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    classify_cheating,
    detect_periodicity,
    test_regime_order_randomization,
)
from rl_curriculum.evaluator import evaluate_policy
from rl_curriculum.probes import PeriodicCheaterProbe
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS

# 相位对齐场景:regime 与周期探针对齐 -> 原始高分;旋转后崩溃
ALIGNED = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 6], [1, 28.0, 6]] * 8,
}


def _cheat_inputs(gen_a, pol, cfg, schema, params, seeds):
    eps = [gen_a.generate(dict(params), seed=s, timeframe="15m")
           for s in seeds]
    report = evaluate_policy(pol, eps, cfg, schema)
    tests = [
        test_regime_order_randomization(gen_a, pol, eps[0], cfg, schema)]
    cls = classify_cheating(
        tests,
        base_median_net_return=float(report["overall"]["median"]),
        base_seed_pass_ratio=float(
            report["seed_pass_ratio_vs_always_flat"]),
        n_episodes_tested=len(eps),
        min_effective_net_return=0.02,
        min_seed_pass_ratio=0.5, min_replication=3)
    return cls, report


def test_periodic_with_advantage_is_cheating(gen_a, cfg, schema):
    cls, report = _cheat_inputs(
        gen_a, PeriodicCheaterProbe(6), cfg, schema, ALIGNED,
        seeds=(91, 92, 93, 94))
    assert report["overall"]["median"] > 0.02
    assert cls["suspected_cheating"]
    assert "periodic_pattern" in cls["cheat_reasons"]
    gates = cls["reason_gates"]["periodic_pattern"]
    assert gates["base_effective_score"] and gates["advantage_collapse"] \
        and gates["replicated"] and gates["stands"]


def test_periodic_without_advantage_is_not_cheating(gen_a, cfg, schema):
    """同样的周期行为,但原始成绩差(普通训练参数) -> 不判作弊。"""
    cls, report = _cheat_inputs(
        gen_a, PeriodicCheaterProbe(6), cfg, schema, TRAIN_PARAMS,
        seeds=(95, 96, 97, 98))
    assert not cls["suspected_cheating"]
    assert cls["ordinary_failure_only"] is True


def test_periodic_evidence_requires_period_and_unresponsiveness():
    """J1:周期证据 = 实际仓位切换的重复周期(有切换;重复次数足够)。"""
    assert detect_periodicity([0, 1] * 20) == 2        # 20 个周期
    assert detect_periodicity([0, 0, 1] * 5) == 3      # 5 个周期
    assert detect_periodicity([0, 1, 1, 0, 1]) is None  # 无稳定周期
    # 重复次数不足(min_repetitions)
    assert detect_periodicity([0, 1, 1, 0, 1, 1, 0]) is None
