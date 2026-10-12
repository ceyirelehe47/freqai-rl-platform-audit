# -*- coding: utf-8 -*-
"""混合动作 HOLD/REBALANCE(w) 的真实概率分布与 SB3 PPO 接线
(RouteC_PositionControl W2,HybridAtomBetaPolicy-v2,R1 修复)。

分布结构(全部解析,可手算;连续分量的**执行映射质量精确**):
- branch:二元 {HOLD, REBALANCE},softmax(branch_logits[2]);
- target w | REBALANCE:4 分量混合 = 原子 −1/0/+1 + 对称 Beta(α,α)
  经 w=2u−1 的连续分量;分量质量 = softmax(mix_logits[4]),
  α = softplus(raw)+0.05。

R1 修复(P1:显式截断产生质量却按未截断连续密度算似然):
- ε = 2^-25(float32 精确碰撞界):u ≤ ε 时 w=fl32(2u−1) 恰为 −1.0f,
  u ≥ 1−ε 时恰为 +1.0f(IEEE754 就近舍入,含平局取偶验证)。
- 采样器:u~Beta(α,α)(float64);u≤ε → 原子 −1;u≥1−ε → 原子 +1;
  否则 w=fl32(2u−1)∈(−1,1)。截断尾质量**并入边界原子**,不再丢给
  无概率对应的 clamp 边界点。
- 执行动作的联合对数概率(与采样测度严格一致):
  · HOLD:log P(HOLD),不乘任何未执行目标密度;
  · REBALANCE, w=−1:log[exp(mix_lp[0]) + m_c·Q],Q=I_ε(α,α);
  · REBALANCE, w=0 :log[exp(mix_lp[1]) + m_c·b0],
    b0=pdf_u(0.5)·2^-150(fl32 的 0.0 单元宽 2^-150,中点法精确到
    双精度——连续分量也可能落到精确 0,质量归并);
  · REBALANCE, w=+1:log[exp(mix_lp[2]) + m_c·Q];
  · REBALANCE, w∈内部:log m_c + log pdf_u((w+1)/2) − ln2
    (w 空间密度;float32 单元宽度只依赖 w,在 PPO ratio 中消去,
    参数梯度不受影响)。
- Q=I_ε(α,α) 用超几何级数 I_x(a,a)=x^a/(a·B(a,a))·₂F₁(a,1−a;a+1;x)
  的前三项:x=2^-25 时截断相对误差 <1e-15(对 scipy.special.betainc
  在 α∈[0.05,20] 验证到 ~1e-14,含 1e-140 量级);全部解析可微
  (lgamma/exp/log 原生反传),不依赖 betainc 的参数梯度支持。
- 熵(与 log_prob 同一执行分布,闭式):
  H = H_branch + P(REBAL)·[Hdisc4 + I·(h_Beta(α,α) + ln(2Z))]
  其中合并类 {A−=m0+m3Q, A0=m1+m3b0, A+=m2+m3Q, I=m3Z},
  Z=1−2Q−b0,h_Beta 为未截断对称 Beta 微分熵(闭式)。
  Q→0 时退化为旧公式(旧实现是该分布的 Q=0 特例)。
  推导:内部执行密度 f_w=m3·pdf_u(u_w)/2(未归一化,积 m3Z),
  ∫f_w ln f_w = m3Z[ln m3 − h_u − ln2];Hdisc4 用合并类质量。
- 确定性解码(mode):branch=argmax;REBALANCE 时 w=E[w|REBAL]
  = m(+1) − m(−1)(对称 Beta 连续均值 0)。内部非平凡目标由原子
  质量差表达;采样训练→确定性预测的行为一致性由专门测试
  (非平凡正/负内部目标)覆盖,不凭声明。
- 连续分量 α = softplus(raw)+1.0 ∈ (1,∞):边界堆积形态由 ±1 原子
  分量承担(不再需要 α<1 的 U 形连续分量);α≥1 使截断尾积分
  ≤ε^α·O(|lnε|)≈0,闭式熵在双精度下精确——对比上轮 α∈[0.05,∞)
  声称适用却在 α=0.1 处产生 ~10% 尾质量错配的缺陷;
- 数值边界(事前固定,不得改 tol 救结果):logsumexp/log_softmax
  稳定化;
  原子判定 = 与 {−1,0,1} 的精确 float 相等;全部合并质量计算
  上转 float64 后回 cast(避免 float32 加法吞掉小质量)。
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

ALPHA_FLOOR = 1.0
N_DIST_PARAMS = 7          # 2 branch logits + 4 mix logits + 1 alpha raw
# float32(2u−1)==±1.0f 的精确碰撞界(IEEE754 就近舍入,平局取偶):
# |w|<1 区间 float32 在 [0.5,1) 的 ulp=2^-24 → 边界中点 1−2^-25。
EPS_COLL = 2.0 ** -25
# float32 的 0.0f 执行值对应的 u 单元半宽(次正规数下探;
# 连续分量落进精确 0 的概率 ≈ pdf(0.5)·2^-150,中点法精确)。
HALF_CELL_W0 = 2.0 ** -150
_LN2 = math.log(2.0)


def torch_lgamma_beta(a: th.Tensor) -> th.Tensor:
    """lnB(a,a) = 2lnΓ(a) − lnΓ(2a)。"""
    return 2.0 * th.lgamma(a) - th.lgamma(2.0 * a)


def log_tail_mass(alpha: th.Tensor) -> th.Tensor:
    """logQ, Q = I_ε(α,α)(对称 Beta 左尾质量;ε=2^-25)。

    I_x(a,a) = x^a/(a·B(a,a)) · ₂F₁(a, 1−a; a+1; x)
    ₂F₁ 级数取 3 项:x≈2.98e-8 时截断相对误差 <1e-15
    (对 scipy.special.betainc 全域 α∈[0.05,20] 验证)。
    """
    a = alpha.to(th.float64)
    x = EPS_COLL
    # ₂F₁ = 1 + (a(1−a)/(a+1))x + ((a)_2(1−a)_2/((a+1)_2 2!))x²
    po = a
    qo = (1.0 - a)
    ro = (a + 1.0)
    t1 = po * qo / ro * x
    po2 = po * a
    qo2 = qo * (1.0 - a)
    ro2 = ro * (a + 2.0)
    t2 = po2 * qo2 / ro2 / 2.0 * x * x
    s = 1.0 + t1 + t2
    lnB = torch_lgamma_beta(a)
    return a * math.log(x) - th.log(a) - lnB + th.log(s)


def log_zero_cell_mass(alpha: th.Tensor) -> th.Tensor:
    """log b0, b0 = pdf_u(0.5)·2^-150(fl32 0.0 执行单元质量)。"""
    a = alpha.to(th.float64)
    lnB = torch_lgamma_beta(a)
    ln_pdf_half = -lnB - 2.0 * (a - 1.0) * _LN2
    return ln_pdf_half - 150.0 * _LN2


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
        # 尾质量/零单元质量(计算在 float64;梯度对 α 解析可得)
        self.log_Q = log_tail_mass(self.alpha)
        self.Q = th.exp(self.log_Q)
        self.b0 = th.exp(log_zero_cell_mass(self.alpha))
        # 内部支撑总质量因子 Z = 1 − 2Q − b0(α>1 ⇒ Q=I_ε(α,α)
        # ≤ I_ε(1,1)=ε=3e-8;α=1(均匀)时尾积分恰为 0 ⇒ 闭式熵精确)
        self.Z = (1.0 - 2.0 * self.Q - self.b0).to(th.float64).clamp(
            min=1e-12)

    # ------------------------------------------------------ helpers
    @staticmethod
    def _split_actions(actions: th.Tensor):
        a = actions.reshape(-1, 2).to(th.float64)
        branch = a[:, 0]
        w = a[:, 1]
        return branch, w

    def _beta_logpdf_u(self, u: th.Tensor) -> th.Tensor:
        """log Beta(u; α,α)(u∈(ε,1−ε) 内部,未归一化截断处理)。"""
        a = self.alpha.to(th.float64)
        lnB = torch_lgamma_beta(a)
        return (a - 1.0) * th.log(u) + (a - 1.0) * th.log1p(-u) - lnB

    def _merged_atom_logp(self) -> th.Tensor:
        """(N,3):执行值 ∈ {−1,0,+1} 的合并原子质量对数。"""
        m_lp = self.mix_logp.to(th.float64)
        cont = m_lp[:, 3]
        out = th.stack([
            th.logaddexp(m_lp[:, 0], cont + self.log_Q),
            th.logaddexp(m_lp[:, 1],
                         cont + log_zero_cell_mass(self.alpha)),
            th.logaddexp(m_lp[:, 2], cont + self.log_Q)], dim=1)
        return out

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
        hold_lp = self.branch_logp[:, 0].to(th.float64)
        rebal_lp = self.branch_logp[:, 1].to(th.float64)
        out = th.where(is_hold, hold_lp, rebal_lp)

        # REBALANCE 行的目标似然(执行映射精确版)
        atom_id = th.where(
            w == -1.0, th.zeros_like(w, dtype=th.int64),
            th.where(w == 0.0, th.ones_like(w, dtype=th.int64),
                     th.where(w == 1.0, 2 * th.ones_like(
                         w, dtype=th.int64),
                         3 * th.ones_like(w, dtype=th.int64))))
        atom_hit = (atom_id < 3) & is_rebal
        merged = self._merged_atom_logp()
        idx = th.arange(merged.shape[0], device=merged.device)
        target_atom_lp = merged[idx, atom_id.clamp(max=2)]
        # 内部判定直接看 float32 执行值:严格落在 (−1,0)∪(0,1) 的
        # float32 值都是合法内部点(含边界单元 −1+2^-24/1−2^-24);
        # 其 u=(w+1)/2 ∈ [2^-25, 1−2^-25] ⊂ (0,1),logpdf 恒安全。
        interior_hit = (w > -1.0) & (w < 1.0) & (w != 0.0) & is_rebal
        u = ((w + 1.0) / 2.0)
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
        branch = th.bernoulli(
            th.exp(self.branch_logp[:, 1]))              # 1=REBALANCE
        comp = th.multinomial(
            th.exp(self.mix_logp), 1, replacement=True).squeeze(1)
        a64 = self.alpha.to(th.float64)
        u = th.distributions.Beta(a64, a64).sample()
        w_cont = 2.0 * u - 1.0
        w_cont = th.where(u <= float(EPS_COLL), -1.0, w_cont)
        w_cont = th.where(u >= 1.0 - float(EPS_COLL), 1.0, w_cont)
        w_atom = th.tensor(
            [-1.0, 0.0, 1.0, 0.0], device=u.device,
            dtype=th.float64)[comp.to(u.device)]
        w = th.where(comp.to(u.device) == 3, w_cont, w_atom)
        w = th.where(branch.to(u.device) == 1.0, w,
                     th.zeros_like(w))
        out = th.stack(
            [branch.to(u.device).to(th.float64), w], dim=1)
        return out.to(th.float32)

    def mode(self) -> th.Tensor:
        branch = (self.branch_logits.argmax(dim=-1)).to(th.float64)
        m = th.exp(self.mix_logp.to(th.float64))
        # E[w | REBAL] = m(+1) − m(−1)(对称 Beta 连续均值 0)
        w_mean = (m[:, 2] - m[:, 0]).clamp(-1.0, 1.0)
        w = th.where(branch == 1.0, w_mean, th.zeros_like(w_mean))
        return th.stack([branch, w], dim=1).to(th.float32)

    def get_actions(self, deterministic: bool = False) -> th.Tensor:
        return self.mode() if deterministic else self.sample()

    # ------------------------------------------------------ entropy
    def entropy(self) -> th.Tensor:
        p = th.exp(self.branch_logp).to(th.float64)
        h_branch = -(p * self.branch_logp.to(th.float64)).sum(-1)
        m = th.exp(self.mix_logp.to(th.float64))           # (N,4)
        m3 = m[:, 3]
        a = self.alpha.to(th.float64)
        Q, b0, Z = self.Q, self.b0, self.Z
        # 合并执行类:{A−, A0, A+, I}
        A_minus = m[:, 0] + m3 * Q
        A_zero = m[:, 1] + m3 * b0
        A_plus = m[:, 2] + m3 * Q
        interior = m3 * Z
        probs = th.stack(
            [A_minus, A_zero, A_plus, interior], dim=1).clamp(min=1e-300)
        h_disc = -(probs * probs.log()).sum(-1)
        # H_Beta(α,α) = lnB − 2(α−1)ψ(α) + (2α−2)ψ(2a)(微分熵)
        lnB = torch_lgamma_beta(a)
        psi_a = th.digamma(a)
        psi_2a = th.digamma(2.0 * a)
        h_beta = lnB - 2.0 * (a - 1.0) * psi_a + (2.0 * a - 2.0) * psi_2a
        h_target = h_disc + interior * (h_beta + th.log(2.0 * Z))
        return (h_branch + p[:, 1] * h_target).to(th.float32)


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

# 存档 header 必须携带、load 侧必须逐项比对的全部身份字段。
POSCTL_HEADER_FIELDS = (
    "policy_spec", "env_core", "observation_spec", "action_spec",
    "reward_spec", "execution_spec", "ledger", "n_dist_params",
    "obs_dim", "account_features", "action_space_lo", "action_space_hi")


def env_identity(env) -> dict:
    """从环境提取存档身份(反序列化前比对用)。"""
    u = env.unwrapped
    return {
        "env_core": getattr(u, "env_core_version", None),
        "observation_spec": getattr(u, "observation_spec_version", None),
        "action_spec": getattr(u, "action_spec_version", None),
        "reward_spec": getattr(u, "reward_spec_version", None),
        "execution_spec": getattr(u, "execution_spec_version", None),
        "ledger": getattr(u, "ledger_version", None),
        "obs_dim": int(np.prod(env.observation_space.shape)),
        "account_features": list(getattr(
            u, "n_account_features_obj", None) or ()),
    }


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
    header = env_identity(env)
    header.update({
        "policy_spec": POSCTL_POLICY_SPEC_VERSION,
        "n_dist_params": N_DIST_PARAMS,
        "account_features": list(_account_feature_names(env)),
        "action_space_lo": [float(x) for x in
                            env.action_space.low.tolist()],
        "action_space_hi": [float(x) for x in
                            env.action_space.high.tolist()],
    })
    setattr(model, POSCTL_HEADER_KEY, header)
    return model


def _account_feature_names(env):
    from rl_posctl.versions import POSCTL_ACCOUNT_FEATURES
    return POSCTL_ACCOUNT_FEATURES


def save_posctl_model(model: PPO, path) -> None:
    header = getattr(model, POSCTL_HEADER_KEY, None)
    if not header:
        raise RuntimeError("缺少 posctl policy header,拒绝保存")
    missing = [k for k in POSCTL_HEADER_FIELDS if k not in header]
    if missing:
        raise RuntimeError(
            f"posctl header 缺字段 {missing},拒绝保存")
    model.save(str(path))


def load_posctl_model(path, env) -> PPO:
    """新进程冷读;身份不匹配(含旧二元 PPO 存档)在**任何权重
    反序列化之前**显式拒绝。维数相同但语义不同(版本/特征名/动作
    空间签名不一致)必须拒绝。"""
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
    env_id = env_identity(env)
    env_id.update({
        "policy_spec": POSCTL_POLICY_SPEC_VERSION,
        "n_dist_params": N_DIST_PARAMS,
        "account_features": list(_account_feature_names(env)),
        "action_space_lo": [float(x) for x in
                            env.action_space.low.tolist()],
        "action_space_hi": [float(x) for x in
                            env.action_space.high.tolist()],
    })
    problems = []
    for key in POSCTL_HEADER_FIELDS:
        got, want = header.get(key, None), env_id[key]
        if got != want:
            problems.append(f"{key}: 存档 {got!r} != 环境 {want!r}")
    if problems:
        raise RuntimeError(
            "posctl 存档身份不匹配,拒绝误载"
            f"(同维不同语义不允许):\n  " + "\n  ".join(problems)
            + f"\n  path={path}")

    model = PPO.load(
        path, env=env, device="cpu",
        custom_objects={
            "policy_class": HybridActorCriticPolicy,
            POSCTL_HEADER_KEY: getattr_local(header)})
    return model


def load_posctl_model_archive(path):
    """旧版本存档的只读冷载(R2-06 原件移交;不构造新环境)。

    - zip 内 _posctl_policy_header 必须完整(POSCTL_HEADER_FIELDS);
    - policy_spec/n_dist_params 必须与当前代码一致(策略网络语义
      未变,旧权重可加载);env_core/execution 等环境身份**原样
      返回**(如 R1 的 PosctlEnvCore-v2)供调用方如实披露,不强制
      匹配新环境——新环境热载请用 load_posctl_model(逐项比对拒绝)。
    - PPO.load 不带 env(使用存档自带 spaces);仅供权重回读/
      确定性前向核验,不得用于新训练。
    """
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
            f"存档缺少 {POSCTL_HEADER_KEY}(旧二元 PPO 或异源存档),"
            f"显式拒绝误载:{path}")
    missing = [k for k in POSCTL_HEADER_FIELDS if k not in header]
    if missing:
        raise RuntimeError(
            f"存档 header 缺字段 {missing},拒绝:{path}")
    if header.get("policy_spec") != POSCTL_POLICY_SPEC_VERSION:
        raise RuntimeError(
            f"策略语义不匹配(存档 {header.get('policy_spec')!r} != "
            f"代码 {POSCTL_POLICY_SPEC_VERSION!r}),拒绝:{path}")
    if int(header.get("n_dist_params", -1)) != N_DIST_PARAMS:
        raise RuntimeError("分布参数数不匹配,拒绝误载")
    model = PPO.load(
        path, env=None, device="cpu",
        custom_objects={
            "policy_class": HybridActorCriticPolicy,
            POSCTL_HEADER_KEY: getattr_local(header)})
    return model, dict(header)


def getattr_local(header):
    return header


def attach_env_identity(model: PPO, env, obs_dim: int | None = None) -> PPO:
    """保存前补全/覆核观察维数与全部环境身份(load 侧逐项比对)。"""
    header = getattr(model, POSCTL_HEADER_KEY, None)
    if header is None:
        raise RuntimeError("缺少 posctl policy header")
    env_id = env_identity(env)
    if obs_dim is None:
        obs_dim = env_id["obs_dim"]
    header["obs_dim"] = int(obs_dim)
    for k in ("env_core", "observation_spec", "action_spec",
              "reward_spec", "execution_spec", "ledger"):
        header[k] = env_id[k]
    header.setdefault("policy_spec", POSCTL_POLICY_SPEC_VERSION)
    header.setdefault("n_dist_params", N_DIST_PARAMS)
    header.setdefault("account_features", list(_account_feature_names(env)))
    if "action_space_lo" not in header:
        header["action_space_lo"] = [float(x) for x in
                                     env.action_space.low.tolist()]
        header["action_space_hi"] = [float(x) for x in
                                     env.action_space.high.tolist()]
    setattr(model, POSCTL_HEADER_KEY, header)
    return model


# 兼容旧调用名:只补观察维数(其余身份由 make_posctl_ppo 已带;
# env 侧字段若需补全请用 attach_env_identity(model, env))。
def attach_obs_dim(model: PPO, obs_dim: int) -> PPO:
    header = getattr(model, POSCTL_HEADER_KEY, None)
    if header is None:
        raise RuntimeError("缺少 posctl policy header")
    header["obs_dim"] = int(obs_dim)
    setattr(model, POSCTL_HEADER_KEY, header)
    return model
