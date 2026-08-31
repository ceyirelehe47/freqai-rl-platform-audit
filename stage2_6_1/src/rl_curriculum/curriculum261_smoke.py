"""阶段 2.6.1 工作包 J:qualified generator 上的 256-step PPO plumbing smoke。

只验证运行完整性(env API / reset / step / observation shape / action
集成 / reward finite / SB3-PPO plumbing / 无 crash / 无 NaN);不构成
课程训练,其 reward/学习曲线绝不参与课程参数选择。使用 training seed
namespace(与 qualification corpus 不相交)。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_TIMEFRAME,
    curriculum261_eval_config,
    derive261_seed,
)
from rl_curriculum.curriculum261_production_obs import (
    production_observation_schema,
)
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.evaluator import select_features_strict
from rl_curriculum.generator_api import PRICE_COLUMNS
from rl_platform.env import AlignedLongFlatEnv

SMOKE_STEPS = 256
SMOKE_SEED = 7
SMOKE_BATCH = 64


def run_ppo_smoke(out_dir: Path | None = None) -> dict[str, Any]:
    """用 qualified C1 D1 生成器(training seed)执行 256-step PPO smoke。"""
    from stable_baselines3 import PPO

    schema = production_observation_schema()
    cfg = curriculum261_eval_config()
    spec = family_specs()["c1_opportunity"]
    rung_params = dict(spec.rung_params["D1"])
    rung_params["cur261_rung"] = "D1"
    seed = derive261_seed("training_r2", "c1_opportunity", "D1", 0, 0)
    episode = spec.generator.generate(
        spec.generator.base_params(rung_params, "A"), seed,
        split="curriculum261_training", timeframe=CURRICULUM261_TIMEFRAME)
    features = select_features_strict(episode.df, schema)
    env = AlignedLongFlatEnv(
        features=features, prices=episode.df[list(PRICE_COLUMNS)],
        fee=cfg.fee, slippage_bps=cfg.slippage_bps,
        initial_cash=cfg.initial_cash, window_size=1,
        execution_mode="market_open_causal")
    obs0, _ = env.reset(seed=SMOKE_SEED)
    model = PPO("MlpPolicy", env, n_steps=SMOKE_STEPS, batch_size=SMOKE_BATCH,
                seed=SMOKE_SEED, verbose=0, device="cpu")
    model.learn(total_timesteps=SMOKE_STEPS)

    # 复跑一个 episode 采集 reward/obs/action 的有限性证据
    obs, _ = env.reset(seed=SMOKE_SEED)
    rewards: list[float] = []
    finite_ok = True
    done = False
    steps = 0
    while not done:
        action, _ = model.predict(obs.reshape(1, -1), deterministic=True)
        obs, reward, terminated, truncated, _info = env.step(int(action[0]))
        done = terminated or truncated
        rewards.append(float(reward))
        finite_ok = finite_ok and np.isfinite(reward).all() \
            and np.isfinite(obs).all()
        steps += 1
    result: dict[str, Any] = {
        "format": "cur261-ppo-256step-smoke-v1",
        "runner": "stable_baselines3.PPO(MlpPolicy)",
        "steps": SMOKE_STEPS,
        "batch_size": SMOKE_BATCH,
        "seed": SMOKE_SEED,
        "seed_namespace": "training_r2",
        "episode_family": "c1_opportunity",
        "episode_rung": "D1",
        "observation_dim": int(schema.observation_dim),
        "observation_shape_ok": bool(obs0.shape == schema.observation_shape()),
        "action_space": "Discrete(2)",
        "eval_steps": steps,
        "rewards_finite": bool(finite_ok),
        "reward_sum": float(np.sum(rewards)),
        "no_crash": True,
        "note": "256-step PPO smoke:仅验证 env/obs/action/reward/"
                "SB3 plumbing;不构成课程训练,不参与课程参数选择",
        "executed_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
    }
    result["pass"] = bool(result["observation_shape_ok"]
                          and result["rewards_finite"] and result["no_crash"])
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "curriculum_ppo_256step_smoke.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8")
    return result
