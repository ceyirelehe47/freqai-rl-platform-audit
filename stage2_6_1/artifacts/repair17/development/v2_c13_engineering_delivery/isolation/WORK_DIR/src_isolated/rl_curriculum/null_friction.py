"""阶段 2.6.0e 工作包 A:冻结账本真实往返摩擦的唯一可审计来源。

2.6.0d 及更早使用的错误公式:

    1 - (1 - fee)^2 * (1 - slippage)^2      # fee=0.001, slip=0 -> 0.001999

与冻结账本(rl_platform.ledger.LongFlatLedger +
rl_platform.market_execution 的 market_open_causal 成交合同)不一致:
错误公式把"卖出按名义额扣费"误当成"买卖各打一次 (1-fee) 折"。

冻结账本的真实语义:

    买入: qty = cash / [buy_exec_price  * (1 + fee)]
    卖出: final_cash = qty * sell_exec_price * (1 - fee)
    buy_exec_price  = P * (1 + s)(+ 方向不利 tick 取整)
    sell_exec_price = P * (1 - s)(+ 方向不利 tick 取整)

买卖使用同一 raw reference price P、price_tick = 0 时,一次完整往返的
现金保留比例为:

    retention = [(1 - f) / (1 + f)] * [(1 - s) / (1 + s)]

真实完整往返摩擦(单一实现来源,qualification margin 只能取自这里):

    friction = 1 - [(1 - f) / (1 + f)] * [(1 - s) / (1 + s)]

fee=0.001、slippage=0 时 = 0.002 / 1.001 = 0.001998001998...(不是
旧公式的 0.001999,更不是硬编码的 0.002)。

单位(A1):与 EpisodeResult.net_return 相同的 simple-return 单位
(final_cash / initial_cash - 1 的差值尺度;retention 本身就是该比值,
friction 是它的 1-补)。

price_tick 语义(A3):方向不利 tick 取整(买 ceil / 卖 floor)只会使
真实成交价更不利,因此 tick=0 的 closed-form friction 是任意
price_tick >= 0 配置的保守下界,同时是 qualification margin 的硬上限。
该性质在本模块由真实执行函数(LongFlatLedger.apply_target / liquidate
-> market_fill -> ceil_to_tick / floor_to_tick)在预注册参数网格上实证
(friction_parity_problems),不得只写注释;网格任一组合违反性质时,
qualification spec 的构建/验证必须失败。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

FRICTION_CONTRACT_FORMAT = "null-friction-contract-v2"

#: 冻结账本语义下的精确 closed-form 公式(字符串进入 qualification spec
#: 与资格报告的对账;单一来源,禁止在别处复制)
LEDGER_ROUND_TRIP_FORMULA = (
    "1 - [(1 - fee) / (1 + fee)] * [(1 - slippage) / (1 + slippage)]")

#: 预注册 parity 网格(A3:大量正价格 / tick / fee / slippage 组合)
PARITY_GRID_PRICES: tuple[float, ...] = (
    0.0001, 0.37, 1.0, 4.25, 100.0, 3600.5, 100000.0,
)
PARITY_GRID_TICKS: tuple[float, ...] = (0.0, 0.00001, 0.01, 0.1, 1.0, 25.0)
PARITY_GRID_FEES: tuple[float, ...] = (0.0, 0.0005, 0.001, 0.0025, 0.01)
PARITY_GRID_SLIPPAGES: tuple[float, ...] = (0.0, 0.0005, 0.001, 0.005)
#: tick=0 时 closed-form 与真实账本往返的浮点对齐容差
PARITY_TICK_ZERO_ATOL = 1e-12


def ledger_round_trip_retention(fee: float, slippage: float) -> float:
    """同一 raw reference price 一次完整往返后的现金保留比例。

    由冻结账本买卖公式精确推导(qty = cash / (P(1+s)(1+f));
    final_cash = qty * P(1-s)(1-f)),price_tick = 0。
    """
    f = float(fee)
    s = float(slippage)
    if f < 0.0 or s < 0.0:
        raise ValueError(f"fee/slippage 必须非负,收到 fee={f!r}, slip={s!r}")
    return ((1.0 - f) / (1.0 + f)) * ((1.0 - s) / (1.0 + s))


def ledger_round_trip_friction(fee: float, slippage: float) -> float:
    """冻结账本真实完整往返摩擦(tick=0 精确 closed form)。

    fee=0.001、slippage=0 时 = 0.002/1.001 = 0.001998001998...。
    """
    return 1.0 - ledger_round_trip_retention(fee, slippage)


def actual_round_trip_friction(
    *, fee: float, slippage_bps: float, price_tick: float,
    reference_price: float, exit: str = "market",
    initial_cash: float = 100.0,
) -> float:
    """用真实 LongFlatLedger + market_execution 做一次平价往返。

    在同一 raw reference price 上买满 -> 平卖(exit="market")或终端
    清算(exit="liquidate",基准价与普通卖出相同的滑点/tick/手续费),
    返回 1 - final_cash/initial_cash(simple-return 单位)。tick 取整只
    可能进一步恶化成交价,因此该值 >= tick=0 的 closed-form friction。
    """
    from rl_platform.ledger import LongFlatLedger

    if exit not in ("market", "liquidate"):
        raise ValueError(f"exit 必须是 market/liquidate,收到 {exit!r}")
    led = LongFlatLedger(
        initial_cash=float(initial_cash), fee=float(fee),
        slippage_bps=float(slippage_bps), price_tick=float(price_tick),
    )
    led.apply_target(1, float(reference_price))
    if exit == "market":
        led.apply_target(0, float(reference_price))
    else:
        led.liquidate(float(reference_price))
    if led.cash <= 0.0:
        raise RuntimeError("平价往返后现金非正(账本状态异常)")
    return 1.0 - led.cash / float(initial_cash)


def _admissible(price: float, tick: float, slip: float) -> bool:
    """预注册可采纳性:价格至少一个 tick,且滑点后卖出价仍 >= 一个
    tick(否则 floor_to_tick 把有效成交价取整为 0,执行合同本身
    fail-closed——该组合不是可交易的市场配置,不计入 parity 网格;
    保守起见同样要求买入侧可表达)。"""
    return price >= tick and price * (1.0 - slip) >= tick \
        and price * (1.0 + slip) >= tick


def friction_parity_problems() -> list[str]:
    """预注册网格上的真实执行 parity 校验(A3,不得只写注释)。

    - tick = 0:市场卖出与终端清算两条路径的 actual friction 都必须与
      closed-form 在浮点容差内相等(交叉验证公式与账本语义一致);
    - tick > 0:actual friction 必须不小于 closed-form(方向不利取整的
      保守下界性质)。违反 -> 返回问题清单(qualification spec 构建失败)。
    """
    problems: list[str] = []
    for price in PARITY_GRID_PRICES:
        for tick in PARITY_GRID_TICKS:
            if not _admissible(price, tick, max(PARITY_GRID_SLIPPAGES)):
                continue
            for fee in PARITY_GRID_FEES:
                for slip in PARITY_GRID_SLIPPAGES:
                    if not _admissible(price, tick, slip):
                        continue
                    closed = ledger_round_trip_friction(fee, slip)
                    kw = dict(fee=fee, slippage_bps=slip * 1e4,
                              price_tick=tick, reference_price=price)
                    actual_m = actual_round_trip_friction(exit="market", **kw)
                    actual_l = actual_round_trip_friction(
                        exit="liquidate", **kw)
                    if tick <= 0.0:
                        for label, actual in (("market", actual_m),
                                              ("liquidation", actual_l)):
                            if abs(actual - closed) > PARITY_TICK_ZERO_ATOL:
                                problems.append(
                                    f"tick=0 parity 失败[{label}]:"
                                    f"P={price} fee={fee} slip={slip} "
                                    f"actual={actual!r} != closed={closed!r}")
                    else:
                        for label, actual in (("market", actual_m),
                                              ("liquidation", actual_l)):
                            if actual < closed - PARITY_TICK_ZERO_ATOL:
                                problems.append(
                                    f"保守下界性质失败[{label}]:P={price} "
                                    f"tick={tick} fee={fee} slip={slip} "
                                    f"actual={actual!r} < closed={closed!r}")
    return problems


def friction_parity_report() -> dict[str, Any]:
    """parity 证据(进入 artifacts;spec 验证引用其判定而非其内容)。"""
    problems = friction_parity_problems()
    admissible = sum(
        1
        for price in PARITY_GRID_PRICES
        for tick in PARITY_GRID_TICKS
        for slip in PARITY_GRID_SLIPPAGES
        if _admissible(price, tick, slip)
    )
    n_fee = len(PARITY_GRID_FEES)
    n_combos = admissible * n_fee
    return {
        "format": FRICTION_CONTRACT_FORMAT,
        "formula": LEDGER_ROUND_TRIP_FORMULA,
        "units": "simple_return",
        "admissibility_rule": (
            "P >= tick 且 P*(1±s) >= tick(价格至少一个 tick;不可采纳"
            "组合的卖出有效价会被 floor_to_tick 取整为 0,执行合同本身"
            "fail-closed,不构成可交易市场配置)"),
        "n_admissible_slip_tick_price_combos": admissible,
        "n_combinations": n_combos,
        "n_execution_paths": 2,
        "n_round_trips": n_combos * 2,
        "tick_zero_atol": PARITY_TICK_ZERO_ATOL,
        "problems": problems,
        "pass": not problems,
        "example_fee_0p001_slip_0": ledger_round_trip_friction(0.001, 0.0),
        "legacy_wrong_formula_value": 1.0 - (1.0 - 0.001) ** 2,
    }


def friction_contract_code_hash() -> str:
    """本模块内容哈希(进入 qualification spec 的 margin_derivation:
    摩擦合同实现变化 -> spec hash 变化 -> 旧承诺全部失效)。"""
    src = Path(inspect.getsourcefile(ledger_round_trip_friction))  # type: ignore[arg-type]
    return "nfc-" + hashlib.sha256(src.read_bytes()).hexdigest()


def friction_contract_payload() -> dict[str, Any]:
    """可规范化摩擦合同摘要(测试与 artifacts 使用)。"""
    return {
        "format": FRICTION_CONTRACT_FORMAT,
        "formula": LEDGER_ROUND_TRIP_FORMULA,
        "units": "simple_return",
        "code_hash": friction_contract_code_hash(),
        "ledger_semantics": {
            "buy": "qty = cash / (buy_exec_price * (1 + fee))",
            "sell": "final_cash = qty * sell_exec_price * (1 - fee)",
            "slippage": "buy P*(1+s) / sell P*(1-s)",
            "tick": "buy ceil_to_tick / sell floor_to_tick(方向不利)",
            "source_modules": ["rl_platform.ledger", "rl_platform.market_execution"],
        },
        "parity_grid": {
            "prices": list(PARITY_GRID_PRICES),
            "ticks": list(PARITY_GRID_TICKS),
            "fees": list(PARITY_GRID_FEES),
            "slippages": list(PARITY_GRID_SLIPPAGES),
        },
    }


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
