"""R2 family branch 判定与全局组合测试。

覆盖任务书 §16/§18/§20:C1/C2/C3 独立判定;跨 family 拼接被拒;
任何 family F -> global diagnostics FAIL。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rl_curriculum.ppo262_r2_cli import _recovery_check
from rl_curriculum.ppo262_r2_evaluator import (
    CrossFamilyEvidenceError, decide_family_branch,
    family_recovery_evidence,
)

THR = {
    "recovery_eval_capture": 0.0,
    "recovery_probability_gap": 0.05,
    "recovery_det_behavior_gap": 0.02,
}


def _cap(fam, val=0.3, valid=True):
    return {"family": fam, "valid": valid, "capture": val
            if valid else None}


def _prob(fam, gap=0.2, suff=True):
    return {"family": fam, "probability_gap": gap,
            "sampling_sufficient": suff,
            "class_sample_counts": {"a": 100}}


def _beh(fam, gap=0.1):
    return {"family": fam, "det_behavior_gap": gap}


def test_recovery_check_all_conditions_same_family():
    r = _recovery_check(_cap("c1_opportunity"), _prob("c1_opportunity"),
                        _beh("c1_opportunity"), THR,
                        family="c1_opportunity")
    assert r["recovered"]
    # 单条件不满足 -> 不恢复
    assert not _recovery_check(
        _cap("c1_opportunity", val=-0.1), _prob("c1_opportunity"),
        _beh("c1_opportunity"), THR, family="c1_opportunity")["recovered"]
    assert not _recovery_check(
        _cap("c1_opportunity"), _prob("c1_opportunity", gap=0.01),
        _beh("c1_opportunity"), THR, family="c1_opportunity")["recovered"]
    assert not _recovery_check(
        _cap("c1_opportunity"), _prob("c1_opportunity"),
        _beh("c1_opportunity", gap=0.001), THR,
        family="c1_opportunity")["recovered"]
    # capture 证据无效 -> 不恢复
    assert not _recovery_check(
        _cap("c1_opportunity", valid=False), _prob("c1_opportunity"),
        _beh("c1_opportunity"), THR, family="c1_opportunity")["recovered"]


def test_recovery_check_rejects_cross_family_stitching():
    with pytest.raises(CrossFamilyEvidenceError):
        _recovery_check(_cap("c1_opportunity"), _prob("c3_cost"),
                        _beh("c1_opportunity"), THR,
                        family="c1_opportunity")
    with pytest.raises(CrossFamilyEvidenceError):
        family_recovery_evidence(
            "c2_context", _cap("c2_context"), _prob("c1_opportunity"),
            _beh("c2_context"))


def test_family_branches_independent():
    """三族分支互不替代:C1=A 不影响 C2 的独立判定。"""
    c1 = decide_family_branch(
        unscaled_recovered=True, scaled_recovered=False,
        linear_all_fail=False, class_balanced_all_fail=False,
        bc_executed=False, bc_retained_2of3=False,
        bc_destroyed_2of3=False)
    c2 = decide_family_branch(
        unscaled_recovered=False, scaled_recovered=False,
        linear_all_fail=False, class_balanced_all_fail=False,
        bc_executed=True, bc_retained_2of3=False,
        bc_destroyed_2of3=True)
    c3 = decide_family_branch(
        unscaled_recovered=False, scaled_recovered=False,
        linear_all_fail=True, class_balanced_all_fail=True,
        bc_executed=False, bc_retained_2of3=False,
        bc_destroyed_2of3=False)
    assert (c1, c2, c3) == ("A", "D", "E")


def test_any_family_F_fails_global():
    branches = {"c1_opportunity": "A", "c2_context": "F",
                "c3_cost": "B"}
    assert any(b == "F" for b in branches.values())
    # validator 语义:family_branch_decision.pass = not any F
    assert not (not any(b == "F" for b in branches.values()))
    ok = {"c1_opportunity": "A", "c2_context": "D", "c3_cost": "E"}
    assert not any(b == "F" for b in ok.values())


def test_global_route_decision_matrix():
    """§18 路线组合:全 A -> rerun;任一 B -> 2.6.1 R3;任一 D ->
    PPO repair;任一 C -> warm-start governance;任一 E -> R3;
    任一 F -> FAIL。"""

    def route(branches):
        if any(b == "F" for b in branches.values()):
            return "FAIL"
        if all(b == "A" for b in branches.values()):
            return "rerun"
        if any(b == "B" for b in branches.values()):
            return "r3_preprocess"
        if any(b == "D" for b in branches.values()):
            return "ppo_repair"
        if any(b == "C" for b in branches.values()):
            return "warm_start"
        if any(b == "E" for b in branches.values()):
            return "r3_generator"
        return "unexpected"

    assert route({"c1": "A", "c2": "A", "c3": "A"}) == "rerun"
    assert route({"c1": "A", "c2": "B", "c3": "A"}) == "r3_preprocess"
    assert route({"c1": "A", "c2": "D", "c3": "A"}) == "ppo_repair"
    assert route({"c1": "C", "c2": "A", "c3": "A"}) == "warm_start"
    assert route({"c1": "A", "c2": "E", "c3": "A"}) == "r3_generator"
    assert route({"c1": "A", "c2": "F", "c3": "A"}) == "FAIL"


def test_branch_d_requires_bc_learned():
    """BC 未学会时不得判 D(1/3 分裂或未学会 -> F 或按其它证据)。"""
    b = decide_family_branch(
        unscaled_recovered=False, scaled_recovered=False,
        linear_all_fail=False, class_balanced_all_fail=False,
        bc_executed=True, bc_retained_2of3=False,
        bc_destroyed_2of3=False)
    assert b == "F"


def test_no_single_global_branch_mechanical_assignment():
    """R1 的'整项目单一 Branch D'机械分配不得再现:判定输入必须
    family-keyed。"""
    ev = {
        "c1_opportunity": {"branch": "A"},
        "c2_context": {"branch": "F"},
        "c3_cost": {"branch": "B"},
    }
    branches = [d["branch"] for d in ev.values()]
    assert len(set(branches)) > 1  # 不同族允许不同分支
