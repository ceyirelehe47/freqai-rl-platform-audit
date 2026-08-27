"""工作包 I/J:五类故意作弊探针的判定(阶段 2.6.0a 更新)。

阶段 2.6.0a 语义变化(旧断言与新断言的差异见报告第 24 节):
- 作弊探针改用独立 TestOnlyProbePolicy 协议(不再共用正式策略接口);
- classify_cheating 需要四门证据(原始有效成绩/依赖禁止变量/优势崩溃/
  多 Episode 重复),本文件用显式 regimes 构造"固定结构下得分"的
  StepCounter 场景验证;
- 常数动作序列不再是周期作弊(detect_periodicity 返回 None);
- NullOvertrader 判普通挂科(FAIL),不是作弊。
阶段 2.6.0b 更新:classify_cheating 改为 (cf_results, *,
replication_evidence, min_distinct_seeds, min_failing_episodes) 签名
(n_episodes_tested/min_replication 已删);复制证据由
build_replication_evidence(records, base_net_by_episode=...) 构造,
逐 seed 实际运行反事实考试;严格 Null 家族为 sign/volstate/stochvol
(block 降级为诊断族);作弊场景改为"漂移块只落在原始窗口、不落在任何
变体窗口"的显式结构,保证优势在变体中真实崩溃。
"""

from __future__ import annotations

from rl_curriculum.counterfactual import (
    build_replication_evidence,
    classify_cheating,
    detect_periodicity,
    test_common_prefix_future_suffix,
    test_episode_length_invariance,
    test_null_control,
    test_price_scale_invariance,
    test_regime_order_randomization,
)
from rl_curriculum.evaluator import evaluate_policy
from rl_curriculum.generators import FORMAL_NULL_FAMILIES
from rl_curriculum.probes import (
    AbsolutePriceCheaterProbe,
    FutureLeakProbe,
    NullOvertraderProbe,
    PeriodicCheaterProbe,
    StepCounterCheaterProbe,
)
from rl_curriculum.evaluator import EvalConfig, run_policy_episode

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
# 固定结构场景:漂移块 [37,50) 只覆盖 StepCounter 在原始 96-bar Episode
# 的做多窗口 [34,61];短 Episode 窗口 [20,36] 与长变体窗口 [51,92] 都
# 与漂移不相交 -> 原始有效成绩达标且长度变体优势真实崩溃
FIXED_STRUCTURE_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 37], [1, 60.0, 14], [0, 0.0, 45]],
}
# 单调上行场景(两段正漂移):绝对价格作弊探针获得稳定基础成绩;
# ×10/×100 价格尺度变体把价格推到阈值之上 -> 变体空仓,优势崩溃
MONOTONE_UP_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[1, 28.0, 48], [1, 28.0, 48]],
}
# 相位对齐场景:漂移块 [4,7) 恰在周期探针(period=4 -> 做多 [4,8) mod 8)
# 的做多窗口内(探针捕获其中 2 根漂移 bar);两种 regime 旋转(左移到
# [0,3) / 移到末尾 [89,92))都把漂移整体移进空仓相位 -> 优势崩溃
# (周期行为与市场内容无关的实证)
ALIGNED_PERIODIC_PARAMS = {
    "episode_bars": 92,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 4], [1, 800.0, 3], [0, 0.0, 85]],
}
CFG = EvalConfig(fee=0.001)
MIN_EFFECTIVE = 0.02

# 逐作弊原因选用的反事实考试(与 CHEAT_REASON_EXAMS 对应;证据按原因聚合)
_EXAM_BY_REASON = {
    "future_leakage": "common_prefix_future_suffix",
    "absolute_price": "price_scale_invariance",
    "episode_position": "episode_length_invariance",
    "periodic_pattern": "regime_order_randomization",
}


def _run_exam(gen_a, pol, ep, cfg, schema, exam):
    if exam == "episode_length_invariance":
        return test_episode_length_invariance(gen_a, pol, ep, cfg, schema)
    if exam == "price_scale_invariance":
        # 只用放大尺度(×10/×100):把价格推过 buy_below 阈值 -> 变体空仓
        return test_price_scale_invariance(
            pol, ep, cfg, schema, scales=(10.0, 100.0))
    if exam == "regime_order_randomization":
        return test_regime_order_randomization(gen_a, pol, ep, cfg, schema)
    return test_common_prefix_future_suffix(gen_a, pol, ep, cfg, schema)


def _null_episodes(params, seeds):
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    return {
        fam: [
            DEFAULT_GENERATOR_REGISTRY[fam].generate(
                dict(params), seed=s, split="null_control",
                timeframe="15m")
            for s in seeds[:2]
        ]
        for fam in FORMAL_NULL_FAMILIES
    }


