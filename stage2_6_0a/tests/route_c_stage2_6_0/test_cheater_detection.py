"""工作包 I/J:五类故意作弊探针的判定(阶段 2.6.0a 更新)。

阶段 2.6.0a 语义变化(旧断言与新断言的差异见报告第 24 节):
- 作弊探针改用独立 TestOnlyProbePolicy 协议(不再共用正式策略接口);
- classify_cheating 需要四门证据(原始有效成绩/依赖禁止变量/优势崩溃/
  多 Episode 重复),本文件用显式 regimes 构造"固定结构下得分"的
  StepCounter 场景验证;
- 常数动作序列不再是周期作弊(detect_periodicity 返回 None);
- NullOvertrader 判普通挂科(FAIL),不是作弊。
"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    classify_cheating,
    detect_periodicity,
    test_common_prefix_future_suffix,
    test_episode_length_invariance,
    test_null_control,
    test_price_scale_invariance,
    test_regime_order_randomization,
)
from rl_curriculum.evaluator import evaluate_policy
from rl_curriculum.probes import (
    AbsolutePriceCheaterProbe,
    FutureLeakProbe,
    NullOvertraderProbe,
    PeriodicCheaterProbe,
    StepCounterCheaterProbe,
)
from rl_curriculum.evaluator import EvalConfig

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
# 固定结构场景:中段(35%~65%)恰为正漂移 regime -> StepCounter 得分
FIXED_STRUCTURE_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [10.0, 12.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 34], [1, 25.0, 30], [0, 0.0, 32]],
}
# 单调上行场景(两段正漂移):绝对价格作弊探针获得稳定基础成绩
MONOTONE_UP_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[1, 28.0, 48], [1, 28.0, 48]],
}
# 相位对齐场景:regime 周期与周期探针(period=6 -> 12 bars)对齐,
# 旋转一个 regime 后优势崩溃(周期行为与市场内容无关的实证)
ALIGNED_PERIODIC_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 6], [1, 28.0, 6]] * 8,
}
CFG = EvalConfig(fee=0.001)
MIN_EFFECTIVE = 0.02


def _full_tests(gen_a, null_families, pol, cfg, schema, params, seed=121):
    ep = gen_a.generate(dict(params), seed=seed, timeframe="15m")
    tests = [
        test_common_prefix_future_suffix(gen_a, pol, ep, cfg, schema),
        test_price_scale_invariance(pol, ep, cfg, schema),
        test_episode_length_invariance(gen_a, pol, ep, cfg, schema),
        test_regime_order_randomization(gen_a, pol, ep, cfg, schema),
    ]
    null_eps_by_family = {
        fam: [
            __import__("rl_curriculum.generators", fromlist=["x"])
            .DEFAULT_GENERATOR_REGISTRY[fam]
            .generate(dict(TRAIN_PARAMS), seed=s, split="null_control",
                      timeframe="15m")
            for s in (131, 132)
        ]
        for fam in null_families
    }
    tests.append(test_null_control(pol, null_eps_by_family, cfg, schema))
    return tests, ep


def _classify(gen_a, pol, cfg, schema, params, seeds, null_families):
    """多 Episode 基础成绩 + 反事实证据 -> classify_cheating。"""
    eps = [gen_a.generate(dict(params), seed=s, split="train",
                          timeframe="15m") for s in seeds]
    report = evaluate_policy(pol, eps, cfg, schema)
    tests, _ep = _full_tests(
        gen_a, null_families, pol, cfg, schema, params, seed=seeds[0])
    cls = classify_cheating(
        tests,
        base_median_net_return=float(report["overall"]["median"]),
        base_seed_pass_ratio=float(report["seed_pass_ratio_vs_always_flat"]),
        n_episodes_tested=len(eps),
        min_effective_net_return=MIN_EFFECTIVE,
        min_seed_pass_ratio=0.5,
        min_replication=3,
    )
    return cls, report


def test_step_counter_cheater_detected(gen_a, cfg, schema):
    """固定结构下得分良好 + 长度反事实优势崩溃 + 多 seed 重复 ->
    SUSPECTED_CHEATING(episode_position)。"""
    cls, report = _classify(
        gen_a, StepCounterCheaterProbe(), cfg, schema,
        FIXED_STRUCTURE_PARAMS, seeds=(121, 122, 123, 124),
        null_families=("probe_null_sign", "probe_null_block"))
    assert report["overall"]["median"] > MIN_EFFECTIVE, (
        f"固定结构场景下 StepCounter 应达到作弊判定最低有效成绩,"
        f"实际中位 {report['overall']['median']}")
    assert cls["suspected_cheating"]
    assert "episode_position" in cls["cheat_reasons"]
    gate = cls["reason_gates"]["episode_position"]
    assert gate["base_effective_score"] and gate["advantage_collapse"] \
        and gate["replicated"]


def test_absolute_price_cheater_detected(gen_a, cfg, schema):
    """低价区做多(buy_below=150)在上行市场中得分 + 价格尺度反事实崩溃。"""
    cls, report = _classify(
        gen_a, AbsolutePriceCheaterProbe(buy_below=150.0), cfg, schema,
        MONOTONE_UP_PARAMS, seeds=(211, 212, 213, 214),
        null_families=("probe_null_sign", "probe_null_block"))
    assert report["overall"]["median"] > MIN_EFFECTIVE, (
        f"buy_below=150 在上行市场应达到最低有效成绩,"
        f"实际中位 {report['overall']['median']}")
    assert cls["suspected_cheating"]
    assert "absolute_price" in cls["cheat_reasons"]
    assert cls["reason_gates"]["absolute_price"]["stands"]


def test_periodic_cheater_detected(gen_a, cfg, schema):
    cls, report = _classify(
        gen_a, PeriodicCheaterProbe(6), cfg, schema,
        ALIGNED_PERIODIC_PARAMS, seeds=(221, 222, 223, 224),
        null_families=("probe_null_sign", "probe_null_block"))
    assert report["overall"]["median"] > MIN_EFFECTIVE
    assert cls["suspected_cheating"]
    assert "periodic_pattern" in cls["cheat_reasons"]
    assert cls["reason_gates"]["periodic_pattern"]["stands"]


def test_future_leak_probe_detected(gen_a, cfg, schema):
    """多切割点共同前缀必须发现未来泄漏(探针只在测试 harness 获得未来)。"""
    pol = FutureLeakProbe(fee_threshold=cfg.fee)
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=141, timeframe="15m")
    cp_fail = any(
        not test_common_prefix_future_suffix(
            gen_a, pol, ep, cfg, schema, cut_ratio=cr).pass_
        for cr in (0.3, 0.5, 0.7)
    )
    assert cp_fail, "共同前缀测试必须发现 FutureLeakProbe"
    # Null 稳定正超额(无高换手)亦构成泄漏证据
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    null_by_family = {
        fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
            dict(TRAIN_PARAMS), seed=s, split="null_control",
            timeframe="15m") for s in (142, 143)]
        for fam in ("probe_null_sign", "probe_null_block")
    }
    null_r = test_null_control(pol, null_by_family, cfg, schema)
    assert (not null_r.pass_) and (not null_r.extra["high_turnover"])


def test_null_overtrader_is_fail_not_cheating(gen_a, cfg, schema):
    """NullOvertrader:高换手 + 扣费亏损 -> 普通挂科(FAIL),不是作弊。"""
    pol = NullOvertraderProbe()
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    null_by_family = {
        fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
            dict(TRAIN_PARAMS), seed=s, split="null_control",
            timeframe="15m") for s in (151, 152, 153, 154)]
        for fam in ("probe_null_control", "probe_null_sign")
    }
    r = test_null_control(pol, null_by_family, cfg, schema)
    assert r.extra["high_turnover"] is True
    per = r.extra["per_family"]["probe_null_control"]
    assert per["excess_median"] < 0
    # 成绩未达作弊门槛且无依赖证据 -> 普通挂科
    cls, _report = _classify(
        gen_a, pol, cfg, schema, TRAIN_PARAMS, seeds=(151, 152, 153),
        null_families=("probe_null_control", "probe_null_sign"))
    assert not cls["suspected_cheating"]
    assert cls["ordinary_failure_only"]


def test_periodicity_detector():
    assert detect_periodicity([0, 1] * 20) == 2
    assert detect_periodicity([0, 0, 1] * 5) == 3
    assert detect_periodicity([0, 1, 1, 0, 1, 0, 0, 1, 1, 1]) is None
    # J1(阶段 2.6.0a 修订):常数序列无实际仓位切换 -> 不是周期作弊。
    # 旧断言 detect_periodicity([0] * 10) == 2 把常数动作当作周期,
    # 会使全程空仓/全程满仓模型被误判 periodic cheating。
    assert detect_periodicity([0] * 10) is None
    assert detect_periodicity([1] * 50) is None
    # 换手不足(少于最小切换次数)同样不算
    assert detect_periodicity([0, 1] + [1] * 30) is None
