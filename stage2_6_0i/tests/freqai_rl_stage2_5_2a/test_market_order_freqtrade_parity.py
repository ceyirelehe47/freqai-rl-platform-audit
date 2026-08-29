"""工作包 B:市场订单零滑点 Freqtrade parity(execution_mode=market_open_causal)。

精确 parity 只在 simulated_slippage_bps = 0 时要求(任务书 B.3):
    信息截至 t -> 信号位于 t -> 市场订单在 open[t+1] 执行。

源码依据(freqtrade 2026.7, commit 52bc96f):
- backtesting.py:551-567:信号列 shift(1),信号 t 移到执行行 t+1;
- backtesting.py:1039-1057:custom_entry_price 仅 order_type=="limit" 分支,
  市场订单 propose_rate 保持 row[OPEN_IDX];
- backtesting.py:596:exit_signal 的 close_rate = row[OPEN_IDX];
- backtesting.py:788-789:_get_order_filled 闭区间 low<=rate<=high,
  合法 OHLC 下 open 恒在区间内 -> 下单当根成交;
- exchange.py:1042 price_to_precision(ROUND):出场侧价格精度往返,
  数据价格 snap 到 tick 网格后不变。

轮次(全部零模拟滑点):
    fee0_slip0 / fee001_slip0(宽 K 线)
    legal_narrow_slip0(合法窄 K 线:bar 区间恰为 body,1 tick 宽)
    zero_amplitude_slip0(合法零振幅 K 线)
窄 K 线不再需要任何"调价保证成交"——因果合同根本不读取 high/low。

每轮比较(不得只比较成交子集):信号数/entry 数/exit 数/完成交易数/
每笔 entry-exit 时间与价格(1e-12)/单笔收益/最终净值(递推闭式+精度预算)。

simulated_slippage_bps > 0 的压力轮在 test_simulated_slippage_monotonicity
单独验证(只验证公式与成本单调性,不声称 Freqtrade 已复现该模拟滑点)。
"""

import json
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from legal_ohlc import assert_legal_ohlc
from rl_platform.env import AlignedLongFlatEnv
from rl_platform.signal_convert import targets_to_signals

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"
ROOT = ART.parents[1]
TEMPLATE = ROOT / "experiments" / "freqai_rl_stage2_5_2a" / "configs" / \
    "config_stage252a.template.json"
PAIR = "SYN/USDT"
TIMERANGE = "20260715-20260801"
DATA_START = "2026-06-01T00:00:00Z"
N_DAYS = 61
TICK = 0.01

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

MODEL_TMPL = '''"""测试级 scripted 适配(非生产路径):覆盖 fit 返回确定性策略。"""
import sys

PROJ = r"{proj_root}"
for p in (PROJ + "/src", PROJ + "/user_data/freqaimodels"):
    if p not in sys.path:
        sys.path.insert(0, p)

from RouteCModel import RouteCModel  # noqa: E402
from rl_platform.inference import ScriptedPolicy  # noqa: E402


class ScriptedRouteCModel(RouteCModel):
    """fit 返回 ScriptedPolicy(%-ret-4 标准化值 > 0 -> 目标 1)。"""

    def fit(self, data_dictionary, dk, **kwargs):
        cols = list(data_dictionary["train_features"].columns)
        idx = cols.index("%-ret-4")
        return ScriptedPolicy(feature_index=idx, threshold=0.0)
'''

STRAT_TMPL = '''"""测试壳:复用真实 RouteCStrategy(市场订单 + live/backtest 双信号路径)。"""
import sys

PROJ = r"{proj_root}"
p = PROJ + "/user_data/strategies"
if p not in sys.path:
    sys.path.insert(0, p)

from RouteCStrategy import RouteCStrategy as _Base  # noqa: E402


class RouteCStrategyShell(_Base):
    pass
'''


