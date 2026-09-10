"""阶段 2.6.2 Repair R2:诊断训练基础设施(真实梯度 + 真实 checkpoint)。

R1 的三处基础设施缺陷在本模块修复:

1. R1 的 gradient probe 用 -log_prob(action)(行为模仿式),不是 PPO
   clipped surrogate 梯度。R2 的 DiagnosedPPO2 完整复制 SB3 2.9.0
   PPO.train() 语义(逐 minibatch advantage 归一化 / ratio /
   clipped surrogate / entropy 项 / clip_grad_norm 在 optimizer.step
   之前),在真实 loss.backward() 之后、optimizer.step() 之前记录
   参数 .grad:actor/critic 总范数、第一层逐输入列、pre/post
   clipping 范数、surrogate 各分量,全部绑定
   {update_index, minibatch_index};
2. R1 预注册了 probability checkpoints 但从未传入 saver
   ("probability_dynamics_checkpoints": {})。R2 的 R2CheckpointStore
   把每个 checkpoint 的 policy state dict 真实写入磁盘(.pt),记录
   policy/actor/critic/optimizer 哈希,可重新加载并评估;
3. R1 的 BC 用单一 unweighted CE。R2 的 BC actor 克隆使用
   train-label 逆频率加权 CE(权重只来自 BC train 标签分布)。
"""

from __future__ import annotations

import hashlib
import io
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

DECISION_STEPS = 287


# ============================================================ 状态哈希
def _tensor_bytes(t) -> bytes:
    return np.ascontiguousarray(
        t.detach().cpu().numpy().astype(np.float32)).tobytes()


def policy_state_hash(model) -> str:
    h = hashlib.sha256()
    sd = model.policy.state_dict()
    for k in sorted(sd):
        h.update(k.encode("utf-8"))
        h.update(_tensor_bytes(sd[k]))
    return h.hexdigest()


def actor_state_hash(model) -> str:
    """actor 子网(policy_net + action_net)参数哈希。"""
    policy = model.policy
    h = hashlib.sha256()
    for mod in (policy.mlp_extractor.policy_net, policy.action_net):
        for p in mod.parameters():
            h.update(_tensor_bytes(p))
    return h.hexdigest()


def critic_state_hash(model) -> str:
    """critic 子网(value_net + value_net head)参数哈希。"""
    policy = model.policy
    h = hashlib.sha256()
    for mod in (policy.mlp_extractor.value_net, policy.value_net):
        for p in mod.parameters():
            h.update(_tensor_bytes(p))
    return h.hexdigest()


def optimizer_state_hash(model) -> str:
    """optimizer 状态哈希(torch.save 字节;identity 用)。"""
    buf = io.BytesIO()
    model.policy.optimizer.state_dict()  # ensure built
    import torch
    torch.save(model.policy.optimizer.state_dict(), buf)
    return hashlib.sha256(buf.getvalue()).hexdigest()


