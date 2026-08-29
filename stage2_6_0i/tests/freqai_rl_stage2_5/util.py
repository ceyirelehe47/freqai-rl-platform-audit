"""阶段 2.5 测试公共工具:人工价格序列与环境驱动。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rl_platform.env import AlignedLongFlatEnv

BASE_TS = pd.Timestamp("2026-06-01T00:00:00Z")
N_ROWS = 30
ZIGZAG = [100.0, 110.0, 90.0, 120.0, 80.0, 130.0]


def make_values(kind: str, n: int = N_ROWS) -> list[float]:
    if kind == "constant":
        return [100.0] * n
    if kind == "rising":
        return [100.0 * (1.1 ** i) for i in range(n)]
    if kind == "falling":
        return [100.0 * (0.9 ** i) for i in range(n)]
    if kind == "zigzag":
        return [ZIGZAG[i % len(ZIGZAG)] for i in range(n)]
    raise ValueError(kind)


def make_ohlc(values: list[float], base_ts: pd.Timestamp = BASE_TS,
              high_low_margin: float = 0.005) -> pd.DataFrame:
    """人工 K 线。open/close = 给定值;high/low 按 ±margin 扩振幅。

    阶段 2.5.1 起环境的成交价被限制在执行 bar 的 high/low 内(镜像
    Freqtrade custom price clamp),测试数据必须提供真实幅度的 K 线;
    默认 ±0.5%(50bps)大于本阶段最大滑点 10bps,保证非 clamp 断言路径,
    且不改变 open/close(净值与手算基准不受影响)。
    """
    n = len(values)
    highs = [v * (1.0 + high_low_margin) for v in values]
    lows = [v * (1.0 - high_low_margin) for v in values]
    return pd.DataFrame({
        "date": pd.date_range(base_ts, periods=n, freq="1h", tz="UTC"),
        "open": values, "high": highs, "low": lows, "close": values,
        "volume": [1.0] * n,
    })


def build_env(values: list[float], fee: float = 0.001, slippage_bps: float = 0.0,
              initial_cash: float = 100.0, reward_scale: float = 1.0) -> AlignedLongFlatEnv:
    """用人工价格构造环境:特征矩阵为常数(测试只关心账本与时间语义)。"""
    ohlc = make_ohlc(values)
    features = pd.DataFrame(
        np.zeros((len(values), 2)), columns=["f0", "f1"]
    )
    return AlignedLongFlatEnv(
        features=features, prices=ohlc, fee=fee, slippage_bps=slippage_bps,
        initial_cash=initial_cash, reward_scale=reward_scale, window_size=1,
        dates=ohlc["date"],
    )


def run_script(env: AlignedLongFlatEnv, actions: list[int]) -> list[dict]:
    """驱动环境执行给定目标仓位序列,收集每步 info。"""
    obs, info = env.reset()
    infos = [info]
    for a in actions:
        obs, reward, terminated, truncated, info = env.step(a)
        infos.append(info)
        if terminated:
            break
    return infos
