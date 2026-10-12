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

    def test_small_horizon_bruteforce_parity(self):
        """h=6:独立实现的逐步后向(独立构造的转移 + 显式 k/a
        循环,与 reference_policy 无共享代码路径)逐值一致。"""
        spec = spec_for("c4d2", seed=MS, horizon=6,
                        mu_max=1.2e-3, sigma_lo=0.03, sigma_hi=0.06)
        pol = reference_policy(spec)
        table, _ = _state_chain(spec)
        ms, mc, mq, mg = self._independent_chain(spec)
        trans = np.kron(np.kron(np.kron(ms, mc), mq), mg)
        K = table.shape[0]
        G = np.array([gbar(W_GRID, mu_eff_of(
            spec, table[j, 0:1], table[j, 1:2], table[j, 2:3])[0],
            float(np.where(table[j, 3] == 1, spec.sigma_hi,
                           spec.sigma_lo))) for j in range(K)])
        fee = spec.fee
        W = len(W_GRID)
        V = -fee * np.abs(W_GRID)[None, :].repeat(K, 0)
        for _ in range(6):
            EV = trans @ V
            newV = np.empty((K, W))
            for k in range(W):
                hold = G[:, k] + EV[:, k]
                rebal = np.stack([G[:, a] + EV[:, a]
                                  - fee * abs(W_GRID[a] - W_GRID[k])
                                  for a in range(W)]).max(axis=0)
                newV[:, k] = np.maximum(hold, rebal)
            V = newV
        v_dp = pol["values"][6]
        assert np.allclose(V, v_dp, atol=1e-12), \
            float(np.abs(V - v_dp).max())

    def test_initial_value_matches_pathwise_simulation(self):
        """端到端:生成器真实 episode 上执行参考策略的路径平均
        总对数增长 ≈ DP initial_value(MC 4σ;证明 DP 是该 MDP 的
        精确期望,而非自洽假象)。"""
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
        assert mean == pytest.approx(exact, abs=ci + 0.02), (
            mean, exact, ci)

    def test_reference_beats_flat_on_train_face_exact(self):
        """精确期望(初始分布加权 DP 值)> 0 = 恒空仓;抽样实现
        统计仅要求无失败且不明显劣于 flat(弱断言,避免噪声误判)。"""
        from rl_posctl.curriculum import initial_value
        spec = spec_for("c4d2", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        assert initial_value(spec) > 0.0
        st = tier_validity(spec, n_episodes=16)
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


    def _exact_policy_value(self, spec, act_fn):
        """固定策略的精确期望值(测试侧独立评估器,与
        reference_policy 无共享路径)。act_fn(i,k,sl)->w 索引
        (-1=HOLD 保持 k)。初始分布与生成器一致(s/c/g 均匀,
        q~Q_FRESH_P)。"""
        table, trans = _state_chain(spec)
        K = table.shape[0]
        W = len(W_GRID)
        G = np.array([gbar(W_GRID, mu_eff_of(
            spec, table[j, 0:1], table[j, 1:2], table[j, 2:3])[0],
            float(np.where(table[j, 3] == 1, spec.sigma_hi,
                           spec.sigma_lo))) for j in range(K)])
        fee = spec.fee
        V = -fee * np.abs(W_GRID)[None, :].repeat(K, 0)
        for sl in range(1, spec.horizon + 1):
            EV = trans @ V
            Vn = np.empty((K, W))
            for i in range(K):
                for k in range(W):
                    a = act_fn(i, k, sl)
                    if a == -1:
                        Vn[i, k] = G[i, k] + EV[i, k]
                    else:
                        Vn[i, k] = (G[i, a] + EV[i, a]
                                    - fee * abs(W_GRID[a] - W_GRID[k]))
            V = Vn
        w0 = int(np.argmin(np.abs(W_GRID)))
        pi = np.empty(K)
        for i in range(K):
            pi[i] = (1 / 3.0) * 0.5 * Q_FRESH_P[
                int(np.argmin(np.abs(Q_LEVELS - table[i, 2])))] * 0.5
        return float(pi @ V[:, w0])

    def test_reference_beats_local_only_on_c2(self):
        """精确期望层断言(DP 固定策略评估,无抽样噪声):
        参考 > local_only;抽样层只保留稳定性弱断言。"""
        spec = spec_for("c2", seed=MS, horizon=32,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        pol = reference_policy(spec)

        def ref_act(i, k, sl):
            return int(pol["policies"][sl][i, k])

        def local_act(i, k, sl):
            sv = pol["table"][i, 0]
            w = float(np.clip(sv, -1.0, 1.0))
            return int(np.argmin(np.abs(W_GRID - w)))

        v_ref = self._exact_policy_value(spec, ref_act)
        v_loc = self._exact_policy_value(spec, local_act)
        assert v_ref > v_loc, (v_ref, v_loc)


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


# ==================== 参考费用近似对拍(披露义务) ====================
class TestReferenceCostApproximation:
    def test_linear_fee_model_vs_real_ledger_replay(self):
        """DP 的 fee·|Δw| 线性费用模型 vs 真实账本回放(滑点/tick=0
        面一致;偏差披露,不虚称精确)。"""
        spec = spec_for("c4d2", seed=MS, horizon=64,
                        **profiles.TRAIN_SPEC_OVERRIDES)
        env = make_env(spec, 31337)
        actions = []
        obs, _ = env.reset()
        while True:
            t = env._current_tick
            row = env._feature_row(t)
            eq = env.ledger.equity(env._close[t])
            ratio = (env.ledger.exposure_ratio(env._close[t])
                     if eq > 0 else 0.0)
            act = reference_action(spec, row, ratio,
                                   steps_left=env.n_rows - 1 - t)
            actions.append([float(act[0]), float(act[1]),
                            float(ratio)])
            o, r, term, trunc, info = env.step(act)
            if term or trunc:
                break
        assumed = 0.0          # DP 费用模型(log 收益量纲:fee·|Δw|)
        real_log_fee = 0.0     # 真实账本费用折 log:Σ −ln(1−fee/E₀)
        # DP 口径:费用 = fee·|目标 w − 当前实际敞口比|(当前比随
        # 净值漂移;用事前 ratio,与 V 的 (k→a) 转移一致)
        prev_ratio = 0.0
        for k_rec, (branch, w, ratio_now) in enumerate(actions):
            rec = env.step_records[k_rec]
            if branch == 1:
                assumed += spec.fee * abs(w - ratio_now)
            fee_i = rec.get("fee") or 0.0
            if fee_i:
                real_log_fee += -math.log1p(-fee_i / rec["equity_start"])
            prev_ratio = ratio_now
        # 终端清算腿(真实账本必平仓;DP 终值同含 fee·|w|)
        assumed += spec.fee * abs(prev_ratio)
        # 线性费用模型 vs 真实账本(滑点/tick=0 面):log 量纲一致;
        # 偏差来自扣费后净值求解与权益漂移(披露口径,不虚称精确)
        assert real_log_fee == pytest.approx(assumed, rel=0.25,
                                             abs=1e-9)
