# -*- coding: utf-8 -*-
"""课程有效性测试(W3 v2,R1 修复四档与参考数学;看学习结果前固定)。

覆盖:
- C4 四档真实差异:同 seed 下价格/特征逐位不同(上轮 P1:四个名字
  对应同一生成过程);每档能力点非空(D0 方向幅度/D1 风险敏感/
  D2 动态调仓反手/D3 成本敏感 HOLD);
- 参考数学:有界均匀噪声律下 gbar 闭式 = 幂级数精确(含支撑内
  破产 → −inf,不用 GH 节点声称概率 0);DP 参考 = 可观察状态
  MDP 精确解(h=6 独立暴力实现对照);
- 训练面有效性:DP 参考在 TRAIN 规格下输出非平凡(内部仓位双侧/
  HOLD/调仓/反手),且在固定 bank 上不劣于 flat 等基线;
- C1 无门控结构(镜像边前提);C2 同信号跨上下文最优动作不同;
  C3 参考跳过低于费用的边际;
- 生成器因果性与分区隔离(v1 语义保留)。
"""

import math

import numpy as np
import pandas as pd
import pytest

from rl_posctl.curriculum import (
    Q_FRESH_P, Q_LEVELS, generate_episode, gbar, kelly_w, mu_eff_of,
    reference_action, reference_policy, spec_for, tier_validity,
    baseline_policies, W_GRID, _state_chain, TIER_OVERRIDES)
from rl_posctl.banks import domain_seed, episode_seed
from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize
from rl_posctl import profiles

MS = profiles.MASTER_SEED
TIERS = ("c4d0", "c4d1", "c4d2", "c4d3")


def make_env(spec, seed):
    prices, feats, _ = generate_episode(spec, seed)
    return HybridPositionEnv(
        features=feats, prices=prices, fee=spec.fee, window_size=1)


def ref_fn(spec):
    def fn(row, w, sl):
        return reference_action(spec, row, w, steps_left=sl)
    return fn


