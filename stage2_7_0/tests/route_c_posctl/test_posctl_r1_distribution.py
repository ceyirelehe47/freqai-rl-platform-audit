# -*- coding: utf-8 -*-
"""R1-B 混合分布执行映射正反例(独立审查 §4 原反例+概率一致性)。

原反例(上轮缺陷):显式 Beta 截断把 ~10% 样本压到边界点却仍用连续
pdf 算似然;熵按未截 Beta 公式。v2 分布:截断尾质量并入边界原子、
0 单元质量、float32 碰撞界 ε=2^-25 全部精确;采样测度 = log_prob
测度;熵同一分布闭式;ratio 同源;内部非平凡目标可表达。
"""

import math

import numpy as np
import pytest
import torch as th

from rl_posctl.policy import (
    ALPHA_FLOOR, EPS_COLL, HybridAtomBetaDistribution,
    log_tail_mass, log_zero_cell_mass)

try:
    from scipy.special import betainc as _scipy_betainc
except ImportError:      # pragma: no cover
    _scipy_betainc = None


def inv_softplus(y: float) -> float:
    return math.log(math.expm1(y))


def make_dist(branch_p=(0.3, 0.7), mix=(0.1, 0.2, 0.3, 0.4),
              alpha=2.0, n=4000):
    bl = th.tensor([[math.log(branch_p[0]),
                     math.log(branch_p[1])]] * n,
                   dtype=th.float64)
    ml = th.tensor([[math.log(m) for m in mix]] * n,
                   dtype=th.float64)
    ar = th.tensor([inv_softplus(alpha - ALPHA_FLOOR)] * n,
                   dtype=th.float64)
    return HybridAtomBetaDistribution(bl, ml, ar)


def _ci4(p, n):
    """二项 4σ 置信半径(经验频率对照)。"""
    return 4.0 * math.sqrt(max(p * (1 - p), 1e-12) / n)


class TestTailMassExact:
    @pytest.mark.parametrize("alpha", [1.0, 1.5, 2.0, 5.0, 20.0])
    def test_Q_matches_scipy_incomplete_beta(self, alpha):
        if _scipy_betainc is None:      # pragma: no cover
            pytest.skip("scipy 不可用")
        ref = float(_scipy_betainc(alpha, alpha, EPS_COLL))
        got = math.exp(float(log_tail_mass(
            th.tensor([alpha], dtype=th.float64))[0]))
        assert got == pytest.approx(ref, rel=1e-12, abs=1e-300)

    def test_alpha_floor_bounds_Q_tiny(self):
        """α 下界 1.0(均匀)⇒ Q=I_ε(1,1)=ε=2^-25;Z>0 恒成立,
        截断尾积分在 α=1 恰为 0(闭式熵精确的边界情形)。"""
        q = math.exp(float(log_tail_mass(
            th.tensor([1.0], dtype=th.float64))[0]))
        assert q == pytest.approx(2.0 ** -25, rel=1e-9)


