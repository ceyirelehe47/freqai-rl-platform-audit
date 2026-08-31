"""R4 测试:design/power 阶段纪律与 gate/lock 前置(§33)。

- design fail(pack 不存在)不能进入 calibration;
- design plan 网格锁定后禁止漂移;
- calibration fail(gate=false)不能 lock;
- gate=false 不能 lock;
- plan/digest 漂移拒绝;
- exposure 后拒绝重跑(见 namespaces 测试)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r4_param_pack import (
    load_selected_pack,
)
from rl_curriculum.curriculum261_r4_plan import (
    build_plan_r4,
    load_locked_plan_r4,
    lock_plan_r4,
    plan_digest_r4,
)
from rl_curriculum.curriculum261_r4_power import (
    design_plan_digest,
    design_plan_payload,
    run_design_stage,
)


@pytest.fixture(autouse=True)
def _lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R4_LOCK_DIR", str(tmp_path))
    return tmp_path


def _gate(pass_: bool) -> dict:
    return {"pass": pass_, "format": "f"}


def _plan_kwargs(**over):
    from rl_curriculum.curriculum261_r4_param_pack import (
        C1_D3_CANDIDATES, pack_payload,
    )

    pack = pack_payload({"c1_opportunity": {
        "candidate": "c1_b_edge_up2",
        "params": C1_D3_CANDIDATES["c1_b_edge_up2"]}})
    kwargs = dict(
        baseline_commit="d105405",
        vendor_pin="52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
        frozen_contracts={"env_core": "v"},
        parameter_pack=pack,
        frozen_parameter_identity={"identity": "r4fp-x"},
        preprocessing_v2_contract_digest="r4pc-x",
        calibration_bundle_hash="r4pb-a",
        holdout_bundle_hash="r4pb-b",
        preprocessing_robustness_gate=_gate(True),
        curriculum_robustness_gate=_gate(True),
        conditioning_gate_constants={},
        supervised_gate_constants={},
        kappa=1.5,
        reference_thresholds_by_family={},
        prior_r2_plan_digest="qp-x",
        prior_diag262r2_plan_digest="dp-x",
        prior_r3_baseline_commit="1b47db4",
    )
    kwargs.update(over)
    return kwargs


def test_design_fail_blocks_calibration(_lock_dir):
    """design 阶段未产出 pack -> load_selected_pack fail closed。"""
    with pytest.raises(RuntimeError):
        load_selected_pack(_lock_dir)


def test_design_plan_grid_locked_against_drift(_lock_dir):
    """已锁定 design plan 后,代码网格漂移 -> run_design_stage 拒绝。"""
    plan = design_plan_payload()
    plan["candidate_grid"]["c1_opportunity"] = {
        "sneaky": dict(plan["candidate_grid"]["c1_opportunity"][
            "c1_a_edge_up"])}
    (_lock_dir / "r4_parameter_design_plan.json").write_text(
        json.dumps(plan), encoding="utf-8")
    with pytest.raises(RuntimeError):
        run_design_stage(_lock_dir)


def test_design_plan_digest_stable():
    p1, p2 = design_plan_payload(), design_plan_payload()
    assert design_plan_digest(p1) == design_plan_digest(p2)
    p3 = design_plan_payload()
    p3["power_rules"]["design_target_gate_prob"] = 0.5  # 看结果改阈值
    assert design_plan_digest(p3) != design_plan_digest(p1)


def test_calibration_gate_fail_blocks_plan(_lock_dir):
    with pytest.raises(RuntimeError):
        build_plan_r4(**_plan_kwargs(
            preprocessing_robustness_gate=_gate(False)))
    with pytest.raises(RuntimeError):
        build_plan_r4(**_plan_kwargs(
            curriculum_robustness_gate=_gate(False)))


def test_plan_digest_drift_rejected(_lock_dir, monkeypatch):
    plan = build_plan_r4(**_plan_kwargs())
    path, digest = lock_plan_r4(plan)
    assert path.is_file()
    loaded, d2 = load_locked_plan_r4()
    assert d2 == digest
    # 篡改 plan -> digest 重算不一致 -> 拒绝
    tampered = json.loads(path.read_text(encoding="utf-8"))
    tampered["kappa_override_sneak"] = 1.0
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_locked_plan_r4()


def test_plan_digest_excludes_created_utc(_lock_dir):
    plan = build_plan_r4(**_plan_kwargs())
    import copy

    plan2 = copy.deepcopy(plan)
    plan2["created_utc"] = "2099-01-01T00:00:00+00:00"
    assert plan_digest_r4(plan) == plan_digest_r4(plan2)
