# -*- coding: utf-8 -*-
"""W2 混合动作概率正确性(POLICY_AND_LEARNING §2)——手算期望。

期望值全部由本文显式公式/math 标准库独立计算,不调用被验实现
生成期望。数值容限事前固定(1e-6),不得改 tol 救结果。
"""

import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch as th

from rl_posctl.env import HybridPositionEnv
from rl_posctl.policy import (
    HybridAtomBetaDistribution,
    HybridActorCriticPolicy,
    N_DIST_PARAMS,
    POSCTL_HEADER_KEY,
    attach_obs_dim,
    load_posctl_model,
    make_posctl_ppo,
    save_posctl_model,
    split_dist_params,
)

INV_SOFTPLUS_EPS = 1e-6


def inv_softplus(y: float) -> float:
    """softplus^{-1}(y),y>0(测试常数,独立实现)。"""
    return math.log(math.expm1(y))


ALPHA_FLOOR = 1.0   # v2:α=softplus(raw)+1.0(与实现一致)


def make_dist(branch_p=(0.3, 0.7), mix=(0.1, 0.2, 0.3, 0.4),
              alpha=2.0):
    bl = th.tensor([math.log(branch_p[0]), math.log(branch_p[1])],
                   dtype=th.float64, requires_grad=True)
    ml = th.tensor([math.log(m) for m in mix], dtype=th.float64,
                   requires_grad=True)
    ar = th.tensor([inv_softplus(alpha - ALPHA_FLOOR)],
                   dtype=th.float64,
                   requires_grad=True)
    return (HybridAtomBetaDistribution(bl, ml, ar),
            {"bl": bl, "ml": ml, "ar": ar})


def _expand(x, n=1):
    return x if x.shape[0] == n else x.expand(n, *x.shape)


# ==================== 手算 log-prob ====================
class TestHandComputedLogProb:
    def test_hold_logprob_pure(self):
        d, _ = make_dist()
        lp = d.log_prob(th.tensor([[0.0, 0.0]]))
        assert float(lp[0]) == pytest.approx(math.log(0.3), abs=1e-6)

    def test_atoms(self):
        d, _ = make_dist()
        for w, m in ((-1.0, 0.1), (0.0, 0.2), (1.0, 0.3)):
            lp = d.log_prob(th.tensor([[1.0, w]]))
            want = math.log(0.7) + math.log(m)
            assert float(lp[0]) == pytest.approx(want, abs=1e-6), w

    def test_continuous(self):
        d, _ = make_dist(alpha=2.0)
        w = 0.5
        u = (w + 1) / 2                       # 0.75
        beta_pdf = 6.0 * u * (1 - u)          # Beta(2,2) pdf 手算
        want = (math.log(0.7) + math.log(0.4)
                + math.log(beta_pdf) - math.log(2.0))
        lp = d.log_prob(th.tensor([[1.0, w]]))
        assert float(lp[0]) == pytest.approx(want, abs=1e-6)

    def test_batch_mix_shapes(self):
        d, _ = make_dist()
        acts = th.tensor([[0.0, 0.0], [1.0, -1.0], [1.0, 0.3],
                          [1.0, 0.0], [1.0, 1.0]])
        lp = d.log_prob(acts)
        assert lp.shape == (5,)
        assert bool(th.isfinite(lp).all())

    def test_illegal_branch_rejected(self):
        d, _ = make_dist()
        with pytest.raises(ValueError):
            d.log_prob(th.tensor([[0.5, 0.0]]))


