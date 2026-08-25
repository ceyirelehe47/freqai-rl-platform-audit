"""工作包 G 测试(二):Trade 状态 heartbeat 重同步与未成交重复意图(任务书二十四节)。

订单成交状态的真值来源固定为 Freqtrade Trade 持久层(内存 SQLite +
真实 Trade 模型),信号生成经真实 RouteCStrategy._current_position_for_signals
(dp.runmode=DRY_RUN 分支)读取真实仓位。不连接真实账户、无 API Key。
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from rl_platform.inference import ScriptedPolicy
from rl_platform.signal_convert import targets_to_signals

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_1"
ROOT = ART.parents[1]
PAIR = "BTC/USDT"


def load_strategy():
    spec = importlib.util.spec_from_file_location(
        "route_c_strategy_resync_test",
        ROOT / "user_data" / "strategies" / "RouteCStrategy.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RouteCStrategy


@pytest.fixture()
def fresh_db():
    from freqtrade.persistence import Trade, init_db

    Trade.use_db = True  # Backtesting 会全局置 False,此处复位(测试隔离)
    init_db("sqlite://")
    Trade.session.rollback()
    for t in Trade.get_trades():
        Trade.session.delete(t)
    Trade.session.commit()
    yield
    Trade.session.rollback()


def make_strategy():
    from freqtrade.enums import RunMode

    strat = load_strategy()(config={"freqai": {"route_c": {"slippage_bps": 5.0}}})
    strat.dp = SimpleNamespace(runmode=RunMode.DRY_RUN)
    return strat


def set_trade(open_long: bool):
    """设置 Trade 表状态:open_long=True 时放置一个 open 多头,否则清空。"""
    from datetime import UTC, datetime, timedelta

    from freqtrade.persistence import Trade

    if open_long:
        t = Trade(pair=PAIR, stake_amount=100.0, amount=0.01, open_rate=10000.0,
                  open_date=datetime.now(UTC) - timedelta(hours=2),
                  fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
                  exchange="binanceus")
        Trade.session.add(t)
    Trade.session.commit()


def heartbeat_signals(strategy, model_target: int) -> dict:
    """模拟一个 heartbeat:模型给出最新目标 -> 信号生成(真实仓位起点)。"""
    df = pd.DataFrame({
        "&-target_position": [model_target],
        "do_predict": [1],
    })
    df = targets_to_signals(
        df, initial_position=strategy._current_position_for_signals({"pair": PAIR})
    )
    return {
        "target": model_target,
        "enter": int(df["enter_long"].iloc[-1]),
        "exit": int(df["exit_long"].iloc[-1]),
    }


# --------------------------------------------- 场景 1:入场未成交 -> 持续入场意图
def test_entry_unfilled_keeps_entering(fresh_db):
    strat = make_strategy()
    set_trade(open_long=False)  # Trade 表仍为空(订单未成交)
    seen = [heartbeat_signals(strat, 1) for _ in range(3)]
    assert all(s["enter"] == 1 for s in seen), seen
    assert all(s["exit"] == 0 for s in seen)


# --------------------------------------------- 场景 2:入场已成交 -> 不重复入场
def test_entry_filled_no_duplicate(fresh_db):
    strat = make_strategy()
    set_trade(open_long=True)  # Trade 出现 open long
    seen = [heartbeat_signals(strat, 1) for _ in range(3)]
    assert all(s["enter"] == 0 and s["exit"] == 0 for s in seen), seen


# --------------------------------------------- 场景 3:退出未成交 -> 持续退出意图
def test_exit_unfilled_keeps_exiting(fresh_db):
    strat = make_strategy()
    set_trade(open_long=True)  # 仍是 open long
    seen = [heartbeat_signals(strat, 0) for _ in range(3)]
    assert all(s["exit"] == 1 and s["enter"] == 0 for s in seen), seen


# --------------------------------------------- 场景 4:退出已完成 -> 不重复退出
def test_exit_completed_no_duplicate(fresh_db):
    strat = make_strategy()
    set_trade(open_long=False)  # Trade 表为空
    seen = [heartbeat_signals(strat, 0) for _ in range(3)]
    assert all(s["enter"] == 0 and s["exit"] == 0 for s in seen), seen


# --------------------------------------------- 真值源验证:预测历史不影响信号
def test_trade_table_is_source_of_truth(fresh_db):
    """内存中的目标历史不参与信号判定;即使上一 heartbeat 目标为 1,
    Trade 为空 + 目标 1 仍生成入场(未成交重复意图)。"""
    strat = make_strategy()
    set_trade(open_long=False)
    s1 = heartbeat_signals(strat, 1)
    assert s1["enter"] == 1
    # 三个 heartbeat 目标一直是 1,订单始终未成交
    s2 = heartbeat_signals(strat, 1)
    s3 = heartbeat_signals(strat, 1)
    assert s2["enter"] == 1 and s3["enter"] == 1


# --------------------------------------------- 策略读取的滑点配置(工作包 C 联动)
def test_strategy_slippage_from_config(fresh_db):
    strat = make_strategy()
    assert strat.route_c_slippage_bps == 5.0
    assert strat.custom_entry_price(PAIR, None, None, 100.0, None, "long") == \
        pytest.approx(100.0 * 1.0005)
    assert strat.custom_exit_price(PAIR, None, None, 100.0, 0.0, None) == \
        pytest.approx(100.0 * 0.9995)
    # 0 bps 时返回原始 proposed rate
    strat0 = load_strategy()(config={"freqai": {"route_c": {"slippage_bps": 0.0}}})
    strat0.dp = SimpleNamespace()
    assert strat0.custom_entry_price(PAIR, None, None, 100.0, None, "long") == 100.0
    assert strat0.custom_exit_price(PAIR, None, None, 100.0, 0.0, None) == 100.0


# --------------------------------------------- 逐 heartbeat trace 证据
def test_resync_trace_evidence(fresh_db):
    ART.mkdir(parents=True, exist_ok=True)
    strat = make_strategy()
    rows = []

    def beat(tag, trade_open, target):
        # 重置 Trade 表到目标状态
        from freqtrade.persistence import Trade

        Trade.get_trades_proxy(is_open=True)  # 触发 session
        for t in Trade.get_trades_proxy(is_open=True):
            Trade.session.delete(t)
        Trade.session.commit()
        set_trade(open_long=trade_open)
        s = heartbeat_signals(strat, target)
        rows.append({
            "beat": tag, "trade_open": int(trade_open), "model_target": target,
            "real_position": int(trade_open), **s,
        })

    beat("entry_unfilled_1", False, 1)
    beat("entry_unfilled_2", False, 1)
    beat("entry_filled", True, 1)
    beat("exit_unfilled_1", True, 0)
    beat("exit_unfilled_2", True, 0)
    beat("exit_completed", False, 0)
    pd.DataFrame(rows).to_csv(ART / "live_trade_resync_trace.csv", index=False)
    assert rows[0]["enter"] == 1 and rows[1]["enter"] == 1
    assert rows[2]["enter"] == 0 and rows[2]["exit"] == 0
    assert rows[3]["exit"] == 1 and rows[4]["exit"] == 1
    assert rows[5]["enter"] == 0 and rows[5]["exit"] == 0
