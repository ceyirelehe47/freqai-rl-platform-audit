"""环境与 Freqtrade 回测器的时间与价格对齐测试(任务书十九节)。

同一锯齿人工数据、同一目标仓位变化(决策行 0 看多 -> 行 5 转空):
- 环境侧:AlignedLongFlatEnv 逐步 step(目标序列 [1]*6 + [0]*23);
- 回测侧:真实 Backtesting.start()(虚拟市场 monkeypatch,测试级),
  固定信号策略 enter 写在行 0、exit 写在行 5。

预期(两侧都是"信息截至 t -> open[t+1] 成交"):
- entry/exit 时间与价格完全一致(01:00@110 / 06:00@100);
- 单笔收益率精确一致:两侧公式均为 q2*(1-f)/(q1*(1+f)) - 1;
- 零费终值一致(仅 amount 精度截断误差);
- 有费终值差异 = W*f*(1-R)(freqtrade 的 stake=amount*rate 不为买入费预留,
  环境按现金覆盖成本约束预留,闭式推导见 test 中 expected_wallet_diff)。
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from freqai_rl_stage2_5.util import ZIGZAG, build_env, make_ohlc, make_values  # noqa: E402

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5"
N = 30
TARGETS = [1] * 5 + [0] * 24  # 决策行 0-4 持多,行 5 转空 -> 卖在 open[6](06:00)

FAKE_MARKETS = {
    "SYN/USDT": {
        "symbol": "SYN/USDT", "base": "SYN", "quote": "USDT",
        "spot": True, "swap": False, "future": False, "active": True,
        # 极细精度,把 amount/price 截断误差压到 1e-9 相对量级以下
        "precision": {"price": 1e-8, "amount": 1e-8},
        "limits": {
            "amount": {"min": 1e-8, "max": None},
            "cost": {"min": 1e-8, "max": None},
            "leverage": {"max": 1},
        },
        "info": {},
    }
}

STRAT_TMPL = '''from pandas import DataFrame
from freqtrade.strategy import IStrategy


class {cls}(IStrategy):
    """阶段 2.5 对齐测试用固定信号策略(非 RL)。非生产用途。"""

    minimal_roi = {{"0": 100}}
    stoploss = -0.99
    startup_candle_count = 0
    can_short = False
    timeframe = "1h"
    process_only_new_candles = True
    position_adjustment_enable = False
    order_types = {{"entry": "limit", "exit": "limit",
                    "stoploss": "market", "stoploss_on_exchange": False}}

    SLIP = {slip}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["date"].dt.strftime("%Y-%m-%dT%H:%M") == "2026-06-01T00:00",
               ["enter_long", "enter_tag"]] = (1, "fixed")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df.loc[df["date"].dt.strftime("%Y-%m-%dT%H:%M") == "2026-06-01T05:00",
               "exit_long"] = 1
        return df

    def custom_entry_price(self, pair, trade, current_time, proposed_rate,
                           entry_tag, side, **kwargs):
        return proposed_rate * (1 + self.SLIP)

    def custom_exit_price(self, pair, trade, current_time, proposed_rate,
                          current_profit, exit_tag, **kwargs):
        return proposed_rate * (1 - self.SLIP)
'''


def run_env_side(fee: float, slippage_bps: float) -> dict:
    values = make_values("zigzag", N)
    env = build_env(values, fee=fee, slippage_bps=slippage_bps)
    env.reset()
    infos = []
    for a in TARGETS:
        _, _, terminated, _, info = env.step(a)
        infos.append(info)
        if terminated:
            break
    buys = [i for i in infos if i["trade_direction"] == "buy"]
    sells = [i for i in infos if i["trade_direction"] == "sell"]
    assert len(buys) == 1 and len(sells) == 1
    buy, sell = buys[0], sells[0]
    final = infos[-1]["equity_end"]
    return {
        "entry_time": str(buy["execution_time"]), "entry_price": buy["exec_price"],
        "exit_time": str(sell["execution_time"]), "exit_price": sell["exec_price"],
        "final_equity": final,
        "single_trade_return": sell["cash"] / 100.0 - 1.0,
        "n_trades": 2,
    }


def run_bt_side(fee: float, slippage_bps: float, with_slip_strat: bool) -> dict:
    values = make_values("zigzag", N)
    if with_slip_strat:
        # 给 high/low 留出滑点余量(custom_entry_price 会被 clamp 到当根 high)
        ohlc = make_ohlc(values)
        ohlc["high"] = ohlc["open"] * (1 + 1.5 * slippage_bps / 10000.0)
        ohlc["low"] = ohlc["open"] * (1 - 1.5 * slippage_bps / 10000.0)
    else:
        ohlc = make_ohlc(values)

    with tempfile.TemporaryDirectory() as tmp:
        strat_dir = os.path.join(tmp, "strategies")
        data_dir = os.path.join(tmp, "data", "binanceus")
        os.makedirs(strat_dir)
        os.makedirs(data_dir)
        cls = "FixedTargetAlign"
        with open(os.path.join(strat_dir, f"{cls}.py"), "w") as f:
            f.write(STRAT_TMPL.format(cls=cls, slip=slippage_bps / 10000.0))
        ohlc.to_feather(os.path.join(data_dir, "SYN_USDT-1h.feather"))

        import freqtrade.exchange as ftx
        from freqtrade.optimize.backtesting import Backtesting

        def fake_reload(self, reload=False, load_leverage_tiers=False):
            self._markets = dict(FAKE_MARKETS)
            self._api.markets = dict(FAKE_MARKETS)
            self._api.markets_by_id = {}
            return None

        conf = {
            "max_open_trades": 1,
            "stake_currency": "USDT",
            "stake_amount": "unlimited",  # 全仓复利,与环境语义一致
            "tradable_balance_ratio": 1,
            "dry_run": True,
            "dry_run_wallet": 100,
            "trading_mode": "spot",
            "timeframe": "1h",
            "fee": fee,
            "exchange": {
                "name": "binanceus", "key": "", "secret": "",
                "ccxt_config": {"aiohttp_trust_env": True},
                "pair_whitelist": ["SYN/USDT"], "pair_blacklist": [],
            },
            "pairlists": [{"method": "StaticPairList"}],
            "entry_pricing": {
                "price_side": "same", "use_order_book": True, "order_book_top": 1,
                "price_last_balance": 0.0,
                "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1},
            },
            "exit_pricing": {
                "price_side": "other", "use_order_book": True, "order_book_top": 1,
            },
            "datadir": Path(data_dir),
            "user_data_dir": Path(tmp),
            "strategy": cls,
            "strategy_path": strat_dir,
            "timerange": "20260601-20260602",
            "runmode": "backtest",
            "db_url": f"sqlite:///{tmp}/bt.db",
            "export": "none",
            "cache": "none",
        }
        with patch.object(ftx.Exchange, "reload_markets", fake_reload):
            bt = Backtesting(conf)
            bt.start()
        content = bt.all_bt_content[cls]
        trades = content["results"]
        assert len(trades) == 1, f"期望 1 笔交易,得到 {len(trades)}"
        t = trades.iloc[0]
        final_wallet = bt.wallets.get_total("USDT")
        return {
            "entry_time": str(t["open_date"]), "entry_price": float(t["open_rate"]),
            "exit_time": str(t["close_date"]), "exit_price": float(t["close_rate"]),
            "final_wallet": float(final_wallet),
            "single_trade_return": float(t["profit_ratio"]),
            "profit_abs": float(t["profit_abs"]),
            "n_trades": 1,
        }


def expected_wallet_diff(fee: float, r_env: float, initial: float = 100.0) -> float:
    """闭式推导的环境终值 - 回测终值 = W*f*(1-R_env)。

    freqtrade: stake = amount*rate(不为买入费预留现金),
               wallet_after = W*(q2*(1-f)/q1 - f);
    环境:      qty = W/(q1*(1+f))(现金覆盖名义+费用),
               equity_after = W*q2*(1-f)/(q1*(1+f))。
    两式相减恰为 W*f*(1-R_env),R_env 为环境单笔收益比。
    """
    return initial * fee * (1.0 - r_env)


def test_parity_all_cases():
    ART.mkdir(parents=True, exist_ok=True)
    report = ["# 环境与 Freqtrade 回测器对齐(锯齿,决策行0转多/行5转空)", ""]
    cases = [
        ("fee0_slip0", 0.0, 0.0, False),
        ("fee001_slip0", 0.001, 0.0, False),
        ("fee001_slip5bps", 0.001, 5.0, True),
    ]
    results = {}
    for name, fee, slip, with_slip in cases:
        env = run_env_side(fee, slip)
        bt = run_bt_side(fee, slip, with_slip)
        results[name] = {"fee": fee, "slippage_bps": slip, "env": env, "freqtrade": bt}

        # 时间与价格对齐
        assert env["entry_time"] == bt["entry_time"], f"{name} entry 时间不一致"
        assert env["exit_time"] == bt["exit_time"], f"{name} exit 时间不一致"
        assert math.isclose(env["entry_price"], bt["entry_price"], rel_tol=1e-9), \
            f"{name} entry 价格不一致: {env['entry_price']} vs {bt['entry_price']}"
        assert math.isclose(env["exit_price"], bt["exit_price"], rel_tol=1e-9), \
            f"{name} exit 价格不一致: {env['exit_price']} vs {bt['exit_price']}"

        # 单笔收益率精确一致(同公式 q2*(1-f)/(q1*(1+f)) - 1;回测侧 round 8 位)
        assert abs(env["single_trade_return"] - bt["single_trade_return"]) <= 5e-9, \
            f"{name} 单笔收益不一致: {env['single_trade_return']} vs {bt['single_trade_return']}"

        # 终值对比
        diff = env["final_equity"] - bt["final_wallet"]
        exp_diff = expected_wallet_diff(fee, env["single_trade_return"] + 1.0)
        report.append(
            f"## {name}\n"
            f"- entry: {env['entry_time']} @ {env['entry_price']:.8f}"
            f"(env) / {bt['entry_price']:.8f}(bt)\n"
            f"- exit:  {env['exit_time']} @ {env['exit_price']:.8f}"
            f"(env) / {bt['exit_price']:.8f}(bt)\n"
            f"- 单笔收益: env {env['single_trade_return']:.10f} / "
            f"bt {bt['single_trade_return']:.10f}\n"
            f"- 终值: env {env['final_equity']:.10f} / bt {bt['final_wallet']:.10f}\n"
            f"- 终值差(env-bt) = {diff:.10e},闭式期望 {exp_diff:.10e},"
            f"残差 {diff - exp_diff:.3e}\n"
        )
        if fee == 0.0:
            # 零费:唯一差异来源是回测 amount 精度截断(虚拟市场 1e-8)
            assert abs(diff) < 1e-5, f"{name} 零费终值差异常: {diff}"
        else:
            # 有费:残差应只剩 amount/price 精度截断
            assert abs(diff - exp_diff) < 1e-4, \
                f"{name} 终值差与闭式推导不符: {diff} vs {exp_diff}"

    report.append("## 结论")
    report.append("- 两侧均在 open[t+1] 成交,entry/exit 时间与价格一致(相对 1e-9)。")
    report.append("- 单笔收益率公式两侧相同,差 <= 5e-9(回测 round 8 位)。")
    report.append("- 零费终值差 < 1e-5(仅 amount 精度截断)。")
    report.append("- 有费终值差 = W*f*(1-R):freqtrade 的 stake 语义不为买入费预留现金,")
    report.append("  环境按现金覆盖成本约束预留;每笔相对量级 ~1e-4(f=0.001),")
    report.append("  残差与闭式推导吻合到 1e-4 内(精度截断)。")
    (ART / "env_vs_freqtrade_parity.md").write_text("\n".join(report) + "\n")
    (ART / "env_vs_freqtrade_parity.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print("\n".join(report))
