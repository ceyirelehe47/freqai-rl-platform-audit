"""工作包 E 测试:base currency fee 的部分成交暴露(safe_amount_after_fee 口径)。

上游源码(trade_model.py):
    safe_amount_after_fee = safe_filled - safe_fee_base
recalc_trade_from_orders 累计已关闭订单使用 safe_amount_after_fee;
活动订单上的部分成交必须按同一口径累计,base 币手续费存在时
不得高估暴露。
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rl_platform.execution_state import (
    LONG,
    PARTIAL_ENTRY,
    PARTIAL_EXIT,
    PENDING_EXIT,
    resolve_execution_state,
)

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"
PAIR = "BTC/USDT"


def make_db():
    from freqtrade.persistence import Trade, init_db

    Trade.use_db = True
    init_db("sqlite://")
    Trade.session.rollback()
    for t in Trade.get_trades():
        Trade.session.delete(t)
    Trade.session.commit()
    return Trade


def make_order(side, *, filled, amount=0.01, ft_fee_base=None,
               status="open", ft_is_open=True):
    from freqtrade.persistence import Order

    return Order(
        ft_order_side=side, ft_pair=PAIR, ft_is_open=ft_is_open,
        ft_amount=amount, ft_price=10000.0, order_id=f"o_{side}_{filled}_{ft_fee_base}",
        symbol=PAIR, side=side, order_type="limit", status=status,
        price=10000.0, average=10000.0 if filled else None,
        amount=amount, filled=filled, remaining=amount - filled,
        cost=filled * 10000.0, ft_fee_base=ft_fee_base,
        order_date=datetime.now(UTC) - timedelta(minutes=5),
    )


def make_trade(amount=0.0):
    from freqtrade.persistence import Trade

    return Trade(
        pair=PAIR, stake_amount=100.0, amount=amount,
        open_rate=10000.0, open_date=datetime.now(UTC) - timedelta(hours=1),
        fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
        exchange="binanceus",
    )


def test_upstream_safe_amount_after_fee_semantics():
    """直查上游口径:Order.safe_amount_after_fee = filled - ft_fee_base。"""
    o = make_order("buy", filled=0.01, ft_fee_base=0.00005)
    assert o.safe_filled == pytest.approx(0.01)
    assert o.safe_fee_base == pytest.approx(0.00005)
    assert o.safe_amount_after_fee == pytest.approx(0.00995)


def test_partial_entry_with_base_fee_not_overstated():
    """活动 entry 单 filled=0.01 且 ft_fee_base=0.00005:
    实际暴露必须是 0.00995(不是 0.01),状态 PARTIAL_ENTRY。"""
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=0.01, ft_fee_base=0.00005))
    snap = resolve_execution_state([t], PAIR)
    assert snap.state == PARTIAL_ENTRY
    assert snap.filled_amount == pytest.approx(0.00995)
    assert snap.model_position == 1


def test_partial_entry_quote_fee_regression():
    """quote 手续费(ft_fee_base=None)场景数值不变:暴露 == filled。"""
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=0.01, ft_fee_base=None))
    snap = resolve_execution_state([t], PAIR)
    assert snap.state == PARTIAL_ENTRY
    assert snap.filled_amount == pytest.approx(0.01)


def test_exit_partial_base_fee_reduces_exposure():
    """活动 exit 单 filled=0.006 且 base fee 0.0001:
    暴露 = 0.02(trade.amount) - 0.0059 = 0.0141,状态 PARTIAL_EXIT。"""
    t = make_trade(amount=0.02)
    t.orders.append(make_order("sell", filled=0.006, ft_fee_base=0.0001))
    snap = resolve_execution_state([t], PAIR)
    assert snap.state == PARTIAL_EXIT
    assert snap.filled_amount == pytest.approx(0.02 - (0.006 - 0.0001))
    assert snap.model_position == 1


def test_consistent_with_upstream_recalc_for_closed_orders():
    """同一订单口径一致性:open 状态下我们的累计(filled - fee_base)
    == 上游 recalc_trade_from_orders 关闭订单后写入 trade.amount 的值。"""
    from freqtrade.persistence import Order, Trade, init_db

    Trade.use_db = True
    init_db("sqlite://")
    # 已关闭订单(filled 完成)带 base fee -> 上游 recalc
    t = make_trade(amount=0.0)
    o = make_order(
        "buy", filled=0.01, ft_fee_base=0.00005,
        status="closed", ft_is_open=False,
    )
    t.orders.append(o)
    t.recalc_trade_from_orders()
    assert t.amount == pytest.approx(0.00995)
    # 我们的解析在订单 open 时给出同样的费后累计
    t2 = make_trade(amount=0.0)
    o2 = make_order("buy", filled=0.01, ft_fee_base=0.00005)  # open 状态
    t2.orders.append(o2)
    snap = resolve_execution_state([t2], PAIR)
    assert snap.filled_amount == pytest.approx(t.amount)
    assert snap.open_entry_orders[0].filled_after_fee == pytest.approx(
        o.safe_amount_after_fee
    )
    Trade.session.rollback()


def test_base_fee_zero_filled_keeps_pending_entry():
    """零成交 + base fee 0(未收任何费):仍 PENDING_ENTRY,暴露 0。"""
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=0.0, ft_fee_base=0.0))
    snap = resolve_execution_state([t], PAIR)
    assert snap.state == "PENDING_ENTRY"
    assert snap.filled_amount == pytest.approx(0.0)


def test_base_fee_evidence():
    ART.mkdir(parents=True, exist_ok=True)
    cases = {}
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=0.01, ft_fee_base=0.00005))
    snap = resolve_execution_state([t], PAIR)
    cases["entry_partial_base_fee"] = {
        "filled": 0.01, "ft_fee_base": 0.00005,
        "filled_after_fee": 0.00995,
        "state": snap.state, "resolved_exposure": snap.filled_amount,
    }
    t2 = make_trade(amount=0.0)
    t2.orders.append(make_order("buy", filled=0.01, ft_fee_base=None))
    snap2 = resolve_execution_state([t2], PAIR)
    cases["entry_partial_quote_fee"] = {
        "filled": 0.01, "ft_fee_base": None,
        "resolved_exposure": snap2.filled_amount,
        "state": snap2.state,
    }
    (ART / "partial_fill_base_fee.json").write_text(
        json.dumps({
            "upstream_semantic":
                "Order.safe_amount_after_fee = safe_filled - safe_fee_base "
                "(trade_model.py:164-166);recalc_trade_from_orders 累计口径",
            "cases": cases,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
