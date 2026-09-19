# -*- coding: utf-8 -*-
"""G5 诊断合同的单元/行为测试(计划锁定、隔离、arms、判定规则)。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum import ppo262_g5 as g5
from rl_curriculum.curriculum261_api import CURRICULUM261_SEED_NAMESPACES
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_r2_namespaces import DIAG262R2_NAMESPACES


def test_namespace_isolation():
    ns = set(g5.DIAG262G5_NAMESPACES)
    assert len(ns) == 6
    assert not ns & set(CURRICULUM261_SEED_NAMESPACES)
    assert not ns & set(DIAG262R2_NAMESPACES)
    assert all(n.startswith("diag262g5_") for n in ns)


def test_seed_isolation_and_rejection():
    assert g5.G5_BC_SEEDS == (29101, 29102, 29103)
    s = g5.derive262g5_seed(
        g5.DIAG262G5_NAMESPACES[0], "c3_cost", "D0", 0, 0)
    assert s > 0
    with pytest.raises(ValueError):
        g5.derive262g5_seed(
            "diag262r2_1_bc_c3", "c3_cost", "D0", 0, 0)
    with pytest.raises(ValueError):
        g5.derive262g5_seed("calibration", "c3_cost", "D0", 0, 0)


def test_arms_frozen_and_config_only():
    base = dict(PPO262_CANDIDATES[g5.G5_BASE_CANDIDATE])
    assert g5.G5_ARMS["A0_control"]["overlay"] == {}
    for name, arm in g5.G5_ARMS.items():
        assert set(arm["overlay"]) <= set(base), name
        for k in arm.get("model_kwargs", {}):
            assert k in {"normalize_advantage"}, (name, k)
    assert g5.G5_ARMS["A1_lr_low"]["overlay"]["learning_rate"] == 3e-5
    assert g5.G5_ARMS["A4_vf_low"]["overlay"]["vf_coef"] == 0.05
    assert g5.G5_ARMS["A5_clip_low"]["overlay"]["clip_range"] == 0.05


def test_plan_lock_create_only_and_tamper_detection(tmp_path):
    path, digest = g5.lock_g5_plan(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["g5_plan_digest"] == digest
    assert doc["non_formal_declaration"]
    # 重锁拒绝
    with pytest.raises(RuntimeError):
        g5.lock_g5_plan(tmp_path)
    # 篡改拒绝
    doc["arms"]["A1_lr_low"]["overlay"]["learning_rate"] = 1e-9
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeError):
        g5.load_g5_plan(tmp_path)

def test_kl_helper_direction():
    """KL(π‖π)=0(同分布);扰动 logits 后 KL>0(方向性真实)。"""
    import torch
    from rl_curriculum.ppo262_g5 import _kl_to_bc

    class _P:
        def __init__(self, logits):
            self._logits = logits

        def get_distribution(self, xt):
            import types

            return types.SimpleNamespace(distribution=(
                types.SimpleNamespace(logits=self._logits)))

    class _M:
        def __init__(self, logits):
            self.policy = _P(logits)

    dev = {"X": [[0.0] * 9] * 4, "y": [0, 1, 0, 1]}

    class _A:
        @staticmethod
        def apply(o):
            return o

    logits = torch.tensor([[2.0, 0.0]] * 4)
    m1, m2 = _M(logits.clone()), _M(logits.clone())
    assert _kl_to_bc(m1, m2, dev, _A) == pytest.approx(0.0, abs=1e-6)
    m3 = _M(logits + torch.tensor([[0.0, 3.0]] * 4))
    assert _kl_to_bc(m3, m2, dev, _A) > 0.1
