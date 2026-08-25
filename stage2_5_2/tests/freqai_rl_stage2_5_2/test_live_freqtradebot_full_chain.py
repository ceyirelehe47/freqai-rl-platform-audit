"""工作包 C:FreqtradeBot 完整链路 12 场景(任务书十二节)。

链路:RouteCModel.rl_model_predict -> RouteCStrategyShellLive(真实信号
路径)-> FreqtradeBot.process -> Fake Exchange -> 真实 Trade/Order 持久层
-> 下一 heartbeat。场景编号与任务书十二节一一对应;每个场景断言:
执行状态、模型观察仓位、订单创建/保留/取消、以及「同方向挂单不重复」。

订单状态变化一律通过 Freqtrade 官方路径同步:
- 成交:update_trades_without_assigned_fees / manage_open_orders ->
  update_trade_state -> trade.update_order -> recalc_trade_from_orders;
- 取消:manage_open_orders -> ft_check_timed_out / replace_order ->
  strategy.adjust_order_price(返回 None)-> handle_replace_order ->
  handle_cancel_enter/exit -> cancel_order_with_result;
不手工修改 Trade.amount / Order.filled。
"""

import json
from pathlib import Path

import pytest

from freqai_rl_stage2_5_2.bot_harness import BotHarness, PAIR

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2"


@pytest.fixture()
def harness(tmp_path):
    h = BotHarness(tmp_path / "chain", n_history=100)
    yield h
    from freqtrade.persistence import Trade

    Trade.session.rollback()


# ------------------------------------------------ 场景 1:首次全历史启动,空仓,目标多头
def test_scenario_1_first_full_history_start_flat_target_long(harness):
    """100 行历史 + FLAT + 最新目标 1 + do_predict=1:
    前 99 行无信号,最新行恰一个 entry,FreqtradeBot 创建一个 entry order。"""
    harness.fake.create_status = "open"
    harness.fake.create_filled = 0.0
    harness.set_target(1)
    snap = harness.heartbeat(advance=False)  # 首次:不推进,直接喂整段历史

    # 历史回填:rl_model_predict 走 history_backfill 分支
    trace = harness.model_shell.live_trace[-1]
    assert trace["mode"] == "history_backfill"
    assert trace["n_rows"] == 100
    # 信号:仅最新行
    assert snap["signals"]["enter_last"] == 1
    assert snap["signals"]["exit_last"] == 0
    # 分析后整张 df 的历史行信号为 0(九节)
    df, _ = harness.bot.dataprovider.get_analyzed_dataframe(PAIR, "1h")
    assert int(df["enter_long"].iloc[:-1].sum()) == 0
    assert int(df["exit_long"].iloc[:-1].sum()) == 0
    # 执行状态:入场挂单零成交 -> PENDING_ENTRY(不是 LONG!)
    assert snap["state"] == "PENDING_ENTRY"
    assert snap["model_position"] == 0
    # 恰好创建了一个 entry order
    assert len(harness.fake.created_calls) == 1
    assert harness.fake.created_calls[0]["side"] == "buy"
    assert snap["n_created_orders"] == 1
    assert snap["trade_amount"] == 0.0  # 未成交:amount 仍为 0
    # 证据
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "freqtradebot_full_chain.md").write_text(
        "# FreqtradeBot 完整链路(工作包 C)\n\n"
        "## 场景 1:首次全历史启动(空仓,目标 1)\n"
        f"- 100 行历史回填:前 99 行 enter/exit 全 0,最新行 enter=1\n"
        f"- Fake Exchange 创建 1 个 entry order: {harness.fake.created_calls[0]}\n"
        f"- 执行状态 PENDING_ENTRY(零成交挂单,模型观察 0,旧简化会误判多头)\n",
        encoding="utf-8",
    )


# ------------------------------------------------ 场景 2:entry 挂单零成交
def test_scenario_2_entry_open_zero_fill(harness):
    harness.fake.create_status = "open"
    harness.fake.create_filled = 0.0
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]

    harness.set_target(1)  # 目标仍为 1
    snap = harness.heartbeat()
    assert snap["state"] == "PENDING_ENTRY"
    assert snap["model_position"] == 0
    assert snap["n_created_orders"] == 1, "不得创建第二个 entry order"
    assert oid in snap["open_order_ids"], "原 entry order 必须保持活动"
    assert snap["signals"]["enter_last"] == 0, "同方向挂单期间无重复入场信号"


