#!/usr/bin/env python
"""诊断:固定时间戳信号为何没进入回测。"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PROJ = os.path.expanduser("~/projects/crypto_rl")
BASE_TS = pd.Timestamp("2026-06-01T00:00:00Z")
Z = [100.0, 110.0, 90.0, 120.0, 80.0, 130.0]
vals = [Z[i % 6] for i in range(30)]
syn = pd.DataFrame({
    "date": pd.date_range(BASE_TS, periods=30, freq="1h", tz="UTC"),
    "open": vals, "high": vals, "low": vals, "close": vals, "volume": [1.0] * 30,
})

STRAT = '''from pandas import DataFrame
from freqtrade.strategy import IStrategy


class FixedSignalA(IStrategy):
    minimal_roi = {"0": 100}
    stoploss = -0.99
    startup_candle_count = 0
    can_short = False
    timeframe = "1h"
    process_only_new_candles = True
    ENTER_TS = "2026-06-01T00:00"
    EXIT_TS = "2026-06-01T02:00"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        m = df["date"].dt.strftime("%Y-%m-%dT%H:%M") == self.ENTER_TS
        print(f"[diag] entry matches={int(m.sum())} first_date={df['date'].iloc[0]}")
        df.loc[m, ["enter_long", "enter_tag"]] = (1, "fixed_enter")
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        m = df["date"].dt.strftime("%Y-%m-%dT%H:%M") == self.EXIT_TS
        print(f"[diag] exit matches={int(m.sum())}")
        df.loc[m, "exit_long"] = 1
        return df
'''

FAKE_MARKETS = {
    "SYN/USDT": {
        "symbol": "SYN/USDT", "base": "SYN", "quote": "USDT",
        "spot": True, "swap": False, "future": False, "active": True,
        "precision": {"price": 4, "amount": 4},
        "limits": {
            "amount": {"min": 0.0001, "max": None},
            "cost": {"min": 0.0001, "max": None},
            "leverage": {"max": 1},
        },
        "info": {},
    }
}

with tempfile.TemporaryDirectory() as tmp:
    strat_dir = os.path.join(tmp, "strategies")
    data_dir = os.path.join(tmp, "data", "binanceus")
    os.makedirs(strat_dir)
    os.makedirs(data_dir)
    with open(os.path.join(strat_dir, "FixedSignalA.py"), "w") as f:
        f.write(STRAT)
    syn.to_feather(os.path.join(data_dir, "SYN_USDT-1h.feather"))

    import freqtrade.exchange as ftx
    from freqtrade.optimize.backtesting import Backtesting
    from freqtrade.resolvers import StrategyResolver
    from freqtrade.data.dataprovider import DataProvider

    conf = {
        "max_open_trades": 1, "stake_currency": "USDT", "stake_amount": 100,
        "dry_run": True, "dry_run_wallet": 1000, "trading_mode": "spot",
        "timeframe": "1h", "fee": 0.001,
        "exchange": {"name": "binanceus", "key": "", "secret": "",
                     "ccxt_config": {"aiohttp_trust_env": True},
                     "pair_whitelist": ["SYN/USDT"], "pair_blacklist": []},
        "pairlists": [{"method": "StaticPairList"}],
        "entry_pricing": {"price_side": "same", "use_order_book": True, "order_book_top": 1,
                          "price_last_balance": 0.0,
                          "check_depth_of_market": {"enabled": False, "bids_to_ask_delta": 1}},
        "exit_pricing": {"price_side": "other", "use_order_book": True, "order_book_top": 1},
        "datadir": Path(data_dir), "user_data_dir": Path(tmp),
        "strategy": "FixedSignalA", "strategy_path": strat_dir,
        "timerange": "20260601-20260602", "runmode": "backtest",
        "db_url": f"sqlite:///{tmp}/bt.db", "export": "none", "cache": "none",
    }

    def fake_reload(self, reload=False, load_leverage_tiers=False):
        self._markets = dict(FAKE_MARKETS)
        self._api.markets = dict(FAKE_MARKETS)
        self._api.markets_by_id = {}
        return None

    with patch.object(ftx.Exchange, "reload_markets", fake_reload):
        strat = StrategyResolver.load_strategy(conf)
        print("[diag] resolved:", strat.__class__.__name__, "tf:", strat.timeframe)
        out = strat.ft_advise_signals(syn.copy(), {"pair": "SYN/USDT"})
        print("[diag] after ft_advise_signals: enter_long sum=", out["enter_long"].sum(),
              " exit_long sum=", out.get("exit_long", pd.Series(dtype=float)).sum())
        print("[diag] columns:", list(out.columns))
        bt = Backtesting(conf)
        bt.start()
        c = bt.all_bt_content["FixedSignalA"]
        print("[diag] trades:", len(c["results"]))
