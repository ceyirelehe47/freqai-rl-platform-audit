"""镜像 Freqtrade 2026.7 回测器对自定义价格的约束(阶段 2.5.1 工作包 C,
阶段 2.5.2 工作包 D 升级为「bar 内保证可成交」执行合同)。

固定 commit 52bc96f 的源码规则(多头/现货):

entry(optimize/backtesting.py get_valid_entry_price_and_stake):
    propose_rate = row[OPEN]
    new_rate = custom_entry_price(default=propose_rate)
    if new_rate != propose_rate:
        propose_rate = price_to_precision(new_rate)
    propose_rate = min(propose_rate, row[HIGH])   # 不得高于当根 high

exit_signal 族(_get_exit_for_signal -> _exit_trade):
    close_rate = row[OPEN]
    rate = custom_exit_price(default=close_rate)
    if rate != close_rate: close_rate = rate
    close_rate = max(close_rate, row[LOW])        # 不得低于当根 low
    close_rate = price_to_precision(close_rate)   # _exit_trade 内

回测器撮合(_get_order_filled / _try_close_open_order,backtest_loop 步骤 3/5):
    low <= rate <= high (闭区间)即视为当根成交

阶段 2.5.2 执行合同(任务书十三节,推荐方案):
    请求滑点价触及当根 high/low 边界时,按价格精度向 bar 内部移动至少一个
    tick,使最终限价严格落在 bar 内部(买入严格小于 high、卖出严格大于 low),
    从而在回测器闭区间撮合语义下保证下单当根成交 —— 环境与回测器两侧使用
    同一公共执行价格函数,不再出现「恰等边界价依赖后续 bar 解析」的分叉。
    bar 范围本身容纳不下内部价(如零振幅/单 tick 十字星)时,fallback 为
    当根 open(依据上述源码:entry=min(rate,high)、exit=max(rate,low) 均允许
    边界价,闭区间撮合下 open∈[low,high] 恒当根成交),并记录 fallback 事实。

价格精度说明:
    所有边界移动在 tick 整数格上进行(k_high-1 / k_low+1),输出价格是 tick
    的整数倍;上游 price_to_precision 对已是 tick 整数倍的价格是恒等变换
    (浮点尘埃 << 半 tick),因此 custom 价经回测器精度化后与函数输出一致。
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
    """确定性滑点 + Freqtrade 同等价格限制(阶段 2.5.1 语义,兼容保留)。

    阶段 2.5.2 起生产路径(环境与策略)改用 bar_executable_price;
    本函数保留给未配置价格精度的旧配置与阶段 2.5/2.5.1 回归测试。

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


def _snap(price: float, tick: float) -> int:
    """把价格对齐到 tick 整数格(round-half-even,与 decimal ROUND 一致)。"""
    return int(round(price / tick))


def bar_executable_price(
    side: str,
    raw_open: float,
    high: float,
    low: float,
    slippage_bps: float,
    price_tick: float,
) -> tuple[float, float, bool, bool]:
    """阶段 2.5.2 执行合同:bar 内保证可成交的限价(工作包 D)。

    规则(环境与 RouteCStrategy 使用同一函数):
    1. 请求价 = open*(1±bps/10000)(0bps 时直接返回 open,镜像回测器
       「custom 价 == propose 时不做精度化」的恒等路径);
    2. 请求价对齐到 tick 整数格后仍触及边界(k>=k_high 买入 / k<=k_low 卖出)
       时,向 bar 内部移动一个 tick(k_high-1 / k_low+1);
    3. 移动后越出 bar 另一侧(bar 范围容纳不下内部价)时 fallback 为 open;
    4. 正常路径(未触及边界)直接使用对齐后的请求价。

    :return: (最终成交价, 请求价, 是否向bar内移动, 是否fallback)
    """
    if float(price_tick) <= 0:
        raise ValueError(f"执行合同要求 price_tick > 0,收到 {price_tick}")
    if not (low > 0 and high >= low):
        raise ValueError(f"非法 bar: low={low}, high={high}")
    s = float(slippage_bps)
    if s == 0.0:
        # 0bps:与回测器恒等路径一致(custom 价 == open -> 不精度化、不移动)
        return float(raw_open), float(raw_open), False, False

    k_open = _snap(raw_open, price_tick)
    k_high = _snap(high, price_tick)
    k_low = _snap(low, price_tick)
    tick = float(price_tick)

    def _canon(k: int) -> float:
        # k*tick 的算术浮点可能与 price_to_precision 的十进制往返结果相差 1 ulp;
        # 在恰等边界的闭区间撮合下这足以让订单滞留。规范化(round 10 位,
        # tick <= 1e-8 时仍保真)保证两侧与回测器精度化输出是同一浮点。
        return round(k * tick, 10)

    if side == "buy":
        requested = raw_open * (1.0 + s / 10000.0)
        k_req = _snap(requested, tick)
        if k_req < k_high:
            return _canon(k_req), requested, False, False
        k_exec = k_high - 1
        if k_exec < k_low:
            # bar 容纳不下合法内部价 -> fallback open(open∈[low,high] 恒可成交)
            return _canon(k_open), requested, True, True
        return _canon(k_exec), requested, True, False
    if side == "sell":
        requested = raw_open * (1.0 - s / 10000.0)
        k_req = _snap(requested, tick)
        if k_req > k_low:
            return _canon(k_req), requested, False, False
        k_exec = k_low + 1
        if k_exec > k_high:
            return _canon(k_open), requested, True, True
        return _canon(k_exec), requested, True, False
    raise ValueError(f"未知方向 {side!r}")


__all__ = [
    "apply_slippage_with_clamp",
    "bar_executable_price",
    "clamp_entry_price",
    "clamp_exit_price",
]
