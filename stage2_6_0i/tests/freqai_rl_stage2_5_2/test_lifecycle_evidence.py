"""工作包 C 证据补齐:pending/partial/反转生命周期逐 heartbeat trace CSV。

复用 bot_harness,把任务书二十四节要求的生命周期证据文件逐一产出:
- pending_entry_trace.csv(场景 2 + 9 的挂单/过期恢复)
- partial_entry_trace.csv(场景 3 + 10b 的部分成交与反转取消)
- pending_exit_trace.csv(场景 6 + 11 的退出挂单/反转取消)
- partial_exit_trace.csv(场景 7)
- target_reversal_cancel_trace.csv(场景 10/11 取消请求与取消后行为)
- freqtradebot_full_chain.md(完整链路说明与场景清单)
"""

from pathlib import Path

import pandas as pd

from freqai_rl_stage2_5_2.bot_harness import BotHarness, PAIR

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2"


def _row(tag, snap):
    return {
        "beat": tag,
        "state": snap["state"],
        "model_position": snap["model_position"],
        "filled_amount": snap["filled_amount"],
        "n_created_orders": snap["n_created_orders"],
        "n_cancel_calls": snap["n_cancel_calls"],
        "open_orders": len(snap["open_order_ids"]),
        "enter_last": snap["signals"]["enter_last"],
        "exit_last": snap["signals"]["exit_last"],
    }


def _fill_entry(h, frac=1.0):
    h.set_target(1)
    h.heartbeat(advance=False)
    oid = h.fake.created_calls[0]["order_id"]
    amt = h.fake.created_calls[0]["amount"]
    h.fake.fetch_script[oid] = [{"status": "closed", "filled": amt * frac}]
    h.set_target(1)
    h.heartbeat()
    return oid, amt


