"""工作包 C 测试:reward telescoping。

sum(unscaled_log_rewards) == log(final_cash / initial_cash)
浮点误差之外不得有偏差(终端清算成本已包含在最后一步 reward 内)。
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from legal_ohlc import make_legal_candles
from rl_platform.env import AlignedLongFlatEnv

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2a"


def episode(df, actions, *, fee=0.001, slippage_bps=5.0, price_tick=0.01,
            reward_scale=1.0):
    env = AlignedLongFlatEnv(
        features=pd.DataFrame({"f": np.zeros(len(df))}),
        prices=df[["open", "high", "low", "close"]],
        fee=fee, slippage_bps=slippage_bps, price_tick=price_tick,
        reward_scale=reward_scale,
    )
    env.reset()
    done = False
    i = 0
    while not done:
        _, _, term, _, info = env.step(actions[i % len(actions)])
        done = term
        i += 1
    return env, info


CASES = {
    "hold_to_end": [1],
    "flat_to_end": [0],
    "exit_before_end": [1, 1, 1, 0, 0],
    "last_step_long": [0, 0, 0, 1],
    "alternate": [1, 0, 1, 0, 1, 0],
}


@pytest.mark.parametrize("case", CASES.values(), ids=CASES.keys())
@pytest.mark.parametrize("bps,tick", [(0.0, 0.01), (5.0, 0.01), (10.0, 0.0)])
def test_telescoping(case, bps, tick):
    df = make_legal_candles("wide", 18)
    env, _ = episode(df, case, slippage_bps=bps, price_tick=tick)
    expect = np.log(env.ledger.cash / env.initial_cash)
    assert env.episode_reward_raw == pytest.approx(expect, abs=1e-12), (
        env.episode_reward_raw, expect
    )
    assert env.ledger.btc == 0.0  # 终端必为全现金


def test_telescoping_scaled_reward():
    df = make_legal_candles("wide", 15)
    env, _ = episode(df, [1, 0, 1, 1, 0], reward_scale=2.5)
    assert env.episode_reward_scaled == pytest.approx(
        2.5 * env.episode_reward_raw, abs=1e-12)


def test_telescoping_random_prices_and_actions():
    rng = np.random.default_rng(11)
    records = []
    for trial in range(20):
        n = int(rng.integers(8, 50))
        df = make_legal_candles("wide", n, seed=int(rng.integers(0, 99999)))
        acts = list(rng.integers(0, 2, size=n))
        env, _ = episode(df, acts, slippage_bps=float(rng.choice([0.0, 5.0])))
        expect = np.log(env.ledger.cash / env.initial_cash)
        assert env.episode_reward_raw == pytest.approx(expect, abs=1e-12)
        records.append({"n": n, "final_cash": env.ledger.cash,
                        "sum_raw": env.episode_reward_raw, "expect": expect})
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "reward_telescoping.json").write_text(
        json.dumps({
            "identity": "sum(reward_raw) == log(final_cash / initial_cash)",
            "max_abs_err": max(abs(r["sum_raw"] - r["expect"]) for r in records),
            "trials": len(records),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