def make_data(mode: str) -> pd.DataFrame:
    """确定性合成数据,价格全部 snap 到 tick(0.01)网格,全部合法 OHLC。

    mode:
    - wide: 宽 K 线(high/low 在 body 外留 0.5% 余量);
    - legal_narrow: 合法窄 K 线(close 相对 open 每根 ±1 tick,
      high == max(open, close), low == min(open, close):区间恰为 body);
    - doji: 零振幅(open == high == low == close)。
    """
    n = N_DAYS * 24
    idx = pd.date_range(DATA_START, periods=n, freq="1h", tz="UTC")
    if mode == "legal_narrow":
        # 每根 ±1 tick 的(种子固定)随机步长:body 恒 1 tick 宽,
        # 且与 %-ret-4 等特征周期不共振(交替步长会让 ret-4 恒零被剔除)
        rng = np.random.default_rng(3)
        steps = rng.choice([TICK, -TICK], size=n)
        close = 100.0 + np.cumsum(steps)
    else:
        step = np.sin(np.arange(n) / 24.0 * 2.0 * np.pi) * 0.002
        close = 100.0 * np.exp(np.cumsum(np.log1p(step)))
    open_ = np.empty(n)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    if mode == "doji":
        high = open_.copy()
        low = open_.copy()
        close = open_.copy()
    elif mode == "legal_narrow":
        high = np.maximum(open_, close)
        low = np.minimum(open_, close)
    else:
        high = np.maximum(open_, close) * 1.005
        low = np.minimum(open_, close) * 0.995
    snap = lambda a: np.round(np.round(a / TICK).astype(np.int64) * TICK, 10)
    open_, high, low, close = snap(open_), snap(high), snap(low), snap(close)
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    df = pd.DataFrame({
        "date": idx, "open": open_, "high": high, "low": low,
        "close": close, "volume": np.full(n, 10.0),
    })
    assert_legal_ohlc(df)
    return df


def load_cached_targets(userdir: Path, identifier: str) -> pd.DataFrame:
    pred_dir = userdir / "models" / identifier / "backtesting_predictions"
    frames = []
    for f in sorted(pred_dir.glob("cb_syn_*_prediction.feather"),
                    key=lambda p: int(p.name.split("_")[2])):
        df = pd.read_feather(f)
        frames.append(df[["date", "&-target_position", "do_predict"]])
    full = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
    return full


def env_replay(ohlc: pd.DataFrame, targets: pd.DataFrame, fee: float
               ) -> tuple[list[dict], pd.DataFrame]:
    """环境侧重放:market_open_causal(默认)+ 零模拟滑点 + tick 网格。"""
    merged = targets.merge(
        ohlc[["date", "open", "close"]], on="date", how="left"
    )
    assert merged[["open", "close"]].notna().all().all()
    n = len(merged)
    feats = pd.DataFrame(np.zeros((n, 2)), columns=["f0", "f1"])
    env = AlignedLongFlatEnv(
        features=feats, prices=merged[["open", "close"]],
        fee=fee, slippage_bps=0.0, window_size=1,
        dates=merged["date"], price_tick=TICK,
    )
    env.reset()
    infos = []
    for i in range(n - 1):
        _, _, terminated, _, info = env.step(int(merged["&-target_position"].iloc[i]))
        infos.append(info)
        if terminated:
            break
    return infos, merged


