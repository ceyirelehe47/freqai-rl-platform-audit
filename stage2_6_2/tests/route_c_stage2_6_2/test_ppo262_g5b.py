"""G5b 诊断合同测试(边际 BC 损失/计划锁/判定规则)。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rl_curriculum import ppo262_g5b as g5b
from rl_curriculum.ppo262_g5 import DIAG262G5_NAMESPACES
from rl_curriculum.ppo262_r2_namespaces import DIAG262R2_NAMESPACES
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_SEED_NAMESPACES as NS261,
)


def test_namespace_isolation():
    ns = set(g5b.DIAG262G5B_NAMESPACES)
    assert len(ns) == 6
    assert not ns & set(NS261)
    assert not ns & set(DIAG262R2_NAMESPACES)
    assert not ns & set(DIAG262G5_NAMESPACES)


def test_seed_isolation_and_rejection():
    assert g5b.G5B_BC_SEEDS == (29201, 29202, 29203)
    s = g5b.derive262g5b_seed(
        g5b.DIAG262G5B_NAMESPACES[0], "c3_cost", "D0", 0, 0)
    assert s > 0
    with pytest.raises(ValueError):
        g5b.derive262g5b_seed("diag262g5_bc_eval_c3_s0", "c3_cost",
                              "D0", 0, 0)


def test_arms_frozen():
    assert set(g5b.G5B_ARMS) == {
        "B0_control", "B2_margin_bc", "B3_rehearsal",
        "B4_margin_rehearsal"}
    assert g5b.G5B_ARMS["B0_control"] == {"bc": "standard",
                                          "rehearsal": False}
    assert g5b.G5B_ARMS["B4_margin_rehearsal"] == {"bc": "margin",
                                                   "rehearsal": True}


def test_plan_lock_and_tamper(tmp_path):
    path, digest = g5b.lock_g5b_plan(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["g5b_plan_digest"] == digest
    assert doc["non_formal_declaration"]
    assert doc["margin_bc_optimization"]["margin"] == 2.0
    with pytest.raises(RuntimeError):
        g5b.lock_g5b_plan(tmp_path)
    doc["margin"] = 0.5
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeError):
        g5b.load_g5b_plan(tmp_path)


def test_margin_loss_widens_and_classifies():
    import gymnasium
    import torch
    from rl_curriculum.ppo262_r2_train import build_diagnosed_ppo2
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES

    class _Env(gymnasium.Env):
        observation_space = gymnasium.spaces.Box(
            -np.inf, np.inf, shape=(4,), dtype=np.float32)
        action_space = gymnasium.spaces.Discrete(2)

        def reset(self, *, seed=None, options=None):
            super().reset(seed=seed)
            return np.zeros(4, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(4, dtype=np.float32), 0.0, True, False, {}

    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    cfg["net_arch"] = [8]
    model = build_diagnosed_ppo2(cfg, 7, _Env())

    class _Adapter:
        @staticmethod
        def apply(o):
            return o

    rng = np.random.default_rng(0)
    X = rng.normal(size=(64, 4)).tolist()
    w = np.array([1.0, -1.0, 0.5, -0.5])
    y = (np.array([np.dot(x, w) for x in X]) > 0).astype(np.int64)
    ds = {"X": X, "y": y}
    info = g5b.bc_train_actor_margin(
        model, ds, epochs=200, lr=1e-2, adapter=_Adapter(),
        rng_seed=1, margin=2.0)
    stats = g5b.margin_stats(model, ds, _Adapter())
    assert stats["argmax_match"] >= 0.95
    assert stats["mean_abs_diff"] >= 1.0
    assert info["history"][-1]["violating_frac"] <= 0.2


def test_margin_stats_reports_thresholds():
    import types
    import torch

    class _P:
        def get_distribution(self, xt):
            return types.SimpleNamespace(distribution=(
                types.SimpleNamespace(logits=self.logits)))

    class _M:
        def __init__(self, logits):
            self.policy = _P()
            self.policy.logits = logits

    logits = torch.tensor([[3.0, 1.0], [0.0, 0.4]])
    m = _M(logits)
    dev = {"X": [[0.0] * 9] * 2, "y": [0, 1]}

    class _A:
        @staticmethod
        def apply(o):
            return o

    stats = g5b.margin_stats(m, dev, _A)
    # diff = z1-z0:样本1 = 1-3 = -2(y=0,s=-1 ✓);样本2 = 0.4(y=1 ✓)
    # → mean|diff| = 1.2;frac<0.5 = frac<2.0 = 0.5;argmax match = 1.0
    assert stats["frac_below_0p5"] == pytest.approx(0.5)
    assert stats["frac_below_2p0"] == pytest.approx(0.5)
    assert stats["argmax_match"] == pytest.approx(1.0)
