"""纯账本单元测试(任务书十七节,13 项,全部手算对照)。

不启动 PPO、不启动 FreqAI,只测 LongFlatLedger。
手算基准(fee=f, 滑点 s bps):
- 买入: qty = cash / (p*(1+s/1e4)*(1+f));名义 = qty*exec;费用 = 名义*f
- 卖出: proceeds = qty*q*(1-s/1e4)*(1-f)
- 完整开平: 净值变化比 = q*(1-s/1e4)*(1-f) / (p*(1+s/1e4)*(1+f))
"""

import math

import pytest

from rl_platform.ledger import LongFlatLedger


def approx(a: float, b: float, tol: float = 1e-12) -> bool:
    return math.isclose(a, b, rel_tol=tol, abs_tol=tol)


# ---------------------------------------------------------------- 场景 1:全程空仓
def test_flat_all_the_way():
    led = LongFlatLedger(initial_cash=100.0, fee=0.001)
    for _ in range(10):
        rec = led.apply_target(0, raw_open=123.0)
        assert rec.direction == "hold"
        assert rec.fee_paid == 0.0
    assert led.cash == 100.0 and led.btc == 0.0
    assert approx(led.equity(50.0), 100.0)
    assert led.realized_pnl == 0.0


# ------------------------------------------------- 场景 2:买入后价格不变(只损失费用)
def test_buy_then_flat_price():
    led = LongFlatLedger(initial_cash=100.0, fee=0.001)
    rec = led.apply_target(1, raw_open=100.0)
    assert rec.direction == "buy"
    qty = 100.0 / (100.0 * 1.001)
    assert approx(rec.qty, qty)
    assert approx(rec.fee_paid, qty * 100.0 * 0.001)  # 费用按实际名义金额
    assert approx(led.equity(100.0), 100.0 / 1.001)   # 手算:cash/(1+f)
    # 未实现盈亏(现金口径,含预估卖出费):qty*p*(1-f) - cost_basis
    assert approx(led.unrealized_pnl(100.0), 100.0 * 0.999 / 1.001 - 100.0)


# ------------------------------------------------------------- 场景 3/4:买后涨/跌
def test_buy_then_rise_and_fall():
    for price_after, expect in ((110.0, None), (90.0, None)):
        led = LongFlatLedger(initial_cash=100.0, fee=0.001)
        led.apply_target(1, raw_open=100.0)
        qty = 100.0 / (100.0 * 1.001)
        assert approx(led.equity(price_after), qty * price_after)
        if price_after > 100.0:
            assert led.equity(price_after) > 100.0  # 上涨且足以覆盖费用
        else:
            assert led.equity(price_after) < 100.0


# ------------------------------------------------- 场景 5:买入后卖出(完整开平手算)
@pytest.mark.parametrize("p,q,fee", [
    (100.0, 100.0, 0.001),   # 同价开平:损失 2f/(1+f)
    (100.0, 110.0, 0.001),   # 盈利单
    (100.0, 90.0, 0.001),    # 亏损单
    (100.0, 100.0, 0.0),     # 零费同价:净值不变
])
def test_buy_then_sell_hand_calculated(p, q, fee):
    led = LongFlatLedger(initial_cash=100.0, fee=fee)
    rec_b = led.apply_target(1, raw_open=p)
    rec_s = led.apply_target(0, raw_open=q)
    assert rec_s.direction == "sell"
    qty = 100.0 / (p * (1 + fee))
    proceeds = qty * q * (1 - fee)
    assert approx(led.cash, proceeds)
    assert approx(rec_s.fee_paid, qty * q * fee)
    # 手算:单笔净值变化比 = q*(1-f)/(p*(1+f))
    assert approx(led.cash / 100.0, q * (1 - fee) / (p * (1 + fee)))
    assert approx(led.realized_pnl, proceeds - 100.0)
    assert led.btc == 0.0


# ------------------------------------------------------- 场景 6/7:重复目标不交易
def test_repeated_targets_no_trade():
    led = LongFlatLedger(initial_cash=100.0, fee=0.001)
    led.apply_target(1, raw_open=100.0)
    qty_after_buy = led.btc
    for _ in range(5):
        rec = led.apply_target(1, raw_open=105.0)  # 重复多头
        assert rec.direction == "hold"
        assert rec.fee_paid == 0.0
        assert rec.qty == 0.0
    assert led.btc == qty_after_buy
    led.apply_target(0, raw_open=110.0)
    cash_after_sell = led.cash
    for _ in range(5):
        rec = led.apply_target(0, raw_open=95.0)  # 重复空仓
        assert rec.direction == "hold"
        assert rec.fee_paid == 0.0
    assert led.cash == cash_after_sell


# ------------------------------------------------------------- 场景 8:频繁切换
def test_frequent_flips():
    led = LongFlatLedger(initial_cash=100.0, fee=0.001)
    equity = 100.0
    n_trades = 8
    for i in range(n_trades):
        p = 100.0 + (1.0 if i % 2 == 0 else -1.0)
        rec_b = led.apply_target(1, raw_open=p)
        rec_s = led.apply_target(0, raw_open=p)
        assert rec_b.direction == "buy" and rec_s.direction == "sell"
        equity *= (1 - 0.001) / (1 + 0.001)  # 同价开平每轮手算损失
    assert approx(led.cash, equity)
    assert led.total_fees_paid > 0
    assert approx(led.cash, 100.0 * ((1 - 0.001) / (1 + 0.001)) ** n_trades)


