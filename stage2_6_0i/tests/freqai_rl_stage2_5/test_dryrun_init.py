"""Dry-run 状态初始化验证(任务书十三节第 4 条,测试级)。

不启动长期 Dry-run、不连接真实账户:用 freqtrade 真实持久层
(内存 sqlite + Trade.get_trades_proxy,与官方 BaseReinforcementLearningModel
.get_state_info 完全相同的读取接口)验证:
- 无 open trade -> 初始仓位 0;
- 已有 BTC/USDT 多头 open trade -> 初始仓位 1;
- 已平仓 trade 不影响;
- 出现空头持仓时报错而非静默。

生产路径 rl_platform.dryrun_state.get_initial_position_live 即调用同一接口。
"""

from datetime import UTC, datetime, timedelta

import pytest


def _make_open_trade(is_open: bool = True, is_short: bool = False, pair: str = "BTC/USDT"):
    from freqtrade.persistence import Trade

    return Trade(
        pair=pair,
        stake_amount=100.0,
        amount=0.001,
        open_rate=100000.0,
        open_date=datetime.now(UTC) - timedelta(hours=2),
        is_open=is_open,
        is_short=is_short,
        fee_open=0.001,
        fee_close=0.001,
        exchange="binanceus",
    )


@pytest.fixture()
def fresh_db():
    from freqtrade.persistence import init_db

    init_db("sqlite://")
    from freqtrade.persistence import Trade

    Trade.session.rollback()
    for t in Trade.get_trades():
        Trade.session.delete(t)
    Trade.session.commit()
    yield Trade
    Trade.session.rollback()


def _add_and_commit(Trade, trade):
    Trade.session.add(trade)
    Trade.session.commit()


def test_no_trades_position_zero(fresh_db):
    from rl_platform.dryrun_state import get_initial_position_live

    assert get_initial_position_live("BTC/USDT") == 0


def test_open_long_trade_position_one(fresh_db):
    from rl_platform.dryrun_state import get_initial_position_live, resolve_initial_position

    trade = _make_open_trade()
    fresh_db.session.add(trade)
    fresh_db.session.commit()

    trades = fresh_db.get_trades_proxy(is_open=True)
    assert resolve_initial_position(trades, "BTC/USDT") == 1
    assert get_initial_position_live("BTC/USDT") == 1


def test_closed_trade_does_not_count(fresh_db):
    from rl_platform.dryrun_state import resolve_initial_position

    trade = _make_open_trade(is_open=False)
    fresh_db.session.add(trade)
    fresh_db.session.commit()

    trades = fresh_db.get_trades_proxy(is_open=True)
    assert resolve_initial_position(trades, "BTC/USDT") == 0


def test_other_pair_does_not_count(fresh_db):
    from rl_platform.dryrun_state import resolve_initial_position

    trade = _make_open_trade(pair="ETH/USDT")
    fresh_db.session.add(trade)
    fresh_db.session.commit()

    trades = fresh_db.get_trades_proxy(is_open=True)
    assert resolve_initial_position(trades, "BTC/USDT") == 0


def test_short_position_raises(fresh_db):
    from rl_platform.dryrun_state import resolve_initial_position

    trade = _make_open_trade(is_short=True)
    fresh_db.session.add(trade)
    fresh_db.session.commit()

    trades = fresh_db.get_trades_proxy(is_open=True)
    with pytest.raises(RuntimeError):
        resolve_initial_position(trades, "BTC/USDT")
