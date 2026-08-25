"""Long/Flat 净值账本(阶段 2.5 路线 C 核心,2.5.1/2.5.2 加固)。

单步语义(任务书第六节的固定顺序):
1. 记录 close[t] 时的期初净值;
2. 旧仓位承担 close[t] -> open[t+1] 的价格跳空(由持仓自然实现,无需记账动作);
3. 在 open[t+1] 按目标仓位执行买卖(含确定性滑点);
4. 扣除手续费与滑点;
5. 新仓位承担 open[t+1] -> close[t+1] 的价格变化;
6. 得到 close[t+1] 时的期末净值。

费用口径(与 Freqtrade 2026.7 现货回测器一致):
- 买入: entry cost = amount * rate * (1 + fee)
  (backtesting.py Order.cost = amount * propose_rate * (1 + self.fee))
- 卖出: exit value = amount * rate * (1 - fee)
  (trade_model.py calc_close_trade_value = amount * rate * (1 - fee_close))
- profit_ratio = close_value / open_value - 1
  (trade_model.py calc_profit_ratio)

确定性滑点(基点表示):
- 买入请求价 = open[t+1] * (1 + slippage_bps / 10000)
- 卖出请求价 = open[t+1] * (1 - slippage_bps / 10000)

执行价格(阶段 2.5.2 工作包 D 执行合同,price_tick > 0 时):
- 使用 price_clamp.bar_executable_price:请求价触及当根 high/low 边界时
  按 tick 向 bar 内部移动至少一格(买入严格小于 high、卖出严格大于 low),
  保证回测器闭区间撮合语义下当根成交;bar 容纳不下内部价时 fallback open。
- price_tick == 0(未配置)时保留阶段 2.5.1 语义:仅 clamp 到边界,
  供旧配置与阶段 2.5/2.5.1 回归测试使用。

终端清算口径(阶段 2.5.1 起):
- Freqtrade 回测器对回测结束仍持仓的 trade 用最后一根 bar 的 open 平仓
  (handle_left_open),不走 custom price,不收滑点,只扣手续费;
- liquidate 与回测器对齐:按 raw_open 成交,无滑点,扣手续费。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rl_platform.price_clamp import apply_slippage_with_clamp, bar_executable_price


@dataclass
class TradeRecord:
    """一次成交的完整记账(用于 info 诊断与 CSV 审计)。"""

    direction: str  # "buy" / "sell" / "liquidate" / "hold"
    raw_open: float  # 执行 bar 的原始 open
    exec_price: float  # 滑点+限制后的实际成交价
    notional: float  # 成交名义金额(数量 * 成交价)
    fee_paid: float  # 手续费 = notional * fee
    slippage_cost: float  # 相对 raw_open 的滑点成本(数量 * |成交价 - raw_open|)
    qty: float  # 成交数量(BTC)
    cash_after: float
    btc_after: float
    requested_price: float | None = None  # 滑点后、限制前的请求价(None=未请求)
    price_clamped: bool = False  # 请求价是否被当根 high/low 限制
    price_moved_inside: bool = False  # 执行合同:是否向 bar 内部移动(阶段 2.5.2)
    price_fallback: bool = False  # 执行合同:bar 无法容纳内部价时是否 fallback open


@dataclass
class LongFlatLedger:
    """Long/Flat 现货净值账本:现金与 BTC 互斥(100% 或 0%)。

    买入:全部可用现金按成交价(执行合同价格)买入,
    手续费按名义金额计,约束 notional + fee = cash,
    即 qty = cash / (exec_price * (1 + fee))。
    卖出:全部 BTC 按成交价卖出,所得 = notional * (1 - fee)。
    """

    initial_cash: float = 100.0
    fee: float = 0.001
    slippage_bps: float = 0.0
    price_tick: float = 0.0  # 阶段 2.5.2 执行合同;0 = 旧边界 clamp 语义

    cash: float = field(init=False, default=0.0)
    btc: float = field(init=False, default=0.0)
    cost_basis: float = field(init=False, default=0.0)  # 当前持仓的买入现金成本
    realized_pnl: float = field(init=False, default=0.0)  # 累计已实现盈亏(现金口径)
    total_fees_paid: float = field(init=False, default=0.0)
    total_slippage_cost: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """完全清空状态(reset 后必须与全新实例等价)。"""
        self.cash = float(self.initial_cash)
        self.btc = 0.0
        self.cost_basis = 0.0
        self.realized_pnl = 0.0
        self.total_fees_paid = 0.0
        self.total_slippage_cost = 0.0

    @property
    def position(self) -> int:
        """当前实际仓位(目标仓位语义下二者一致)。"""
        return 1 if self.btc > 0 else 0

    def equity(self, price: float) -> float:
        """按给定价格计的总净值 = 现金 + BTC * price。"""
        return self.cash + self.btc * price

    def unrealized_pnl(self, price: float) -> float:
        """按 mark 价计的未实现盈亏(现金口径,卖出所得 - 买入成本)。"""
        if self.btc <= 0:
            return 0.0
        return self.btc * price * (1 - self.fee) - self.cost_basis

    def _buy_all(self, raw_open: float, high: float | None, low: float | None) -> TradeRecord:
        if self.price_tick > 0 and (high is None or low is None):
            raise ValueError("执行合同(price_tick>0)要求提供执行 bar 的 high 与 low")
        requested = raw_open * (1.0 + self.slippage_bps / 10000.0)
        if self.price_tick > 0:
            exec_price, _req, moved, fb = bar_executable_price(
                "buy", raw_open, high, low, self.slippage_bps, self.price_tick
            )
            clamped = exec_price != requested
        else:
            exec_price = requested if high is None else min(requested, high)
            clamped = high is not None and exec_price < requested
            moved, fb = False, False
        qty = self.cash / (exec_price * (1.0 + self.fee))
        notional = qty * exec_price
        fee_amt = notional * self.fee
        slip_cost = qty * (exec_price - raw_open)
        self.cost_basis = self.cash
        self.btc = qty
        self.cash = 0.0
        self.total_fees_paid += fee_amt
        self.total_slippage_cost += slip_cost
        return TradeRecord(
            direction="buy", raw_open=raw_open, exec_price=exec_price, notional=notional,
            fee_paid=fee_amt, slippage_cost=slip_cost, qty=qty,
            cash_after=self.cash, btc_after=self.btc,
            requested_price=requested, price_clamped=clamped,
            price_moved_inside=moved, price_fallback=fb,
        )

    def _sell_all(
        self, raw_open: float, low: float | None, high: float | None, direction: str = "sell"
    ) -> TradeRecord:
        if self.price_tick > 0 and (low is None or high is None):
            raise ValueError("执行合同(price_tick>0)要求提供执行 bar 的 low 与 high")
        requested = raw_open * (1.0 - self.slippage_bps / 10000.0)
        if self.price_tick > 0:
            exec_price, _req, moved, fb = bar_executable_price(
                "sell", raw_open, high, low, self.slippage_bps, self.price_tick
            )
            clamped = exec_price != requested
        else:
            exec_price = requested if low is None else max(requested, low)
            clamped = low is not None and exec_price > requested
            moved, fb = False, False
        notional = self.btc * exec_price
        fee_amt = notional * self.fee
        proceeds = notional - fee_amt
        slip_cost = self.btc * (raw_open - exec_price)
        self.cash += proceeds
        self.realized_pnl += proceeds - self.cost_basis
        self.total_fees_paid += fee_amt
        self.total_slippage_cost += slip_cost
        qty = self.btc
        self.btc = 0.0
        self.cost_basis = 0.0
        return TradeRecord(
            direction=direction, raw_open=raw_open, exec_price=exec_price, notional=notional,
            fee_paid=fee_amt, slippage_cost=slip_cost, qty=qty,
            cash_after=self.cash, btc_after=self.btc,
            requested_price=requested, price_clamped=clamped,
            price_moved_inside=moved, price_fallback=fb,
        )

    def apply_target(
        self,
        target: int,
        raw_open: float,
        high: float | None = None,
        low: float | None = None,
    ) -> TradeRecord:
        """在执行 bar 上把仓位调整到目标。

        幂等:重复目标不交易。high/low 为执行 bar 的当根高低价;
        price_tick>0 时走执行合同(bar 内一 tick),否则走阶段 2.5.1 边界 clamp。
        None 表示调用方不提供限制(纯账本单元测试用,生产路径必传)。
        """
        if target not in (0, 1):
            raise ValueError(f"目标仓位必须是 0 或 1,收到 {target}")
        if target == 1 and self.btc <= 0 and self.cash > 0:
            return self._buy_all(raw_open, high=high, low=low)
        if target == 0 and self.btc > 0:
            return self._sell_all(raw_open, low=low, high=high)
        # 重复目标或无资金:无成交、无费用
        return TradeRecord(
            direction="hold", raw_open=raw_open, exec_price=raw_open, notional=0.0,
            fee_paid=0.0, slippage_cost=0.0, qty=0.0,
            cash_after=self.cash, btc_after=self.btc,
        )

    def liquidate(self, raw_open: float) -> TradeRecord:
        """Episode 终端强制清算。

        与 Freqtrade 回测器 handle_left_open 对齐(阶段 2.5.1 口径修正):
        用最终执行 bar 的 open 成交,不收滑点,只扣手续费。
        """
        if self.btc > 0:
            qty = self.btc
            notional = qty * raw_open
            fee_amt = notional * self.fee
            proceeds = notional - fee_amt
            self.cash += proceeds
            self.realized_pnl += proceeds - self.cost_basis
            self.total_fees_paid += fee_amt
            self.btc = 0.0
            self.cost_basis = 0.0
            return TradeRecord(
                direction="liquidate", raw_open=raw_open, exec_price=raw_open,
                notional=notional, fee_paid=fee_amt, slippage_cost=0.0, qty=qty,
                cash_after=self.cash, btc_after=self.btc,
                requested_price=raw_open, price_clamped=False,
            )
        return TradeRecord(
            direction="hold", raw_open=raw_open, exec_price=raw_open, notional=0.0,
            fee_paid=0.0, slippage_cost=0.0, qty=0.0,
            cash_after=self.cash, btc_after=self.btc,
        )
