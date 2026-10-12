# -*- coding: utf-8 -*-
"""R2-04 参考递推的真实账户状态转移:独立对照与收敛(R2 核心)。

旧缺陷(独立审查 F4):v2 DP 的 HOLD 保持 w 列,与真实环境 HOLD
(保持数量,w_next=w(1+r)/(1+w·r))不一致;固定路径 100→110→99、
初始 50%:真实固定数量净值 99.5,恒比例 99.75。本文件:
- 转移算子 vs TwoSidedLinearLedger 逐位对拍(含 |w|>1 漂移态);
- reviewer 固定路径复现(99.5 / log(0.995));
- 1 步独立 GL-200 积分 vs DP 值(积分器/网格独立);
- 无费固定数量 h 步 = E[log(1+w·(Π(1+r_k)−1))](独立张量积分);
- 网格/求积细化收敛差(error_report)< 声称优势(qualified 门槛);
- 强制平仓边界延伸语义(逐状态精确);格点动作最优性对照。
"""

import math

import numpy as np
import pytest

from rl_posctl.curriculum import (
    W_GRID, error_report, gbar, hold_step, initial_value,
    liq_value, reference_action, reference_policy,
    rebal_fee_fraction, rebal_step, spec_for)
from rl_posctl.ledger import TwoSidedLinearLedger
from rl_posctl import profiles

MS = profiles.MASTER_SEED


def train_spec(course="c4d2", horizon=64):
    return spec_for(course, seed=MS, horizon=horizon,
                    **profiles.TRAIN_SPEC_OVERRIDES)


def build_ledger_state(w_old, fee):
    """构造敞口比恰为 w_old 的账本(|w|>1 经 HOLD 漂移到达)。"""
    led = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=fee)
    if w_old == 0.0:
        return led, 100.0
    if abs(w_old) <= 1.0:
        led.apply_target_ratio(w_old, 100.0)
        return led, 100.0
    r_d = (-w_old - 1.0) / (-w_old + 1.0)
    assert w_old < -1.0 and 0.0 < r_d < 1.0
    led.apply_target_ratio(-1.0, 100.0)
    p_d = 100.0 * (1.0 + r_d)
    got = led.qty * p_d / led.equity(p_d)
    assert abs(got - w_old) < 1e-9
    return led, p_d