# ==================== 熵:广义公式手算 ====================
class TestEntropyHandComputed:
    def test_entropy_exact(self):
        d, _ = make_dist()
        mix = [0.1, 0.2, 0.3, 0.4]
        h_branch = -(0.3 * math.log(0.3) + 0.7 * math.log(0.7))
        h_disc = -sum(m * math.log(m) for m in mix)
        a = 2.0
        lnB = 2 * math.lgamma(a) - math.lgamma(2 * a)
        dga = float(th.digamma(th.tensor(a)))
        dg2a = float(th.digamma(th.tensor(2 * a)))
        h_beta = (lnB - 2 * (a - 1) * dga
                  + (2 * a - 2) * dg2a)
        h_target = h_disc + 0.4 * (h_beta + math.log(2.0))
        want = h_branch + 0.7 * h_target
        got = d.entropy()
        assert float(got[0]) == pytest.approx(want, abs=1e-6)


# ==================== PPO 比值与梯度掩码 ====================
class TestRatioAndGradients:
    def test_ppo_ratio_manual(self):
        d1, _ = make_dist(branch_p=(0.3, 0.7))
        d2, _ = make_dist(branch_p=(0.5, 0.5), mix=(0.25, 0.25,
                                                    0.25, 0.25))
        a = th.tensor([[1.0, 0.5]])
        ratio = th.exp(d2.log_prob(a) - d1.log_prob(a))
        u = 0.75
        beta_pdf = 6.0 * u * (1 - u)
        lp1 = (math.log(0.7) + math.log(0.4)
               + math.log(beta_pdf) - math.log(2.0))
        lp2 = (math.log(0.5) + math.log(0.25)
               + math.log(beta_pdf) - math.log(2.0))
        assert float(ratio[0]) == pytest.approx(
            math.exp(lp2 - lp1), rel=1e-5)

    def test_hold_zero_target_gradient(self):
        """HOLD 样本:目标头不得获得任何似然梯度。"""
        d, p = make_dist()
        lp = d.log_prob(th.tensor([[0.0, 0.0]]))
        lp.backward()
        assert float(p["ml"].grad.abs().sum()) == 0.0
        assert float(p["ar"].grad.abs().sum()) == 0.0
        assert float(p["bl"].grad.abs().sum()) > 0.0

    def test_rebalance_atom_gradient_mask(self):
        """REBALANCE(执行值 0):被选合并原子质量得梯度,其余 mix
        分量按 softmax 结构 −m_j;连续头似然梯度仅经 0 单元质量
        b0(≈pdf·2^-150,数值上 ≈0 但非精确 0——这是执行映射的
        精确性质,不是泄漏)。"""
        d, p = make_dist()
        lp = d.log_prob(th.tensor([[1.0, 0.0]]))
        lp.backward()
        g = p["ml"].grad                     # shape (4,)
        m = [0.1, 0.2, 0.3, 0.4]
        assert float(g[1]) == pytest.approx(1.0 - m[1], abs=1e-9)
        for j in (0, 2, 3):
            assert float(g[j]) == pytest.approx(-m[j], abs=1e-9)
        # b0 = pdf_u(0.5)·2^-150 ⇒ alpha 依赖 ~1e-45:可忽略但非 0
        assert float(p["ar"].grad.abs().sum()) < 1e-30

    def test_rebalance_continuous_alpha_gradient(self):
        d, p = make_dist()
        lp = d.log_prob(th.tensor([[1.0, 0.5]]))
        lp.backward()
        assert float(p["ar"].grad.abs().sum()) > 0.0
        assert float(p["ml"].grad[3]) != 0.0

    def test_entropy_gradient_on_target_head_even_for_hold_obs(self):
        """熵是分布级期望:HOLD 动作的样本,熵对目标头仍有梯度
        (经 p_rebal 加权);不得声称 HOLD 使全部参数零梯度。"""
        d, p = make_dist()
        ent = d.entropy().sum()
        ent.backward()
        assert float(p["ml"].grad.abs().sum()) > 0.0
        assert float(p["ar"].grad.abs().sum()) > 0.0

    def test_extreme_params_no_nan(self):
        for branch_p in ((0.001, 0.999), (0.999, 0.001)):
            for mix in ((0.98, 0.01, 0.005, 0.005),
                        (0.002, 0.002, 0.002, 0.994)):
                for alpha in (1.0001, 50.0):   # v2:α∈(1,∞)
                    d, _ = make_dist(branch_p, mix, alpha)
                    acts = th.tensor([[0.0, 0.0], [1.0, -1.0],
                                      [1.0, 0.0], [1.0, 1.0],
                                      [1.0, 0.5], [1.0, -0.9999999],
                                      [1.0, 0.9999999]])
                    lp = d.log_prob(acts)
                    assert bool(th.isfinite(lp).all()), (
                        branch_p, mix, alpha)
                    assert bool(th.isfinite(d.entropy()).all())


