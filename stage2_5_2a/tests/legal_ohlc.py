"""合法 OHLC 测试数据生成与验证(阶段 2.5.2a 工作包 F)。

阶段 2.5.2 曾构造 close 位于 high/low 之外的"窄 K 线"作为 parity 证据,
阶段 2.5.2a 起所有新增 synthetic OHLC 必须满足:

    high >= max(open, close)
    low  <= min(open, close)
    high >= low
    open > 0, close > 0
    volume >= 0

提供 validate_ohlc(生成后立即验证)与 make_legal_candles(合法宽/窄/
零振幅/跳空 K 线;所有价格 snap 到 tick 整数格)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def validate_ohlc(df: pd.DataFrame) -> list[str]:
    """返回违反合法 OHLC 约束的清单;空清单 = 合法。"""
    issues: list[str] = []
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            issues.append(f"缺少列 {col}")
    if issues:
        return issues
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    bad = (h < np.maximum(o, c)).to_numpy()
    if bad.any():
        issues.append(f"{int(bad.sum())} 行 high < max(open, close)")
    bad = (l > np.minimum(o, c)).to_numpy()
    if bad.any():
        issues.append(f"{int(bad.sum())} 行 low > min(open, close)")
    bad = (h < l).to_numpy()
    if bad.any():
        issues.append(f"{int(bad.sum())} 行 high < low")
    bad = (o <= 0).to_numpy()
    if bad.any():
        issues.append(f"{int(bad.sum())} 行 open <= 0")
    bad = (c <= 0).to_numpy()
    if bad.any():
        issues.append(f"{int(bad.sum())} 行 close <= 0")
    if "volume" in df.columns:
        bad = (df["volume"] < 0).to_numpy()
        if bad.any():
            issues.append(f"{int(bad.sum())} 行 volume < 0")
    return issues


def assert_legal_ohlc(df: pd.DataFrame) -> None:
    issues = validate_ohlc(df)
    assert not issues, f"非法 OHLC 数据: {issues}"


def snap_tick(value: float, tick: float) -> float:
    """snap 到 tick 整数格并规范化浮点(与 price_to_precision 十进制往返一致)。"""
    if tick <= 0:
        return float(value)
    return round(round(value / tick) * tick, 10)


def make_legal_candles(
    kind: str,
    n: int,
    *,
    base: float = 100.0,
    tick: float = 0.01,
    seed: int = 7,
    drift_sigma: float = 0.008,
    start: str = "2026-01-01",
) -> pd.DataFrame:
    """生成合法 synthetic OHLC。

    kind:
    - wide:   宽 K 线(high/low 在 body 外留 ~0.8% 余量)
    - narrow: 窄 K 线(close 相对 open 每根最多移动 1 tick,
              high == max(open, close), low == min(open, close):区间恰为 body)
    - zero_range: 零振幅 K 线(open == high == low == close)
    - gap:    跳空 K 线(open 跳离上一根 close,bar 内仍合法)

    四类使用相同的 close 随机游走种子与 open 延续规则
    (gap 除外),保证 wide/narrow/zero_range 的 open/close 序列一致,
    只有 high/low(与 gap 的 open)不同——供因果不变性对照使用。
    """
    rng = np.random.default_rng(seed)
    if kind == "narrow":
        # close 相对 open 移动 ±1 tick(与 wide 同种子但步长压到 tick 级)
        steps = rng.choice([-tick, 0.0, tick], size=n)
        closes = np.cumsum(steps) + base
        opens = np.empty(n)
        opens[0] = base
        opens[1:] = closes[:-1]
    else:
        rets = rng.normal(0.0, drift_sigma, size=n)
        closes = base * np.cumprod(1.0 + rets)
        opens = np.empty(n)
        opens[0] = base
        opens[1:] = closes[:-1]
    if kind == "gap":
        # 每根 open 跳离上一根 close(±0.3%~0.8%,与 close 无关的独立跳空)
        gap_pct = rng.uniform(0.003, 0.008, size=n) * rng.choice([-1.0, 1.0], size=n)
        opens = opens * (1.0 + gap_pct)

    opens = np.array([snap_tick(x, tick) for x in opens])
    closes = np.array([snap_tick(x, tick) for x in closes])
    highs = np.empty(n)
    lows = np.empty(n)
    for i in range(n):
        o, c = opens[i], closes[i]
        if kind == "wide":
            margin = max(tick, snap_tick(max(abs(o), abs(c)) * 0.008, tick))
            highs[i] = snap_tick(max(o, c) + margin, tick)
            lows[i] = snap_tick(max(tick, min(o, c) - margin), tick)
        elif kind == "narrow":
            highs[i] = max(o, c)
            lows[i] = min(o, c)
        elif kind == "zero_range":
            # 零振幅:open == high == low == close(合法 OHLC 的最小形态)
            m = snap_tick((o + c) / 2.0, tick)
            opens[i] = highs[i] = lows[i] = closes[i] = m
        elif kind == "gap":
            highs[i] = max(o, c)
            lows[i] = min(o, c)
        else:
            raise ValueError(f"未知 kind {kind!r}")
    df = pd.DataFrame({
        "date": pd.date_range(start=start, periods=n, freq="1h", tz="UTC"),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": np.abs(rng.normal(10.0, 1.0, size=n)),
    })
    assert_legal_ohlc(df)
    return df


# 固定目标序列(任务书工作包 F):0,1,1,1,0,0,1,1,0
SCRIPTED_TARGETS = [0, 1, 1, 1, 0, 0, 1, 1, 0]
