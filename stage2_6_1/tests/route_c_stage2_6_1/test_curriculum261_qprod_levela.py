# -*- coding: utf-8 -*-
"""QProd Level A 工程排练测试(E02:步账本诚实/判定核心/失败封口)。

零原生生成:fixture_inputs 提供标注工程夹具;控制/锁定/判定/exposure
真实执行;替身与 NOT_RUN 显式记录。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, QProdRunSession, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_levela import (
    QPROD_LEVELA_GATES, build_engineering_cue_report_fixture,
    build_engineering_topology_fixture, commit_exposure_terminal,
    open_exposure, judge_qualification_gates,
    level_a_step_execution_plan, run_level_a_rehearsal,

)
from rl_curriculum.curriculum261_qprod_plan import load_qualification_plan

AUTHORITY_ID = "t-auth"


def _ctx(tmp_path: Path):
    adir = tmp_path / "authority"
    adir.mkdir(exist_ok=True)
    (adir / "authority_identity.json").write_text(json.dumps(
        {"authority_id": AUTHORITY_ID}), encoding="utf-8")
    return build_engineering_context(
        level="level_a", iteration_id="eng-i1",
        base_dir=tmp_path / "base", code_freeze_sha="sha-a",
        authority_dir=adir)


def _fixture_inputs(tmp_path: Path, *, pack_pass_families=True,
                    robustness_pass=True, bundle_hash_override=None):
    from rl_curriculum.ppo262_eng_fixture import (
        _engineering_pack, build_frozen_v2_preprocessor,
    )
    pack = _engineering_pack("v1_r2_reference")
    if not pack_pass_families:
        pack["families"].pop("c3_cost")
    preproc, _records = build_frozen_v2_preprocessor()
    envelope_path = tmp_path / "env.json"
    preproc.serialize_envelope(envelope_path)
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    bundle_hash = envelope["hashes"]["preprocessor_bundle_hash"]
    if bundle_hash_override is not None:
        bundle_hash = bundle_hash_override
    return {
        "gate_topology": build_engineering_topology_fixture(),
        "cue_audit_report": build_engineering_cue_report_fixture(),
        "preplan_smoke": {"pass": True},
        "design_plan": {"grid": "fixture"},
        "parameter_pack": pack,
        "calibration_artifacts": {
            "preprocessor_bundle_calibration.json": {
                "preprocessor_bundle_hash": bundle_hash},
            "preprocessor_bundle_holdout.json": {
                "preprocessor_bundle_hash": bundle_hash}},
        "robustness_gate": {"pass": robustness_pass},
        "c2_marginal": {"metrics": {"non_cue_false_positive_max": 0.001}},
        "c2_marginal_thresholds": {"non_cue_false_positive_max": 0.01},
        "v2_envelope_path": envelope_path,
    }


def _run(tmp_path: Path, **kw):
    ctx = _ctx(tmp_path)
    session = QProdRunSession(
        ctx.state_root, level="level_a", iteration_id=ctx.iteration_id)
    session.acquire({"entry": "test"})
    out = run_level_a_rehearsal(
        ctx, session, _fixture_inputs(tmp_path, **kw))
    return ctx, out


def test_rehearsal_happy_path_with_honest_ledger(tmp_path):
    ctx, out = _run(tmp_path)
    assert out["verdict"] == "PASS"
    ledger = json.loads(
        (ctx.artifact_root / "level_a_step_ledger.json").read_text(
            encoding="utf-8"))
    by_step = {e["step"]: e for e in ledger["steps"]}
    # 17 步全覆盖;smoke=NOT_RUN;原生数据步=替身;控制步=real
    assert len(ledger["steps"]) == 17
    assert by_step["smoke"]["execution"] == "not_run"
    assert "NOT_RUN" in by_step["smoke"]["note"] or (
        "不执行" in by_step["smoke"]["note"])
    for step in ("determinism-matrix", "cue-audit", "preplan-smoke",
                 "design", "calibrate"):
        assert by_step[step]["execution"] == "fixture_double", step
    for step in ("design-plan-lock", "lock-plan", "qualify",
                 "preflight-sealed", "report-read", "verify-formal-logs"):
        assert by_step[step]["execution"] == "real", step
    assert set(level_a_step_execution_plan()) == set(by_step)
    # F2(reviewer)修复钉:序列核验门必须真实通过(旧实现恒 False
    # 的死门下 PASS 与 sequence_ok=false 并存自相矛盾)
    verification = json.loads(
        (ctx.artifact_root / "formal_log_verification.json").read_text(
            encoding="utf-8"))
    assert verification["sequence_ok"] is True
    assert by_step["verify-formal-logs"]["ok"] is True
    assert ledger["verdict"] == "PASS"


def test_result_binds_plan_and_engineering_markers(tmp_path):
    ctx, out = _run(tmp_path)
    result = json.loads(
        (ctx.artifact_root / "qprod_qualification_result.json").read_text(
            encoding="utf-8"))
    assert result["verdict"] == "PASS"
    assert result["engineering_only"] is True
    assert result["formal_pass"] is False, "工程判定绝不产生正式合格声明"
    assert result["scope"] == "engineering"
    qp = load_qualification_plan(ctx.state_root)
    assert result["qualification_plan_digest"] == qp[
        "qualification_plan_digest"]
    # 两阶段计划衔接:资格计划携带数据前运行计划 digest
    assert qp["prior_plan_digest"].startswith("qbpl-")
    assert qp["qualification_plan_digest"].startswith("qapl-")
    assert qp["prior_plan_digest"] != qp["qualification_plan_digest"]


def test_gate_fail_seals_fail_not_exportable(tmp_path):
    ctx, out = _run(tmp_path, robustness_pass=False)
    assert out["verdict"] == "FAIL"
    raw = json.loads(
        (ctx.artifact_root / "qprod_qualification_raw.json").read_text(
            encoding="utf-8"))
    assert raw["gates"]["robustness_gate_pass"]["pass"] is False
    ledger = json.loads(
        (ctx.artifact_root / "level_a_step_ledger.json").read_text(
            encoding="utf-8"))
    assert ledger["verdict"] == "FAIL"
    # 失败后 smoke/full-cold 等后续步骤不得执行
    steps = [e["step"] for e in ledger["steps"]]
    assert "smoke" not in steps
    # journal 终态=FAIL(completed+FAIL 不被后续救活)
    journal = (ctx.state_root / "qprod_run_journal.jsonl").read_text(
        encoding="utf-8")
    assert '"verdict": "FAIL"' in journal


def test_missing_gate_evidence_fails_closed(tmp_path):
    ctx = _ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({})
    inputs = _fixture_inputs(tmp_path)
    inputs["robustness_gate"] = {"pass": False}  # gate 失败证据
    out = run_level_a_rehearsal(ctx, session, inputs)
    assert out["verdict"] == "FAIL"


def test_exposure_one_shot_no_reopen(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    open_exposure(art, plan_digest="d1", iteration_id="i")
    commit_exposure_terminal(art, plan_digest="d1", status="completed")
    with pytest.raises(QProdContextError, match="不可重开"):
        open_exposure(art, plan_digest="d1", iteration_id="i")
    with pytest.raises(QProdContextError, match="不可重入"):
        commit_exposure_terminal(art, plan_digest="d1",
                                 status="completed")
    with pytest.raises(QProdContextError, match="不一致"):
        commit_exposure_terminal(art, plan_digest="other",
                                 status="failed")


def test_broken_pack_structure_fails_at_preflight(tmp_path):
    ctx = _ctx(tmp_path)
    session = QProdRunSession(ctx.state_root, level="level_a",
                              iteration_id=ctx.iteration_id)
    session.acquire({})
    with pytest.raises(QProdContextError, match="preflight-static"):
        run_level_a_rehearsal(
            ctx, session, _fixture_inputs(tmp_path,
                                          pack_pass_families=False))


def test_judgment_core_gate_set_matches_run_scope(tmp_path):
    """判定 gate 集与数据前运行计划声明一致(公共判定核心单源)。"""
    ctx, out = _run(tmp_path)
    run_plan = json.loads(
        (ctx.state_root / "qprod_research_plan.json").read_text(
            encoding="utf-8"))
    assert run_plan["run_scope"]["gate_set"] == list(QPROD_LEVELA_GATES)
    raw = json.loads(
        (ctx.artifact_root / "qprod_qualification_raw.json").read_text(
            encoding="utf-8"))
    assert set(raw["gates"]) == set(QPROD_LEVELA_GATES)


def test_bundle_mismatch_fails_calibration_gate(tmp_path):
    ctx, out = _run(tmp_path, bundle_hash_override="r4pb-MISMATCH")
    assert out["verdict"] == "FAIL"
    raw = json.loads(
        (ctx.artifact_root / "qprod_qualification_raw.json").read_text(
            encoding="utf-8"))
    assert raw["gates"]["calibration_bundle_hash_match"]["pass"] is False
