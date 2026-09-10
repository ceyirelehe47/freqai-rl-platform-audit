"""R15 阶段精确 failure closure(Work Package C;§七)。

R14 缺陷:cmd_fail_closure 使用固定的成功阶段尾部模板
(7 个文件全是 qualification 之后的产物名),R14 实际死在
plan-roundtrip ⇒ 7 项全 false,且 cleanliness 把"未到该阶段"
记为 final_namespace_state=aborted 等误导性字段。

R15 权威语义:
- phase 由权威 workflow 定义机械派生(每个 step 声明
  failure_phase;qualify 细分 pre-exposure / exposed-running /
  terminal 由 exposure marker/ledger 状态机械判定);
- 每类证据状态使用四值:present / absent_due_to_failure_phase /
  not_expected / not_started(不得把"未到该阶段"记为 false 或
  "aborted");
- expected artifact multiset = 截至失败点应存在的产物集合
  (workflow producer 图机械推导);
- report wording 与实际 phase 一致(未生成的数据不得出现
  "已生成"字样);
- cleanliness 复用 write_path_cleanliness_r15(只读收尾)。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r15_workflow import (
    R15_WORKFLOW_STEPS,
    R15_WORKFLOW_VERSION,
    r15_producer_of_artifact,
    r15_workflow_graph_digest,
    r15_workflow_step_names,
)

#: fail closure 证据清单覆盖的关键产物(§七示例字段的最小集;
#: 完整 per-producer multiset 由 workflow 图机械推导)。
R15_EVIDENCE_KEYS: tuple[tuple[str, str], ...] = (
    ("design_plan_state", "r15_design_plan.json"),
    ("design_data_state", "r15_parameter_pack.json"),
    ("calibration_state", "calibration_evidence.json"),
    ("qualification_plan", "qualification_plan_r15.json"),
    ("sealed_preflight", "sealed_final_preflight.json"),
    ("qualification_result", "qualification_result.json"),
    ("qualification_raw", "qualification_raw.json"),
    ("ppo_smoke", "ppo_256step_smoke.json"),
    ("full_cold_reader", "full_cold_reader_check.json"),
)

#: 证据状态四值(§七:不得把"未到该阶段"表示为 false)。
PRESENT = "present"
ABSENT_DUE_TO_FAILURE_PHASE = "absent_due_to_failure_phase"
NOT_STARTED = "not_started"
NOT_EXPECTED = "not_expected"


def _step_index(failed_step: str) -> int:
    names = list(r15_workflow_step_names())
    if failed_step not in names:
        raise ValueError(
            f"failed_step '{failed_step}' 不在权威 workflow 步骤集"
            f"({names})——fail closure 阶段判定必须由权威定义派生")
    return names.index(failed_step)


def qualification_failure_subphase(
        out_dir: Path, *, rehearsal: bool = False) -> str:
    """qualify 步的三细分 phase(机械判定;§七)。

    formal:exposure marker + append-only ledger 状态;
    rehearsal:rehearsal_exposure.json 的 status。
    """
    if rehearsal:
        marker = out_dir / "rehearsal_exposure.json"
        if not marker.is_file():
            return "qualification-pre-exposure"
        try:
            status = json.loads(
                marker.read_text(encoding="utf-8")).get("status")
        except (json.JSONDecodeError, OSError):
            return "qualification-exposed-running"
        if status == "running":
            return "qualification-exposed-running"
        return "qualification-terminal"
    from rl_curriculum.curriculum261_r15_namespaces import (
        qualification_r15_lock_dir,
        qualification_r15_terminal_exposed,
    )
    marker = (qualification_r15_lock_dir()
              / "qualification_exposure_r15.json")
    if not marker.is_file():
        return "qualification-pre-exposure"
    if qualification_r15_terminal_exposed():
        return "qualification-terminal"
    return "qualification-exposed-running"


def build_phase_accurate_fail_closure(
        out_dir: Path, *, failed_step: str, reason: str,
        verdict: str = "FAIL", rehearsal: bool = False,
) -> dict[str, Any]:
    """按实际停止阶段机械组装 failure closure 证据(§七)。

    不得使用固定成功阶段模板;不得记录未发生的事实。
    """
    out_dir = Path(out_dir)
    idx = _step_index(failed_step)
    step = R15_WORKFLOW_STEPS[idx]
    base_phase = step["failure_phase"]
    if base_phase == "qualification":
        phase = qualification_failure_subphase(
            out_dir, rehearsal=rehearsal)
    else:
        phase = base_phase
    producer = r15_producer_of_artifact()
    names = list(r15_workflow_step_names())

    def evidence_state(artifact: str) -> str:
        prod = producer.get(artifact)
        if prod is None:
            return NOT_EXPECTED
        # rehearsal profile 的 formal-only 产物(report 名)
        if rehearsal and artifact == "r15_report_values.json":
            return NOT_EXPECTED
        if names.index(prod) > idx:
            return NOT_STARTED
        if names.index(prod) == idx:
            return (PRESENT if (out_dir / artifact).is_file()
                    else ABSENT_DUE_TO_FAILURE_PHASE)
        return (PRESENT if (out_dir / artifact).is_file()
                else ABSENT_DUE_TO_FAILURE_PHASE)

    evidence: dict[str, str] = {
        key: evidence_state(art) for key, art in R15_EVIDENCE_KEYS}
    # expected artifact multiset:截至失败点(不含)应存在的产物全集
    expected_multiset = sorted({
        art for art, prod in producer.items()
        if names.index(prod) < idx})
    actual_present = sorted(
        a for a in expected_multiset if (out_dir / a).is_file())
    missing_expected = sorted(
        set(expected_multiset) - set(actual_present))

    # exposure/final namespace 状态(机械)
    if idx < names.index("qualify"):
        exposure_state = "not_exposed"
        final_namespace_state = NOT_STARTED
    else:
        sub = qualification_failure_subphase(
            out_dir, rehearsal=rehearsal)
        exposure_state = {
            "qualification-pre-exposure": "not_exposed",
            "qualification-exposed-running": "exposed_running",
            "qualification-terminal": "exposed_terminal",
        }[sub]
        final_namespace_state = {
            "qualification-pre-exposure": "started_not_yet_exposed",
            "qualification-exposed-running": "exposed_running",
            "qualification-terminal": "exposed_terminal",
        }[sub]

    # gate_identity:qualify 之后失败且有 result 时,从 checks 机械
    # 提取第一个 False binding gate;否则 not_applicable
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
        f"exposure={exposure_state}")

    return {
        "format": "cur261-r15-fail-closure-v2",
        "iteration": "r15",
        "rehearsal": bool(rehearsal),
        "verdict": verdict,
        "failed_step": failed_step,
        "failure_phase": phase,
        "abort_reason": reason,
        "workflow_version": R15_WORKFLOW_VERSION,
        "workflow_graph_digest": r15_workflow_graph_digest(),
        "stopped_at_index": idx,
        "next_step_not_executed": (
            names[idx + 1] if idx + 1 < len(names) else "(链尾)"),
        "evidence_states": evidence,
        "expected_artifact_multiset": expected_multiset,
        "actual_present_artifacts": actual_present,
        "missing_expected_artifacts": missing_expected,
        "design_plan_state": evidence["design_plan_state"],
        "design_data_state": evidence["design_data_state"],
        "calibration_state": evidence["calibration_state"],
        "qualification_plan": evidence["qualification_plan"],
        "exposure_state": exposure_state,
        "final_namespace_state": final_namespace_state,
        "gate_identity": gate_identity,
        "qualification_result": qualification_result_state,
        "report_wording": ";".join(wording_parts),
        "phase_accuracy_note": (
            "证据状态四值 present/absent_due_to_failure_phase/"
            "not_expected/not_started;未到该阶段不得记为 false 或 "
            "aborted(R15 §七;R14 固定成功阶段模板缺陷的修复)"),
    }
