"""工作包 D:bar 内一 tick 执行合同的完整成交 parity(任务书十三/十四节)。

执行合同(推荐方案):
- 请求滑点价触及当根 high/low 边界时,按价格精度向 bar 内部移动至少一个
  tick(买入严格小于 high、卖出严格大于 low),保证回测器闭区间撮合语义
  (_get_order_filled: low <= rate <= high)下下单当根成交;
- bar 范围容纳不下内部价(单 tick/零振幅 bar)时 fallback 为当根 open
  (源码依据:entry min(rate,high)、exit max(rate,low) 允许边界价,
  open∈[low,high] 恒可成交);
- 环境与 RouteCStrategy 使用同一公共执行价格函数
  (rl_platform.price_clamp.bar_executable_price);
- 数据价格全部落在 tick 网格上(真实市场亦然),fallback 价 = open 在
  两侧严格一致。

七轮(任务书十四节):
    fee0_slip0 / fee001_slip0 / fee001_slip5bps / fee001_slip10bps
    / 窄K线+5bps(±0.5bps 振幅,tick 空间混合 1-2 tick:
      单 tick bar 走 fallback、2 tick bar 走内移一 tick)
    / 窄K线+10bps / 零振幅K线(全程 fallback open)

每轮比较(不得只比较成交子集):
    信号数量 / entry order 数 / exit order 数 / 完成交易数 /
    每笔 entry 时间与价格 / 每笔 exit 时间与价格 / 每笔收益 /
    最终环境净值 / 最终 Freqtrade 钱包(逐笔递推闭式 + 精度截断预算)。
"""

import json
import math
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from rl_platform.env import AlignedLongFlatEnv
from rl_platform.price_clamp import bar_executable_price
from rl_platform.signal_convert import targets_to_signals

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2"
ROOT = ART.parents[1]
TEMPLATE = ROOT / "experiments" / "freqai_rl_stage2_5_2" / "configs" / "config_stage252.template.json"
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

