"""工作包 C 测试级集成 harness:FreqAI live 推理 -> 策略 -> FreqtradeBot ->
Fake Exchange -> Trade/Order 持久层 -> 下一 heartbeat(任务书十至十二节)。

链路覆盖(全部真实组件,除外部交易所):
    RouteCModel.rl_model_predict()(真实方法,live 分支)
    -> RouteCStrategyShellLive.populate_indicators / populate_entry/exit_trend
       (真实 RouteCStrategy 信号路径,仅 populate_indicators 用注入的
        rl_model_predict 产出目标列,替代完整 FreqAI 训练管线)
    -> FreqtradeBot.process()(analyze -> manage_open_orders -> exit -> enter)
    -> Fake Exchange create_order / fetch_order / cancel_order_with_result
       (只替代外部交易所;按测试脚本返回 open/部分成交/全部成交/
        rejected/expired/cancelled)
    -> 真实 Trade/Order 持久层(文件 SQLite)
    -> 下一 heartbeat(bot.process() 再次驱动)

Fake Exchange 规则:
- create_order:按 create_status/create_filled 返回初始订单;
- fetch_order:每次调用消费脚本 fetch_script[order_id] 的下一个状态
  (长度 1 时粘滞);脚本用尽后保持当前状态;
- cancel_order_with_result:把订单置为 canceled(保留当前 filled);
- refresh_latest_ohlcv/get_rate:提供合成 K 线与最新价(无网络)。

不连接真实账户、无 API Key;订单状态变化全部通过 Freqtrade 官方
update_trade_state / handle_cancel_order / adjust_order_price 路径同步。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PAIR = "SYN/USDT"
TIMEFRAME = "1h"
LOGGER = logging.getLogger(__name__)

FAKE_MARKETS = {
    PAIR: {
        "symbol": PAIR, "base": "SYN", "quote": "USDT",
        "spot": True, "swap": False, "future": False, "active": True,
        "precision": {"price": 0.01, "amount": 1e-8},
        "limits": {"amount": {"min": 1e-5, "max": None},
                   "cost": {"min": 1e-4, "max": None},
                   "leverage": {"max": 1}},
        "fee": {"maker": 0.001, "taker": 0.001},
        "info": {},
    }
}

STRATEGY_SHELL_TMPL = '''"""阶段 2.5.2 工作包 C 测试壳(测试级,非生产路径)。

复用真实 RouteCStrategy 的信号路径(populate_entry/exit_trend ->
latest_row_signals / adjust_*_price),仅 populate_indicators 用注入的
RouteCModel.rl_model_predict 产出 &-target_position(替代完整 FreqAI
训练/缓存管线,推理入口与生产完全相同)。
"""
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd

PROJ = r"{proj_root}"
for p in (PROJ + "/src", PROJ + "/user_data/strategies"):
    if p not in sys.path:
        sys.path.insert(0, p)

from RouteCStrategy import RouteCStrategy  # noqa: E402


class RouteCStrategyShellLive(RouteCStrategy):
    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        model = getattr(self, "_s252_model", None)
        policy = getattr(self, "_s252_policy", None)
        if model is None or policy is None:
            raise RuntimeError("harness 未注入 _s252_model / _s252_policy")
        n = len(dataframe)
        dpv = getattr(self, "_s252_do_predict", None)
        dp_mask = [1] * (n - 1) + [int(dpv)] if dpv is not None else [1] * n
        feats = pd.DataFrame({{"f0": np.zeros(n)}})
        dk = SimpleNamespace(
            pair=metadata["pair"],
            label_list=["&-target_position"],
            do_predict=dp_mask,
        )
        out = model.rl_model_predict(feats, dk, policy)
        dataframe = dataframe.copy()
        dataframe["&-target_position"] = out["&-target_position"].to_numpy()
        dataframe["do_predict"] = dp_mask
        return dataframe
'''


class HarnessTargetPolicy:
    """回显 harness.current_target 的确定性策略(测试脚本驱动目标)。"""

    def __init__(self, harness) -> None:
        self.harness = harness

    def predict(self, obs, deterministic: bool = True):
        return int(self.harness.current_target), None


class FakeExchangeScript:
    """外部交易所的脚本化状态机(仅测试级)。"""

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

    def _order_dict(self, oid, pair, side, amount, rate, status, filled):
        return {
            "id": oid, "symbol": pair, "price": rate,
            "average": rate if filled > 0 else None,
            "amount": amount, "cost": filled * rate,
            "type": "limit", "side": side,
            "filled": filled, "remaining": amount - filled,
            "timestamp": int(datetime.now(UTC).timestamp() * 1000),
            "status": status, "fee": None, "info": {},
        }

    # ---- ccxt 语义接口(FreqtradeBot 调用) ----
    def create_order(self, *, pair, ordertype, side, amount, rate, **kwargs):
        oid = self._next_id()
        filled = min(self.create_filled, amount)
        order = self._order_dict(
            oid, pair, side, amount, rate,
            self.create_status, filled,
        )
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
            if filled > 0 and state.get("average"):
                current["average"] = state["average"]
            elif filled > 0:
                current["average"] = current["price"]
            else:
                current["average"] = None
        return dict(current)

    def cancel_order_with_result(self, order_id, pair, amount):
        current = self.orders[order_id]
        current["status"] = "canceled"
        self.cancel_calls.append(order_id)
        return dict(current)


def make_route_c_model(live=True, slippage_bps=5.0, price_tick=0.01):
    """构造 RouteCModel 实例(测试级 patch 父类 __init__,同 2.5.1 模式)。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "route_c_model_harness",
        ROOT / "user_data" / "freqaimodels" / "RouteCModel.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    RouteCModel = mod.RouteCModel

    def fake_super_init(self, **kwargs):
        cfg = kwargs["config"]
        self.freqai_info = cfg["freqai"]
        self.config = cfg
        self.CONV_WIDTH = self.freqai_info.get("conv_width", 1)
        self.live = live
        self.activate_tensorboard = False

    with patch(
        "freqtrade.freqai.RL.BaseReinforcementLearningModel."
        "BaseReinforcementLearningModel.__init__",
        fake_super_init,
    ):
        return RouteCModel(config={
            "freqai": {
                "conv_width": 1,
                "route_c": {
                    "ppo": {}, "slippage_bps": slippage_bps, "seed": 42,
                    "price_tick": price_tick,
                },
            },
        })


