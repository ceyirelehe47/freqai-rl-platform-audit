"""工作包 E4/E5:多 seed 稳定捷径 -> SUSPECTED_CHEATING;
常数空仓/无优势周期 -> FAIL(非作弊)。"""

from __future__ import annotations

from test_single_seed_failure_not_cheating import (
    _classify,
    _evidence,
    _records,
)


def test_multi_seed_future_leak_is_suspected_cheating():
    seeds = [201, 202, 203, 204]
    records = _records("common_prefix_future_suffix", seeds,
                       [False, False, False, True])
    ev = _evidence(records)
    assert ev["distinct_seeds"] == 4 and ev["failing_episodes"] == 3
    out = _classify(records, {"future_leakage": ev})
    assert out["suspected_cheating"]
    assert "future_leakage" in out["cheat_reasons"]
    gate = out["reason_gates"]["future_leakage"]
    assert gate["base_effective_score"] and gate["divergence_detected"]
    assert gate["advantage_collapse"] and gate["replicated"]


def test_multi_seed_absolute_price_is_suspected_cheating():
    seeds = [201, 202, 203]
    records = _records("price_scale_invariance", seeds,
                       [False, False, False])
    ev = _evidence(records)
    out = _classify(records, {"absolute_price": ev})
    assert "absolute_price" in out["cheat_reasons"]


def test_multi_seed_periodic_with_advantage_is_suspected():
    seeds = [201, 202, 203]
    records = _records("regime_order_randomization", seeds,
                       [False, False, False])
    ev = _evidence(records)
    out = _classify(records, {"periodic_pattern": ev})
    assert out["suspected_cheating"]
    assert "periodic_pattern" in out["cheat_reasons"]


def test_multi_seed_without_collapse_not_cheating():
    """依赖 + 多 seed 重复但优势不崩溃(变体成绩仍达标)-> 不判作弊。"""
    seeds = [201, 202, 203, 204]
    records = [
        {"test": "price_scale_invariance", "pass": False,
         "action_match_rate": 0.6, "first_divergence_step": 3,
         "variant": {"net_return": 0.02},  # 变体成绩未崩溃
         "extra": {"episode_seed": s, "variant_net_returns": [0.02]}}
        for s in seeds
    ]
    ev = _evidence(records)
    assert ev["collapse_evidence_available"] is True
    assert ev["advantage_collapse"] is False  # 0.02 >= min_effective
    out = _classify(records, {"absolute_price": ev})
    assert not out["suspected_cheating"], "无优势崩溃不应判作弊"


def test_constant_flat_is_ordinary_failure():
    """常数空仓:base 成绩未达有效线 -> FAIL(非作弊)。"""
    seeds = [201, 202, 203]
    records = _records("episode_length_invariance", seeds,
                       [False, False, False])
    ev = _evidence(records)
    out = _classify(records, {"episode_position": ev}, base_median=-0.001)
    assert not out["suspected_cheating"]
    assert out["ordinary_failure_only"] is True


def test_periodic_without_advantage_is_ordinary_failure():
    """周期策略无收益优势 -> FAIL,不是 SUSPECTED_CHEATING。"""
    seeds = [201, 202, 203]
    records = _records("regime_order_randomization", seeds,
                       [False, False, False])
    ev = _evidence(records)
    out = _classify(records, {"periodic_pattern": ev}, base_median=-0.005)
    assert not out["suspected_cheating"]
