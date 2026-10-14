# -*- coding: utf-8 -*-
"""PSC_P0_v1 两臂混合分布、公共确定性解码与 P0 PPO 接线/存取。

臂 A(P0SymBetaControl-v1):复用旧 HybridAtomBetaPolicy-v2 对称 Beta
家族数学(α=softplus+1.0,7 参数,ε=2^-25 碰撞界,Q/b0/Z 精确执行映射),
只换 P0 身份与公共解码;旧类零改动。

臂 B(P0AsymBeta-v1):u~Beta(α,β)(α,β>1),w=2u−1;8 参数
(2 branch + 4 mix + α_raw + β_raw)。左右尾质量不同:
  Q_lo = I_ε(α,β),Q_hi = I_ε(β,α)(参数互换,由 I_x(α,β)+I_{1−x}(β,α)=1)
尾质量闭式:log I_x(a,b) = a·ln x − ln a − ln B(a,b) + ln ₂F₁(a,1−b;a+1;x)
,x=ε=2^-25;₂F₁ 按 (a)_k/(a+1)_k = a/(a+k) 截断三项
(t1,t2,t3),α,β∈(1,500] 域内相对误差 <1e−15(独立对照:scipy/torch
betainc 与数值积分;测试 test_psc_p0_policy.py)。梯度=截断式解析导,
有限差分对照。

公共确定性解码 P0CategoryMax-v1(两臂同一函数):
  ①branch=argmax(branch_logits),平局取 HOLD;
  ②HOLD→(0,0.0);
  ③REBALANCE→合并类 [A−,A0,A+,内部] 质量 argmax,平局取低索引;
    原子类输出精确 −1/0/+1;内部类输出家族内部代表值
    (A=0.0 对称中心,与原子 0 值重合如实记录;B=Beta 众数截断代表值)。
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path
from typing import Optional

import numpy as np
import torch as th
import torch.nn as nn
from stable_baselines3 import PPO
from stable_baselines3.common.policies import ActorCriticPolicy

from rl_posctl.policy import (
    EPS_COLL, HALF_CELL_W0, HybridAtomBetaDistribution,
    HybridActorCriticPolicy, N_DIST_PARAMS as OLD_N_DIST_PARAMS,
    _LN2, env_identity, partial_init_weights, split_dist_params,
    rollout_upper_bound)
from rl_posctl.versions import POSCTL_ACCOUNT_FEATURES
from rl_posctl.versions import POSCTL_PSC_P0_TIME_FEATURES as P0_TIME_FEATURES
from rl_posctl.skill_p0.p0spec import (
    ARM_FAMILY, ARMS, BATCH_SIZE, CLIP_RANGE, DECODE_RULE, ENT_COEF, GAMMA,
    GAE_LAMBDA, HIDDEN, LEARNING_RATE, MAX_GRAD_NORM, N_DIST_PARAMS,
    N_EPOCHS, N_STEPS, OBS_SPEC_VERSION, TASK_ID, VF_COEF)

# ---------------------------------------------------------------------------
# 非对称 Beta 尾质量闭式(可微;float64)
# ---------------------------------------------------------------------------
_LN_EPS = math.log(EPS_COLL)


def log_beta_ab(a: th.Tensor, b: th.Tensor) -> th.Tensor:
    """lnB(a,b) = lnΓ(a)+lnΓ(b)−lnΓ(a+b)。强制 float64:网络参数
    为 float32,torch.lgamma 在 float32 下对大参数(如 lnΓ(499)≈
    +2599)ulp 损失 ~1e-4——mpmath 50 位仲裁确认(2026-10-14 修复)。"""
    a = a.to(th.float64)
    b = b.to(th.float64)
    return th.lgamma(a) + th.lgamma(b) - th.lgamma(a + b)


def log_incbeta_eps(a: th.Tensor, b: th.Tensor) -> th.Tensor:
    """log I_ε(a,b),ε=2^-25;₂F₁(a,1−b;a+1;ε) 三项截断闭式。

    项:t_k = [a/(a+k)]·[(1−b)_k 升阶乘/k!]·ε^k,k=1..3。
    float64 全程;α,β∈[1,500] 域内 vs scipy betainc 相对误差
    <1e-12(测试网格覆盖;mpmath 50 位仲裁)。
    """
    a = a.to(th.float64)
    b = b.to(th.float64)
    x = float(EPS_COLL)
    om = 1.0 - b
    t1 = (a / (a + 1.0)) * om * x
    t2 = (a / (a + 2.0)) * (om * (2.0 - b) / 2.0) * x * x
    t3 = (a / (a + 3.0)) * (om * (2.0 - b) * (3.0 - b) / 6.0) * x ** 3
    s = t1 + t2 + t3
    lnB = log_beta_ab(a, b)
    return a * _LN_EPS - th.log(a) - lnB + th.log1p(s)


def log_zero_cell_mass_ab(a: th.Tensor, b: th.Tensor) -> th.Tensor:
    """log b0 = log[2^−(a+b−2)/B(a,b)] + log(2^-150)(fl32 0.0f 单元)。"""
    a = a.to(th.float64)
    b = b.to(th.float64)
    lnB = log_beta_ab(a, b)
    return -(a + b - 2.0) * _LN2 - lnB - 150.0 * _LN2


def asym_interior_representative(alpha: th.Tensor, beta: th.Tensor
                                 ) -> th.Tensor:
    """内部代表值:截断条件众数 w* = 2·clip((α−1)/(α+β−2),ε,1−ε)−1。

    α+β→2 退化(softplus 极负输入被 float64 ulp 吸收 ⇒ α=β=1 精确,
    均匀/无众数)时回退中心 0.5。float32 化后若恰为 0.0f,按
    mode_u−0.5 符号偏移一个最小次正规 float32(±2^-149;取 +)。
    clip 保证永不与 ±1.0f 碰撞。
    """
    a = alpha.to(th.float64)
    b = beta.to(th.float64)
    denom = a + b - 2.0
    safe = th.where(denom > 1e-12, denom, th.ones_like(denom))
    raw_mode = th.where(
        denom > 1e-12, (a - 1.0) / safe,
        th.full_like(a, 0.5))
    mode_u = raw_mode.clamp(float(EPS_COLL), 1.0 - float(EPS_COLL))
    w = 2.0 * mode_u - 1.0
    nudge = th.where(mode_u >= 0.5,
                     th.full_like(w, 2.0 ** -149),
                     th.full_like(w, -(2.0 ** -149)))
    w32 = w.to(th.float32).to(th.float64)
    w = th.where(w32 == 0.0, nudge, w)
    return w


class P0AsymBetaDistribution:
    """HOLD/REBALANCE 混合分布(非对称 Beta 连续体;逐样本 (N,))。

    参数域:α = softplus(α_raw)+1,β 同(float64)。softplus 输出
    < 2^-52 时被 1.0 的 ulp 吸收 ⇒ α 可精确等于 1(域下界);该处
    密度无奇异(α=1 ⇒ u^0 项),log-prob/熵/尾质量闭式全部有效;
    仅内部众数公式退化(见 asym_interior_representative 回退)。
    声称的截断级数精度域:α,β ∈ [1, 500](scipy betainc 对照
    <1e-12;数值求积对照仅在 pdf 平滑(α,β≥1.5)时用于第三路)。
    """

    def __init__(self, branch_logits: th.Tensor, mix_logits: th.Tensor,
                 alpha_raw: th.Tensor, beta_raw: th.Tensor) -> None:
        branch_logits = branch_logits.reshape(-1, 2)
        mix_logits = mix_logits.reshape(-1, 4)
        alpha_raw = alpha_raw.reshape(-1)
        beta_raw = beta_raw.reshape(-1)
        self.branch_logits = branch_logits
        self.mix_logits = mix_logits
        self.alpha = nn.functional.softplus(alpha_raw) + 1.0   # ≥1
        self.beta = nn.functional.softplus(beta_raw) + 1.0     # ≥1
        self.branch_logp = th.log_softmax(branch_logits, dim=-1)
        self.mix_logp = th.log_softmax(mix_logits, dim=-1)  # (-1,0,+1,cont)
        self.log_Qlo = log_incbeta_eps(self.alpha, self.beta)
        self.log_Qhi = log_incbeta_eps(self.beta, self.alpha)
        self.Qlo = th.exp(self.log_Qlo)
        self.Qhi = th.exp(self.log_Qhi)
        self.log_b0 = log_zero_cell_mass_ab(self.alpha, self.beta)
        self.b0 = th.exp(self.log_b0)
        self.Z = (1.0 - self.Qlo - self.Qhi - self.b0).to(
            th.float64).clamp(min=1e-12)

    # ------------------------------------------------------ helpers
    @staticmethod
    def _split_actions(actions: th.Tensor):
        a = actions.reshape(-1, 2).to(th.float64)
        return a[:, 0], a[:, 1]

    def _beta_logpdf_u(self, u: th.Tensor) -> th.Tensor:
        a = self.alpha.to(th.float64)
        b = self.beta.to(th.float64)
        return ((a - 1.0) * th.log(u) + (b - 1.0) * th.log1p(-u)
                - log_beta_ab(a, b))

    def merged_atom_logp(self) -> th.Tensor:
        """(N,3):执行值 ∈ {−1,0,+1} 合并原子质量(左右尾不同)。"""
        m_lp = self.mix_logp.to(th.float64)
        cont = m_lp[:, 3]
        return th.stack([
            th.logaddexp(m_lp[:, 0], cont + self.log_Qlo),
            th.logaddexp(m_lp[:, 1], cont + self.log_b0),
            th.logaddexp(m_lp[:, 2], cont + self.log_Qhi)], dim=1)

    def interior_log_mass(self) -> th.Tensor:
        """log(m3·Z)。"""
        return self.mix_logp.to(th.float64)[:, 3] + th.log(self.Z)

    def interior_representative(self) -> th.Tensor:
        return asym_interior_representative(self.alpha, self.beta)

    # ------------------------------------------------------ log-prob
    def log_prob(self, actions: th.Tensor) -> th.Tensor:
        branch, w = self._split_actions(actions)
        is_hold = branch == 0.0
        is_rebal = branch == 1.0
        if bool((is_hold & (w != 0.0)).any()):
            raise ValueError("HOLD 动作的 w 占位必须为 0(编码错误)")
        if bool((~(is_hold | is_rebal)).any()):
            raise ValueError("动作 branch 必须精确为 0/1")
        out = th.where(is_hold, self.branch_logp[:, 0].to(th.float64),
                       self.branch_logp[:, 1].to(th.float64))
        atom_id = th.where(
            w == -1.0, th.zeros_like(w, dtype=th.int64),
            th.where(w == 0.0, th.ones_like(w, dtype=th.int64),
                     th.where(w == 1.0, 2 * th.ones_like(
                         w, dtype=th.int64),
                         3 * th.ones_like(w, dtype=th.int64))))
        atom_hit = (atom_id < 3) & is_rebal
        merged = self.merged_atom_logp()
        idx = th.arange(merged.shape[0], device=merged.device)
        target_atom_lp = merged[idx, atom_id.clamp(max=2)]
        interior_hit = (w > -1.0) & (w < 1.0) & (w != 0.0) & is_rebal
        u = (w + 1.0) / 2.0
        u_safe = u.clamp(float(EPS_COLL), 1.0 - float(EPS_COLL))
        target_cont_lp = (self.mix_logp.to(th.float64)[:, 3]
                          + self._beta_logpdf_u(u_safe) - _LN2)
        target_lp = th.where(atom_hit, target_atom_lp, target_cont_lp)
        if bool((is_rebal & ~atom_hit & ~interior_hit).any()):
            raise ValueError(
                "REBALANCE 目标落在支撑之外且不是精确原子"
                "(必须为 {−1,0,1} 或 (−1,1) 内 float32 值)")
        out = th.where(is_rebal, out + target_lp, out)
        return out.to(th.float32)

    # ------------------------------------------------------ sampling
    def sample(self) -> th.Tensor:
        branch = th.bernoulli(th.exp(self.branch_logp[:, 1]))
        comp = th.multinomial(
            th.exp(self.mix_logp), 1, replacement=True).squeeze(1)
        a64 = self.alpha.to(th.float64)
        b64 = self.beta.to(th.float64)
        u = th.distributions.Beta(a64, b64).sample()
        w_cont = 2.0 * u - 1.0
        w_cont = th.where(u <= float(EPS_COLL), -1.0, w_cont)
        w_cont = th.where(u >= 1.0 - float(EPS_COLL), 1.0, w_cont)
        w_atom = th.tensor(
            [-1.0, 0.0, 1.0, 0.0], device=u.device,
            dtype=th.float64)[comp.to(u.device)]
        w = th.where(comp.to(u.device) == 3, w_cont, w_atom)
        w = th.where(branch.to(u.device) == 1.0, w, th.zeros_like(w))
        return th.stack(
            [branch.to(u.device).to(th.float64), w], dim=1).to(th.float32)

    def mode(self) -> th.Tensor:
        return p0_category_decode(
            self.branch_logits, self.merged_atom_logp(),
            self.interior_log_mass(), self.interior_representative())

    def get_actions(self, deterministic: bool = False) -> th.Tensor:
        return self.mode() if deterministic else self.sample()

    # ------------------------------------------------------ entropy
    def entropy(self) -> th.Tensor:
        p = th.exp(self.branch_logp).to(th.float64)
        h_branch = -(p * self.branch_logp.to(th.float64)).sum(-1)
        m = th.exp(self.mix_logp.to(th.float64))
        m3 = m[:, 3]
        a = self.alpha.to(th.float64)
        b = self.beta.to(th.float64)
        A_minus = m[:, 0] + m3 * self.Qlo
        A_zero = m[:, 1] + m3 * self.b0
        A_plus = m[:, 2] + m3 * self.Qhi
        interior = m3 * self.Z
        probs = th.stack(
            [A_minus, A_zero, A_plus, interior], dim=1).clamp(min=1e-300)
        h_disc = -(probs * probs.log()).sum(-1)
        lnB = log_beta_ab(a, b)
        h_beta = (lnB - (a - 1.0) * th.digamma(a)
                  - (b - 1.0) * th.digamma(b)
                  + (a + b - 2.0) * th.digamma(a + b))
        h_target = h_disc + interior * (h_beta + th.log(2.0 * self.Z))
        return (h_branch + p[:, 1] * h_target).to(th.float32)


# ---------------------------------------------------------------------------
# 公共确定性解码(P0CategoryMax-v1;两臂同一函数)
# ---------------------------------------------------------------------------
_ATOM_W = (-1.0, 0.0, 1.0)


def _argmax_lowest(logits_or_masses: th.Tensor) -> th.Tensor:
    """逐行 argmax,平局确定取最低索引(torch.argmax 平局序不保证)。"""
    m = logits_or_masses.to(th.float64)
    mx = m.max(dim=-1, keepdim=True).values
    is_max = m == mx
    n_cat = m.shape[-1]
    idx = th.arange(n_cat, device=m.device,
                    dtype=th.float64).expand_as(m)
    big = th.full_like(m, float(n_cat * 10))
    return th.where(is_max, idx, big).min(dim=-1).values.to(th.int64)


def p0_category_decode(branch_logits: th.Tensor, atom_logp: th.Tensor,
                       interior_log: th.Tensor,
                       interior_rep: th.Tensor) -> th.Tensor:
    """类别式确定性解码。branch 平局取 HOLD;REBALANCE 四类
    [A−,A0,A+,内部] 质量平局取低索引;原子输出精确值;内部输出
    家族代表值。输入 (N,·) float;输出 (N,2) float32。"""
    b64 = branch_logits.reshape(-1, 2).to(th.float64)
    atom = atom_logp.reshape(-1, 3).to(th.float64)
    interior = interior_log.reshape(-1, 1).to(th.float64)
    rep = interior_rep.reshape(-1).to(th.float64)
    branch = _argmax_lowest(b64)                       # 平局->0(HOLD)
    masses = th.cat([atom, interior], dim=1)           # (N,4)
    cat_idx = _argmax_lowest(masses)                   # 平局->低索引
    atom_w = th.tensor(_ATOM_W, device=masses.device,
                       dtype=th.float64)[cat_idx.clamp(max=2)]
    w = th.where(cat_idx == 3, rep, atom_w)
    w = th.where(branch == 1, w, th.zeros_like(w))
    return th.stack([branch.to(th.float64), w], dim=1).to(th.float32)


class P0DistView:
    """家族分布的 P0 视图:sample/log_prob/entropy 透传(语义不变),
    deterministic 统一走 P0CategoryMax-v1(旧 mean/质量差解码不用于
    P0 主评分,可另作只读诊断)。"""

    def __init__(self, dist, arm: str) -> None:
        if arm not in ARMS:
            raise ValueError(f"未知 P0 臂 {arm!r}")
        self.dist = dist
        self.arm = arm

    def sample(self) -> th.Tensor:
        return self.dist.sample()

    def log_prob(self, actions: th.Tensor) -> th.Tensor:
        return self.dist.log_prob(actions)

    def entropy(self) -> th.Tensor:
        return self.dist.entropy()

    def mode(self) -> th.Tensor:
        d = self.dist
        if self.arm == "A":
            atom_lp = d._merged_atom_logp()            # noqa: SLF001 只读复用
            interior_log = (d.mix_logp.to(th.float64)[:, 3]
                            + th.log(d.Z))
            rep = th.zeros_like(d.alpha, dtype=th.float64)
        else:
            atom_lp = d.merged_atom_logp()
            interior_log = d.interior_log_mass()
            rep = d.interior_representative()
        return p0_category_decode(d.branch_logits, atom_lp,
                                  interior_log, rep)

    def get_actions(self, deterministic: bool = False) -> th.Tensor:
        return self.mode() if deterministic else self.sample()


# ---------------------------------------------------------------------------
# P0 policy 与 PPO 构建
# ---------------------------------------------------------------------------
class P0ActorCriticPolicy(HybridActorCriticPolicy):
    """P0 双臂 Actor-Critic(arm 经 policy_kwargs 传入;重建时由存档
    policy_kwargs 自动携带)。_build 保持 mlp_extractor 先于头构建,
    同 seed 两臂公共 trunk 初始权重逐位一致(头部宽度差如实列)。"""

    def __init__(self, observation_space, action_space, lr_schedule,
                 arm: str = "B", **kwargs):
        if arm not in ARMS:
            raise ValueError(f"未知 P0 臂 {arm!r}")
        self.p0_arm = arm
        super().__init__(observation_space, action_space,
                         lr_schedule, **kwargs)

    def _build(self, lr_schedule) -> None:
        self._build_mlp_extractor()
        latent_dim_pi = self.mlp_extractor.latent_dim_pi
        self.action_net = nn.Linear(
            latent_dim_pi, N_DIST_PARAMS[self.p0_arm])
        self.value_net = nn.Linear(
            self.mlp_extractor.latent_dim_vf, 1)
        module_gains = {
            self.features_extractor: np.sqrt(2),
            self.action_net: 0.01, self.value_net: 1.0}
        for module, gain in module_gains.items():
            module.apply(partial_init_weights(gain))
        self.optimizer = self.optimizer_class(
            self.parameters(), lr=lr_schedule(1),
            **self.optimizer_kwargs)

    def _get_action_dist_from_latent(self, latent_pi: th.Tensor):
        raw = self.action_net(latent_pi)
        if self.p0_arm == "A":
            b, m, a = split_dist_params(raw)
            return P0DistView(
                HybridAtomBetaDistribution(b, m, a), "A")
        raw = raw.reshape(-1, N_DIST_PARAMS["B"])
        return P0DistView(P0AsymBetaDistribution(
            raw[:, 0:2], raw[:, 2:6], raw[:, 6], raw[:, 7]), "B")


# ---------------------------------------------------------------------------
# P0 header / 存取(旧 12 字段 + P0 扩展;任何不匹配在权重反序列化前拒)
# ---------------------------------------------------------------------------
P0_HEADER_KEY = "_psc_p0_header"
P0_BASE_FIELDS = (
    "policy_spec", "env_core", "observation_spec", "action_spec",
    "reward_spec", "execution_spec", "ledger", "n_dist_params",
    "obs_dim", "account_features", "action_space_lo", "action_space_hi")
P0_EXTRA_FIELDS = (
    "arm", "decode_rule", "gamma", "task_id", "bank_ref",
    "hyperparams_digest", "horizon", "code_digest")
P0_HEADER_FIELDS = P0_BASE_FIELDS + P0_EXTRA_FIELDS


def p0_hyperparams(*, n_steps: int = N_STEPS,
                   batch_size: int = BATCH_SIZE,
                   n_epochs: int = N_EPOCHS) -> dict:
    """超参身份字典。batch_size/n_epochs 仅 R1 工程 smoke(engsmoke)
    覆盖;默认实参与旧 P0 逐字节相同(旧存档摘要不变)。"""
    return {
        "hidden": list(HIDDEN), "n_steps": int(n_steps),
        "batch_size": int(batch_size), "n_epochs": int(n_epochs),
        "learning_rate": LEARNING_RATE, "gamma": GAMMA,
        "gae_lambda": GAE_LAMBDA, "clip_range": CLIP_RANGE,
        "vf_coef": VF_COEF, "max_grad_norm": MAX_GRAD_NORM,
        "ent_coef": ENT_COEF,
    }


def p0_hyperparams_digest(*, n_steps: int = N_STEPS,
                          batch_size: int = BATCH_SIZE,
                          n_epochs: int = N_EPOCHS) -> str:
    blob = json.dumps(p0_hyperparams(n_steps=n_steps,
                                     batch_size=batch_size,
                                     n_epochs=n_epochs),
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def p0_code_digest() -> str:
    """P0 模块源码身份(p0spec/p0policy/p0env 文件字节)。"""
    import rl_posctl.skill_p0.p0env as _p0env
    h = hashlib.sha256()
    for mod in (__import__(__name__, fromlist=[""]), _p0env):
        with open(mod.__file__, "rb") as fh:   # noqa: SIM115
            h.update(fh.read())
    return h.hexdigest()


def _p0_obs_feature_names() -> list:
    return list(POSCTL_ACCOUNT_FEATURES) + list(P0_TIME_FEATURES)


def make_p0_ppo(env, *, arm: str, seed: int, bank_ref: str,
                horizon: int, n_steps: int = N_STEPS,
                learning_rate: float = LEARNING_RATE,
                batch_size: int | None = None,
                n_epochs: int | None = None) -> PPO:
    """构建 P0 PPO(超参冻结于 p0spec;bank_ref/horizon 绑定数据身份)。

    batch_size/n_epochs 显式覆盖仅限 R1 工程 smoke(ENGINEERING_ONLY,
    见 psc_p0_train --kind engsmoke);不传 = 旧 P0 冻结几何逐字节不变。
    """
    if arm not in ARMS:
        raise ValueError(f"未知 P0 臂 {arm!r}")
    bs = BATCH_SIZE if batch_size is None else int(batch_size)
    ep = N_EPOCHS if n_epochs is None else int(n_epochs)
    model = PPO(
        env=env, policy=P0ActorCriticPolicy,
        policy_kwargs={"arm": arm,
                       "net_arch": {"pi": list(HIDDEN),
                                    "vf": list(HIDDEN)},
                       "activation_fn": nn.Tanh},
        learning_rate=learning_rate, n_steps=n_steps,
        batch_size=bs, n_epochs=ep, gamma=GAMMA,
        gae_lambda=GAE_LAMBDA, clip_range=CLIP_RANGE,
        vf_coef=VF_COEF, max_grad_norm=MAX_GRAD_NORM,
        ent_coef=ENT_COEF, seed=seed, device="cpu")
    header = _p0_expected_identity(
        env, arm=arm, bank_ref=bank_ref, horizon=horizon,
        n_steps=n_steps, batch_size=bs, n_epochs=ep)
    setattr(model, P0_HEADER_KEY, header)
    return model


def _p0_expected_identity(env, *, arm: str, bank_ref: str,
                          horizon: int, n_steps: int = N_STEPS,
                          batch_size: int = BATCH_SIZE,
                          n_epochs: int = N_EPOCHS) -> dict:
    env_id = env_identity(env)
    header = dict(env_id)
    header.update({
        "policy_spec": ARM_FAMILY[arm],
        "n_dist_params": N_DIST_PARAMS[arm],
        "account_features": _p0_obs_feature_names(),
        "action_space_lo": [float(x) for x in
                            env.action_space.low.tolist()],
        "action_space_hi": [float(x) for x in
                            env.action_space.high.tolist()],
        "arm": arm,
        "decode_rule": DECODE_RULE,
        "gamma": GAMMA,
        "task_id": TASK_ID,
        "bank_ref": str(bank_ref),
        "hyperparams_digest": p0_hyperparams_digest(
            n_steps=n_steps, batch_size=batch_size,
            n_epochs=n_epochs),
        "horizon": int(horizon),
        "code_digest": p0_code_digest(),
    })
    return header


def save_p0_model(model: PPO, path) -> None:
    header = getattr(model, P0_HEADER_KEY, None)
    if not header:
        raise RuntimeError("缺少 P0 header,拒绝保存")
    missing = [k for k in P0_HEADER_FIELDS if k not in header]
    if missing:
        raise RuntimeError(f"P0 header 缺字段 {missing},拒绝保存")
    model.save(str(path))


def _read_p0_header(path) -> dict:
    import zipfile
    path = str(path)
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"非 SB3 存档,拒绝加载:{path}") from exc
    if "data" not in names:
        raise RuntimeError(f"存档缺少 data,拒绝:{path}")
    with zipfile.ZipFile(path) as zf:
        data = json.loads(zf.read("data").decode("utf-8"))
    header = data.get(P0_HEADER_KEY)
    if not header:
        raise RuntimeError(
            f"存档缺少 {P0_HEADER_KEY}(旧 posctl/异源存档),"
            f"显式拒绝误载:{path}")
    return header, data


def load_p0_model(path, env, *, arm: str, bank_ref: str,
                  horizon: int, n_steps: int = N_STEPS,
                  batch_size: int | None = None,
                  n_epochs: int | None = None) -> PPO:
    """新进程冷读;旧档/A-B 互载/错观察/错解码/错 gamma 在任何权重
    反序列化之前逐项拒绝。bank_ref/n_steps 允许按用途放宽为 None
    (检查点评估用训练同值)。batch_size/n_epochs 仅工程 smoke
    几何覆盖(与训练时传值一致)。"""
    header, _ = _read_p0_header(path)
    want = _p0_expected_identity(
        env, arm=arm, bank_ref=bank_ref, horizon=horizon,
        n_steps=n_steps,
        batch_size=(BATCH_SIZE if batch_size is None
                    else int(batch_size)),
        n_epochs=(N_EPOCHS if n_epochs is None else int(n_epochs)))
    if bank_ref is None:
        want.pop("bank_ref")
    problems = []
    for key in P0_HEADER_FIELDS:
        if key not in want:
            continue
        got = header.get(key, None)
        if got != want[key]:
            problems.append(f"{key}: 存档 {got!r} != 期望 {want[key]!r}")
    if problems:
        raise RuntimeError(
            "P0 存档身份不匹配,拒绝误载:\n  "
            + "\n  ".join(problems) + f"\n  path={path}")
    return PPO.load(
        path, env=env, device="cpu",
        custom_objects={
            "policy_class": P0ActorCriticPolicy,
            P0_HEADER_KEY: dict(header)})


def load_p0_model_archive(path, *, arm: str):
    """只读冷载(不带 env;不用于新训练)。要求 P0 header 完整且
    家族/参数数与请求臂一致。"""
    header, _ = _read_p0_header(path)
    missing = [k for k in P0_HEADER_FIELDS if k not in header]
    if missing:
        raise RuntimeError(f"P0 header 缺字段 {missing}:{path}")
    if header.get("arm") != arm or (
            header.get("policy_spec") != ARM_FAMILY[arm]) or (
            int(header.get("n_dist_params", -1))
            != N_DIST_PARAMS[arm]):
        raise RuntimeError(
            f"存档臂身份 {header.get('arm')!r}/"
            f"{header.get('policy_spec')!r} != 请求 {arm!r},拒绝")
    return PPO.load(
        path, env=None, device="cpu",
        custom_objects={
            "policy_class": P0ActorCriticPolicy,
            P0_HEADER_KEY: dict(header)}), dict(header)


# ---------------------------------------------------------------------------
# 初始化对拍与 optimizer 计数
# ---------------------------------------------------------------------------
def _tensor_digest(t: th.Tensor) -> str:
    return hashlib.sha256(
        t.detach().to(th.float64).cpu().numpy().tobytes()
    ).hexdigest()


def trunk_digest(model: PPO) -> dict:
    """公共 trunk(mlp_extractor,两臂同构部分)逐参数摘要。"""
    pol = model.policy
    parts = []
    for name, p in sorted(pol.mlp_extractor.state_dict().items()):
        parts.append(f"{name}:{_tensor_digest(p)}")
    return {"mlp_extractor": hashlib.sha256(
        "|".join(parts).encode("utf-8")).hexdigest(),
        "n_items": len(parts)}


def wrap_optimizer_counter(model: PPO) -> dict:
    """包 model.policy.optimizer.step 计数(真实 optimizer.step 计量)。"""
    opt = model.policy.optimizer
    box = {"n": 0}
    orig_step = opt.step

    def _counted(*args, **kwargs):
        box["n"] += 1
        return orig_step(*args, **kwargs)

    opt.step = _counted
    return box


# ---------------------------------------------------------------------------
# 检查点阶段元数据(FiniteRepair R1 / F1:采集→更新→保存次序绑定)
# ---------------------------------------------------------------------------
P0_STAGE_KEY = "_psc_p0_stage"
P0_STAGE_FIELDS = (
    "stage", "target_step", "num_timesteps", "optimizer_steps",
    "policy_digest", "optimizer_digest", "run_name", "code_digest",
    "saved_utc")
P0_STAGES = ("initial", "mid", "final")


def policy_digest(model: PPO) -> str:
    """整个 policy(state_dict 全参数/缓冲)的确定性摘要。"""
    sd = model.policy.state_dict()
    parts = [f"{k}:{_tensor_digest(v)}"
             for k, v in sorted(sd.items())]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _optimizer_state_dict_digest(sd: dict) -> str:
    """optimizer state_dict 确定性摘要(对存档 th.load 后的纯字典
    同样可复算;R2/C1:优化器证据实际核对,不只携带声明字符串)。"""
    parts = []
    for k, v in sorted(sd.items()):
        if isinstance(v, dict):
            for kk, vv in sorted(v.items()):
                parts.append(f"{k}.{kk}:{_tensor_digest(vv)}"
                             if hasattr(vv, "detach")
                             else f"{k}.{kk}:{vv!r}")
        elif hasattr(v, "detach"):
            parts.append(f"{k}:{_tensor_digest(v)}")
        else:
            parts.append(f"{k}:{v!r}")
    return hashlib.sha256("|".join(parts).encode(
        "utf-8")).hexdigest()


def optimizer_state_digest(model: PPO) -> str:
    """policy optimizer state_dict 摘要(含 Adam 步计数张量;
    未更新前 state 为空 → 空态摘要,与已更新状态可区分)。"""
    return _optimizer_state_dict_digest(
        model.policy.optimizer.state_dict())


def save_p0_model_staged(model: PPO, path, *, stage: str,
                         target_step: int, optimizer_steps: int,
                         run_name: str) -> dict:
    """带阶段元数据的 P0 保存(create-only;R1/F1)。

    - stage ∈ initial/mid/final;mid/final 只允许在对应更新完成后
      由 CheckpointLifecycle 调用(采集计数/已完成优化计数不混用);
    - 同名已存在 → 显式拒绝(不静默跳过、不覆盖旧文件);
    - 元数据随 data JSON 落盘(_psc_p0_stage),与权重/optimizer
      状态同一存档原子绑定。
    """
    if stage not in P0_STAGES:
        raise ValueError(f"未知 stage {stage!r}")
    p = Path(path)
    if p.exists():
        raise RuntimeError(
            f"检查点已存在,拒绝覆盖(create-only):{p}"
            "(final 保存不得因同名旧文件静默跳过)")
    meta = {
        "stage": stage,
        "target_step": int(target_step),
        "num_timesteps": int(model.num_timesteps),
        "optimizer_steps": int(optimizer_steps),
        "policy_digest": policy_digest(model),
        "optimizer_digest": optimizer_state_digest(model),
        "run_name": str(run_name),
        "code_digest": p0_code_digest(),
        "saved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime()),
    }
    setattr(model, P0_STAGE_KEY, meta)
    try:
        save_p0_model(model, p)
    finally:
        pass
    return meta


def read_p0_stage(path) -> dict:
    """读存档阶段元数据;缺失(旧格式/无阶段绑定)显式拒绝。"""
    _, data = _read_p0_header(path)
    stage = data.get(P0_STAGE_KEY)
    if not isinstance(stage, dict):
        raise RuntimeError(
            f"存档缺少 {P0_STAGE_KEY}(旧格式检查点,更新阶段未绑定,"
            f"拒绝消费):{path}")
    missing = [k for k in P0_STAGE_FIELDS if k not in stage]
    if missing:
        raise RuntimeError(
            f"阶段元数据缺字段 {missing}:{path}")
    return dict(stage)


def inspect_p0_archive(path) -> dict:
    """只读冷检(不动 torch 随机流;weights_only 安全加载)。

    返回 header/stage/policy_digest/adam_steps/optimizer_digest
    (优化器状态内的 Adam step 计数与完整 state_dict 摘要均从
    存档复算;state 为空 = 0/空态摘要)。这是确认入口与复核方的
    独立核验来源,不信文件名与日志。
    """
    import io
    import zipfile
    header, _ = _read_p0_header(path)
    stage = read_p0_stage(path)
    with zipfile.ZipFile(str(path)) as zf:
        pol = th.load(io.BytesIO(zf.read("policy.pth")),
                      map_location="cpu", weights_only=True)
        parts = [f"{k}:{_tensor_digest(v)}"
                 for k, v in sorted(pol.items())]
        pdig = hashlib.sha256("|".join(parts).encode(
            "utf-8")).hexdigest()
        try:
            opt = th.load(io.BytesIO(zf.read("policy.optimizer.pth")),
                          map_location="cpu", weights_only=True)
        except KeyError:
            opt = None
    adam_steps = 0
    if opt:
        states = opt.get("state") or {}
        for v in states.values():
            step = v.get("step") if isinstance(v, dict) else None
            if step is None:
                continue
            adam_steps = max(adam_steps, int(
                step.item() if hasattr(step, "item") else step))
    odig = _optimizer_state_dict_digest(opt) if opt is not None else None
    return {"header": header, "stage": stage,
            "policy_digest": pdig, "adam_steps": int(adam_steps),
            "optimizer_digest": odig}


def verify_final_checkpoint(path, run_record: dict) -> dict:
    """确认入口前置核验(任何资源消费之前;R1/F1 + R2/C1)。

    自洽层核验(档↔record 互证,工程 smoke 几何按自身 record 核):
    拒绝无阶段元数据(旧 pre-update 档)、stage≠final、status≠OK、
    num_timesteps/optimizer_steps/run_name/code_digest 与 record 不符、
    run_name/code_digest/bank_ref/arm 身份错配、存档 Adam 步≠阶段
    声明、policy 摘要≠阶段声明、**复算 optimizer 摘要≠阶段声明**
    (R2/C1:优化器证据实际核对,声明全零/串改一律拒绝)。
    缺 record 字段时该项跳过(宽松面仅限本层;主实验槽位绑定由
    verify_final_checkpoint_for_slot 强制必需字段)。
    """
    info = inspect_p0_archive(path)
    stage = info["stage"]
    problems = []
    if stage["stage"] != "final":
        problems.append(
            f"stage={stage['stage']!r} != 'final'(pre-update 中间档"
            "不得当最终模型消费)")
    if run_record.get("status") != "OK":
        problems.append(
            f"run status={run_record.get('status')!r} != 'OK'")
    for skey, rkey in (("num_timesteps", "actual_steps"),
                       ("optimizer_steps", "optimizer_steps"),
                       ("run_name", "run_name"),
                       ("code_digest", "code_digest")):
        want = run_record.get(rkey)
        got = stage.get(skey)
        if want is not None and got != want:
            problems.append(
                f"stage.{skey}={got!r} != run_record.{rkey}={want!r}")
    if stage.get("code_digest") != info["header"].get("code_digest"):
        problems.append("stage/header code_digest 不一致")
    if run_record.get("bank_ref") is not None and (
            info["header"].get("bank_ref")
            != run_record["bank_ref"]):
        problems.append("header.bank_ref != run_record.bank_ref")
    if run_record.get("arm") is not None and (
            info["header"].get("arm") != run_record["arm"]):
        problems.append("header.arm != run_record.arm")
    if info["adam_steps"] != int(stage["optimizer_steps"]):
        problems.append(
            f"存档 Adam 步 {info['adam_steps']} != 阶段声明 "
            f"{stage['optimizer_steps']}(保存时点与声明不符)")
    if info["policy_digest"] != stage["policy_digest"]:
        problems.append("存档 policy 摘要 != 阶段声明摘要")
    if (info["optimizer_digest"] is None
            or info["optimizer_digest"]
            != stage["optimizer_digest"]):
        problems.append(
            "存档复算 optimizer 摘要 != 阶段声明 optimizer_digest"
            "(优化器证据不实或缺失;R2/C1)")
    if problems:
        raise RuntimeError(
            "最终检查点核验失败,确认入口拒绝(未消费任何资源):\n  "
            + "\n  ".join(problems) + f"\n  path={path}")
    return {"path": str(path), "stage": stage,
            "header": dict(info["header"]),
            "policy_digest": info["policy_digest"],
            "optimizer_digest": info["optimizer_digest"],
            "adam_steps": info["adam_steps"],
            "sha256": hashlib.sha256(
                Path(path).read_bytes()).hexdigest()}


# ---------------------------------------------------------------------------
# 主实验槽位期望(R2/C1:用途/身份/几何绑定,期望独立于 record 自述)
# ---------------------------------------------------------------------------
MAIN_RECORD_REQUIRED_FIELDS = (
    "status", "run_name", "arm", "seed", "kind", "total_steps",
    "actual_steps", "optimizer_steps", "reserved_ub", "n_steps",
    "bank_ref", "code_digest", "checkpoint_manifest")


def expected_main_checkpoint(arm: str, seed: int, *, bank_ref: str,
                             code_digest: str | None = None) -> dict:
    """冻结的主实验槽位期望(R2/C1)。

    期望值全部推导自 p0spec 冻结常数与在场输入原件(train bank
    字节),**不取自待验 run_record 自述**;确认入口据此把候选
    绑定到独立确定的预期槽位(用途=main、arm/seed、训练几何、
    输入/代码身份、预定采集与更新阶段)。
    """
    from rl_posctl.skill_p0.p0spec import (
        ARMS, C1_HORIZON, CHECKPOINT_STEPS, MAIN_TOTAL_STEPS,
        N_STEPS, OPT_STEPS_MAIN_UB, OPT_STEPS_PER_ROLLOUT,
        PPO_SEEDS, TASK_ID)
    if arm not in ARMS:
        raise ValueError(f"未知 arm {arm!r}(须 ∈ {ARMS})")
    if seed not in PPO_SEEDS:
        raise ValueError(f"seed {seed!r} 不在预注册 {PPO_SEEDS}")
    if not bank_ref:
        raise ValueError("bank_ref 缺失:输入身份无法独立确定")
    return {
        "purpose": "main",
        "run_name": f"{arm}_{seed}",
        "arm": arm, "seed": int(seed),
        "total_steps": int(MAIN_TOTAL_STEPS),
        "optimizer_steps": int(OPT_STEPS_MAIN_UB),
        "n_steps": int(N_STEPS),
        "opt_steps_per_rollout": int(OPT_STEPS_PER_ROLLOUT),
        "scheduled_mid_targets": tuple(
            int(c) for c in CHECKPOINT_STEPS
            if 0 < int(c) < int(MAIN_TOTAL_STEPS)),
        "bank_ref": str(bank_ref),
        "code_digest": str(code_digest or p0_code_digest()),
        "task_id": TASK_ID, "horizon": int(C1_HORIZON),
    }


def _check_main_manifest(manifest, expected: dict) -> list:
    """预定采集/更新阶段绑定:checkpoint_manifest 必须覆盖冻结计划
    的 initial + 全部 mid + final,且 mid 为 post-update 几何
    (num_timesteps 为 rollout 整数倍、优化步数与 rollout 数一致)。"""
    problems = []
    if not isinstance(manifest, list) or not manifest:
        return ["run_record.checkpoint_manifest 缺失/非列表"]
    per_stage: dict = {}
    for ent in manifest:
        if not isinstance(ent, dict):
            problems.append("manifest 条目非字典")
            continue
        key = (ent.get("stage"), ent.get("target"))
        per_stage.setdefault(key, []).append(ent)
    dups = [k for k, v in per_stage.items() if len(v) > 1]
    if dups:
        problems.append(f"manifest 重复条目 {dups}")
    total = expected["total_steps"]
    opt_ub = expected["optimizer_steps"]
    n_steps = expected["n_steps"]
    per_ro = expected["opt_steps_per_rollout"]
    init = per_stage.get(("initial", 0), [None])[0]
    if init is None:
        problems.append("manifest 缺 initial(0) 档")
    elif int(init.get("optimizer_steps", -1)) != 0:
        problems.append("initial 档 optimizer_steps != 0")
    for t in expected["scheduled_mid_targets"]:
        ent = per_stage.get(("mid", t), [None])[0]
        if ent is None:
            problems.append(
                f"manifest 缺预定 mid({t})档:计划内采集目标"
                "不得悬置(待 flush 的更新不算完成)")
            continue
        nts = int(ent.get("num_timesteps", -1))
        opts = int(ent.get("optimizer_steps", -1))
        if nts < t or nts % n_steps != 0:
            problems.append(
                f"mid({t}) num_timesteps={nts} 非 post-update"
                f" rollout 边界(≥{t} 且 %{n_steps}==0)")
        if opts != (nts // n_steps) * per_ro:
            problems.append(
                f"mid({t}) optimizer_steps={opts} != "
                f"(num_timesteps/{n_steps})×{per_ro}(更新阶段绑定)")
    fin = per_stage.get(("final", total), [None])[0]
    if fin is None:
        problems.append(f"manifest 缺 final({total}) 档")
    else:
        if int(fin.get("num_timesteps", -1)) != total:
            problems.append(
                f"final num_timesteps={fin.get('num_timesteps')}"
                f" != 计划 {total}")
        if int(fin.get("optimizer_steps", -1)) != opt_ub:
            problems.append(
                f"final optimizer_steps={fin.get('optimizer_steps')}"
                f" != 计划 {opt_ub}")
    return problems


def verify_final_checkpoint_for_slot(path, run_record: dict,
                                     expected: dict) -> dict:
    """主实验槽位绑定核验(R2/C1:在任何 bank 生成/经济评估/随机
    工作之前)。

    在 verify_final_checkpoint(档↔record 自洽 + 存档复算摘要)
    之上,把候选绑定到 expected_main_checkpoint 的独立期望:
    - 必需 record 字段缺失即拒绝(不跳过、不默认合法);
    - 用途:kind 必须 = main(工程 smoke/诊断档不得冒充主实验);
    - 槽位:run_name/arm/seed 与冻结槽位一致;
    - 完成度:total=actual=num_timesteps=131072、optimizer_steps
      =5120、final 不得零更新/少步数;manifest 覆盖预定 mid;
    - 身份:代码(stage/header/record/期望四方一致,过期即拒)、
      输入(bank_ref 三方一致)、task_id/horizon;
    - 优化器证据:存档复算摘要 = 阶段声明(错误声明拒绝)。
    诊断/提前停机原件可在别处保存,但不给科学消费者放行。
    """
    missing = [k for k in MAIN_RECORD_REQUIRED_FIELDS
               if k not in run_record]
    if missing:
        raise RuntimeError(
            "主实验槽位核验失败:run_record 缺必需字段 "
            f"{missing}(缺失即拒绝,不默认合法;R2/C1)\n"
            f"  path={path}")
    out = verify_final_checkpoint(path, run_record)
    info_stage = out["stage"]
    header = out["header"]
    problems = []
    if run_record["kind"] != expected["purpose"]:
        problems.append(
            f"kind={run_record['kind']!r} != 预期用途 "
            f"{expected['purpose']!r}(工程 smoke/诊断档不得"
            "冒充主实验 final)")
    if run_record["run_name"] != expected["run_name"]:
        problems.append(
            f"run_name={run_record['run_name']!r} != 槽位 "
            f"{expected['run_name']!r}(放错槽位/重复占用)")
    if info_stage.get("run_name") != expected["run_name"]:
        problems.append(
            f"stage.run_name={info_stage.get('run_name')!r} != 槽位 "
            f"{expected['run_name']!r}")
    if run_record["arm"] != expected["arm"]:
        problems.append(
            f"arm={run_record['arm']!r} != 槽位 {expected['arm']!r}")
    if header.get("arm") != expected["arm"]:
        problems.append(
            f"header.arm={header.get('arm')!r} != 槽位 "
            f"{expected['arm']!r}")
    if int(run_record["seed"]) != int(expected["seed"]):
        problems.append(
            f"seed={run_record['seed']!r} != 槽位 "
            f"{expected['seed']!r}")
    total = int(expected["total_steps"])
    opt_ub = int(expected["optimizer_steps"])
    for key, want in (("total_steps", total),
                      ("actual_steps", total),
                      ("optimizer_steps", opt_ub),
                      ("n_steps", int(expected["n_steps"]))):
        got = run_record[key]
        if int(got) != want:
            problems.append(
                f"run_record.{key}={got!r} != 计划 {want!r}"
                "(完成度/几何不匹配:少步数、零更新或不足计划"
                "不得签完整 final)")
    if int(run_record["reserved_ub"]) < int(run_record["actual_steps"]):
        problems.append(
            f"reserved_ub={run_record['reserved_ub']!r} < "
            f"actual_steps={run_record['actual_steps']!r}(预算面不符)")
    if int(info_stage["num_timesteps"]) != total:
        problems.append(
            f"stage.num_timesteps={info_stage['num_timesteps']!r}"
            f" != 计划 {total}")
    if int(info_stage["optimizer_steps"]) != opt_ub:
        problems.append(
            f"stage.optimizer_steps={info_stage['optimizer_steps']!r}"
            f" != 计划 {opt_ub}(零更新/未完成计划的 final 不得签)")
    if int(info_stage["target_step"]) != total:
        problems.append(
            f"stage.target_step={info_stage['target_step']!r}"
            f" != 计划 {total}")
    code4 = {
        "stage": info_stage.get("code_digest"),
        "header": header.get("code_digest"),
        "record": run_record["code_digest"],
        "expected": expected["code_digest"]}
    bad_code = {k: v for k, v in code4.items() if v != code4["expected"]}
    if bad_code:
        problems.append(
            f"代码身份不一致/过期 {bad_code} != 期望 "
            f"{code4['expected']!r}")
    bank3 = {"header": header.get("bank_ref"),
             "record": run_record["bank_ref"],
             "expected": expected["bank_ref"]}
    bad_bank = {k: v for k, v in bank3.items()
                if v != bank3["expected"]}
    if bad_bank:
        problems.append(
            f"输入身份(bank_ref)不一致/错配 {bad_bank} != 期望 "
            f"{bank3['expected']!r}")
    if header.get("task_id") != expected["task_id"]:
        problems.append(
            f"header.task_id={header.get('task_id')!r} != "
            f"{expected['task_id']!r}")
    if int(header.get("horizon", -1)) != int(expected["horizon"]):
        problems.append(
            f"header.horizon={header.get('horizon')!r} != "
            f"{expected['horizon']!r}")
    problems.extend(_check_main_manifest(
        run_record["checkpoint_manifest"], expected))
    if problems:
        raise RuntimeError(
            "主实验槽位绑定核验失败,确认入口拒绝(未消费任何资源,"
            "在 bank 生成/经济评估/随机工作之前;R2/C1):\n  "
            + "\n  ".join(problems) + f"\n  path={path}")
    out["expected"] = {
        k: (list(v) if isinstance(v, tuple) else v)
        for k, v in expected.items()}
    out["slot_bound"] = True
    return out


def verify_post_update_save(path, *, expect_stage: str,
                            expect_optimizer_steps: int,
                            expect_timesteps: int) -> dict:
    """单档 post-update 核验(mid/final 通用;smoke 新进程只读用)。"""
    info = inspect_p0_archive(path)
    stage = info["stage"]
    problems = []
    if stage["stage"] != expect_stage:
        problems.append(f"stage={stage['stage']!r}!={expect_stage!r}")
    if int(stage["optimizer_steps"]) != int(expect_optimizer_steps):
        problems.append(
            f"optimizer_steps={stage['optimizer_steps']}"
            f"!={expect_optimizer_steps}")
    if int(stage["num_timesteps"]) != int(expect_timesteps):
        problems.append(
            f"num_timesteps={stage['num_timesteps']}"
            f"!={expect_timesteps}")
    if info["adam_steps"] != int(stage["optimizer_steps"]):
        problems.append(
            f"Adam 步 {info['adam_steps']} != 声明 "
            f"{stage['optimizer_steps']}")
    if info["policy_digest"] != stage["policy_digest"]:
        problems.append("policy 摘要与声明不符")
    if problems:
        raise RuntimeError(
            f"post-update 保存核验失败:{path}\n  "
            + "\n  ".join(problems))
    return info