# ------------------------------------------------ 场景 3:entry 部分成交
def test_scenario_3_entry_partial_fill(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]

    # 下一 heartbeat:fetch 脚本推进到部分成交(仍 open)
    harness.fake.fetch_script[oid] = [
        {"status": "open", "filled": amt * 0.4},
    ]
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "PARTIAL_ENTRY"
    assert snap["model_position"] == 1
    assert snap["n_created_orders"] == 1, "部分成交期间不创建第二个 entry"
    # Trade 实际数量与订单累计成交一致(官方 update_trade_state 路径)
    from freqtrade.persistence import Trade
    t = Trade.get_trades_proxy(is_open=True)[0]
    # 注意:活动订单的部分成交不计入 trade.amount(recalc 跳过 ft_is_open),
    # 暴露 = trade.amount + 订单 filled(执行状态解析器口径)
    o = t.select_order_by_order_id(oid)
    assert o.safe_filled == pytest.approx(amt * 0.4)
    assert snap["filled_amount"] == pytest.approx(amt * 0.4)


# ------------------------------------------------ 场景 4:entry 全部成交
def test_scenario_4_entry_fully_filled(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]

    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "LONG"
    assert snap["model_position"] == 1
    assert snap["n_created_orders"] == 1, "目标仍为 1,不再入场"
    assert not snap["open_order_ids"]
    assert snap["trade_amount"] == pytest.approx(amt, rel=1e-9)


