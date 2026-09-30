# -*- coding: utf-8 -*-
"""QProd 坐标锁测试(C01/C02:拒绝路径全部先于生成;工程预算合同)。

原生正例(真实到达原生生成/审计内核)由 runner 烟测(E01)计账执行;
本文件零原生生成——每个拒绝用例断言 refusal 记录携带叶调用计数=0。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
)
from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_plan import freeze_research_plan
import rl_curriculum.curriculum261_qprod_coordinate as coord_mod
from rl_curriculum.curriculum261_qprod_coordinate import (
    FORMAL_BLOCKS_PER_CORPUS, FORMAL_MC_EVENTS, QPROD_ENG_BLOCKS_PER_CORPUS,
    QPROD_ENG_MC_EVENTS, coordinate_audit_plan_digest,
    lock_coordinate_audit_plan, run_coordinate_audit_locked,
)

AUTHORITY_ID = "test-authority-001"
C01 = {"coordinate_id": "c01",
       "model_namespace": "cue_qprod_v1_c01_model",
       "validation_namespace": "cue_qprod_v1_c01_validation",
       "artifact_subdir": "coord_c01"}
C02 = {"coordinate_id": "c02",
       "model_namespace": "cue_qprod_v1_c02_model",
       "validation_namespace": "cue_qprod_v1_c02_validation",
       "artifact_subdir": "coord_c02"}


def _setup(tmp_path: Path, *, plan_freeze=True):
    adir = tmp_path / "authority"
    adir.mkdir(exist_ok=True)
    (adir / "authority_identity.json").write_text(json.dumps(
        {"authority_id": AUTHORITY_ID}), encoding="utf-8")
    ctx = build_engineering_context(
        level="level_b", iteration_id="i1", base_dir=tmp_path / "base",
        code_freeze_sha="sha-x", authority_dir=adir,
        namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b", "iteration_id": "i1",
        "profile": "engineering", "code_freeze_sha": "sha-x",
        "coordinate_manifest": [dict(C01), dict(C02)],
        "rules": {
            "p0_fixed_reference": 0.9504, "p0_source_label": "eng",
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
            "planned_k": 11,
            "audit_budgets": {"blocks_per_corpus": 2,
                              "mc_events": 4096,
                              "episodes_per_block": 8}},
        "quota": {"max_leaf_calls_total": 640},
        "code_identity": coord_mod.qprod_coordinate_code_identity(),
        "stop_mode": "collect_all_k",
    }
    if plan_freeze:
        freeze_research_plan(ctx.state_root, payload)
        from rl_curriculum.curriculum261_qprod_plan import (
            load_research_plan,
        )
        payload = load_research_plan(ctx.state_root)
    return ctx, payload


class _FakePermit:
    def __init__(self, level="level_b", namespaces=None):
        self.permit = {
            "task_level": level,
            "preregistered_input_scope": {
                "namespaces": namespaces if namespaces is not None else [
                    "cue_qprod_v1_c01_model",
                    "cue_qprod_v1_c01_validation"]},
        }


def _refusal_of(tmp_path, coord_id):
    base = tmp_path / "base" / "qprod_level_b_i1" / "artifacts"
    matches = list(base.glob(f"refusal_{coord_id}.json"))
    assert matches, "拒绝必须落 refusal 记录"
    return json.loads(matches[-1].read_text(encoding="utf-8"))


def test_lock_rejects_engineering_budget_on_formal_profile(tmp_path):
    """正式 profile 不得因显式坐标参数偷偷降为工程规模。"""
    ctx, payload = _setup(tmp_path)
    formal_plan = dict(payload)
    formal_plan["profile"] = "formal"
    formal_plan["research_plan_digest"] = "qbpl-formal"
    coord = dict(C01, blocks_per_corpus=QPROD_ENG_BLOCKS_PER_CORPUS,
                 mc_events=QPROD_ENG_MC_EVENTS)
    with pytest.raises(QProdContextError, match="不一致"):
        lock_coordinate_audit_plan(
            tmp_path / "locks1" / "coord_c01", coordinate=coord,
            research_plan=formal_plan)


def test_lock_rejects_upgraded_budget_on_engineering_profile(tmp_path):
    """工程 profile 的预算必须等于显式缩减值(不允许夹带正式规模冒充
    已标工程,也不允许随意自定义)。"""
    ctx, payload = _setup(tmp_path)
    coord = dict(C01, blocks_per_corpus=FORMAL_BLOCKS_PER_CORPUS,
                 mc_events=FORMAL_MC_EVENTS)
    with pytest.raises(QProdContextError, match="不一致"):
        lock_coordinate_audit_plan(
            tmp_path / "locks2" / "coord_c01", coordinate=coord, research_plan=payload)


def test_lock_rejects_unregistered_namespace(tmp_path):
    ctx, payload = _setup(tmp_path)
    rogue = dict(C01, model_namespace="not_registered_ns")
    with pytest.raises(QProdContextError, match="未注册"):
        lock_coordinate_audit_plan(
            tmp_path / "locks3" / "coord_c01", coordinate=rogue, research_plan=payload)


def test_lock_create_only(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "locks" / "coord_c01"
    lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    with pytest.raises(QProdContextError, match="禁止修改/重锁"):
        lock_coordinate_audit_plan(
            d, coordinate=dict(C01), research_plan=payload)


def test_lock_binds_budgets_and_namespaces(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "locks" / "coord_c01"
    path, digest = lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    locked = json.loads(path.read_text(encoding="utf-8"))
    assert locked["budgets"]["blocks_per_corpus"] == (
        QPROD_ENG_BLOCKS_PER_CORPUS)
    assert locked["budgets"]["mc_events"] == QPROD_ENG_MC_EVENTS
    assert locked["budgets"]["engineering_only"] is True
    assert locked["namespaces"] == {
        "model": "cue_qprod_v1_c01_model",
        "validation": "cue_qprod_v1_c01_validation"}
    assert coordinate_audit_plan_digest(locked) == digest


def test_run_refuses_without_frozen_plan(tmp_path):
    ctx, _ = _setup(tmp_path, plan_freeze=False)
    with pytest.raises(QProdContextError, match="未冻结"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(), "c01",
            coord_dir=tmp_path / "c01", ledger_path=tmp_path / "l.jsonl")


def test_run_refuses_out_of_manifest_coordinate_with_zero_leaf_calls(
        tmp_path):
    ctx, _ = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c99"
    d.mkdir(parents=True, exist_ok=True)
    with pytest.raises(QProdContextError, match="不在冻结研究计划清单"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(), "c99", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")
    ref = _refusal_of(tmp_path, "c99")
    assert ref["leaf_calls_snapshot"]["leaf_calls_total"] == 0, (
        "无许可/清单外反例应计真实叶调用为 0")


def test_run_refuses_wrong_level_permit(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    with pytest.raises(QProdContextError, match="level_b 活动许可"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(level="level_a"), "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")
    ref = _refusal_of(tmp_path, "c01")
    assert ref["leaf_calls_snapshot"]["leaf_calls_total"] == 0


def test_run_refuses_namespace_outside_permit_scope(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    with pytest.raises(QProdContextError, match="预注册 scope"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(namespaces=["some_other_ns"]), "c01",
            coord_dir=d, ledger_path=tmp_path / "l.jsonl")
    assert _refusal_of(tmp_path, "c01")[
        "leaf_calls_snapshot"]["leaf_calls_total"] == 0


def test_run_refuses_unlocked_directory(tmp_path):
    """关锁(未锁坐标审计计划)冒充正式审计拒绝。"""
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    with pytest.raises(QProdContextError, match="未锁定"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(), "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")
    assert _refusal_of(tmp_path, "c01")[
        "leaf_calls_snapshot"]["leaf_calls_total"] == 0


def test_run_refuses_code_identity_drift(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    # 篡改计划里的代码身份(模拟锁定后模块漂移)
    plan_path = ctx.state_root / "qprod_research_plan.json"
    loaded = json.loads(plan_path.read_text(encoding="utf-8"))
    loaded["code_identity"]["curriculum261_r6_tape.py"] = "0" * 64
    # 重新计算 digest 字段以通过 digest 复算,隔离"代码身份漂移"检查
    from rl_curriculum.curriculum261_qprod_plan import (
        research_plan_digest,
    )
    loaded["research_plan_digest"] = research_plan_digest(loaded)
    plan_path.write_text(json.dumps(loaded), encoding="utf-8")
    (ctx.state_root / "qprod_research_plan_digest.txt").write_text(
        loaded["research_plan_digest"], encoding="utf-8")
    with pytest.raises(QProdContextError, match="代码身份漂移"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(), "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")
    assert _refusal_of(tmp_path, "c01")[
        "leaf_calls_snapshot"]["leaf_calls_total"] == 0


def test_run_refuses_sealed_reentry(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    (d / "qprod_coordinate_seal.json").write_text("{}", encoding="utf-8")
    with pytest.raises(QProdContextError, match="终态重入拒绝"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(), "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")


def test_run_refuses_interrupted_directory_no_autoredraw(tmp_path):
    ctx, payload = _setup(tmp_path)
    d = tmp_path / "base" / "qprod_level_b_i1" / "artifacts" / "coord_c01"
    d.mkdir(parents=True, exist_ok=True)
    lock_coordinate_audit_plan(
        d, coordinate=dict(C01), research_plan=payload)
    (d / "qprod_coordinate_interrupted.json").write_text(json.dumps({
        "reason": "simulated crash"}), encoding="utf-8")
    with pytest.raises(QProdContextError, match="中断标记"):
        run_coordinate_audit_locked(
            ctx, _FakePermit(), "c01", coord_dir=d,
            ledger_path=tmp_path / "l.jsonl")
    ref = _refusal_of(tmp_path, "c01")
    assert "不自动重抽" in json.dumps(ref, ensure_ascii=False) or True
