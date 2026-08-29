"""工作包 C 测试:Episode 终端退出支付完整成本(无免费退出漏洞)。

阶段 2.5.2a 终端语义:最后一个执行周期结束于 close[last] ->
以 close[last] 为清算基准价,使用与普通市场卖出完全相同的
simulated_slippage_bps、tick 取整(floor)、卖出手续费 -> 最终全部现金。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from legal_ohlc import make_legal_candles
from rl_platform.env import AlignedLongFlatEnv
from rl_platform.ledger import LongFlatLedger
from rl_platform.market_execution import floor_to_tick, sell_market_price

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"


def make_env(prices_df, *, fee=0.001, slippage_bps=5.0, price_tick=0.01):
    env = AlignedLongFlatEnv(
        features=pd.DataFrame({"f": np.zeros(len(prices_df))}),
        prices=prices_df[["open", "high", "low", "close"]] if "high" in prices_df
        else prices_df[["open", "close"]],
        fee=fee, slippage_bps=slippage_bps, price_tick=price_tick,
    )
    env.reset()
    return env


def run(env, actions):
    infos = []
    done = False
    i = 0
    while not done:
        _, _, term, _, info = env.step(actions[i % len(actions)])
        infos.append(info)
        done = term
        i += 1
    return infos


def const_prices(n, price=100.0):
    return pd.DataFrame({
        "open": [price] * n, "high": [price] * n,
        "low": [price] * n, "close": [price] * n,
    })


def test_constant_price_normal_vs_terminal_same_cost():
    """1) 恒定价格:普通退出与终端退出使用完全相同的成本。"""
    # 情形 A:买入后中途卖出(最后决策步 action=0)
    n = 10
    env_a = make_env(const_prices(n))
    acts_a = [1] * (n - 2) + [0]
    infos_a = run(env_a, acts_a)
    sell_info = [i for i in infos_a if i["trade_direction"] == "sell"][-1]
    # 情形 B:买入持有到终点,强制清算
    env_b = make_env(const_prices(n))
    infos_b = run(env_b, [1])
    liq = infos_b[-1]["terminal_liquidation"]
    # 相同买入(exec=ceil(100*1.0005)=100.05) -> 相同持仓数量
    buy_a = [i for i in infos_a if i["trade_direction"] == "buy"][0]
    buy_b = [i for i in infos_b if i["trade_direction"] == "buy"][0]
    assert buy_a["exec_price"] == pytest.approx(buy_b["exec_price"])
    assert buy_a["qty"] == pytest.approx(buy_b["qty"])
    # 卖出成本完全一致:同价、同费率、同滑点公式
    assert sell_info["exec_price"] == pytest.approx(liq["exec_price"])  # 都 99.95
    assert sell_info["fee_paid"] == pytest.approx(liq["fee_paid"])
    assert sell_info["qty"] == pytest.approx(liq["qty"])
    per_unit_a = sell_info["fee_paid"] / sell_info["notional"]
    per_unit_b = liq["fee_paid"] / liq["notional"]
    assert per_unit_a == pytest.approx(per_unit_b)
    assert liq["slippage_cost"] > 0, "终端清算必须支付滑点"


def test_exit_one_step_before_end():
    """2) 倒数第二步正常退出:最后决策步卖出,无终端清算记录。"""
    n = 8
    env = make_env(const_prices(n))
    infos = run(env, [1] * (n - 2) + [0])
    last = infos[-1]
    assert last["trade_direction"] == "sell"
    assert last["btc"] == 0.0
    # 卖出后已全现金,终端清算为 hold(不重复收费)
    liq = last.get("terminal_liquidation")
    assert liq is None or liq["qty"] == 0.0


def test_hold_to_end_forced_liquidation():
    """3) 持有到终点被强制退出:清算发生在 close 后,基准价 = close[last]。"""
    n = 9
    p = const_prices(n, price=120.0)
    env = make_env(p)
    infos = run(env, [1])
    last = infos[-1]
    liq = last["terminal_liquidation"]
    assert liq["direction"] == "liquidate"
    assert liq["reference_price"] == pytest.approx(p["close"].iloc[-1])  # close[last]
    expected_exec = floor_to_tick(120.0 * (1 - 5.0 / 10000.0), 0.01)
    assert liq["exec_price"] == pytest.approx(expected_exec)  # 119.94
    assert last["btc"] == 0.0
    assert last["cash"] == pytest.approx(env.ledger.cash)


def test_same_price_same_cost_both_paths():
    """4) 同一价格下两条路径单位成本一致(买/卖/清算三向核对)。"""
    n = 12
    prices = const_prices(n, price=100.0)
    env = make_env(prices)
    acts = [1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 0]  # 中途有普通卖出
    infos = run(env, acts)
    normal_sells = [i for i in infos if i["trade_direction"] == "sell"]
    liq = infos[-1].get("terminal_liquidation")
    assert normal_sells
    # 终点仍持仓(最后决策 0? 序列最后为 0 -> 已卖出;构造强制:最后决策 1)
    env2 = make_env(prices)
    infos2 = run(env2, [1])
    liq2 = infos2[-1]["terminal_liquidation"]
    for s in normal_sells:
        assert s["exec_price"] == pytest.approx(liq2["exec_price"])
        assert (s["fee_paid"] / s["notional"]) == pytest.approx(
            liq2["fee_paid"] / liq2["notional"])
    # 买入方向成本同样发生(ceil 取整)
    buys = [i for i in infos if i["trade_direction"] == "buy"]
    assert all(b["exec_price"] == pytest.approx(100.05) for b in buys)


def test_terminal_equity_monotone_in_slippage():
    """5) slippage 0 -> 5 -> 10 bps:终端最终净值单调下降。"""
    finals = []
    for bps in (0.0, 5.0, 10.0):
        env = make_env(make_legal_candles("wide", 16), slippage_bps=bps)
        infos = run(env, [1])  # 第一步买入后持有到底
        finals.append(env.ledger.cash)
    assert finals[0] > finals[1] > finals[2], finals
    (ART / "terminal_liquidation_parity.json").write_text(
        json.dumps({
            "monotone_final_cash_by_slippage": {
                "bps0": finals[0], "bps5": finals[1], "bps10": finals[2],
            },
            "same_cost_as_normal_sell": True,
            "liquidation_price_formula":
                "floor_to_tick(close[last] * (1 - simulated_slippage_bps/10000))",
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def test_last_step_new_long_pays_both_sides():
    """6) 最后一步新开多头:买入成本 + 清算卖出成本 + 双边手续费。"""
    n = 7
    env = make_env(const_prices(n), slippage_bps=5.0)
    acts = [0] * (n - 2) + [1]  # 一直空仓,最后决策才买入
    infos = run(env, acts)
    last = infos[-1]
    assert last["trade_direction"] == "buy"
    assert last["fee_paid"] > 0
    assert last["slippage_cost"] > 0  # 买入价 100.05 > open 100
    liq = last["terminal_liquidation"]
    assert liq["direction"] == "liquidate"
    assert liq["fee_paid"] > 0
    assert liq["slippage_cost"] > 0  # 清算价 99.95 < close 100
    # 买 100.05 卖 99.95:单轮往返成本严格为负收益
    assert last["cash"] < 100.0


def test_no_free_ride_at_random_horizon():
    """7) 随机 Episode 长度:终点强制退出的单位成本与普通卖出一致,
    不存在"持有到固定终点可以免费退出"的套利。"""
    rng = np.random.default_rng(2026)
    for trial in range(10):
        n = int(rng.integers(8, 40))
        df = make_legal_candles("wide", n, seed=int(rng.integers(0, 10000)))
        # 持有到底:清算单位成本
        env_t = make_env(df)
        infos_t = run(env_t, [1])
        liq = infos_t[-1]["terminal_liquidation"]
        expect_exec, expect_diag = sell_market_price(
            df["close"].iloc[-1], 5.0, 0.01)
        assert liq["exec_price"] == pytest.approx(expect_exec), trial
        assert liq["fee_paid"] / liq["notional"] == pytest.approx(0.001)
        # 与普通卖出(同 episode 中发生的)单位成本一致
        env_n = make_env(df)
        acts = [1] * (n - 2) + [0]
        infos_n = run(env_n, acts)
        sell = [i for i in infos_n if i["trade_direction"] == "sell"][-1]
        assert (sell["fee_paid"] / sell["notional"]) == pytest.approx(
            liq["fee_paid"] / liq["notional"])
        # telescoping 不因 horizon 随机而破坏
        assert env_n.episode_reward_raw == pytest.approx(
            np.log(env_n.ledger.cash / 100.0), abs=1e-10)
        assert env_t.episode_reward_raw == pytest.approx(
            np.log(env_t.ledger.cash / 100.0), abs=1e-10)


def test_ledger_liquidate_matches_sell_market_price():
    """ledger 层直查:liquidate 与 _sell_all 同公式同费率。"""
    for ref in (100.0, 99.97, 123.45):
        led_a = LongFlatLedger(fee=0.001, slippage_bps=5.0, price_tick=0.01)
        led_a.cash = 1000.0
        led_b = LongFlatLedger(fee=0.001, slippage_bps=5.0, price_tick=0.01)
        led_b.cash = 1000.0
        led_a.btc = 2.0
        led_b.btc = 2.0
        liq = led_a.liquidate(ref)
        sold = led_b._sell_all(ref)
        assert liq.exec_price == pytest.approx(sold.exec_price)
        assert liq.fee_paid == pytest.approx(sold.fee_paid)
        assert liq.slippage_cost == pytest.approx(sold.slippage_cost)
        assert led_a.cash == pytest.approx(led_b.cash)
        assert liq.direction == "liquidate"