# ------------------------------------------------ 场景 5:目标变为空仓 -> 创建 exit
def test_scenario_5_target_flips_to_exit(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "LONG"

    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["signals"]["exit_last"] == 1
    assert len(harness.fake.created_calls) == 2
    assert harness.fake.created_calls[1]["side"] == "sell"
    assert snap["state"] in ("PENDING_EXIT", "LONG")  # exit 单 open 零成交


# ------------------------------------------------ 场景 6:exit 挂单零成交
def test_scenario_6_exit_open_zero_fill(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    harness.heartbeat()
    harness.set_target(0)
    harness.heartbeat()
    assert len(harness.fake.created_calls) == 2

    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["state"] == "PENDING_EXIT"
    assert snap["model_position"] == 1
    assert snap["n_created_orders"] == 2, "不得创建第二个 exit order"
    assert snap["signals"]["exit_last"] == 0


# ------------------------------------------------ 场景 7:exit 部分成交
def test_scenario_7_exit_partial_fill(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    harness.heartbeat()
    harness.set_target(0)
    harness.heartbeat()
    xoid = harness.fake.created_calls[1]["order_id"]

    harness.fake.fetch_script[xoid] = [{"status": "open", "filled": amt * 0.5}]
    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["state"] == "PARTIAL_EXIT"
    assert snap["model_position"] == 1
    assert snap["filled_amount"] == pytest.approx(amt * 0.5)
    assert snap["n_created_orders"] == 2, "不重复创建 exit"


# ------------------------------------------------ 场景 8:exit 全部成交
def test_scenario_8_exit_fully_filled(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    harness.heartbeat()
    harness.set_target(0)
    harness.heartbeat()
    xoid = harness.fake.created_calls[1]["order_id"]

    harness.fake.fetch_script[xoid] = [{"status": "closed", "filled": amt}]
    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["n_open_trades"] == 0
    from rl_platform.execution_state import get_live_execution_snapshot
    assert get_live_execution_snapshot(PAIR).state == "FLAT"
    assert snap["n_created_orders"] == 2, "目标 0 已平仓,不再退出"


# ------------------------------------------------ 场景 9:entry 被拒/零成交过期 -> 恢复 FLAT
def test_scenario_9_entry_expired_recovers_flat_then_reenter(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]

    # 交易所把挂单置为 expired(零成交):官方 update_trade_state ->
    # check_order_canceled_empty -> handle_cancel_order 删除 trade
    harness.fake.fetch_script[oid] = [{"status": "expired", "filled": 0.0}]
    harness.set_target(1)
    snap = harness.heartbeat()
    from rl_platform.execution_state import get_live_execution_snapshot
    assert get_live_execution_snapshot(PAIR).state == "FLAT"
    assert snap["n_open_trades"] == 0
    # 下一有效 heartbeat 目标仍 1 -> 重新尝试一次 entry
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "PENDING_ENTRY"
    assert len(harness.fake.created_calls) == 2


def test_scenario_9b_entry_rejected_at_creation(harness):
    """下单即被交易所拒绝:execute_entry 返回 False,不留任何 Trade。"""
    harness.fake.create_status = "rejected"
    harness.fake.create_filled = 0.0
    harness.set_target(1)
    snap = harness.heartbeat(advance=False)
    assert snap["n_open_trades"] == 0
    from rl_platform.execution_state import get_live_execution_snapshot
    assert get_live_execution_snapshot(PAIR).state == "FLAT"


# ------------------------------------------------ 场景 10:pending entry 期间目标反转
def test_scenario_10_reversal_cancel_pending_entry_zero_fill(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]

    # 目标反转 1 -> 0:同 heartbeat 取消挂单、不创建 exit
    harness.set_target(0)
    snap = harness.heartbeat()
    assert oid in harness.fake.cancel_calls, "必须请求取消剩余 entry"
    assert snap["n_created_orders"] == 1, "同一 heartbeat 不创建 exit"
    from rl_platform.execution_state import get_live_execution_snapshot
    assert get_live_execution_snapshot(PAIR).state == "FLAT", "零成交取消后恢复 FLAT"
    assert snap["n_open_trades"] == 0  # trade 被上游删除


def test_scenario_10b_reversal_cancel_pending_entry_partial_fill(harness):
    """部分成交的 entry 反转:取消剩余量,保留已成交暴露(PARTIAL_ENTRY -> LONG)。"""
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    # 推进到部分成交
    harness.fake.fetch_script[oid] = [{"status": "open", "filled": amt * 0.4}]
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "PARTIAL_ENTRY"

    # 目标反转 0 -> 取消剩余 entry(取消后订单 canceled,已成交 40% 保留)
    harness.fake.fetch_script[oid] = [
        {"status": "open", "filled": amt * 0.4},
        {"status": "canceled", "filled": amt * 0.4},
    ]
    harness.set_target(0)
    snap = harness.heartbeat()
    assert oid in harness.fake.cancel_calls
    assert snap["n_created_orders"] == 1, "同一 heartbeat 不创建 exit"
    from rl_platform.execution_state import get_live_execution_snapshot
    st = get_live_execution_snapshot(PAIR)
    assert st.state == "LONG", "部分成交暴露保留 -> LONG(无活动订单)"
    assert st.filled_amount == pytest.approx(amt * 0.4)


# ------------------------------------------------ 场景 11:pending exit 期间目标反转
def test_scenario_11_reversal_cancel_pending_exit(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    harness.heartbeat()
    harness.set_target(0)
    harness.heartbeat()
    xoid = harness.fake.created_calls[1]["order_id"]

    # 目标反转回 1:取消剩余 exit,同一 heartbeat 不创建 entry
    harness.set_target(1)
    snap = harness.heartbeat()
    assert xoid in harness.fake.cancel_calls
    assert snap["n_created_orders"] == 2, "同一 heartbeat 不创建新 entry"
    from rl_platform.execution_state import get_live_execution_snapshot
    st = get_live_execution_snapshot(PAIR)
    assert st.state == "LONG", "取消后仍有暴露 -> 保持 LONG"
    assert st.filled_amount == pytest.approx(amt, rel=1e-9)


# ------------------------------------------------ 场景 12:进程重启恢复
def test_scenario_12_restart_recovery(tmp_path):
    """五种状态分别重建 harness(新 FreqtradeBot/新模型/新策略实例),
    从同一 SQLite 恢复相同执行状态,不依赖旧 Python 实例属性。"""
    db_url = f"sqlite:///{tmp_path}/shared_bot.db"
    rows = []

    def build_and_seed(state_name, seeder):
        h = BotHarness(tmp_path / state_name, share_db_url=db_url)
        from freqtrade.persistence import Trade

        Trade.session.rollback()
        for t in Trade.get_trades():
            Trade.session.delete(t)
        Trade.session.commit()
        seeder(h)
        # 「重启」:全新 harness 连同一数据库,内存状态全空
        h2 = BotHarness(tmp_path / (state_name + "_restart"), share_db_url=db_url)
        snap = h2.snapshot()
        rows.append({"state": state_name, "recovered": snap["state"],
                     "model_position": snap["model_position"],
                     "filled_amount": snap.filled_amount if hasattr(snap, "filled_amount") else snap["filled_amount"]})
        return snap, rows[-1]

    def seed_pending_entry(h):
        h.set_target(1)
        h.heartbeat(advance=False)

    def seed_partial_entry(h):
        h.set_target(1)
        h.heartbeat(advance=False)
        oid = h.fake.created_calls[0]["order_id"]
        amt = h.fake.created_calls[0]["amount"]
        h.fake.fetch_script[oid] = [{"status": "open", "filled": amt * 0.4}]
        h.set_target(1)
        h.heartbeat()

    def seed_long(h):
        h.set_target(1)
        h.heartbeat(advance=False)
        oid = h.fake.created_calls[0]["order_id"]
        amt = h.fake.created_calls[0]["amount"]
        h.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
        h.set_target(1)
        h.heartbeat()

    def seed_pending_exit(h):
        seed_long(h)
        h.set_target(0)
        h.heartbeat()

    def seed_partial_exit(h):
        seed_long(h)
        h.set_target(0)
        h.heartbeat()
        xoid = h.fake.created_calls[1]["order_id"]
        amt = h.fake.created_calls[1]["amount"]
        h.fake.fetch_script[xoid] = [{"status": "open", "filled": amt * 0.5}]
        h.set_target(0)
        h.heartbeat()

    s, r = build_and_seed("PENDING_ENTRY", seed_pending_entry)
    assert r["recovered"] == "PENDING_ENTRY" and r["model_position"] == 0
    s, r = build_and_seed("PARTIAL_ENTRY", seed_partial_entry)
    assert r["recovered"] == "PARTIAL_ENTRY" and r["model_position"] == 1
    s, r = build_and_seed("LONG", seed_long)
    assert r["recovered"] == "LONG" and r["model_position"] == 1
    s, r = build_and_seed("PENDING_EXIT", seed_pending_exit)
    assert r["recovered"] == "PENDING_EXIT" and r["model_position"] == 1
    s, r = build_and_seed("PARTIAL_EXIT", seed_partial_exit)
    assert r["recovered"] == "PARTIAL_EXIT" and r["model_position"] == 1

    ART.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    pd.DataFrame(rows).to_csv(ART / "restart_recovery_trace.csv", index=False)


# ------------------------------------------------ do_predict 无效:无订单变化
def test_do_predict_invalid_no_order_changes(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)

    # do_predict=2:不生成新订单,不取消既有挂单,目标即使反转也不动订单
    harness.set_target_invalid_prediction(0, dp=2)
    snap = harness.heartbeat()
    assert snap["n_created_orders"] == 1
    assert snap["n_cancel_calls"] == 0, "无效预测不得触发取消"
    assert snap["state"] == "PENDING_ENTRY"
    assert snap["signals"]["enter_last"] == 0
    assert snap["signals"]["exit_last"] == 0


# ------------------------------------------------ 证据:完整链路 trace
def test_full_chain_evidence(harness):
    """把场景 1-8 的主线路径写进证据文件(逐 heartbeat 状态迁移)。"""
    rows = []
    harness.set_target(1)
    rows.append({"beat": "first_history", **{k: v for k, v in harness.heartbeat(advance=False).items() if k != "orders"}})
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "closed", "filled": amt}]
    harness.set_target(1)
    rows.append({"beat": "entry_filled", **{k: v for k, v in harness.heartbeat().items() if k != "orders"}})
    harness.set_target(0)
    rows.append({"beat": "exit_created", **{k: v for k, v in harness.heartbeat().items() if k != "orders"}})
    xoid = harness.fake.created_calls[1]["order_id"]
    harness.fake.fetch_script[xoid] = [{"status": "open", "filled": amt * 0.5}]
    harness.set_target(0)
    rows.append({"beat": "exit_partial", **{k: v for k, v in harness.heartbeat().items() if k != "orders"}})
    harness.fake.fetch_script[xoid] = [{"status": "closed", "filled": amt}]
    harness.set_target(0)
    rows.append({"beat": "exit_filled_flat", **{k: v for k, v in harness.heartbeat().items() if k != "orders"}})

    import pandas as pd

    ART.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(ART / "freqtradebot_full_chain_trace.csv", index=False)
    states = [r["state"] for r in rows]
    assert states == ["PENDING_ENTRY", "LONG", "PENDING_EXIT", "PARTIAL_EXIT", "FLAT"]