# ------------------------------------------------------- 场景 9/10:零费与 0.001
def test_fee_zero_vs_one_thousandth():
    led0 = LongFlatLedger(initial_cash=100.0, fee=0.0)
    led1 = LongFlatLedger(initial_cash=100.0, fee=0.001)
    for led in (led0, led1):
        led.apply_target(1, raw_open=100.0)
        led.apply_target(0, raw_open=100.0)
    assert approx(led0.cash, 100.0)
    assert approx(led1.cash, 100.0 * (1 - 0.001) / (1 + 0.001))
    assert led1.cash < led0.cash  # 费用提高净值不能提高


# --------------------------------------------------- 场景 11:滑点 0/5/10 bps
@pytest.mark.parametrize("bps", [0.0, 5.0, 10.0])
def test_slippage_hand_calculated(bps):
    led = LongFlatLedger(initial_cash=100.0, fee=0.001, slippage_bps=bps)
    rec_b = led.apply_target(1, raw_open=100.0)
    exec_buy = 100.0 * (1 + bps / 10000.0)
    qty = 100.0 / (exec_buy * 1.001)
    assert approx(rec_b.exec_price, exec_buy)
    assert approx(rec_b.qty, qty)
    assert approx(rec_b.slippage_cost, qty * (exec_buy - 100.0))
    rec_s = led.apply_target(0, raw_open=100.0)
    exec_sell = 100.0 * (1 - bps / 10000.0)
    assert approx(rec_s.exec_price, exec_sell)
    assert approx(led.cash, qty * exec_sell * (1 - 0.001))


def test_slippage_monotonicity_ledger():
    finals = []
    for bps in (0.0, 5.0, 10.0):
        led = LongFlatLedger(initial_cash=100.0, fee=0.001, slippage_bps=bps)
        for p in (100.0, 110.0, 90.0, 105.0):
            led.apply_target(1, raw_open=p)
            led.apply_target(0, raw_open=p)
        finals.append(led.cash)
    assert finals[0] > finals[1] > finals[2]  # 滑点增加净值单调下降


# ------------------------------------------- 场景 12:Episode 结束仍持多头(清算)
def test_liquidation_at_end():
    # 阶段 2.5.2a 更新(旧断言 exec==120/slippage_cost==0 编码了
    # 「持有到 Episode 结束可以免滑点退出」的奖励漏洞,已废除):
    # 终端清算与普通市场卖出使用完全相同的 simulated_slippage_bps、
    # tick 取整与卖出手续费——更严格的因果成本断言。
    led = LongFlatLedger(initial_cash=100.0, fee=0.001, slippage_bps=5.0)
    rec_b = led.apply_target(1, raw_open=100.0)
    rec_l = led.liquidate(120.0)
    assert rec_l.direction == "liquidate"
    exec_sell = 120.0 * (1.0 - 5.0 / 10000.0)  # floor_to_tick(tick=0 不量化)
    assert approx(rec_l.exec_price, exec_sell)
    assert rec_l.slippage_cost > 0.0  # 终端退出必须支付滑点(无免费退出)
    assert rec_l.fee_paid > 0.0
    assert approx(led.cash, rec_b.qty * exec_sell * (1 - 0.001))
    assert led.btc == 0.0
    # 最终净值 = 现金 + 全部持仓净清算价值(此处持仓已清零)
    assert approx(led.equity(999.0), led.cash)
    assert approx(led.realized_pnl, led.cash - 100.0)
    # 与普通卖出同成本:同一基准价下 liquidate 与 _sell_all 同价同费
    led2 = LongFlatLedger(initial_cash=100.0, fee=0.001, slippage_bps=5.0)
    led2.apply_target(1, raw_open=100.0)
    rec_s = led2._sell_all(120.0)
    assert approx(rec_l.exec_price, rec_s.exec_price)
    assert approx(rec_l.fee_paid, rec_s.fee_paid)


# ------------------------------------------------- 场景 13:reset 后状态完全清空
def test_reset_clears_everything():
    led = LongFlatLedger(initial_cash=100.0, fee=0.001, slippage_bps=5.0)
    led.apply_target(1, raw_open=100.0)
    led.liquidate(120.0)
    assert led.realized_pnl != 0.0 or led.total_fees_paid != 0.0
    led.reset()
    fresh = LongFlatLedger(initial_cash=100.0, fee=0.001, slippage_bps=5.0)
    assert led.cash == fresh.cash == 100.0
    assert led.btc == fresh.btc == 0.0
    assert led.cost_basis == 0.0
    assert led.realized_pnl == 0.0
    assert led.total_fees_paid == 0.0
    assert led.total_slippage_cost == 0.0


# --------------------------------------------------------- 非法目标仓位必须报错
def test_invalid_target_raises():
    led = LongFlatLedger(initial_cash=100.0, fee=0.001)
    with pytest.raises(ValueError):
        led.apply_target(2, raw_open=100.0)
    with pytest.raises(ValueError):
        led.apply_target(-1, raw_open=100.0)
