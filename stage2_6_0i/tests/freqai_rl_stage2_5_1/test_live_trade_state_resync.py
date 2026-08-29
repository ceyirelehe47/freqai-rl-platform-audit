"""工作包 G 测试(二):Trade 状态 heartbeat 重同步(任务书 2.5.1 二十四节;
阶段 2.5.2 工作包 A/B 语义更新)。

订单成交状态的真值来源固定为 Freqtrade Trade/Order 持久层(内存 SQLite +
真实 Trade/Order 模型),信号生成经真实 RouteCStrategy.populate_entry_trend
(dp.runmode=DRY_RUN -> live 路径 latest_row_signals)读取真实执行状态。
不连接真实账户、无 API Key。

阶段 2.5.2 更新说明(旧断言为什么错误):
1. 旧版把「入场挂单零成交」建模为「Trade 表为空」——依据固定源码
   freqtradebot.execute_entry,限价单在下单当刻即创建 amount=0 的 open Trade,
   挂单未成交时 Trade 表并非为空,而是「open Trade + 活动入场 Order(filled=0)」,
   即执行状态 PENDING_ENTRY。旧断言在该状态下仍要求 enter=1(重复入场),
   与 2.5.2 任务书八节「同方向活动订单 -> 不生成重复 entry」矛盾。
   新断言用真实 Order 建模零成交挂单,要求不重复入场;Trade 表真为空(FLAT)
   且目标 1 时仍生成入场(该子断言保留,语义未变)。
2. 旧版把「退出挂单零成交」建模为「trade.amount>0 无订单」,并要求持续
   重复 exit 信号。真实零成交退出单是「暴露>0 + 活动 exit Order(filled=0)」
   (PENDING_EXIT);freqtradebot.execute_trade_exit 对同方向挂单走
   handle_similar_open_order 防重复,新断言要求不重复 exit(更严格、
   与 FreqtradeBot 行为一致)。
"""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

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


def clear_trades():
    from freqtrade.persistence import Trade

    Trade.session.rollback()
    for t in Trade.get_trades_proxy(is_open=True):
        Trade.session.delete(t)
    Trade.session.commit()


def set_filled_long(amount: float = 0.01):
    """已全部成交的多头:open Trade(amount>0),无活动订单 -> LONG。"""
    from freqtrade.persistence import Trade

    t = Trade(pair=PAIR, stake_amount=100.0, amount=amount, open_rate=10000.0,
              open_date=datetime.now(UTC) - timedelta(hours=2),
              fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
              exchange="binanceus")
    Trade.session.add(t)
    Trade.session.commit()
    return t


def set_pending_order(side: str, filled: float):
    """真实活动订单建模:open Trade + 真实 Order(ccxt 语义 side/状态/数量)。

    side="buy" -> 活动入场单;side="sell" -> 活动退出单。
    filled=0 零成交;0<filled<amount 部分成交(trade.amount 不含活动订单成交,
    按 recalc_trade_from_orders 语义显式置零)。
    """
    from freqtrade.persistence import Order, Trade

    amount = 0.01
    t = Trade(pair=PAIR, stake_amount=100.0, amount=0.0 if side == "buy" else amount,
              open_rate=10000.0,
              open_date=datetime.now(UTC) - timedelta(hours=2),
              fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
              exchange="binanceus")
    o = Order(
        ft_order_side=side, ft_pair=PAIR, ft_is_open=True,
        ft_amount=amount, ft_price=10000.0,
        order_id=f"test_order_{side}_{filled}", symbol=PAIR, side=side,
        order_type="limit", status="open", price=10000.0, average=None,
        amount=amount, filled=filled, remaining=amount - filled,
        cost=filled * 10000.0,
        order_date=datetime.now(UTC) - timedelta(minutes=10),
    )
    o.ft_trade_id = 0
    t.orders.append(o)
    Trade.session.add(t)
    Trade.session.commit()
    return t, o


