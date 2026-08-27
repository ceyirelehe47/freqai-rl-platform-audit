#!/usr/bin/env python
"""阶段二 §22:RL 训练环境 vs Freqtrade 回测器(相同锯齿人工数据,fee=0.001)。

- RL 侧:复用 synthetic_zigzag_trace.csv 的 t3_enter_exit (fee=0.001) 真实 trace。
- 回测侧:同一锯齿 OHLCV 写入 feather,用测试级 monkeypatch 注入虚拟市场
  (不修改上游源码),通过真实 Backtesting.start() 执行两个固定时间戳信号策略:
  * FixedSignalA: 信号在数据行 0(与 RL 的观察行同信息集) → 回测成交 open[1]
  * FixedSignalB: 信号在数据行 1 → 回测成交 open[2](与 RL 环境执行同根同价)
"""
import os
import sys
import tempfile
from unittest.mock import patch

import pandas as pd

PROJ = os.path.expanduser("~/projects/crypto_rl")
ART = f"{PROJ}/artifacts/freqai_rl_platform_audit"

BASE_TS = pd.Timestamp("2026-06-01T00:00:00Z")
N = 30
ZIGZAG = [100.0, 110.0, 90.0, 120.0, 80.0, 130.0]

STRAT = '''from pandas import DataFrame
from freqtrade.strategy import IStrategy


class {cls}(IStrategy):
    """审计用固定时间戳信号策略(非 RL)。非生产用途。"""

    minimal_roi = {{"0": 100}}
    stoploss = -0.99
    startup_candle_count = 0
    can_short = False
    timeframe = "1h"
    process_only_new_candles = True

    ENTER_TS = "{ets}"
    EXIT_TS = "{xts}"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        m = df["date"].dt.strftime("%Y-%m-%dT%H:%M") == self.ENTER_TS
        df.loc[m, ["enter_long", "enter_tag"]] = (1, "fixed_enter")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        m = df["date"].dt.strftime("%Y-%m-%dT%H:%M") == self.EXIT_TS
        df.loc[m, "exit_long"] = 1
        return df
'''

STRATS = {
    # 行0=00:00(价100), 行1=01:00(110), 行2=02:00(90), 行3=03:00(120), 行4=04:00(80)
    "FixedSignalA": ("2026-06-01T00:00", "2026-06-01T02:00"),
    "FixedSignalB": ("2026-06-01T01:00", "2026-06-01T03:00"),
}

FAKE_MARKETS = {
    "SYN/USDT": {
        "symbol": "SYN/USDT", "base": "SYN", "quote": "USDT",
        "spot": True, "swap": False, "future": False, "active": True,
        "precision": {"price": 0.0001, "amount": 0.0001},
        "limits": {
            "amount": {"min": 0.0001, "max": None},
            "cost": {"min": 0.0001, "max": None},
            "leverage": {"max": 1},
        },
        "info": {},
    }
}