def run_bt_round(fee: float, mode: str = "wide") -> dict:
    data = make_data(mode)
    with tempfile.TemporaryDirectory() as tmp:
        userdir = Path(tmp) / "user_data"
        strat_dir = userdir / "strategies"
        model_dir = userdir / "freqaimodels"
        data_dir = Path(tmp) / "data" / "binanceus"
        for d in (strat_dir, model_dir, data_dir):
            d.mkdir(parents=True)
        proj_root = str(ROOT).replace("\\", "/")
        (model_dir / "ScriptedRouteCModel.py").write_text(
            MODEL_TMPL.format(proj_root=proj_root))
        (strat_dir / "RouteCStrategyShell.py").write_text(
            STRAT_TMPL.format(proj_root=proj_root))
        data.to_feather(data_dir / "SYN_USDT-1h.feather")

        import freqtrade.exchange as ftx
        from freqtrade.optimize.backtesting import Backtesting

        def fake_reload(self, reload=False, load_leverage_tiers=False):
            self._markets = dict(FAKE_MARKETS)
            self._api.markets = dict(FAKE_MARKETS)
            self._api.markets_by_id = {}
            return None

        conf = json.loads(TEMPLATE.read_text())
        identifier = f"test252a-rc-{fee}-{mode}"
        freqai = conf["freqai"]
        freqai["identifier"] = identifier
        freqai["train_period_days"] = 30
        freqai["backtest_period_days"] = 7
        freqai["activate_tensorboard"] = False
        assert freqai["route_c"]["simulated_slippage_bps"] == 0.0
        assert freqai["route_c"]["execution_mode"] == "market_open_causal"
        conf["fee"] = fee
        conf["exchange"]["pair_whitelist"] = [PAIR]
        config_path = Path(tmp) / "config.json"
        config_path.write_text(json.dumps(conf, indent=2))
        conf["config_files"] = [str(config_path)]
        conf.update({
            "datadir": data_dir, "user_data_dir": userdir,
            "strategy": "RouteCStrategyShell", "strategy_path": str(strat_dir),
            "freqaimodel": "ScriptedRouteCModel",
            "timerange": TIMERANGE, "runmode": "backtest",
            "db_url": f"sqlite:///{tmp}/bt.db", "export": "none", "cache": "none",
        })

        with patch.object(ftx.Exchange, "reload_markets", fake_reload):
            bt = Backtesting(conf)
            bt.start()
        content = bt.all_bt_content["RouteCStrategyShell"]
        trades = content["results"]
        targets = load_cached_targets(userdir, identifier)
        infos, merged = env_replay(data, targets, fee)
        return {
            "trades": trades, "infos": infos, "targets": targets,
            "final_wallet": float(bt.wallets.get_total("USDT")),
            "identifier": identifier, "mode": mode, "data": data,
            "merged": merged,
        }


def compare_round(name: str, fee: float, result: dict) -> list[str]:
    """完整 parity 对比:不得只比较成交子集。"""
    trades = result["trades"]
    infos = result["infos"]
    targets = result["targets"]
    data = result["data"]
    buys = [i for i in infos if i["trade_direction"] == "buy"]
    sells = [i for i in infos if i["trade_direction"] in ("sell", "liquidate")]

    sig_df = targets_to_signals(targets.copy(), initial_position=0)
    n_enter_sig = int(sig_df["enter_long"].sum())
    n_exit_sig = int(sig_df["exit_long"].sum())

    report = [f"## {name}(fee={fee}, mode={result['mode']})", ""]
    report.append(
        f"- 信号: enter {n_enter_sig} / exit {n_exit_sig};"
        f" 回测交易 {len(trades)};环境买入 {len(buys)} 卖出(含清算) {len(sells)}"
    )
    assert n_enter_sig == n_exit_sig == len(trades) == len(buys) == len(sells), (
        f"{name}: 完整路径不一致 sig_enter={n_enter_sig} sig_exit={n_exit_sig} "
        f"bt={len(trades)} env_buy={len(buys)} env_sell={len(sells)}"
    )

    env_final = infos[-1]["equity_end"]
    E = 1.0
    W = 1.0
    for k, (t, b, s) in enumerate(
        zip(trades.iterrows(), buys, sells, strict=True)
    ):
        _, tr = t
        assert str(tr["open_date"]) == str(b["execution_time"]), \
            f"{name}#{k} entry 时间: {tr['open_date']} vs {b['execution_time']}"
        assert str(tr["close_date"]) == str(s["execution_time"]), \
            f"{name}#{k} exit 时间: {tr['close_date']} vs {s['execution_time']}"
        assert math.isclose(float(tr["open_rate"]), b["exec_price"], rel_tol=1e-12,
                            abs_tol=1e-12), \
            f"{name}#{k} entry 价: {tr['open_rate']} vs {b['exec_price']}"
        assert math.isclose(float(tr["close_rate"]), s["exec_price"], rel_tol=1e-12,
                            abs_tol=1e-12), \
            f"{name}#{k} exit 价: {tr['close_rate']} vs {s['exec_price']}"
        # 因果合同零滑点恒等式:成交价 == 执行 bar 的 open(与 high/low 无关)
        tick_i = b["execution_tick"]
        assert b["exec_price"] == pytest.approx(
            result["merged"]["open"].iloc[tick_i]), \
            f"{name}#{k} env entry 价 != open"
        assert abs(float(tr["profit_ratio"]) - s["cash"] / b["equity_start"] + 1.0) \
            <= 1e-7, f"{name}#{k} profit_ratio: {tr['profit_ratio']} vs env"
        R = s["cash"] / b["equity_start"]
        E *= R
        W *= (R * (1.0 + fee) - fee)
        report.append(
            f"- #{k}: entry {tr['open_date']} @ {tr['open_rate']:.2f}"
            f" / exit {tr['close_date']} @ {tr['close_rate']:.2f}"
            f"(env {b['exec_price']:.2f}/{s['exec_price']:.2f})"
        )

    assert abs(env_final - 100.0 * E) < 1e-9 * max(1.0, abs(E)), \
        f"{name} 环境终值与逐笔递推不符: {env_final} vs {100.0 * E}"
    assert abs(result["final_wallet"] - 100.0 * W) < 5e-6 * max(1, len(trades)), \
        f"{name} 回测终值与递推不符: {result['final_wallet']} vs {100.0 * W}"
    diff = env_final - result["final_wallet"]
    report.append(
        f"- 终值: env {env_final:.8f} / bt {result['final_wallet']:.8f},"
        f" 差 {diff:.3e}(递推口径差 E-W = {100.0 * (E - W):.3e})"
    )
    return report


