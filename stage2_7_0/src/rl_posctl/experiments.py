# -*- coding: utf-8 -*-
"""pilot 执行器:训练 env bank、候选运行、评估与记录
(RouteC_PositionControl;R1 改为执行前预约计量 + create-only 目录)。

- EpisodeBankEnv:固定训练域 episode 列表上的确定性轮转(reset
  依序取 bank 项;全部候选/seed 同序 -> 语料顺序配对);补全全部
  版本身份属性(loader 反序列化前比对用);
- run_pilot:预约(ppo_learn_attempts+ppo_steps;单次步数上限在
  预约时校验)→ learn → 实际步数如实结清(超预约 fail closed,
  不再事后计账)→ 无梯度评估 → 落盘;out_dir create-only;
- 经济失败:训练中任一 info.reward_valid=False -> RUN_INVALID,
  保留已产生 checkpoint 与失败现场,不删样本/不重抽;
- 评估:eval_model_on_spec 在**固定 eval bank**上重放(从同一
  固定原件读取/重放不重复算生成;评估步照记 eval_steps)。
  上轮 eval_model 直接 generate_episode 绕过生成配额的路径已移除。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import gymnasium as gym
import numpy as np
import torch as th

from rl_posctl.banks import QuotaLedger, build_bank, domain_seed, \
    episode_seed
from rl_posctl.curriculum import CourseSpec, spec_for, \
    generate_episode
from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize
from rl_posctl.policy import (
    HybridActorCriticPolicy, attach_env_identity, load_posctl_model,
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

    # ---- 版本身份透传(load_posctl_model 反序列化前比对) ----
    @property
    def env_core_version(self):
        return self._inner.env_core_version

    @property
    def observation_spec_version(self):
        return self._inner.observation_spec_version

    @property
    def action_spec_version(self):
        return self._inner.action_spec_version

    @property
    def reward_spec_version(self):
        return self._inner.reward_spec_version

    @property
    def execution_spec_version(self):
        return self._inner.execution_spec_version

    @property
    def ledger_version(self):
        return self._inner.ledger_version


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
    """训练面规格(应用课程档参数 + TRAIN_SPEC_OVERRIDES,事前固定)。"""
    return spec_for(course, seed=master_seed, horizon=64,
                    **profiles.TRAIN_SPEC_OVERRIDES)


def build_train_bank(course: str, master_seed: int, n_episodes: int,
                     quota: QuotaLedger, window: int = 1):
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


def _episode_log(env, last_info):
    """该 episode 的未折扣对数收益(账本口径,非折扣奖励和)。"""
    er = env.episode_reward_raw
    return None if er is None else float(er)


def eval_model_on_spec(model, spec: CourseSpec, eval_bank, window,
                       ledger=None, tag=""):
    """deterministic 模型在**固定 eval bank**上重放(费用=spec.fee)。

    重放固定 bank 不重复算生成(生成已在 bank 构建时计费);
    eval_steps 逐 episode 走预约账本。
    """
    rows = []
    for i, (prices, feats, _) in enumerate(eval_bank):
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
            rid = ledger.reserve(
                f"eval:{tag}:{i}", eval_steps=steps)
            ledger.commit(rid, f"eval:{tag}:{i}", eval_steps=steps)
    return rows


def run_pilot(*, name: str, course: str, window: int,
              policy_kwargs: dict, seed: int, total_steps: int,
              bank, eval_bank, master_seed: int, out_dir: Path,
              ledger, device: str = "cpu"):
    """一次 bounded 运行:预约→训练→结清→评估→落盘(out_dir 唯一)。

    ledger = ReservationLedger(执行前预约);out_dir 由调用方
    create_only_dir 创建(已存在即拒绝)。
    """
    spec = train_course_spec(course, master_seed)
    env = EpisodeBankEnv(bank, fee=spec.fee, window_size=window)
    out_dir = Path(out_dir)
    model = make_posctl_ppo(
        env, policy_kwargs=policy_kwargs, seed=seed,
        n_steps=profiles.ROLLOUT, batch_size=profiles.BATCH,
        n_epochs=profiles.N_EPOCHS, gamma=profiles.GAMMA,
        ent_coef=profiles.ENT_COEF, device=device)
    attach_env_identity(model, env)
    stop = FailureAwareStop()
    rid = ledger.reserve(f"pilot:{name}", ppo_learn_attempts=1,
                         ppo_steps=int(total_steps))
    t0 = time.time()
    try:
        model.learn(total_timesteps=total_steps,
                    callback=stop.cb)
    except BaseException:
        ledger.abandon(rid, f"pilot:{name}",
                       note="learn 异常中断,保守保留预约")
        raise
    elapsed = time.time() - t0
    # SB3 按 rollout 倍数执行;实际步数如实结清(超预约即拒绝)
    actual_steps = int(model.num_timesteps)
    ledger.commit(rid, f"pilot:{name}", ppo_learn_attempts=1,
                  ppo_steps=actual_steps)
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
        rows = eval_model_on_spec(
            model, spec, eval_bank, window,
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
