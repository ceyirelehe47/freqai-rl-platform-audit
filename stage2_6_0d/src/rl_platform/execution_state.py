"""真实执行状态解析器(阶段 2.5.2 工作包 A)。

背景(任务书四节):未成交的入场限价单也会创建 open Trade(execute_entry 中
新 Trade 以 amount=0、is_open=True 落库,trade_model.py recalc_trade_from_orders
跳过 ft_is_open 的订单),因此「存在 is_open=True 的非空头 Trade -> 多头」
是错误简化:零成交挂单、部分成交、待退出订单必须分别解析。

本模块从真实 Trade 与 Order 状态中解析:

    FLAT            无实际成交暴露,无活动订单
    PENDING_ENTRY   活动入场单,已成交数量为零
    PARTIAL_ENTRY   入场单未完成,已有正的实际成交
    LONG            正的实际 BTC 暴露,无活动退出单
    PENDING_EXIT    正暴露 + 活动退出单,退出侧尚未发生部分成交
    PARTIAL_EXIT    退出单未完成,已部分卖出,仍有正的剩余暴露
    INCONSISTENT    订单/成交数据互相矛盾,或多活动订单冲突,或空头暴露

实际暴露(filled_amount)定义(依据固定 commit 52bc96f 源码):
    trade.amount        仅由已关闭(ft_is_open=False)订单经 recalc 汇总
    + 活动入场单累计成交 (open entry orders 的 safe_amount_after_fee =
      safe_filled - safe_fee_base,与上游 recalc_trade_from_orders 累计口径一致)
    - 活动退出单累计成交 (open exit orders 的 safe_amount_after_fee)
即活动订单上的部分成交不计入 trade.amount,必须从 Order.filled 单独累计。

模型观察仓位映射(任务书五节,记录进 manifest):
    FLAT->0  PENDING_ENTRY->0  PARTIAL_ENTRY->1  LONG->1
    PENDING_EXIT->1  PARTIAL_EXIT->1  INCONSISTENT->无(fail closed)

INCONSISTENT 语义(fail closed):
    不生成新订单(信号层不写任何 enter/exit);
    快照携带完整诊断(describe());
    绝不静默挑选一个仓位值;model_position 为 None。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

logger = logging.getLogger(__name__)

FLAT = "FLAT"
PENDING_ENTRY = "PENDING_ENTRY"
PARTIAL_ENTRY = "PARTIAL_ENTRY"
LONG = "LONG"
PENDING_EXIT = "PENDING_EXIT"
PARTIAL_EXIT = "PARTIAL_EXIT"
INCONSISTENT = "INCONSISTENT"

ALL_STATES = (
    FLAT, PENDING_ENTRY, PARTIAL_ENTRY, LONG, PENDING_EXIT, PARTIAL_EXIT, INCONSISTENT,
)

# 模型观察中的二值仓位映射(五节);INCONSISTENT 无映射 -> fail closed
MODEL_POSITION_MAP: dict[str, int] = {
    FLAT: 0,
    PENDING_ENTRY: 0,
    PARTIAL_ENTRY: 1,
    LONG: 1,
    PENDING_EXIT: 1,
    PARTIAL_EXIT: 1,
}

# 与固定源码一致的订单状态常量(constants.py)
NON_OPEN_EXCHANGE_STATES = ("cancelled", "canceled", "expired", "rejected", "closed")
CANCELED_EXCHANGE_STATES = ("cancelled", "canceled", "expired", "rejected")

# 实际成交数量的判定 epsilon(五节:与交易所最小数量或明确 epsilon 比较)
DEFAULT_AMOUNT_EPSILON = 1e-12


class InconsistentExecutionStateError(RuntimeError):
    """执行状态为 INCONSISTENT 时的 fail-closed 错误。"""


@dataclass
class OrderFact:
    """一个活动订单的平铺事实(诊断与测试断言用)。"""

    order_id: str
    side: str          # buy / sell(ccxt 语义)
    is_entry: bool     # 是否入场方向(== trade.entry_side)
    status: str | None
    amount: float      # safe_amount(订单数量)
    filled: float      # safe_filled(已成交)
    remaining: float   # safe_remaining
    price: float | None
    cancel_reason: str | None = None
    fee_base: float = 0.0  # safe_fee_base(base 币手续费;quote 费率时为 0)
    filled_after_fee: float = 0.0  # safe_amount_after_fee = safe_filled - fee_base


@dataclass
class ExecutionSnapshot:
    """一次解析的完整结果:状态 + 事实 + 诊断。"""

    state: str
    pair: str
    filled_amount: float = 0.0    # 实际净暴露(base 币)
    closed_amount: float = 0.0    # trade.amount(仅已关闭订单的汇总)
    open_entry_orders: list[OrderFact] = field(default_factory=list)
    open_exit_orders: list[OrderFact] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def model_position(self) -> int | None:
        """模型观察仓位;INCONSISTENT 时为 None(不得静默选择)。"""
        return MODEL_POSITION_MAP.get(self.state)

    @property
    def has_open_orders(self) -> bool:
        return bool(self.open_entry_orders or self.open_exit_orders)

    @property
    def is_fail_closed(self) -> bool:
        return self.state == INCONSISTENT

    def describe(self) -> str:
        lines = [
            f"执行状态: {self.state}(pair={self.pair})",
            f"实际成交暴露: {self.filled_amount!r}(已关闭订单汇总 {self.closed_amount!r})",
            f"活动入场单: {[f'{o.order_id} filled={o.filled}/fee_base={o.fee_base}/{o.amount}' for o in self.open_entry_orders]}",
            f"活动退出单: {[f'{o.order_id} filled={o.filled}/fee_base={o.fee_base}/{o.amount}' for o in self.open_exit_orders]}",
        ]
        for k, v in self.diagnostics.items():
            lines.append(f"诊断[{k}]: {v}")
        return "\n".join(lines)


def _order_fact(order: Any, entry_side: str) -> OrderFact:
    return OrderFact(
        order_id=str(order.order_id),
        side=str(order.ft_order_side),
        is_entry=order.ft_order_side == entry_side,
        status=order.status,
        amount=float(order.safe_amount),
        filled=float(order.safe_filled),
        remaining=float(order.safe_remaining),
        price=(float(order.safe_price) if order.safe_price is not None else None),
        cancel_reason=order.ft_cancel_reason,
        fee_base=float(order.safe_fee_base),
        filled_after_fee=float(order.safe_amount_after_fee),
    )


def resolve_execution_state(
    trades: Iterable[Any],
    pair: str,
    amount_epsilon: float = DEFAULT_AMOUNT_EPSILON,
) -> ExecutionSnapshot:
    """从 open trade 列表(生产路径 Trade.get_trades_proxy(is_open=True))解析执行状态。

    纯函数,无副作用:每次调用从 Trade/Order 当前状态重新推导,
    进程重启后以同一函数从数据库恢复(任务书十二节)。
    """
    eps = float(amount_epsilon)
    if eps <= 0:
        raise ValueError(f"amount_epsilon 必须为正,收到 {eps}")

    open_pair_trades = [
        t for t in trades
        if getattr(t, "is_open", False) and t.pair == pair
    ]
    snap = ExecutionSnapshot(state=FLAT, pair=pair)
    if not open_pair_trades:
        return snap
    if len(open_pair_trades) > 1:
        snap.state = INCONSISTENT
        snap.diagnostics["multiple_open_trades"] = [t.id for t in open_pair_trades]
        return snap

    trade = open_pair_trades[0]
    if getattr(trade, "is_short", False):
        snap.state = INCONSISTENT
        snap.diagnostics["short_trade"] = f"Long/Flat 项目出现空头 trade {trade.id}"
        return snap

    entry_side = trade.entry_side  # long -> "buy"
    orders = list(trade.open_orders)  # ft_is_open 且非 stoploss
    entry_orders = [_order_fact(o, entry_side) for o in orders if o.ft_order_side == entry_side]
    exit_orders = [
        _order_fact(o, entry_side) for o in orders if o.ft_order_side == trade.exit_side
    ]
    snap.open_entry_orders = entry_orders
    snap.open_exit_orders = exit_orders

    # ---- 订单自洽性校验(amount/filled/remaining/状态互相矛盾 -> INCONSISTENT)
    for o in entry_orders + exit_orders:
        if o.status in NON_OPEN_EXCHANGE_STATES:
            snap.state = INCONSISTENT
            snap.diagnostics[f"order_{o.order_id}"] = (
                f"活动订单(ft_is_open)状态却是非活动 {o.status}"
            )
            return snap
        if o.filled < 0 or o.remaining < 0:
            snap.state = INCONSISTENT
            snap.diagnostics[f"order_{o.order_id}"] = (
                f"负数数量 filled={o.filled} remaining={o.remaining}"
            )
            return snap
        if abs((o.filled + o.remaining) - o.amount) > max(eps, 1e-9 * abs(o.amount)):
            snap.state = INCONSISTENT
            snap.diagnostics[f"order_{o.order_id}"] = (
                f"filled+remaining={o.filled + o.remaining} != amount={o.amount}"
            )
            return snap
    if entry_orders and exit_orders:
        snap.state = INCONSISTENT
        snap.diagnostics["entry_and_exit_orders"] = "同一 trade 同时存在活动入场与退出订单"
        return snap
    if len(entry_orders) > 1 or len(exit_orders) > 1:
        snap.state = INCONSISTENT
        snap.diagnostics["multiple_active_orders"] = (
            f"活动入场单 {len(entry_orders)} 个 / 活动退出单 {len(exit_orders)} 个"
        )
        return snap

    # ---- 实际暴露:已关闭订单汇总 + 活动订单上的累计成交
    closed_amount = float(trade.amount or 0.0)
    # 阶段 2.5.2a 工作包 E:活动订单累计成交一律用 safe_amount_after_fee
    # (filled - ft_fee_base),与上游 recalc_trade_from_orders 的累计口径一致;
    # base 币手续费存在时不再高估暴露(quote 费率场景数值不变)。
    entry_open_filled = sum(o.filled_after_fee for o in entry_orders)
    exit_open_filled = sum(o.filled_after_fee for o in exit_orders)
    filled_amount = closed_amount + entry_open_filled - exit_open_filled
    snap.closed_amount = closed_amount
    snap.filled_amount = filled_amount

    exit_remaining = sum(o.remaining for o in exit_orders)

    if entry_orders:
        if filled_amount <= eps:
            snap.state = PENDING_ENTRY
        else:
            snap.state = PARTIAL_ENTRY
        return snap

    if exit_orders:
        if filled_amount > eps:
            snap.state = PENDING_EXIT if exit_open_filled <= eps else PARTIAL_EXIT
            return snap
        # 暴露已为零但退出单仍活动:剩余量是否为尘量
        if exit_remaining <= eps:
            snap.state = FLAT
            snap.diagnostics["exit_order_dust"] = (
                f"退出单剩余 {exit_remaining} <= epsilon,暴露已为零,等待订单清理"
            )
        else:
            snap.state = INCONSISTENT
            snap.diagnostics["exit_without_exposure"] = (
                f"退出单声称剩余 {exit_remaining} 但实际暴露为零"
            )
        return snap

    # ---- 无活动订单
    if filled_amount > eps:
        snap.state = LONG
    else:
        snap.state = FLAT
        snap.diagnostics["open_trade_zero_exposure"] = (
            f"open trade {getattr(trade, 'id', '?')} 暴露为零且无活动订单"
            "(已取消挂单后的瞬时残留,等待上游清理)"
        )
    return snap


def get_live_execution_snapshot(
    pair: str, amount_epsilon: float = DEFAULT_AMOUNT_EPSILON
) -> ExecutionSnapshot:
    """生产路径入口(仅 Dry-run / 实盘):从 Freqtrade Trade 持久层解析执行状态。

    与官方 BaseReinforcementLearningModel.get_state_info 相同的读取接口
    (Trade.get_trades_proxy(is_open=True))。
    """
    from freqtrade.persistence import Trade

    open_trades = Trade.get_trades_proxy(is_open=True)
    snap = resolve_execution_state(open_trades, pair, amount_epsilon=amount_epsilon)
    if snap.is_fail_closed:
        logger.error("执行状态 INCONSISTENT(fail closed):\n%s", snap.describe())
    else:
        logger.info(
            "RouteC 执行状态: %s(pair=%s, 暴露=%s)",
            snap.state, pair, snap.filled_amount,
        )
    return snap


def get_model_position_live(pair: str, amount_epsilon: float = DEFAULT_AMOUNT_EPSILON) -> int:
    """模型观察仓位(五节映射);INCONSISTENT 时抛错(fail closed,不静默选择)。"""
    snap = get_live_execution_snapshot(pair, amount_epsilon=amount_epsilon)
    if snap.is_fail_closed:
        raise InconsistentExecutionStateError(snap.describe())
    pos = snap.model_position
    assert pos is not None
    return pos


__all__ = [
    "ALL_STATES",
    "DEFAULT_AMOUNT_EPSILON",
    "ExecutionSnapshot",
    "InconsistentExecutionStateError",
    "MODEL_POSITION_MAP",
    "OrderFact",
    "get_live_execution_snapshot",
    "get_model_position_live",
    "resolve_execution_state",
]
