"""工作包 C 补充:目标反转取消后的后续 heartbeat 行为(任务书八节、十节)。

覆盖 full_chain 之外的关键后续验证:
- 零成交 entry 反转取消 -> 下一 heartbeat 按实际暴露(FLAT)决策;
- 部分成交 entry 反转取消 -> 保留暴露 -> 下一 heartbeat 目标 0 生成 exit;
- exit 反转取消 -> 保留 LONG -> 下一 heartbeat 目标 0 重新 exit、目标 1 保持;
- 取消请求只在目标反转时发生(非反转 heartbeat 不触碰订单)。
"""

from pathlib import Path

import pytest

from freqai_rl_stage2_5_2.bot_harness import BotHarness, PAIR


@pytest.fixture()
def harness(tmp_path):
    h = BotHarness(tmp_path / "reversal", n_history=100)
    yield h
    from freqtrade.persistence import Trade

    Trade.session.rollback()


def _fill_entry(h, frac=1.0):
    h.set_target(1)
    h.heartbeat(advance=False)
    oid = h.fake.created_calls[0]["order_id"]
    amt = h.fake.created_calls[0]["amount"]
    h.fake.fetch_script[oid] = [{"status": "closed", "filled": amt * frac}]
    h.set_target(1)
    h.heartbeat()
    return oid, amt


def test_after_zero_fill_entry_cancel_next_heartbeat_flat(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]

    # 反转 -> 取消
    harness.set_target(0)
    snap = harness.heartbeat()
    assert oid in harness.fake.cancel_calls
    assert snap["state"] == "FLAT"

    # 下一 heartbeat:目标 0 -> FLAT hold,无任何新订单
    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["n_created_orders"] == 1
    assert snap["signals"]["enter_last"] == 0
    assert snap["signals"]["exit_last"] == 0

    # 目标回到 1 -> 重新 entry(取消完成后按实际暴露决策)
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "PENDING_ENTRY"
    assert len(harness.fake.created_calls) == 2


def test_after_partial_entry_cancel_next_heartbeat_exits(harness):
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    amt = harness.fake.created_calls[0]["amount"]
    harness.fake.fetch_script[oid] = [{"status": "open", "filled": amt * 0.4}]
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["state"] == "PARTIAL_ENTRY"

    # 反转取消(取消前 fetch 仍 open,取消后 canceled,40% 保留)
    harness.fake.fetch_script[oid] = [
        {"status": "open", "filled": amt * 0.4},
        {"status": "canceled", "filled": amt * 0.4},
    ]
    harness.set_target(0)
    snap = harness.heartbeat()
    assert oid in harness.fake.cancel_calls
    assert snap["n_created_orders"] == 1, "取消 heartbeat 不创建 exit"

    # 下一 heartbeat:LONG(40% 暴露)+ 目标 0 -> 生成 exit(同一 process 内
    # analyze 写 exit 信号 -> exit_positions 下单,状态转为 PENDING_EXIT)
    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["state"] in ("LONG", "PENDING_EXIT")
    assert snap["signals"]["exit_last"] == 1
    assert len(harness.fake.created_calls) == 2
    assert harness.fake.created_calls[1]["side"] == "sell"
    assert harness.fake.created_calls[1]["amount"] == pytest.approx(amt * 0.4, rel=1e-6)


def test_after_exit_cancel_next_heartbeat_re_exits(harness):
    _oid, amt = _fill_entry(harness)
    harness.set_target(0)
    harness.heartbeat()
    xoid = harness.fake.created_calls[1]["order_id"]

    # 目标反转回 1 -> 取消 exit,保留 LONG
    harness.set_target(1)
    snap = harness.heartbeat()
    assert xoid in harness.fake.cancel_calls
    assert snap["n_created_orders"] == 2
    from rl_platform.execution_state import get_live_execution_snapshot
    assert get_live_execution_snapshot(PAIR).state == "LONG"

    # 下一 heartbeat:目标 1 -> LONG hold,无新订单
    harness.set_target(1)
    snap = harness.heartbeat()
    assert snap["n_created_orders"] == 2
    assert snap["signals"]["enter_last"] == 0 and snap["signals"]["exit_last"] == 0

    # 目标再回 0 -> 重新 exit(按实际暴露)
    harness.set_target(0)
    snap = harness.heartbeat()
    assert snap["signals"]["exit_last"] == 1
    assert len(harness.fake.created_calls) == 3


def test_no_cancel_without_target_reversal(harness):
    """目标不反转(持续 1)时,挂单保持,绝不取消(取消只能来自目标反转)。"""
    harness.set_target(1)
    harness.heartbeat(advance=False)
    oid = harness.fake.created_calls[0]["order_id"]
    for _ in range(3):
        harness.set_target(1)
        snap = harness.heartbeat()
        assert snap["n_cancel_calls"] == 0
        assert oid in snap["open_order_ids"]
