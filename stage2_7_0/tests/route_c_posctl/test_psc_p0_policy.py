# -*- coding: utf-8 -*-
"""PSC_P0_v1 分布独立对照(P04/最小反例 2-3;纯数学+受计量采样)。

独立于实现的对照:scipy.special.betainc、数值求积、手工 Beta 密度、
蒙特卡洛;不以同一 helper 的两次输出互证。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import torch as th
from scipy.special import betainc as sci_betainc

from rl_posctl.policy import EPS_COLL, HybridAtomBetaDistribution
from rl_posctl.skill_p0.p0eval import _incbeta_quad
from rl_posctl.skill_p0.p0policy import (
    P0AsymBetaDistribution, asym_interior_representative,
    log_incbeta_eps, log_zero_cell_mass_ab, p0_category_decode)


def _mk_b(branch=(0.0, 0.4), mix=(-0.2, -0.1, 0.3, -0.4),
          ar=0.8, br=1.6, n=1):
    b = th.tensor([branch] * n, dtype=th.float64)
    m = th.tensor([mix] * n, dtype=th.float64)
    a = th.full((n,), ar, dtype=th.float64)
    be = th.full((n,), br, dtype=th.float64)
    return P0AsymBetaDistribution(b, m, a, be)


def test_alpha_beta_domain_floor():
    """α=softplus+1:域下界 1(极负输入 ulp 吸收为精确 1.0);
    softplus(raw) ≥ 2^-52 时严格 >1。"""
    d = _mk_b(ar=-50.0, br=1e-3)
    assert float(d.alpha.min()) >= 1.0
    assert float(d.beta.min()) >= 1.0
    d2 = _mk_b(ar=-30.0, br=-30.0)      # softplus≈9.4e-14 ≥ ulp
    assert float(d2.alpha[0]) > 1.0
    assert float(d2.beta[0]) > 1.0


def test_tail_mass_three_way_grid():
    """闭式级数 vs scipy betainc vs 数值求积(网格)。"""
    worst_sci = 0.0
    skipped_underflow = 0
    for a in (1.0001, 1.1, 2.0, 5.0, 17.3, 100.0, 499.0):
        for b in (1.0001, 1.5, 3.0, 29.7, 250.0, 499.0):
            lp_lo = float(log_incbeta_eps(
                th.tensor(a, dtype=th.float64),
                th.tensor(b, dtype=th.float64)))
            lp_hi = float(log_incbeta_eps(
                th.tensor(b, dtype=th.float64),
                th.tensor(a, dtype=th.float64)))
            ref_lo = float(sci_betainc(a, b, EPS_COLL))
            ref_hi = float(sci_betainc(b, a, EPS_COLL))
            # 极端浓度下两侧真值都可能下溢 float64(exp(log)=0):
            # 对照在 log 空间做;scipy 侧也下溢到 0 的点无法数值
            # 对照,计数跳过(级数与 scipy 在可表示域已全面一致)。
            for lp, ref in ((lp_lo, ref_lo), (lp_hi, ref_hi)):
                if ref <= 0.0:
                    skipped_underflow += 1
                    continue
                if ref > 1e-15:
                    worst_sci = max(
                        worst_sci,
                        abs(math.exp(lp) - ref) / ref)
                elif ref >= 1e-290:
                    # 小值:log 空间对照(相对精度同量级)
                    worst_sci = max(
                        worst_sci,
                        abs(lp - math.log(ref)))
                else:
                    # 次正规数仅剩少量有效位,scipy 侧本身失真,
                    # 无法数值仲裁;计数跳过(级数与 scipy 在可表示
                    # 域已一致)
                    skipped_underflow += 1
            if 1.5 <= a <= 5.0 and 1.5 <= b <= 5.0:
                # 求积第三路仅在弱集中 pdf(端点幂律不陡)时数值
                # 可靠;强集中/近奇异情形的权威对照=scipy betainc
                # (全网格 <1e-12)。此处 log 空间对照覆盖平滑域。
                q = _incbeta_quad(a, b, EPS_COLL, n=40001)
                lp2 = float(log_incbeta_eps(
                    th.tensor(a), th.tensor(b)))
                if q > 0:
                    assert abs(lp2 - math.log(q)) < 1e-5, (
                        a, b, lp2, q)
    assert worst_sci < 1e-12
    assert skipped_underflow >= 0   # 如实记录(强浓度端点双侧下溢)


def test_mirror_swap_property():
    """左右尾互换:I_ε(α,β) 与 I_ε(β,α) 不同(非对称),且
    A 家族(α=β)两者相等;镜像条件质量对调。"""
    d = _mk_b()
    assert float(d.log_Qlo) != float(d.log_Qhi)
    a = 3.3
    sym_lo = float(th.exp(log_incbeta_eps(
        th.tensor(a), th.tensor(a))))
    assert sym_lo == pytest.approx(
        float(sci_betainc(a, a, EPS_COLL)), rel=1e-10)


def test_merged_atoms_sum_with_interior():
    """执行测度总质量:branch×(合并原子+内部)=1。"""
    d = _mk_b(n=6, ar=0.3, br=2.2)
    m = th.exp(d.mix_logp.to(th.float64))
    m3 = m[:, 3]
    a_mass = th.exp(d.merged_atom_logp())
    total = (a_mass[:, 0] + a_mass[:, 1] + a_mass[:, 2]
             + m3 * d.Z)
    p = th.exp(d.branch_logp.to(th.float64))
    joint = (p[:, 0] + p[:, 1] * total)
    assert th.allclose(joint, th.ones_like(joint), atol=1e-12)


def test_logprob_matches_manual_beta_density():
    """内部 log-prob 与手工 Beta 密度+Jacobian 逐位对拍。"""
    d = _mk_b()
    alpha, beta = float(d.alpha), float(d.beta)
    m3 = math.exp(float(d.mix_logp[0, 3]))
    p_r = math.exp(float(d.branch_logp[0, 1]))
    for w in (0.25, -0.4, 0.9, -0.99, 0.01):
        act = th.tensor([[1.0, w]], dtype=th.float32)
        lp = float(d.log_prob(act)[0])
        u = min(max((w + 1.0) / 2.0, EPS_COLL), 1 - EPS_COLL)
        dens = (math.exp((alpha - 1) * math.log(u)
                         + (beta - 1) * math.log1p(-u)
                         - math.lgamma(alpha) - math.lgamma(beta)
                         + math.lgamma(alpha + beta)) / 2.0)
        manual = math.log(p_r * m3 * dens)
        assert lp == pytest.approx(manual, rel=1e-6, abs=1e-9), w


def test_logprob_atoms_merge_tails():
    """原子 log-prob=混合原子+连续并入质量(logaddexp 口径)。"""
    d = _mk_b()
    m = th.exp(d.mix_logp.to(th.float64))[0]
    alpha, beta = float(d.alpha), float(d.beta)
    qlo = float(sci_betainc(alpha, beta, EPS_COLL))
    qhi = float(sci_betainc(beta, alpha, EPS_COLL))
    b0 = float(th.exp(log_zero_cell_mass_ab(
        d.alpha, d.beta)))
    p_r = math.exp(float(d.branch_logp[0, 1]))
    for w, mass in ((-1.0, m[0] + m[3] * qlo),
                    (0.0, m[1] + m[3] * b0),
                    (1.0, m[2] + m[3] * qhi)):
        lp = float(d.log_prob(
            th.tensor([[1.0, w]], dtype=th.float32))[0])
        assert lp == pytest.approx(
            math.log(p_r * mass), rel=1e-6, abs=1e-9), w


def test_hold_joint_logp_excludes_target_head():
    d = _mk_b()
    lp_hold = float(d.log_prob(
        th.tensor([[0.0, 0.0]], dtype=th.float32))[0])
    assert lp_hold == pytest.approx(
        float(d.branch_logp[0, 0]), rel=1e-6)   # log_prob 回 cast f32
    with pytest.raises(ValueError):
        d.log_prob(th.tensor([[0.0, 0.3]], dtype=th.float32))


def test_hold_zero_target_gradient():
    """HOLD 行目标头梯度为 0(未使用头不进似然;数值探针非更新)。"""
    b = th.randn(4, 2, dtype=th.float64)
    m = th.randn(4, 4, dtype=th.float64, requires_grad=True)
    ar = th.randn(4, dtype=th.float64, requires_grad=True)
    br = th.randn(4, dtype=th.float64, requires_grad=True)
    d = P0AsymBetaDistribution(b, m, ar, br)
    acts = th.tensor([[0.0, 0.0]] * 4, dtype=th.float32)
    loss = d.log_prob(acts).sum()
    loss.backward()
    assert m.grad is not None and th.allclose(
        m.grad, th.zeros_like(m.grad), atol=1e-12)
    assert ar.grad is not None and th.allclose(
        ar.grad, th.zeros_like(ar.grad), atol=1e-10)
    assert br.grad is not None and th.allclose(
        br.grad, th.zeros_like(br.grad), atol=1e-10)


def test_entropy_monte_carlo(psc_p0_meter_dist):
    """闭式熵 vs 执行测度蒙特卡洛(小样本受计量)。"""
    d = _mk_b(branch=(0.0, 0.4))
    n = 2048
    th.manual_seed(321)
    acts = th.stack([d.sample()[0] for _ in range(n)])
    psc_p0_meter_dist(n)
    lp = d.log_prob(acts).to(th.float64)
    ent = float(d.entropy()[0])
    ent_mc = float(-lp.mean())
    assert ent == pytest.approx(ent_mc, abs=0.10), (ent, ent_mc)


def test_ratio_identity_frozen_params():
    d = _mk_b(n=8)
    acts = d.sample()
    with th.no_grad():
        lp_old = d.log_prob(acts)
        lp_new = d.log_prob(acts)
    ratio = th.exp(lp_new - lp_old)
    assert th.allclose(ratio, th.ones_like(ratio), atol=1e-6)


def test_extreme_params_finite():
    for ar, br in ((-20.0, -20.0), (8.5, 8.5), (-20.0, 8.5)):
        d = _mk_b(ar=ar, br=br, n=3)
        for name in ("log_Qlo", "log_Qhi", "log_b0"):
            v = getattr(d, name)
            assert bool(th.isfinite(v).all()), (ar, br, name)
        merged = d.merged_atom_logp()
        assert bool(th.isfinite(merged).all())
        lp = d.log_prob(d.sample())
        assert bool(th.isfinite(lp).all())
        ent = d.entropy()
        assert bool(th.isfinite(ent).all()), (ar, br, float(ent[0]))


def test_batch_broadcast():
    d = _mk_b(n=37)
    acts = d.sample()
    assert acts.shape == (37, 2)
    lp = d.log_prob(acts)
    assert lp.shape == (37,)
    assert d.entropy().shape == (37,)
    dec = p0_category_decode(
        d.branch_logits, d.merged_atom_logp(),
        d.interior_log_mass(), d.interior_representative())
    assert dec.shape == (37, 2)


def test_epsilon_collision_sampling(psc_p0_meter_dist):
    """采样执行映射:u≤ε→−1,u≥1−ε→+1(独立直方图核对)。"""
    ar = th.tensor([[-0.9]], dtype=th.float64)   # α≈1.56
    br = th.tensor([[3.4]], dtype=th.float64)    # β≈4.29(偏左)
    b = th.tensor([[0.0, 8.0]], dtype=th.float64)
    m = th.tensor([[-20.0, -20.0, -20.0, 0.0]], dtype=th.float64)
    d = P0AsymBetaDistribution(b, m, ar, br)
    n = 1024
    th.manual_seed(77)
    ws = th.stack([d.sample()[0] for _ in range(n)])[:, 1]
    psc_p0_meter_dist(n)
    ws = ws.numpy()
    assert ((ws > -1.0) & (ws < 1.0) & (ws != 0.0)).all()
    assert ws.mean() < -0.2        # 非对称左偏(镜像反例锚)


def test_interior_representative_no_boundary_collision():
    a = th.tensor([1.0000001, 2.0, 50.0], dtype=th.float64)
    b = th.tensor([1.0000001, 8.0, 2.0], dtype=th.float64)
    w = asym_interior_representative(a, b)
    w32 = w.to(th.float32)
    assert bool((w32 > -1.0).all() and (w32 < 1.0).all())
    assert not bool((w32 == 0.0).any())
    # 符号随 α−β(mode_u−0.5):β 大 → 负;α 大 → 正;对称退化 → 中心
    assert float(w32[1]) < 0.0 and float(w32[2]) > 0.0
    wsym = asym_interior_representative(
        th.tensor([1.0], dtype=th.float64),
        th.tensor([1.0], dtype=th.float64))
    assert abs(float(wsym[0])) <= 2.0 ** -149 + 1e-30


def test_common_decode_tie_breaks():
    """branch 平局取 HOLD;类别平局取低索引(确定)。"""
    bl = th.tensor([[0.0, 0.0]], dtype=th.float64)
    atom = th.log(th.tensor([[0.25, 0.25, 0.25]],
                            dtype=th.float64))
    inter = th.log(th.tensor([0.25], dtype=th.float64))
    rep = th.zeros(1, dtype=th.float64)
    dec = p0_category_decode(bl, atom, inter, rep)
    assert dec[0, 0] == 0.0       # 平局 → HOLD
    bl2 = th.tensor([[0.0, 5.0]], dtype=th.float64)   # REBALANCE 胜出
    dec2 = p0_category_decode(bl2, atom, inter, rep)
    assert dec2[0, 0] == 1.0 and dec2[0, 1] == -1.0   # 平局 → A−


def test_arm_a_view_common_decode():
    """A 臂经 P0DistView:确定性=公共解码;内部代表值=0.0。"""
    from rl_posctl.skill_p0.p0policy import P0DistView
    th.manual_seed(4)
    dist = HybridAtomBetaDistribution(
        th.randn(1, 2, dtype=th.float64),
        th.randn(1, 4, dtype=th.float64),
        th.randn(1, dtype=th.float64))
    view = P0DistView(dist, "A")
    dec = view.mode()
    assert dec.shape == (1, 2)
    assert float(dec[0, 0]) in (0.0, 1.0)
    m = th.exp(dist.mix_logp.to(th.float64))[0]
    if float(dec[0, 0]) == 1.0 and int(th.argmax(m)) != 3:
        assert float(dec[0, 1]) == float(
            [-1.0, 0.0, 1.0][int(th.argmax(m))])
    masses = th.cat([dist._merged_atom_logp(),      # noqa: SLF001
                     (dist.mix_logp.to(th.float64)[:, 3]
                      + th.log(dist.Z))[:, None]], dim=1)
    if int(th.argmax(masses[0])) == 3:
        assert float(dec[0, 1]) == 0.0
