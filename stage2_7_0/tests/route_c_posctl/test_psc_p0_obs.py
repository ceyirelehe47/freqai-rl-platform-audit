# -*- coding: utf-8 -*-
"""PSC_P0_v1 观察身份与时间信息(P02/最小反例 1;手工数据,小额受计量)。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rl_posctl.skill_p0.p0env import P0FiniteTimeEnv
from rl_posctl.skill_p0.p0spec import (
    C1_FEE, FUNDING_SCHEDULE, INITIAL_CASH, MAINTENANCE_MARGIN,
    REWARD_SCALE)
from rl_posctl.skill_p0.p0task import (
    counterfactual_probes, mirror_probe)
from rl_posctl.skill_p0.p0banks import mirror_episode


def _hand_episode(n: int, seed: int = 7, s_sign: float = 1.0):
    rng = np.random.default_rng(seed)
    r = 0.004 * s_sign + 0.006 * np.sqrt(3) * rng.uniform(
        -1, 1, n - 1)
    r = np.concatenate([[0.0], r])
    close = 100.0 * np.cumprod(1.0 + r)
    open_ = np.empty_like(close)
    open_[0] = 100.0
    open_[1:] = close[:-1]
    prices = pd.DataFrame({"open": open_, "close": close})
    s = np.zeros(n)
    s[1:] = s_sign
    feats = pd.DataFrame({
        "s": s, "c": np.ones(n), "q": np.full(n, 0.5),
        "g": np.zeros(n)})
    hidden = {"mu_eff": np.zeros(n), "sigma": np.zeros(n),
              "s": s.astype(int), "c": np.ones(n, dtype=int),
              "q": np.full(n, 0.5), "g": np.zeros(n, dtype=int),
              "qi": np.zeros(n, dtype=int)}
    return prices, feats, hidden


def _mk_env(item):
    prices, feats, _ = item
    return P0FiniteTimeEnv(
        features=feats, prices=prices, fee=C1_FEE, window_size=1,
        funding_schedule=dict(FUNDING_SCHEDULE),
        maintenance_margin=MAINTENANCE_MARGIN,
        initial_cash=INITIAL_CASH, reward_scale=REWARD_SCALE)


@pytest.mark.parametrize("horizon", [32, 64, 96])
def test_obs_shape_and_clock(horizon):
    env = _mk_env(_hand_episode(horizon + 1))
    assert env.observation_space.shape == (8,)
    obs, _ = env.reset()
    assert obs.shape == (8,)
    assert obs[-1] == pytest.approx(horizon / 128.0)
    assert obs[-2] == pytest.approx(horizon / 128.0)


def test_h32_h64_same_ratio_different_absolute(psc_p0_meter_eval):
    """同 remaining 比例(0.5)不同绝对时长可区分(H=32 vs 64)。"""
    e32 = _mk_env(_hand_episode(33))
    e64 = _mk_env(_hand_episode(65))
    o32, _ = e32.reset()
    o64, _ = e64.reset()
    assert o32[-2] == pytest.approx(32 / 128.0)   # 初始 remaining=H
    assert o64[-2] == pytest.approx(64 / 128.0)
    steps32 = steps64 = 0
    for _ in range(16):
        o32, _, t, _, _ = e32.step(np.array([0.0, 0.0]))
        steps32 += 1
        if t:
            break
    for _ in range(32):
        o64, _, t, _, _ = e64.step(np.array([0.0, 0.0]))
        steps64 += 1
        if t:
            break
    # 两 env 现在 remaining 均为 16(比例 0.5),绝对值编码可区分
    assert o32[-2] == pytest.approx(16 / 128.0)
    assert o64[-2] == pytest.approx(32 / 128.0)
    assert o32[-2] != pytest.approx(o64[-2])
    assert o32[-1] != o64[-1]                   # H 维也不同
    psc_p0_meter_eval(steps32 + steps64)


def test_clock_does_not_leak_across_reset(psc_p0_meter_eval):
    env = _mk_env(_hand_episode(9))
    obs, _ = env.reset()
    for _ in range(8):
        obs, _, term, _, _ = env.step(np.array([0.0, 0.0]))
        assert term or obs[-2] > 0.0
    assert term
    obs2, _ = env.reset()
    assert obs2[-2] == pytest.approx(8 / 128.0)   # 不携带上一时钟
    psc_p0_meter_eval(8)


def test_vecenv_autoreset_consistency(psc_p0_meter_eval):
    """VecEnv 自动 reset 后时间维回到初始(同一路径构造)。"""
    from stable_baselines3.common.vec_env import DummyVecEnv
    item = _hand_episode(9)
    inner = _mk_env(item)

    def make():
        return _mk_env(item)
    venv = DummyVecEnv([make])
    obs = venv.reset()
    assert obs.shape == (1, 8)
    total = 0
    for _ in range(9):
        obs, _, dones, _ = venv.step(
            np.array([[0.0, 0.0]]))
        total += 1
        if dones[0]:
            break
    assert dones[0]
    # VecEnv 已自动 reset:首观察 remaining=H
    assert obs[0, -2] == pytest.approx(8 / 128.0)
    assert obs[0, -2] == pytest.approx(
        float(inner.reset()[0][-2]))
    psc_p0_meter_eval(total)


def test_counterfactual_future_and_meta():
    item = _hand_episode(17, seed=11)
    res = counterfactual_probes(item, t_check=5)
    assert res["future_invariant"], res
    assert res["meta_invariant"], res


def test_counterfactual_mid_episode():
    item = _hand_episode(65, seed=13)
    res = counterfactual_probes(item, t_check=30)
    assert res["pass"], res


def test_mirror_transform_semantics():
    prices, feats, hidden = _hand_episode(17, seed=21, s_sign=1.0)
    p1, f1, h1 = mirror_episode(prices, feats, hidden)
    res = mirror_probe((prices, feats, {}),
                       (p1, f1, {}))
    assert res["r_negated"] and res["s_negated"], res
    assert res["cgq_identical"] and res["prices_positive"], res
    # mu_eff 随 s 翻转
    assert np.allclose(h1["mu_eff"], -hidden["mu_eff"])


def test_account_features_untouched_positions():
    """6 个前维语义与旧 env 一致(特征窗口+账户变换)。"""
    item = _hand_episode(9, seed=3)
    env = _mk_env(item)
    from rl_posctl.env import HybridPositionEnv
    old = HybridPositionEnv(
        features=item[1], prices=item[0], fee=C1_FEE,
        window_size=1, funding_schedule=dict(FUNDING_SCHEDULE),
        maintenance_margin=MAINTENANCE_MARGIN,
        initial_cash=INITIAL_CASH, reward_scale=REWARD_SCALE)
    o_new, _ = env.reset()
    o_old, _ = old.reset()
    np.testing.assert_array_equal(o_new[:6], o_old[:6])
    # funding 显式空计划:不冒充未知零资金费
    assert env.funding_missing is False
    assert env.funding_schedule == {}