PARITY_ROUNDS = [
    ("fee0_slip0_wide", 0.0, "wide"),
    ("fee001_slip0_wide", 0.001, "wide"),
    ("legal_narrow_slip0", 0.001, "legal_narrow"),
    ("zero_amplitude_slip0", 0.001, "doji"),
]


def test_market_order_zero_slippage_parity():
    """工作包 B 验收:零模拟滑点市场订单四轮完整 parity。"""
    ART.mkdir(parents=True, exist_ok=True)
    report = [
        "# market_open_causal 零滑点市场订单 parity(阶段 2.5.2a 工作包 B)",
        "",
        "执行合同:信息截至 t -> 信号 t -> 市场订单 open[t+1] 成交;",
        "Freqtrade 源码:信号 shift(1)(backtesting.py:551-567),市场单",
        "propose_rate=open(:1039-1057 仅 limit 走 custom price),exit_signal",
        "close_rate=open(:596),_get_order_filled 闭区间(:788-789)。",
        "",
    ]
    summary = {}
    for name, fee, mode in PARITY_ROUNDS:
        result = run_bt_round(fee, mode=mode)
        lines = compare_round(name, fee, result)
        report.extend(lines)
        report.append("")
        buys = [i for i in result["infos"] if i["trade_direction"] == "buy"]
        summary[name] = {
            "fee": fee, "simulated_slippage_bps": 0.0, "mode": mode,
            "n_trades": int(len(result["trades"])),
            "n_env_buys": len(buys),
            "final_wallet": result["final_wallet"],
            "final_equity_env": result["infos"][-1]["equity_end"],
        }
    report.append("## 结论")
    report.append("- 四轮(宽/合法窄/零振幅/零费)信号数/交易数/时间/价格(1e-12)/"
                  "单笔收益全部逐笔一致,无成交子集比较。")
    report.append("- 零滑点下成交价恒等于执行 bar 的 open,与 high/low 无关;")
    report.append("- 终值差完全由已知口径解释:stake 逐笔递推 W 与环境 E 的"
                  "费差闭式 + amount 精度截断预算(5e-6/笔)。")
    report.append("- 非零 simulated_slippage_bps 属训练/离线压力环境,"
                  "不声称 Freqtrade 已精确复现(见 simulated_slippage_monotonicity.json)。")
    (ART / "zero_slippage_freqtrade_parity.md").write_text(
        "\n".join(report), encoding="utf-8")
    (ART / "market_order_parity_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    # 每轮都必须真实产生交易(空转轮等于没验证)
    for name, s in summary.items():
        assert s["n_trades"] > 0, f"{name} 无交易,parity 数据构造失效"
        assert s["n_env_buys"] == s["n_trades"]
