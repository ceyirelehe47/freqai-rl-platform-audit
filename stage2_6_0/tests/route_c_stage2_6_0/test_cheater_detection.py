"""工作包 I:五类故意作弊策略全部被识别(SUSPECTED_CHEATING / Null 挂科)。"""

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
from rl_curriculum.policies import (
    AbsolutePriceCheaterPolicy,
    FutureLeakProbePolicy,
    NullOvertraderPolicy,
    PeriodicCheaterPolicy,
    StepCounterCheaterPolicy,
)

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


def _full_tests(gen_a, gen_c, pol, cfg, seed=121):
    ep = gen_a.generate(TRAIN_PARAMS, seed=seed)
    tests = [
        test_common_prefix_future_suffix(gen_a, pol, ep, cfg),
        test_price_scale_invariance(pol, ep, cfg),
        test_episode_length_invariance(gen_a, pol, ep, cfg),
        test_regime_order_randomization(gen_a, pol, ep, cfg),
    ]
    null_eps = [gen_c.generate(dict(TRAIN_PARAMS), seed=s, split="null_control")
                for s in (131, 132, 133, 134)]
    tests.append(test_null_control(pol, null_eps, cfg))
    return tests


def test_step_counter_cheater_detected(gen_a, gen_c, cfg):
    tests = _full_tests(gen_a, gen_c, StepCounterCheaterPolicy(), cfg)
    cls = classify_cheating(tests)
    assert cls["suspected_cheating"]
    assert "episode_position" in cls["cheat_reasons"]


def test_absolute_price_cheater_detected(gen_a, gen_c, cfg):
    tests = _full_tests(gen_a, gen_c, AbsolutePriceCheaterPolicy(), cfg)
    cls = classify_cheating(tests)
    assert cls["suspected_cheating"]
    assert "absolute_price" in cls["cheat_reasons"]


def test_periodic_cheater_detected(gen_a, gen_c, cfg):
    tests = _full_tests(gen_a, gen_c, PeriodicCheaterPolicy(6), cfg)
    cls = classify_cheating(tests)
    assert cls["suspected_cheating"]
    assert "periodic_pattern" in cls["cheat_reasons"]


def test_future_leak_probe_detected(gen_a, gen_c, cfg):
    """观察字段审计 + 多切割点共同前缀必须发现未来泄漏。"""
    pol = FutureLeakProbePolicy(fee_threshold=cfg.fee)
    ep = gen_a.generate(TRAIN_PARAMS, seed=141)
    cp_fail = any(
        not test_common_prefix_future_suffix(
            gen_a, pol, ep, cfg, cut_ratio=cr).pass_
        for cr in (0.3, 0.5, 0.7)
    )
    assert cp_fail, "共同前缀测试必须发现 FutureLeakProbe"
    # Null 稳定正超额(无高换手)亦构成泄漏证据
    null_eps = [gen_c.generate(dict(TRAIN_PARAMS), seed=s, split="null_control")
                for s in (142, 143, 144, 145)]
    null_r = test_null_control(pol, null_eps, cfg)
    assert (not null_r.pass_) and (not null_r.extra["high_turnover"])


def test_null_overtrader_detected(gen_a, gen_c, cfg):
    """NullOvertrader:高换手 + 扣费亏损 + Null Control 挂科(非作弊高分)。"""
    pol = NullOvertraderPolicy()
    null_eps = [gen_c.generate(dict(TRAIN_PARAMS), seed=s, split="null_control")
                for s in (151, 152, 153, 154)]
    r = test_null_control(pol, null_eps, cfg)
    assert r.extra["high_turnover"] is True
    assert r.extra["excess_median"] < 0


def test_periodicity_detector():
    assert detect_periodicity([0, 1] * 20) == 2
    assert detect_periodicity([0, 0, 1, 0, 0, 1] * 5) == 3
    assert detect_periodicity([0, 1, 1, 0, 1, 0, 0, 1, 1, 1]) is None
    assert detect_periodicity([0] * 10) == 2  # 常数序列满足任意周期(由换手/成绩语义区分)
