# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:256-step PPO plumbing smoke(§31/§32)。

只验证:V2 fit state 加载(ppo_smoke_r5 非 final namespace fit)、
transformed observation、V2 outer 无界 observation space、SB3
check_env、model save/load、reset/step、action 路径、reward 有限、
无 NaN、无 crash。不用于任何参数选择与 PASS 判定。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
)
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import generate_pair
from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessingEnvV2,
)
from rl_curriculum.curriculum261_r5_calibration import (
    fit_preprocessor_v2_from_bank_r5,
)
from rl_curriculum.curriculum261_r3_obs import scaled_episode
from rl_curriculum.curriculum261_r5_pairs import EVAL_CFG
from rl_curriculum.evaluator import select_features_strict


def run_ppo_smoke_r5(
        envelope_path: Path | None = None,
        pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """256-step PPO plumbing smoke(V2 outer 无界空间;非 final namespace)。"""
    if envelope_path is not None and Path(envelope_path).is_file():
        from rl_curriculum.curriculum261_r4_preprocessing import (
            RouteCPreprocessorV2,
        )

        preproc = RouteCPreprocessorV2.load_envelope(Path(envelope_path))
    else:
        preproc, _ = fit_preprocessor_v2_from_bank_r5(
            "ppo_smoke_r5", pack or {"digest": "ppo-smoke-no-pack"})
    from rl_platform.env import AlignedLongFlatEnv

    rec = generate_pair(
        FAMILY_C2, "D1", 0, namespace="ppo_smoke_r5",
        rung_params_override=(
            {"D3": dict(pack["d3_overrides"][FAMILY_C2])}
            if pack else None))
    ep = rec.episodes["A"]
    scaled_ep = scaled_episode(ep, preproc.inner)
    schema = r4_observation_schema(preproc)
    features = select_features_strict(
        scaled_ep.df, schema, context="ppo_smoke_r5")
    inner_env = AlignedLongFlatEnv(
        features=features,
        prices=scaled_ep.df[list(("open", "high", "low", "close"))],
        fee=EVAL_CFG.fee, slippage_bps=EVAL_CFG.slippage_bps,
        initial_cash=EVAL_CFG.initial_cash,
        reward_scale=EVAL_CFG.reward_scale,
        window_size=1, price_tick=EVAL_CFG.price_tick,
        execution_mode="market_open_causal")
    env = RouteCPreprocessingEnvV2(inner_env, preproc.bundle_hash)

    space_unbounded = bool(
        np.isneginf(env.observation_space.low[:8]).all()
        and np.isposinf(env.observation_space.high[:8]).all()
        and env.observation_space.low[8] == 0.0
        and env.observation_space.high[8] == 1.0)

    from stable_baselines3.common.env_checker import check_env

    check_env(env, warn=True)

    obs, _ = env.reset(seed=7)
    obs_shape_ok = bool(obs.shape == (9,) and str(obs.dtype) == "float32")
    space_contains = bool(env.observation_space.contains(obs))

    import torch
    from stable_baselines3 import PPO

    torch.manual_seed(7)
    model = PPO(
        "MlpPolicy", env, n_steps=256, batch_size=64, seed=7,
        policy_kwargs=dict(net_arch=[32, 32]), verbose=0)
    assert np.isneginf(model.observation_space.low[:8]).all(), (
        "PPO model observation space 必须保持无界(V2 语义)")
    model.learn(total_timesteps=256)

    obs2, _ = env.reset(seed=7)
    action, _ = model.predict(obs2, deterministic=True)
    action_path_ok = bool(int(action) in (0, 1))

    rewards_finite = True
    o = obs2
    total = 0.0
    for _ in range(50):
        a, _ = model.predict(o, deterministic=True)
        o, r, term, trunc, _ = env.step(int(a))
        total += float(r)
        if not np.isfinite(r) or not np.isfinite(o).all():
            rewards_finite = False
            break
        if term or trunc:
            break

    with tempfile.TemporaryDirectory() as td:
        mpath = Path(td) / "smoke_model.zip"
        model.save(str(mpath))
        model2 = PPO.load(str(mpath))
        a2, _ = model2.predict(obs2, deterministic=True)
        save_load_deterministic = bool(int(a2) == int(action))

    checks = {
        "fit_state_loaded": True,
        "transformed_observation_shape_9_float32": obs_shape_ok,
        "declared_observation_space_contains": space_contains,
        "observation_space_unbounded": space_unbounded,
        "sb3_check_env_pass": True,
        "model_save_load_deterministic": bool(save_load_deterministic),
        "preprocessor_state_bound": preproc.state_hash_r3(),
        "reset_step_ok": True,
        "action_path_valid": action_path_ok,
        "reward_finite": bool(rewards_finite and np.isfinite(total)),
        "no_nan": bool(rewards_finite),
        "no_crash": True,
    }
    return {
        "format": "cur261-r5-ppo-256step-smoke-v1",
        "iteration": "r5",
        "namespace": "ppo_smoke_r5",
        "n_steps": 256,
        "checks": checks,
        "pass": bool(all(
            v is True or (isinstance(v, str) and v)
            for v in checks.values())),
    }