def heartbeat_signals(strategy, model_target: int, do_predict: int = 1) -> dict:
    """模拟一个 heartbeat:模型目标 -> 真实策略 live 路径信号(只处理最新行)。"""
    df = pd.DataFrame({
        "&-target_position": [model_target],
        "do_predict": [do_predict],
    })
    df = strategy.populate_entry_trend(df, {"pair": PAIR})
    return {
        "target": model_target,
        "enter": int(df["enter_long"].iloc[-1]),
        "exit": int(df["exit_long"].iloc[-1]),
    }


# ------------------------- 场景 1:FLAT 入场 + 零成交挂单不重复入场(PENDING_ENTRY)
def test_entry_unfilled_no_duplicate_and_flat_enters(fresh_db):
    strat = make_strategy()
    # 真为空仓(FLAT)+ 目标 1 -> 入场(旧断言此子句保留)
    clear_trades()
    s0 = heartbeat_signals(strat, 1)
    assert s0["enter"] == 1 and s0["exit"] == 0

    # 零成交入场挂单(open Trade + entry Order filled=0)-> PENDING_ENTRY:
    # 模型仓位观察 0,但不生成重复 entry(2.5.2 任务书八节)
    clear_trades()
    set_pending_order("buy", filled=0.0)
    from rl_platform.dryrun_state import get_initial_position_live
    from rl_platform.execution_state import get_live_execution_snapshot
    assert get_live_execution_snapshot(PAIR).state == "PENDING_ENTRY"
    assert get_initial_position_live(PAIR) == 0  # 模型观察:无实际暴露
    seen = [heartbeat_signals(strat, 1) for _ in range(3)]
    assert all(s["enter"] == 0 and s["exit"] == 0 for s in seen), seen


# --------------------------------------------- 场景 2:入场已成交 -> 不重复入场
def test_entry_filled_no_duplicate(fresh_db):
    strat = make_strategy()
    set_filled_long()
    seen = [heartbeat_signals(strat, 1) for _ in range(3)]
    assert all(s["enter"] == 0 and s["exit"] == 0 for s in seen), seen


# ------------- 场景 3:零成交退出挂单(PENDING_EXIT)-> 不重复退出(语义更新)
def test_exit_unfilled_no_duplicate(fresh_db):
    """旧断言要求持续 exit=1(重复退出意图);依据固定源码
    execute_trade_exit -> handle_similar_open_order,同方向活动订单不会重复下,
    新断言与之对齐:PENDING_EXIT + 目标 0 -> 无重复 exit 信号。"""
    strat = make_strategy()
    t, o = set_pending_order("sell", filled=0.0)
    from rl_platform.execution_state import get_live_execution_snapshot
    snap = get_live_execution_snapshot(PAIR)
    assert snap.state == "PENDING_EXIT", snap.describe()
    assert snap.model_position == 1  # 实际暴露仍在
    seen = [heartbeat_signals(strat, 0) for _ in range(3)]
    assert all(s["exit"] == 0 and s["enter"] == 0 for s in seen), seen


# --------------------------------------------- 场景 4:退出已完成 -> 不重复退出
def test_exit_completed_no_duplicate(fresh_db):
    strat = make_strategy()
    clear_trades()  # Trade 表为空(FLAT)
    seen = [heartbeat_signals(strat, 0) for _ in range(3)]
    assert all(s["enter"] == 0 and s["exit"] == 0 for s in seen), seen


# --------------------------------------------- 真值源验证:预测历史不影响信号
def test_trade_table_is_source_of_truth(fresh_db):
    """内存中的目标历史不参与信号判定;FLAT + 目标 1 每次都生成入场,
    LONG + 目标 0 每次都生成退出意图信号由真实执行状态决定。"""
    strat = make_strategy()
    clear_trades()
    s1 = heartbeat_signals(strat, 1)
    assert s1["enter"] == 1
    # 三个 heartbeat 目标一直是 1,没有任何成交发生(Trade 表保持为空)
    s2 = heartbeat_signals(strat, 1)
    s3 = heartbeat_signals(strat, 1)
    assert s2["enter"] == 1 and s3["enter"] == 1


