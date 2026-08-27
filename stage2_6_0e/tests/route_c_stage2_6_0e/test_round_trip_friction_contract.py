"""工作包 A(A1-A4):按冻结账本重新推导的 economic margin 合同测试。

覆盖任务书 A4 的 12 类场景:多种 fee/slippage/tick 组合、真实
LongFlatLedger 平价往返(市场卖出与终端清算两条路径)、margin 不大于
真实摩擦、旧错误公式被明确区分、spec hash 随经济参数变化、metric
单位改换使旧承诺失效。
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from rl_curriculum.null_friction import (
    LEDGER_ROUND_TRIP_FORMULA,
    actual_round_trip_friction,
    friction_contract_code_hash,
    friction_parity_problems,
    friction_parity_report,
    ledger_round_trip_friction,
    ledger_round_trip_retention,
)
from rl_curriculum.null_qualification_spec import (
    build_spec_payload,
    null_qualification_spec_hash,
    round_trip_friction,
    verify_spec_payload,
)


def test_fee_only_slippage_zero_exact_value():
    """A4-1:fee=0.001、slippage=0、tick=0 -> 0.002/1.001(不是 0.001999)。"""
    f = ledger_round_trip_friction(0.001, 0.0)
    assert abs(f - 0.002 / 1.001) < 1e-15
    assert abs(f - 0.001998001998001998) < 1e-15
    # 与旧公式明确区分
    assert abs(f - (1 - (1 - 0.001) ** 2)) > 1e-9


def test_slippage_only_fee_zero():
    """A4-2:fee=0、slippage>0 -> 1-(1-s)/(1+s)。"""
    for s in (0.0005, 0.001, 0.005):
        f = ledger_round_trip_friction(0.0, s)
        assert abs(f - (1 - (1 - s) / (1 + s))) < 1e-15


def test_fee_and_slippage_both_positive():
    """A4-3:fee>0、slippage>0 的乘法组合。"""
    f = 0.001
    s = 0.0007
    expected = 1 - ((1 - f) / (1 + f)) * ((1 - s) / (1 + s))
    assert abs(ledger_round_trip_friction(f, s) - expected) < 1e-15
    # 单调性:费用/滑点只增摩擦
    assert ledger_round_trip_friction(0.002, s) > ledger_round_trip_friction(
        f, s)
    assert ledger_round_trip_friction(f, 0.0009) > ledger_round_trip_friction(
        f, s)


@pytest.mark.parametrize("price", [0.37, 1.0, 4.25, 100.0, 3600.5, 100000.0])
def test_multiple_reference_prices_parity(price):
    """A4-4:多组 reference price 下真实账本往返与 closed-form 一致
    (tick=0,两条退出路径;margin 不大于真实摩擦)。"""
    for fee in (0.0, 0.0005, 0.001, 0.0025):
        for slip in (0.0, 0.0005, 0.001):
            closed = ledger_round_trip_friction(fee, slip)
            for exit_ in ("market", "liquidate"):
                actual = actual_round_trip_friction(
                    fee=fee, slippage_bps=slip * 1e4, price_tick=0.0,
                    reference_price=price, exit=exit_)
                assert abs(actual - closed) <= 1e-12
                assert actual >= closed - 1e-12


@pytest.mark.parametrize("tick", [0.0, 0.00001, 0.01, 0.1, 1.0, 25.0])
def test_multiple_price_ticks_conservative_lower_bound(tick):
    """A4-5/A3:多组 price_tick 下,真实执行摩擦 >= closed-form(买 ceil/
    卖 floor 方向不利取整的保守下界性质,由真实 execution 函数实证;
    价格低于一个 tick 的不可采纳组合按预注册规则跳过)。"""
    for price in (1.0, 100.0, 3600.5):
        for fee in (0.0, 0.001, 0.01):
            for slip in (0.0, 0.001, 0.005):
                if price * (1 - slip) < tick or price < tick:
                    continue  # 不可采纳(卖出有效价会被取整为 0)
                closed = ledger_round_trip_friction(fee, slip)
                for exit_ in ("market", "liquidate"):
                    actual = actual_round_trip_friction(
                        fee=fee, slippage_bps=slip * 1e4, price_tick=tick,
                        reference_price=price, exit=exit_)
                    assert actual >= closed - 1e-12


def test_buy_ceil_sell_floor_directionality():
    """A4-6:买入 ceil、卖出 floor 的方向不利取整只恶化成交价
    (market_fill 诊断核对:actual_effective_slippage >= 请求滑点)。"""
    from rl_platform.market_execution import buy_market_price, sell_market_price

    for tick in (0.01, 0.1, 1.0):
        bp, dbuys = buy_market_price(100.0, 10.0, tick)
        sp, dsell = sell_market_price(100.0, 10.0, tick)
        assert bp >= 100.0 * 1.001 - 1e-12
        assert sp <= 100.0 * 0.999 + 1e-12
        assert dbuys["actual_effective_slippage_bps"] >= 10.0 - 1e-9
        assert dsell["actual_effective_slippage_bps"] >= 10.0 - 1e-9


def test_real_longflat_ledger_flat_price_round_trip():
    """A4-7:真实 LongFlatLedger 平价往返(同 raw price 买入再卖出)
    的现金保留比例 == closed-form retention。"""
    from rl_platform.ledger import LongFlatLedger

    for fee in (0.0, 0.0005, 0.001, 0.0025, 0.01):
        for slip_bps in (0.0, 5.0, 10.0):
            led = LongFlatLedger(initial_cash=100.0, fee=fee,
                                 slippage_bps=slip_bps, price_tick=0.0)
            led.apply_target(1, 50.0)
            rec_buy = led._hold_record(50.0)  # noqa: SLF001 - 触发无害
            del rec_buy
            led.apply_target(0, 50.0)
            expected = ledger_round_trip_retention(fee, slip_bps / 1e4)
            assert abs(led.cash / 100.0 - expected) <= 1e-12


def test_terminal_liquidation_path_same_friction():
    """A4-8:终端清算路径(liquidate)与普通卖出承担相同摩擦。"""
    from rl_platform.ledger import LongFlatLedger

    for fee in (0.0005, 0.001, 0.01):
        for slip_bps in (0.0, 10.0, 50.0):
            led = LongFlatLedger(initial_cash=250.0, fee=fee,
                                 slippage_bps=slip_bps, price_tick=0.0)
            led.apply_target(1, 125.0)
            led.liquidate(125.0)
            expected = ledger_round_trip_retention(fee, slip_bps / 1e4)
            assert abs(led.cash / 250.0 - expected) <= 1e-12


def test_qualification_margin_not_greater_than_real_friction(cfg):
    """A4-9:qualification margin(spec 来源)不大于真实完整往返摩擦
    (构造上相等;tick>0 时真实摩擦更大)。"""
    margin = round_trip_friction(cfg)
    for tick in (0.0, 0.01, 1.0):
        actual = actual_round_trip_friction(
            fee=cfg.fee, slippage_bps=cfg.slippage_bps, price_tick=tick,
            reference_price=100.0)
        assert margin <= actual + 1e-12


def test_legacy_wrong_formula_distinguished():
    """A4-10:旧错误公式(0.001999)与冻结账本公式(0.001998002...)
    在数值、公式字符串、spec 校验三个层面都被明确区分。"""
    correct = ledger_round_trip_friction(0.001, 0.0)
    legacy = 1 - (1 - 0.001) ** 2
    assert abs(correct - legacy) > 1e-9
    assert LEDGER_ROUND_TRIP_FORMULA != "1 - (1 - fee)^2 * (1 - slippage)^2"
    assert "1 + fee" in LEDGER_ROUND_TRIP_FORMULA
    report = friction_parity_report()
    assert abs(report["example_fee_0p001_slip_0"] - correct) < 1e-15
    assert abs(report["legacy_wrong_formula_value"] - legacy) < 1e-15


def test_spec_hash_changes_with_economic_parameters(cfg):
    """A4-11:修改 fee/slippage/tick 后 spec hash 变化(margin 只能来自
    规范,经济参数变化 -> 旧承诺失效)。"""
    from rl_curriculum.evaluator import EvalConfig

    base = build_spec_payload(cfg, timeframe="15m", episode_bars=96)
    h = null_qualification_spec_hash(base)
    for mutated_cfg in (
        EvalConfig(fee=0.0005, slippage_bps=0.0, price_tick=0.0),
        EvalConfig(fee=0.001, slippage_bps=5.0, price_tick=0.0),
        EvalConfig(fee=0.001, slippage_bps=0.0, price_tick=0.01),
    ):
        spec2 = build_spec_payload(
            mutated_cfg, timeframe="15m", episode_bars=96)
        assert null_qualification_spec_hash(spec2) != h
        assert verify_spec_payload(spec2) == []


def test_metric_unit_change_invalidates_old_commitment(cfg):
    """A4-12:metric 单位从 simple return 改为 log return(或改公式/
    单位字段)时旧承诺失效(verify 拒绝;hash 变化)。"""
    base = build_spec_payload(cfg, timeframe="15m", episode_bars=96)
    h = null_qualification_spec_hash(base)
    tampered = copy.deepcopy(base)
    tampered["margin_derivation"]["units"] = "log_return"
    assert null_qualification_spec_hash(tampered) != h
    problems = verify_spec_payload(tampered)
    assert any("simple_return" in p for p in problems)
    tampered2 = copy.deepcopy(base)
    tampered2["margin_derivation"]["formula"] = \
        "1 - (1 - fee)^2 * (1 - slippage)^2"
    problems2 = verify_spec_payload(tampered2)
    assert any("旧错误公式" in p or "冻结账本公式" in p
               for p in problems2)


def test_parity_grid_full_report_passes():
    """A3:预注册 parity 网格(真实执行函数)全过——不得只写注释。"""
    assert friction_parity_problems() == []
    report = friction_parity_report()
    assert report["pass"] is True
    assert report["n_round_trips"] >= 1000
    assert report["n_combinations"] >= 300


def test_friction_contract_hash_binds_implementation():
    """A2:摩擦合同哈希进入 spec(nfc-);实现变化 -> spec hash 变化。"""
    h = friction_contract_code_hash()
    assert h.startswith("nfc-")
    spec = build_spec_payload(
        __import__("rl_curriculum.mock_sealed_exam", fromlist=["x"]
                   ).default_eval_config(),
        timeframe="15m", episode_bars=96)
    assert spec["margin_derivation"]["friction_contract_hash"] == h
    tampered = copy.deepcopy(spec)
    tampered["margin_derivation"]["friction_contract_hash"] = "nfc-forged"
    assert any("摩擦合同" in p for p in verify_spec_payload(tampered))


def test_retention_units_simple_return(cfg):
    """A1:margin 与 EpisodeResult.net_return 同为 simple-return 单位
    (retention = final_cash/initial_cash;friction = 1 - retention)。"""
    from rl_platform.ledger import LongFlatLedger

    led = LongFlatLedger(initial_cash=cfg.initial_cash, fee=cfg.fee,
                         slippage_bps=cfg.slippage_bps,
                         price_tick=cfg.price_tick)
    led.apply_target(1, 100.0)
    led.apply_target(0, 100.0)
    net_return = led.cash / cfg.initial_cash - 1.0  # EpisodeResult 口径
    assert abs(net_return + round_trip_friction(cfg)) < 1e-12
    assert abs(net_return - (ledger_round_trip_retention(
        cfg.fee, cfg.slippage_bps / 1e4) - 1.0)) < 1e-12


def test_negative_fee_rejected():
    """friction 合同对非法输入 fail closed。"""
    with pytest.raises(ValueError):
        ledger_round_trip_friction(-0.001, 0.0)
    with pytest.raises(ValueError):
        ledger_round_trip_friction(0.001, -0.01)


def test_random_grid_property_monotone_friction():
    """随机大规模属性测试:任意合法参数下 actual >= closed(真实执行)。"""
    rng = np.random.default_rng(20260827)
    for _ in range(120):
        fee = float(rng.uniform(0.0, 0.01))
        slip = float(rng.uniform(0.0, 0.004))
        price = float(10.0 ** rng.uniform(-2, 5))
        tick = float(rng.choice([0.0, 1e-5, 0.01, 0.5, 10.0]))
        if price < tick or price * (1 - slip) < tick:
            continue  # 不可采纳组合(价格低于一个 tick)
        closed = ledger_round_trip_friction(fee, slip)
        for exit_ in ("market", "liquidate"):
            actual = actual_round_trip_friction(
                fee=fee, slippage_bps=slip * 1e4, price_tick=tick,
                reference_price=price, exit=exit_)
            assert actual >= closed - 1e-12
