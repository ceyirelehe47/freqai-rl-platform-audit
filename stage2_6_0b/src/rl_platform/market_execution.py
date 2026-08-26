"""阶段 2.5.2a 因果市场成交合同(execution_mode = market_open_causal)。

时间语义(阶段 2.5.2a 任务书第一节冻结):
    K 线 t 完整收盘 -> 模型观察所有截至 t 的信息 -> 输出目标仓位
    -> 在 open[t+1] 形成市场成交 -> 新仓位承担 open[t+1] -> close[t+1]
    -> 得到 close[t+1] 时的净值与奖励。

有效成交价只依赖(任务书第一节白名单):
    open[t+1]、交易方向、执行前已固定的 simulated_slippage_bps、
    执行前已固定的价格 tick、手续费配置。

本模块的函数签名与实现均不接收、不读取执行 K 线的 high/low/close
或任何后续 K 线(不得依赖"订单是否会被 K 线覆盖")。

有效成交价公式(方向不利的 tick 取整):
    买入: effective_price = ceil_to_tick(open * (1 + simulated_slippage_bps / 10000))
    卖出: effective_price = floor_to_tick(open * (1 - simulated_slippage_bps / 10000))
取整规则: 买入向上、卖出向下;不使用 round-half-even;取整不得改善成交价格。

simulated_slippage_bps 语义:
    预先设定的有效市场冲击/滑点压力参数,只属于训练与离线压力环境;
    不是历史 K 线中的真实限价成交价格,也不要求位于该根 K 线 high/low 内。
    Freqtrade live 使用交易所真实回报价格,simulated_slippage_bps 不改变
    live 市场订单价格(阶段 2.5.2a 任务书第九节边界声明)。

本模块取代阶段 2.5.2 的 bar_executable_price 执行合同;旧合同
(legacy_noncausal_not_for_training)保留在 price_clamp.py 仅供历史
回归测试,不得进入训练/生产调用路径。
"""

from __future__ import annotations

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any

EXECUTION_MODE = "market_open_causal"
LEGACY_EXECUTION_MODE = "legacy_noncausal_not_for_training"
TICK_ROUNDING_VERSION = "side_aware_ceil_floor_v1"
VALID_EXECUTION_MODES = (EXECUTION_MODE, LEGACY_EXECUTION_MODE)


def _to_decimal(value: float) -> Decimal:
    try:
        d = Decimal(str(float(value)))
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ValueError(f"价格/tick 数值非法: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"价格/tick 数值非有限: {value!r}")
    return d


def ceil_to_tick(price: float, price_tick: float) -> float:
    """向上取整到 tick 整数格(买入方向不利)。price_tick<=0 表示不量化。"""
    tick = _to_decimal(price_tick)
    if tick <= 0:
        return float(price)
    ticks = (_to_decimal(price) / tick).to_integral_value(rounding=ROUND_CEILING)
    return float(ticks * tick)


def floor_to_tick(price: float, price_tick: float) -> float:
    """向下取整到 tick 整数格(卖出方向不利)。price_tick<=0 表示不量化。"""
    tick = _to_decimal(price_tick)
    if tick <= 0:
        return float(price)
    ticks = (_to_decimal(price) / tick).to_integral_value(rounding=ROUND_FLOOR)
    return float(ticks * tick)


def _validate_inputs(
    raw_open: float, simulated_slippage_bps: float, price_tick: float
) -> tuple[float, float, float]:
    raw_open = float(raw_open)
    simulated_slippage_bps = float(simulated_slippage_bps)
    price_tick = float(price_tick)
    if not math.isfinite(raw_open) or raw_open <= 0.0:
        raise ValueError(f"raw_open 必须为正有限数,收到 {raw_open!r}")
    if not math.isfinite(simulated_slippage_bps) or simulated_slippage_bps < 0.0:
        raise ValueError(
            f"simulated_slippage_bps 必须为非负有限数,收到 {simulated_slippage_bps!r}"
        )
    if not math.isfinite(price_tick) or price_tick < 0.0:
        raise ValueError(f"price_tick 必须为非负有限数,收到 {price_tick!r}")
    return raw_open, simulated_slippage_bps, price_tick


def market_fill(
    side: str, raw_open: float, simulated_slippage_bps: float, price_tick: float
) -> tuple[float, dict[str, Any]]:
    """因果市场成交:返回 (有效成交价, 成交诊断)。

    买入向上取整、卖出向下取整到 tick 整数格;取整只可能让成交价
    对交易者更不利,否则视为内部错误(fail closed)。
    """
    side = str(side).lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"side 必须是 buy/sell,收到 {side!r}")
    raw_open, bps, tick = _validate_inputs(raw_open, simulated_slippage_bps, price_tick)
    if side == "buy":
        requested = raw_open * (1.0 + bps / 10000.0)
        effective = ceil_to_tick(requested, tick)
        rounding = "ceil" if tick > 0 and effective != requested else "none"
        actual_bps = (effective / raw_open - 1.0) * 10000.0
        if effective < requested - 1e-12:
            raise RuntimeError(
                f"买入 tick 取整改善了成交价(effective={effective} < requested={requested})"
            )
    else:
        requested = raw_open * (1.0 - bps / 10000.0)
        effective = floor_to_tick(requested, tick)
        rounding = "floor" if tick > 0 and effective != requested else "none"
        actual_bps = (1.0 - effective / raw_open) * 10000.0
        if effective > requested + 1e-12:
            raise RuntimeError(
                f"卖出 tick 取整改善了成交价(effective={effective} > requested={requested})"
            )
    if not math.isfinite(effective) or effective <= 0.0:
        raise ValueError(
            f"有效成交价必须为正有限数(side={side}, effective={effective!r})"
        )
    diagnostics: dict[str, Any] = {
        "direction": side,
        "raw_open": raw_open,
        "requested_price": requested,
        "effective_price": effective,
        "requested_slippage_bps": bps,
        "actual_effective_slippage_bps": actual_bps,
        "tick_rounding": rounding,
        "price_tick": tick,
        "rounded": rounding != "none",
        "tick_rounding_version": TICK_ROUNDING_VERSION,
    }
    return effective, diagnostics


def buy_market_price(
    raw_open: float, simulated_slippage_bps: float, price_tick: float
) -> tuple[float, dict[str, Any]]:
    """买入有效成交价 = ceil_to_tick(open * (1 + simulated_slippage_bps/10000))。"""
    return market_fill("buy", raw_open, simulated_slippage_bps, price_tick)


def sell_market_price(
    raw_open: float, simulated_slippage_bps: float, price_tick: float
) -> tuple[float, dict[str, Any]]:
    """卖出有效成交价 = floor_to_tick(open * (1 - simulated_slippage_bps/10000))。"""
    return market_fill("sell", raw_open, simulated_slippage_bps, price_tick)
