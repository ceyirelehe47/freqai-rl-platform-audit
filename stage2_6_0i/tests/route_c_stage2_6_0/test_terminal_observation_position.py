"""工作包 0 修复 1:终端清算后 observation 仓位字段必须为 0。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rl_platform.env import AlignedLongFlatEnv


def _make_env(n=50, final_action=1):
    rng = np.random.default_rng(5)
    rets = rng.normal(0.0006, 0.004, n)
    close = 100.0 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    prices = pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999, "close": close,
    })
    feats = pd.DataFrame({"r": np.concatenate([[0.0], np.diff(close) / close[:-1]])})
    return AlignedLongFlatEnv(features=feats, prices=prices, window_size=1), final_action


def _run_to_terminal(final_action):
    env, _ = _make_env(final_action=final_action)
    env.reset(seed=1)
    obs = info = None
    for _ in range(200):
        obs, _r, term, _tr, info = env.step(final_action)
        if term:
            return env, obs, info
    raise AssertionError("Episode 未终止")


def test_terminal_observation_position_is_zero_when_long():
    env, obs, info = _run_to_terminal(1)
    assert float(obs[-1]) == 0.0
    assert env.ledger.btc == 0.0


def test_terminal_info_fields_present():
    env, obs, info = _run_to_terminal(1)
    assert info["requested_target_position"] == 1
    assert info["actual_position_after_liquidation"] == 0
    tl = info["terminal_liquidation"]
    assert tl["direction"] == "liquidate"
    assert tl["exec_price"] <= tl["reference_price"]  # 卖出方向不利
    assert float(env.get_observation()[-1]) == 0.0


def test_terminal_flat_case_also_zero():
    env, obs, info = _run_to_terminal(0)
    assert float(obs[-1]) == 0.0
    assert info["requested_target_position"] == 0
    assert info["actual_position_after_liquidation"] == 0


def test_non_terminal_observation_still_carries_position():
    env, _ = _make_env()
    obs, _ = env.reset(seed=2)
    assert float(obs[-1]) == 0.0
    obs2, _r, term, _tr, info = env.step(1)
    assert not term
    assert float(obs2[-1]) == 1.0  # 非终端:观察仓位 = 当前目标
    assert "requested_target_position" not in info


def test_reward_telescoping_unchanged_after_fix():
    env, _ = _make_env()
    env.reset(seed=3)
    total = 0.0
    for _ in range(200):
        _o, _r, term, _tr, info = env.step(1)
        total += info["reward_raw"]
        if term:
            break
    assert abs(total - __import__("math").log(env.ledger.cash / 100.0)) < 1e-9
