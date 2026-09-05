# -*- coding: utf-8 -*-
"""R17 阶段精确 failure closure(§8.4 + §5.4)。

继承 R15 的四值证据语义(present / absent_due_to_failure_phase /
not_started / not_expected;未到该阶段不得记为 false 或 aborted)。

R17 相对 R15 的差异:
- qualification 三细分 phase 从权威 journal
  (curriculum261_r17_execgov.exposure_state)机械判定,marker 只是
  投影;journal 损坏时如实记录 corrupt 并按已暴露处理(封口路径
  不因证据损坏而拒绝收尾,但不得声称"从未 exposure",§8.2);
- 新增 bootstrap 失败边界(§5.4):failed_step="bootstrap" 表示
  interpreter/import/环境失败发生在任何 workflow 节点之前——
  executed prefix 为空、首个未执行节点是 provenance-verify、
  未开始 provenance-verify(不得写成"已执行失败")、design/
  calibration/final 全未开始、qualification 未授权且未 exposure;
- reader 语义(§8.5):本模块只读取已发布证据 + 追加失败结论,
  不恢复执行、不补造事件。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r17_workflow import (
    R17_WORKFLOW_STEPS,
    R17_WORKFLOW_VERSION,
    r17_producer_of_artifact,
    r17_workflow_graph_digest,
    r17_workflow_step_names,
)

#: fail closure 证据清单(R17 文件名布局)。
R17_EVIDENCE_KEYS: tuple[tuple[str, str], ...] = (
    ("design_plan_state", "r17_design_plan.json"),
    ("design_data_state", "r17_parameter_pack.json"),
    ("calibration_state", "calibration_evidence.json"),
    ("qualification_plan", "qualification_plan_r17.json"),
    ("sealed_preflight", "sealed_final_preflight_r17.json"),
    ("qualification_result", "qualification_result.json"),
    ("qualification_raw", "qualification_raw.json"),
    ("ppo_smoke", "ppo_256step_smoke.json"),
    ("full_cold_reader", "full_cold_reader_check.json"),
)

#: 证据状态四值(§8.4)。
PRESENT = "present"
ABSENT_DUE_TO_FAILURE_PHASE = "absent_due_to_failure_phase"
NOT_STARTED = "not_started"
NOT_EXPECTED = "not_expected"


def _step_index(failed_step: str) -> int:
    if failed_step == "bootstrap":
        return -1
    names = list(r17_workflow_step_names())
    if failed_step not in names:
        raise ValueError(
            f"failed_step '{failed_step}' 不在权威 workflow 步骤集"
            f"({names} 或 'bootstrap')——fail closure 阶段判定必须由"
            "权威定义派生")
    return names.index(failed_step)


def qualification_failure_subphase_r17(
        out_dir: Path, *, rehearsal: bool = False) -> tuple[str, bool]:
    """qualify 步三细分 phase(机械判定;返回 (phase, journal_ok))。

    formal:权威 journal 的 exposure 状态;rehearsal:
    rehearsal_exposure.json 投影。journal 损坏 ⇒
    (qualification-exposed-running, False)——封口按已暴露处理并
    如实记录损坏,不得静默当作未暴露。
    """
    if rehearsal:
        marker = Path(out_dir) / "rehearsal_exposure.json"
        if not marker.is_file():
            return "qualification-pre-exposure", True
        try:
            status = json.loads(
                marker.read_text(encoding="utf-8")).get("status")
        except (json.JSONDecodeError, OSError):
            return "qualification-exposed-running", False
        if status == "running":
            return "qualification-exposed-running", True
        return "qualification-terminal", True
    from rl_curriculum.curriculum261_r17_execgov import (
        R17JournalCorruption,
        exposure_state as journal_exposure_state,
    )

    try:
        state = journal_exposure_state()
    except R17JournalCorruption:
        return "qualification-exposed-running", False
    if not state["exposed"]:
        return "qualification-pre-exposure", True
    if state["terminal"]:
        return "qualification-terminal", True
    return "qualification-exposed-running", True


def build_phase_accurate_fail_closure_r17(
        out_dir: Path, *, failed_step: str, reason: str,
        verdict: str = "FAIL", rehearsal: bool = False,
) -> dict[str, Any]:
    """按实际停止阶段机械组装 failure closure 证据(§8.4)。"""
    out_dir = Path(out_dir)
    idx = _step_index(failed_step)
    if failed_step == "bootstrap":
        base_phase = "bootstrap"
    else:
        step = R17_WORKFLOW_STEPS[idx]
        base_phase = step["failure_phase"]
    if base_phase == "qualification":
        phase, journal_ok = qualification_failure_subphase_r17(
            out_dir, rehearsal=rehearsal)
    elif base_phase == "bootstrap":
        phase, journal_ok = "bootstrap", True
    else:
        journal_ok = True
        phase = base_phase
    producer = r17_producer_of_artifact()
    names = list(r17_workflow_step_names())

    def evidence_state(artifact: str) -> str:
        prod = producer.get(artifact)
        if prod is None:
            return NOT_EXPECTED
        if rehearsal and artifact == "r17_report_values.json":
            return NOT_EXPECTED
        if failed_step == "bootstrap" or names.index(prod) > idx:
            return NOT_STARTED
        return (PRESENT if (out_dir / artifact).is_file()
                else ABSENT_DUE_TO_FAILURE_PHASE)

    evidence: dict[str, str] = {
        key: evidence_state(art) for key, art in R17_EVIDENCE_KEYS}
    expected_multiset = sorted({
        art for art, prod in producer.items()
        if failed_step != "bootstrap" and names.index(prod) < idx})
    actual_present = sorted(
        a for a in expected_multiset if (out_dir / a).is_file())
    missing_expected = sorted(
        set(expected_multiset) - set(actual_present))

    if failed_step == "bootstrap" or idx < names.index("qualify"):
        if failed_step == "bootstrap":
            sub = "bootstrap"
        else:
            sub = None
        exposure_state_val = "not_exposed"
        final_namespace_state = NOT_STARTED
    else:
        sub, _ = qualification_failure_subphase_r17(
            out_dir, rehearsal=rehearsal)
        exposure_state_val = {
            "qualification-pre-exposure": "not_exposed",
            "qualification-exposed-running": "exposed_running",
            "qualification-terminal": "exposed_terminal",
        }[sub]
        final_namespace_state = {
            "qualification-pre-exposure": "started_not_yet_exposed",
            "qualification-exposed-running": "exposed_running",
            "qualification-terminal": "exposed_terminal",
        }[sub]

    gate_identity = "not_applicable"
    qualification_result_state = evidence["qualification_result"]
    if qualification_result_state == PRESENT:
        try:
            res = json.loads(
                (out_dir / "qualification_result.json").read_text(
                    encoding="utf-8"))
            failed_checks = sorted(
                k for k, v in res.get("checks", {}).items()
                if isinstance(v, bool) and not v)
            gate_identity = (failed_checks[0] if failed_checks
                             else "none(checks 全过;失败不在 final "
                                  "gate)")
        except (json.JSONDecodeError, OSError):
            gate_identity = "unreadable(qualification_result.json)"

    if failed_step == "bootstrap":
        wording_parts = [
            "失败发生在 bootstrap(workflow 之前);已执行 workflow "
            "前缀为空;首个未执行节点是 provenance-verify(未开始,"
            "不是已执行失败);design/calibration/final 全未开始;"
            "qualification 未授权且未 exposure",
        ]
    else:
        wording_parts = [
            f"formal 链停止于 {failed_step}(phase={phase})",
        ]
    if evidence["design_data_state"] == PRESENT:
        wording_parts.append("design data 已生成")
    else:
        wording_parts.append(
            f"design data 未生成({evidence['design_data_state']})")
    if evidence["calibration_state"] == PRESENT:
        wording_parts.append("calibration 已完成")
    else:
        wording_parts.append(
            f"calibration 未完成({evidence['calibration_state']})")
    wording_parts.append(
        f"qualification result={qualification_result_state};"
        f"exposure={exposure_state_val}")

    return {
        "format": "cur261-r17-fail-closure-v1",
        "iteration": "r17",
        "rehearsal": bool(rehearsal),
        "verdict": verdict,
        "failed_step": failed_step,
        "failure_phase": phase,
        "abort_reason": reason,
        "journal_integrity_ok": journal_ok,
        "workflow_version": R17_WORKFLOW_VERSION,
        "workflow_graph_digest": r17_workflow_graph_digest(),
        "stopped_at_index": idx,
        "executed_prefix": ([] if failed_step == "bootstrap"
                            else names[:idx]),
        "next_step_not_executed": (
            "provenance-verify" if failed_step == "bootstrap"
            else names[idx + 1] if idx + 1 < len(names) else "(链尾)"),
        "evidence_states": evidence,
        "expected_artifact_multiset": expected_multiset,
        "actual_present_artifacts": actual_present,
        "missing_expected_artifacts": missing_expected,
        "design_plan_state": evidence["design_plan_state"],
        "design_data_state": evidence["design_data_state"],
        "calibration_state": evidence["calibration_state"],
        "qualification_plan": evidence["qualification_plan"],
        "exposure_state": exposure_state_val,
        "final_namespace_state": final_namespace_state,
        "gate_identity": gate_identity,
        "qualification_result": qualification_result_state,
        "report_wording": ";".join(wording_parts),
        "phase_accuracy_note": (
            "证据状态四值 present/absent_due_to_failure_phase/"
            "not_expected/not_started;phase 由实际执行事件决定,"
            "不是预期下一步或文件存在性;bootstrap 失败时 workflow "
            "前缀为空且 provenance-verify 未开始(R15 启动失败反例 "
            "的回归期望)"),
    }


#: 机械转换后的 r17_cli 使用的名称别名(同一实现)。
build_phase_accurate_fail_closure = build_phase_accurate_fail_closure_r17
qualification_failure_subphase = qualification_failure_subphase_r17


__all__ = [
    "R17_EVIDENCE_KEYS",
    "PRESENT",
    "ABSENT_DUE_TO_FAILURE_PHASE",
    "NOT_STARTED",
    "NOT_EXPECTED",
    "qualification_failure_subphase_r17",
    "build_phase_accurate_fail_closure_r17",
]
