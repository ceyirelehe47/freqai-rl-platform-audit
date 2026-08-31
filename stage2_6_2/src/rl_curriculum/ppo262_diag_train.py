"""阶段 2.6.2 Repair R1:诊断训练基础设施(official 合同之外,独立 namespace)。

本模块只服务 diagnostic workflow(s262_diag_r1):

- DiagnosedPPO:子类化 SB3 PPO,把 train/* 指标绑定到正确的
  rollout/update(Repair D:s262_r0 的 callback 在 on_rollout_end 读
  logger,时序上永远滞后一轮且首轮为空);
- ObsAdapter / ObsScaleWrapper:preprocessing ablation 的
  observation 仿射适配层(Wrapper + 评估侧 policy 适配,不触碰
  AlignedLongFlatEnv / evaluator / 生产 observation 合同);
- diag_train_run:允许重复暴露 bank 的诊断训练 runner(
  official train_run 的"不循环 bank"合同在此不适用,以显式
  cycles 计数与审计替代);
- BC warm-start:reference-policy 监督标签 -> actor 克隆 -> PPO
  fine-tune(区分 representation / initialization / update 问题)。

诊断产物一律写 artifacts/route_c_stage2_6_2/repair1/,不得进入
official final namespace,不得生成 official PASS。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

DECISION_STEPS = 287

#: PPO train 阶段 logger 键 -> 诊断记录键(SB3 2.9.0 标准 PPO 输出)
DIAG_TRAIN_METRIC_MAP: tuple[tuple[str, str], ...] = (
    ("train/entropy_loss", "entropy_loss"),
    ("train/approx_kl", "approx_kl"),
    ("train/clip_fraction", "clip_fraction"),
    ("train/value_loss", "value_loss"),
    ("train/policy_gradient_loss", "policy_loss"),
    ("train/explained_variance", "explained_variance"),
    ("train/loss", "loss"),
    ("train/grad_norm", "grad_norm"),
)


# ================================================================ PPO 子类
class DiagnosedPPO:
    """构造器占位:实际类在 _build_diagnosed_ppo_cls() 中动态派生。

    SB3 的 PPO 在 import 时不一定可用(纯统计路径不依赖 torch),
    因此类定义惰性完成;train_run 层统一通过 build_diagnosed_ppo
    构造,保证 official train_run 与 diagnostic runner 共用同一实现。
    """


def _build_diagnosed_ppo_cls():
    from stable_baselines3 import PPO

    class _DiagnosedPPO(PPO):
        """PPO + rollout/update 诊断绑定(Repair D)。

        - collect_rollouts 完成计数 + rollout buffer 分布统计
          (rewards/returns/advantages/by-action/by-latent 由外部
          callback 以 step 对齐补充);
        - train() 返回后直接读取 logger.name_to_value 中**本次**
          update 写入的 train/* 值(SB3 2.9.0 的 dump/清空发生在
          learn 循环的 dump_logs(),晚于 train()——事后在
          on_rollout_end 读只能拿到空 dict,正是 s262_r0 的根因);
        - 每条记录绑定 {update_index, rollout_index, env_step};
          缺失的 metric 显式列入 missing_metrics,绝不静默填 0;
        - __init__ 不消耗任何额外随机数:同 seed 下初始权重与
          原生 PPO 逐位一致(权重复现合同不破坏)。
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.diag_update_records: list[dict[str, Any]] = []
            self.diag_rollout_records: list[dict[str, Any]] = []
            self._diag_rollouts_completed = 0

        # ---- rollout 计数与 buffer 统计
        def collect_rollouts(self, env, callback, rollout_buffer,
                             n_rollout_steps):
            import torch
            result = super().collect_rollouts(
                env, callback, rollout_buffer, n_rollout_steps)
            if result:
                self._diag_rollouts_completed += 1
                actions = rollout_buffer.actions.flatten()
                adv = np.asarray(rollout_buffer.advantages)
                ret = np.asarray(rollout_buffer.returns)
                rew = np.asarray(rollout_buffer.rewards)
                with torch.no_grad():
                    obs_t = torch.as_tensor(
                        rollout_buffer.observations, dtype=torch.float32)
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
                    "env_step_start": int(self.num_timesteps - len(rew)),
                    "env_step_end": int(self.num_timesteps),
                    "rewards": {
                        "mean": float(np.mean(rew)), "std": float(np.std(rew)),
                        "min": float(np.min(rew)), "max": float(np.max(rew)),
                    },
                    "returns": {
                        "mean": float(np.mean(ret)), "std": float(np.std(ret)),
                    },
                    "advantages": {
                        "mean": float(np.mean(adv)), "std": float(np.std(adv)),
                        "positive_rate": float(np.mean(adv > 0)),
                        "negative_rate": float(np.mean(adv < 0)),
                    },
                    "advantages_by_action": adv_by_action,
                    "value_prediction": {
                        "mean": float(np.mean(values)),
                        "std": float(np.std(values)),
                        "value_bias": float(np.mean(values.flatten() - ret)),
                        "value_mae": float(np.mean(np.abs(
                            values.flatten() - ret))),
                        "explained_variance_vs_returns": ev,
                    },
                    "action_mean": float(np.mean(actions)),
                })
            return result

        # ---- update 指标捕获(绑定到刚完成的 rollout)
        def train(self) -> None:
            # SB3 2.9.0 的 PPO.train() 不再记录 train/grad_norm
            # (clip_grad_norm_ 返回值被丢弃);此处临时包装
            # clip_grad_norm_ 捕获 clipping 前的总梯度范数
            import torch as th
            grad_norms: list[float] = []
            orig_clip = th.nn.utils.clip_grad_norm_

            def _clip(params, max_norm, *a, **kw):
                val = orig_clip(params, max_norm, *a, **kw)
                try:
                    norm = getattr(val, "total_norm", val)
                    grad_norms.append(float(norm))
                except (TypeError, ValueError):
                    pass
                return val

            th.nn.utils.clip_grad_norm_ = _clip
            try:
                super().train()
            finally:
                th.nn.utils.clip_grad_norm_ = orig_clip
            # SB3 2.9.0 时序(实测核对):learn 循环 =
            # collect_rollouts -> train()(只 logger.record,不 dump)
            # -> dump_logs()(logger.dump 并清空 name_to_value)。
            # 因此 train() 返回后、dump_logs 前读取 name_to_value,
            # 拿到的恰好是**本次** update 写入的 train/* 值——
            # s262_r0 的 callback 在 on_rollout_end(上一轮 dump 之后、
            # 本轮 train 之前)读取,只能得到空 dict(Repair D 根因)。
            captured = dict(self.logger.name_to_value or {})
            record: dict[str, Any] = {
                "update_index": len(self.diag_update_records) + 1,
                "rollout_index": self._diag_rollouts_completed,
                "env_step": int(self.num_timesteps),
            }
            missing = []
            for src, dst in DIAG_TRAIN_METRIC_MAP:
                if src == "train/grad_norm":
                    # grad_norm 走 clip 包装通道(SB3 2.9.0 无此 logger 键)
                    if grad_norms:
                        record["grad_norm"] = float(np.mean(grad_norms))
                        record["grad_norm_max"] = float(np.max(grad_norms))
                    else:
                        missing.append("grad_norm(not captured)")
                    continue
                if src in captured:
                    record[dst] = float(captured[src])
                else:
                    missing.append(src)
            record["missing_metrics"] = missing
            self.diag_update_records.append(record)

    return _DiagnosedPPO


_DIAG_PPO_CLS = None


def build_diagnosed_ppo(config: dict[str, Any], seed: int, env):
    """DiagnosedPPO 构造(与 ppo262_config.build_ppo 同参数语义)。"""
    global _DIAG_PPO_CLS
    if _DIAG_PPO_CLS is None:
        _DIAG_PPO_CLS = _build_diagnosed_ppo_cls()
    import torch
    act_fn = {"Tanh": torch.nn.Tanh,
              "ReLU": torch.nn.ReLU}[config["activation_fn"]]
    return _DIAG_PPO_CLS(
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


# ============================================================ 梯度探针
def gradient_probe(model, obs: np.ndarray, actions: np.ndarray,
                   returns: np.ndarray) -> dict[str, Any]:
    """一次性诊断反传:actor/critic 分离梯度 + 第一层逐输入列幅度。

    用一个 mini-batch 的 actor CE / critic MSE 分别反传(不更新参数),
    记录每子网梯度范数与第一层权重逐列平均 |grad|——回答"梯度是否
    到达小尺度特征列"。仅在诊断路径调用,不影响训练动力学。
    """
    import torch
    policy = model.policy
    obs_t = torch.as_tensor(obs, dtype=torch.float32)
    act_t = torch.as_tensor(actions, dtype=torch.long)
    ret_t = torch.as_tensor(returns, dtype=torch.float32)

    def _norm(params):
        return float(torch.sqrt(sum(
            (p.grad.detach() ** 2).sum() for p in params
            if p.grad is not None)))

    out: dict[str, Any] = {}
    # actor
    policy.zero_grad()
    dist = policy.get_distribution(obs_t)
    actor_loss = -dist.log_prob(act_t).mean()
    actor_loss.backward()
    actor_params = (list(policy.mlp_extractor.policy_net.parameters())
                    + list(policy.action_net.parameters()))
    critic_params = (list(policy.mlp_extractor.value_net.parameters())
                     + list(policy.value_net.parameters()))
    out["actor_loss_batch"] = float(actor_loss)
    out["actor_grad_norm"] = _norm(actor_params)
    first = policy.mlp_extractor.policy_net[0]
    if first.weight.grad is not None:
        g = first.weight.grad.detach().abs().mean(dim=0)
        out["actor_first_layer_per_input_abs_grad"] = [
            float(x) for x in g]
    # critic
    policy.zero_grad()
    values = policy.predict_values(obs_t).flatten()
    critic_loss = torch.nn.functional.mse_loss(values, ret_t)
    critic_loss.backward()
    out["critic_loss_batch"] = float(critic_loss)
    out["critic_grad_norm"] = _norm(critic_params)
    policy.zero_grad()
    return out


# ============================================================ obs adapter
class ObsAdapter:
    """feature-wise 仿射适配层 x' = (x - center) / scale(可逆)。

    - identity:Arm A(与 s262_r0/R2 observation 逐位一致);
    - fixed:Arm B 常数在看诊断结果前冻结进 plan,不读任何
      eval corpus,不在 episode 内拟合;
    - fitted:Arm C 只允许 fit 在诊断训练 bank 上,fit 后冻结,
      同一变换应用于训练与 dev;
    - position slot(最后一维)恒不缩放(仓位语义不得改变);
    - 特征顺序不变,变换可逆,dtype float32 保持。
    """

    KINDS = ("identity", "fixed", "fitted")

    def __init__(self, center, scale, *, kind: str, source: str):
        self.center = np.asarray(center, dtype=np.float64)
        self.scale = np.asarray(scale, dtype=np.float64)
        if np.any(self.scale <= 0) or not np.all(np.isfinite(self.scale)):
            raise ValueError("adapter scale 必须为正有限值")
        if len(self.center) != len(self.scale):
            raise ValueError("center/scale 维度不一致")
        if kind not in self.KINDS:
            raise ValueError(f"未知 adapter kind: {kind}")
        self.kind = kind
        self.source = source

    @classmethod
    def identity(cls, dim: int) -> "ObsAdapter":
        return cls(np.zeros(dim), np.ones(dim), kind="identity",
                   source="unscaled(与 s262_r0/R2 逐位一致)")

    @classmethod
    def fixed(cls, center, scale, source: str) -> "ObsAdapter":
        return cls(center, scale, kind="fixed", source=source)

    @classmethod
    def fit_frozen(cls, observations: np.ndarray, *, source: str,
                   eps: float = 1e-9) -> "ObsAdapter":
        """Arm C:只在诊断训练 bank 的 obs 上 fit(mean/std),冻结。"""
        x = np.asarray(observations, dtype=np.float64)
        if x.ndim != 2:
            raise ValueError("fit_frozen 需要 (n, dim) obs 矩阵")
        center = x.mean(axis=0)
        scale = x.std(axis=0)
        # 常数列(std=0,如恒为 0 的暖机特征)不放大:下限保护
        scale = np.where(scale < eps, 1.0, scale)
        # position slot 最后一维不缩放
        center[-1] = 0.0
        scale[-1] = 1.0
        return cls(center, scale, kind="fitted", source=source)

    def apply(self, obs: np.ndarray) -> np.ndarray:
        out = (np.asarray(obs, dtype=np.float64) - self.center) / self.scale
        if not np.all(np.isfinite(out)):
            raise FloatingPointError("adapter 输出含 NaN/Inf")
        return out.astype(np.float32)

    def identity_equivalent(self) -> bool:
        return bool(np.all(self.center == 0.0) and np.all(self.scale == 1.0))

    def describe(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "source": self.source,
            "center": [float(v) for v in self.center],
            "scale": [float(v) for v in self.scale],
        }


def ObsScaleWrapper(env: CurriculumMultiEpisodeEnv, adapter: ObsAdapter):
    """CurriculumMultiEpisodeEnv 的 observation 缩放 Wrapper 工厂。

    返回真正继承 gymnasium.Wrapper 的实例(SB3 的 vec env 包装做
    isinstance 检查):observation 逐 step/reset 经 adapter 变换;
    action/reward/termination/ledger 语义完全不动;attribution info
    原样透传(Repair C 字段不丢失);env 的审计属性(bank/audit/
    episodes_consumed)经 Wrapper 转发可见。
    """
    import gymnasium as gym

    class _Wrapper(gym.Wrapper):
        def __init__(self):
            super().__init__(env)
            self.adapter = adapter

        def reset(self, *, seed=None, options=None):
            obs, info = self.env.reset(seed=seed, options=options)
            return self.adapter.apply(obs), info

        def step(self, action):
            obs, reward, terminated, truncated, info = (
                self.env.step(action))
            return (self.adapter.apply(obs), reward, terminated,
                    truncated, info)

    return _Wrapper()


class ScaledEvalPolicy:
    """评估侧 policy 适配:同一 adapter 应用到评估 obs(与训练同源)。

    reference / baselines 仍在 raw 空间评估(capture 公式语义不变);
    只有被诊断的 PPO 模型经此适配评估。
    """

    def __init__(self, model, adapter: ObsAdapter, name: str):
        self.model = model
        self.adapter = adapter
        self.name = name

    def reset_episode(self) -> None:
        return None

    def act(self, observation) -> int:
        import torch
        obs = self.adapter.apply(
            np.asarray(observation)).reshape(1, -1)
        with torch.no_grad():
            dist = self.model.policy.get_distribution(
                torch.as_tensor(obs))
            action = torch.argmax(dist.distribution.logits, dim=-1)
        return int(action.item())


# ============================================================ 诊断 callback
class DiagnosisCallback:
    """诊断训练逐 step 记录(attribution + cost + latent 对齐)。

    - 每 step 记录 episode attribution(Repair C 字段)、执行动作、
      reward、fee_paid、action target 变化(与真实 ledger trade 分开);
    - terminal step 记录 terminal_liquidation 费用;
    - latent label 由外部注入的 {episode_index -> label 数组} 对齐
      (label 只进日志,不进 observation);
    - episode 完成行与 bank manifest 一一对应(manifest_index 顺序)。
    """

    def __init__(self, env, *, latent_labels: dict[int, np.ndarray] | None,
                 on_episode_done=None, action_change_cost_hint=None):
        from stable_baselines3.common.callbacks import BaseCallback

        outer = self
        self.latent_labels = latent_labels
        self._on_episode_done = on_episode_done

        class _Impl(BaseCallback):
            def __init__(inner):
                super().__init__(verbose=0)
                inner.step_rows: list[dict[str, Any]] = []
                inner.episode_rows: list[dict[str, Any]] = []
                inner._ep = {
                    "rewards": 0.0, "fees": 0.0, "steps": 0,
                    "positions": [], "changes": 0, "liq_fee": 0.0,
                    "trades": 0,
                }

            def _on_step(inner) -> bool:
                for info in inner.locals.get("infos", []):
                    if "episode_index" not in info:
                        continue
                    ep = inner._ep
                    ep["rewards"] += float(info.get("reward_raw", 0.0))
                    ep["fees"] += float(info.get("fee_paid", 0.0))
                    ep["steps"] += 1
                    pos = int(info.get("new_target_position", 0))
                    ep["positions"].append(pos)
                    if (len(ep["positions"]) > 1
                            and ep["positions"][-1]
                            != ep["positions"][-2]):
                        ep["changes"] += 1
                    if info.get("trade_direction") in ("buy", "sell"):
                        ep["trades"] += 1
                    liq = info.get("terminal_liquidation")
                    row = {
                        "env_step": int(inner.num_timesteps),
                        "manifest_index": info.get("manifest_index"),
                        "episode_key": info.get("episode_key", ""),
                        "family": info.get("family"),
                        "rung": info.get("rung"),
                        "pair_index": info.get("pair_index"),
                        "variant": info.get("variant"),
                        "action": int(info.get("action", -1)),
                        "reward_raw": float(info.get("reward_raw", 0.0)),
                        "fee_paid": float(info.get("fee_paid", 0.0)),
                        "terminated": bool(info.get("terminated", False)),
                    }
                    labels = (outer.latent_labels or {}).get(
                        info.get("manifest_index"))
                    if labels is not None and row["env_step"] is not None:
                        t = ep["steps"] - 1
                        if 0 <= t < len(labels):
                            row["latent_label"] = int(labels[t])
                    inner.step_rows.append(row)
                    if info.get("terminated", False):
                        ep["liq_fee"] += float(
                            (liq or {}).get("fee_paid", 0.0))
                        inner.episode_rows.append({
                            "manifest_index": info.get("manifest_index"),
                            "episode_key": info.get("episode_key", ""),
                            "namespace": info.get("namespace"),
                            "family": info.get("family"),
                            "rung": info.get("rung"),
                            "pair_index": info.get("pair_index"),
                            "variant": info.get("variant"),
                            "steps": ep["steps"],
                            "episode_reward_raw": ep["rewards"],
                            "cost_fees_paid": ep["fees"],
                            "terminal_liquidation_fee": ep["liq_fee"],
                            "long_fraction": float(np.mean(ep["positions"])),
                            "position_changes": ep["changes"],
                            "ledger_trades": ep["trades"],
                        })
                        inner._ep = {"rewards": 0.0, "fees": 0.0,
                                     "steps": 0, "positions": [],
                                     "changes": 0, "liq_fee": 0.0,
                                     "trades": 0}
                        if outer._on_episode_done is not None:
                            outer._on_episode_done(
                                env.episodes_consumed, inner.model)
                return True

        self.impl = _Impl()

    def as_callback(self):
        return self.impl


def latent_label_series(loaded, family: str) -> np.ndarray:
    """episode 的 latent label 序列(诊断聚合用;不进 observation)。

    C1: seg_state(2=positive/1=neutral/0=negative)
    C2: cue bar 上的 aligned(+1)/anti(-1)/非 cue(0),按 variant 的
        active gate 合成
    C3: 信号 bar 上 above_cost(+1)/below(0)/非信号(-1 缺省填 0 之外
        用 2 标记非信号)
    """
    h = loaded.episode.hidden
    if family == "c1_opportunity":
        return h["seg_state"].to_numpy().astype(int)
    if family == "c2_context":
        cue = h["cue_dir"].to_numpy()
        gate_dir = h["active_gate_is_dir"].to_numpy()
        ctx = np.where(gate_dir == 1, h["wick_dir_state"].to_numpy(),
                       h["wick_width_state"].to_numpy())
        out = np.zeros(len(cue), dtype=int)
        m = cue != 0
        out[m & (cue * ctx > 0)] = 1     # aligned
        out[m & (cue * ctx < 0)] = -1    # anti-aligned
        return out
    if family == "c3_cost":
        strength = h["sig_strength"].to_numpy()
        above = h["above_cost"].to_numpy()
        out = np.full(len(strength), 2, dtype=int)  # 2 = 非信号 bar
        m = strength != 0.0
        out[m & (above == 1)] = 1
        out[m & (above == 0)] = 0
        return out
    raise ValueError(f"未知 family {family!r}")


# ============================================================ 诊断训练 runner
def diag_train_run(
    bank: list, *, config: dict[str, Any], model_seed: int,
    total_timesteps: int, run_label: str,
    adapter: ObsAdapter | None = None,
    checkpoint_episodes: tuple[int, ...] | None = None,
    checkpoint_saver: Callable[[int, Any], Any] | None = None,
    gradient_probe_every: int = 0,
    gradient_probe_batches: int = 1,
    bc_init_state: dict | None = None,
) -> dict[str, Any]:
    """诊断训练 run(允许重复暴露 bank;显式 cycles 审计)。

    与 official train_run 的差异全部显式化:
    - total_timesteps 允许 = k x bank_steps(k>=1);环境按 manifest
      顺序循环回绕,exhausted_cycles 必须 == k(审计);
    - adapter 非 identity 时 observation 经仿射变换(Ablation Arm B/C);
    - 每 update 的 train/* 指标绑定 rollout index(DiagnosedPPO);
    - 逐 step 诊断(attribution/cost/latent)默认开启;
    - gradient_probe_every > 0 时每 N 个 update 记录一次梯度探针;
    - bc_init_state:BC warm-start 的 policy state_dict(构造后、任何
      训练前载入;仅 actor 子网由调用方保证来源)。
    """
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

    checkpoints: dict[str, Any] = {}

    def _save_checkpoint(n_done: int, model) -> None:
        if checkpoint_episodes is None or checkpoint_saver is None:
            return
        if n_done in checkpoint_episodes:
            tag = f"ep{n_done}"
            if tag not in checkpoints:
                checkpoints[tag] = checkpoint_saver(n_done, model)

    cb = DiagnosisCallback(
        inner_env, latent_labels=latent_labels,
        on_episode_done=_save_checkpoint)
    model = build_diagnosed_ppo(config, model_seed, train_env)
    bc_init_actor_hash = None
    if bc_init_state is not None:
        # load_state_dict 为 in-place copy:optimizer 持有的参数张量
        # 引用不变,无需重建
        model.policy.load_state_dict(bc_init_state)
        bc_init_actor_hash = actor_state_hash(model)
    # 初始化 checkpoint(0 episode:任何 update 前)
    init_state = hashlib.sha256(
        json.dumps([[float(w) for w in p.flatten().tolist()]
                    for p in model.policy.parameters()]
                   ).encode("utf-8")).hexdigest()
    _save_checkpoint(0, model)

    probes: list[dict[str, Any]] = []

    # gradient probe 挂点:用 callback 的 rollout 结束时机取最近 buffer
    from stable_baselines3.common.callbacks import BaseCallback

    class _ProbeCb(BaseCallback):
        def __init__(inner):
            super().__init__(verbose=0)
            inner.rollouts = 0

        def _on_rollout_end(inner) -> None:
            inner.rollouts += 1
            if (gradient_probe_every > 0
                    and inner.rollouts % gradient_probe_every == 0):
                buf = model.rollout_buffer
                obs = np.asarray(buf.observations, dtype=np.float32)
                acts = buf.actions.flatten()
                rets = np.asarray(buf.returns, dtype=np.float32)
                probes.append({
                    "update_index": inner.rollouts,  # train 即将执行
                    "env_step": int(model.num_timesteps),
                    **gradient_probe(model, obs[-287 * gradient_probe_batches:],
                                     acts[-287 * gradient_probe_batches:],
                                     rets[-287 * gradient_probe_batches:]),
                })

        def _on_step(inner) -> bool:
            return True

    t0 = time.time()
    model.learn(total_timesteps=total_timesteps,
                callback=[cb.as_callback(), _ProbeCb()],
                progress_bar=False)
    elapsed = time.time() - t0
    _save_checkpoint(total_timesteps // DECISION_STEPS, model)

    audit = inner_env.audit()
    problems: list[str] = []
    expected_episodes = cycles * len(bank)
    if audit["steps_taken"] != total_timesteps:
        problems.append(f"steps {audit['steps_taken']} != {total_timesteps}")
    if audit["episodes_consumed"] != expected_episodes:
        problems.append(
            f"episodes {audit['episodes_consumed']} != {expected_episodes}"
            f"(cycles={cycles} x {len(bank)})")
    if audit["exhausted_cycles"] != cycles:
        problems.append(
            f"exhausted_cycles {audit['exhausted_cycles']} != {cycles}")
    if audit["duplicate_episode_completions"] != expected_episodes - len(bank):
        # 循环暴露下每个 episode 恰好完成 cycles 次
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
        "update_records": model.diag_update_records,
        "rollout_records": model.diag_rollout_records,
        "gradient_probes": probes,
        "initial_policy_state_sha256": init_state,
        "bc_init_actor_state_sha256": bc_init_actor_hash,
        "checkpoints": checkpoints,
        "model": model,
    }


# ============================================================ BC warm-start
def collect_bc_dataset(bank: list, reference_policy, schema,
                       eval_config) -> dict[str, Any]:
    """从 reference 轨迹收集 (obs, action) 监督数据。

    - obs 是 policy-visible observation(reference 自身轨迹,含其
      position 历史);label 只来自 causal observation reference
      policy 的动作——不读 latent oracle / future return / 元数据;
    - 逐 pair 结构保留(pair 级 train/dev 划分防泄漏)。
    """
    from rl_curriculum.evaluator import run_observation_episode
    xs, ys, meta = [], [], []
    for loaded in bank:
        _, actions, obs_list = run_observation_episode(
            reference_policy, loaded.episode, eval_config, schema,
            return_actions=True, return_observations=True)
        for o, a in zip(obs_list, actions):
            xs.append(np.asarray(o, dtype=np.float32))
            ys.append(int(a))
        meta.append({
            "family": loaded.key.family, "rung": loaded.key.rung,
            "pair_index": int(loaded.key.pair_index),
            "variant": loaded.key.variant,
            "episode_key": loaded.key.canonical(),
        })
    return {
        "X": np.stack(xs), "y": np.asarray(ys, dtype=np.int64),
        "episode_meta": meta,
    }


def bc_train_actor(model, dataset: dict[str, Any], *, epochs: int,
                   lr: float, adapter: ObsAdapter,
                   rng_seed: int) -> dict[str, Any]:
    """actor behavior cloning(冻结 critic;label=reference action)。

    只更新 policy 侧参数(mlp_extractor.policy_net + action_net);
    critic 与 value 路径不动(BC 后 PPO fine-tune 从随机 critic 开始)。
    """
    import torch
    policy = model.policy
    actor_params = (list(policy.mlp_extractor.policy_net.parameters())
                    + list(policy.action_net.parameters()))
    opt = torch.optim.Adam(actor_params, lr=lr)
    X = torch.as_tensor(np.stack(
        [adapter.apply(x) for x in dataset["X"]]), dtype=torch.float32)
    y = torch.as_tensor(dataset["y"], dtype=torch.long)
    gen = torch.Generator().manual_seed(int(rng_seed))
    perm = torch.randperm(len(X), generator=gen)
    history = []
    for epoch in range(epochs):
        opt.zero_grad()
        dist = policy.get_distribution(X)
        loss = torch.nn.functional.cross_entropy(
            dist.distribution.logits, y)
        loss.backward()
        opt.step()
        with torch.no_grad():
            match = float((dist.distribution.logits.argmax(dim=-1)
                           == y).float().mean())
        history.append({"epoch": epoch + 1, "loss": float(loss),
                        "match_rate": match})
    before_hash = None
    return {
        "epochs": epochs, "lr": lr,
        "final_train_match_rate": history[-1]["match_rate"],
        "history": history,
    }


def actor_state_hash(model) -> str:
    """actor 子网参数哈希(BC 前后/导入验证)。"""
    import torch
    policy = model.policy
    parts = [policy.mlp_extractor.policy_net,
             policy.action_net]
    h = hashlib.sha256()
    for mod in parts:
        for p in mod.parameters():
            h.update(np.ascontiguousarray(
                p.detach().numpy(), dtype=np.float32).tobytes())
    return h.hexdigest()
