"""工作包 B/E:模拟滑点压力测试(环境侧,不声称 Freqtrade parity)。

simulated_slippage_bps > 0 时只验证:
- 成交价公式(买入 ceil / 卖出 floor);
- 成本单调性(每笔成本随 bps 单调不减);
- 最终净值单调性(0 -> 5 -> 10 bps 严格下降);
- 报告边界:Freqtrade live 使用交易所真实回报价格,simulated_slippage_bps
  只属于训练与离线压力环境。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from legal_ohlc import make_legal_candles
from rl_platform.env import AlignedLongFlatEnv
from rl_platform.market_execution import buy_market_price, sell_market_price

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"

TARGETS = [0, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0]


def episode_final(df, bps, *, fee=0.001, price_tick=0.01):
    env = AlignedLongFlatEnv(
        features=pd.DataFrame({"f": np.zeros(len(df))}),
        prices=df[["open", "high", "low", "close"]],
        fee=fee, slippage_bps=bps, price_tick=price_tick,
    )
    env.reset()
    infos = []
    done = False
    i = 0
    while not done:
        _, _, term, _, info = env.step(TARGETS[i % len(TARGETS)])
        infos.append(info)
        done = term
        i += 1
    return env, infos


def test_slippage_formula_and_monotone_cost():
    df = make_legal_candles("wide", 20)
    per_trade_costs = {0.0: [], 5.0: [], 10.0: []}
    finals = {}
    for bps in (0.0, 5.0, 10.0):
        env, infos = episode_final(df, bps)
        finals[bps] = env.ledger.cash
        for info in infos:
            if info["trade_direction"] in ("buy", "sell", "liquidate"):
                # 每笔成本 = 手续费 + 滑点成本
                per_trade_costs[bps].append(
                    info["fee_paid"] + info["slippage_cost"])
    # 成本单调不减(逐笔配对,同数据同动作序列,只差滑点)
    for c0, c5, c10 in zip(per_trade_costs[0.0], per_trade_costs[5.0],
                           per_trade_costs[10.0], strict=True):
        assert c5 >= c0 - 1e-15
        assert c10 >= c5 - 1e-15
    # 最终净值单调下降
    assert finals[0.0] > finals[5.0] > finals[10.0]


def test_formula_exact_directional_quotes():
    for o in (100.0, 100.03, 99.97, 5432.10):
        p5, _ = buy_market_price(o, 5.0, 0.01)
        p10, _ = buy_market_price(o, 10.0, 0.01)
        assert p10 >= p5 >= o
        s5, _ = sell_market_price(o, 5.0, 0.01)
        s10, _ = sell_market_price(o, 10.0, 0.01)
        assert s10 <= s5 <= o
        if o == 100.0:  # 恰在网格上的精确值
            assert p5 == pytest.approx(100.05)
            assert p10 == pytest.approx(100.10)
            assert s5 == pytest.approx(99.95)
            assert s10 == pytest.approx(99.90)


def test_monotonicity_evidence():
    df = make_legal_candles("wide", 20)
    finals = {}
    for bps in (0.0, 5.0, 10.0):
        env, _ = episode_final(df, bps)
        finals[str(bps)] = env.ledger.cash
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "simulated_slippage_monotonicity.json").write_text(
        json.dumps({
            "claim": "环境侧公式与成本/净值单调性;不声称 Freqtrade 已精确复现",
            "final_cash_by_bps": finals,
            "monotone_decreasing": finals["0.0"] > finals["5.0"] > finals["10.0"],
            "formula": {
                "buy": "ceil_to_tick(open * (1 + simulated_slippage_bps/10000))",
                "sell": "floor_to_tick(open * (1 - simulated_slippage_bps/10000))",
            },
            "boundary_statement": (
                "Freqtrade live 使用交易所真实回报价格;simulated_slippage_bps "
                "只属于训练与离线压力环境,不改变 live 市场订单价格"
            ),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    assert finals["0.0"] > finals["5.0"] > finals["10.0"]
