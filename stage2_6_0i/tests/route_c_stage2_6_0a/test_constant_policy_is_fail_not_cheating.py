"""工作包 J:常数动作/全程空仓是普通挂科(FAIL),不是作弊。
阶段 2.6.0b 更新:classify_cheating 新签名(复制证据由
build_replication_evidence 构造,不再接收 n_episodes_tested/
min_replication);严格 Null 三族改为 sign/volstate/stochvol。"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    build_replication_evidence,
    classify_cheating,
)
from rl_curriculum.evaluator import evaluate_policy
from rl_curriculum.policies import AlwaysFlatPolicy, AlwaysLongPolicy
from rl_curriculum.verdict_spec import probe_course_verdict_spec
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def _full_cf(gen_a, pol, cfg, schema, seeds=(81, 82, 83)):
    from rl_curriculum.counterfactual import (
        test_common_prefix_future_suffix,
        test_cost_monotonicity,
        test_episode_length_invariance,
        test_initial_price_invariance,
        test_nuisance_slot_injection,
        test_nuisance_slot_shuffle,
        test_null_control,
        test_price_scale_invariance,
        test_regime_order_randomization,
        test_signal_ablation,
        test_time_shift_invariance,
        test_trend_direction_mirror,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    eps = [gen_a.generate(dict(TRAIN_PARAMS), seed=s, timeframe="15m")
           for s in seeds]
    base = eps[0]
    gen_a_r = DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]
    nulls = {
        fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
            dict(TRAIN_PARAMS), seed=s, split="null_control",
            timeframe="15m") for s in (84, 85)]
        for fam in ("probe_null_sign", "probe_null_volstate",
                    "probe_null_stochvol")
    }
    tests = [
        test_common_prefix_future_suffix(gen_a_r, pol, base, cfg, schema),
        test_price_scale_invariance(pol, base, cfg, schema),
        test_initial_price_invariance(gen_a_r, pol, base, cfg, schema),
        test_episode_length_invariance(gen_a_r, pol, base, cfg, schema),
        test_time_shift_invariance(pol, base, cfg, schema),
        test_regime_order_randomization(gen_a_r, pol, base, cfg, schema),
        test_nuisance_slot_injection(pol, eps, cfg, schema),
        test_nuisance_slot_shuffle(pol, eps, cfg, schema),
        test_signal_ablation(pol, eps, cfg, schema, signal_group="trend"),
        test_trend_direction_mirror(pol, eps, cfg, schema),
        test_cost_monotonicity(pol, base, cfg, schema),
        test_null_control(pol, nulls, cfg, schema),
    ]
    report = evaluate_policy(pol, eps, cfg, schema)
    # 2.6.0b 工作包 E:逐作弊原因聚合真实多 Episode 复制证据
    records = [t.to_record() for t in tests]
    from rl_curriculum.evaluator import run_policy_episode

    base_net_by_episode = {
        ep.spec.seed: run_policy_episode(pol, ep, cfg, schema).net_return
        for ep in eps
    }
    evidence = {
        reason: build_replication_evidence(
            [r for r in records if r["test"] in names],
            base_net_by_episode=base_net_by_episode,
            min_effective_net_return=0.02,
            min_distinct_seeds=3, min_failing_episodes=3)
        for reason, names in (
            ("future_leakage", ("common_prefix_future_suffix",)),
            ("absolute_price", ("price_scale_invariance",
                                "initial_price_invariance")),
            ("episode_position", ("episode_length_invariance",
                                  "time_shift_invariance")),
            ("periodic_pattern", ("regime_order_randomization",)),
        )
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
    return cls, report, tests


def test_always_flat_is_ordinary_failure(gen_a, cfg, schema):
    """全程空仓:未达有效成绩 + 无依赖证据 -> FAIL,不是 SUSPECTED_CHEATING。"""
    cls, report, tests = _full_cf(gen_a, AlwaysFlatPolicy(), cfg, schema)
    assert report["overall"]["median"] == 0.0
    assert not cls["suspected_cheating"]
    assert cls["cheat_reasons"] == []
    assert cls["ordinary_failure_only"] is True
    # 判定器输出 FAIL(而非作弊/无效)
    v = probe_course_verdict_spec().evaluate({
        "integrity_ok": True, "report": report,
        "counterfactual_results": [t.to_record() for t in tests],
        "cheating": cls})
    assert v["status"] == "FAIL"


def test_always_long_is_ordinary_failure(gen_a, cfg, schema):
    """全程满仓(常数动作):判 FAIL;周期检测不视为作弊。"""
    cls, report, tests = _full_cf(gen_a, AlwaysLongPolicy(), cfg, schema)
    assert not cls["suspected_cheating"]
    from rl_curriculum.counterfactual import detect_periodicity

    actions = [1] * 95
    assert detect_periodicity(actions) is None  # 常数序列非周期作弊


def test_unresponsive_but_losing_not_cheating(gen_a, cfg, schema):
    """不响应 regime 且成绩差 -> 普通挂科(证据门槛未过)。"""
    from rl_curriculum.probes import PeriodicCheaterProbe

    # 周期探针在普通训练参数下无固定结构优势(中位成绩低)
    cls, report, _ = _full_cf(gen_a, PeriodicCheaterProbe(6), cfg, schema)
    assert not cls["suspected_cheating"], cls["cheat_reasons"]
    assert cls["ordinary_failure_only"] is True


def test_detect_periodicity_requires_switches():
    from rl_curriculum.counterfactual import detect_periodicity

    assert detect_periodicity([0, 1] * 30) == 2
    assert detect_periodicity([0] * 100) is None      # 常数
    assert detect_periodicity([1] * 100) is None      # 常数
    assert detect_periodicity([0, 1, 1, 1] + [1] * 50) is None  # 换手不足
    # 单段长持仓 -> 无周期
    assert detect_periodicity([0] * 40 + [1] * 40) is None
