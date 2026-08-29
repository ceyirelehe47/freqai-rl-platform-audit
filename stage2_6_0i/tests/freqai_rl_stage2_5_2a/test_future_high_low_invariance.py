"""工作包 A.4 硬性验收:未来 high/low 不变性。

两份数据 open、close、动作序列、fee、slippage、tick 完全相同,
high/low 改为完全不同但仍合法的数值(含极端值):
- 每一步成交方向完全一致;
- 每一步成交价格完全一致;
- 每一步手续费完全一致;
- 每一步 reward 完全一致;
- 最终净值完全一致。

对照组:legacy_noncausal_not_for_training(阶段 2.5.2 bar 内调价合同)
在同样场景下结果确实随 high/low 改变——证明阶段 2.5.2 旧合同存在
未来信息泄漏,也证明本测试具备区分能力(不是恒等空测试)。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from legal_ohlc import make_legal_candles, snap_tick
from rl_platform.env import AlignedLongFlatEnv
from rl_platform.market_execution import LEGACY_EXECUTION_MODE

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"

TARGETS = [0, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 0]


def mutate_high_low(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """保持 open/close 不变,把 high/low 换成另一组合法数值。"""
    out = df.copy()
    n = len(out)
    if mode == "shuffled":
        # 每根 bar 的 high/low 用独立随机的合法更大的区间(不同 seed)
        rng = np.random.default_rng(99)
        highs, lows = [], []
        for i in range(n):
            body_hi = max(out["open"].iloc[i], out["close"].iloc[i])
            body_lo = min(out["open"].iloc[i], out["close"].iloc[i])
            margin = rng.uniform(0.001, 0.02) * body_hi
            highs.append(snap_tick(body_hi + margin, 0.01))
            lows.append(snap_tick(max(0.01, body_lo - margin), 0.01))
    elif mode == "extreme":
        highs = [1e9] * n
        lows = [1e-6] * n
    else:
        raise ValueError(mode)
    out["high"] = highs
    out["low"] = lows
    return out


def run_episode(df, targets, *, fee=0.001, slippage_bps=5.0, price_tick=0.01,
                execution_mode=None):
    kwargs = dict(
        features=pd.DataFrame({"f": np.zeros(len(df))}),
        prices=df[["open", "high", "low", "close"]],
        fee=fee, slippage_bps=slippage_bps, price_tick=price_tick,
    )
    if execution_mode is not None:
        kwargs["execution_mode"] = execution_mode
    env = AlignedLongFlatEnv(**kwargs)
    env.reset()
    rows = []
    done = False
    i = 0
    while not done:
        _, r, term, _, info = env.step(targets[i % len(targets)])
        rows.append({
            "direction": info["trade_direction"],
            "exec_price": info["exec_price"],
            "fee_paid": info["fee_paid"],
            "reward": info["reward_raw"],
            "cash": info["cash"],
            "btc": info["btc"],
        })
        done = term
        i += 1
    return env, rows


def compare_rows(a, b):
    assert len(a) == len(b)
    for i, (ra, rb) in enumerate(zip(a, b)):
        for key in ("direction", "exec_price", "fee_paid", "reward", "cash", "btc"):
            if isinstance(ra[key], str):
                assert ra[key] == rb[key], f"step {i} {key}: {ra[key]} != {rb[key]}"
            else:
                assert ra[key] == rb[key], f"step {i} {key}: {ra[key]!r} != {rb[key]!r}"


@pytest.mark.parametrize("mode", ["shuffled", "extreme"])
@pytest.mark.parametrize("slippage_bps,price_tick", [(0.0, 0.01), (5.0, 0.01), (5.0, 0.0)])
def test_high_low_invariance(mode, slippage_bps, price_tick):
    base_df = make_legal_candles("wide", 20)
    mutated = mutate_high_low(base_df, mode)
    env_a, rows_a = run_episode(base_df, TARGETS, slippage_bps=slippage_bps,
                                price_tick=price_tick)
    env_b, rows_b = run_episode(mutated, TARGETS, slippage_bps=slippage_bps,
                                price_tick=price_tick)
    compare_rows(rows_a, rows_b)
    assert env_a.ledger.cash == env_b.ledger.cash
    assert env_a.ledger.btc == env_b.ledger.btc
    assert env_a.episode_reward_raw == env_b.episode_reward_raw


def test_legacy_mode_is_high_low_sensitive():
    """对照组:legacy 合同(bar 内调价)的结果确实随 high/low 改变。

    窄 K 线下 5bps 请求价越出 bar 边界,legacy 合同把价格拉回 bar 内
    (读取执行 K 线最终 high/low,属未来信息);把 high/low 换成宽区间后
    价格不再被拉回——成交价改变。这证明旧合同存在未来信息泄漏,
    也证明上面的不变性测试具备区分能力。"""
    base_df = make_legal_candles("narrow", 20)
    mutated = mutate_high_low(base_df, "shuffled")  # 换成宽合法区间
    env_a, rows_a = run_episode(base_df, TARGETS, slippage_bps=5.0,
                                price_tick=0.01,
                                execution_mode=LEGACY_EXECUTION_MODE)
    env_b, rows_b = run_episode(mutated, TARGETS, slippage_bps=5.0,
                                price_tick=0.01,
                                execution_mode=LEGACY_EXECUTION_MODE)
    differs = any(
        ra["exec_price"] != rb["exec_price"]
        for ra, rb in zip(rows_a, rows_b)
    )
    assert differs, "legacy 模式应依赖 high/low(对照组失效)"


def test_invariance_evidence_file():
    base_df = make_legal_candles("wide", 20)
    mutated = mutate_high_low(base_df, "shuffled")
    _, rows_a = run_episode(base_df, TARGETS)
    _, rows_b = run_episode(mutated, TARGETS)
    _, rows_x = run_episode(mutate_high_low(base_df, "extreme"), TARGETS)
    compare_rows(rows_a, rows_b)
    compare_rows(rows_a, rows_x)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "future_high_low_invariance.json").write_text(
        json.dumps({
            "claim": "改变未来 high/low(合法化重造,含极端值)不影响"
                     "成交方向/成交价/手续费/reward/最终净值",
            "n_rows": int(len(base_df)),
            "targets": TARGETS,
            "grid": {
                "slippage_bps": [0.0, 5.0],
                "price_tick": [0.0, 0.01],
                "high_low_modes": ["shuffled", "extreme"],
            },
            "legacy_control": "legacy_noncausal_not_for_training 模式在同一"
                              "场景下成交价确实随 high/low 改变(旧合同存在"
                              "未来信息泄漏,已在阶段 2.5.2a 废弃出生产路径)",
            "per_step_equal": True,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