class TestTransitionOperatorsVsLedger:
    FEE = 1e-3

    @pytest.mark.parametrize("w_old", [
        -1.0, -0.7, -0.3, 0.0, 0.3, 0.7, 1.0, -1.857, -4.2])
    @pytest.mark.parametrize("w_t", [-1.0, -0.5, 0.0, 0.5, 1.0])
    @pytest.mark.parametrize("r", [-0.09, -0.02, 0.0, 0.03, 0.105])
    def test_rebal_step_matches_ledger(self, w_old, w_t, r):
        if 1.0 + w_old * r <= 0.0:
            pytest.skip("开盘不可偿付域(经济失败)")
        led, p0 = build_ledger_state(w_old, self.FEE)
        e0 = led.equity(p0)
        if w_t != w_old:
            led.apply_target_ratio(w_t, p0)
        p2 = p0 * (1.0 + r)
        e2 = led.equity(p2)
        lg, wn = rebal_step(w_old, w_t, r, self.FEE)
        assert lg == pytest.approx(math.log(e2 / e0), abs=1e-12)
        assert wn == pytest.approx(led.qty * p2 / e2, abs=1e-10)

    @pytest.mark.parametrize("w0", [-1.0, -0.5, 0.5, 1.0, -1.857])
    @pytest.mark.parametrize("r", [0.10, -0.05])
    def test_hold_step_matches_ledger(self, w0, r):
        if 1.0 + w0 * r <= 0.0:
            pytest.skip("破产域")
        led, p0 = build_ledger_state(w0, self.FEE)
        e0 = led.equity(p0)
        p2 = p0 * (1.0 + r)
        e2 = led.equity(p2)
        lg, wn = hold_step(w0, r)
        assert lg == pytest.approx(math.log(e2 / e0), abs=1e-12)
        assert wn == pytest.approx(led.qty * p2 / e2, abs=1e-10)

    def test_rebal_fee_fraction_matches_ledger_solve(self):
        """费用分数 f 与账本扣费后口径求解逐位一致(买卖两支)。"""
        for w_old in (-0.8, 0.0, 0.3, 0.9):
            for w_t in (-1.0, -0.25, 0.0, 0.4, 1.0):
                if w_t == w_old:
                    continue
                led, p0 = build_ledger_state(w_old, self.FEE)
                e0 = led.equity(p0)
                led.apply_target_ratio(w_t, p0)
                f_ledger = 1.0 - led.equity(p0) / e0
                assert rebal_fee_fraction(
                    w_old, w_t, self.FEE) == pytest.approx(
                    f_ledger, abs=1e-12)

    def test_reviewer_fixed_qty_path(self):
        """reviewer 固定路径:100→110→99、初始 50% 多头:真实固定
        数量净值 99.5(恒比例错误模型给 99.75)。"""
        led = TwoSidedLinearLedger(initial_cash=100.0, fee_rate=0.0)
        led.apply_target_ratio(0.5, 100.0)
        lg1, w1 = hold_step(0.5, 0.10)
        assert w1 == pytest.approx(0.5238095238095238, rel=1e-12)
        lg2, w2 = hold_step(w1, -0.1)          # 110 → 99
        # 独立账本复算(不经 DP 算子)
        assert led.equity(110.0) == pytest.approx(105.0)
        assert led.equity(99.0) == pytest.approx(99.5)
        assert lg1 + lg2 == pytest.approx(
            math.log(99.5 / 100.0), rel=1e-12)
        # 恒比例(w 固定 0.5)的对照值 ≠ 真实(差异即旧 DP 缺陷)
        wrong = math.log(1.05) + math.log(0.95)   # = -0.00250313
        assert wrong == pytest.approx(-0.0025031302181185294,
                                      rel=1e-9)
        assert abs(wrong - math.log(0.995)) > 2e-3

    def test_liq_value_matches_ledger(self):
        for w in (0.3, 0.8, 1.0, -1.857):
            led2, p0b = build_ledger_state(w, 1e-3)
            e0b = led2.equity(p0b)
            led2.liquidate(p0b)
            got = math.log(led2.equity(p0b) / e0b)
            assert liq_value(w, 1e-3) == pytest.approx(got, abs=1e-12)


