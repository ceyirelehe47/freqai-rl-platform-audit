# -*- coding: utf-8 -*-
"""课程有效性测试(W3):在看任何学习结果之前固定。

覆盖:
- C4 核心:存在状态使内部仓位期望对数增长严格优于 0 与 ±1;
  存在状态 HOLD 优于小幅再平衡(费用主导);存在状态调整优于
  HOLD(机会变化主导)——全部由已知参数数值积分证明,不用未来
  完美动作;
- C1 空头边真实且不因做空出捷径(local_only 忽略信号显著差于
  参考;镜像质量配对);
- C2 同信号跨上下文最优动作不同(local-only 被门控击败);
- C3 参考跳过低于费用的边际(always_retarget 多付费用);
- 生成器因果性:特征不含未来;bar k 收益只依赖决策 k−1 状态;
- 分区隔离:train/dev/eval 种子域不相交,同 seed 完全可复现。
"""

import math

import numpy as np
import pytest

from rl_posctl.curriculum import (
    CourseSpec,
    baseline_policies,
    expected_log_growth,
    generate_episode,
    kelly_w,
    reference_action,
)
from rl_posctl.banks import domain_seed, episode_seed
from rl_posctl.env import HybridPositionEnv
from rl_posctl.evalreport import run_policy, summarize


def make_env(spec, seed):
    prices, feats, _ = generate_episode(spec, seed)
    return HybridPositionEnv(
        features=feats, prices=prices, fee=spec.fee,
        slippage_bps=spec.slippage_bps, initial_cash=spec.initial_cash,
        window_size=1)


def ref_fn(spec):
    def fn(row, w):
        return reference_action(spec, row, w)
    return fn


# ==================== C4 有效性(事前解析/数值) ====================
class TestC4Validity:
    def test_interior_beats_endpoints_and_flat(self):
        """μ=0.003,σ=0.10:μ/σ²≈0.3,Kelly 内点严格优于 0/±1
        (费用的纯期望对数增长;手算数值积分)。"""
        mu, sigma = 0.003, 0.10
        w_star = kelly_w(mu, sigma)
        assert 0.0 < w_star < 1.0, w_star
        v_star = expected_log_growth(w_star, mu, sigma)
        for other in (0.0, 1.0, -1.0, 0.5 * w_star):
            assert v_star > expected_log_growth(other, mu, sigma), other

    def test_hold_beats_small_rebalance_when_cost_dominates(self):
        """已持有小仓 w=0.02,边际 μ=0:清仓费(2e-5)大于持有
        方差拖累((0.02·0.1)²/2=1e-6) -> HOLD 严格更优。"""
        spec = CourseSpec(course="c4d3", fee=0.001)
        row = {"s": 0.0, "c": 1.0, "q_step": 0.0, "g": 0.0}
        act = reference_action(spec, row, current_w=0.02)
        assert act == (0, 0.0)                 # HOLD

    def test_adjust_beats_hold_when_opportunity_shifts(self):
        """w≈0 时出现高质量机会:再平衡严格优于 HOLD。"""
        spec = CourseSpec(course="c4d3", fee=0.001)
        row = {"s": 1.0, "c": 1.0, "q_step": 1.0, "g": 0.0}
        act = reference_action(spec, row, current_w=0.0)
        assert act[0] == 1 and act[1] > 0.1

    def test_risk_regime_reduces_exposure(self):
        """D1:同 μ,σ 高 regime 参考敞口更低(风险敏感配置)。"""
        spec = CourseSpec(course="c4d1")
        row_lo = {"s": 1.0, "c": 1.0, "q_step": 1.0, "g": 0.0}
        row_hi = {"s": 1.0, "c": 1.0, "q_step": 1.0, "g": 1.0}
        w_lo = reference_action(spec, row_lo, 0.0)
        w_hi = reference_action(spec, row_hi, 0.0)
        assert w_lo[1] > w_hi[1] > 0.0

    def test_reference_uses_no_future(self):
        """参考只依赖特征行与当前比例(签名即合同;间接由生成器
        因果测试保证特征本身无未来)。"""
        spec = CourseSpec(course="c4d2")
        row = {"s": 1.0, "c": 1.0, "q_step": 0.75, "g": 1.0}
        a1 = reference_action(spec, row, 0.3)
        a2 = reference_action(spec, row, 0.3)
        assert a1 == a2                          # 确定性