def test_lifecycle_trace_evidence(tmp_path):
    ART.mkdir(parents=True, exist_ok=True)

    # ---------------- pending entry(挂单零成交 -> 过期 -> 恢复 -> 重入)
    h = BotHarness(tmp_path / "pending_entry", n_history=100)
    rows = [_row("first_history_target1", h.snapshot())]
    h.set_target(1)
    rows.append(_row("create_entry_order", h.heartbeat(advance=False)))
    oid = h.fake.created_calls[0]["order_id"]
    for i in range(2):
        h.set_target(1)
        rows.append(_row(f"hold_zero_fill_{i + 1}", h.heartbeat()))
    h.fake.fetch_script[oid] = [{"status": "expired", "filled": 0.0}]
    h.set_target(1)
    rows.append(_row("order_expired_recovers_flat", h.heartbeat()))
    h.set_target(1)
    rows.append(_row("reenter_after_recovery", h.heartbeat()))
    pd.DataFrame(rows).to_csv(ART / "pending_entry_trace.csv", index=False)

    # ---------------- partial entry(部分成交 -> 反转取消保留暴露 -> 退出)
    h2 = BotHarness(tmp_path / "partial_entry", n_history=100)
    rows = [_row("flat_target1", h2.snapshot())]
    h2.set_target(1)
    rows.append(_row("create_entry_order", h2.heartbeat(advance=False)))
    oid2 = h2.fake.created_calls[0]["order_id"]
    amt2 = h2.fake.created_calls[0]["amount"]
    h2.fake.fetch_script[oid2] = [{"status": "open", "filled": amt2 * 0.4}]
    h2.set_target(1)
    rows.append(_row("partial_fill_40pct", h2.heartbeat()))
    h2.fake.fetch_script[oid2] = [
        {"status": "open", "filled": amt2 * 0.4},
        {"status": "canceled", "filled": amt2 * 0.4},
    ]
    h2.set_target(0)
    rows.append(_row("reversal_cancel_keeps_40pct", h2.heartbeat()))
    h2.set_target(0)
    rows.append(_row("next_beat_exits_actual_exposure", h2.heartbeat()))
    pd.DataFrame(rows).to_csv(ART / "partial_entry_trace.csv", index=False)

    # ---------------- pending exit(退出挂单零成交 -> 反转取消保持 LONG)
    h3 = BotHarness(tmp_path / "pending_exit", n_history=100)
    _oid3, amt3 = _fill_entry(h3)
    rows = [_row("long_after_fill", h3.snapshot())]
    h3.set_target(0)
    rows.append(_row("create_exit_order", h3.heartbeat()))
    xoid3 = h3.fake.created_calls[1]["order_id"]
    h3.set_target(0)
    rows.append(_row("hold_zero_fill_exit", h3.heartbeat()))
    h3.set_target(1)
    rows.append(_row("reversal_cancel_exit_keeps_long", h3.heartbeat()))
    pd.DataFrame(rows).to_csv(ART / "pending_exit_trace.csv", index=False)

    # ---------------- partial exit(部分退出 -> 补完 -> FLAT)
    h4 = BotHarness(tmp_path / "partial_exit", n_history=100)
    _oid4, amt4 = _fill_entry(h4)
    h4.set_target(0)
    h4.heartbeat()
    xoid4 = h4.fake.created_calls[1]["order_id"]
    rows = []
    h4.fake.fetch_script[xoid4] = [{"status": "open", "filled": amt4 * 0.5}]
    h4.set_target(0)
    rows.append(_row("exit_50pct_sold", h4.heartbeat()))
    h4.fake.fetch_script[xoid4] = [{"status": "closed", "filled": amt4}]
    h4.set_target(0)
    rows.append(_row("exit_completed_flat", h4.heartbeat()))
    pd.DataFrame(rows).to_csv(ART / "partial_exit_trace.csv", index=False)

    # ---------------- target reversal cancel(入场零成交/部分成交 + 退出)
    h5 = BotHarness(tmp_path / "reversal", n_history=100)
    rows = []
    h5.set_target(1)
    h5.heartbeat(advance=False)
    oid5 = h5.fake.created_calls[0]["order_id"]
    amt5 = h5.fake.created_calls[0]["amount"]
    h5.set_target(0)
    rows.append(_row("cancel_entry_zero_fill", h5.heartbeat()))
    h5.set_target(1)
    rows.append(_row("reenter", h5.heartbeat()))
    oid5b = h5.fake.created_calls[1]["order_id"]
    h5.fake.fetch_script[oid5b] = [{"status": "closed", "filled": amt5}]
    h5.set_target(1)
    rows.append(_row("filled_long", h5.heartbeat()))
    h5.set_target(0)
    rows.append(_row("create_exit", h5.heartbeat()))
    xoid5 = h5.fake.created_calls[2]["order_id"]
    h5.set_target(1)
    rows.append(_row("cancel_exit_keep_long", h5.heartbeat()))
    pd.DataFrame(rows).to_csv(ART / "target_reversal_cancel_trace.csv", index=False)

    # ---------------- 完整链路说明(交付物 freqtradebot_full_chain.md)
    (ART / "freqtradebot_full_chain.md").write_text(
        "# FreqtradeBot 完整链路(阶段 2.5.2 工作包 C)\n\n"
        "链路:RouteCModel.rl_model_predict -> RouteCStrategyShellLive"
        "(真实 populate_entry/exit_trend + adjust_*_price)-> FreqtradeBot.process"
        "(analyze -> manage_open_orders -> exit_positions -> enter_positions)"
        " -> Fake Exchange(脚本化订单状态) -> 真实 Trade/Order 持久层(文件 SQLite)"
        " -> 下一 heartbeat。\n\n"
        "## 场景清单(任务书十二节)\n\n"
        "| 场景 | 测试 | 结论 |\n|---|---|---|\n"
        "| 1 首次全历史启动空仓目标多头 | test_scenario_1 | 前 99 行无信号,"
        "最新行恰一个 entry,PENDING_ENTRY(非 LONG) |\n"
        "| 2 entry 挂单零成交 | test_scenario_2 | 不建第二个 entry,原单保持 |\n"
        "| 3 entry 部分成交 | test_scenario_3 | PARTIAL_ENTRY,模型观察 1,"
        "数量与 Order.filled 一致 |\n"
        "| 4 entry 全部成交 | test_scenario_4 | LONG,不再入场 |\n"
        "| 5 目标转空仓 | test_scenario_5 | 创建 exit order |\n"
        "| 6 exit 挂单零成交 | test_scenario_6 | PENDING_EXIT,不重复 exit |\n"
        "| 7 exit 部分成交 | test_scenario_7 | PARTIAL_EXIT,剩余暴露一致 |\n"
        "| 8 exit 全部成交 | test_scenario_8 | FLAT,不再退出 |\n"
        "| 9 entry 拒绝/零成交过期 | test_scenario_9/9b | 恢复 FLAT,可重入 |\n"
        "| 10 pending entry 反转 | test_scenario_10/10b | 官方扩展点取消,"
        "部分成交保留暴露 |\n"
        "| 11 pending exit 反转 | test_scenario_11 | 取消保持 LONG |\n"
        "| 12 进程重启恢复 | test_scenario_12 | 五状态从 SQLite 恢复一致 |\n"
        "| do_predict 无效 | test_do_predict_invalid | 无订单变化 |\n\n"
        "订单状态变化全部经 Freqtrade 官方路径(update_trade_state / "
        "handle_cancel_order / adjust_order_price),无 Trade.amount 手工篡改。\n",
        encoding="utf-8",
    )
