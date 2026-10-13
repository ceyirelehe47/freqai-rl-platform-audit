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
                       dtype=th.float64)[cat_idx]
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


def p0_hyperparams(*, n_steps: int = N_STEPS) -> dict:
    return {
        "hidden": list(HIDDEN), "n_steps": int(n_steps),
        "batch_size": BATCH_SIZE, "n_epochs": N_EPOCHS,
        "learning_rate": LEARNING_RATE, "gamma": GAMMA,
        "gae_lambda": GAE_LAMBDA, "clip_range": CLIP_RANGE,
        "vf_coef": VF_COEF, "max_grad_norm": MAX_GRAD_NORM,
        "ent_coef": ENT_COEF,
    }


def p0_hyperparams_digest(*, n_steps: int = N_STEPS) -> str:
    blob = json.dumps(p0_hyperparams(n_steps=n_steps),
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
                learning_rate: float = LEARNING_RATE) -> PPO:
    """构建 P0 PPO(超参冻结于 p0spec;bank_ref/horizon 绑定数据身份)。"""
    if arm not in ARMS:
        raise ValueError(f"未知 P0 臂 {arm!r}")
    model = PPO(
        env=env, policy=P0ActorCriticPolicy,
        policy_kwargs={"arm": arm,
                       "net_arch": {"pi": list(HIDDEN),
                                    "vf": list(HIDDEN)},
                       "activation_fn": nn.Tanh},
        learning_rate=learning_rate, n_steps=n_steps,
        batch_size=BATCH_SIZE, n_epochs=N_EPOCHS, gamma=GAMMA,
        gae_lambda=GAE_LAMBDA, clip_range=CLIP_RANGE,
        vf_coef=VF_COEF, max_grad_norm=MAX_GRAD_NORM,
        ent_coef=ENT_COEF, seed=seed, device="cpu")
    header = _p0_expected_identity(env, arm=arm, bank_ref=bank_ref,
                                   horizon=horizon, n_steps=n_steps)
    setattr(model, P0_HEADER_KEY, header)
    return model


def _p0_expected_identity(env, *, arm: str, bank_ref: str,
                          horizon: int, n_steps: int = N_STEPS) -> dict:
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
        "hyperparams_digest": p0_hyperparams_digest(n_steps=n_steps),
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
                  horizon: int, n_steps: int = N_STEPS) -> PPO:
    """新进程冷读;旧档/A-B 互载/错观察/错解码/错 gamma 在任何权重
    反序列化之前逐项拒绝。bank_ref/n_steps 允许按用途放宽为 None
    (检查点评估用训练同值)。"""
    header, _ = _read_p0_header(path)
    want = _p0_expected_identity(env, arm=arm, bank_ref=bank_ref,
                                 horizon=horizon, n_steps=n_steps)
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
