"""阶段 2.6.2:PPO 训练 runner(core replicates / probes / config dev)。

- bank(manifest)→ CurriculumMultiEpisodeEnv(n_envs=1)→ PPO;
- checkpoint 计划:episode 边界 0 / 160 / 400 / 640(staged = 初始/
  after-C1/after-C2/final;mixed = matched-step 同边界);
- 学习曲线:custom callback 收集逐 episode reward / net return /
  long fraction / position changes / entropy / approx KL / clip frac /
  value loss / policy loss / explained variance / grad-norm 诊断;
- 训练后强制审计:steps == 预算、episodes == bank 大小、无跳过/
  重复/越界(exhausted_cycles <= 1);
- 模型持久化:SB3 zip + sidecar manifest(config digest / model seed /
  manifest hash / observation identity / SB3+torch 版本 / 文件 sha256)。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from rl_curriculum.ppo262_banks import (
    EpisodeKey, LoadedEpisode, bank_manifest,
)
from rl_curriculum.ppo262_config import build_ppo
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

DECISION_STEPS = 287


# ---------------------------------------------------------------- callback
class TeachingCurveCallback:
    """逐 episode 学习曲线 + 逐 rollout PPO 诊断(SB3 兼容 callback)。

    不写 TensorBoard 全量目录;只产出结构化摘要(§21)。
    on_episode_done(n_episodes_completed, model) 在每个 episode 完成
    时触发(checkpoint 保存钩子,由 train_run 注入)。
    """

    def __init__(self, env: CurriculumMultiEpisodeEnv,
                 on_episode_done=None):
        from stable_baselines3.common.callbacks import BaseCallback

        class _Impl(BaseCallback):
            def __init__(inner_self):
                super().__init__(verbose=0)
                inner_self.episode_rows: list[dict[str, Any]] = []
                inner_self.rollout_rows: list[dict[str, Any]] = []
                inner_self._ep_positions: list[int] = []
                inner_self._ep_changes = 0
                inner_self._ep_rewards = 0.0
                inner_self._ep_fees = 0.0
                inner_self._ep_steps = 0

            def _on_step(inner_self) -> bool:
                infos = inner_self.locals.get("infos", [])
                for info in infos:
                    if "episode_index" not in info:
                        continue
                    inner_self._ep_rewards += float(info.get(
                        "reward_raw", info.get("episode_reward_raw", 0.0)))
                    inner_self._ep_steps += 1
                    inner_self._ep_fees += float(info.get("fee_paid", 0.0))
                    inner_self._ep_positions.append(
                        int(info.get("new_target_position", 0)))
                    if (len(inner_self._ep_positions) > 1
                            and inner_self._ep_positions[-1]
                            != inner_self._ep_positions[-2]):
                        inner_self._ep_changes += 1
                    if info.get("terminated", False):
                        liq = info.get("terminal_liquidation") or {}
                        row = {
                            "env_step": inner_self.num_timesteps,
                            "episode_index": info["episode_index"],
                            "manifest_index": info.get(
                                "manifest_index", info["episode_index"]),
                            "episode_key": info.get("episode_key", ""),
                            "namespace": info.get("namespace"),
                            "family": info.get("family"),
                            "rung": info.get("rung"),
                            "pair_index": info.get("pair_index"),
                            "variant": info.get("variant"),
                            "steps": inner_self._ep_steps,
                            "episode_reward_raw": inner_self._ep_rewards,
                            "long_fraction": float(np.mean(
                                inner_self._ep_positions)),
                            "position_changes": inner_self._ep_changes,
                            "cost_fees_paid": inner_self._ep_fees,
                            "terminal_liquidation_fee": float(
                                liq.get("fee_paid", 0.0)),
                        }
                        if not row["episode_key"]:
                            raise RuntimeError(
                                "terminal step 丢失 episode attribution"
                                "(Repair C 合同被破坏:info 必须携带 "
                                "episode_key/family/rung 等字段)")
                        inner_self.episode_rows.append(row)
                        inner_self._ep_positions = []
                        inner_self._ep_changes = 0
                        inner_self._ep_rewards = 0.0
                        inner_self._ep_steps = 0
                        inner_self._ep_fees = 0.0
                        if on_episode_done is not None:
                            on_episode_done(
                                env.episodes_consumed, inner_self.model)
                return True

            def _on_rollout_end(inner_self) -> None:
                # Repair D:不再在此处读取 train/* logger 值——SB3 2.9.0
                # 的时序是 collect_rollouts(on_rollout_end)先于 train(),
                # 且 train() 末尾 dump 清空 name_to_value,这里读到的
                # 只能是空 dict 或滞后一轮的值(s262_r0 根因之一)。
                # rollout/update 绑定的 train/* 记录改由 DiagnosedPPO
                # 在 train() 内捕获(update_records,含 rollout_index/
                # update_index/env_step 绑定与 missing_metrics 显式声明)。
                return None

        self.impl = _Impl()

    def as_callback(self):
        return self.impl


# ---------------------------------------------------------------- 训练入口
def save_model_with_manifest(model, out_path: Path, *, manifest: dict):
    """SB3 save + sidecar manifest(模型文件 sha256 一并写入)。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out_path))
    zip_path = out_path.with_suffix(".zip")
    h = hashlib.sha256()
    h.update(zip_path.read_bytes())
    manifest = dict(manifest)
    manifest["model_file"] = zip_path.name
    manifest["model_sha256"] = h.hexdigest()
    sidecar = out_path.with_suffix(".manifest.json")
    sidecar.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    return manifest