# ==================== 采样/确定性解码一致性 ====================
class TestSamplingDecode:
    def test_sample_shape_and_validity(self):
        d, _ = make_dist()
        th.manual_seed(0)
        a = d.sample()
        assert a.shape == (1, 2)
        assert float(a[0, 0]) in (0.0, 1.0)
        if float(a[0, 0]) == 0.0:
            assert float(a[0, 1]) == 0.0
        else:
            assert -1.0 <= float(a[0, 1]) <= 1.0

    def test_atoms_reachable_exactly(self):
        """精确 0/±1 可被采到(原子),不是阈值剪切。"""
        d, _ = make_dist(mix=(0.001, 0.499, 0.499, 0.001))
        th.manual_seed(1)
        seen = set()
        for _ in range(6000):
            a = d.sample()
            if float(a[0, 0]) == 1.0:
                w = round(float(a[0, 1]), 12)
                if w in (-1.0, 0.0, 1.0):
                    seen.add(w)
        assert {0.0, 1.0} <= seen

    def test_hold_perturbation_no_effect(self):
        """HOLD 目标扰动不改变执行/对应似然(w 占位强制 0)。"""
        d, _ = make_dist()
        with pytest.raises(ValueError):
            d.log_prob(th.tensor([[0.0, 0.4]]))   # 编码错误拒绝

    def test_mode_consistent(self):
        d, _ = make_dist()
        m = d.mode()
        assert float(m[0, 0]) == 1.0              # P(rebal)=0.7 大
        assert float(m[0, 1]) == pytest.approx(
            0.3 - 0.1, abs=1e-6)                  # E[w]=m(+1)-m(-1)


# ==================== 真实 PPO 接线:更新/存档/冷读 ====================
def tiny_env(n=8):
    px = pd.Series(100.0 + np.arange(n) * 0.5)
    prices = pd.DataFrame({"open": px, "close": px})
    feats = pd.DataFrame(np.zeros((n, 2)), columns=["f0", "f1"])
    return HybridPositionEnv(features=feats, prices=prices,
                             fee=0.001, window_size=1)