# ============================================================ checkpoint
class R2CheckpointStore:
    """R2 诊断 checkpoint 持久化(真实 state dict 落盘 + 哈希)。"""

    def __init__(self, root: Path, run_id: str, *, family: str,
                 arm: str, seed: int, expected_tags: tuple[str, ...]):
        self.dir = Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.family = family
        self.arm = arm
        self.seed = int(seed)
        self.expected_tags = tuple(expected_tags)
        self.records: dict[str, dict[str, Any]] = {}

    def save(self, episode_index: int, model,
             tag: str | None = None) -> dict[str, Any]:
        tag = tag or f"ep{int(episode_index)}"
        if tag in self.records:
            return self.records[tag]
        import torch
        path = self.dir / f"{tag}.pt"
        sd = {k: v.detach().cpu().clone()
              for k, v in model.policy.state_dict().items()}
        torch.save({
            "policy_state_dict": sd,
            "meta": {"run_id": self.run_id, "tag": tag,
                     "episode_index": int(episode_index),
                     "family": self.family, "arm": self.arm,
                     "seed": self.seed},
        }, path)
        rec = {
            "tag": tag,
            "episode_index": int(episode_index),
            "path": str(path),
            "policy_state_sha256": policy_state_hash(model),
            "actor_state_sha256": actor_state_hash(model),
            "critic_state_sha256": critic_state_hash(model),
            "optimizer_state_sha256": optimizer_state_hash(model),
            "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        }
        self.records[tag] = rec
        return rec

    def verify_expected(self) -> dict[str, Any]:
        """全部 expected tag 已保存、文件存在、哈希可复算。"""
        import torch
        problems: list[str] = []
        for tag in self.expected_tags:
            rec = self.records.get(tag)
            if rec is None:
                problems.append(f"checkpoint {tag} 未保存")
                continue
            p = Path(rec["path"])
            if not p.is_file():
                problems.append(f"checkpoint {tag} 文件缺失: {p}")
                continue
            blob = torch.load(p, map_location="cpu", weights_only=False)
            sd = blob["policy_state_dict"]
            h = hashlib.sha256()
            for k in sorted(sd):
                h.update(k.encode("utf-8"))
                h.update(_tensor_bytes(sd[k]))
            if h.hexdigest() != rec["policy_state_sha256"]:
                problems.append(f"checkpoint {tag} 哈希复算不一致")
        extra = sorted(set(self.records) - set(self.expected_tags))
        return {
            "run_id": self.run_id,
            "expected": list(self.expected_tags),
            "produced": sorted(self.records),
            "extra_tags": extra,
            "n_expected": len(self.expected_tags),
            "n_produced": len(self.records),
            "problems": problems,
            "pass": not problems and not extra,
        }


def load_r2_checkpoint(path, *, config: dict[str, Any], model_seed: int,
                       env, expect_policy_sha256: str | None = None):
    """从磁盘重新加载 checkpoint(可评估性证明)。"""
    import torch
    blob = torch.load(path, map_location="cpu", weights_only=False)
    model = build_diagnosed_ppo2(config, model_seed, env)
    model.policy.load_state_dict(blob["policy_state_dict"])
    if expect_policy_sha256 is not None:
        got = policy_state_hash(model)
        if got != expect_policy_sha256:
            raise ValueError(
                f"checkpoint 重载哈希不一致: {got} != {expect_policy_sha256}")
    return model


# ============================================================ PPO 子类
class DiagnosedPPO2:
    """构造器占位:实际类在 _build_diagnosed_ppo2_cls() 中动态派生。"""


def _build_diagnosed_ppo2_cls():
    import torch as th
    import torch.nn.functional as F
    from gymnasium import spaces
    from stable_baselines3 import PPO
    from stable_baselines3.common.utils import explained_variance

    class _DiagnosedPPO2(PPO):
        """PPO + 真实 surrogate 梯度/minibatch 诊断(R2)。

        train() 为 SB3 2.9.0 PPO.train() 的忠实副本 + 插桩:
        - 每个 minibatch 记录 surrogate 分量(policy/value/entropy
          loss、ratio、clip_fraction、approx_kl、advantage 分布);
        - loss.backward() 之后、clip_grad_norm_/step 之前记录
          actor/critic .grad 范数与第一层逐输入列(采样);
        - pre-clip 总范数(clip_grad_norm_ 返回值)与 post-clip
          总范数(重算)都记录;
        - 首个 minibatch 的张量与 pre-update 权重被克隆保存
          (diag2_first_minibatch),供单 minibatch 等价性测试
          手工复算对照;
        - rollout 计数与 buffer 统计同 R1 DiagnosedPPO。
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.diag_rollout_records: list[dict[str, Any]] = []
            self.diag2_update_records: list[dict[str, Any]] = []
            self.diag2_minibatch_records: list[dict[str, Any]] = []
            self._diag_rollouts_completed = 0
            self._diag2_mb_counter = 0
            self._diag2_detail_every = 1
            self.diag2_first_minibatch: dict[str, Any] | None = None

        # ---- rollout 计数与 buffer 统计(与 R1 同款)
        def collect_rollouts(self, env, callback, rollout_buffer,
                             n_rollout_steps):
            result = super().collect_rollouts(
                env, callback, rollout_buffer, n_rollout_steps)
            if result:
                self._diag_rollouts_completed += 1
                actions = rollout_buffer.actions.flatten()
                adv = np.asarray(rollout_buffer.advantages)
                ret = np.asarray(rollout_buffer.returns)
                rew = np.asarray(rollout_buffer.rewards)
                with th.no_grad():
                    obs_t = th.as_tensor(
                        rollout_buffer.observations, dtype=th.float32)
                    values = self.policy.predict_values(obs_t).numpy()
                ev = float(1.0 - np.var(ret - values.flatten())
                           / max(np.var(ret), 1e-12))
                adv_by_action: dict[str, dict[str, float]] = {}
                for a in (0, 1):
                    m = actions == a
                    adv_by_action[f"action_{a}"] = {
                        "mean": float(np.mean(adv[m])) if m.any() else None,
                        "std": float(np.std(adv[m])) if m.any() else None,
                        "n": int(np.sum(m)),
                    }
                self.diag_rollout_records.append({
                    "rollout_index": self._diag_rollouts_completed,
                    "env_step_start": int(
                        self.num_timesteps - len(rew)),
                    "env_step_end": int(self.num_timesteps),
                    "rewards": {
                        "mean": float(np.mean(rew)),
                        "std": float(np.std(rew)),
                        "min": float(np.min(rew)),
                        "max": float(np.max(rew)),
                    },
                    "returns": {"mean": float(np.mean(ret)),
                                "std": float(np.std(ret))},
                    "advantages": {
                        "mean": float(np.mean(adv)),
                        "std": float(np.std(adv)),
                        "positive_rate": float(np.mean(adv > 0)),
                        "negative_rate": float(np.mean(adv < 0)),
                    },
                    "advantages_by_action": adv_by_action,
                    "value_prediction": {
                        "mean": float(np.mean(values)),
                        "std": float(np.std(values)),
                        "value_bias": float(np.mean(
                            values.flatten() - ret)),
                        "value_mae": float(np.mean(np.abs(
                            values.flatten() - ret))),
                        "explained_variance_vs_returns": ev,
                    },
                    "action_mean": float(np.mean(actions)),
                })
            return result

        # ---- actor/critic 梯度工具
        @staticmethod
        def _grad_norm(params) -> float | None:
            gs = [p.grad for p in params if p.grad is not None]
            if not gs:
                return None
            return float(th.sqrt(sum((g.detach() ** 2).sum()
                                     for g in gs)))

        def _capture_minibatch_grads(self, rec: dict[str, Any]) -> None:
            policy = self.policy
            actor_params = (list(policy.mlp_extractor.policy_net.parameters())
                            + list(policy.action_net.parameters()))
            critic_params = (list(
                policy.mlp_extractor.value_net.parameters())
                + list(policy.value_net.parameters()))
            rec["actor_total_grad_norm"] = self._grad_norm(actor_params)
            rec["critic_total_grad_norm"] = self._grad_norm(critic_params)
            rec["action_head_grad_norm"] = self._grad_norm(
                policy.action_net.parameters())
            rec["value_head_grad_norm"] = self._grad_norm(
                policy.value_net.parameters())
            if (self._diag2_mb_counter % self._diag2_detail_every == 0):
                first_p = policy.mlp_extractor.policy_net[0]
                if first_p.weight.grad is not None:
                    g = first_p.weight.grad.detach().abs().mean(dim=0)
                    rec["policy_first_layer_per_input_abs_grad"] = [
                        float(x) for x in g]
                first_v = policy.mlp_extractor.value_net[0]
                if first_v.weight.grad is not None:
                    g = first_v.weight.grad.detach().abs().mean(dim=0)
                    rec["value_first_layer_per_input_abs_grad"] = [
                        float(x) for x in g]

        # ---- train():SB3 2.9.0 PPO.train() 忠实副本 + 插桩
        def train(self) -> None:
            self.policy.set_training_mode(True)
            self._update_learning_rate(self.policy.optimizer)
            clip_range = self.clip_range(self._current_progress_remaining)
            if self.clip_range_vf is not None:
                clip_range_vf = self.clip_range_vf(
                    self._current_progress_remaining)

            entropy_losses = []
            pg_losses, value_losses = [], []
            clip_fractions = []
            update_index = len(self.diag2_update_records) + 1
            mb_of_update = 0

            continue_training = True
            for epoch in range(self.n_epochs):
                approx_kl_divs = []
                for rollout_data in self.rollout_buffer.get(
                        self.batch_size):
                    actions = rollout_data.actions
                    if isinstance(self.action_space, spaces.Discrete):
                        actions = rollout_data.actions.long().flatten()

                    values, log_prob, entropy = (
                        self.policy.evaluate_actions(
                            rollout_data.observations, actions))
                    values = values.flatten()
                    advantages = rollout_data.advantages
                    adv_raw = advantages.detach().clone()
                    if self.normalize_advantage and len(advantages) > 1:
                        advantages = (
                            advantages - advantages.mean()) / (
                            advantages.std() + 1e-8)

                    ratio = th.exp(log_prob - rollout_data.old_log_prob)

                    policy_loss_1 = advantages * ratio
                    policy_loss_2 = advantages * th.clamp(
                        ratio, 1 - clip_range, 1 + clip_range)
                    policy_loss = -th.min(
                        policy_loss_1, policy_loss_2).mean()

                    pg_losses.append(policy_loss.item())
                    clip_fraction = th.mean(
                        (th.abs(ratio - 1) > clip_range).float()).item()
                    clip_fractions.append(clip_fraction)

                    if self.clip_range_vf is None:
                        values_pred = values
                    else:
                        values_pred = rollout_data.old_values + th.clamp(
                            values - rollout_data.old_values,
                            -clip_range_vf, clip_range_vf)
                    value_loss = F.mse_loss(rollout_data.returns,
                                            values_pred)
                    value_losses.append(value_loss.item())

                    if entropy is None:
                        entropy_loss = -th.mean(-log_prob)
                    else:
                        entropy_loss = -th.mean(entropy)
                    entropy_losses.append(entropy_loss.item())

                    loss = (policy_loss + self.ent_coef * entropy_loss
                            + self.vf_coef * value_loss)

                    with th.no_grad():
                        log_ratio = log_prob - rollout_data.old_log_prob
                        approx_kl_div = th.mean(
                            (th.exp(log_ratio) - 1) - log_ratio
                        ).cpu().numpy()
                        approx_kl_divs.append(approx_kl_div)

                    if (self.target_kl is not None
                            and approx_kl_div > 1.5 * self.target_kl):
                        continue_training = False
                        if self.verbose >= 1:
                            print(f"Early stopping at step {epoch} due "
                                  f"to reaching max kl: "
                                  f"{approx_kl_div:.2f}")
                        break

                    # ---- 插桩:真实 loss.backward 之后、clip/step 之前
                    self._diag2_mb_counter += 1
                    mb_of_update += 1
                    rec: dict[str, Any] = {
                        "update_index": update_index,
                        "minibatch_index": self._diag2_mb_counter,
                        "epoch": epoch,
                        "minibatch_of_update": mb_of_update,
                        "env_step": int(self.num_timesteps),
                        "n_samples": int(rollout_data.observations
                                         .shape[0]),
                        "clip_range": float(clip_range),
                        "ent_coef": float(self.ent_coef),
                        "vf_coef": float(self.vf_coef),
                        "policy_loss": float(policy_loss.item()),
                        "value_loss": float(value_loss.item()),
                        "entropy_loss": float(entropy_loss.item()),
                        "total_loss": float(loss.item()),
                        "clip_fraction": float(clip_fraction),
                        "approx_kl": float(approx_kl_div),
                        "ratio_mean": float(ratio.detach().mean()),
                        "ratio_abs_dev_mean": float(
                            (ratio.detach() - 1).abs().mean()),
                        "advantage_raw": {
                            "mean": float(adv_raw.mean()),
                            "std": float(adv_raw.std()),
                            "min": float(adv_raw.min()),
                            "max": float(adv_raw.max()),
                        },
                        "advantage_normalized": {
                            "mean": float(advantages.mean()),
                            "std": float(advantages.std()),
                        },
                    }
                    if self.diag2_first_minibatch is None:
                        self.diag2_first_minibatch = {
                            "update_index": update_index,
                            "minibatch_index": self._diag2_mb_counter,
                            "observations": rollout_data.observations
                                .detach().cpu().clone(),
                            "actions": actions.detach().cpu().clone(),
                            "old_log_prob": rollout_data.old_log_prob
                                .detach().cpu().clone(),
                            "returns": rollout_data.returns
                                .detach().cpu().clone(),
                            "advantages_raw": adv_raw,
                            "clip_range": float(clip_range),
                            "ent_coef": float(self.ent_coef),
                            "vf_coef": float(self.vf_coef),
                            "normalize_advantage": bool(
                                self.normalize_advantage),
                            "max_grad_norm": float(self.max_grad_norm),
                            "policy_state_before": {
                                k: v.detach().cpu().clone() for k, v in
                                self.policy.state_dict().items()},
                        }

                    self.policy.optimizer.zero_grad()
                    loss.backward()
                    self._capture_minibatch_grads(rec)
                    total_norm = th.nn.utils.clip_grad_norm_(
                        self.policy.parameters(), self.max_grad_norm)
                    rec["pre_clip_total_grad_norm"] = float(
                        getattr(total_norm, "total_norm", total_norm))
                    rec["post_clip_total_grad_norm"] = self._grad_norm(
                        self.policy.parameters())
                    self.policy.optimizer.step()
                    self.diag2_minibatch_records.append(rec)

                self._n_updates += 1
                if not continue_training:
                    break

            explained_var = explained_variance(
                self.rollout_buffer.values.flatten(),
                self.rollout_buffer.returns.flatten())

            self.logger.record("train/entropy_loss", np.mean(entropy_losses))
            self.logger.record("train/policy_gradient_loss",
                               np.mean(pg_losses))
            self.logger.record("train/value_loss", np.mean(value_losses))
            self.logger.record("train/approx_kl", np.mean(approx_kl_divs))
            self.logger.record("train/clip_fraction",
                               np.mean(clip_fractions))
            self.logger.record("train/loss", loss.item())
            self.logger.record("train/explained_variance", explained_var)
            if hasattr(self.policy, "log_std"):
                self.logger.record(
                    "train/std",
                    th.exp(self.policy.log_std).mean().item())

            self.logger.record("train/n_updates", self._n_updates,
                               exclude="tensorboard")
            self.logger.record("train/clip_range", clip_range)
            if self.clip_range_vf is not None:
                self.logger.record("train/clip_range_vf", clip_range_vf)

            self.diag2_update_records.append({
                "update_index": update_index,
                "rollout_index": self._diag_rollouts_completed,
                "env_step": int(self.num_timesteps),
                "n_minibatches": mb_of_update,
                "mean_policy_loss": float(np.mean(pg_losses)),
                "mean_value_loss": float(np.mean(value_losses)),
                "mean_entropy_loss": float(np.mean(entropy_losses)),
                "mean_clip_fraction": float(np.mean(clip_fractions)),
                "mean_approx_kl": float(np.mean(approx_kl_divs)),
                "final_loss": float(loss.item()),
                "explained_variance": float(explained_var),
            })

    return _DiagnosedPPO2


_DIAG2_PPO_CLS = None


def build_diagnosed_ppo2(config: dict[str, Any], seed: int, env):
    """DiagnosedPPO2 构造(与 ppo262_config.build_ppo 同参数语义)。"""
    global _DIAG2_PPO_CLS
    if _DIAG2_PPO_CLS is None:
        _DIAG2_PPO_CLS = _build_diagnosed_ppo2_cls()
    import torch
    act_fn = {"Tanh": torch.nn.Tanh,
              "ReLU": torch.nn.ReLU}[config["activation_fn"]]
    return _DIAG2_PPO_CLS(
        policy=config["policy"], env=env,
        learning_rate=config["learning_rate"],
        n_steps=config["n_steps"],
        batch_size=config["batch_size"],
        n_epochs=config["n_epochs"],
        gamma=config["gamma"],
        gae_lambda=config["gae_lambda"],
        clip_range=config["clip_range"],
        ent_coef=config["ent_coef"],
        vf_coef=config["vf_coef"],
        max_grad_norm=config["max_grad_norm"],
        policy_kwargs={
            "net_arch": list(config["net_arch"]),
            "activation_fn": act_fn,
        },
        seed=int(seed),
        verbose=0,
        device=config["device"],
    )


# ============================================================ 诊断 runner
def r2_diag_train_run(
    bank: list, *, config: dict[str, Any], model_seed: int,
    total_timesteps: int, run_label: str,
    adapter=None,
    checkpoint_store: R2CheckpointStore | None = None,
    checkpoint_episodes: tuple[int, ...] = (),
    gradient_detail_every: int = 1,
    bc_init_state: dict | None = None,
) -> dict[str, Any]:
    """R2 诊断训练 run(重复暴露 bank;真实 checkpoint;真实梯度)。

    与 R1 diag_train_run 的差异全部显式化:
    - checkpoint_store 必须真实保存(verify_expected 由调用方审计);
    - bc_init_state 载入后立即保存 after_bc_before_ppo checkpoint;
    - 梯度记录来自真实 PPO surrogate(DiagnosedPPO2.train);
    - 返回值含 checkpoint store 的 records(不再有空 dict 通道)。
    """
    from rl_curriculum.ppo262_diag_train import (
        DiagnosisCallback, ObsAdapter, ObsScaleWrapper, latent_label_series,
    )

    bank_steps = len(bank) * DECISION_STEPS
    if total_timesteps % DECISION_STEPS != 0:
        raise ValueError(
            f"total_timesteps {total_timesteps} 必须是 {DECISION_STEPS} 倍数")
    if total_timesteps % bank_steps != 0 or total_timesteps < bank_steps:
        raise ValueError(
            f"诊断预算 {total_timesteps} 必须是 bank 容量 {bank_steps} 的"
            f"整数倍(重复暴露以整 bank 为单位,cycles 对齐)")
    cycles = total_timesteps // bank_steps
    if config["n_steps"] % DECISION_STEPS != 0:
        raise ValueError(
            f"n_steps {config['n_steps']} 必须是 {DECISION_STEPS} 倍数")

    inner_env = CurriculumMultiEpisodeEnv(bank)
    if adapter is None or adapter.identity_equivalent():
        train_env = inner_env
        used_adapter = ObsAdapter.identity(
            int(inner_env.observation_space.shape[0]))
    else:
        train_env = ObsScaleWrapper(inner_env, adapter)
        used_adapter = adapter

    latent_labels = {}
    for i, loaded in enumerate(bank):
        latent_labels[i] = latent_label_series(
            loaded, loaded.key.family)

    def _save_checkpoint(n_done: int, model,
                         tag: str | None = None) -> None:
        if checkpoint_store is None:
            return
        if tag is not None or n_done in checkpoint_episodes:
            checkpoint_store.save(n_done, model, tag=tag)

    cb = DiagnosisCallback(
        inner_env, latent_labels=latent_labels,
        on_episode_done=_save_checkpoint)
    model = build_diagnosed_ppo2(config, model_seed, train_env)
    model._diag2_detail_every = int(gradient_detail_every)
    init_hash = policy_state_hash(model)
    bc_init_actor_hash = None
    if bc_init_state is None:
        # scratch run:initial checkpoint(任何 update 前)
        _save_checkpoint(0, model)
    else:
        # BC run:initial = BC 载入后的状态(after_bc_before_ppo),
        # 不另存随机初始化 ep0(计划 tag 集不含它)
        model.policy.load_state_dict(bc_init_state)
        bc_init_actor_hash = actor_state_hash(model)
        _save_checkpoint(0, model, tag="after_bc_before_ppo")

    t0 = time.time()
    model.learn(total_timesteps=total_timesteps,
                callback=cb.as_callback(), progress_bar=False)
    elapsed = time.time() - t0
    _save_checkpoint(total_timesteps // DECISION_STEPS, model)

    audit = inner_env.audit()
    problems: list[str] = []
    expected_episodes = cycles * len(bank)
    if audit["steps_taken"] != total_timesteps:
        problems.append(
            f"steps {audit['steps_taken']} != {total_timesteps}")
    if audit["episodes_consumed"] != expected_episodes:
        problems.append(
            f"episodes {audit['episodes_consumed']} != {expected_episodes}"
            f"(cycles={cycles} x {len(bank)})")
    if audit["exhausted_cycles"] != cycles:
        problems.append(
            f"exhausted_cycles {audit['exhausted_cycles']} != {cycles}")
    if audit["duplicate_episode_completions"] != (
            expected_episodes - len(bank)):
        problems.append(
            f"重复完成计数 {audit['duplicate_episode_completions']} 与 "
            f"cycles 合同不符(期望 {expected_episodes - len(bank)})")

    return {
        "run_label": run_label,
        "model_seed": int(model_seed),
        "total_timesteps": total_timesteps,
        "cycles": cycles,
        "bank_episodes": len(bank),
        "adapter": used_adapter.describe(),
        "elapsed_seconds": round(elapsed, 1),
        "fps": round(total_timesteps / max(elapsed, 1e-9), 1),
        "env_audit": audit,
        "audit_problems": problems,
        "pass": not problems,
        "episode_curve": cb.impl.episode_rows,
        "step_diagnostics_rows": len(cb.impl.step_rows),
        "update_records": model.diag2_update_records,
        "minibatch_records": model.diag2_minibatch_records,
        "first_minibatch_capture_present": (
            model.diag2_first_minibatch is not None),
        "rollout_records": model.diag_rollout_records,
        "initial_policy_state_sha256": init_hash,
        "bc_init_actor_state_sha256": bc_init_actor_hash,
        "checkpoint_records": dict(checkpoint_store.records)
        if checkpoint_store is not None else {},
        "checkpoint_verification": (
            checkpoint_store.verify_expected()
            if checkpoint_store is not None else None),
        "model": model,
    }


# ============================================================ BC(R2)
def collect_family_bc_dataset(
    bank: list, family: str, rung_params: dict[str, Any],
    thresholds: dict[str, Any], schema, eval_config,
) -> dict[str, Any]:
    """按 family 收集 (obs, action) 监督数据(reference 逐 rung 正确构建)。

    - label 只来自 causal observation reference policy(该 family 该
      rung 的正确 reference;不读 latent oracle / future / 元数据);
    - 逐行保留 pair 身份(held-out pair performance 用);
    - 收到非本 family episode 时 fail closed。
    """
    from rl_curriculum.evaluator import run_observation_episode
    from rl_curriculum.ppo262_metrics import build_261_policy_set

    xs, ys, row_pairs, ep_meta = [], [], [], []
    pols_by_rung: dict[str, Any] = {}
    for loaded in bank:
        if loaded.key.family != family:
            raise ValueError(
                f"collect_family_bc_dataset 收到异族 episode:"
                f"{loaded.key.canonical()}(期望 {family})")
        rung = loaded.key.rung
        pols = pols_by_rung.get(rung) or build_261_policy_set(
            family, rung_params[family][rung], thresholds[family])
        pols_by_rung[rung] = pols
        _, actions, obs_list = run_observation_episode(
            pols["reference"], loaded.episode, eval_config, schema,
            return_actions=True, return_observations=True)
        pair_id = (rung, int(loaded.key.pair_index))
        for o, a in zip(obs_list, actions):
            xs.append(np.asarray(o, dtype=np.float32))
            ys.append(int(a))
            row_pairs.append(pair_id)
        ep_meta.append({
            "family": family, "rung": rung,
            "pair_index": int(loaded.key.pair_index),
            "variant": loaded.key.variant,
            "episode_key": loaded.key.canonical(),
        })
    return {
        "X": np.stack(xs), "y": np.asarray(ys, dtype=np.int64),
        "row_pairs": row_pairs, "episode_meta": ep_meta,
    }


def balanced_class_weights(y: np.ndarray) -> dict[int, float]:
    """逆频率类权重(只来自给定 label 分布;train-only 合同)。"""
    y = np.asarray(y)
    n = len(y)
    return {int(c): float(n / (2.0 * np.sum(y == c)))
            for c in (0, 1) if np.any(y == c)}


def bc_retention(bc_bal: float | None, ft_bal: float | None,
                 thr: dict[str, Any]) -> dict[str, Any]:
    """BC retention 纯函数(预注册规则;cmd_bc 与测试共用)。

    - bc_learned:BC 结束 held-out balanced accuracy >= 阈值;
    - retained:学会且 fine-tune 绝对下降 <= 阈值 且终值 >= 阈值;
    - destroyed:学会且(下降超阈 或 终值低于阈值)。
    """
    bc_learned = bool(bc_bal is not None and bc_bal >= thr[
        "bc_learned_min_bal_acc"])
    drop = (bc_bal - ft_bal) if (bc_bal is not None
                                  and ft_bal is not None) else None
    retained = bool(
        bc_learned and drop is not None
        and drop <= thr["bc_retained_max_drop"]
        and ft_bal >= thr["bc_retained_min_final_bal_acc"])
    destroyed = bool(
        bc_learned and (
            (drop is not None and drop > thr["bc_retained_max_drop"])
            or (ft_bal is not None
                and ft_bal < thr["bc_retained_min_final_bal_acc"])))
    return {"bc_learned": bc_learned, "drop": drop,
            "retained": retained, "destroyed": destroyed}


def bc_train_actor_weighted(
    model, dataset: dict[str, Any], *, epochs: int, lr: float,
    adapter, rng_seed: int, class_weighted: bool = True,
) -> dict[str, Any]:
    """actor behavior cloning(冻结 critic;加权 CE)。

    权重只来自 dataset["y"](BC train 标签);class_weighted=False
    时退化为 unweighted(历史对照口径)。
    """
    import torch
    policy = model.policy
    actor_params = (list(policy.mlp_extractor.policy_net.parameters())
                    + list(policy.action_net.parameters()))
    opt = torch.optim.Adam(actor_params, lr=lr)
    X = torch.as_tensor(np.stack(
        [adapter.apply(x) for x in dataset["X"]]), dtype=torch.float32)
    y = torch.as_tensor(dataset["y"], dtype=torch.long)
    class_weight = None
    if class_weighted:
        wmap = balanced_class_weights(dataset["y"])
        class_weight = torch.as_tensor(
            [wmap.get(int(c), 1.0) for c in (0, 1)],
            dtype=torch.float32)
    gen = torch.Generator().manual_seed(int(rng_seed))
    history = []
    for epoch in range(epochs):
        opt.zero_grad()
        dist = policy.get_distribution(X)
        loss = torch.nn.functional.cross_entropy(
            dist.distribution.logits, y, weight=class_weight)
        loss.backward()
        opt.step()
        with torch.no_grad():
            match = float((dist.distribution.logits.argmax(dim=-1)
                           == y).float().mean())
        history.append({"epoch": epoch + 1, "loss": float(loss.item()),
                        "match_rate": match})
    return {
        "epochs": epochs, "lr": lr, "class_weighted": class_weighted,
        "class_weights": (balanced_class_weights(dataset["y"])
                          if class_weighted else None),
        "final_train_match_rate": history[-1]["match_rate"],
        "history": history,
        "rng_seed": int(rng_seed),
    }
