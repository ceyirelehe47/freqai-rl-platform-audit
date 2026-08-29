"""工作包 A 单元测试:真实执行状态解析器(任务书四至六节)。

全部使用真实 Freqtrade Trade/Order 模型 + 内存 SQLite(不连接真实账户),
不使用自定义假数据类;订单状态变化通过构造真实 Order 状态表达
(集成级「官方订单更新路径」验证在工作包 C 的 FreqtradeBot 链路测试)。

覆盖场景(任务书六节清单):
- 无 Trade -> FLAT;
- 零成交、状态 open 的 entry order -> PENDING_ENTRY(模型观察 0);
- entry order 部分成交 -> PARTIAL_ENTRY(模型观察 1,不重复入场);
- entry order 全部成交(订单关闭,trade.amount>0)-> LONG;
- exit order 零成交 -> PENDING_EXIT(暴露保持,模型观察 1);
- exit order 部分成交 -> PARTIAL_EXIT(剩余暴露与订单一致);
- exit order 全部成交(trade 关闭)-> 不在 open 列表 -> FLAT;
- entry rejected / expired / cancelled(零成交)-> 订单非活动;
- exit rejected / cancelled;
- 进程重启后从数据库恢复(新建解析调用,无内存状态);
- 多个冲突活动订单 / 同 pair 多 open trade -> INCONSISTENT;
- 意外 short trade -> INCONSISTENT;
- amount/filled/remaining 互相矛盾 -> INCONSISTENT。
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rl_platform.execution_state import (
    FLAT,
    INCONSISTENT,
    LONG,
    PARTIAL_ENTRY,
    PARTIAL_EXIT,
    PENDING_ENTRY,
    PENDING_EXIT,
    get_live_execution_snapshot,
    get_model_position_live,
    resolve_execution_state,
)
from rl_platform.execution_state import InconsistentExecutionStateError

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2"
PAIR = "BTC/USDT"
AMOUNT = 0.01


@pytest.fixture()
def fresh_db():
    from freqtrade.persistence import Trade, init_db

    Trade.use_db = True
    init_db("sqlite://")
    Trade.session.rollback()
    for t in Trade.get_trades():
        Trade.session.delete(t)
    Trade.session.commit()
    yield Trade
    Trade.session.rollback()


def make_order(side: str, *, status: str = "open", filled: float = 0.0,
               amount: float = AMOUNT, order_id: str | None = None,
               is_open: bool | None = None, remaining: float | None = None,
               ft_is_open: bool = True):
    from freqtrade.persistence import Order

    if ft_is_open and status not in ("open",):
        ft_is_open = False
    return Order(
        ft_order_side=side, ft_pair=PAIR, ft_is_open=ft_is_open,
        ft_amount=amount, ft_price=10000.0,
        order_id=order_id or f"o_{side}_{status}_{filled}_{datetime.now(UTC).timestamp()}",
        symbol=PAIR, side=side, order_type="limit", status=status,
        price=10000.0, average=10000.0 if filled else None,
        amount=amount, filled=filled,
        remaining=(amount - filled) if remaining is None else remaining,
        cost=filled * 10000.0,
        order_date=datetime.now(UTC) - timedelta(minutes=10),
    )


def make_trade(amount: float = 0.0, is_short: bool = False, **kwargs):
    from freqtrade.persistence import Trade

    return Trade(
        pair=kwargs.pop("pair", PAIR), stake_amount=100.0, amount=amount,
        open_rate=10000.0, open_date=datetime.now(UTC) - timedelta(hours=2),
        fee_open=0.001, fee_close=0.001, is_open=True, is_short=is_short,
        exchange="binanceus", **kwargs,
    )


def add_and_commit(fresh_db, trade):
    fresh_db.session.add(trade)
    fresh_db.session.commit()
    return trade


# ---------------------------------------------------------------- 基础状态
def test_no_trades_is_flat(fresh_db):
    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == FLAT
    assert snap.model_position == 0
    assert not snap.has_open_orders


def test_zero_fill_open_entry_order_is_pending_entry(fresh_db):
    """零成交、状态 open 的入场限价单:Trade.is_open=True 但 amount=0。

    旧简化(is_open -> 1)会把它当成多头;新解析器必须给出
    PENDING_ENTRY,模型观察 0(无实际暴露)。"""
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=0.0))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == PENDING_ENTRY
    assert snap.model_position == 0
    assert snap.filled_amount == pytest.approx(0.0, abs=1e-12)
    assert len(snap.open_entry_orders) == 1
    assert snap.open_entry_orders[0].filled == 0.0


def test_entry_partially_filled_is_partial_entry(fresh_db):
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=AMOUNT * 0.4))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == PARTIAL_ENTRY
    assert snap.model_position == 1
    assert snap.filled_amount == pytest.approx(AMOUNT * 0.4)
    assert snap.open_entry_orders[0].remaining == pytest.approx(AMOUNT * 0.6)


def test_entry_fully_filled_is_long(fresh_db):
    """入场单全部成交:订单关闭(ft_is_open=False),trade.amount>0。"""
    t = make_trade(amount=AMOUNT)
    t.orders.append(make_order("buy", status="closed", filled=AMOUNT))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == LONG
    assert snap.model_position == 1
    assert not snap.has_open_orders


def test_exit_zero_fill_is_pending_exit(fresh_db):
    """退出挂单零成交:暴露保持(amount>0),模型观察 1。"""
    t = make_trade(amount=AMOUNT)
    t.orders.append(make_order("sell", filled=0.0))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == PENDING_EXIT
    assert snap.model_position == 1
    assert snap.filled_amount == pytest.approx(AMOUNT)


def test_exit_partially_filled_is_partial_exit(fresh_db):
    """退出单部分成交(仍 open):已卖出部分不计入暴露。"""
    t = make_trade(amount=AMOUNT)
    t.orders.append(make_order("sell", filled=AMOUNT * 0.3))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == PARTIAL_EXIT
    assert snap.model_position == 1
    assert snap.filled_amount == pytest.approx(AMOUNT * 0.7)


def test_exit_fully_filled_trade_closed_is_flat(fresh_db):
    from freqtrade.persistence import Trade

    t = make_trade(amount=AMOUNT)
    t.is_open = False
    t.close_date = datetime.now(UTC)
    add_and_commit(fresh_db, t)
    # is_open=False 的 trade 不进入 get_trades_proxy(is_open=True)
    open_trades = Trade.get_trades_proxy(is_open=True)
    snap = resolve_execution_state(open_trades, PAIR)
    assert snap.state == FLAT


# ------------------------------------------------------------ 异常终态订单
@pytest.mark.parametrize("status", ["rejected", "expired", "cancelled"])
def test_entry_terminal_zero_fill_recovers_flat(fresh_db, status):
    """entry 被 rejected/expired/cancelled 且零成交:订单非活动,
    trade 无暴露无挂单 -> FLAT(不留下虚假 LONG)。"""
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", status=status, filled=0.0))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == FLAT
    assert snap.model_position == 0
    assert not snap.has_open_orders


def test_cancelled_entry_with_partial_fill_keeps_exposure(fresh_db):
    """取消前已部分成交:实际暴露保留 -> LONG(无活动订单)。"""
    t = make_trade(amount=AMOUNT * 0.5)
    t.orders.append(make_order("buy", status="cancelled", filled=AMOUNT * 0.5))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == LONG
    assert snap.filled_amount == pytest.approx(AMOUNT * 0.5)


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_exit_terminal_orders(fresh_db, status):
    """exit 被拒/被取消(零成交):暴露仍在 -> LONG。"""
    t = make_trade(amount=AMOUNT)
    t.orders.append(make_order("sell", status=status, filled=0.0))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == LONG
    assert snap.model_position == 1


# ------------------------------------------------------------- 冲突与矛盾
def test_inconsistent_short_trade(fresh_db):
    t = make_trade(amount=AMOUNT, is_short=True)
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == INCONSISTENT
    assert snap.is_fail_closed
    assert snap.model_position is None
    assert "空头" in snap.diagnostics.get("short_trade", "")
    with pytest.raises(InconsistentExecutionStateError):
        get_model_position_live(PAIR)


def test_inconsistent_multiple_active_entry_orders(fresh_db):
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=0.0, order_id="dup1"))
    t.orders.append(make_order("buy", filled=0.0, order_id="dup2"))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == INCONSISTENT
    assert "multiple_active_orders" in snap.diagnostics


def test_inconsistent_entry_and_exit_orders_simultaneously(fresh_db):
    t = make_trade(amount=AMOUNT)
    t.orders.append(make_order("buy", filled=0.0, order_id="e1"))
    t.orders.append(make_order("sell", filled=0.0, order_id="x1"))
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == INCONSISTENT
    assert "entry_and_exit_orders" in snap.diagnostics


def test_inconsistent_amount_filled_remaining(fresh_db):
    """filled+remaining != amount:数据矛盾 -> INCONSISTENT。"""
    t = make_trade(amount=0.0)
    t.orders.append(make_order("buy", filled=AMOUNT * 0.5,
                               remaining=AMOUNT * 0.9))  # 0.5+0.9 != 0.01
    add_and_commit(fresh_db, t)

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == INCONSISTENT


def test_inconsistent_multiple_open_trades_same_pair(fresh_db):
    add_and_commit(fresh_db, make_trade(amount=AMOUNT))
    add_and_commit(fresh_db, make_trade(amount=AMOUNT))

    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == INCONSISTENT
    assert "multiple_open_trades" in snap.diagnostics


# ------------------------------------------------------------- 重启恢复
def test_restart_recovery_from_database(fresh_db):
    """进程重启 = 重新从数据库解析(无内存状态);五种状态逐一恢复一致。"""
    from freqtrade.persistence import Trade

    def snapshot():
        # 模拟新进程:每次重新读取代理列表
        return resolve_execution_state(Trade.get_trades_proxy(is_open=True), PAIR)

    states = []
    for setup in (
        lambda: None,  # FLAT
        lambda: _trade_with(fresh_db, [("buy", 0.0)]),  # PENDING_ENTRY
        lambda: _trade_with(fresh_db, [("buy", 0.004)]),  # PARTIAL_ENTRY
        lambda: _trade_with(fresh_db, [("sell", 0.0)], amount=AMOUNT),  # PENDING_EXIT
        lambda: _trade_with(fresh_db, [("sell", 0.004)], amount=AMOUNT),  # PARTIAL_EXIT
    ):
        Trade.session.rollback()
        for t in Trade.get_trades():
            Trade.session.delete(t)
        Trade.session.commit()
        setup()
        states.append(snapshot().state)
    assert states == [FLAT, PENDING_ENTRY, PARTIAL_ENTRY, PENDING_EXIT, PARTIAL_EXIT]


def _trade_with(fresh_db, orders, amount=0.0):
    t = make_trade(amount=amount)
    for spec in orders:
        side, filled = spec[0], spec[1]
        status = spec[2] if len(spec) > 2 else "open"
        t.orders.append(make_order(side, filled=filled, status=status))
    fresh_db.session.add(t)
    fresh_db.session.commit()
    return t


# ------------------------------------------------------------- 证据矩阵
def test_execution_state_matrix_evidence(fresh_db):
    """七态 × 事实矩阵证据 CSV(交付物 execution_state_matrix.md 的数据源)。"""
    import pandas as pd

    rows = []

    def record(name, setup, expected):
        from freqtrade.persistence import Trade

        Trade.session.rollback()
        for t in Trade.get_trades():
            Trade.session.delete(t)
        Trade.session.commit()
        setup()
        snap = get_live_execution_snapshot(PAIR)
        rows.append({
            "case": name, "state": snap.state, "expected": expected,
            "ok": snap.state == expected,
            "filled_amount": snap.filled_amount,
            "closed_amount": snap.closed_amount,
            "open_entry": len(snap.open_entry_orders),
            "open_exit": len(snap.open_exit_orders),
            "model_position": snap.model_position,
        })
        assert snap.state == expected, (name, snap.describe())

    record("no_trade", lambda: None, FLAT)
    record("entry_zero_fill", lambda: _trade_with(fresh_db, [("buy", 0.0)]), PENDING_ENTRY)
    record("entry_partial", lambda: _trade_with(fresh_db, [("buy", 0.004)]), PARTIAL_ENTRY)
    record("entry_filled", lambda: _trade_with(
        fresh_db, [("buy", 0.01, "closed")], amount=0.01), LONG)
    record("exit_zero_fill",
           lambda: _trade_with(fresh_db, [("sell", 0.0)], amount=AMOUNT), PENDING_EXIT)
    record("exit_partial",
           lambda: _trade_with(fresh_db, [("sell", 0.004)], amount=AMOUNT), PARTIAL_EXIT)
    record("entry_rejected", lambda: (_trade_with(fresh_db, [("buy", 0.0)]),
                                      _set_status(fresh_db, "rejected")), FLAT)
    record("multi_active_orders", lambda: _trade_with(
        fresh_db, [("buy", 0.0), ("buy", 0.0)]), INCONSISTENT)
    record("short_trade", lambda: add_and_commit(
        fresh_db, make_trade(amount=AMOUNT, is_short=True)), INCONSISTENT)

    ART.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(ART / "execution_state_trace.csv", index=False)


def _set_status(fresh_db, status):
    """把最后一个 trade 的订单置为终态(模拟 rejected/expired 到达)。"""
    from freqtrade.persistence import Trade

    t = Trade.get_trades_proxy(is_open=True)[0]
    o = t.orders[-1]
    o.status = status
    o.ft_is_open = False
    fresh_db.session.commit()
    return t