class TestRealPPOChain:
    def test_single_minibatch_backward_step(self, r2_learn):
        env = tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8, seed=0)
        p0 = [p.detach().clone() for p in model.policy.parameters()]
        # R2:测试内 learn 也走任务账本(先预约后执行;计 ppo 不混记 eval)
        assert r2_learn.learn(model, 16) == 16
        changed = [not th.allclose(a, b) for a, b in zip(
            p0, model.policy.parameters())]
        assert any(changed)                       # 真实反向+step

    def test_rollout_uses_env_decode(self, r2_learn):
        """真实 rollout:采样动作经 env.decode_action 合法执行。"""
        env = tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8, seed=0)
        assert r2_learn.learn(model, 16) == 16
        assert model.env.envs[0].unwrapped.ledger is not None

    def test_evaluate_actions_shapes(self):
        env = tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8, seed=0)
        obs = th.as_tensor(env.reset()[0]).unsqueeze(0)
        with th.no_grad():
            a, v, lp = model.policy(obs)
        assert a.shape == (1, 2)
        assert lp.shape == (1,)
        actions, values, logp, ent = None, None, None, None
        values, logp, ent = model.policy.evaluate_actions(obs, a)
        assert values.shape == (1, 1)
        assert float(ent) > 0.0

    def test_save_load_same_and_header_refusal(self, tmp_path):
        env = tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8, seed=0)
        attach_obs_dim(model, int(np.prod(
            env.observation_space.shape)))
        path = tmp_path / "m.zip"
        save_posctl_model(model, path)
        obs = th.as_tensor(env.reset()[0], dtype=th.float32)
        with th.no_grad():
            a0, _, _ = model.policy(obs.unsqueeze(0))
        m2 = load_posctl_model(path, env)
        with th.no_grad():
            a1, _, _ = m2.policy(obs.unsqueeze(0))
        assert bool(th.allclose(a0, a1))          # 同进程重载一致

        # 旧二元/异源存档拒绝:构造无 header 的 SB3 PPO zip
        from stable_baselines3 import PPO as VanillaPPO
        import gymnasium as gym
        old_env = gym.make("CartPole-v1")
        old = VanillaPPO("MlpPolicy", old_env, n_steps=8,
                         batch_size=8, verbose=0)
        old_path = tmp_path / "old_binary.zip"
        old.save(str(old_path))
        with pytest.raises(RuntimeError, match="拒绝"):
            load_posctl_model(old_path, env)

    def test_new_process_cold_load_parity(self, tmp_path):
        """新进程冷读:分布参数与动作对拍(工程夹具环境)。"""
        env = tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8, seed=0)
        attach_obs_dim(model, int(np.prod(
            env.observation_space.shape)))
        path = tmp_path / "cold.zip"
        save_posctl_model(model, path)
        obs = env.reset()[0]
        import json
        spec = {
            "path": str(path),
            "obs": [float(x) for x in obs],
        }
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        import rl_posctl as _rp
        tested_src = str(Path(_rp.__file__).resolve().parent.parent)
        code = (
            "import json,sys\n"
            "sys.path.insert(0,{src!r})\n"
            "import torch as th\n"
            "from rl_posctl.env import HybridPositionEnv\n"
            "from rl_posctl.policy import load_posctl_model\n"
            "import pandas as pd, numpy as np\n"
            "spec=json.load(open({sp!r}))\n"
            "n=8\n"
            "px=pd.Series(100.0+np.arange(n)*0.5)\n"
            "prices=pd.DataFrame({{'open':px,'close':px}})\n"
            "feats=pd.DataFrame(np.zeros((n,2)),columns=['f0','f1'])\n"
            "env=HybridPositionEnv(features=feats,prices=prices,"
            "fee=0.001,window_size=1)\n"
            "m=load_posctl_model(spec['path'],env)\n"
            "o=th.as_tensor(spec['obs'],dtype=th.float32)"
            ".unsqueeze(0)\n"
            "with th.no_grad():\n"
            "    a,v,lp=m.policy(o)\n"
            "    b=m.policy._get_action_dist_from_latent("
            "m.policy.mlp_extractor.forward_actor("
            "m.policy.extract_features(o))[0])\n"
            "print(json.dumps({{'action':[float(x) for x in a[0]],\n"
            " 'logprob':float(lp[0]),\n"
            " 'entropy':float(b.entropy()[0])}}))\n"
        ).format(src=tested_src, sp=str(spec_path))
        script = tmp_path / "cold_load.py"
        script.write_text(code, encoding="utf-8")
        env_vars = dict(os.environ)
        # 冷读必须解析到**被测源**(可编辑安装的 crypto_rl/src 面板
        # 会影子导入旧版;显式 PYTHONPATH 固定导入域)
        env_vars["PYTHONPATH"] = tested_src
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=180,
            env=env_vars)
        assert r.returncode == 0, r.stderr[-800:]
        got = json.loads(r.stdout.strip().splitlines()[-1])
        with th.no_grad():
            a0, _, lp0 = model.policy(th.as_tensor(
                obs, dtype=th.float32).unsqueeze(0))
        assert got["action"] == pytest.approx(
            [float(x) for x in a0[0]], abs=1e-5)
        assert got["logprob"] == pytest.approx(
            float(lp0[0]), abs=1e-5)