def main():
    os.makedirs(ART, exist_ok=True)
    vals = [ZIGZAG[i % len(ZIGZAG)] for i in range(N)]
    syn = pd.DataFrame({
        "date": pd.date_range(BASE_TS, periods=N, freq="1h", tz="UTC"),
        "open": vals, "high": vals, "low": vals, "close": vals, "volume": [1.0] * N,
    })

    with tempfile.TemporaryDirectory() as tmp:
        strat_dir = os.path.join(tmp, "strategies")
        data_dir = os.path.join(tmp, "data", "binanceus")
        os.makedirs(strat_dir)
        os.makedirs(data_dir)
        for cls, (ets, xts) in STRATS.items():
            with open(os.path.join(strat_dir, f"{cls}.py"), "w") as f:
                f.write(STRAT.format(cls=cls, ets=ets, xts=xts))
        syn.to_feather(os.path.join(data_dir, "SYN_USDT-1h.feather"))

        import freqtrade.exchange as ftx
        from pathlib import Path
        from freqtrade.optimize.backtesting import Backtesting

        def fake_reload(self, reload=False, load_leverage_tiers=False):
            self._markets = dict(FAKE_MARKETS)
            self._api.markets = dict(FAKE_MARKETS)
            self._api.markets_by_id = {}
            return None

        results = {}
        for cls in STRATS:
            conf = {
                "max_open_trades": 1,
                "stake_currency": "USDT",
                "stake_amount": 100,
                "dry_run": True,
                "dry_run_wallet": 1000,
                "trading_mode": "spot",
                "timeframe": "1h",
                "fee": 0.001,
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
                "db_url": f"sqlite:///{tmp}/bt_{cls}.db",
                "export": "none",
                "cache": "none",
            }
            with patch.object(ftx.Exchange, "reload_markets", fake_reload):
                bt = Backtesting(conf)
                bt.start()
                content = bt.all_bt_content[cls]
                trades = content["results"]
                print(f"[debug] {cls}: trades={len(trades)}, "
                      f"rejected={len(content.get('rejected_signals') or [])}, "
                      f"timedout_entry={len(content.get('timedout_entry_orders') or [])}, "
                      f"timedout_exit={len(content.get('timedout_exit_orders') or [])}")
                keep = ["pair", "open_date", "close_date", "open_rate", "close_rate",
                        "profit_ratio", "profit_abs", "trade_duration", "exit_reason",
                        "is_open"]
                results[cls] = trades[keep].to_dict("records") if len(trades) else []

    rl = pd.read_csv(f"{ART}/synthetic_zigzag_trace.csv")
    rl_t3 = rl[(rl["fee"] == 0.001) & (rl["script"] == "t3_enter_exit")]
    rl_enter = rl_t3[rl_t3["action_name"] == "Enter(Buy)"].iloc[0]
    rl_exit = rl_t3[rl_t3["action_name"] == "Exit(Sell)"].iloc[0]
    rl_pnl = rl_exit["total_profit_realized"] - 1

    lines = ["# RL 训练环境 vs Freqtrade 回测器对比(相同锯齿数据,fee=0.001,stake=100)", ""]
    lines.append("锯齿序列(索引:价格): " +
                 ", ".join(f"{i}:{ZIGZAG[i % 6]}" for i in range(6)) + ",…循环")
    lines.append("")
    lines.append("## RL 三动作环境(t3_enter_exit,来自 synthetic_zigzag_trace.csv)")
    lines.append(f"- 观察窗口末行 = 数据行 {int(rl_enter['tick_before']) - 1}"
                 f"(00:00,价格100;obs 不含当前 tick)")
    lines.append(f"- Enter 执行: tick {int(rl_enter['tick_after'])}(02:00), "
                 f"价格 open={rl_enter['price_used_open']}")
    lines.append(f"- Exit 执行: tick {int(rl_exit['tick_after'])}(04:00), "
                 f"价格 open={rl_exit['price_used_open']}")
    lines.append(f"- 平仓后 total_profit = {rl_exit['total_profit_realized']},"
                 f"单笔净值变化 = {rl_pnl:.8f}")
    lines.append("")
    lines.append("## Freqtrade 回测器(真实 Backtesting.start(),虚拟市场 monkeypatch)")
    for cls, trs in results.items():
        lines.append(f"### {cls}")
        for t in trs:
            lines.append(
                f"- open_date={t['open_date']} open_rate={t['open_rate']} | "
                f"close_date={t['close_date']} close_rate={t['close_rate']} | "
                f"profit_ratio={t['profit_ratio']:.8f} profit_abs={t['profit_abs']:.6f} | "
                f"exit_reason={t['exit_reason']} is_open={t['is_open']}"
            )
        if not trs:
            lines.append("- (无交易)")
    lines.append("")
    lines.append("## 对照结论")
    lines.append("- RL 环境:观察行0(00:00,100) → 动作执行在 open[2](02:00,90):错开 2 根。")
    lines.append("- FixedSignalA(信号行0):回测成交 open[1](01:00,110):错开 1 根。")
    lines.append("- FixedSignalB(信号行1):回测成交 open[2](02:00,90):与 RL 执行同根同价。")
    lines.append("- 即:RL 训练环境的动作比『同信息集回测信号』晚一根 K 线执行;")
    lines.append("  要让回测复现 RL 的成交价,必须把信号再提前一根(FixedSignalB)。")

    with open(f"{ART}/env_vs_backtester_comparison.md", "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
