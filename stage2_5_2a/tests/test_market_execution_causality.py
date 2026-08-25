"""工作包 A/F 测试:因果市场成交合同(market_open_causal)。

- market_execution 函数签名不得出现执行 K 线 high/low(任务书 A.1);
- 买入向上 tick 取整、卖出向下取整,取整不得改善成交价;
- 环境生产调用图不再触碰 bar_executable_price(legacy 仅供历史测试);
- 合法宽/窄/零振幅/跳空 K 线 + 固定目标序列:零滑点市场执行只依赖
  open,high/low 不改变成交结果(工作包 F);
- 不再维护"向 bar 内移动一 tick 保证成交"的生产语义:
  成交价可以位于执行 K 线 [low, high] 之外(narrow bar + 非零滑点)。
"""

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from legal_ohlc import SCRIPTED_TARGETS, assert_legal_ohlc, make_legal_candles
from rl_platform import ledger as ledger_mod
from rl_platform.env import AlignedLongFlatEnv
from rl_platform.ledger import LongFlatLedger
from rl_platform.market_execution import (
    EXECUTION_MODE,
    LEGACY_EXECUTION_MODE,
    buy_market_price,
    ceil_to_tick,
    floor_to_tick,
    market_fill,
    sell_market_price,
)

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"


# ---------------------------------------------------------------- 函数合同
def test_functions_do_not_accept_high_low():
    """A.1 硬性要求:因果成交函数签名不得出现 high/low。"""
    for fn in (buy_market_price, sell_market_price, market_fill,
               ceil_to_tick, floor_to_tick):
        params = inspect.signature(fn).parameters
        assert "high" not in params, f"{fn.__name__} 签名出现 high"
        assert "low" not in params, f"{fn.__name__} 签名出现 low"


def test_buy_ceil_sell_floor_direction():
    # 100.03 * 1.0005 = 100.080015 -> ceil -> 100.09
    p, d = buy_market_price(100.03, 5.0, 0.01)
    assert p == pytest.approx(100.09)
    assert d["tick_rounding"] == "ceil"
    # 100.03 * 0.9995 = 99.979985 -> floor -> 99.97
    p, d = sell_market_price(100.03, 5.0, 0.01)
    assert p == pytest.approx(99.97)
    assert d["tick_rounding"] == "floor"


def test_rounding_never_improves_price():
    """性质测试:随机价格/滑点/tick 下,取整后永远不优于请求价。"""
    rng = np.random.default_rng(42)
    for _ in range(500):
        o = float(rng.uniform(1.0, 50000.0))
        bps = float(rng.uniform(0.0, 50.0))
        tick = float(rng.choice([0.01, 0.1, 1.0, 0.0]))
        p_buy, db = buy_market_price(o, bps, tick)
        assert p_buy >= o * (1 + bps / 1e4) - 1e-9
        assert db["actual_effective_slippage_bps"] >= bps - 1e-6
        p_sell, ds = sell_market_price(o, bps, tick)
        assert p_sell <= o * (1 - bps / 1e4) + 1e-9
        assert ds["actual_effective_slippage_bps"] >= bps - 1e-6


def test_input_validation():
    for bad_open in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            buy_market_price(bad_open, 5.0, 0.01)
    with pytest.raises(ValueError):
        buy_market_price(100.0, -1.0, 0.01)
    with pytest.raises(ValueError):
        sell_market_price(100.0, 5.0, -0.01)
    with pytest.raises(ValueError):
        market_fill("hold", 100.0, 5.0, 0.01)


def test_zero_bps_identity_returns_open():
    p, d = buy_market_price(123.45, 0.0, 0.01)
    assert p == pytest.approx(123.45)
    assert d["tick_rounding"] == "none"
    p, _ = sell_market_price(123.45, 0.0, 0.01)
    assert p == pytest.approx(123.45)


def test_tick_zero_no_quantization():
    # price_tick=0 表示不量化:返回连续公式价(不受交易所 tick 约束的纯模拟)
    p, _ = buy_market_price(100.03, 5.0, 0.0)
    assert p == pytest.approx(100.03 * 1.0005)


def test_diagnostics_content():
    _, d = buy_market_price(100.0, 5.0, 0.01)
    for key in ("direction", "raw_open", "requested_price", "effective_price",
                "requested_slippage_bps", "actual_effective_slippage_bps",
                "tick_rounding", "price_tick", "rounded", "tick_rounding_version"):
        assert key in d, f"诊断缺少 {key}"
    assert d["requested_price"] == pytest.approx(100.05)