# --------------------------------------------- 策略读取的滑点配置(工作包 C 联动)
def test_strategy_slippage_from_config(fresh_db):
    """阶段 2.5.2a 更新(旧断言验证 custom_entry/exit_price 的滑点公式,
    该钩子依赖执行 K 线 high/low 属非因果合同且已被市场订单合同取代):
    新断言更严格——策略为市场订单、不定义价格钩子,simulated 滑点
    不再改变 live 订单价格;amount_epsilon 与模型同源读取(工作包 E)。"""
    strat = make_strategy()
    assert strat.order_types["entry"] == "market"
    assert strat.order_types["exit"] == "market"
    # custom_*_price 是 IStrategy 基类回调;断言本策略类未覆盖它们
    # (即策略不提供任何自定义订单价格,simulated 滑点不改变 live 订单价)
    cls = type(strat)
    while cls.__name__ != "RouteCStrategy" and cls.__bases__:
        cls = cls.__bases__[0]
    assert "custom_entry_price" not in vars(cls), "市场订单策略不得覆盖入场价格钩子"
    assert "custom_exit_price" not in vars(cls), "市场订单策略不得覆盖退出价格钩子"
    # amount_epsilon 从 freqai.route_c 同源读取(与 RouteCModel 一致)
    assert strat.route_c_amount_epsilon == pytest.approx(1e-12)
    strat_e = load_strategy()(config={"freqai": {"route_c": {"amount_epsilon": 1e-3}}})
    strat_e.dp = SimpleNamespace()
    assert strat_e.route_c_amount_epsilon == pytest.approx(1e-3)


# --------------------------------------------- 逐 heartbeat trace 证据
def test_resync_trace_evidence(fresh_db):
    from rl_platform.execution_state import get_live_execution_snapshot

    ART.mkdir(parents=True, exist_ok=True)
    strat = make_strategy()
    rows = []

    def beat(tag, setup, target):
        clear_trades()
        setup()
        snap = get_live_execution_snapshot(PAIR)
        s = heartbeat_signals(strat, target)
        rows.append({
            "beat": tag, "execution_state": snap.state,
            "filled_amount": snap.filled_amount,
            "model_position": snap.model_position,
            "model_target": target, **s,
        })

    beat("flat_target1_enter", lambda: None, 1)
    beat("pending_entry_hold", lambda: set_pending_order("buy", 0.0), 1)
    beat("partial_entry_hold", lambda: set_pending_order("buy", 0.004), 1)
    beat("long_target1_hold", lambda: set_filled_long(), 1)
    beat("long_target0_exit", lambda: set_filled_long(), 0)
    beat("pending_exit_hold", lambda: set_pending_order("sell", 0.0), 0)
    beat("partial_exit_hold", lambda: set_pending_order("sell", 0.004), 0)
    beat("flat_target0_hold", lambda: None, 0)
    pd.DataFrame(rows).to_csv(ART / "live_trade_resync_trace.csv", index=False)

    by = {r["beat"]: r for r in rows}
    assert by["flat_target1_enter"]["enter"] == 1
    assert by["pending_entry_hold"]["execution_state"] == "PENDING_ENTRY"
    assert by["pending_entry_hold"]["enter"] == 0
    assert by["partial_entry_hold"]["execution_state"] == "PARTIAL_ENTRY"
    assert by["partial_entry_hold"]["model_position"] == 1
    assert by["partial_entry_hold"]["enter"] == 0
    assert by["long_target1_hold"]["execution_state"] == "LONG"
    assert by["long_target0_exit"]["exit"] == 1
    assert by["pending_exit_hold"]["execution_state"] == "PENDING_EXIT"
    assert by["pending_exit_hold"]["exit"] == 0
    assert by["partial_exit_hold"]["execution_state"] == "PARTIAL_EXIT"
    assert by["partial_exit_hold"]["exit"] == 0
    assert by["flat_target0_hold"]["execution_state"] == "FLAT"
    assert by["flat_target0_hold"]["enter"] == 0 and by["flat_target0_hold"]["exit"] == 0