def make_candles(n_history: int = 100) -> pd.DataFrame:
    """恒定价格合成 K 线;最后一根锚定当前小时,heartbeat 逐小时推进。"""
    last_hour = pd.Timestamp.now(tz="UTC").floor("h")
    idx = pd.date_range(end=last_hour, periods=n_history, freq="1h", tz="UTC")
    n = len(idx)
    return pd.DataFrame({
        "date": idx,
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.01),
        "low": np.full(n, 99.99),
        "close": np.full(n, 100.0),
        "volume": np.full(n, 10.0),
    })


class BotHarness:
    """组装完整 live 链路并驱动 heartbeat。"""

    def __init__(self, tmpdir, n_history: int = 100, slippage_bps: float = 5.0,
                 price_tick: float = 0.01, fee: float = 0.001,
                 share_db_url: str | None = None) -> None:
        import freqtrade.exchange as ftx
        from freqtrade.enums import CandleType, RunMode
        from freqtrade.freqtradebot import FreqtradeBot
        from freqtrade.persistence import Trade

        Trade.use_db = True
        self.tmpdir = Path(tmpdir)
        userdir = self.tmpdir / "user_data"
        strat_dir = userdir / "strategies"
        strat_dir.mkdir(parents=True, exist_ok=True)
        proj_root = str(ROOT).replace("\\", "/")
        (strat_dir / "RouteCStrategyShellLive.py").write_text(
            STRATEGY_SHELL_TMPL.format(proj_root=proj_root), encoding="utf-8")

        self.candles = make_candles(n_history)
        self.fake = FakeExchangeScript()
        self.current_target = 0
        self.latest_do_predict: list[int] | None = None
        self.db_url = share_db_url or f"sqlite:///{self.tmpdir}/bot.db"

        self.conf = {
            "dry_run": True,
            "trading_mode": "spot",
            "runmode": RunMode.DRY_RUN,
            "timeframe": TIMEFRAME,
            "stake_currency": "USDT",
            "stake_amount": 100.0,
            "max_open_trades": 1,
            "dry_run_wallet": {"USDT": 1000.0, "SYN": 0.0},
            "db_url": self.db_url,
            "exchange": {
                "name": "binanceus", "key": "", "secret": "",
                "pair_whitelist": [PAIR],
                "ccxt_config": {}, "ccxt_async_config": {},
                "skip_pair_validation": True,
                "skip_open_order_update": True,
                "enable_ws": False,
            },
            "pairlists": [{"method": "StaticPairList"}],
            "entry_pricing": {
                "price_side": "same", "use_order_book": False,
                "order_book_top": 1, "check_depth_of_market": {"enabled": False},
            },
            "exit_pricing": {"price_side": "same", "use_order_book": False},
            "unfilledtimeout": {
                "entry": 30, "exit": 30, "unit": "minutes", "exit_timeout_count": 0,
            },
            "order_types": {
                "entry": "limit", "exit": "limit",
                "stoploss": "market", "stoploss_on_exchange": False,
            },
            "fee": fee,
            "internals": {"process_throttle_secs": 1},
            "strategy": "RouteCStrategyShellLive",
            "strategy_path": str(strat_dir),
            "user_data_dir": userdir,
            "initial_state": "running",
            "cancel_open_orders_on_exit": False,
            "dataformat_ohlcv": "feather",
            "export": "none",
        }

        def fake_reload(self, reload=False, load_leverage_tiers=False):
            self._markets = dict(FAKE_MARKETS)
            self._api.markets = dict(FAKE_MARKETS)
            self._api.markets_by_id = {}
            return None

        with patch.object(ftx.Exchange, "reload_markets", fake_reload):
            self.bot = FreqtradeBot(self.conf)

        # ---- 注入模型/策略(真实 RouteCModel.rl_model_predict + 真实信号路径)
        self.model_shell = make_route_c_model(
            live=True, slippage_bps=slippage_bps, price_tick=price_tick,
        )
        self.policy = HarnessTargetPolicy(self)
        self.bot.strategy._s252_model = self.model_shell
        self.bot.strategy._s252_policy = self.policy

        # ---- Fake Exchange(实例级替换外部交易所行为,其余组件保持真实)
        ex = self.bot.exchange

        def fake_reload_bound(reload=False, load_leverage_tiers=False):
            # 与构造期 class 级 patch 相同:注入虚拟市场,不访问网络
            ex._markets = dict(FAKE_MARKETS)
            ex._api.markets = dict(FAKE_MARKETS)
            ex._api.markets_by_id = {}
            return None

        ex.reload_markets = fake_reload_bound

        def fake_refresh(pair_list, *args, **kwargs):
            # 动态读 self.candles:advance_candle 会整体替换 DataFrame
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

        self.candle_type = CandleType.SPOT
        self.heartbeats = 0

    # ------------------------------------------------------------ 驱动接口
    def set_target(self, target: int) -> None:
        self.current_target = int(target)
        self.bot.strategy._s252_do_predict = None

    def set_target_invalid_prediction(self, target: int, dp: int = 2) -> None:
        """目标与 do_predict 一起设置(无效预测;长度在调用时按 df 行数构造)。"""
        self.current_target = int(target)
        self.bot.strategy._s252_do_predict = dp  # 仅最新行的 dp 值

    def advance_candle(self) -> None:
        """推进一根 K 线(模拟时间流逝一小时;replace_order 的新 K 线条件
        与 unfilledtimeout 都由此驱动)。"""
        last = self.candles["date"].iloc[-1]
        new = pd.DataFrame({
            "date": [last + pd.Timedelta(hours=1)],
            "open": [100.0], "high": [100.01], "low": [99.99],
            "close": [100.0], "volume": [10.0],
        })
        self.candles = pd.concat([self.candles, new], ignore_index=True)

    def heartbeat(self, advance: bool = True) -> dict:
        """一次完整 bot.process();advance=True 时先推进一根 K 线。"""
        if advance:
            self.advance_candle()
        self.bot.process()
        self.heartbeats += 1
        return self.snapshot()

    # ------------------------------------------------------------ 观察接口
    def snapshot(self) -> dict:
        from freqtrade.persistence import Trade
        from rl_platform.execution_state import get_live_execution_snapshot

        trades = Trade.get_trades_proxy(is_open=True)
        snap = get_live_execution_snapshot(PAIR)
        orders = []
        for t in trades:
            for o in t.orders:
                orders.append({
                    "order_id": o.order_id, "side": o.ft_order_side,
                    "status": o.status, "ft_is_open": o.ft_is_open,
                    "amount": o.safe_amount, "filled": o.safe_filled,
                    "remaining": o.safe_remaining, "price": o.safe_price,
                    "cancel_reason": o.ft_cancel_reason,
                })
        last_analyzed, _ = self.bot.dataprovider.get_analyzed_dataframe(
            PAIR, TIMEFRAME)
        signals = {
            "enter_last": int(last_analyzed["enter_long"].iloc[-1])
            if last_analyzed is not None and len(last_analyzed) else None,
            "exit_last": int(last_analyzed["exit_long"].iloc[-1])
            if last_analyzed is not None and len(last_analyzed) else None,
        }
        return {
            "heartbeat": self.heartbeats,
            "state": snap.state,
            "filled_amount": snap.filled_amount,
            "model_position": snap.model_position,
            "n_open_trades": len(trades),
            "trade_amount": trades[0].amount if trades else 0.0,
            "trade_stake": trades[0].stake_amount if trades else 0.0,
            "orders": orders,
            "open_order_ids": [o["order_id"] for o in orders if o["ft_is_open"]],
            "n_created_orders": len(self.fake.created_calls),
            "n_cancel_calls": len(self.fake.cancel_calls),
            "signals": signals,
        }