STRAT_TMPL = '''"""测试壳:复用真实 RouteCStrategy(执行合同价格 + 信号路径)。"""
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
    """确定性合成数据,价格全部落在 tick(0.01)网格上。

    mode:
    - wide: high/low = max/min(open,close)*(1±0.5%),请求 5/10bps 远在内部;
    - narrow: high/low = open*(1±0.5bps);价格 ~100 时 tick 空间 1-2 tick,
      单 tick bar 触发 fallback open、双 tick bar 内移一 tick;
    - doji: open=high=low=close(零振幅),全程 fallback open。
    """
    n = N_DAYS * 24
    idx = pd.date_range(DATA_START, periods=n, freq="1h", tz="UTC")
    step = np.sin(np.arange(n) / 24.0 * 2.0 * np.pi) * 0.002
    close = 100.0 * np.exp(np.cumsum(np.log1p(step)))
    open_ = np.empty(n)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    if mode == "doji":
        high = open_.copy()
        low = open_.copy()
        close = open_.copy()
    else:
        margin = 0.00005 if mode == "narrow" else 0.005
        if mode == "narrow":
            high = open_ * (1 + margin)
            low = open_ * (1 - margin)
        else:
            high = np.maximum(open_, close) * (1 + margin)
            low = np.minimum(open_, close) * (1 - margin)
    # 规范化到十进制网格浮点:与 price_to_precision 往返及 bar_executable_price
    # 的输出保持同一浮点,消除恰等边界上的 1 ulp 漂移(见 price_clamp._canon)
    snap = lambda a: np.round(np.round(a / TICK).astype(np.int64) * TICK, 10)
    open_, high, low, close = snap(open_), snap(high), snap(low), snap(close)
    if mode == "narrow":
        # 窄 K 线轮不做 max/min(open, close) 调和:小时级价格步长(~0.2%)远大于
        # ±0.5bps margin,调和会把 bar 撑回宽 bar,限制场景失效。
        # (与阶段 2.5.1 窄轮同一构造方式:收窄构造,不是扩大 high/low 绕过问题)
        pass
    else:
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame({
        "date": idx, "open": open_, "high": high, "low": low,
        "close": close, "volume": np.full(n, 10.0),
    })


def load_cached_targets(userdir: Path, identifier: str) -> pd.DataFrame:
    pred_dir = userdir / "models" / identifier / "backtesting_predictions"
    frames = []
    for f in sorted(pred_dir.glob("cb_syn_*_prediction.feather"),
                    key=lambda p: int(p.name.split("_")[2])):
        df = pd.read_feather(f)
        frames.append(df[["date", "&-target_position", "do_predict"]])
    full = pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)
    return full


def env_replay(ohlc: pd.DataFrame, targets: pd.DataFrame, fee: float,
               slippage_bps: float) -> list[dict]:
    """环境侧重放:同一执行合同(price_tick=TICK)。"""
    merged = targets.merge(
        ohlc[["date", "open", "high", "low", "close"]], on="date", how="left"
    )
    assert merged[["open", "high", "low", "close"]].notna().all().all()
    n = len(merged)
    feats = pd.DataFrame(np.zeros((n, 2)), columns=["f0", "f1"])
    env = AlignedLongFlatEnv(
        features=feats, prices=merged[["open", "high", "low", "close"]],
        fee=fee, slippage_bps=slippage_bps, window_size=1,
        dates=merged["date"], price_tick=TICK,
    )
    env.reset()
    infos = []
    for i in range(n - 1):
        _, _, terminated, _, info = env.step(int(merged["&-target_position"].iloc[i]))
        infos.append(info)
        if terminated:
            break
    return infos


def run_bt_round(fee: float, slippage_bps: float, mode: str = "wide") -> dict:
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
        identifier = f"test252-rc-{fee}-{slippage_bps}-{mode}"
        freqai = conf["freqai"]
        freqai["identifier"] = identifier
        freqai["train_period_days"] = 30
        freqai["backtest_period_days"] = 7
        freqai["activate_tensorboard"] = False
        freqai["route_c"]["slippage_bps"] = slippage_bps
        freqai["route_c"]["price_tick"] = TICK
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
        infos = env_replay(data, targets, fee, slippage_bps)
        return {
            "trades": trades, "infos": infos, "targets": targets,
            "final_wallet": float(bt.wallets.get_total("USDT")),
            "identifier": identifier, "mode": mode,
        }


def compare_round(name: str, fee: float, slip: float, result: dict) -> list[str]:
    """十四节完整 parity 对比:不得只比较成交子集。"""
    trades = result["trades"]
    infos = result["infos"]
    targets = result["targets"]
    buys = [i for i in infos if i["trade_direction"] == "buy"]
    sells = [i for i in infos if i["trade_direction"] in ("sell", "liquidate")]

    # 信号数量(与两侧成交数一致)
    sig_df = targets_to_signals(
        targets.copy(), initial_position=0)
    n_enter_sig = int(sig_df["enter_long"].sum())
    n_exit_sig = int(sig_df["exit_long"].sum())

    report = [f"## {name}(fee={fee}, slip={slip}bps, mode={result['mode']})", ""]
    report.append(
        f"- 信号: enter {n_enter_sig} / exit {n_exit_sig};"
        f" 回测交易 {len(trades)};环境买入 {len(buys)} 卖出(含清算) {len(sells)}"
    )
    # 完整路径一致:信号数 == 交易数 == 环境成交数(不允许子集)
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
        # 时间完全一致
        assert str(tr["open_date"]) == str(b["execution_time"]), \
            f"{name}#{k} entry 时间: {tr['open_date']} vs {b['execution_time']}"
        assert str(tr["close_date"]) == str(s["execution_time"]), \
            f"{name}#{k} exit 时间: {tr['close_date']} vs {s['execution_time']}"
        # 价格一致(两侧同一执行合同函数,同一 tick 网格)
        assert math.isclose(float(tr["open_rate"]), b["exec_price"], rel_tol=1e-12,
                            abs_tol=1e-12), \
            f"{name}#{k} entry 价: {tr['open_rate']} vs {b['exec_price']}"
        assert math.isclose(float(tr["close_rate"]), s["exec_price"], rel_tol=1e-12,
                            abs_tol=1e-12), \
            f"{name}#{k} exit 价: {tr['close_rate']} vs {s['exec_price']}"
        # 单笔收益一致(同公式;回测 amount 精度截断 1e-8)
        assert abs(float(tr["profit_ratio"]) - s["cash"] / b["equity_start"] + 1.0) \
            <= 1e-7, f"{name}#{k} profit_ratio: {tr['profit_ratio']} vs env"
        R = s["cash"] / b["equity_start"]
        E *= R
        W *= (R * (1.0 + fee) - fee)
        report.append(
            f"- #{k}: entry {tr['open_date']} @ {tr['open_rate']:.2f}"
            f" / exit {tr['close_date']} @ {tr['close_rate']:.2f}"
            f"(env {b['exec_price']:.2f}/{s['exec_price']:.2f})"
            f"{' [fallback]' if b.get('price_fallback') or s.get('price_fallback') else ''}"
            f"{' [moved]' if b.get('price_moved_inside') or s.get('price_moved_inside') else ''}"
        )

    # 终值:环境 = 逐笔递推 E;回测 = 逐笔递推 W(stake 口径差 +
    # amount 精度截断,预算 5e-6/笔,与阶段 2.5.1 同口径)
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
    ("fee0_slip0", 0.0, 0.0, "wide"),
    ("fee001_slip0", 0.001, 0.0, "wide"),
    ("fee001_slip5bps", 0.001, 5.0, "wide"),
    ("fee001_slip10bps", 0.001, 10.0, "wide"),
    ("narrow_slip5bps", 0.001, 5.0, "narrow"),
    ("narrow_slip10bps", 0.001, 10.0, "narrow"),
    ("zero_amplitude_slip5bps", 0.001, 5.0, "doji"),
]


def test_full_fill_parity_all_rounds():
    """七轮完整 parity(工作包 D 十四节验收)。"""
    ART.mkdir(parents=True, exist_ok=True)
    report = ["# bar 内一 tick 执行合同:完整成交 parity(阶段 2.5.2 工作包 D)", ""]
    summary = {}
    for name, fee, slip, mode in PARITY_ROUNDS:
        result = run_bt_round(fee, slip, mode=mode)
        lines = compare_round(name, fee, slip, result)
        report.extend(lines)
        report.append("")
        buys = [i for i in result["infos"] if i["trade_direction"] == "buy"]
        summary[name] = {
            "fee": fee, "slippage_bps": slip, "mode": mode,
            "n_trades": int(len(result["trades"])),
            "n_env_buys": len(buys),
            "n_fallback_buys": sum(1 for b in buys if b["price_fallback"]),
            "n_moved_buys": sum(1 for b in buys if b["price_moved_inside"]),
            "final_wallet": result["final_wallet"],
            "final_equity_env": result["infos"][-1]["equity_end"],
        }
    report.append("## 结论")
    report.append("- 七轮(含窄 K 线两轮与零振幅一轮)信号数/订单数/交易数/"
                  "时间/价格/单笔收益全部逐笔一致,无成交子集比较。")
    report.append("- 终值差完全由已知口径解释:stake 逐笔递推 W 与环境 E 的"
                  "费差闭式 + amount 精度截断预算。")
    (ART / "full_fill_parity.md").write_text("\n".join(report), encoding="utf-8")
    (ART / "narrow_bar_full_parity.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    # 窄 K 线与零振幅轮必须真正走到合同的边界分支(fallback/moved),
    # 否则数据构造失效(等于没有验证执行合同)
    narrow5 = summary["narrow_slip5bps"]
    assert narrow5["n_fallback_buys"] + narrow5["n_moved_buys"] > 0, \
        "窄 K 线轮没有任何成交触发边界分支"
    doji = summary["zero_amplitude_slip5bps"]
    assert doji["n_fallback_buys"] == doji["n_env_buys"] > 0, \
        "零振幅轮应全部 fallback open"


def test_execution_contract_unit_properties():
    """执行合同函数单元性质(与回测器撮合语义对照)。"""
    # 常规宽 bar:请求价远离边界 -> 原请求价(tick 对齐)
    p, req, moved, fb = bar_executable_price("buy", 100.00, 100.50, 99.50, 5.0, TICK)
    assert p == pytest.approx(100.05) and not moved and not fb
    # 请求触及 high(k_req == k_high)-> 内移一 tick,严格小于 high
    p, req, moved, fb = bar_executable_price("buy", 100.00, 100.05, 99.50, 5.0, TICK)
    assert p == pytest.approx(100.04) and moved and not fb
    assert p < 100.05
    # 卖出触及 low(k_req == k_low)-> 上移一 tick,严格大于 low
    p, req, moved, fb = bar_executable_price("sell", 100.00, 100.50, 99.95, 5.0, TICK)
    assert p == pytest.approx(99.96) and moved and not fb
    assert p > 99.95
    # 单 tick bar:无法提供内部价 -> fallback open(仍满足闭区间撮合)
    p, req, moved, fb = bar_executable_price("buy", 100.00, 100.00, 100.00, 5.0, TICK)
    assert p == 100.00 and fb
    p, req, moved, fb = bar_executable_price("sell", 100.00, 100.00, 100.00, 5.0, TICK)
    assert p == 100.00 and fb
    # 0bps 恒等(镜像回测器 custom==propose 的恒等路径)
    p, req, moved, fb = bar_executable_price("buy", 100.00, 100.00, 100.00, 0.0, TICK)
    assert p == 100.00 and not moved and not fb
    # 记录请求滑点与实际应用滑点(任务书十三节)
    p, req, moved, fb = bar_executable_price("buy", 100.00, 100.01, 100.00, 5.0, TICK)
    applied_bps = (p / 100.00 - 1.0) * 10000.0
    assert applied_bps < 5.0, "触界时实际应用滑点必须小于请求滑点"