# ==================== 参考数学(有界均匀律) ====================
class TestGbarClosedForm:
    def test_matches_power_series(self):
        """闭式 vs log(1+cu) 幂级数(独立推导;双精度一致)。"""
        rng = np.random.default_rng(3)
        for _ in range(60):
            mu = rng.uniform(-2e-3, 2e-3)
            sig = rng.uniform(0.02, 0.06)
            w = rng.uniform(-1.0, 1.0)
            c = w * math.sqrt(3.0) * sig
            b = 1.0 + w * mu
            assert b - abs(c) > 0.05, "测试域须远离破产界"
            eu = {2: 1 / 3, 4: 1 / 5, 6: 1 / 7, 8: 1 / 9,
                  10: 1 / 11, 12: 1 / 13, 14: 1 / 15, 16: 1 / 17}
            s = math.log(b)
            for k, ek in eu.items():
                s += (-(c / b) ** k) * ek / k
            cf = float(gbar(np.array(w), mu, sig))
            assert cf == pytest.approx(s, abs=1e-14, rel=1e-12), \
                (mu, sig, w, cf, s)

    def test_variance_drag_mu_zero(self):
        """μ=0 时 E = −w²σ²/2 + O(σ⁴)(波动拖累,无伪漂移)。"""
        for sig in (0.03, 0.06):
            w = 0.5
            v = float(gbar(np.array(w), 0.0, sig))
            assert v < 0
            assert v == pytest.approx(
                -(w ** 2) * sig ** 2 / 2.0, rel=0.1)

    def test_ruin_inside_support_is_neg_inf(self):
        """支撑内 1+w·r ≤ 0 可达时如实 −inf(不粉饰为节点均值)。"""
        a = math.sqrt(3.0) * 0.06
        mu = -(1.0 - 0.5 * a)      # 1+μ+a>0 但 1+μ−a<0
        assert float(gbar(np.array(1.0), mu, 0.06)) == -math.inf

    def test_kelly_interior_for_train_face(self):
        spec = spec_for("c4d2", seed=MS,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        mu = spec.mu_max * 0.5      # q=0.5 档(内部仓位考点状态)
        w = kelly_w(mu, spec.sigma_lo)
        assert 0.1 < w < 1.0       # 内点(非 0 非端点)
        assert kelly_w(spec.mu_max, spec.sigma_lo) >= 0.99  # 端点考点


# ==================== DP 参考精确性 ====================
class TestDPReferenceExactness:
    def _independent_chain(self, spec):
        """从生成器文档语义独立构造转移(不复用 _state_chain)。

        s:1−p 保持,p 均匀重抽(3);c/g:1−p_hold 均匀重抽(2);
        q:pq 保持,否则 Q_FRESH_P 重抽(常量取模块真值,构造
        逻辑独立)。"""
        ms = ((1.0 - spec.s_switch_p) * np.eye(3)
              + spec.s_switch_p / 3.0)
        mc = (spec.c_hold_p * np.eye(2)
              + (1.0 - spec.c_hold_p) / 2.0)
        mq = (spec.q_hold_p * np.eye(5)
              + (1.0 - spec.q_hold_p)
              * np.broadcast_to(Q_FRESH_P, (5, 5)))
        mg = (spec.g_hold_p * np.eye(2)
              + (1.0 - spec.g_hold_p) / 2.0)
        return ms, mc, mq, mg

    def test_chain_is_row_stochastic_and_matches_independent(self):
        """行随机(行和=1,非负)且与独立构造逐分量一致
        (先前版本 q 行和<1、c/g 硬翻转——reviewer 反例回归)。"""
        for tier in TIERS:
            spec = spec_for(tier, seed=MS, horizon=8)
            table, trans = _state_chain(spec)
            assert np.allclose(trans.sum(axis=1), 1.0, atol=1e-15), \
                (tier, float(np.abs(trans.sum(axis=1) - 1).max()))
            assert (trans >= -1e-15).all(), tier
            ms, mc, mq, mg = self._independent_chain(spec)
            ref = np.kron(np.kron(np.kron(ms, mc), mq), mg)
            assert np.allclose(trans, ref, atol=1e-14), tier

    def test_chain_matches_generator_empirical_transitions(self):
        """终极语义证明:生成器真实 hidden 状态序列的经验转移频率
        = 转移矩阵(长 MC,4σ 容差;不依赖任何文档声明)。"""
        spec = spec_for("c4d2", seed=MS, horizon=48)
        table, _ = _state_chain(spec)
        svals = np.sort(np.unique(table[:, 0]))
        n = {k: np.zeros((m, m)) for k, m in (
            ("s", 3), ("c", 2), ("q", 5), ("g", 2))}
        for ep in range(60):
            _, _, h = generate_episode(spec, 9000 + ep)
            for comp, arr, vals in (
                    ("s", h["s"], svals),
                    ("c", h["c"], np.array([0.0, 1.0])),
                    ("q", h["q"], Q_LEVELS),
                    ("g", h["g"], np.array([0.0, 1.0]))):
                vi = {v: i for i, v in enumerate(vals)}
                a = arr[:-1]
                b = arr[1:]
                for x, y in zip(a, b):
                    n[comp][vi[x], vi[y]] += 1
        # 分量级模型(独立构造)与经验频率逐格 4σ 二项对照
        ms, mc, mq, mg = self._independent_chain(spec)
        for comp, mat in (("s", ms), ("c", mc), ("q", mq),
                          ("g", mg)):
            cnt = n[comp].sum(axis=1)
            for r in range(mat.shape[0]):
                for c2 in range(mat.shape[1]):
                    p = mat[r, c2]
                    m = int(cnt[r])
                    if m < 5 or p < 1e-6:
                        continue
                    sigma = math.sqrt(p * (1 - p) * m)
                    got = n[comp][r, c2]
                    assert abs(got - p * m) <= 4.0 * sigma + 0.5, (
                        comp, r, c2, got, p * m, m)

    def test_small_horizon_account_dynamics_parity(self):
        """h=6:测试侧**独立实现**的账户动力学后向归纳(自有网格/
        求积/插值 + 内联转移公式;与 reference_policy 无共享代码
        路径)在共同格点上与 DP 值一致(容差=两级收敛差量级)。

        R1 版"独立暴力"复制了错误的固定 w 递推(把 HOLD 当保持
        w 列)——不能叫独立证明;本版内联
        w_next=w(1+r)/(1+w·r) 与扣费后口径费用。"""
        spec = spec_for("c4d2", seed=MS, horizon=6,
                        mu_max=1.2e-3, sigma_lo=0.03, sigma_hi=0.06)
        pol = reference_policy(spec)      # 默认网格(321/64/40)
        table, _ = _state_chain(spec)
        ms, mc, mq, mg = self._independent_chain(spec)
        trans = np.kron(np.kron(np.kron(ms, mc), mq), mg)
        K = table.shape[0]
        mu = np.array([mu_eff_of(
            spec, table[j, 0:1], table[j, 1:2], table[j, 2:3])[0]
            for j in range(K)])
        sig = np.array([float(np.where(
            table[j, 3] == 1, spec.sigma_hi, spec.sigma_lo))
            for j in range(K)])
        fee = spec.fee
        # 自有网格:密集 [-3,3] 均匀 1501 点 + 强制平仓延伸 ±20
        g_in = np.linspace(-3.0, 3.0, 1501)
        g_ex = np.geomspace(3.0, 20.0, 24)
        grid = np.concatenate([-g_ex[::-1], g_in, g_ex])
        zidx = int(np.argmin(np.abs(grid)))
        xs, wq = np.polynomial.legendre.leggauss(60)
        wq = wq / 2.0
        A = len(W_GRID)

        def fee_frac(w, wt):
            if wt > w:
                return fee * abs((wt - w) / (1.0 + wt * fee))
            if wt < w:
                return fee * abs((wt - w) / (1.0 - wt * fee))
            return 0.0

        def cont(ev_row, w_pts):
            inside = np.abs(w_pts) <= 20.0
            out = np.empty_like(w_pts)
            out[inside] = np.interp(w_pts[inside], grid, ev_row)
            if (~inside).any():
                ext = np.where(
                    fee * np.abs(w_pts[~inside]) < 1.0,
                    np.log1p(-fee * np.abs(w_pts[~inside])), -np.inf)
                out[~inside] = ext + float(ev_row[zidx])
            return out

        V = np.tile(np.where(
            fee * np.abs(grid) < 1.0,
            np.log1p(-fee * np.abs(grid)), -np.inf), (K, 1))
        for _ in range(6):
            EV = trans @ V
            Vn = np.empty_like(V)
            for i in range(K):
                r_nodes = mu[i] + math.sqrt(3.0) * sig[i] * xs
                # HOLD
                gb = gbar(grid, mu[i], sig[i])
                finite = np.isfinite(gb)
                c_h = np.zeros_like(grid)
                for m in range(len(xs)):
                    r = float(r_nodes[m])
                    g = 1.0 + grid * r
                    wn = np.where(g > 0, grid * (1.0 + r)
                                  / np.where(g > 0, g, 1.0), 0.0)
                    c_h += wq[m] * cont(EV[i], wn)
                hv = np.where(finite, gb + c_h, -np.inf)
                # REBAL(动作网格;费用按当前格点 w 精确解)
                best = np.full_like(grid, -np.inf)
                for a in range(A):
                    wa = float(W_GRID[a])
                    f_col = np.array([fee_frac(float(grid[k]), wa)
                                      for k in range(len(grid))])
                    if f_col.max() >= 1.0:
                        f_col = np.where(f_col < 1.0, f_col, 1.0)
                    gn = 1.0 + wa * r_nodes
                    if np.any(gn <= 0.0):
                        continue
                    wn_a = wa * (1.0 + r_nodes) / gn
                    cont_a = float(np.dot(wq, cont(EV[i], wn_a)))
                    q = (np.log1p(-f_col) + float(gbar(
                        np.array(wa), mu[i], sig[i])) + cont_a)
                    best = np.maximum(best, q)
                Vn[i] = np.maximum(hv, best)
            V = Vn
        # 共同格点对照(DP 网格内的代表点;两级收敛差量级容差)
        for w_pt in (0.0, 0.25, 0.5, 1.0, -0.5, -1.0):
            k_in = int(np.argmin(np.abs(grid - w_pt)))
            i = 17
            got = float(np.interp(w_pt, pol["grid"],
                                  pol["values"][6][i]))
            exp = float(V[i, k_in])
            assert got == pytest.approx(exp, abs=3e-5), (
                w_pt, got, exp)

    def test_initial_value_matches_pathwise_simulation(self):
        """端到端:生成器真实 episode 上执行参考策略的路径平均
        总对数增长 ≈ DP initial_value(MC 4σ + 求解器收敛差;
        证明 DP 是**同一账户动力学**的期望,而非自洽假象)。"""
        from rl_posctl.curriculum import initial_value
        spec = spec_for("c4d0", seed=MS, horizon=16,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        pol = reference_policy(spec)
        exact = initial_value(spec)
        rng_tot = []
        n_eps = 400
        for ep in range(n_eps):
            prices, feats, _ = generate_episode(spec, 7000 + ep)
            env = HybridPositionEnv(
                features=feats, prices=prices, fee=spec.fee,
                window_size=1)
            env.reset()
            done = False
            while not done:
                t = env._current_tick
                row = feats.iloc[t]
                eq = env.ledger.equity(env._close[t])
                w_cur = (env.ledger.qty * env._close[t]
                         / eq if eq > 0 else 0.0)
                act = reference_action(
                    spec, row, w_cur, steps_left=env.n_rows - 1 - t)
                _, _, term, trunc, info = env.step(act)
                done = term or trunc
            s = summarize(env.step_records)
            rng_tot.append(s["net_log_return"]
                           if s["net_log_return_valid"] else -6.0)
        mean = float(np.mean(rng_tot))
        ci = 4.0 * float(np.std(rng_tot)) / math.sqrt(n_eps)
        # R2:容差 = MC 4σ + 求解器误差量级(旧 +0.02 > 最小声称
        # 优势 0.000428,不能证明动力学一致——reviewer F4)
        assert mean == pytest.approx(exact, abs=ci + 5e-4), (
            mean, exact, ci)

    def test_reference_beats_flat_on_train_face_qualified(self):
        """数值期望(初始分布加权 DP 值)− 收敛差 > 0 = 优于恒空仓
        且误差 < 优势(qualified;不虚称精确);抽样实现统计仅要求
        无失败且不明显劣于 flat(弱断言,避免噪声误判)。"""
        from rl_posctl.curriculum import (error_report, initial_value,
                                          tier_validity as _tv)
        spec = spec_for("c4d2", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        # R4-B:细化链最细级必须覆盖判定网格(321/64/40),
        # 且 tier_validity 消费完整报告对象(可复算绑定)。
        rep = error_report(spec, refinements=((81, 16, 12),
                                              (161, 32, 24),
                                              (321, 64, 40)))
        v = initial_value(spec)
        assert v > 0.0
        assert v - rep["err_bound"] > 0.0, (v, rep)
        st = _tv(spec, n_episodes=16, err_bound=rep)
        assert st["qualified"] is True
        assert st["n_failures"] == 0
        assert st["net_log"] > st["flat_net_log"] - 0.25

    def test_hold_is_real_action_candidate(self):
        """策略表非空出现 HOLD(保持 w 是真实动作候选)。"""
        spec = spec_for("c4d3", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        pol = reference_policy(spec)
        n_hold = int(sum(
            (p == -1).sum() for p in pol["policies"].values()))
        assert n_hold > 0


# ==================== C4 四档差异 ====================
class TestC4TierSeparation:
    def test_same_seed_bitwise_different(self):
        outs = {}
        for tier in TIERS:
            sp = spec_for(tier, seed=MS, horizon=32)
            p, f, _ = generate_episode(sp, 101)
            outs[tier] = (p.values.tobytes(), f.values.tobytes())
        for i in range(len(TIERS)):
            for j in range(i + 1, len(TIERS)):
                assert outs[TIERS[i]][0] != outs[TIERS[j]][0], \
                    f"{TIERS[i]} vs {TIERS[j]} 价格逐位相同"
                assert outs[TIERS[i]][1] != outs[TIERS[j]][1]

    def test_tier_params_actually_differ(self):
        vals = [tuple(sorted(TIER_OVERRIDES[t].items()))
                for t in TIERS]
        assert len(set(vals)) == len(TIERS)

    @pytest.mark.parametrize("tier", TIERS)
    def test_tier_capability_points(self, tier):
        """每档参考行为非空:非零敞口、内部仓位、HOLD 都出现;
        双侧方向;参考 ≥ flat。"""
        spec = spec_for(tier, seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        st = tier_validity(spec, n_episodes=16)
        assert st["steps"] > 0
        assert st["n_failures"] == 0
        assert st["interior"] > 0, f"{tier} 无内部仓位考点"
        assert st["hold"] > 0, f"{tier} 无 HOLD 考点"
        assert st["pos"] > 0 and st["neg"] > 0, \
            f"{tier} 缺多空双侧"
        from rl_posctl.curriculum import initial_value
        assert initial_value(spec) > 0.0, f"{tier} 参考期望不优于 flat"

    def test_d1_risk_sensitivity(self):
        """D1:同一 μ 边际下 hi-σ 的 kelly 敞口收缩。"""
        spec = spec_for("c4d1", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        mu = spec.mu_max * 0.75
        w_lo = kelly_w(mu, spec.sigma_lo)
        w_hi = kelly_w(mu, spec.sigma_hi)
        assert abs(w_hi) < abs(w_lo)

    def test_d2_has_flips_and_adjustments(self):
        spec = spec_for("c4d2", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        st = tier_validity(spec, n_episodes=24)
        assert st["flips"] > 0
        assert st["rebal"] > 0


# ==================== C1–C3 能力(双向适配) ====================
class TestC123Capabilities:
    def test_c1_mu_ignores_context_and_quality(self):
        """C1 无门控:μ_eff 只依赖 s(镜像边=做空真实性的结构前提);
        bar 收益 = μ_eff + a·U 且 |U|≤1(支撑内)。"""
        spec = spec_for("c1", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        p, f, h = generate_episode(spec, 5)
        # hidden v2 语义:mu_eff[t]/sigma[t] 驱动 bar t 收益(=t−1 状态)
        mu = h["mu_eff"][1:]
        sig = h["sigma"][1:]
        for c_val in (0.0, 1.0):
            for q_val in (0.0, 0.5, 1.0):
                mu2 = mu_eff_of(spec, np.array([1.0]),
                                np.array([c_val]), np.array([q_val]))
                assert mu2[0] == pytest.approx(spec.mu_max)
        r = p["close"].to_numpy()[1:] / p["close"].to_numpy()[:-1] - 1
        a = np.sqrt(3.0) * sig
        u = (r - mu) / a
        assert np.all(np.abs(u) <= 1.0 + 1e-12)

    def test_c2_context_gate_changes_optimal_action(self):
        """C2:同 s,不同 c ⇒ 最优目标不同(门控真实)。"""
        spec = spec_for("c2", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        row_c1 = {"s": 1.0, "c": 1.0, "q": 1.0, "g": 0.0}
        row_c0 = {"s": 1.0, "c": 0.0, "q": 1.0, "g": 0.0}
        a1 = reference_action(spec, row_c1, 0.0, steps_left=32)
        a0 = reference_action(spec, row_c0, 0.0, steps_left=32)
        assert a1[1] > 0
        assert a0[1] == 0.0    # c=0 门关:不建仓/清仓

    def test_c3_fee_skipping(self):
        """C3 弱边际:零质量下参考不建仓(费用主导)。"""
        spec = spec_for("c3", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        row_lo = {"s": 1.0, "c": 1.0, "q": 0.0, "g": 0.0}
        a = reference_action(spec, row_lo, 0.0, steps_left=32)
        assert a[1] == 0.0 or a[0] == 0


    def _account_policy_value(self, spec, act_fn):
        """固定策略的数值期望值(账户动力学;测试侧独立评估器,
        与 reference_policy 无共享代码路径)。act_fn(i,w,sl)->w
        动作索引(-1=HOLD;w=评估器格点实际值)。初始分布与生成器一致
        (s/c/g 均匀,q~Q_FRESH_P)。R2:旧 _exact_policy_value 沿用
        固定 w 递推(reviewer F4),已废。"""
        table, trans = _state_chain(spec)
        K = table.shape[0]
        mu = np.array([mu_eff_of(
            spec, table[j, 0:1], table[j, 1:2], table[j, 2:3])[0]
            for j in range(K)])
        # σ 语义与 sigma_of 一致:仅 sigma_regime=True 时随 g 切换
        # (旧实现忽略 sigma_regime,对 c1/c2/c3 误用 σ_hi——已修)
        sig = np.where(
            spec.sigma_regime & (table[:, 3] == 1),
            spec.sigma_hi, spec.sigma_lo)
        fee = spec.fee
        g_in = np.linspace(-3.0, 3.0, 1201)
        g_ex = np.geomspace(3.0, 20.0, 20)
        grid = np.concatenate([-g_ex[::-1], g_in, g_ex])
        zidx = int(np.argmin(np.abs(grid)))
        xs, wq = np.polynomial.legendre.leggauss(48)
        wq = wq / 2.0
        A = len(W_GRID)

        def fee_frac(w, wt):
            if wt > w:
                return fee * abs((wt - w) / (1.0 + wt * fee))
            if wt < w:
                return fee * abs((wt - w) / (1.0 - wt * fee))
            return 0.0

        fmat = np.array([[fee_frac(float(grid[k]), float(W_GRID[a]))
                          for k in range(len(grid))]
                         for a in range(A)])          # (A, nW)

        def cont(ev_row, w_pts):
            inside = np.abs(w_pts) <= 20.0
            out = np.empty_like(w_pts)
            out[inside] = np.interp(w_pts[inside], grid, ev_row)
            if (~inside).any():
                ext = np.where(
                    fee * np.abs(w_pts[~inside]) < 1.0,
                    np.log1p(-fee * np.abs(w_pts[~inside])), -np.inf)
                out[~inside] = ext + float(ev_row[zidx])
            return out

        G_act = np.array([[float(gbar(np.array(W_GRID[a]), mu[i],
                                      sig[i])) for a in range(A)]
                          for i in range(K)])
        G_hold = np.array([[float(gbar(np.array(grid[k]), mu[i],
                                       sig[i]))
                            for k in range(len(grid))]
                           for i in range(K)])
        V = np.tile(np.where(
            fee * np.abs(grid) < 1.0,
            np.log1p(-fee * np.abs(grid)), -np.inf), (K, 1))
        for sl in range(1, spec.horizon + 1):
            EV = trans @ V
            Vn = np.empty_like(V)
            for i in range(K):
                r_nodes = mu[i] + math.sqrt(3.0) * sig[i] * xs
                hold_cont = np.zeros_like(grid)
                rebal_cont = np.zeros(A)
                for m in range(len(xs)):
                    r = float(r_nodes[m])
                    g = 1.0 + grid * r
                    wn = np.where(g > 0, grid * (1.0 + r)
                                  / np.where(g > 0, g, 1.0), 0.0)
                    hold_cont += wq[m] * cont(EV[i], wn)
                    ga = 1.0 + W_GRID * r
                    wn_a = W_GRID * (1.0 + r) / ga
                    rebal_cont += wq[m] * cont(EV[i], wn_a)
                hv = np.where(np.isfinite(G_hold[i]),
                              G_hold[i] + hold_cont, -np.inf)
                q_rebal = (np.log1p(-fmat.T) + G_act[i][None, :]
                           + rebal_cont[None, :])   # (nW, A)
                a_idx = np.array([act_fn(i, float(grid[k]), sl)
                                  for k in range(len(grid))])
                pick_hold = a_idx < 0
                # 按策略**选定**的动作取值(不是 max over actions——
                # 那会把任意策略都评估成最优值)
                safe_a = np.where(pick_hold, 0, a_idx)
                chosen = q_rebal[np.arange(len(grid)), safe_a]
                Vn[i] = np.where(pick_hold, hv, chosen)
            V = Vn
        pi = np.empty(K)
        for i in range(K):
            pi[i] = (1 / 3.0) * 0.5 * Q_FRESH_P[
                int(np.argmin(np.abs(Q_LEVELS - table[i, 2])))] * 0.5
        return float(pi @ V[:, zidx])

    def test_reference_beats_local_only_on_c2(self):
        """同账户动力学评估器(无抽样噪声;两策略共用网格/求积,
        差值不受求解器共模误差影响):参考 > local_only。R2:旧版
        用固定 w 评估器对照固定 w DP(错误递推的自洽对照)。"""
        spec = spec_for("c2", seed=MS, horizon=16,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        pol = reference_policy(spec)

        # 评估器格点 ≠ DP 格点:把 DP 策略表按 w 最近邻映射到评估器
        # 格点(纯查表,零 reference_action 逐点调用)
        dp_grid = pol["grid"]
        dp_pol = pol["policies"]
        acts = {-1: -1}
        for a in range(len(W_GRID)):
            acts[int(np.argmin(np.abs(W_GRID - W_GRID[a])))] = a

        def ref_act(i, w, sl):
            k = int(np.argmin(np.abs(dp_grid - w)))
            return int(dp_pol[sl][i, k])

        def local_act(i, w, sl):
            sv = pol["table"][i, 0]
            wl = float(np.clip(sv, -1.0, 1.0))
            return int(np.argmin(np.abs(W_GRID - wl)))

        v_ref = self._account_policy_value(spec, ref_act)
        v_loc = self._account_policy_value(spec, local_act)
        # DP 最优策略 ≥ 局部信号基线;容差 = 求解器收敛差量级
        # (网格映射误差;不设宽容差掩盖真实劣势)
        assert v_ref > v_loc - 1e-5, (v_ref, v_loc)


# ==================== 生成器因果性与分区隔离 ====================
class TestGeneratorCausality:
    def test_return_depends_on_prior_state_only(self):
        spec = spec_for("c4d1", seed=MS, horizon=32)
        p, f, h = generate_episode(spec, 77)
        mu = h["mu_eff"][1:]      # v2:hidden.mu_eff[t] 驱动 bar t
        a = np.sqrt(3.0) * h["sigma"][1:]
        r = p["close"].to_numpy()[1:] / p["close"].to_numpy()[:-1] - 1
        u = (r - mu) / a
        assert np.all(np.abs(u) <= 1.0 + 1e-12)

    def test_features_contain_no_future(self):
        """截断 horizon 只影响后续 bar,前缀逐位一致(无未来泄漏)。"""
        sp32 = spec_for("c4d0", seed=MS, horizon=32)
        sp16 = spec_for("c4d0", seed=MS, horizon=16)
        p32, f32, _ = generate_episode(sp32, 55)
        p16, f16, _ = generate_episode(sp16, 55)
        assert np.allclose(p16["close"].to_numpy(),
                           p32["close"].to_numpy()[:17])
        assert np.allclose(f16.to_numpy(), f32.to_numpy()[:17])

    def test_domain_seed_isolation(self):
        ds = {d: domain_seed(MS, d) for d in ("train", "dev", "eval")}
        assert len(set(ds.values())) == 3
        seeds = [episode_seed(ds["train"], i) for i in range(50)]
        assert len(set(seeds)) == 50
        dev = [episode_seed(ds["dev"], i) for i in range(50)]
        assert not set(seeds) & set(dev)

    def test_same_seed_reproducible(self):
        sp = spec_for("c4d2", seed=MS, horizon=32)
        p1, f1, _ = generate_episode(sp, 42)
        p2, f2, _ = generate_episode(sp, 42)
        assert p1.equals(p2) and f1.equals(f2)


# ==================== 参考费用口径对拍(v3 精确费用) ====================
class TestReferenceCostExactness:
    def test_exact_fee_model_vs_real_ledger_replay(self):
        """v3 参考的扣费后口径费用(与账本同解)vs 真实账本回放:
        滑点/tick=0 面**逐位一致**(旧 v2 线性 fee·|Δw| 是披露近似,
        rel=0.25;v3 精确后收紧到机器精度;风险腿同式计入)。"""
        from rl_posctl.curriculum import rebal_fee_fraction
        spec = spec_for("c4d2", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        env = make_env(spec, 31337)
        obs, _ = env.reset()
        n_risk = 0
        assumed = 0.0          # DP 费用模型(log 量纲:Σ −ln(1−f))
        real_log_fee = 0.0     # 真实账本费用折 log
        while True:
            t = env._current_tick
            row = env._feature_row(t)
            eq = env.ledger.equity(env._close[t])
            ratio = (env.ledger.exposure_ratio(env._close[t])
                     if eq > 0 else 0.0)
            act = reference_action(spec, row, ratio,
                                   steps_left=env.n_rows - 1 - t)
            if act[0] == 1:
                assumed -= math.log1p(-rebal_fee_fraction(
                    float(ratio), float(act[1]), spec.fee))
            o, r, term, trunc, info = env.step(act)
            rec = env.step_records[-1]
            fee_i = rec.get("fee") or 0.0
            if fee_i:
                real_log_fee -= math.log1p(
                    -fee_i / rec["equity_start"])
            ra = rec.get("risk_action")
            if isinstance(ra, dict) and ra.get("fee"):
                n_risk += 1
                # 风险腿费用按账本原值对账(与 DP 强制平仓模型同式
                # fee·|w|;本 seed 下预期无风险事件,断言见下)
            if term or trunc:
                break
        # 终端清算腿(真实账本必平仓;DP 终值同含 log(1−fee·|w|))
        tl = rec.get("terminal_liquidation")
        if isinstance(tl, dict) and tl.get("fee"):
            assumed -= math.log1p(-tl["fee"] / rec["equity_start"])
        assert n_risk == 0, "本 seed 预期无风险腿(如有请换对拍口径"
        assert real_log_fee == pytest.approx(assumed, rel=1e-6,
                                             abs=1e-9), (
            real_log_fee, assumed, n_risk)
