"""multi-episode 环境测试(§27 Environment)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.ppo262_banks import LoadedEpisode
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv


def test_reset_loads_correct_episode_in_order(small_bank_factory):
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    seen = []
    for i in range(len(bank)):
        obs, info = env.reset()
        assert info["episode_index"] == i
        assert info["episode_key"] == bank[i].key.canonical()
        seen.append(info["episode_key"])
        done = False
        while not done:
            obs, r, term, trunc, _ = env.step(0)
            done = term or trunc
    assert seen == [e.key.canonical() for e in bank]


def test_episode_state_fully_cleared(small_bank_factory):
    """episode 边界:equity 回到 initial_cash、position=0(无泄漏)。"""
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    init_cash = env.eval_config.initial_cash
    for _ in range(3):
        obs, info = env.reset()
        # 初始 obs 的仓位槽位(obs[8])必须为 0(Flat)
        assert obs[-1] == 0.0
        done = False
        while not done:
            obs, r, term, trunc, i = env.step(1)
            done = term or trunc
        # 终端清算:btc=0、全现金
        assert i["btc"] == 0.0
        assert i["cash"] == pytest.approx(
            i["equity_end"], rel=1e-12)
    # 每回合从同一现金开始(账户状态清空)
    eq0 = None
    for _ in range(2):
        obs, info = env.reset()
        done = False
        first = True
        while not done:
            obs, r, term, trunc, i = env.step(1)
            if first:
                eq0 = i["equity_start"]
                assert eq0 == pytest.approx(init_cash, rel=1e-9)
                first = False
            done = term or trunc


def test_observation_shape_dtype_and_no_metadata(small_bank_factory):
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    obs, _ = env.reset()
    arr = np.asarray(obs)
    assert arr.shape == (9,)
    assert str(arr.dtype) == "float32"
    # observation 只含 8 生产特征 + 仓位槽:与 latent/family/rung 无关
    # (frozen Route C 的 observation 构造是唯一来源)
    for _ in range(20):
        obs, r, term, trunc, _ = env.step(int(np.random.randint(0, 2)))
        assert np.asarray(obs).shape == (9,)
        if term or trunc:
            env.reset()


def test_latent_does_not_affect_observation_or_reward(
        small_bank_factory, locked_rung_params):
    """同一 seed 重新生成的 episode:observation/reward 逐位一致。"""
    from rl_curriculum.curriculum261_api import (
        curriculum261_eval_config,
    )
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.evaluator import select_features_strict
    from rl_curriculum.generator_api import PRICE_COLUMNS
    from rl_platform.env import AlignedLongFlatEnv

    bank = small_bank_factory(1)
    loaded = bank[0]
    cfg = curriculum261_eval_config()
    schema = production_observation_schema()
    # 复算:与 evaluator._build_env 同一构造路径,obs 序列一致
    features = select_features_strict(loaded.episode.df, schema)
    env_ref = AlignedLongFlatEnv(
        features=features, prices=loaded.episode.df[list(PRICE_COLUMNS)],
        fee=cfg.fee, slippage_bps=cfg.slippage_bps,
        initial_cash=cfg.initial_cash, window_size=cfg.window_size,
        execution_mode="market_open_causal")
    env_multi = CurriculumMultiEpisodeEnv(
        [loaded], eval_config=cfg, schema=schema)
    o1, _ = env_ref.reset(seed=loaded.episode.spec.seed)
    o2, _ = env_multi.reset(seed=3)
    assert np.allclose(o1, o2, atol=0, rtol=0)
    rng = np.random.default_rng(11)
    acts = [int(a) for a in rng.integers(0, 2, size=287)]
    for a in acts:
        _, r1, t1, _, i1 = env_ref.step(a)
        _, r2, t2, _, i2 = env_multi.step(a)
        assert r1 == r2
        assert t1 == t2
        assert i1["equity_end"] == i2["equity_end"]


def test_no_skip_no_repeat_and_exhaustion(small_bank_factory):
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    env.reset()
    for _ in range(len(bank)):
        done = False
        while not done:
            _, _, term, trunc, _ = env.step(0)
            done = term or trunc
        env.reset()
    audit = env.audit()
    assert audit["duplicate_episode_completions"] == 0
    assert audit["first_pass_order_ok"] is True
    # 全部消耗后的下一次 reset 触发 exhausted(受控计数,非静默)
    assert env.exhausted_cycles == 1
    audit2 = env.audit()
    assert audit2["exhausted_cycles"] == 1


def test_manifest_consumption_is_deterministic(small_bank_factory):
    bank = small_bank_factory(1)

    def _consume():
        env = CurriculumMultiEpisodeEnv(bank)
        env.reset()
        while env.episodes_consumed < len(bank):
            done = False
            while not done:
                _, _, term, trunc, _ = env.step(0)
                done = term or trunc
            if env.episodes_consumed < len(bank):
                env.reset()
        return [t["key"] for t in env.episode_trace]

    keys_a = _consume()
    keys_b = _consume()
    assert keys_a == keys_b
    assert keys_a == [e.key.canonical() for e in bank]


def test_frozen_route_c_actually_executing(small_bank_factory):
    """内层 env 必须是冻结 AlignedLongFlatEnv(版本号即证据)。"""
    from rl_platform.env import AlignedLongFlatEnv
    from rl_platform.versions import (
        ENV_CORE_VERSION, EXECUTION_CONTRACT_VERSION,
    )
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    env.reset()
    assert isinstance(env._inner, AlignedLongFlatEnv)
    assert env._inner.env_core_version == ENV_CORE_VERSION == (
        "RouteCEnvCore-v1.0.0")
    assert env._inner.execution_mode == "market_open_causal"
    assert EXECUTION_CONTRACT_VERSION == "MarketOpenCausalExecution-v1"
    # 终端清算合同:最后一 bar 后 btc 归零
    done = False
    while not done:
        _, _, term, trunc, info = env.step(1)
        done = term or trunc
    assert info["terminated"] is True
    assert info["terminal_liquidation"] is not None


def test_action_reward_finite(small_bank_factory):
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    env.reset()
    rng = np.random.default_rng(3)
    for _ in range(600):
        obs, r, term, trunc, info = env.step(int(rng.integers(0, 2)))
        assert np.isfinite(r)
        assert np.all(np.isfinite(np.asarray(obs)))
        if term or trunc:
            env.reset()