# ==================== 生成器因果性 ====================
class TestGeneratorCausality:
    def test_return_depends_on_prior_signal_only(self):
        """bar k 收益的均值由 features[k−1] 决定:给定特征序列,
        未来收益均值与 features[k] 无关(大样本均值检验)。"""
        spec = CourseSpec(course="c1", mu_max=0.02,
                          sigma_lo=0.001, sigma_hi=0.001,
                          hold_p=0.999, signal_switch_p=0.0,
                          horizon=2, seed=5)
        # 每条 3 bar:bar1 收益取决于 s[0];统计两种 s[0] 的均值
        rets = {"p": [], "m": [], "z": []}
        for ep in range(4000):
            prices, feats, _ = generate_episode(
                spec, 1000 + ep)
            r1 = float(np.log(prices["close"][1] / prices["open"][1]))
            key = {1.0: "p", -1.0: "m", 0.0: "z"}[float(feats["s"][0])]
            rets[key].append(r1)
        mp = float(np.mean(rets["p"]))
        mm = float(np.mean(rets["m"]))
        mz = float(np.mean(rets["z"]))
        assert mp == pytest.approx(0.02, abs=0.004), mp
        assert mm == pytest.approx(-0.02, abs=0.004), mm
        assert mz == pytest.approx(0.0, abs=0.004), mz

    def test_features_contain_no_future_columns(self):
        spec = CourseSpec(course="c4d0", horizon=8)
        prices, feats, hidden = generate_episode(spec, 42)
        for col in feats.columns:
            assert col in ("s", "c", "q", "g", "q_step")
        assert set(hidden) >= {"mu_eff", "sigma"}   # 隐藏面只留在 hidden

    def test_same_seed_reproducible(self):
        spec = CourseSpec(course="c2", horizon=16)
        a = generate_episode(spec, 77)
        b = generate_episode(spec, 77)
        assert np.allclose(a[0].to_numpy(), b[0].to_numpy())
        assert np.allclose(a[1].to_numpy(), b[1].to_numpy())

    def test_domain_seeds_disjoint(self):
        tr = {episode_seed(domain_seed(11, "train"), i)
              for i in range(50)}
        dv = {episode_seed(domain_seed(11, "dev"), i)
              for i in range(50)}
        ev = {episode_seed(domain_seed(11, "eval"), i)
              for i in range(50)}
        assert not (tr & dv) and not (tr & ev) and not (dv & ev)


# ==================== 课程参考 vs 失败对照(无梯度评估) ====================
class TestReferenceVsBaselines:
    N_EP = 30

    SPEC_OVERRIDES = {
        # C4 有效性面:提高信噪比使"参考 > 永远空仓"在测试规模内
        # 显著(事前固定;不用于学习结果解释)
        "c4d0": dict(mu_max=0.03, sigma_lo=0.15, sigma_hi=0.22),
    }

    def eval_suite(self, course, master=99, n_ep=None):
        spec = CourseSpec(course=course, seed=master,
                          **self.SPEC_OVERRIDES.get(course, {}))
        n = n_ep or self.N_EP
        results = {}
        policies = {"reference": ref_fn(spec)}
        policies.update(baseline_policies())
        for name, fn in policies.items():
            logs = []
            fails = 0
            for i in range(n):
                env = make_env(spec, episode_seed(
                    domain_seed(master, "eval"), i))
                infos = run_policy(env, fn)
                s = summarize(infos)
                logs.append(s["net_log_return"])
                fails += int(s["economic_failure"])
            results[name] = (float(np.mean(logs)), fails)
        return results

    def test_c1_reference_beats_local_only_and_flat(self):
        r = self.eval_suite("c1")
        ref = r["reference"][0]
        assert ref > r["local_only"][0], r
        assert ref > r["flat"][0], r
        # 恒定方向仓被方差拖累压垮(参考只在其优势状态持有)
        assert ref > r["long_half"][0], r
        assert ref > r["short_half"][0], r

    def test_c2_context_gating(self):
        r = self.eval_suite("c2")
        # local_only 忽略上下文门,在同强度正负信号下被门控击败
        assert r["reference"][0] > r["local_only"][0] + 0.01, r

    def test_c3_cost_sensitivity(self):
        spec = CourseSpec(course="c3", seed=99)
        r = self.eval_suite("c3")
        # 参考平均费用 <= 恒定半仓再平衡的变体(成本感知)
        # (费用绝对值经由 env 记录;此处比较净收益即可)
        assert r["reference"][0] > r["always_retarget_half"][0], r

    def test_c4_reference_positive_edge(self):
        r = self.eval_suite("c4d0", n_ep=60)
        assert r["reference"][0] > r["flat"][0], r
        assert r["reference"][0] > r["binary_sign"][0], r

    def test_no_economic_failures_for_reference(self):
        for course in ("c1", "c2", "c3", "c4d0"):
            r = self.eval_suite(course, n_ep=10)
            assert r["reference"][1] == 0, (course, r["reference"])
