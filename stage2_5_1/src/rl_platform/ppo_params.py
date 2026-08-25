"""显式 PPO 训练预算(阶段 2.5.1 工作包 A)。

阶段 2.5 的问题:
1. PPO 参数分散在 rl_config / model_training_parameters / RouteCModel 默认值 /
   Stable-Baselines3 默认值四处,没有单一来源;
2. total_timesteps = train_cycles * len(train_features) 不是 PPO 实际执行的
   环境步数(PPO 按完整 rollout 收集,一次 rollout 恰好 n_steps 步),
   "每窗 482 timesteps" 是错误记录(实际为向上取整到 n_steps 倍数后的步数)。

本模块建立:
- resolve_ppo_params():从渲染后配置的 freqai.route_c.ppo 节点解析出
  完整 PPO 参数集(唯一来源;rl_config / model_training_parameters 中出现
  任何 PPO 构造参数即视为冲突,直接报错,不得静默覆盖);
- compute_budget():base/rounded 训练预算;
- run_ppo_fit():构造 PPO、执行 rounded_budget 步训练、验证
  model.num_timesteps == rounded_budget,并把训练记录写入 json。

固定 SB3 版本:stable-baselines3 2.9.0(PIP_REQUIREMENT 由依赖版本指纹记录)。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import torch as th
from stable_baselines3 import PPO
from stable_baselines3.common.utils import set_random_seed


class RouteCPPOConfigError(RuntimeError):
    """PPO 参数冲突或非法(不得静默覆盖)。"""


# PPO() 构造函数中由本阶段显式固定的参数(唯一来源 = freqai.route_c.ppo)。
# net_arch 经 policy_kwargs 传入,也视为同一来源管理的键。
DEFAULT_ROUTE_C_PPO: dict[str, Any] = {
    "n_steps": 128,
    "batch_size": 64,
    "n_epochs": 10,
    "learning_rate": 0.00025,
    "gamma": 0.90,
    "gae_lambda": 0.95,
    "clip_range": 0.20,
    "ent_coef": 0.0,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "normalize_advantage": True,
    "net_arch": [32, 32],
}

# PPO 构造之外、由 resolved 参数一并携带的执行环境字段。
PPO_RUNTIME_DEFAULTS: dict[str, Any] = {
    "policy_type": "MlpPolicy",
    "device": "cpu",
    "n_envs": 1,
    "seed": 42,
}


def resolve_ppo_params(freqai_info: dict[str, Any], strict: bool = False) -> dict[str, Any]:
    """解析完整 PPO 参数集。

    唯一来源是 freqai_info["route_c"]["ppo"](缺省键取显式默认值)。

    :param strict: 渲染阶段的冲突检测。True 时若 rl_config 或
        model_training_parameters 中出现任何 PPO 构造参数键,直接抛错。
        注意上游 FreqtradeValidator 会在 config 校验时按 schema 自动填充
        rl_config 默认键(如 net_arch=[128,128]),因此 freqtrade 进程内
        (RouteCModel.__init__)必须用 strict=False;只有实验入口渲染
        原始配置时(未经 schema 填充)才用 strict=True 检测用户配置冲突。
    """
    ppo_node = ((freqai_info or {}).get("route_c") or {}).get("ppo") or {}
    unknown = sorted(set(ppo_node) - set(DEFAULT_ROUTE_C_PPO))
    if unknown:
        raise RouteCPPOConfigError(
            f"freqai.route_c.ppo 含未知键 {unknown};"
            f"允许的键为 {sorted(DEFAULT_ROUTE_C_PPO)}"
        )

    if strict:
        for section in ("rl_config", "model_training_parameters"):
            dup = sorted(set((freqai_info or {}).get(section) or {}) & set(DEFAULT_ROUTE_C_PPO))
            if dup:
                raise RouteCPPOConfigError(
                    f"freqai.{section} 中出现 PPO 构造参数 {dup};"
                    "PPO 参数唯一来源是 freqai.route_c.ppo,不得重复配置"
                )

    resolved = dict(DEFAULT_ROUTE_C_PPO)
    resolved.update(ppo_node)
    resolved["net_arch"] = [int(x) for x in resolved["net_arch"]]
    for key in ("n_steps", "batch_size", "n_epochs"):
        resolved[key] = int(resolved[key])
        if resolved[key] < 1:
            raise RouteCPPOConfigError(f"{key} 必须 >= 1")
    for key in ("learning_rate", "gamma", "gae_lambda", "clip_range", "ent_coef",
                "vf_coef", "max_grad_norm"):
        resolved[key] = float(resolved[key])
    resolved["normalize_advantage"] = bool(resolved["normalize_advantage"])

    runtime = dict(PPO_RUNTIME_DEFAULTS)
    route_c = (freqai_info or {}).get("route_c") or {}
    runtime["policy_type"] = str(route_c.get("policy_type", runtime["policy_type"]))
    runtime["device"] = str(route_c.get("device", runtime["device"]))
    runtime["seed"] = int(route_c.get("seed", runtime["seed"]))
    n_envs = int(route_c.get("n_envs", runtime["n_envs"]))
    if n_envs != 1:
        raise RouteCPPOConfigError(
            f"阶段 2.5.1 仅支持 n_envs=1(固定 seed 的确定性烟雾口径),收到 {n_envs}"
        )
    runtime["n_envs"] = n_envs
    return {"runtime": runtime, "constructor": resolved}


def compute_budget(train_cycles: int, n_train_rows: int, n_steps: int) -> dict[str, Any]:
    """PPO 按 n_steps 的整数倍收集 rollout。

    base_budget    = train_cycles * n_train_rows(名义预算,与官方公式一致)
    rounded_budget = ceil(base_budget / n_steps) * n_steps(实际传给 learn)
    """
    base = int(train_cycles) * int(n_train_rows)
    rounded = int(math.ceil(base / n_steps) * n_steps)
    return {
        "base_budget": base,
        "rounded_budget": rounded,
        "n_steps": int(n_steps),
        "n_rollouts": rounded // int(n_steps),
        "train_cycles": int(train_cycles),
        "n_train_rows": int(n_train_rows),
    }


def run_ppo_fit(
    env: Any,
    resolved: dict[str, Any],
    train_cycles: int,
    n_train_rows: int,
    tensorboard_log: Path | None,
    record_path: Path | None = None,
    env_reset_count_attr: str = "episode_reset_count",
) -> tuple[PPO, dict[str, Any]]:
    """构造并训练 PPO,验证并返回训练预算记录。

    训练后硬性断言 model.num_timesteps == rounded_budget(若不成立,
    说明 SB3 版本行为变化,必须显式失败而不是记录一个错误步数)。
    """
    runtime = resolved["runtime"]
    ctor = resolved["constructor"]
    budget = compute_budget(train_cycles, n_train_rows, ctor["n_steps"])

    set_random_seed(runtime["seed"])
    policy_kwargs = dict(activation_fn=th.nn.ReLU, net_arch=list(ctor["net_arch"]))
    model = PPO(
        runtime["policy_type"],
        env,
        policy_kwargs=policy_kwargs,
        tensorboard_log=tensorboard_log,
        device=runtime["device"],
        seed=runtime["seed"],
        verbose=1,
        **{k: v for k, v in ctor.items() if k != "net_arch"},
    )
    model.learn(total_timesteps=budget["rounded_budget"])

    actual = int(model.num_timesteps)
    if actual != budget["rounded_budget"]:
        raise RouteCPPOConfigError(
            f"PPO 实际训练步数 {actual} != rounded_budget {budget['rounded_budget']};"
            "SB3 rollout 语义与本模块假设不符,需人工核查"
        )
    if budget["rounded_budget"] % budget["n_steps"] != 0:
        raise RouteCPPOConfigError("rounded_budget 必须是 n_steps 的整数倍")

    record = {
        **budget,
        "actual_num_timesteps": actual,
        "device": runtime["device"],
        "seed": runtime["seed"],
        "policy_type": runtime["policy_type"],
        "n_envs": runtime["n_envs"],
        "episode_resets": int(getattr(env, env_reset_count_attr, 0)),
        "tensorboard_log": str(tensorboard_log) if tensorboard_log else None,
    }
    if record_path is not None:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return model, record