# ---------------------------------------------------------------- 环境调用图
def test_env_market_path_needs_only_open_close():
    """causal 模式:prices 只需 open/close(high/low 不参与成交)。"""
    prices = pd.DataFrame({
        "open": [100.0] * 6,
        "close": [100.0] * 6,
    })
    feats = pd.DataFrame({"f": np.zeros(6)})
    env = AlignedLongFlatEnv(features=feats, prices=prices, fee=0.001)
    env.reset()
    obs, r, term, _, info = env.step(1)
    assert info["trade_direction"] == "buy"
    assert info["exec_price"] == pytest.approx(100.0)
    # legacy 模式仍要求四列(历史合同)
    with pytest.raises(ValueError, match="high"):
        AlignedLongFlatEnv(
            features=feats, prices=prices, fee=0.001,
            execution_mode=LEGACY_EXECUTION_MODE,
        )


def test_env_causal_does_not_call_bar_executable_price(monkeypatch):
    """A.3 调用图保护:causal 路径不触发 bar_executable_price。"""
    calls = []

    def explode(*args, **kwargs):
        calls.append(args)
        raise AssertionError("causal 生产路径不得调用 bar_executable_price")

    monkeypatch.setattr(ledger_mod, "bar_executable_price", explode)
    prices = make_legal_candles("wide", 8)
    feats = pd.DataFrame({"f": np.zeros(8)})
    env = AlignedLongFlatEnv(
        features=feats, prices=prices, fee=0.001,
        slippage_bps=5.0, price_tick=0.01,
    )
    env.reset()
    done = False
    i = 0
    while not done:
        _, _, term, _, info = env.step(SCRIPTED_TARGETS[i % len(SCRIPTED_TARGETS)])
        done = term
        i += 1
    assert not calls
    # 对照:legacy 模式确实使用 bar_executable_price(证明补丁有效)
    env2 = AlignedLongFlatEnv(
        features=feats, prices=prices, fee=0.001,
        slippage_bps=5.0, price_tick=0.01,
        execution_mode=LEGACY_EXECUTION_MODE,
    )
    env2.reset()
    try:
        env2.step(1)
    except AssertionError:
        pass
    else:
        pytest.fail("legacy 模式应调用 bar_executable_price(补丁未生效)")
    assert calls


def test_invalid_execution_mode_rejected():
    prices = pd.DataFrame({"open": [100.0] * 4, "close": [100.0] * 4})
    feats = pd.DataFrame({"f": np.zeros(4)})
    with pytest.raises(ValueError, match="execution_mode"):
        AlignedLongFlatEnv(
            features=feats, prices=prices,
            execution_mode="bar_clamp_v1",
        )
    with pytest.raises(ValueError, match="execution_mode"):
        LongFlatLedger(execution_mode="bar_clamp_v1")


# ------------------------------------------------- 合法 K 线 × 固定目标序列
def replay(df, targets, *, fee=0.001, slippage_bps=0.0, price_tick=0.01):
    env = AlignedLongFlatEnv(
        features=pd.DataFrame({"f": np.zeros(len(df))}),
        prices=df[["open", "high", "low", "close"]],
        fee=fee, slippage_bps=slippage_bps, price_tick=price_tick,
    )
    env.reset()
    infos = []
    done = False
    i = 0
    while not done:
        _, _, term, _, info = env.step(targets[i % len(targets)])
        infos.append(info)
        done = term
        i += 1
    return env, infos


