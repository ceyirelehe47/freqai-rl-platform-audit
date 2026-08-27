"""工作包 H 测试级 harness:真实 FreqAI live 编排完整链路。

与阶段 2.5.2 bot_harness 的本质区别:
- 不再用测试壳替代 populate_indicators 中的模型调用;
- bot 配置携带完整 freqai 段,FreqtradeBot 构造时
  strategy.load_freqAI_model() 真实实例化 RouteCModel;
- 真实调用链:
    RouteCStrategy.populate_indicators
    -> self.freqai.start(dataframe, metadata, strategy)(真实 IFreqaiModel.start)
    -> start_live(FreqAI live 特征处理/缩放/do_predict)
    -> data_drawer.load_data(从磁盘加载已保存模型与 pipeline)
    -> RouteCModel.predict -> rl_model_predict(live 分支)
    -> build_strategy_return_arrays(目标列由 FreqAI 返回)
    -> populate_entry/exit_trend -> FreqtradeBot.process
    -> Fake Exchange(仅替代外部交易所) -> Trade/Order 持久层。

fixture 准备(测试准备阶段,任务书允许):
- 用正式 RouteCModel 在小型合成数据上跑一次 Backtesting 训练极小 PPO
  (真实 train/predict/save 全链路),保留模型目录与 pair_dictionary.json;
- pair_dictionary.json 的 trained_timestamp 更新为当前时刻,
  live_retrain_hours 设为极大值,保证 live 测试不会重新训练。

无 API Key、无外部网络(download_all_data_for_training 测试级 no-op,
训练数据已在磁盘;其余所有网络访问均被 Fake Exchange 拦截)。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROJ_USER_STRAT = ROOT / "user_data" / "strategies"
PROJ_USER_MODELS = ROOT / "user_data" / "freqaimodels"
TEMPLATE = ROOT / "experiments" / "freqai_rl_stage2_5_2a" / "configs" / \
    "config_stage252a.template.json"
PAIR = "SYN/USDT"
TIMEFRAME = "1h"
TIMERANGE = "20260715-20260801"
DATA_START = "2026-06-01T00:00:00Z"
N_DAYS = 61
TICK = 0.01
IDENTIFIER = "stage252a-live-fixture"
LOGGER = logging.getLogger(__name__)

FAKE_MARKETS = {
    PAIR: {
        "symbol": PAIR, "base": "SYN", "quote": "USDT",
        "spot": True, "swap": False, "future": False, "active": True,
        "precision": {"price": TICK, "amount": 1e-8},
        "limits": {"amount": {"min": 1e-8, "max": None},
                   "cost": {"min": 1e-8, "max": None},
                   "leverage": {"max": 1}},
        "fee": {"maker": 0.001, "taker": 0.001},
        "info": {},
    }
}


def make_training_data() -> pd.DataFrame:
    """61 天合成数据(tick 网格,合法 OHLC),训练 2 个窗口。"""
    n = N_DAYS * 24
    idx = pd.date_range(DATA_START, periods=n, freq="1h", tz="UTC")
    step = np.sin(np.arange(n) / 24.0 * 2.0 * np.pi) * 0.002
    close = 100.0 * np.exp(np.cumsum(np.log1p(step)))
    open_ = np.empty(n)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * 1.005
    low = np.minimum(open_, close) * 0.995
    snap = lambda a: np.round(np.round(a / TICK).astype(np.int64) * TICK, 10)
    open_, high, low, close = snap(open_), snap(high), snap(low), snap(close)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame({
        "date": idx, "open": open_, "high": high, "low": low,
        "close": close, "volume": np.full(n, 10.0),
    })


def train_fixture_models(tmp_root: Path) -> dict:
    """测试准备阶段:正式 RouteCModel 小型 Backtesting 训练(真实 PPO)。"""
    import freqtrade.exchange as ftx
    from freqtrade.optimize.backtesting import Backtesting

    userdir = tmp_root / "user_data"
    data_dir = tmp_root / "data" / "binanceus"
    data_dir.mkdir(parents=True, exist_ok=True)
    userdir.mkdir(parents=True, exist_ok=True)
    make_training_data().to_feather(data_dir / "SYN_USDT-1h.feather")

    def fake_reload(self, reload=False, load_leverage_tiers=False):
        self._markets = dict(FAKE_MARKETS)
        self._api.markets = dict(FAKE_MARKETS)
        self._api.markets_by_id = {}
        return None

    conf = json.loads(TEMPLATE.read_text())
    freqai = conf["freqai"]
    freqai["identifier"] = IDENTIFIER
    freqai["train_period_days"] = 30
    freqai["backtest_period_days"] = 7
    freqai["activate_tensorboard"] = False
    freqai["live_retrain_hours"] = 999999
    conf["exchange"]["pair_whitelist"] = [PAIR]
    conf["fee"] = 0.001
    config_path = tmp_root / "config_train.json"
    config_path.write_text(json.dumps(conf, indent=2, default=str))
    conf["config_files"] = [str(config_path)]
    conf.update({
        "datadir": data_dir, "user_data_dir": userdir, "userdir": userdir,
        "strategy": "RouteCStrategy", "strategy_path": str(PROJ_USER_STRAT),
        "freqaimodel": "RouteCModel", "freqaimodel_path": str(PROJ_USER_MODELS),
        "timerange": TIMERANGE, "runmode": "backtest",
        "db_url": f"sqlite:///{tmp_root}/train.db",
        "export": "none", "cache": "none",
    })

    with patch.object(ftx.Exchange, "reload_markets", fake_reload):
        bt = Backtesting(conf)
        bt.start()

    models_dir = userdir / "models" / IDENTIFIER
    assert models_dir.is_dir(), "训练未产生模型目录"
    sub_trains = sorted(d.name for d in models_dir.glob("sub-train-*"))
    assert sub_trains, "无 sub-train 模型目录"
    # live 启动准备:trained_timestamp 置为当前时刻(配合 live_retrain_hours
    # 巨大值),保证 start_scanning 线程与 start_live 都不会重新训练
    pair_dict_path = models_dir / "pair_dictionary.json"
    pair_dict = json.loads(pair_dict_path.read_text())
    now_ts = int(datetime.now(UTC).timestamp())
    for pair_info in pair_dict.values():
        pair_info["trained_timestamp"] = now_ts
    pair_dict_path.write_text(json.dumps(pair_dict))
    return {
        "root": tmp_root, "userdir": userdir, "datadir": data_dir,
        "models_dir": models_dir, "identifier": IDENTIFIER,
        "sub_trains": sub_trains, "pair_dict": pair_dict,
    }


# ---------------------------------------------------------------- Fake Exchange
class FakeExchangeScript:
    """外部交易所脚本化状态机(与 2.5.2 harness 同语义,仅替换外部交易所)。"""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.fetch_script: dict[str, list[dict]] = {}
        self.create_status = "open"
        self.create_filled = 0.0
        self.create_fills_price = None
        self.created_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"fx-{self._counter:04d}"

    def create_order(self, *, pair, ordertype, side, amount, rate, **kwargs):
        self._counter += 1
        oid = f"fx-{self._counter:04d}"
        filled = min(self.create_filled, amount)
        order = {
            "id": oid, "symbol": pair, "price": rate,
            "average": rate if filled > 0 else None,
            "amount": amount, "cost": filled * rate,
            "type": ordertype, "side": side,
            "filled": filled, "remaining": amount - filled,
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "status": self.create_status, "fee": None, "info": {},
        }
        if self.create_fills_price is not None and filled > 0:
            order["average"] = self.create_fills_price
        self.orders[oid] = order
        self.created_calls.append({
            "order_id": oid, "pair": pair, "side": side,
            "ordertype": ordertype, "amount": amount, "rate": rate,
            "status": self.create_status, "filled": filled,
        })
        return order

    def fetch_order(self, order_id, pair, params=None):
        script = self.fetch_script.get(order_id)
        if script:
            state = dict(script[0])
            if len(script) > 1:
                script.pop(0)
        else:
            state = {"keep": True}
        current = self.orders[order_id]
        if not state.get("keep"):
            filled = float(state.get("filled", current["filled"]))
            current["status"] = state.get("status", current["status"])
            current["filled"] = filled
            current["remaining"] = current["amount"] - filled
            current["cost"] = filled * current["price"]
            if filled > 0:
                current["average"] = state.get("average", current["price"])
            else:
                current["average"] = None
        return dict(current)

    def cancel_order_with_result(self, order_id, pair, amount):
        current = self.orders[order_id]
        current["status"] = "canceled"
        self.cancel_calls.append(order_id)
        return dict(current)


def make_live_candles(datadir: Path) -> pd.DataFrame:
    """合成 K 线:从磁盘训练数据最后一根起连续衔接到当前小时。

    FreqAI live 的 update_historic_data 要求 DataProvider K 线与磁盘
    historic data 重叠(真实场景 dp 提供 ~999 根含训练数据末尾),
    因此 fake candles 必须覆盖训练数据的最后一根并衔接到 now。
    """
    hist = pd.read_feather(datadir / "SYN_USDT-1h.feather")
    start = hist["date"].iloc[-1]
    last_hour = pd.Timestamp.now(tz="UTC").floor("h")
    if last_hour <= start:
        last_hour = start + pd.Timedelta(hours=150)
    idx = pd.date_range(start=start, end=last_hour, freq="1h", tz="UTC")
    n = len(idx)
    base = float(hist["close"].iloc[-1])
    step = np.sin(np.arange(n) / 11.0 * np.pi) * 0.003
    close = base * np.exp(np.cumsum(np.log1p(step)))
    open_ = np.empty(n)
    open_[0] = base
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) + TICK
    low = np.minimum(open_, close) - TICK
    snap = lambda a: np.round(np.round(a / TICK).astype(np.int64) * TICK, 10)
    open_, high, low, close = snap(open_), snap(high), snap(low), snap(close)
    return pd.DataFrame({
        "date": idx, "open": open_, "high": high, "low": low,
        "close": close, "volume": np.full(n, 10.0),
    })


class FreqAILiveHarness:
    """组装真实 FreqAI live 编排 + Fake Exchange 的 Dry-run bot。"""

    def __init__(self, trained: dict, tmpdir: Path,
                 share_db_url: str | None = None) -> None:
        import freqtrade.exchange as ftx
        from freqtrade.enums import CandleType, RunMode
        from freqtrade.freqtradebot import FreqtradeBot
        from freqtrade.persistence import Trade

        Trade.use_db = True
        self.tmpdir = Path(tmpdir)
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.trained = trained
        self.candles = make_live_candles(trained["datadir"])
        self.fake = FakeExchangeScript()
        self.db_url = share_db_url or f"sqlite:///{self.tmpdir}/live.db"

        conf = json.loads(TEMPLATE.read_text())
        conf.pop("fiat_display_currency", None)  # 避免 coingecko 外部请求
        freqai = conf["freqai"]
        freqai["identifier"] = trained["identifier"]
        freqai["activate_tensorboard"] = False
        freqai["live_retrain_hours"] = 999999
        freqai["expiration_hours"] = 0
        conf["exchange"]["pair_whitelist"] = [PAIR]
        conf["fee"] = 0.001
        conf.update({
            "dry_run": True,
            "runmode": RunMode.DRY_RUN,
            "db_url": self.db_url,
            "datadir": trained["datadir"],
            "user_data_dir": trained["userdir"],
            "userdir": trained["userdir"],
            "strategy": "RouteCStrategy",
            "strategy_path": str(PROJ_USER_STRAT),
            "freqaimodel": "RouteCModel",
            "freqaimodel_path": str(PROJ_USER_MODELS),
            "stake_amount": 100.0,
            "max_open_trades": 1,
            "dry_run_wallet": {"USDT": 1000.0, "SYN": 0.0},
            "pairlists": [{"method": "StaticPairList"}],
            "unfilledtimeout": {
                "entry": 30, "exit": 30, "unit": "minutes",
                "exit_timeout_count": 0,
            },
            "internals": {"process_throttle_secs": 1},
            "initial_state": "running",
            "cancel_open_orders_on_exit": False,
            "dataformat_ohlcv": "feather",
            "export": "none",
        })
        config_path = Path(tmpdir) / "config_live.json"
        config_path.write_text(json.dumps(conf, indent=2, default=str))
        conf["config_files"] = [str(config_path)]

        def fake_reload(self, reload=False, load_leverage_tiers=False):
            self._markets = dict(FAKE_MARKETS)
            self._api.markets = dict(FAKE_MARKETS)
            self._api.markets_by_id = {}
            return None

        def no_download(dp, config):
            # 训练数据已在磁盘;阻止 live 启动期的外部数据下载(无网络)
            LOGGER.info("download_all_data_for_training skipped (test fixture)")

        import freqtrade.freqai.utils as freqai_utils

        with patch.object(ftx.Exchange, "reload_markets", fake_reload), \
                patch.object(freqai_utils, "download_all_data_for_training",
                             no_download):
            self.bot = FreqtradeBot(conf)

        # 真实 RouteCModel 实例(FreqaiModelResolver 直接实例化)
        self.model: object = self.bot.strategy.freqai
        self.freqai_start_calls = 0
        _orig_start = self.model.start

        def counting_start(dataframe, metadata, strategy):
            self.freqai_start_calls += 1
            return _orig_start(dataframe, metadata, strategy)

        self.model.start = counting_start  # 测试级计数探针(不改生产代码)

        ex = self.bot.exchange

        def fake_reload_bound(reload=False, load_leverage_tiers=False):
            ex._markets = dict(FAKE_MARKETS)
            ex._api.markets = dict(FAKE_MARKETS)
            ex._api.markets_by_id = {}
            return None

        ex.reload_markets = fake_reload_bound

        def fake_refresh(pair_list, *args, **kwargs):
            for item in pair_list:
                p, tf = item[0], item[1]
                ex._klines[(p, tf, CandleType.SPOT)] = self.candles.copy()
            return {}

        def fake_get_rate(pair, side, is_short=False, refresh=False):
            return float(self.candles["close"].iloc[-1])

        ex.refresh_latest_ohlcv = fake_refresh
        ex.get_rate = fake_get_rate
        ex.create_order = self.fake.create_order
        ex.fetch_order = self.fake.fetch_order
        ex.cancel_order_with_result = self.fake.cancel_order_with_result
        ex.fetch_order_or_stoploss_order = lambda oid, pair, stoploss: (
            self.fake.fetch_order(oid, pair)
        )
        self.heartbeats = 0

    # ------------------------------------------------------------ 驱动/观察
    def advance_candle(self) -> None:
        last = self.candles["date"].iloc[-1]
        n = len(self.candles)
        prev_close = float(self.candles["close"].iloc[-1])
        step = np.sin(n / 11.0 * np.pi) * 0.003
        new_close = round(round(prev_close * (1 + step) / TICK) * TICK, 10)
        new_open = prev_close
        new = pd.DataFrame({
            "date": [last + pd.Timedelta(hours=1)],
            "open": [new_open],
            "high": [round(max(new_open, new_close) + TICK, 10)],
            "low": [round(min(new_open, new_close) - TICK, 10)],
            "close": [new_close], "volume": [10.0],
        })
        self.candles = pd.concat([self.candles, new], ignore_index=True)

    def heartbeat(self, advance: bool = True) -> dict:
        if advance:
            self.advance_candle()
        self.bot.process()
        self.heartbeats += 1
        return self.snapshot()

    def snapshot(self) -> dict:
        from freqtrade.persistence import Trade
        from rl_platform.execution_state import get_live_execution_snapshot

        trades = Trade.get_trades_proxy(is_open=True)
        snap = get_live_execution_snapshot(
            PAIR, amount_epsilon=self.bot.strategy.route_c_amount_epsilon)
        orders = []
        for t in trades:
            for o in t.orders:
                orders.append({
                    "order_id": o.order_id, "side": o.ft_order_side,
                    "status": o.status, "ft_is_open": o.ft_is_open,
                    "filled": o.safe_filled, "amount": o.safe_amount,
                })
        last_analyzed, _ = self.bot.dataprovider.get_analyzed_dataframe(
            PAIR, TIMEFRAME)
        hist_enter = int(last_analyzed["enter_long"].iloc[:-1].sum()) \
            if last_analyzed is not None and len(last_analyzed) else None
        return {
            "heartbeat": self.heartbeats,
            "state": snap.state,
            "filled_amount": snap.filled_amount,
            "n_open_trades": len(trades),
            "orders": orders,
            "n_created_orders": len(self.fake.created_calls),
            "n_cancel_calls": len(self.fake.cancel_calls),
            "historical_enter_signals": hist_enter,
            "has_target_column": last_analyzed is not None and
            "&-target_position" in last_analyzed.columns,
            "last_target": int(last_analyzed["&-target_position"].iloc[-1])
            if last_analyzed is not None and len(last_analyzed)
            and "&-target_position" in last_analyzed.columns else None,
        }

    def shutdown(self) -> None:
        try:
            self.model.shutdown()
        except Exception:  # noqa: BLE001 - 测试收尾尽力而为
            pass