class TestOneStepIndependentIntegration:
    def test_one_step_value_vs_independent_integration(self):
        """h=1:DP values[1][i,k] vs 独立 GL-200 积分对照(积分器/
        网格与 DP 无共享;含扣费口径调仓与终端清算腿)。"""
        spec = train_spec(horizon=1)
        pol = reference_policy(spec, n_dense=81, n_ext=16, m_quad=24)
        fee = spec.fee
        xs, ws = np.polynomial.legendre.leggauss(200)
        ws = ws / 2.0
        grid = pol["grid"]
        checked = 0
        n_grid = len(grid)
        ks = [k for k in (5, n_grid // 4, n_grid // 2,
                          3 * n_grid // 4, n_grid - 5)
              if abs(float(grid[k])) <= 20.0]
        for i in (0, 17, 31, 44, 59):
            mu, sig = float(pol["mu"][i]), float(pol["sigma"][i])
            r_nodes = mu + math.sqrt(3.0) * sig * xs
            for k in ks:
                w = float(grid[k])
                if abs(w) > 1.0 / 0.05:
                    continue
                best = -math.inf
                for a in range(W_GRID.shape[0]):
                    wa = float(W_GRID[a])
                    f = rebal_fee_fraction(w, wa, fee)
                    if f >= 1.0:
                        continue
                    gn = 1.0 + wa * r_nodes
                    if np.any(gn <= 0.0):
                        continue
                    wn_a = wa * (1.0 + r_nodes) / gn
                    acc = float(np.dot(ws, liq_value(wn_a, fee)))
                    val = math.log1p(-f) + float(
                        gbar(np.array(wa), mu, sig)) + acc
                    best = max(best, val)
                if best == -math.inf:
                    continue
                checked += 1
                got = float(pol["values"][1][i, k])
                assert got == pytest.approx(best, abs=2e-4), (
                    i, k, w, got, best)
        assert checked >= 20


class TestNoFeeFixedQtyMultiStep:
    def test_hold_arm_h_steps_vs_tensor_product(self):
        """无费 h=4 纯 HOLD 臂 = E[log(1+w·(Π(1+r_k)−1))]
        (固定数量 telescope 到总价格变化;独立 24^4 张量积分)。"""
        h = 4
        spec = spec_for("c4d2", seed=MS, horizon=h, mu_max=0.0,
                        sigma_lo=0.03, sigma_hi=0.06, fee=0.0)
        pol = reference_policy(spec, n_dense=161, n_ext=32,
                               m_quad=24)
        sig = 0.03
        a = math.sqrt(3.0) * sig
        xs, ws = np.polynomial.legendre.leggauss(24)
        ws = ws / 2.0
        grid = pol["grid"]
        k = 80
        w = float(grid[k])
        i = 0

        # Σ_{r1..r4} Πweights · log(1 + w(Π(1+r)−1)) 逐点枚举
        def rec(depth, prod, weight):
            if depth == h:
                return weight * math.log1p(w * (prod - 1.0))
            tot = 0.0
            for m in range(len(xs)):
                tot += rec(depth + 1, prod * (1.0 + a * xs[m]),
                           weight * float(ws[m]))
            return tot

        tot = rec(0, 1.0, 1.0)
        got = float(pol["hold_values"][h][i, k])
        assert got == pytest.approx(tot, abs=5e-4), (got, tot)


class TestConvergenceAndQualification:
    def test_error_report_bound_below_claimed_advantage(self):
        """c4d2(最小优势档):收敛差 ≪ 值本身 ⇒ value−err>0
        (qualified;误差不手设,来自网格/求积细化)。"""
        spec = train_spec("c4d2")
        rep = error_report(spec, refinements=(
            (81, 16, 12), (161, 32, 24)))
        v = rep["values"][-1]
        assert v > 0.0
        assert rep["err_bound"] < 5e-5, rep
        assert v - rep["err_bound"] > 0.0

    def test_solver_meta_declares_approximation(self):
        pol = reference_policy(train_spec())
        meta = pol["solver_meta"]
        assert meta["action_grid_size"] == 41
        assert meta["account_grid_size"] > 41

    def test_nonzero_slippage_reference_refused(self):
        """未建立近似的执行假设(非零滑点)显式拒绝,不虚算。"""
        spec = spec_for("c4d2", seed=MS, horizon=8,
                        mu_max=1.2e-3, sigma_lo=0.03, sigma_hi=0.06,
                        slippage_bps=5.0)
        with pytest.raises(ValueError, match="slippage"):
            reference_policy(spec)


class TestBoundaryAndActionConsistency:
    def test_forced_flat_boundary_extension_exact(self):
        """|w|>1/mm 的格点值 = log(1−fee|w|) + 该状态从 0 出发
        的值(开盘强制平仓语义的精确延伸;逐状态断言,非截断)。"""
        spec = train_spec()
        # 网格延伸到边界外(25 > 1/mm=20):验证边界外格点的
        # 强制平仓延伸值(默认网格恰止于边界,该区域由求积点
        # 延伸处理;这里显式铺格点验证同一语义)
        pol = reference_policy(spec, n_dense=81, n_ext=16, m_quad=24,
                               w_ext=25.0)
        grid = pol["grid"]
        fee = spec.fee
        mm = pol["solver_meta"]["maintenance_margin"]
        zi = pol["zero_idx"]
        ks = [k for k in range(len(grid))
              if abs(float(grid[k])) > 1.0 / mm]
        assert len(ks) >= 2, "网格未覆盖边界外(检查 w_ext 参数)"
        for sl in (1, 8, 64):
            V = pol["values"][sl]
            for k in ks:
                w = float(grid[k])
                assert abs(w) > 1.0 / mm
                for i in (0, 30, 59):
                    expect = float(liq_value(w, fee)) + float(
                        V[i, zi])
                    got = float(V[i, k])
                    if math.isfinite(expect):
                        assert got == pytest.approx(expect, rel=1e-12)

    def _action_value(self, spec, pol, i, w, sl, action):
        """测试侧按公开公式重算动作价值(平手对照用)。"""
        fee = spec.fee
        grid = pol["grid"]
        zi = pol["zero_idx"]
        x, wq = pol["x"], pol["wq"]
        mu_i, sig_i = float(pol["mu"][i]), float(pol["sigma"][i])
        r_nodes = mu_i + math.sqrt(3.0) * sig_i * x
        if sl - 1 >= 1:
            ev_row = (pol["trans"] @ pol["values"][sl - 1])[i]
        else:
            ev_row = liq_value(grid, fee)

        def cont_at(w_pts):
            w_pts = np.asarray(w_pts, dtype=np.float64)
            wb = 1.0 / pol["solver_meta"]["maintenance_margin"]
            inside = np.abs(w_pts) <= wb
            out = np.empty_like(w_pts)
            out[inside] = np.interp(w_pts[inside], grid, ev_row)
            if (~inside).any():
                out[~inside] = liq_value(
                    w_pts[~inside], fee) + float(ev_row[zi])
            return out

        if action[0] == 0:
            g_hold = 1.0 + w * r_nodes
            if np.any(g_hold <= 0.0):
                return -math.inf
            wn = w * (1.0 + r_nodes) / g_hold
            return float(gbar(np.array(w), mu_i, sig_i)) + float(
                np.dot(wq, cont_at(wn)))
        wa = float(action[1])
        f = rebal_fee_fraction(w, wa, fee)
        if f >= 1.0:
            return -math.inf
        g_a = 1.0 + wa * r_nodes
        if np.any(g_a <= 0.0):
            return -math.inf
        wn_a = wa * (1.0 + r_nodes) / g_a
        a_idx = int(np.argmin(np.abs(W_GRID - wa)))
        return (math.log1p(-f) + float(pol["G"][i, a_idx])
                + float(np.dot(wq, cont_at(wn_a))))

    def test_reference_action_optimal_at_grid_points(self):
        """格点上 reference_action 返回动作的价值 ≥ 策略表候选
        动作的价值(同一价值函数;平手差 < 1e-9)。"""
        spec = train_spec()
        # 默认分辨率:reference_action 内部用默认缓存,必须同一套
        pol = reference_policy(spec)
        grid = pol["grid"]
        table = pol["table"]
        ks = [int(np.argmin(np.abs(grid - v)))
              for v in (0.0, 0.6, 1.2)]
        for i in (0, 20, 40, 59):
            row = {"s": float(table[i, 0]), "c": float(table[i, 1]),
                   "q": float(table[i, 2]), "g": float(table[i, 3])}
            for k in ks:
                w = float(grid[k])
                if abs(w) > 1.0 / 0.05:
                    continue
                for sl in (2, 16, 64):
                    act_i = int(pol["policies"][sl][i, k])
                    grid_action = (
                        (0, 0.0) if act_i < 0
                        else (1, float(W_GRID[act_i])))
                    got = reference_action(
                        spec, row, w, steps_left=sl)
                    v_got = self._action_value(
                        spec, pol, i, w, sl, got)
                    v_tab = self._action_value(
                        spec, pol, i, w, sl, grid_action)
                    assert v_got >= v_tab - 1e-9, (
                        i, k, sl, got, grid_action, v_got, v_tab)