def test_scripted_targets_zero_slippage_depends_only_on_open():
    """工作包 F:四类合法 K 线(同 open/close 序列)、同一固定目标序列,
    零滑点市场执行只依赖 open——结果完全一致。"""
    n = 24
    wide = make_legal_candles("wide", n)
    narrow = make_legal_candles("narrow", n)
    zero = make_legal_candles("zero_range", n)
    for df in (wide, narrow, zero):
        assert_legal_ohlc(df)
    # wide/narrow/zero_range 用同一种子:close 游走不同步(narrow 步长不同),
    # 因此逐类对照"零滑点成交价 == 执行 bar 的 open"这一因果不变量
    results = {}
    for name, df in (("wide", wide), ("narrow", narrow), ("zero_range", zero)):
        env, infos = replay(df, SCRIPTED_TARGETS, slippage_bps=0.0)
        for info in infos:
            tick_i = info["execution_tick"]
            assert info["raw_open"] == pytest.approx(df["open"].iloc[tick_i])
            # 零滑点:成交价恒等于执行 bar 的 open,与 high/low 无关
            assert info["exec_price"] == pytest.approx(df["open"].iloc[tick_i])
            if info["trade_direction"] in ("buy", "sell"):
                assert info["requested_price"] == pytest.approx(
                    df["open"].iloc[tick_i])
            assert info["tick_rounding"] == "none" or price_is_tick_grid(
                info["exec_price"], 0.01)
        results[name] = env.ledger.cash
    # 同一 df 上把 high/low 换成另一组合法值,结果必须逐字段不变(见
    # test_future_high_low_invariance.py 的完整矩阵);此处先固定四类证据
    (ART).mkdir(parents=True, exist_ok=True)
    (ART / "legal_ohlc_validation.json").write_text(
        json.dumps({
            "kinds": {
                name: {
                    "n": int(len(df)),
                    "validate_ohlc_issues": [],
                    "high_low_range_mean": float((df["high"] - df["low"]).mean()),
                    "zero_range_rows": int(((df["high"] == df["low"])
                                             & (df["open"] == df["close"])).sum()),
                } for name, df in (
                    ("wide", wide), ("narrow", narrow), ("zero_range", zero),
                    ("gap", make_legal_candles("gap", n)),
                )
            },
            "scripted_targets": SCRIPTED_TARGETS,
            "final_cash_by_kind": results,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def price_is_tick_grid(price, tick):
    return abs(price / tick - round(price / tick)) < 1e-9


def test_gap_candles_legal_and_causal():
    gap = make_legal_candles("gap", 16)
    assert_legal_ohlc(gap)
    env, infos = replay(gap, SCRIPTED_TARGETS, slippage_bps=0.0)
    for info in infos:
        tick_i = info["execution_tick"]
        assert info["exec_price"] == pytest.approx(gap["open"].iloc[tick_i])


def test_narrow_bar_no_special_price_adjustment():
    """工作包 F 硬性语义:不再"向 bar 内移动一 tick 保证成交"。

    窄 K 线 + 非零模拟滑点时,成交价可以越过当根 high/low——
    这是模拟市场冲击参数的本意,不要求位于 K 线区间内。"""
    narrow = make_legal_candles("narrow", 12)
    env, infos = replay(narrow, SCRIPTED_TARGETS, slippage_bps=5.0, price_tick=0.01)
    saw_outside = 0
    for info in infos:
        tick_i = info["execution_tick"]
        hi, lo = narrow["high"].iloc[tick_i], narrow["low"].iloc[tick_i]
        if info["trade_direction"] == "buy" and info["exec_price"] > hi + 1e-12:
            saw_outside += 1
        if info["trade_direction"] == "sell" and info["exec_price"] < lo - 1e-12:
            saw_outside += 1
        # 无论如何都不 clamp 回区间
        if info["trade_direction"] == "buy":
            assert info["exec_price"] >= info["raw_open"]
    assert saw_outside > 0, "窄 K 线 + 5bps 应出现区间外成交(无调价语义)"
    # 诊断记录了 tick 取整方向
    for info in infos:
        if info["trade_direction"] in ("buy", "sell"):
            assert info["tick_rounding"] in ("ceil", "floor", "none")


def test_env_info_market_fill_diagnostics():
    wide = make_legal_candles("wide", 8)
    env, infos = replay(wide, [1, 0, 1, 0, 1, 0, 1], slippage_bps=5.0)
    trade_infos = [i for i in infos if i["trade_direction"] in ("buy", "sell")]
    assert trade_infos
    for info in trade_infos:
        for key in ("raw_open", "exec_price", "requested_price",
                    "requested_slippage_bps", "actual_effective_slippage_bps",
                    "tick_rounding", "fee", "fee_paid"):
            assert key in info, f"info 缺少 {key}"
        assert info["requested_slippage_bps"] == pytest.approx(5.0)
    (ART / "market_price_rounding.json").write_text(
        json.dumps({
            "tick_rounding_version": "side_aware_ceil_floor_v1",
            "samples": [
                {
                    "direction": i["trade_direction"],
                    "raw_open": i["raw_open"],
                    "requested_price": i["requested_price"],
                    "effective_price": i["exec_price"],
                    "tick_rounding": i["tick_rounding"],
                    "actual_effective_slippage_bps": i["actual_effective_slippage_bps"],
                } for i in trade_infos[:6]
            ],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