class TestSamplingMatchesLogProb:
    @pytest.mark.parametrize("alpha,mix", [
        (1.001, (0.1, 0.2, 0.3, 0.4)),
        (1.0001, (0.25, 0.25, 0.25, 0.25)),
        (2.0, (0.1, 0.2, 0.3, 0.4)),
    ])
    def test_executed_atom_frequencies_match_merged_mass(
            self, alpha, mix):
        """执行值 {−1,0,+1} 的经验频率 = 合并质量(含连续尾并入),
        4σ 二项置信;上轮 ~10% 尾质量错配在此显形。"""
        th.manual_seed(1234)
        d = make_dist(mix=mix, alpha=alpha, n=1)
        n = 200_000
        d2 = make_dist(mix=mix, alpha=alpha, n=n)
        acts = d2.sample()
        w = acts[:, 1].to(th.float64)
        p_neg = float(th.exp(d2._merged_atom_logp()[0, 0]))
        p_zero = float(th.exp(d2._merged_atom_logp()[0, 1]))
        p_plus = float(th.exp(d2._merged_atom_logp()[0, 2]))
        f_neg = float((w == -1.0).double().mean())
        f_plus = float((w == 1.0).double().mean())
        # 全体样本频率 = P(rebal) × 合并原子质量(HOLD 行 w 恒 0 但
        # branch=0;这里把 0 原子对照限制在 rebal 行内)
        rebal = acts[:, 0] == 1.0
        f_zero = float((w[rebal] == 0.0).double().mean())
        assert f_neg == pytest.approx(0.7 * p_neg,
                                      abs=_ci4(0.7 * p_neg, n))
        assert f_plus == pytest.approx(0.7 * p_plus,
                                       abs=_ci4(0.7 * p_plus, n))
        assert f_zero == pytest.approx(p_zero,
                                       abs=_ci4(p_zero, n))

    def test_boundary_atoms_get_continuous_tail_mass_formula(self):
        """执行 −1 的合并质量 = m0 + m3·Q(Q 用级数与 scipy 双验证);
        α=1 时 Q=ε=2^-25(连续分量为均匀:边界路由仍是精确公式,
        不留无概率对应的 clamp 边界点)。"""
        if _scipy_betainc is None:      # pragma: no cover
            pytest.skip("scipy 不可用")
        alpha, mix = 1.0000001, (0.1, 0.2, 0.3, 0.4)
        d = make_dist(mix=mix, alpha=alpha, n=1)
        q = float(_scipy_betainc(alpha, alpha, EPS_COLL))
        merged_neg = math.exp(
            float(d._merged_atom_logp()[0, 0]))
        assert merged_neg == pytest.approx(
            mix[0] + mix[3] * q, rel=1e-12)
        th.manual_seed(7)
        d2 = make_dist(mix=mix, alpha=alpha, n=200_000)
        w = d2.sample()[:, 1].to(th.float64)
        f_neg = float((w == -1.0).double().mean())
        assert f_neg == pytest.approx(0.7 * merged_neg,
                                     abs=_ci4(0.7 * merged_neg, 200_000))

    def test_interior_mean_expresses_nontrivial_targets(self):
        """非平凡内部目标可表达:E[w|REBAL] = m₊−m₋ = 0.4;
        采样均值一致(确定性解码路径的行为一致性基础)。"""
        th.manual_seed(11)
        mix = (0.2, 0.2, 0.6, 1e-12)   # E[w|rebal] = 0.6−0.2 = 0.4
        d = make_dist(branch_p=(0.01, 0.99), mix=mix, alpha=2.0,
                      n=100_000)
        acts = d.sample()
        w = acts[:, 1].to(th.float64)
        rebal = acts[:, 0] == 1.0
        mean_w = float(w[rebal].mean())
        assert mean_w == pytest.approx(0.4, abs=0.01)
        mode = d.mode()
        assert float(mode[0, 1]) == pytest.approx(0.4, abs=1e-6)
        neg_mix = (0.6, 0.2, 0.2, 1e-12)
        d2 = make_dist(branch_p=(0.01, 0.99), mix=neg_mix, alpha=2.0,
                       n=1)
        assert float(d2.mode()[0, 1]) == pytest.approx(-0.4, abs=1e-6)


class TestEntropySameDistribution:
    @pytest.mark.parametrize("alpha,mix", [
        (1.001, (0.1, 0.2, 0.3, 0.4)),
        (1.0001, (0.25, 0.25, 0.25, 0.25)),
        (2.0, (0.05, 0.05, 0.05, 0.85)),
        (5.0, (0.1, 0.2, 0.3, 0.4)),
    ])
    def test_entropy_matches_monte_carlo_negative_logp(self, alpha,
                                                       mix):
        """H = −E[log p(执行动作)] 的 MC 估计 vs entropy() 闭式
        (同一执行分布;HOLD/原子/内部全体)。"""
        th.manual_seed(99)
        n = 200_000
        d = make_dist(mix=mix, alpha=alpha, n=n)
        acts = d.sample()
        lp = d.log_prob(acts).to(th.float64)
        h_mc = float(-lp.mean())
        h_cf = float(d.entropy()[0])
        assert h_mc == pytest.approx(h_cf, rel=0.02, abs=0.05), \
            (alpha, mix, h_mc, h_cf)

    def test_entropy_reduces_to_old_formula_when_tail_negligible(self):
        """α=2(Q≈1e-15)时 v2 熵 ≈ 旧未截断公式(旧实现是特例)。"""
        mix = (0.1, 0.2, 0.3, 0.4)
        alpha = 2.0
        d = make_dist(mix=mix, alpha=alpha, n=1)
        m = th.tensor(mix, dtype=th.float64)
        h_disc = float(-(m * m.log()).sum())
        lnB = float(2 * math.lgamma(alpha)
                    - math.lgamma(2 * alpha))
        h_beta = (lnB - 2 * (alpha - 1) * float(th.digamma(
            th.tensor(alpha, dtype=th.float64)))
            + (2 * alpha - 2) * float(th.digamma(
                th.tensor(2 * alpha, dtype=th.float64))))
        old = h_disc + m[3] * (h_beta + math.log(2.0))
        got = float(d.entropy()[0])
        h_branch = -(0.3 * math.log(0.3) + 0.7 * math.log(0.7))
        # entropy() 含 branch 项:比对 target 部分应去掉 H_branch/加权
        assert got == pytest.approx(h_branch + 0.7 * old, abs=1e-6)  # entropy() 返回 float32


