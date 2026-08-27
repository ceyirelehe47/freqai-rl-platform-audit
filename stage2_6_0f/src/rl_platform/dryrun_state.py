"""Dry-run / 实盘执行状态读取(阶段 2.5 路线 C,阶段 2.5.2 工作包 A 重写)。

阶段 2.5/2.5.1 的实现把「存在 is_open=True 的非空头 Trade」直接当作多头,
无法识别零成交挂单、部分成交与待退出订单 —— 阶段 2.5.2 起废除该简化,
统一委托 rl_platform.execution_state.resolve_execution_state 从真实
Trade/Order 状态解析七态执行状态,再按映射表给出模型观察仓位。

本模块保留两个历史入口(阶段 2.5/2.5.1 测试与文档兼容):
- resolve_initial_position(trades, pair):整数仓位;INCONSISTENT 时报错;
- get_initial_position_live(pair):生产路径,Trade.get_trades_proxy 读取。
新代码应直接使用 execution_state.get_live_execution_snapshot / get_model_position_live。

不使用官方 add_state_info(其回测不可用,上一阶段审计 §15)。
本模块只读 Trade/Order 状态,不下单、不连接真实账户。
"""

from __future__ import annotations

import logging

from rl_platform.execution_state import (
    DEFAULT_AMOUNT_EPSILON,
    InconsistentExecutionStateError,
    resolve_execution_state,
)

logger = logging.getLogger(__name__)


def resolve_initial_position(
    trades: list, pair: str, amount_epsilon: float = DEFAULT_AMOUNT_EPSILON
) -> int:
    """从 open trade 列表解析模型观察仓位(兼容入口,阶段 2.5.2 起按七态映射)。

    FLAT/PENDING_ENTRY -> 0;PARTIAL_ENTRY/LONG/PENDING_EXIT/PARTIAL_EXIT -> 1;
    INCONSISTENT(含空头暴露等冲突)-> 抛 RuntimeError,fail closed。
    """
    snap = resolve_execution_state(trades, pair, amount_epsilon=amount_epsilon)
    if snap.is_fail_closed:
        raise RuntimeError(snap.describe())
    pos = snap.model_position
    assert pos is not None
    return pos


def get_initial_position_live(pair: str) -> int:
    """生产路径入口(仅 Dry-run / 实盘调用):从 Trade/Order 表解析模型观察仓位。"""
    from rl_platform.execution_state import get_model_position_live

    try:
        position = get_model_position_live(pair)
    except InconsistentExecutionStateError as exc:
        # 保持阶段 2.5 的对外行为:冲突状态显式报错而不是静默
        raise RuntimeError(str(exc)) from exc
    logger.info("Dry-run/实盘顺序推理仓位: %s (pair=%s)", position, pair)
    return position
