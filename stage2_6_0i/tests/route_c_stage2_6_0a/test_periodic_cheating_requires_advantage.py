"""工作包 J:周期作弊需要"高分 + 反事实优势崩溃"双证据。
阶段 2.6.0b 更新:四门证据语义——复制证据按"该原因实际测试的
Episode/seed"聚合(build_replication_evidence),不再用考试包
Episode 总数冒充重复次数;classify_cheating 新签名。"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    build_replication_evidence,
    classify_cheating,
    detect_periodicity,
    test_regime_order_randomization,
)
from rl_curriculum.evaluator import evaluate_policy, run_policy_episode
from rl_curriculum.probes import PeriodicCheaterProbe
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS

# 相位对齐场景:regime 段(3 bars)与周期探针(period=6 -> 12 bars)
# 对齐 -> 原始高分;任意段旋转(1 段=3 bars / 2 段=6 bars 相位移动)后
# 做多窗口落入负漂移段 -> 优势崩溃(旧 [0,+] 交替模式旋转 2 段后
# 恢复对齐,无法构成崩溃证据,已按 2.6.0b 四门证据语义重排)
ALIGNED = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[-1, 28.0, 3], [-1, 28.0, 3],
                [1, 28.0, 3], [1, 28.0, 3]] * 8,
}


def _cheat_inputs(gen_a, pol, cfg, schema, params, seeds):
    """多 Episode 成绩 + 逐 Episode regime 顺序考试 -> 复制证据 ->
    classify_cheating(工作包 E:逐原因真实多 seed 聚合)。"""
    eps = [gen_a.generate(dict(params), seed=s, timeframe="15m")
           for s in seeds]
    report = evaluate_policy(pol, eps, cfg, schema)
    tests = [test_regime_order_randomization(gen_a, pol, ep, cfg, schema)
             for ep in eps]
    base_net_by_episode = {
        ep.spec.seed: run_policy_episode(pol, ep, cfg, schema).net_return
        for ep in eps
    }
    evidence = {
        "periodic_pattern": build_replication_evidence(
            [t.to_record() for t in tests],
            base_net_by_episode=base_net_by_episode,
            min_effective_net_return=0.02,
            min_distinct_seeds=3, min_failing_episodes=3),
    }
    cls = classify_cheating(
        tests,
        base_median_net_return=float(report["overall"]["median"]),
        base_seed_pass_ratio=float(
            report["seed_pass_ratio_vs_always_flat"]),
        replication_evidence=evidence,
        min_effective_net_return=0.02,
        min_seed_pass_ratio=0.5,
        min_distinct_seeds=3, min_failing_episodes=3)
    return cls, report, evidence


def test_periodic_with_advantage_is_cheating(gen_a, cfg, schema):
    cls, report, evidence = _cheat_inputs(
        gen_a, PeriodicCheaterProbe(6), cfg, schema, ALIGNED,
        seeds=(91, 92, 93, 94))
    assert report["overall"]["median"] > 0.02
    assert cls["suspected_cheating"]
    assert "periodic_pattern" in cls["cheat_reasons"]
    gates = cls["reason_gates"]["periodic_pattern"]
    assert gates["base_effective_score"] and gates["advantage_collapse"] \
        and gates["replicated"] and gates["stands"]
    ev = evidence["periodic_pattern"]
    # 证据是真实多 seed 重复(不是考试包 Episode 总数冒充)
    assert ev["distinct_seeds"] >= 3
    assert ev["failing_episodes"] >= 3
    assert ev["collapse_evidence_available"] is True


def test_periodic_without_advantage_is_not_cheating(gen_a, cfg, schema):
    """同样的周期行为,但原始成绩差(普通训练参数) -> 不判作弊。"""
    cls, report, _ev = _cheat_inputs(
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