class TestRatioAndGradients:
    def test_ratio_interior_cell_width_cancels(self):
        """PPO ratio:内部点的 float32 单元宽 Δu(w) 只依赖 w,
        同一动作在 new/old 两次评估中相消——独立概率密度复核。"""
        d1 = make_dist(mix=(0.1, 0.2, 0.3, 0.4), alpha=1.5, n=1)
        d2 = make_dist(mix=(0.2, 0.2, 0.2, 0.4), alpha=1.2, n=1)
        for w0 in (0.3, -0.55, 0.05, -0.05, 0.9999999):
            w = float(np.float32(w0))   # 执行值 = float32 表示
            a = th.tensor([[1.0, w]], dtype=th.float32)
            lp1 = float(d1.log_prob(a)[0])
            lp2 = float(d2.log_prob(a)[0])
            ratio = math.exp(lp1 - lp2)
            # 独立实现:分支 + 连续密度比(m3·pdf/2 全解析)
            def pdf_mix(d, mix, alpha):
                u = (w + 1.0) / 2.0
                lnB = 2 * math.lgamma(alpha) - math.lgamma(
                    2 * alpha)
                lnpdf = ((alpha - 1) * math.log(u)
                         + (alpha - 1) * math.log1p(-u) - lnB)
                return math.log(mix[3]) + lnpdf - math.log(2.0)
            lp1_ref = (math.log(0.7)
                       + pdf_mix(d1, (0.1, 0.2, 0.3, 0.4), 1.5))
            lp2_ref = (math.log(0.7)
                       + pdf_mix(d2, (0.2, 0.2, 0.2, 0.4), 1.2))
            assert lp1 == pytest.approx(lp1_ref, abs=1e-5), (
                w, lp1, lp1_ref)
            assert lp2 == pytest.approx(lp2_ref, abs=1e-5), (
                w, lp2, lp2_ref)
            assert ratio == pytest.approx(
                math.exp(lp1_ref - lp2_ref), rel=1e-4), w

    def test_hold_logprob_invariant_to_target_head(self):
        """HOLD 伪目标零似然梯度:扰动 mix/alpha 头,HOLD 的 logp
        不变(未执行目标不贡献密度)。"""
        d1 = make_dist(mix=(0.1, 0.2, 0.3, 0.4), alpha=1.001, n=1)
        d2 = make_dist(mix=(0.7, 0.1, 0.1, 0.1), alpha=3.0, n=1)
        a = th.tensor([[0.0, 0.0]], dtype=th.float32)
        lp1 = float(d1.log_prob(a)[0])
        lp2 = float(d2.log_prob(a)[0])
        assert lp1 == lp2   # 只由 branch 概率决定

    def test_extreme_params_no_nan(self):
        for mix in ((0.98, 0.01, 0.005, 0.005),
                    (0.002, 0.002, 0.002, 0.994)):
            for alpha in (1.0001, 50.0):
                d = make_dist(branch_p=(0.001, 0.999), mix=mix,
                              alpha=alpha, n=64)
                acts = d.sample()
                lp = d.log_prob(acts)
                ent = d.entropy()
                assert bool(th.isfinite(lp).all())
                assert bool(th.isfinite(ent).all())

    def test_boundary_collision_values_legal(self):
        """float32 边界单元(−1+2^-24 等)是合法内部点,不误报
        编码错误;其 log_prob 有限。"""
        d = make_dist(mix=(0.2, 0.2, 0.2, 0.4), alpha=1.001, n=1)
        w = float(np.float32(-1.0 + 2.0 ** -24))
        lp = float(d.log_prob(
            th.tensor([[1.0, w]], dtype=th.float32))[0])
        assert math.isfinite(lp)
