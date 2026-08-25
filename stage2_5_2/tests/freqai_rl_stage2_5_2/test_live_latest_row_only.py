"""工作包 B 单元测试:Live 模式只处理最新一行(任务书七至九节)。

验证点:
- 历史行(含 FreqAI 首次传入的整段回填)一律 enter=exit=0;
- 只有最新一行按 [执行状态 + 最新目标 + 最新 do_predict + 活动订单] 生成意图;
- 八节信号规则全矩阵(无订单/同方向挂单/目标反转/do_predict 无效);
- populate_entry_trend 与 populate_exit_trend 任意顺序重复调用幂等,
  不残留上一 heartbeat 信号;
- backtest 与 live 走不同实现(backtest 仍整段顺序扫描)。
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from rl_platform.execution_state import (
    FLAT,
    INCONSISTENT,
    LONG,
    PARTIAL_ENTRY,
    PARTIAL_EXIT,
    PENDING_ENTRY,
    PENDING_EXIT,
)
from rl_platform.signal_convert import latest_row_signals, targets_to_signals

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2"
ROOT = ART.parents[1]
PAIR = "BTC/USDT"


def load_strategy():
    spec = importlib.util.spec_from_file_location(
        "route_c_strategy_latest_row_test",
        ROOT / "user_data" / "strategies" / "RouteCStrategy.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RouteCStrategy


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


def make_strategy(runmode=None):
    from freqtrade.enums import RunMode

    if runmode is None:
        runmode = RunMode.DRY_RUN
    strat = load_strategy()(config={"freqai": {"route_c": {"slippage_bps": 5.0}}})
    strat.dp = SimpleNamespace(runmode=runmode)
    return strat


def history_df(target_history: list[int], latest_target: int,
               latest_dp: int = 1, n_hist: int = 99) -> pd.DataFrame:
    """历史目标任意变化(模拟回填),最新一行为当前目标。"""
    hist = list(target_history) + [latest_target]
    while len(hist) < n_hist + 1:  # n_hist 行历史 + 1 行最新
        hist.insert(0, 0)
    return pd.DataFrame({
        "&-target_position": hist,
        "do_predict": [1] * (len(hist) - 1) + [latest_dp],
    })


def sig(df: pd.DataFrame, strategy, pair=PAIR) -> dict:
    out = strategy.populate_entry_trend(df.copy(), {"pair": pair})
    return {
        "enter_hist": int(out["enter_long"].iloc[:-1].sum()),
        "enter_last": int(out["enter_long"].iloc[-1]),
        "exit_hist": int(out["exit_long"].iloc[:-1].sum()),
        "exit_last": int(out["exit_long"].iloc[-1]),
    }


# ------------------------------------------------- 七节:历史行不得产生信号
def test_history_rows_never_signal(fresh_db):
    """100 行历史,历史段目标 0/1 交替(模拟重放),最新目标 1,真实状态 FLAT:
    前 99 行不得有任何 entry/exit,最新行有且只有一个 entry。"""
    strat = make_strategy()
    df = history_df([0, 1, 0, 1] * 20, latest_target=1)
    assert len(df) == 100
    s = sig(df, strat)
    assert s["enter_hist"] == 0 and s["exit_hist"] == 0, s
    assert s["enter_last"] == 1 and s["exit_last"] == 0


def test_history_targets_are_display_only(fresh_db):
    """历史目标只用于展示:无论历史段如何变化,信号只由最新行决定。"""
    strat = make_strategy()
    for hist in ([1] * 50, [0, 1] * 25, [0] * 50):
        df = history_df(hist, latest_target=0)
        s = sig(df, strat)
        assert s == {"enter_hist": 0, "enter_last": 0, "exit_hist": 0, "exit_last": 0}, (hist, s)


# ---------------------------------------------------------- 八节:信号规则
RULES = [
    # (state, target, dp, expect_enter, expect_exit)
    (FLAT, 0, 1, 0, 0),          # FLAT + 0 -> HOLD
    (FLAT, 1, 1, 1, 0),          # FLAT + 1 -> ENTER
    (LONG, 1, 1, 0, 0),          # LONG + 1 -> HOLD
    (LONG, 0, 1, 0, 1),          # LONG + 0 -> EXIT
    (PENDING_ENTRY, 1, 1, 0, 0),   # 同方向挂单 -> 不重复 entry
    (PARTIAL_ENTRY, 1, 1, 0, 0),
    (PENDING_EXIT, 0, 1, 0, 0),    # 同方向挂单 -> 不重复 exit
    (PARTIAL_EXIT, 0, 1, 0, 0),
    (PENDING_ENTRY, 0, 1, 0, 0),   # 反转:请求取消,本 heartbeat 无 exit/无单
    (PARTIAL_ENTRY, 0, 1, 0, 0),
    (PENDING_EXIT, 1, 1, 0, 0),    # 反转:请求取消,本 heartbeat 无 entry
    (PARTIAL_EXIT, 1, 1, 0, 0),
    (FLAT, 1, 0, 0, 0),          # do_predict != 1 -> 无新订单
    (LONG, 0, 0, 0, 0),
    (PENDING_ENTRY, 0, 0, 0, 0),   # 无效预测不触发目标反转取消
    (PENDING_EXIT, 1, 0, 0, 0),
    (INCONSISTENT, 1, 1, 0, 0),    # fail closed
    (INCONSISTENT, 0, 1, 0, 0),
]


@pytest.mark.parametrize("state,target,dp,exp_enter,exp_exit", RULES)
def test_signal_rule_matrix(state, target, dp, exp_enter, exp_exit):
    df = pd.DataFrame({"&-target_position": [target], "do_predict": [dp]})
    df, intent = latest_row_signals(df, state, target, dp)
    assert int(df["enter_long"].iloc[-1]) == exp_enter
    assert int(df["exit_long"].iloc[-1]) == exp_exit


def test_signal_rule_intents():
    """意图字符串与规则一一对应(供 trace 证据与日志核对)。"""
    def intent_of(state, target, dp=1):
        df = pd.DataFrame({"&-target_position": [target], "do_predict": [dp]})
        return latest_row_signals(df, state, target, dp)[1]

    assert intent_of(FLAT, 1) == "enter"
    assert intent_of(FLAT, 0) == "hold"
    assert intent_of(LONG, 0) == "exit"
    assert intent_of(LONG, 1) == "hold"
    assert intent_of(PENDING_ENTRY, 1) == "hold_pending_entry"
    assert intent_of(PENDING_ENTRY, 0) == "cancel_request_entry"
    assert intent_of(PARTIAL_ENTRY, 0) == "cancel_request_entry"
    assert intent_of(PENDING_EXIT, 0) == "hold_pending_exit"
    assert intent_of(PENDING_EXIT, 1) == "cancel_request_exit"
    assert intent_of(PARTIAL_EXIT, 1) == "cancel_request_exit"
    assert intent_of(FLAT, 1, dp=0) == "no_signal_invalid_prediction"
    assert intent_of(INCONSISTENT, 1) == "fail_closed_inconsistent"


# ---------------------------------------------------------- 九节:幂等性
def test_populate_idempotent_any_order(fresh_db):
    """populate_entry/exit 任意顺序、重复调用结果一致;上一 heartbeat
    残留信号(在传入 df 上预置)被清零。"""
    strat = make_strategy()
    df = history_df([1] * 20, latest_target=1)
    # 预置上一 heartbeat 的残留信号(历史行)
    df["enter_long"] = 1
    df["exit_long"] = 1
    df["enter_tag"] = "stale"

    a = strat.populate_entry_trend(df.copy(), {"pair": PAIR})
    b = strat.populate_exit_trend(a.copy(), {"pair": PAIR})
    c = strat.populate_exit_trend(df.copy(), {"pair": PAIR})
    d = strat.populate_entry_trend(c.copy(), {"pair": PAIR})
    for x in (a, b, c, d):
        assert int(x["enter_long"].iloc[:-1].sum()) == 0
        assert int(x["exit_long"].sum()) == 0
        assert int(x["enter_long"].iloc[-1]) == 1
        assert x["enter_tag"].iloc[-1] == "route_c_target"
        assert x["enter_tag"].iloc[:-1].isna().all() or all(
            v is None for v in x["enter_tag"].iloc[:-1]
        )
    pd.testing.assert_frame_equal(
        a.reset_index(drop=True), d.reset_index(drop=True)
    )


def test_stale_signal_not_reexecuted(fresh_db):
    """上一 heartbeat 写过 enter,订单未成交(FLAT 仍真),本 heartbeat 目标 0:
    旧信号必须消失,不得产生任何订单。"""
    strat = make_strategy()
    df = history_df([1] * 10, latest_target=0)
    df["enter_long"] = 1
    s = sig(df, strat)
    assert s["enter_last"] == 0 and s["exit_last"] == 0 and s["enter_hist"] == 0


# ------------------------------------------------- backtest 与 live 分路
def test_backtest_path_still_scans_full_history(fresh_db):
    """backtest runmode 走顺序扫描:整段目标 0,1,0 产生 enter@1、exit@2。"""
    from freqtrade.enums import RunMode

    strat = make_strategy(runmode=RunMode.BACKTEST)
    df = pd.DataFrame({
        "&-target_position": [0, 1, 1, 0, 0],
        "do_predict": [1, 1, 1, 1, 1],
    })
    out = strat.populate_entry_trend(df, {"pair": PAIR})
    assert out["enter_long"].tolist() == [0, 1, 0, 0, 0]
    assert out["exit_long"].tolist() == [0, 0, 0, 1, 0]

    # 同一数据在 live 路径:只看最新行(FLAT + 0 -> 无信号)
    strat_live = make_strategy()
    s = sig(df, strat_live)
    assert s["enter_last"] == 0 and s["exit_last"] == 0


# ------------------------------------------------- 最新行 trace 证据
def test_live_latest_row_trace_evidence(fresh_db):
    from freqtrade.persistence import Order, Trade

    ART.mkdir(parents=True, exist_ok=True)
    strat = make_strategy()
    rows = []

    def beat(tag, state_setup, target, dp=1):
        from freqtrade.persistence import Trade as T

        T.session.rollback()
        for t in T.get_trades():
            T.session.delete(t)
        T.session.commit()
        state_setup()
        df = history_df([0] * 5, latest_target=target, latest_dp=dp)
        s = sig(df, strat)
        rows.append({"beat": tag, "target": target, "do_predict": dp, **s})

    def _flat():
        pass

    def _pending_entry():
        t = Trade(pair=PAIR, stake_amount=100.0, amount=0.0, open_rate=10000.0,
                  open_date=datetime.now(UTC) - timedelta(hours=1),
                  fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
                  exchange="binanceus")
        t.orders.append(Order(
            ft_order_side="buy", ft_pair=PAIR, ft_is_open=True, ft_amount=0.01,
            ft_price=10000.0, order_id=f"be_{len(rows)}", symbol=PAIR, side="buy",
            order_type="limit", status="open", price=10000.0, amount=0.01,
            filled=0.0, remaining=0.01, cost=0.0,
            order_date=datetime.now(UTC) - timedelta(minutes=5),
        ))
        Trade.session.add(t)
        Trade.session.commit()

    def _long():
        t = Trade(pair=PAIR, stake_amount=100.0, amount=0.01, open_rate=10000.0,
                  open_date=datetime.now(UTC) - timedelta(hours=1),
                  fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
                  exchange="binanceus")
        Trade.session.add(t)
        Trade.session.commit()

    beat("flat_t1_enter", _flat, 1)
    beat("flat_t0_hold", _flat, 0)
    beat("pending_entry_t1_hold", _pending_entry, 1)
    beat("pending_entry_t0_cancel", _pending_entry, 0)
    beat("long_t0_exit", _long, 0)
    beat("long_t1_hold", _long, 1)
    beat("flat_invalid_dp", _flat, 1, dp=2)
    pd.DataFrame(rows).to_csv(ART / "live_latest_row_trace.csv", index=False)

    by = {r["beat"]: r for r in rows}
    assert by["flat_t1_enter"]["enter_last"] == 1
    assert by["flat_t0_hold"]["enter_last"] == 0
    assert by["pending_entry_t1_hold"]["enter_last"] == 0
    assert by["pending_entry_t0_cancel"]["enter_last"] == 0
    assert by["pending_entry_t0_cancel"]["exit_last"] == 0  # 反转 heartbeat 无 exit
    assert by["long_t0_exit"]["exit_last"] == 1
    assert by["long_t1_hold"]["exit_last"] == 0
    assert by["flat_invalid_dp"]["enter_last"] == 0
    for r in rows:
        assert r["enter_hist"] == 0 and r["exit_hist"] == 0