def _classify(gen_a, pol, cfg, schema, params, seeds, reason):
    """多 Episode 基础成绩 + 逐 seed 反事实证据 -> classify_cheating。

    阶段 2.6.0b:对每个 seed 实际运行该原因的反事实考试,用
    build_replication_evidence 聚合真实复制证据(distinct seeds /
    failing episodes / 变体收益 bootstrap),不再以考试包 Episode 总数
    冒充重复次数。
    """
    eps = [gen_a.generate(dict(params), seed=s, split="train",
                          timeframe="15m") for s in seeds]
    report = evaluate_policy(pol, eps, cfg, schema)
    exam = _EXAM_BY_REASON[reason]
    records = [_run_exam(gen_a, pol, ep, cfg, schema, exam) for ep in eps]
    base_net_by_episode = {
        ep.spec.seed: run_policy_episode(pol, ep, cfg, schema).net_return
        for ep in eps
    }
    evidence = build_replication_evidence(
        [r.to_record() for r in records],
        base_net_by_episode=base_net_by_episode,
        min_effective_net_return=MIN_EFFECTIVE,
        min_distinct_seeds=3,
        min_failing_episodes=3)
    null_records = [test_null_control(
        pol, _null_episodes(TRAIN_PARAMS, seeds), cfg, schema)]
    cls = classify_cheating(
        records + null_records,
        base_median_net_return=float(report["overall"]["median"]),
        base_seed_pass_ratio=float(report["seed_pass_ratio_vs_always_flat"]),
        replication_evidence={reason: evidence},
        min_effective_net_return=MIN_EFFECTIVE,
        min_seed_pass_ratio=0.5,
        min_distinct_seeds=3,
        min_failing_episodes=3,
    )
    return cls, report, evidence


def test_step_counter_cheater_detected(gen_a, cfg, schema):
    """固定结构下得分良好 + 长度反事实优势崩溃 + 多 seed 重复 ->
    SUSPECTED_CHEATING(episode_position)。"""
    cls, report, evidence = _classify(
        gen_a, StepCounterCheaterProbe(), cfg, schema,
        FIXED_STRUCTURE_PARAMS, seeds=(121, 122, 123, 124),
        reason="episode_position")
    assert report["overall"]["median"] > MIN_EFFECTIVE, (
        f"固定结构场景下 StepCounter 应达到作弊判定最低有效成绩,"
        f"实际中位 {report['overall']['median']}")
    assert evidence["distinct_seeds"] == 4
    assert evidence["failing_episodes"] == 4
    assert evidence["collapse_evidence_available"] is True
    assert evidence["advantage_collapse"] is True
    assert cls["suspected_cheating"]
    assert "episode_position" in cls["cheat_reasons"]
    gate = cls["reason_gates"]["episode_position"]
    assert gate["base_effective_score"] and gate["divergence_detected"] \
        and gate["advantage_collapse"] and gate["replicated"]


def test_absolute_price_cheater_detected(gen_a, cfg, schema):
    """低价区做多(buy_below=150)在上行市场中得分 + 价格尺度反事实崩溃。"""
    cls, report, evidence = _classify(
        gen_a, AbsolutePriceCheaterProbe(buy_below=150.0), cfg, schema,
        MONOTONE_UP_PARAMS, seeds=(211, 212, 213, 214),
        reason="absolute_price")
    assert report["overall"]["median"] > MIN_EFFECTIVE, (
        f"buy_below=150 在上行市场应达到最低有效成绩,"
        f"实际中位 {report['overall']['median']}")
    assert evidence["advantage_collapse"] is True
    assert evidence["replication_met"] is True
    assert cls["suspected_cheating"]
    assert "absolute_price" in cls["cheat_reasons"]
    assert cls["reason_gates"]["absolute_price"]["stands"]


def test_periodic_cheater_detected(gen_a, cfg, schema):
    cls, report, evidence = _classify(
        gen_a, PeriodicCheaterProbe(4), cfg, schema,
        ALIGNED_PERIODIC_PARAMS, seeds=(221, 222, 223, 224),
        reason="periodic_pattern")
    assert report["overall"]["median"] > MIN_EFFECTIVE, (
        f"相位对齐场景下周期探针应达到最低有效成绩,"
        f"实际中位 {report['overall']['median']}")
    assert evidence["advantage_collapse"] is True
    assert evidence["replication_met"] is True
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
    # Null 稳定正超额(无高换手)亦构成泄漏证据(严格三族)
    null_r = test_null_control(
        pol, _null_episodes(TRAIN_PARAMS, (142, 143)), cfg, schema)
    assert (not null_r.pass_) and (not null_r.extra["high_turnover"])


def test_null_overtrader_is_fail_not_cheating(gen_a, cfg, schema):
    """NullOvertrader:高换手 + 扣费亏损 -> 普通挂科(FAIL),不是作弊。"""
    pol = NullOvertraderProbe()
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    null_by_family = {
        fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
            dict(TRAIN_PARAMS), seed=s, split="null_control",
            timeframe="15m") for s in (151, 152, 153, 154)]
        for fam in ("probe_null_sign", "probe_null_volstate")
    }
    r = test_null_control(pol, null_by_family, cfg, schema)
    assert r.extra["high_turnover"] is True
    per = r.extra["per_family"]["probe_null_sign"]
    assert per["excess_median"] < 0
    # 成绩未达作弊门槛且无依赖证据 -> 普通挂科
    cls, _report, _evidence = _classify(
        gen_a, pol, cfg, schema, TRAIN_PARAMS, seeds=(151, 152, 153),
        reason="episode_position")
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
