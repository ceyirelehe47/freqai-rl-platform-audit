"""阶段 2.5.2a 更新版 parity 测试(原 bar 内一 tick 执行合同已被废弃)。

旧合同(阶段 2.5.2 工作包 D,已废弃为 legacy_noncausal_not_for_training):
- 请求滑点价触及当根 high/low 边界时按 tick 向 bar 内移动保证当根成交;
- 依赖执行 K 线最终 high/low 修改成交价——未来信息泄漏,违反因果成交。

新合同(market_open_causal,阶段 2.5.2a 任务书第一节):
- 策略 entry/exit 均市场订单,回测以 open[t+1] 成交(backtesting.py:1039-1057
  仅 limit 走 custom price;:596 exit_signal close_rate=open;:551-567 shift(1));
- 环境成交价 = buy ceil_to_tick / sell floor_to_tick(open*(1±simulated_bps/1e4)),
  不依赖 high/low;
- 精确 parity 只在 simulated_slippage_bps = 0 时要求(成交价恒等于 open);
- 旧七轮(含非零滑点与非法窄 K 线构造)在阶段 2.5.2a 报告十八节列出并说明。

本文件保留:
1. 零滑点市场订单完整 parity(宽/零振幅,完整路径对比);
2. bar_executable_price 函数级性质测试(legacy 函数,price_clamp.py 保留,
   仅供历史回归,不在生产调用路径)。
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

STRAT_TMPL = '''"""测试壳:复用真实 RouteCStrategy(市场订单 + 信号路径)。"""
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
    """确定性合成数据,价格全部落在 tick(0.01)网格上,全部合法 OHLC。

    mode:
    - wide: 宽 K 线(high/low 在 body 外留 0.5% 余量);
    - doji: 零振幅(open == high == low == close,合法 OHLC 最小形态)。
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
    """环境侧重放:market_open_causal(默认)+ 零模拟滑点。"""
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
        identifier = f"test252a-update-{fee}-{mode}"
        freqai = conf["freqai"]
        freqai["identifier"] = identifier
        freqai["train_period_days"] = 30
        freqai["backtest_period_days"] = 7
        freqai["activate_tensorboard"] = False
        assert freqai["route_c"]["simulated_slippage_bps"] == 0.0
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
    """完整 parity 对比(不得只比较成交子集)。"""
    trades = result["trades"]
    infos = result["infos"]
    targets = result["targets"]
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
        f"{name}: 完整路径不一致"
    )

    env_final = infos[-1]["equity_end"]
    E = 1.0
    W = 1.0
    for k, (t, b, s) in enumerate(
        zip(trades.iterrows(), buys, sells, strict=True)
    ):
        _, tr = t
        assert str(tr["open_date"]) == str(b["execution_time"])
        assert str(tr["close_date"]) == str(s["execution_time"])
        assert math.isclose(float(tr["open_rate"]), b["exec_price"], rel_tol=1e-12,
                            abs_tol=1e-12)
        assert math.isclose(float(tr["close_rate"]), s["exec_price"], rel_tol=1e-12,
                            abs_tol=1e-12)
        # 因果合同零滑点恒等式:成交价 == 执行 bar 的 open(与 high/low 无关)
        tick_i = b["execution_tick"]
        assert b["exec_price"] == pytest.approx(
            result["merged"]["open"].iloc[tick_i]), \
            f"{name}#{k} env entry 价 != open"
        assert abs(float(tr["profit_ratio"]) - s["cash"] / b["equity_start"] + 1.0) \
            <= 1e-7
        R = s["cash"] / b["equity_start"]
        E *= R
        W *= (R * (1.0 + fee) - fee)
        report.append(
            f"- #{k}: entry {tr['open_date']} @ {tr['open_rate']:.2f}"
            f" / exit {tr['close_date']} @ {tr['close_rate']:.2f}"
        )

    assert abs(env_final - 100.0 * E) < 1e-9 * max(1.0, abs(E))
    assert abs(result["final_wallet"] - 100.0 * W) < 5e-6 * max(1, len(trades))
    report.append(
        f"- 终值: env {env_final:.8f} / bt {result['final_wallet']:.8f}"
    )
    return report


PARITY_ROUNDS = [
    ("fee0_slip0_wide", 0.0, "wide"),
    ("fee001_slip0_wide", 0.001, "wide"),
    ("fee001_slip0_doji", 0.001, "doji"),
]


def test_market_order_zero_slip_parity_rounds():
    """零滑点市场订单三轮完整 parity(阶段 2.5.2a 因果合同)。"""
    ART.mkdir(parents=True, exist_ok=True)
    report = [
        "# 阶段 2.5.2a 更新:market_open_causal 零滑点市场订单 parity",
        "",
        "旧 bar 内一 tick 执行合同(依赖执行 K 线最终 high/low)已废弃为",
        "legacy_noncausal_not_for_training;详见 artifacts 与 2.5.2a 报告。",
        "",
    ]
    summary = {}
    for name, fee, mode in PARITY_ROUNDS:
        result = run_bt_round(fee, mode=mode)
        lines = compare_round(name, fee, result)
        report.extend(lines)
        report.append("")
        summary[name] = {
            "fee": fee, "simulated_slippage_bps": 0.0, "mode": mode,
            "n_trades": int(len(result["trades"])),
            "final_wallet": result["final_wallet"],
        }
    report.append("## 结论")
    report.append("- 三轮(宽/零振幅/零费)信号数/交易数/时间/价格(1e-12)/"
                  "单笔收益全部逐笔一致。")
    (ART / "full_fill_parity.md").write_text("\n".join(report), encoding="utf-8")
    (ART / "narrow_bar_full_parity.json").write_text(
        json.dumps({
            "note": "阶段 2.5.2a:旧的窄 K 线/非零滑点 parity 轮随 bar 内调价"
                    "合同一并废弃(非因果);本文件记录零滑点市场订单轮。",
            "rounds": summary,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, s in summary.items():
        assert s["n_trades"] > 0, f"{name} 无交易"


def test_execution_contract_unit_properties():
    """legacy 函数级性质测试:bar_executable_price 保留在 price_clamp.py,
    仅供历史回归(legacy_noncausal_not_for_training,不在生产调用路径)。"""
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
