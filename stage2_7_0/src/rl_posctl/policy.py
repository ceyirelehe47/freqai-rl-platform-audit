# -*- coding: utf-8 -*-
"""混合动作 HOLD/REBALANCE(w) 的真实概率分布与 SB3 PPO 接线
(RouteC_PositionControl W2,HybridAtomBetaPolicy-v1)。

分布结构(全部解析,可手算):
- branch:二元 {HOLD, REBALANCE},softmax(branch_logits[2]);
- target w | REBALANCE:4 分量混合 = 原子 −1/0/+1(精确可选端点与
  精确清仓)+ 对称 Beta(α,α) 经 w=2u−1 的连续分量;
  分量质量 = softmax(mix_logits[4]),α = softplus(raw)+0.05。

执行动作的联合对数概率:
- HOLD:log P(HOLD)。**不乘任何未执行目标的密度**;
- REBALANCE(w=原子):log P(REBAL) + log atom_mass;
- REBALANCE(w∈开区间):log P(REBAL) + log[m_c·beta_pdf((w+1)/2)/2]。

熵(广义,精确):H = H_branch + P(REBAL)·[−Σ_k m_k ln m_k
+ m_c·(H_Beta(α,α) + ln2)],H_Beta 解析。熵对 target 头的梯度
按分布级期望存在(不因 HOLD 样本而为零);似然梯度只流经实际
采样的分支/分量(未用头零似然梯度)。

确定性解码(mode):branch=argmax;REBALANCE 时 w = E[w|REBAL]
= m_{+1} − m_{−1} ∈ [−1,1]。采样与确定性、存档重载共用同一
动作编码器(分支占位 w=0)。

数值边界(事前固定,不得改 tol 救结果):连续样本 u 夹入
[1e-7, 1−1e-7];α 下界 0.05;logsumexp/log_softmax 稳定化;
原子判定 = 与 {−1,0,1} 的精确 float32 相等。
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np
import torch as th
import torch.nn as nn

from stable_baselines3 import PPO
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.torch_layers import MlpExtractor
from rl_posctl.versions import POSCTL_POLICY_SPEC_VERSION


U_EPS = 1e-7
N_DIST_PARAMS = 7          # 2 branch logits + 4 mix logits + 1 alpha raw
ALPHA_FLOOR = 0.05


class HybridAtomBetaDistribution:
    """HOLD/REBALANCE 混合分布(参数即网络输出,逐样本形状 (N,))。"""

    def __init__(self, branch_logits: th.Tensor, mix_logits: th.Tensor,
                 alpha_raw: th.Tensor) -> None:
        branch_logits = branch_logits.reshape(-1, 2)
        mix_logits = mix_logits.reshape(-1, 4)
        alpha_raw = alpha_raw.reshape(-1)
        self.branch_logits = branch_logits
        self.mix_logits = mix_logits
        self.alpha = nn.functional.softplus(alpha_raw) + ALPHA_FLOOR
        self.branch_logp = th.log_softmax(branch_logits, dim=-1)
        self.mix_logp = th.log_softmax(mix_logits, dim=-1)  # (-1,0,+1,cont)

    # ------------------------------------------------------ helpers
    @staticmethod
    def _split_actions(actions: th.Tensor):
        a = actions.reshape(-1, 2).to(th.float64)
        branch = a[:, 0]
        w = a[:, 1]
        return branch, w

    def _beta_logpdf_u(self, u: th.Tensor) -> th.Tensor:
        """log Beta(u; α,α)(u 已夹入 (0,1))。"""
        a = self.alpha
        lnB = torch_lgamma_beta(a)
        return (a - 1.0) * th.log(u) + (a - 1.0) * th.log1p(-u) - lnB

    # ------------------------------------------------------ log-prob
    def log_prob(self, actions: th.Tensor) -> th.Tensor:
        branch, w = self._split_actions(actions)
        is_hold = branch == 0.0
        is_rebal = branch == 1.0
        bad_hold = is_hold & (w != 0.0)
        if bool(bad_hold.any()):
            raise ValueError("HOLD 动作的 w 占位必须为 0(编码错误)")
        if bool((~(is_hold | is_rebal)).any()):
            raise ValueError("动作 branch 必须精确为 0/1")
        hold_lp = self.branch_logp[:, 0]
        rebal_lp = self.branch_logp[:, 1]
        out = th.where(is_hold, hold_lp, rebal_lp)

        # REBALANCE 行的 target 似然
        u = ((w + 1.0) / 2.0).clamp(U_EPS, 1.0 - U_EPS)
        logpdf_w = (self._beta_logpdf_u(u)
                    + math.log(0.5))                     # dw = 2 du
        atom_id = th.where(
            w == -1.0, th.zeros_like(w, dtype=th.int64),
            th.where(w == 0.0, th.ones_like(w, dtype=th.int64),
                     th.where(w == 1.0, 2 * th.ones_like(
                         w, dtype=th.int64),
                         3 * th.ones_like(w, dtype=th.int64))))
        atom_hit = (atom_id < 3) & is_rebal
        mix_lp = self.mix_logp
        idx = th.arange(mix_lp.shape[0], device=mix_lp.device)
        target_atom_lp = mix_lp[idx, atom_id.clamp(max=3)]
        target_cont_lp = mix_lp[:, 3] + logpdf_w
        target_lp = th.where(atom_hit, target_atom_lp, target_cont_lp)
        out = th.where(is_rebal, out + target_lp, out)
        return out.to(th.float32)

    # ------------------------------------------------------ sampling
    def sample(self) -> th.Tensor:
        n = self.branch_logits.shape[0]
        branch = th.bernoulli(
            th.exp(self.branch_logp[:, 1]))              # 1=REBALANCE
        comp = th.multinomial(
            th.exp(self.mix_logp), 1, replacement=True).squeeze(1)
        u = th.distributions.Beta(
            self.alpha, self.alpha).sample()
        u = u.clamp(U_EPS, 1.0 - U_EPS)
        w_cont = 2.0 * u - 1.0
        w_atom = th.tensor(
            [-1.0, 0.0, 1.0, 0.0], device=u.device)[comp]
        w = th.where(comp == 3, w_cont, w_atom)
        w = th.where(branch == 1.0, w, th.zeros_like(w))
        return th.stack([branch, w], dim=1).to(th.float32)

    def mode(self) -> th.Tensor:
        branch = (self.branch_logits.argmax(dim=-1)).to(th.float32)
        m = th.exp(self.mix_logp)
        # E[w | REBAL] = m(+1) − m(−1)(对称 Beta 连续均值 0)
        w_mean = (m[:, 2] - m[:, 0]).clamp(-1.0, 1.0)
        w = th.where(branch == 1.0, w_mean, th.zeros_like(w_mean))
        return th.stack([branch, w], dim=1).to(th.float32)

    def get_actions(self, deterministic: bool = False) -> th.Tensor:
        return self.mode() if deterministic else self.sample()

    # ------------------------------------------------------ entropy
    def entropy(self) -> th.Tensor:
        p = th.exp(self.branch_logp)
        h_branch = -(p * self.branch_logp).sum(-1)
        m = th.exp(self.mix_logp)
        h_mix_disc = -(m * self.mix_logp).sum(-1)
        a = self.alpha
        # H(Beta(a,a)) = lnB − 2(a−1)ψ(a) + (2a−2)ψ(2a)
        lnB = torch_lgamma_beta(a)
        psi_a = th.digamma(a)
        psi_2a = th.digamma(2.0 * a)
        h_beta = lnB - 2.0 * (a - 1.0) * psi_a + (2.0 * a - 2.0) * psi_2a
        h_target = h_mix_disc + m[:, 3] * (h_beta + math.log(2.0))
        return (h_branch + p[:, 1] * h_target).to(th.float32)


def torch_lgamma_beta(a: th.Tensor) -> th.Tensor:
    return 2.0 * th.lgamma(a) - th.lgamma(2.0 * a)


def split_dist_params(raw: th.Tensor):
    """action_net 输出 (N,7) -> (branch_logits, mix_logits, alpha_raw)。"""
    raw = raw.reshape(-1, N_DIST_PARAMS)
    return raw[:, 0:2], raw[:, 2:6], raw[:, 6]


class HybridActorCriticPolicy(ActorCriticPolicy):
    """混合动作 Actor-Critic policy(SB3 2.9 受控子类)。

    只覆写 _build / _get_action_dist_from_latent;其余(特征提取、
    mlp_extractor、value 头、优化器、evaluate_actions、predict)
    全部沿用 SB3 原实现。action_net 输出 7 个分布参数。
    """

    def _build(self, lr_schedule) -> None:
        self._build_mlp_extractor()
        latent_dim_pi = self.mlp_extractor.latent_dim_pi

        self.action_net = nn.Linear(latent_dim_pi, N_DIST_PARAMS)
        self.value_net = nn.Linear(
            self.mlp_extractor.latent_dim_vf, 1)
        # 初始化与 SB3 默认一致(orthogonal policy / constant value)
        module_gains = {
            self.features_extractor: np.sqrt(2),
            self.action_net: 0.01, self.value_net: 1.0}
        for module, gain in module_gains.items():
            module.apply(partial_init_weights(gain))

        self.optimizer = self.optimizer_class(
            self.parameters(), lr=lr_schedule(1),
            **self.optimizer_kwargs)

    def _get_action_dist_from_latent(
            self, latent_pi: th.Tensor) -> HybridAtomBetaDistribution:
        raw = self.action_net(latent_pi)
        b, m, a = split_dist_params(raw)
        return HybridAtomBetaDistribution(b, m, a)


def partial_init_weights(gain: float):
    def _init(module: nn.Module) -> None:
        if isinstance(module, (nn.Linear, nn.Conv2d)):
            nn.init.orthogonal_(module.weight, gain=gain)
            if module.bias is not None:
                nn.init.constant_(module.bias, 0.0)
    return _init


# ============================== PPO 子类与存取 ==============================
POSCTL_HEADER_KEY = "_posctl_policy_header"


def make_posctl_ppo(env, *, policy_kwargs: Optional[dict] = None,
                    learning_rate: float = 3e-4,
                    n_steps: int = 2048, batch_size: int = 256,
                    n_epochs: int = 10, gamma: float = 0.99,
                    seed: int = 0, device: str = "cpu",
                    ent_coef: float = 0.0, **kwargs) -> PPO:
    """构建混合动作 PPO(默认 rollout=2048/batch=256/epochs<=10)。"""
    kw = dict(policy=HybridActorCriticPolicy,
              policy_kwargs=policy_kwargs or {},
              learning_rate=learning_rate, n_steps=n_steps,
              batch_size=batch_size, n_epochs=n_epochs, gamma=gamma,
              seed=seed, device=device, ent_coef=ent_coef)
    kw.update(kwargs)
    model = PPO(env=env, **kw)
    setattr(model, POSCTL_HEADER_KEY, {
        "policy_spec": POSCTL_POLICY_SPEC_VERSION,
        "env_core": getattr(env.unwrapped, "env_core_version", None),
        "observation_spec": getattr(
            env.unwrapped, "observation_spec_version", None),
        "action_spec": getattr(
            env.unwrapped, "action_spec_version", None),
        "n_dist_params": N_DIST_PARAMS,
    })
    return model


def save_posctl_model(model: PPO, path) -> None:
    if not hasattr(model, POSCTL_HEADER_KEY):
        raise RuntimeError("缺少 posctl policy header,拒绝保存")
    model.save(str(path))


def load_posctl_model(path, env) -> PPO:
    """新进程冷读;身份不匹配(含旧二元 PPO 存档)显式拒绝。"""
    import zipfile
    path = str(path)
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"非 SB3 存档,拒绝加载:{path}") from exc
    if "data" not in names:
        raise RuntimeError(f"存档缺少 data,拒绝:{path}")
    import json
    with zipfile.ZipFile(path) as zf:
        data = json.loads(zf.read("data").decode("utf-8"))
    header = data.get(POSCTL_HEADER_KEY)
    if not header:
        raise RuntimeError(
            f"存档缺少 {POSCTL_HEADER_KEY}(旧二元 PPO 或异源"
            f"存档),显式拒绝误载:{path}")
    if header.get("policy_spec") != POSCTL_POLICY_SPEC_VERSION:
        raise RuntimeError(
            f"policy 规格不匹配({header.get('policy_spec')!r}"
            f" != {POSCTL_POLICY_SPEC_VERSION!r}),拒绝:{path}")
    obs_dim_env = int(np.prod(env.observation_space.shape))
    if int(header.get("obs_dim", -1)) != int(obs_dim_env):
        raise RuntimeError(
            f"观察维数不匹配(存档 {header.get('obs_dim')}"
            f" vs 环境 {obs_dim_env}),拒绝误载:{path}")

    model = PPO.load(
        path, env=env, device="cpu",
        custom_objects={
            "policy_class": HybridActorCriticPolicy,
            POSCTL_HEADER_KEY: getattr_local(header)})
    return model


def getattr_local(header):
    return header


def attach_obs_dim(model: PPO, obs_dim: int) -> PPO:
    """保存前记录观察维数(load 侧用于身份比对)。"""
    header = getattr(model, POSCTL_HEADER_KEY)
    header["obs_dim"] = int(obs_dim)
    setattr(model, POSCTL_HEADER_KEY, header)
    return model
