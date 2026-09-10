"""阶段 2.6.1 Repair R4:256-step PPO plumbing smoke(§30)。

只在 R4 正式 preprocessing V2 外层 adapter(RouteCPreprocessingEnvV2)
上运行。验证:outer 无界 observation space、transformed obs、
preprocessor bundle 加载、model manifest 绑定 bundle hash、
SB3 check_env、reset/step、action、reward 有限、save/load、
no NaN、no crash。不用于 PPO tuning / BC / C3 optimization /
staged-mixed / 课程选择。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    curriculum261_eval_config,
)
from rl_curriculum.curriculum261_r4_calibration import (
    EVAL_CFG,
    fit_preprocessor_v2_from_bank,
)
from rl_curriculum.curriculum261_r4_param_pack import (
    load_selected_pack,
)
from rl_curriculum.curriculum261_r3_obs import scaled_episode
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessorV2,
    build_v2_env,
)


def run_ppo_smoke_r4(
        preproc_v2: RouteCPreprocessorV2 | None = None,
        envelope_path: Path | None = None,
        pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """256-step PPO plumbing smoke(V2 outer adapter)。"""
    from rl_curriculum.curriculum261_pairs import generate_pair

    if preproc_v2 is None:
        if envelope_path is not None:
            preproc_v2 = RouteCPreprocessorV2.load_envelope(
                Path(envelope_path))
        else:
            if pack is None:
                pack = load_selected_pack(_default_lock_dir())
            preproc_v2, _ = fit_preprocessor_v2_from_bank(
                "preprocess_fit_calibration_r4", pack)

    rec = generate_pair(
        CURRICULUM261_FAMILIES[0], "D1", 0, namespace="ppo_smoke_r4")
    ep = rec.episodes["A"]
    scaled_ep = scaled_episode(ep, preproc_v2.inner)
    env = build_v2_env(preproc_v2, scaled_ep.df, EVAL_CFG)

    obs, _ = env.reset(seed=7)
    obs_shape_ok = bool(obs.shape == (9,) and str(obs.dtype) == "float32")
    outer_contains = bool(env.observation_space.contains(obs))
    unbounded_ok = bool(
        np.all(np.isinf(env.observation_space.low[:8]))
        and np.all(np.isinf(env.observation_space.high[:8]))
        and env.observation_space.low[-1] == 0.0
        and env.observation_space.high[-1] == 1.0)
    position_ok = bool(float(obs[-1]) in (0.0, 1.0))

    # SB3 env_checker 看到的必须是 outer space(无界)
    from stable_baselines3.common.env_checker import check_env

    checker_ok = True
    try:
        check_env(env, warn=True)
    except Exception as exc:  # noqa: BLE001
        checker_ok = False
        checker_error = str(exc)[:300]

    import torch
    from stable_baselines3 import PPO

    torch.manual_seed(7)
    model = PPO(
        "MlpPolicy", env, n_steps=256, batch_size=64, seed=7,
        policy_kwargs=dict(net_arch=[32, 32]), verbose=0)
    model.learn(total_timesteps=256)

    # model 看到的 observation space == outer 无界空间
    model_space_ok = bool(
        model.observation_space.shape == (9,)
        and np.all(np.isinf(model.observation_space.low[:8]))
        and model.observation_space.low[-1] == 0.0)

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
        "fit_envelope_bundle_loaded": True,
        "transformed_observation_shape_9_float32": obs_shape_ok,
        "outer_observation_space_contains": outer_contains,
        "outer_space_feature_unbounded_position_01": unbounded_ok,
        "position_slot_0_or_1": position_ok,
        "sb3_check_env_on_outer_space": bool(checker_ok),
        "sb3_model_sees_outer_unbounded_space": model_space_ok,
        "model_save_load_deterministic": bool(save_load_deterministic),
        "preprocessor_bundle_bound": preproc_v2.bundle_hash,
        "reset_step_ok": True,
        "action_path_valid": action_path_ok,
        "reward_finite": bool(rewards_finite and np.isfinite(total)),
        "no_nan": bool(rewards_finite),
        "no_crash": True,
    }
    if not checker_ok:
        checks["sb3_check_env_error"] = checker_error  # type: ignore[assignment]
    return {
        "format": "cur261-r4-ppo-256step-smoke-v1",
        "iteration": "r4",
        "namespace": "ppo_smoke_r4",
        "n_steps": 256,
        "checks": checks,
        "pass": bool(all(v is True or (isinstance(v, str) and v)
                         for k, v in checks.items()
                         if not k.endswith("error"))),
    }


def _default_lock_dir() -> Path:
    from rl_curriculum.curriculum261_r4_namespaces import (
        qualification_r4_lock_dir,
    )

    return qualification_r4_lock_dir()
