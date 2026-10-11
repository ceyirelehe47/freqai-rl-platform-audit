# -*- coding: utf-8 -*-
"""双向现金结算线性合约账本(RouteC_PositionControl W1)。

研究交易载体(第一版工程默认,不宣称对齐任何交易所):
- 单资产线性合约,报价/抵押统一一种计价货币;合约数量有正负;
- 逐步盯市现金结算:cash 只因已实现损益/手续费/资金费变动;
  equity(P) = cash + qty * (P - avg_entry);
- 自融资推导:在成交价 x(方向不利滑点+tick 取整)成交带符号增量
  δ = q_new - q_old,手续费 = |δ| * x * fee。减仓/反手的减仓腿
  实现损益 realized = -closed_signed * (x - avg_entry);加仓腿按
  成交价加权移动 avg_entry;反手翻转后 avg_entry = x。唯一不变式:
  成交前后 equity(x) 只差手续费(滑点已在 x 内),无凭空资金。
- 目标比例求解(扣费后口径):请求 w(带符号,|w|<=1),以执行 bar
  原始 open 为统一标记价,e = equity(open) 为成交前净值,
  E_after = e - δ*(x - open) - |δ|*x*fee。要求
  q_new * open = w * E_after。对固定方向,方程对 q_new 线性:
      q_new = w * (e + c*q_old) / (open + w*c)
  其中买入(δ>0) c = x*(1+fee) - open;卖出(δ<0) c = x*(1-fee) - open。
  先按方向假设解出 q_new,再验证符号一致;解与假设矛盾时换支,
  两支都矛盾则 q_new == q_old(无需交易)。tick 取整使 x 离散化时,
  实际达成比例与请求的残差如实记录。
- HOLD:数量不变,不收费,无后台目标;比例随价格漂移可超 ±1,
  观察值不截断。
- 资金费:预定 bar 的 close 按标记价结算,payment = qty*close*rate
  (rate>0 时空头收、多头付)。缺失资金费输入按 0 处理时如实标注
  funding_missing=True,不冒充真实零成本研究。
- 非正净值:不 clamp;调用方(env)显式经济失败终结。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _round_adverse(price: float, tick: float, is_buy: bool) -> float:
    """方向不利取整:买入向上取整到 tick,卖出向下取整。tick<=0 原样。"""
    if tick <= 0.0:
        return price
    n = price / tick
    k = math.ceil(n - 1e-9) if is_buy else math.floor(n + 1e-9)
    return k * tick


@dataclass
class FillRecord:
    """一次成交的完整记账(审计原件)。"""

    kind: str            # "rebalance" / "hold" / "liquidate" / "risk_flatten"
    raw_mark: float      # 统一标记价(执行 bar 原始 open 或风险检查价)
    exec_price: float    # 滑点+取整后的实际成交价
    signed_qty: float    # δ = q_new - q_old(带符号)
    fee: float           # |δ| * exec_price * fee_rate
    realized_pnl: float  # 减仓腿已实现损益(含反手减仓腿)
    qty_before: float
    qty_after: float
    avg_entry_before: float
    avg_entry_after: float
    equity_before_at_mark: float
    equity_after_at_mark: float
    requested_ratio: float | None = None   # 请求 w(HOLD/清算为 None)
    achieved_ratio: float | None = None    # 成交后实际比例(同标记价)
    residual: float | None = None          # achieved - requested
    infeasible_reason: str | None = None   # 求解不可行时的如实记录


@dataclass
class TwoSidedLinearLedger:
    """现金结算线性合约净值账本(隔离离线研究仿真)。"""

    initial_cash: float = 100.0
    fee_rate: float = 0.001
    slippage_bps: float = 0.0
    price_tick: float = 0.0

    cash: float = field(init=False, default=0.0)
    qty: float = field(init=False, default=0.0)
    avg_entry: float = field(init=False, default=0.0)
    realized_pnl_cum: float = field(init=False, default=0.0)
    fees_total: float = field(init=False, default=0.0)
    funding_total: float = field(init=False, default=0.0)
    funding_events: int = field(init=False, default=0)
    fills: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.cash = self.initial_cash
        self.qty = 0.0
        self.avg_entry = 0.0
        self.realized_pnl_cum = 0.0
        self.fees_total = 0.0
        self.funding_total = 0.0
        self.funding_events = 0
        self.fills = []

    # ------------------------------------------------------ valuation
    def equity(self, price: float) -> float:
        return self.cash + self.qty * (price - self.avg_entry)

    def exposure_ratio(self, price: float) -> float:
        """带符号敞口比例 = qty*price/equity;equity<=0 时未定义(交由
        调用方经济失败处理,不截断、不 clamp)。"""
        e = self.equity(price)
        if e <= 0.0:
            return math.inf if self.qty > 0 else (
                -math.inf if self.qty < 0 else 0.0)
        return self.qty * price / e

    def solvency_ratio(self, price: float) -> float:
        """偿付余量 = equity / |qty|*price(空仓=inf;<=0 失败)。"""
        n = abs(self.qty) * price
        if n <= 0.0:
            return math.inf
        return self.equity(price) / n

    def _exec_price(self, raw: float, is_buy: bool) -> float:
        slip = raw * (1.0 + self.slippage_bps / 10000.0) if is_buy else \
            raw * (1.0 - self.slippage_bps / 10000.0)
        return _round_adverse(slip, self.price_tick, is_buy)

    # ------------------------------------------------------ trades
    def _apply_fill(self, q_new: float, x: float, raw_mark: float,
                    kind: str, requested: float | None) -> FillRecord:
        avg_before = self.avg_entry
        q_old = self.qty
        delta = q_new - q_old
        fee = abs(delta) * x * self.fee_rate
        realized = 0.0
        if q_old != 0.0 and delta != 0.0:
            if delta * q_old < 0.0:
                closed = -math.copysign(min(abs(delta), abs(q_old)), q_old)
                realized = -closed * (x - self.avg_entry)
            # 纯加仓无已实现损益
        e_before = self.cash + q_old * (raw_mark - self.avg_entry)
        avg_after = self.avg_entry
        if q_new != 0.0:
            same_side = q_old != 0.0 and (q_new * q_old) > 0.0
            if abs(q_new) > abs(q_old) and same_side:
                avg_after = (self.avg_entry * abs(q_old)
                             + x * (abs(q_new) - abs(q_old))) / abs(q_new)
            elif not same_side:
                avg_after = x
        else:
            avg_after = 0.0
        self.cash += realized - fee
        self.realized_pnl_cum += realized
        self.fees_total += fee
        self.qty = q_new
        self.avg_entry = avg_after
        e_after = self.equity(raw_mark)
        rec = FillRecord(
            kind=kind, raw_mark=raw_mark, exec_price=x, signed_qty=delta,
            fee=fee, realized_pnl=realized, qty_before=q_old,
            qty_after=q_new,
            avg_entry_before=avg_before,
            avg_entry_after=avg_after,
            equity_before_at_mark=e_before,
            equity_after_at_mark=e_after,
            requested_ratio=requested)
        if raw_mark > 0.0 and e_after > 0.0:
            rec.achieved_ratio = self.exposure_ratio(raw_mark)
            rec.residual = (rec.achieved_ratio - requested
                            if requested is not None else None)
        self.fills.append(rec)
        return rec

    # ------------------------------------------------------ target solve
    def _solve_q_new(self, w: float, raw_open: float) -> tuple:
        """按扣费后口径解目标数量;返回 (q_new, exec_price, direction)。

        direction ∈ {"buy","sell","none"};两支线性解都不自洽时
        (唯一可能是浮点极端或 w 恰等于当前比例)返回 no-trade。
        分母/分子非正(偿付不足以支撑该请求)时 raise ValueError,
        由调用方按经济失败/拒绝处理,不静默缩小仓位。
        """
        e = self.equity(raw_open)
        if e <= 0.0:
            raise ValueError(
                f"成交前净值非正({e}),目标比例求解未定义")
        q_old = self.qty

        def solve_with(c: float):
            den = raw_open + w * c
            num = w * (e + c * q_old)
            if den <= 0.0:
                return None
            return num / den

        # 先试与 w 同号的增量方向(w 相对当前比例加仓侧),再试对侧
        cur_ratio = q_old * raw_open / e
        first_buy = w > cur_ratio
        for is_buy in (first_buy, not first_buy):
            x = self._exec_price(raw_open, is_buy)
            c = x * (1.0 + self.fee_rate) - raw_open if is_buy else \
                x * (1.0 - self.fee_rate) - raw_open
            q_new = solve_with(c)
            if q_new is None:
                continue
            delta = q_new - q_old
            if (is_buy and delta > 0.0) or (
                    not is_buy and delta < 0.0):
                return q_new, x, ("buy" if is_buy else "sell")
            if abs(delta) <= 1e-12 * max(1.0, abs(q_old)):
                return q_old, x, "none"
        # 两支矛盾:当前比例已等于目标(含 fee 精确抵消)或浮点极端
        return q_old, self._exec_price(raw_open, True), "none"

    def apply_target_ratio(self, w: float, raw_open: float,
                           kind: str = "rebalance") -> FillRecord:
        """把敞口调整到目标比例 w(|w|<=1;扣费后口径精确求解)。"""
        if not (math.isfinite(w) and -1.0 <= w <= 1.0):
            raise ValueError(
                f"非法目标比例 {w!r}:必须为 [-1,1] 内有限数")
        q_new, x, direction = self._solve_q_new(float(w), raw_open)
        if direction == "none":
            rec = FillRecord(
                kind=kind, raw_mark=raw_open, exec_price=x,
                signed_qty=0.0, fee=0.0, realized_pnl=0.0,
                qty_before=self.qty, qty_after=self.qty,
                avg_entry_before=self.avg_entry,
                avg_entry_after=self.avg_entry,
                equity_before_at_mark=self.equity(raw_open),
                equity_after_at_mark=self.equity(raw_open),
                requested_ratio=float(w),
                achieved_ratio=self.exposure_ratio(raw_open),
                residual=(self.exposure_ratio(raw_open) - float(w)))
            self.fills.append(rec)
            return rec
        return self._apply_fill(q_new, x, raw_open, kind, float(w))

    def hold(self, raw_mark: float) -> FillRecord:
        """HOLD:数量不变,无成交费/滑点;浮动损益由估值自然体现。"""
        e = self.equity(raw_mark)
        rec = FillRecord(
            kind="hold", raw_mark=raw_mark, exec_price=raw_mark,
            signed_qty=0.0, fee=0.0, realized_pnl=0.0,
            qty_before=self.qty, qty_after=self.qty,
            avg_entry_before=self.avg_entry,
            avg_entry_after=self.avg_entry,
            equity_before_at_mark=e, equity_after_at_mark=e,
            requested_ratio=None,
            achieved_ratio=self.exposure_ratio(raw_mark))
        self.fills.append(rec)
        return rec

    def settle_funding(self, price: float, rate: float) -> float:
        """资金费结算:payment = qty*price*rate(多头 qty>0 付正 rate)。

        返回带符号支付额(负=账户支出)。空仓或 rate==0 不产生事件。
        """
        payment = -self.qty * price * rate
        if payment != 0.0:
            self.cash += payment
            self.funding_total += payment
            self.funding_events += 1
        return payment

    def liquidate(self, reference_price: float) -> FillRecord:
        """终端/风险清算:全部平仓,方向不利滑点+取整+费用照常。"""
        if self.qty == 0.0:
            return self.hold(reference_price)
        is_buy = self.qty < 0.0   # 平空头=买入
        x = self._exec_price(reference_price, is_buy)
        return self._apply_fill(0.0, x, reference_price,
                                "liquidate", None)

    def risk_flatten(self, reference_price: float) -> FillRecord:
        """预定风险规则触发的一次性全额平仓(risk action,区别于
        模型动作;同样支付全部摩擦)。"""
        if self.qty == 0.0:
            return self.hold(reference_price)
        is_buy = self.qty < 0.0
        x = self._exec_price(reference_price, is_buy)
        return self._apply_fill(0.0, x, reference_price,
                                "risk_flatten", None)
