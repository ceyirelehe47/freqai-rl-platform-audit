# -*- coding: utf-8 -*-
"""pilot 执行器:训练 env bank、容量/时序候选运行、评估与记录
(RouteC_PositionControl E5)。

- EpisodeBankEnv:固定训练域 episode 列表上的确定性轮转(reset
  依序取 bank 项;全部候选/seed 同序 -> 语料顺序配对);
- run_pilot:构建 PPO -> learn(总步数精确 = n_iterations × rollout,
  SB3 向上取整如实计入预算) -> 无梯度评估 -> 落盘模型/指标/记录;
- 经济失败:训练中任一 info.reward_valid=False -> RUN_INVALID,
  保留已产生 checkpoint 与失败现场,不重抽;
- 评估:deterministic 策略 vs 参考 vs 基线,同 eval 域同 seed,
  记录每 episode 原始 net_log_return(未折扣)。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import gymnasium as gym
import numpy as np
import pandas as pd
import torch as th

from rl_posctl.banks import QuotaLedger, build_bank, domain_seed, \
    episode_seed
from rl_posctl.curriculum import CourseSpec, baseline_policies, \
    generate_episode, reference_action
from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize
from rl_posctl.policy import (
    HybridActorCriticPolicy, attach_obs_dim, load_posctl_model,
    make_posctl_ppo, save_posctl_model)
from rl_posctl import profiles


class EpisodeBankEnv(gym.Env):
    """固定 episode bank 上的确定性轮转环境(训练用)。

    所有候选与 seed 使用同一 bank 列表与同一访问顺序(语料顺序
    配对);每个 episode 结束自动前进到下一项(环形)。
    """

    metadata = {"render_modes": []}

    def __init__(self, bank, fee: float, window_size: int = 1):
        super().__init__()
        self.bank = bank
        self.idx = -1
        self.fee = fee
        self.window_size = window_size
        self._inner = self._make(bank[0])
        self.observation_space = self._inner.observation_space
        self.action_space = self._inner.action_space

    def _make(self, item) -> HybridPositionEnv:
        prices, feats, _ = item
        return HybridPositionEnv(
            features=feats, prices=prices, fee=self.fee,
            window_size=self.window_size)

    def _sync(self) -> None:
        inner = self._inner
        self.observation_space = inner.observation_space

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.idx = (self.idx + 1) % len(self.bank)
        self._inner = self._make(self.bank[self.idx])
        self._sync()
        return self._inner.reset(seed=seed)

    def step(self, action):
        obs, r, term, trunc, info = self._inner.step(action)
        if term or trunc:
            info = dict(info)
        return obs, r, term, trunc, info

    @property
    def ledger(self):
        return self._inner.ledger

    @property
    def env_core_version(self):
        return self._inner.env_core_version

    @property
    def observation_spec_version(self):
        return self._inner.observation_spec_version

    @property
    def action_spec_version(self):
        return self._inner.action_spec_version


class FailureAwareStop:
    """训练期经济失败监视(SB3 callback;fail 停)。"""

    def __init__(self) -> None:
        from stable_baselines3.common.callbacks import BaseCallback
        outer = self

        class _Cb(BaseCallback):
            def _on_step(self) -> bool:
                infos = self.locals.get("infos") or []
                for info in infos:
                    if info.get("reward_valid") is False:
                        outer.failure = info.get("economic_failure")
                        return False
                return True

        self.cb = _Cb()
        self.failure = None


def train_course_spec(course: str, master_seed: int) -> CourseSpec:
    """训练面规格(含 profiles.TRAIN_SPEC_OVERRIDES,事前固定)。"""
    return CourseSpec(course=course, seed=master_seed,
                      horizon=64,
                      **profiles.TRAIN_SPEC_OVERRIDES)


def build_train_bank(course: str, master_seed: int, n_episodes: int,
                     quota: QuotaLedger, window: int):
    """训练 bank(生成时按结构重试;同结构参数确定性)。"""
    spec = train_course_spec(course, master_seed)
    ds = domain_seed(master_seed, "train")
    bank = []
    made = 0
    while len(bank) < n_episodes:
        quota.record(gen_calls=1, episodes=1, bank=f"posctl_{course}",
                     domain="train")
        made += 1
        try:
            bank.append(generate_episode(spec, episode_seed(ds, made)))
        except RuntimeError:
            continue        # 结构重试(计数已计入,不按 PnL 拒收)
    return bank


def eval_model(model, spec, master_seed, n_episodes, window,
               ledger=None, tag=""):
    """deterministic 模型在 eval 域的未折扣原始收益(逐 episode)。"""
    ds = domain_seed(master_seed, "eval")
    rows = []
    for i in range(n_episodes):
        prices, feats, _ = generate_episode(
            spec, episode_seed(ds, i))
        env = HybridPositionEnv(
            features=feats, prices=prices, fee=spec.fee,
            window_size=window)
        obs, _ = env.reset()
        done = False
        steps = 0
        while not done:
            act, _ = model.predict(obs, deterministic=True)
            obs, r, term, trunc, info = env.step(act)
            steps += 1
            done = term or trunc
        rows.append({
            "episode": i, "steps": steps,
            "net_log_return": _episode_log(env, info),
            "final_equity": info["equity_end"],
            "economic_failure": not info["reward_valid"]})
        if ledger is not None:
            ledger.charge(eval_steps=steps, tag=tag)
    return rows


def _episode_log(env, last_info):
    """该 episode 的未折扣对数收益(账本口径,非折扣奖励和)。"""
    er = env.episode_reward_raw
    return None if er is None else float(er)


def run_pilot(*, name: str, course: str, window: int,
              policy_kwargs: dict, seed: int, total_steps: int,
              bank, master_seed: int, out_dir: Path,
              ledger: profiles.UsageLedger, device: str = "cpu"):
    """一次 pilot 运行:训练 -> 评估 -> 模型/记录落盘。"""
    spec = train_course_spec(course, master_seed)
    env = EpisodeBankEnv(bank, fee=spec.fee, window_size=window)
    model = make_posctl_ppo(
        env, policy_kwargs=policy_kwargs, seed=seed,
        n_steps=profiles.ROLLOUT, batch_size=profiles.BATCH,
        n_epochs=profiles.N_EPOCHS, gamma=profiles.GAMMA,
        ent_coef=profiles.ENT_COEF, device=device)
    attach_obs_dim(model, int(np.prod(
        env.observation_space.shape)))
    stop = FailureAwareStop()
    t0 = time.time()
    model.learn(total_timesteps=total_steps,
                callback=stop.cb)
    elapsed = time.time() - t0
    # SB3 按 rollout 倍数执行;经济失败提前停时按实际步数计费
    actual_steps = int(model.num_timesteps)
    ledger.charge(ppo_steps=actual_steps, tag=f"pilot:{name}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = {
        "name": name, "course": course, "window": window,
        "seed": seed, "device": device,
        "requested_steps": total_steps, "actual_steps": actual_steps,
        "elapsed_s": round(elapsed, 2),
        "status": "RUN_INVALID" if stop.failure else "OK",
        "economic_failure": stop.failure,
    }
    if stop.failure:
        rec["detail"] = "训练中出现非正净值经济失败;按预注册" \
                       "计划停止,不删样本/不重抽"
    else:
        save_posctl_model(model, out_dir / f"{name}.zip")
        rows = eval_model(
            model, spec, master_seed, profiles.EVAL_EPISODES, window,
            ledger=ledger, tag=f"eval:{name}")
        logs = [r["net_log_return"] for r in rows
                if r["net_log_return"] is not None]
        rec.update({
            "eval_mean_net_log_return": float(np.mean(logs))
            if logs else None,
            "eval_n_failures": sum(
                1 for r in rows if r["economic_failure"]),
            "eval_rows_file": f"{name}_eval.json"})
        (out_dir / f"{name}_eval.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1),
            encoding="utf-8")
    (out_dir / f"{name}_record.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1),
        encoding="utf-8")
    return rec


def count_params(model) -> dict:
    """逐参数统计:总可训练/actor/critic/共享(共享不重复计)。"""
    pol = model.policy
    total = sum(p.numel() for p in pol.parameters())
    actor = sum(p.numel() for p in pol.action_net.parameters())
    critic = sum(p.numel() for p in pol.value_net.parameters())
    shared = 0
    fe = sum(p.numel() for p in (
        pol.features_extractor.parameters()))
    mlp = pol.mlp_extractor
    pi_p = sum(p.numel() for p in mlp.policy_net.parameters())
    vf_p = sum(p.numel() for p in mlp.value_net.parameters())
    return {
        "total_trainable": total,
        "actor_head": actor, "critic_head": critic,
        "features_extractor": fe,
        "mlp_pi_branch": pi_p, "mlp_vf_branch": vf_p,
    }
