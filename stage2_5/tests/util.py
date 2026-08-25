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


def make_ohlc(values: list[float], base_ts: pd.Timestamp = BASE_TS) -> pd.DataFrame:
    n = len(values)
    return pd.DataFrame({
        "date": pd.date_range(base_ts, periods=n, freq="1h", tz="UTC"),
        "open": values, "high": values, "low": values, "close": values,
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
