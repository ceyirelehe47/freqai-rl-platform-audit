"""Dry-run / 实盘初始化状态读取(阶段 2.5 路线 C)。

顺序推理器启动时需要当前目标仓位。回测中初始为 0;
Dry-run / 实盘中必须从 Freqtrade 的真实 Trade 状态读取:
- 无 open trade -> 0;
- 存在该 pair 的 open 多头 trade -> 1。

不使用官方 add_state_info(其回测不可用,上一阶段审计 §15)。
本模块只读 Trade 状态,不下单、不连接真实账户。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def resolve_initial_position(trades: list[Any], pair: str) -> int:
    """从 open trade 列表解析当前目标仓位。

    :param trades: 具有 is_open / pair / is_short 属性的 trade 对象列表
                   (生产路径传 Trade.get_trades_proxy(is_open=True) 的结果)。
    :param pair: 交易对,如 "BTC/USDT"。
    """
    for trade in trades:
        if not getattr(trade, "is_open", False):
            continue
        if trade.pair != pair:
            continue
        if getattr(trade, "is_short", False):
            # 阶段 2.5 禁用做空;出现空头持仓说明配置漂移,显式报错而不是静默忽略
            raise RuntimeError(f"{pair} 存在空头持仓,与 Long/Flat 环境配置冲突")
        return 1
    return 0


def get_initial_position_live(pair: str) -> int:
    """生产路径入口(仅 Dry-run / 实盘调用):从 Freqtrade Trade 表读取。

    依赖 freqtrade.persistence.Trade.get_trades_proxy(公开接口,
    官方 BaseReinforcementLearningModel.get_state_info 同款调用方式)。
    """
    from freqtrade.persistence import Trade

    open_trades = Trade.get_trades_proxy(is_open=True)
    position = resolve_initial_position(open_trades, pair)
    logger.info("Dry-run/实盘顺序推理初始目标仓位: %s (pair=%s)", position, pair)
    return position
