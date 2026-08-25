"""镜像 Freqtrade 2026.7 回测器对自定义价格的约束(阶段 2.5.1 工作包 C)。

固定 commit 52bc96f 的源码规则(多头/现货):

entry(backtesting.py get_valid_entry_price_and_stake):
    propose_rate = row[OPEN]
    new_rate = custom_entry_price(default=propose_rate)
    if new_rate != propose_rate:
        propose_rate = price_to_precision(new_rate)
    propose_rate = min(propose_rate, row[HIGH])   # 不得高于当根 high

exit_signal 族(backtesting.py _process_exit):
    close_rate = row[OPEN]
    rate = custom_exit_price(default=close_rate)
    if rate != close_rate:
        close_rate = rate                          # 注意:exit 侧无 precision 处理
    close_rate = max(close_rate, row[LOW])         # 不得低于当根 low

forced exit(handle_left_open):用最后一根 bar 的 open 平仓,不走 custom price,
不收滑点,正常扣手续费 —— 环境终端清算(ledger.liquidate)按同一口径实现。

价格精度(price_to_precision)说明:
- entry 侧对 custom 价应用交易所价格精度,exit 侧不应用(上游不对称);
- 本模块不模拟 precision 截断,其影响上界为 1 个价格 tick。
  测试用虚拟市场 precision=1e-8(影响 < 1e-8 相对),真实 BTC/USDT 市场
  tick=0.01(相对 ~1e-7,比 5bps 滑点小两个数量级),在主报告中记录。
"""

from __future__ import annotations


def clamp_entry_price(requested: float, high: float) -> float:
    """买入请求价按 Freqtrade 规则限制到当根 high 内(long)。"""
    if not (high > 0):
        raise ValueError(f"非法 high={high}")
    return min(requested, high)


def clamp_exit_price(requested: float, low: float) -> float:
    """卖出请求价按 Freqtrade 规则限制到当根 low 内(long)。"""
    if not (low > 0):
        raise ValueError(f"非法 low={low}")
    return max(requested, low)


def apply_slippage_with_clamp(
    side: str, raw_open: float, high: float, low: float, slippage_bps: float
) -> tuple[float, float, bool]:
    """确定性滑点 + Freqtrade 同等价格限制。

    :return: (最终成交价, 请求价, 是否被限制)
    """
    s = float(slippage_bps)
    if side == "buy":
        requested = raw_open * (1.0 + s / 10000.0)
        exec_price = clamp_entry_price(requested, high)
        return exec_price, requested, exec_price < requested
    if side == "sell":
        requested = raw_open * (1.0 - s / 10000.0)
        exec_price = clamp_exit_price(requested, low)
        return exec_price, requested, exec_price > requested
    raise ValueError(f"未知方向 {side!r}")
