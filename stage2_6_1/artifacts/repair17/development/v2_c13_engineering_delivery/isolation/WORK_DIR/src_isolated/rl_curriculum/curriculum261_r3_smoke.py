"""阶段 2.6.1 Repair R3:256-step PPO plumbing smoke(WP-K)。

只验证:fit state 加载、transformed observation、declared observation
space、model save/load、preprocessor state 绑定、reset/step、action
路径、reward 有限、无 NaN、无 crash。不用于 scaler/课程参数/PPO
超参选择与 family PASS 判定。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    curriculum261_eval_config,
)
from rl_curriculum.curriculum261_pairs import generate_pair
from rl_curriculum.curriculum261_r3_calibration import (
    EVAL_CFG,
    fit_preprocessor_from_bank,
)
from rl_curriculum.curriculum261_r3_obs import scaled_episode
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
)
from rl_curriculum.evaluator import select_features_strict


def run_ppo_smoke_r3(preproc: RouteCPreprocessor | None = None,
                     state_path: Path | None = None,
                     ) -> dict[str, Any]:
    """256-step PPO plumbing smoke(新正式 preprocessing adapter)。"""
    if preproc is None:
        if state_path is not None:
            preproc = RouteCPreprocessor.load(Path(state_path))
        else:
            preproc, _ = fit_preprocessor_from_bank(
                "preprocess_fit_calibration_r3")
    from rl_platform.env import AlignedLongFlatEnv
    from rl_curriculum.curriculum261_r3_obs import (
        r3_observation_schema,
    )

    rec = generate_pair(
        CURRICULUM261_FAMILIES[0], "D1", 0, namespace="ppo_smoke_r3")
    ep = rec.episodes["A"]
    scaled_ep = scaled_episode(ep, preproc)
    schema = r3_observation_schema(preproc)
    features = select_features_strict(
        scaled_ep.df, schema, context="ppo_smoke_r3")
    env = AlignedLongFlatEnv(
        features=features,
        prices=scaled_ep.df[list(("open", "high", "low", "close"))],
        fee=EVAL_CFG.fee, slippage_bps=EVAL_CFG.slippage_bps,
        initial_cash=EVAL_CFG.initial_cash,
        reward_scale=EVAL_CFG.reward_scale,
        window_size=1, price_tick=EVAL_CFG.price_tick,
        execution_mode="market_open_causal")

    obs, _ = env.reset(seed=7)
    obs_shape_ok = bool(obs.shape == (9,) and str(obs.dtype) == "float32")
    space_contains = bool(env.observation_space.contains(obs))

    import torch
    from stable_baselines3 import PPO

    torch.manual_seed(7)
    model = PPO(
        "MlpPolicy", env, n_steps=256, batch_size=64, seed=7,
        policy_kwargs=dict(net_arch=[32, 32]), verbose=0)
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
        "model_save_load_deterministic": bool(save_load_deterministic),
        "preprocessor_state_bound": preproc.state_hash(),
        "reset_step_ok": True,
        "action_path_valid": action_path_ok,
        "reward_finite": bool(rewards_finite and np.isfinite(total)),
        "no_nan": bool(rewards_finite),
        "no_crash": True,
    }
    return {
        "format": "cur261-r3-ppo-256step-smoke-v1",
        "iteration": "r3",
        "namespace": "ppo_smoke_r3",
        "n_steps": 256,
        "checks": checks,
        "pass": bool(all(v is True or (isinstance(v, str) and v)
                         for v in checks.values())),
    }
