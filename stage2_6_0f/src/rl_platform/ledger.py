"""Long/Flat 净值账本(阶段 2.5 路线 C 核心,2.5.1/2.5.2/2.5.2a 加固)。

单步语义(任务书第六节的固定顺序):
1. 记录 close[t] 时的期初净值;
2. 旧仓位承担 close[t] -> open[t+1] 的价格跳空(由持仓自然实现,无需记账动作);
3. 在 open[t+1] 按目标仓位执行买卖(含确定性模拟滑点);
4. 扣除手续费与滑点;
5. 新仓位承担 open[t+1] -> close[t+1] 的价格变化;
6. 得到 close[t+1] 时的期末净值。

阶段 2.5.2a 执行合同(execution_mode = market_open_causal,任务书第一节):
- 成交价只依赖 open[t+1]、方向、执行前已固定的 simulated_slippage_bps、
  价格 tick 与手续费;不依赖执行 K 线的 high/low(因果成交);
- 买入 ceil_to_tick 向上取整,卖出 floor_to_tick 向下取整
  (方向不利取整,禁止 round-half-even);
- 终端清算与普通市场卖出使用完全相同的 simulated_slippage_bps、
  tick 取整与卖出手续费,清算基准价为 close[last](清算发生在最后
  一根 K 线收盘后),不存在"持有到 Episode 结束可以免滑点"的漏洞;
- reward telescoping: sum(reward_raw) == log(final_cash / initial_cash)。

旧执行路径(legacy_noncausal_not_for_training,阶段 2.5.2 bar 内调价合同):
- 依赖执行 K 线最终 high/low 反向修改成交价以保证当根成交,
  违反因果成交语义(未来信息泄漏),仅保留供历史回归测试显式选择,
  不得用于训练/生产;阶段 2.5.2 的窄 K 线 parity 报告仅作历史研究记录。

费用口径(与 Freqtrade 2026.7 现货回测器一致):
- 买入: entry cost = amount * rate * (1 + fee)
  (backtesting.py Order.cost = amount * propose_rate * (1 + self.fee))
- 卖出: exit value = amount * rate * (1 - fee)
  (trade_model.py calc_close_trade_value = amount * rate * (1 - fee_close))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rl_platform.market_execution import (
    EXECUTION_MODE,
    LEGACY_EXECUTION_MODE,
    VALID_EXECUTION_MODES,
    buy_market_price,
    sell_market_price,
)
from rl_platform.price_clamp import apply_slippage_with_clamp, bar_executable_price


@dataclass
class TradeRecord:
    """一次成交的完整记账(用于 info 诊断与 CSV 审计)。"""

    direction: str  # "buy" / "sell" / "liquidate" / "hold"
    raw_open: float  # 执行基准价(causal: 执行 bar 的 open;liquidate: close[last])
    exec_price: float  # 有效成交价(滑点+tick 取整后)
    notional: float  # 成交名义金额(数量 * 成交价)
    fee_paid: float  # 手续费 = notional * fee
    slippage_cost: float  # 相对 raw_open 的滑点成本(数量 * |成交价 - raw_open|)
    qty: float  # 成交数量(BTC)
    cash_after: float
    btc_after: float
    requested_price: float | None = None  # 滑点后、tick 取整前的请求价
    price_clamped: bool = False  # legacy:请求价是否被当根 high/low 限制
    price_moved_inside: bool = False  # legacy(2.5.2):是否向 bar 内部移动
    price_fallback: bool = False  # legacy(2.5.2):是否 fallback open
    tick_rounding: str | None = None  # causal: ceil / floor / none
    actual_effective_slippage_bps: float | None = None  # causal:实际有效滑点(基点)

    def market_fill_diagnostics(self) -> dict[str, Any]:
        """causal 成交诊断(info 契约,阶段 2.5.2a 工作包 A)。"""
        return {
            "direction": self.direction,
            "raw_open": self.raw_open,
            "effective_price": self.exec_price,
            "requested_price": self.requested_price,
            "requested_slippage_bps": None,  # 由 ledger 层补充
            "actual_effective_slippage_bps": self.actual_effective_slippage_bps,
            "tick_rounding": self.tick_rounding,
            "fee_paid": self.fee_paid,
        }


@dataclass
class LongFlatLedger:
    """Long/Flat 现货净值账本:现金与 BTC 互斥(100% 或 0%)。

    买入:全部可用现金按有效成交价买入,手续费按名义金额计,
    约束 notional + fee = cash,即 qty = cash / (exec_price * (1 + fee))。
    卖出:全部 BTC 按有效成交价卖出,所得 = notional * (1 - fee)。

    execution_mode:
    - market_open_causal(默认,生产/训练唯一允许):
      buy_market_price / sell_market_price,不接收执行 K 线 high/low;
    - legacy_noncausal_not_for_training:阶段 2.5.2 bar 内调价合同,
      仅历史回归测试显式选择。
    """

    initial_cash: float = 100.0
    fee: float = 0.001
    # 模拟环境专用确定性滑点(= 配置键 freqai.route_c.simulated_slippage_bps)
    slippage_bps: float = 0.0
    price_tick: float = 0.0
    execution_mode: str = EXECUTION_MODE

    cash: float = field(init=False, default=0.0)
    btc: float = field(init=False, default=0.0)
    cost_basis: float = field(init=False, default=0.0)  # 当前持仓的买入现金成本
    realized_pnl: float = field(init=False, default=0.0)  # 累计已实现盈亏(现金口径)
    total_fees_paid: float = field(init=False, default=0.0)
    total_slippage_cost: float = field(init=False, default=0.0)

    def __post_init__(self) -> None:
        if self.execution_mode not in VALID_EXECUTION_MODES:
            raise ValueError(
                f"execution_mode 必须是 {VALID_EXECUTION_MODES} 之一,收到 {self.execution_mode!r}"
            )
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

    # ------------------------------------------------------- 记账内核(共用)
    def _settle_buy(
        self,
        exec_price: float,
        raw_open: float,
        requested: float,
        tick_rounding: str | None,
        actual_bps: float | None,
        clamped: bool = False,
        moved: bool = False,
        fb: bool = False,
    ) -> TradeRecord:
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
            tick_rounding=tick_rounding, actual_effective_slippage_bps=actual_bps,
        )

    def _settle_sell(
        self,
        exec_price: float,
        raw_open: float,
        requested: float,
        direction: str,
        tick_rounding: str | None,
        actual_bps: float | None,
        clamped: bool = False,
        moved: bool = False,
        fb: bool = False,
    ) -> TradeRecord:
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
            tick_rounding=tick_rounding, actual_effective_slippage_bps=actual_bps,
        )

    # ------------------------------------------- market_open_causal 生产路径
    def _buy_all(self, raw_open: float) -> TradeRecord:
        exec_price, diag = buy_market_price(raw_open, self.slippage_bps, self.price_tick)
        return self._settle_buy(
            exec_price, raw_open, diag["requested_price"],
            diag["tick_rounding"], diag["actual_effective_slippage_bps"],
        )

    def _sell_all(self, raw_open: float, direction: str = "sell") -> TradeRecord:
        exec_price, diag = sell_market_price(raw_open, self.slippage_bps, self.price_tick)
        return self._settle_sell(
            exec_price, raw_open, diag["requested_price"], direction,
            diag["tick_rounding"], diag["actual_effective_slippage_bps"],
        )

    def apply_target(self, target: int, raw_open: float) -> TradeRecord:
        """market_open_causal:在 open[t+1] 把仓位调整到目标(不接收 high/low)。

        幂等:重复目标不交易。成交价由 market_execution 决定。
        """
        if target not in (0, 1):
            raise ValueError(f"目标仓位必须是 0 或 1,收到 {target}")
        if target == 1 and self.btc <= 0 and self.cash > 0:
            return self._buy_all(raw_open)
        if target == 0 and self.btc > 0:
            return self._sell_all(raw_open)
        return self._hold_record(raw_open)

    def liquidate(self, reference_price: float) -> TradeRecord:
        """Episode 终端强制清算(market_open_causal,阶段 2.5.2a 工作包 C)。

        清算基准价为 close[last](清算发生在最后一根 K 线收盘后):
        最后一根 K 线内的持仓先承担 open -> close 收益,再以
        floor_to_tick(close * (1 - simulated_slippage_bps/10000)) 卖出,
        支付与普通市场卖出完全相同的滑点、tick 取整与手续费。
        """
        if self.btc > 0:
            exec_price, diag = sell_market_price(
                reference_price, self.slippage_bps, self.price_tick
            )
            return self._settle_sell(
                exec_price, reference_price, diag["requested_price"], "liquidate",
                diag["tick_rounding"], diag["actual_effective_slippage_bps"],
            )
        return self._hold_record(reference_price)

    def _hold_record(self, raw_open: float) -> TradeRecord:
        return TradeRecord(
            direction="hold", raw_open=raw_open, exec_price=raw_open, notional=0.0,
            fee_paid=0.0, slippage_cost=0.0, qty=0.0,
            cash_after=self.cash, btc_after=self.btc,
        )

    # -------------------------- legacy_noncausal_not_for_training(历史测试专用)
    def _buy_all_legacy(self, raw_open: float, high: float | None, low: float | None) -> TradeRecord:
        """阶段 2.5.2 bar 内调价合同:依赖执行 bar 最终 high/low(非因果)。"""
        if self.price_tick > 0 and (high is None or low is None):
            raise ValueError("legacy 执行合同(price_tick>0)要求提供执行 bar 的 high 与 low")
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
        return self._settle_buy(
            exec_price, raw_open, requested, None, None,
            clamped=clamped, moved=moved, fb=fb,
        )

    def _sell_all_legacy(
        self, raw_open: float, low: float | None, high: float | None, direction: str = "sell"
    ) -> TradeRecord:
        """阶段 2.5.2 bar 内调价合同:依赖执行 bar 最终 low/high(非因果)。"""
        if self.price_tick > 0 and (low is None or high is None):
            raise ValueError("legacy 执行合同(price_tick>0)要求提供执行 bar 的 low 与 high")
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
        return self._settle_sell(
            exec_price, raw_open, requested, direction, None, None,
            clamped=clamped, moved=moved, fb=fb,
        )

    def apply_target_legacy(
        self,
        target: int,
        raw_open: float,
        high: float | None = None,
        low: float | None = None,
    ) -> TradeRecord:
        """legacy_noncausal_not_for_training:阶段 2.5.2 执行合同(仅供历史测试)。"""
        if target not in (0, 1):
            raise ValueError(f"目标仓位必须是 0 或 1,收到 {target}")
        if target == 1 and self.btc <= 0 and self.cash > 0:
            return self._buy_all_legacy(raw_open, high=high, low=low)
        if target == 0 and self.btc > 0:
            return self._sell_all_legacy(raw_open, low=low, high=high)
        return self._hold_record(raw_open)

    def liquidate_legacy(self, raw_open: float) -> TradeRecord:
        """legacy 终端清算:免滑点只收手续费(阶段 2.5.2a 起仅历史测试使用)。"""
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
        return self._hold_record(raw_open)
