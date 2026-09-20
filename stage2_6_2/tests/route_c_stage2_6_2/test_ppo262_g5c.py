"""G5c 诊断合同测试(预算匹配对照/计划锁/命名空间隔离)。"""
from __future__ import annotations

import json

import pytest

from rl_curriculum import ppo262_g5c as g5c
from rl_curriculum.ppo262_g5 import DIAG262G5_NAMESPACES
from rl_curriculum.ppo262_g5b import DIAG262G5B_NAMESPACES
from rl_curriculum.ppo262_r2_namespaces import DIAG262R2_NAMESPACES
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_SEED_NAMESPACES as NS261,
)


def test_namespace_isolation():
    ns = set(g5c.DIAG262G5C_NAMESPACES)
    assert len(ns) == 6
    assert not ns & set(NS261)
    assert not ns & set(DIAG262R2_NAMESPACES)
    assert not ns & set(DIAG262G5_NAMESPACES)
    assert not ns & set(DIAG262G5B_NAMESPACES)


def test_seed_isolation_and_rejection():
    assert g5c.G5C_SEEDS == (29301, 29302, 29303)
    s = g5c.derive262g5c_seed(
        g5c.DIAG262G5C_NAMESPACES[0], "c3_cost", "D0", 0, 0)
    assert s > 0
    with pytest.raises(ValueError):
        g5c.derive262g5c_seed("diag262g5b_bc_train_c3_s0", "c3_cost",
                              "D0", 0, 0)


def test_arms_budget_matched_and_frozen():
    """C1 与 C2 预算逐字相同;C0 = G5b 失败对照预算。"""
    a = g5c.G5C_ARMS
    assert set(a) == {"C0_std30", "C1_std300", "C2_margin300"}
    assert (a["C1_std300"]["epochs"], a["C1_std300"]["lr"]) == (
        a["C2_margin300"]["epochs"], a["C2_margin300"]["lr"])
    assert (a["C0_std30"]["epochs"], a["C0_std30"]["lr"]) == (30, 3e-4)
    assert a["C0_std30"]["loss"] == a["C1_std300"]["loss"] == "ce"
    assert a["C2_margin300"]["loss"] == "hinge"
    assert a["C2_margin300"]["margin"] == 2.0


def test_plan_lock_create_once_and_tamper(tmp_path):
    path, digest = g5c.lock_g5c_plan(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["g5c_plan_digest"] == digest
    assert doc["decision_rule"].startswith("与 G5b 逐字相同")
    with pytest.raises(RuntimeError):
        g5c.lock_g5c_plan(tmp_path)
    doc["arms"]["C1_std300"]["epochs"] = 30
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeError):
        g5c.load_g5c_plan(tmp_path)


def test_decision_rule_constants():
    """判定阈值与 G5b 合同逐字相同(preserved/selective/sanity)。"""
    assert "drop<=0.05" in g5c.build_g5c_plan()["decision_rule"]
    assert ">=2/3" in g5c.build_g5c_plan()["decision_rule"]
    assert "C0_std30" in g5c.build_g5c_plan()["decision_rule"]