def model_manifest_base(*, config_name: str, config: dict[str, Any],
                        model_seed: int, order_name: str,
                        run_label: str) -> dict[str, Any]:
    import stable_baselines3
    import torch

    from rl_curriculum.curriculum261_production_obs import (
        production_observation_identity,
    )
    from rl_curriculum.ppo262_config import candidate_digest

    return {
        "format": "ppo262-model-manifest-v1",
        "run_label": run_label,
        "order_name": order_name,
        "config_name": config_name,
        "config": config,
        "config_digest": candidate_digest(config_name),
        "model_seed": int(model_seed),
        "sb3_version": stable_baselines3.__version__,
        "torch_version": torch.__version__,
        "device": str(config.get("device", "cpu")),
        "observation_identity": production_observation_identity(),
        "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def train_run(
    bank: list[LoadedEpisode], *,
    config_name: str, config: dict[str, Any], model_seed: int,
    total_timesteps: int, order_name: str, run_label: str,
    checkpoint_episodes: tuple[int, ...] | None = None,
    checkpoint_dir: Path | None = None,
    checkpoint_saver: Callable[[int, Any], Any] | None = None,
) -> dict[str, Any]:
    """一次确定性 PPO 训练 run(训练后审计 + 曲线 + 可选 checkpoint)。

    total_timesteps 必须是 287 的倍数且 <= bank 步数;checkpoint 在
    episode 边界保存(checkpoint_saver(n_episodes_done, model))。
    """
    bank_steps = len(bank) * DECISION_STEPS
    if total_timesteps % DECISION_STEPS != 0:
        raise ValueError(
            f"total_timesteps {total_timesteps} 必须是 {DECISION_STEPS} 的"
            f"倍数(episode 边界对齐,禁止半 episode 停止)")
    if total_timesteps > bank_steps:
        raise ValueError(
            f"total_timesteps {total_timesteps} 超过 bank 容量 "
            f"{bank_steps}(不得循环训练 bank)")
    if config["n_steps"] % DECISION_STEPS != 0:
        raise ValueError(
            f"n_steps {config['n_steps']} 必须是 {DECISION_STEPS} 的倍数"
            f"(rollout 块边界与 episode 边界对齐)")

    env = CurriculumMultiEpisodeEnv(bank)
    checkpoints: dict[str, Any] = {}

    def _save_checkpoint(n_done: int, model) -> None:
        if checkpoint_episodes is None or checkpoint_saver is None:
            return
        if n_done in checkpoint_episodes:
            tag = f"ep{n_done}"
            if tag not in checkpoints:
                checkpoints[tag] = checkpoint_saver(n_done, model)

    curve = TeachingCurveCallback(env, on_episode_done=_save_checkpoint)
    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    # Repair D:DiagnosedPPO 与原生 PPO 同参构造(不消耗额外随机数,
    # 同 seed 初始权重逐位一致),train() 内捕获本 update 的 train/*
    # 指标并绑定 rollout/update index
    model = build_diagnosed_ppo(config, model_seed, env)

    # 初始 checkpoint(0 个 episode 完成:构造后、任何更新前)
    _save_checkpoint(0, model)

    t0 = time.time()
    model.learn(total_timesteps=total_timesteps, callback=curve.as_callback(),
                progress_bar=False)
    elapsed = time.time() - t0

    # 训练后审计(fail closed)
    audit = env.audit()
    problems: list[str] = []
    if audit["steps_taken"] != total_timesteps:
        problems.append(
            f"steps {audit['steps_taken']} != 预算 {total_timesteps}")
    if audit["episodes_consumed"] * DECISION_STEPS != total_timesteps:
        problems.append(
            f"完成的 episode 步数与预算不平("
            f"{audit['episodes_consumed']} x {DECISION_STEPS})")
    if audit["duplicate_episode_completions"] != 0:
        problems.append("存在重复完成的 episode(违反不循环合同)")
    if not audit["first_pass_order_ok"]:
        problems.append("episode 消费顺序非 first-pass")
    if audit["exhausted_cycles"] > 1:
        problems.append(
            f"exhausted_cycles = {audit['exhausted_cycles']}"
            f"(训练越界 bank)")
    # final checkpoint(最后一个 episode 完成处由 callback 保存;
    # 若 learn 因 SB3 内部语义未触发,这里补一次显式保存)
    _save_checkpoint(total_timesteps // DECISION_STEPS, model)

    manifest = bank_manifest(bank)
    return {
        "run_label": run_label,
        "order_name": order_name,
        "config_name": config_name,
        "model_seed": int(model_seed),
        "total_timesteps": total_timesteps,
        "elapsed_seconds": round(elapsed, 1),
        "fps": round(total_timesteps / max(elapsed, 1e-9), 1),
        "bank_manifest": manifest,
        "env_audit": audit,
        "audit_problems": problems,
        "pass": not problems,
        "episode_curve": curve.impl.episode_rows,
        # Repair D:rollout 曲线 = DiagnosedPPO 的 update 记录
        # (每条绑定 update_index/rollout_index/env_step;
        # 缺失 metric 显式在 missing_metrics)
        "rollout_curve": model.diag_update_records,
        "rollout_buffer_stats": model.diag_rollout_records,
        "checkpoints": {k: v for k, v in checkpoints.items()},
        "model": model,  # 训练后模型(调用方保存;不进 JSON)
    }
