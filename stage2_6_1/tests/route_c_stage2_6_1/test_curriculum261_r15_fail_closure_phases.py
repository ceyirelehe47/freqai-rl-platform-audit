"""R15 阶段精确 failure closure 测试(§七;工作包 C)。

R14 缺陷回归:固定成功阶段尾部模板(7 个后期产物名全 false,
cleanliness 记 final_namespace_state=aborted 等误导字段)。
R15:phase 由权威 workflow 机械派生;证据状态四值
present/absent_due_to_failure_phase/not_expected/not_started;
wording 与实际阶段一致。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r15_fail_closure import (
    ABSENT_DUE_TO_FAILURE_PHASE,
    NOT_EXPECTED,
    NOT_STARTED,
    PRESENT,
    build_phase_accurate_fail_closure,
    qualification_failure_subphase,
)
from rl_curriculum.curriculum261_r15_workflow import (
    r15_producer_of_artifact,
    r15_workflow_step_names,
)

STEPS = list(r15_workflow_step_names())
PRODUCER = r15_producer_of_artifact()


def _closure(tmp_path, failed_step, *, rehearsal=False,
             present=(), reason="injected failure"):
    for name in present:
        f = tmp_path / name
        if not f.exists():  # 调用方预构造的文件(如带 checks 的
            # qualification_result.json)不得被占位覆盖
            f.write_text("{}", encoding="utf-8")
    return build_phase_accurate_fail_closure(
        tmp_path, failed_step=failed_step, reason=reason,
        verdict="FAIL", rehearsal=rehearsal)


class TestPhaseDerivation:
    @pytest.mark.parametrize("step,phase", [
        ("provenance-verify", "pre-provenance"),
        ("determinism-matrix", "determinism"),
        ("audit", "audit"),
        ("cue-audit", "cue-audit"),
        ("preplan-smoke", "preplan-smoke"),
        ("plan-roundtrip", "plan-roundtrip"),
        ("design-plan-lock", "design-plan-lock"),
        ("design", "design"),
        ("calibrate", "calibration"),
        ("preflight-static", "preflight-static"),
        ("lock-plan", "lock-plan"),
        ("preflight-sealed", "sealed-preflight"),
        ("smoke", "smoke"),
        ("full-cold", "full-cold"),
        ("report-read", "report-read"),
        ("verify-formal-logs", "verify-formal-logs"),
    ], ids=lambda x: x)
    def test_phase_matches_workflow_step(self, tmp_path, step, phase):
        c = _closure(tmp_path, step)
        assert c["failure_phase"] == phase
        assert c["failed_step"] == step
        assert c["abort_reason"] == "injected failure"


class TestQualifySubphases:
    def test_pre_exposure_without_marker(self, tmp_path):
        assert qualification_failure_subphase(
            tmp_path, rehearsal=True) == "qualification-pre-exposure"
        c = _closure(tmp_path, "qualify", rehearsal=True)
        assert c["failure_phase"] == "qualification-pre-exposure"
        assert c["exposure_state"] == "not_exposed"
        assert c["final_namespace_state"] == "started_not_yet_exposed"

    def test_exposed_running(self, tmp_path):
        (tmp_path / "rehearsal_exposure.json").write_text(
            json.dumps({"status": "running"}), encoding="utf-8")
        c = _closure(tmp_path, "qualify", rehearsal=True)
        assert c["failure_phase"] == "qualification-exposed-running"
        assert c["exposure_state"] == "exposed_running"

    def test_terminal(self, tmp_path):
        (tmp_path / "rehearsal_exposure.json").write_text(
            json.dumps({"status": "FAIL"}), encoding="utf-8")
        c = _closure(tmp_path, "qualify", rehearsal=True)
        assert c["failure_phase"] == "qualification-terminal"
        assert c["exposure_state"] == "exposed_terminal"
        assert c["final_namespace_state"] == "exposed_terminal"


class TestPlanRoundtripFailure:
    """§七 示例:R14 实际失败场景的阶段精确记录。"""

    def test_states_match_example(self, tmp_path):
        c = _closure(tmp_path, "plan-roundtrip")
        assert c["design_plan_state"] == NOT_STARTED
        assert c["design_data_state"] == NOT_STARTED
        assert c["calibration_state"] == NOT_STARTED
        assert c["qualification_plan"] == NOT_STARTED
        assert c["exposure_state"] == "not_exposed"
        assert c["final_namespace_state"] == NOT_STARTED
        assert c["gate_identity"] == "not_applicable"
        assert c["qualification_result"] == NOT_STARTED
        assert "workflow 已生成 design data" not in c["report_wording"]
        assert "design data 已生成" not in c["report_wording"]
        assert "final 已保存" not in c["report_wording"]

    def test_no_misleading_aborted_state(self, tmp_path):
        """R14 缺陷回归:未到该阶段不得记 aborted/false 语义字段。"""
        c = _closure(tmp_path, "plan-roundtrip")
        assert c["final_namespace_state"] != "aborted"
        for key, value in c["evidence_states"].items():
            assert value in (PRESENT, ABSENT_DUE_TO_FAILURE_PHASE,
                             NOT_EXPECTED, NOT_STARTED), (
                f"{key}={value} 不在四值集合")

    def test_expected_multiset_mechanical(self, tmp_path):
        c = _closure(tmp_path, "plan-roundtrip")
        idx = STEPS.index("plan-roundtrip")
        expected = sorted({
            art for art, prod in PRODUCER.items()
            if STEPS.index(prod) < idx})
        assert c["expected_artifact_multiset"] == expected
        # preplan 产物在,design 产物不在
        assert "preplan_engineering_smoke.json" in \
            c["expected_artifact_multiset"]
        assert "r15_design_plan.json" not in \
            c["expected_artifact_multiset"]


class TestEvidenceStates:
    def test_present_when_producer_ran_and_file_exists(self, tmp_path):
        c = _closure(
            tmp_path, "design",
            present=("r15_design_plan.json",
                     "r15_design_plan_digest.txt"))
        assert c["design_plan_state"] == PRESENT

    def test_absent_when_producer_is_failed_step(self, tmp_path):
        c = _closure(tmp_path, "design")  # pack 不存在
        assert c["design_data_state"] == ABSENT_DUE_TO_FAILURE_PHASE

    def test_absent_when_earlier_producer_file_missing(self, tmp_path):
        # design-plan-lock 已过但其产物缺失(异常)
        c = _closure(tmp_path, "calibrate")  # design_plan 文件未构造
        assert c["design_plan_state"] == ABSENT_DUE_TO_FAILURE_PHASE

    def test_not_expected_for_formal_only_in_rehearsal(self, tmp_path):
        c = _closure(tmp_path, "report-read", rehearsal=True)
        assert c["evidence_states"]["qualification_result"] in (
            PRESENT, ABSENT_DUE_TO_FAILURE_PHASE)

    def test_all_downstream_not_started(self, tmp_path):
        c = _closure(tmp_path, "cue-audit")
        assert c["design_plan_state"] == NOT_STARTED
        assert c["calibration_state"] == NOT_STARTED
        assert c["qualification_result"] == NOT_STARTED


class TestGateIdentity:
    def test_qualify_failure_extracts_first_false_check(self, tmp_path):
        (tmp_path / "qualification_result.json").write_text(
            json.dumps({"verdict": "FAIL", "checks": {
                "alpha_ok": True, "beta_gate": False,
                "gamma_gate": False}}), encoding="utf-8")
        c = _closure(tmp_path, "smoke",
                     present=("qualification_result.json",))
        assert c["gate_identity"] == "beta_gate"

    def test_gate_identity_not_applicable_before_qualify(self, tmp_path):
        c = _closure(tmp_path, "lock-plan")
        assert c["gate_identity"] == "not_applicable"


class TestWording:
    def test_wording_reflects_actual_phase(self, tmp_path):
        c = _closure(tmp_path, "calibrate")
        assert "calibration 未完成" in c["report_wording"]
        assert "calibration 已完成" not in c["report_wording"]

    def test_wording_present_when_data_exists(self, tmp_path):
        c = _closure(
            tmp_path, "calibrate",
            present=("calibration_evidence.json",))
        assert "calibration 已完成" in c["report_wording"]


class TestContractAnchors:
    def test_unknown_step_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="不在权威 workflow"):
            _closure(tmp_path, "not-a-step")

    def test_workflow_digest_attached(self, tmp_path):
        from rl_curriculum.curriculum261_r15_workflow import (
            r15_workflow_graph_digest,
        )
        c = _closure(tmp_path, "audit")
        assert c["workflow_graph_digest"] == r15_workflow_graph_digest()

    def test_next_step_recorded(self, tmp_path):
        c = _closure(tmp_path, "cue-audit")
        assert c["next_step_not_executed"] == "preplan-smoke"
