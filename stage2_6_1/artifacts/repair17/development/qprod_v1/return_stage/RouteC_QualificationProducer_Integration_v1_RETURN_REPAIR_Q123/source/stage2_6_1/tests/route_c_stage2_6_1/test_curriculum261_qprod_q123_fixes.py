# -*- coding: utf-8 -*-
"""QProd 返修轮(Q1/Q2/Q3)钉测试:ChatGPT 终验三项的修复语义。

全部零原生生成(许可/计划/reader 级;ledger 配额用 fake 叶实现)。
每条对应 REPRO_Q123.json 中一个已修复复现用例。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_curriculum261_qprod_levela as tl
import test_curriculum261_qprod_permit as tp
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,)
import test_curriculum261_qprod_aggregate as ta
from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, QProdRunSession,
)
from rl_curriculum.curriculum261_qprod_levela import (
    build_engineering_topology_fixture, run_level_a_rehearsal,
)


# ---------------------------------------------------------------- Q1
def test_q1_preplan_fail_stops_chain_below_17_steps(tmp_path):
    ctx = tl._ctx(tmp_path)
    s = QProdRunSession(ctx.state_root, level="level_a",
                        iteration_id=ctx.iteration_id)
    s.acquire({})
    inputs = tl._fixture_inputs(tmp_path)
    inputs["preplan_smoke"] = {"pass": False}
    with pytest.raises(QProdContextError, match="preplan"):
        run_level_a_rehearsal(ctx, s, inputs)
    led = json.loads((ctx.artifact_root / "level_a_step_ledger.json")
                     .read_text())
    assert led["verdict"] == "FAIL"
    assert len(led["steps"]) < 17, "前置 FAIL 不得仍 17 步 PASS"


def test_q1_missing_topology_fails_provenance(tmp_path):
    ctx = tl._ctx(tmp_path)
    s = QProdRunSession(ctx.state_root, level="level_a",
                        iteration_id=ctx.iteration_id)
    s.acquire({})
    inputs = tl._fixture_inputs(tmp_path)
    inputs.pop("gate_topology")
    with pytest.raises(QProdContextError, match="provenance"):
        run_level_a_rehearsal(ctx, s, inputs)


def test_q1_fake_topology_steps_fail_provenance(tmp_path):
    """拓扑步骤名与权威 17 步不符(仅名字对齐不够——内容对拍)。"""
    ctx = tl._ctx(tmp_path)
    s = QProdRunSession(ctx.state_root, level="level_a",
                        iteration_id=ctx.iteration_id)
    s.acquire({})
    inputs = tl._fixture_inputs(tmp_path)
    topo = build_engineering_topology_fixture()
    topo["workflow_steps"] = topo["workflow_steps"][:-1] + ["bogus"]
    inputs["gate_topology"] = topo
    with pytest.raises(QProdContextError, match="workflow_steps"):
        run_level_a_rehearsal(ctx, s, inputs)


def _producer_for_export_tests(tmp_path):
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                           / "route_c_stage2_6_2"))
    import test_ppo262_qprod_export as te

    return te


def test_q1_export_rejects_missing_terminal_journal(tmp_path):
    te = _producer_for_export_tests(tmp_path)
    ctx, out = te._producer(tmp_path)
    (ctx.state_root / "qprod_run_journal.jsonl").unlink()
    with pytest.raises(te.QProdExportError, match="真实终态不可核"):
        te.export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_q1_export_rejects_calibration_prereq_tamper(tmp_path):
    te = _producer_for_export_tests(tmp_path)
    ctx, out = te._producer(tmp_path)
    (ctx.artifact_root / "preprocessor_bundle_holdout.json").write_text(
        json.dumps({"tampered": True}), encoding="utf-8")
    with pytest.raises(te.QProdExportError, match="校准前置"):
        te.export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


def test_q1_export_rejects_raw_tamper_with_consistent_outer(tmp_path):
    """raw 数据改坏(观测字段伪值)但外层 PASS/摘要自洽仍拒。"""
    te = _producer_for_export_tests(tmp_path)
    ctx, out = te._producer(tmp_path)
    rp = ctx.artifact_root / "qprod_qualification_raw.json"
    raw = json.loads(rp.read_text())
    raw["gates"]["cue_audit_pass"]["observed"][
        "audit_digest_recomputed"] = "r15ca-FABULATED"
    rp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    with pytest.raises(te.QProdExportError, match="raw_evidence_sha256"):
        te.export_qualification_delivery(
            ctx.artifact_root, ctx.state_root, tmp_path / "d",
            expected_scope="engineering")


# ---------------------------------------------------------------- Q2
@pytest.mark.parametrize("quota", [
    {"max_leaf_calls_per_coordinate": 0,
     "max_successful_episodes_total": 128,
     "mc_events_per_coordinate": 4096, "max_native_executions": 2},
    {"max_leaf_calls_per_coordinate": -5,
     "max_successful_episodes_total": 128,
     "mc_events_per_coordinate": 4096, "max_native_executions": 2},
    {"max_leaf_calls_per_coordinate": True,
     "max_successful_episodes_total": 128,
     "mc_events_per_coordinate": 4096, "max_native_executions": 2},
])
def test_q2_nonpositive_quota_permit_rejected(tmp_path, quota):
    ctx = tp._ctx(tmp_path)
    path, _ = tp._write_permit(tmp_path / "authority", ctx, quota=quota)
    with pytest.raises(QProdContextError, match="配额"):
        tp.validate_permit(path, context=ctx)


def test_q2_unsupported_max_attempts_rejected_at_lock(tmp_path):
    import test_curriculum261_qprod_coordinate as tc

    ctx, payload = tc._setup(tmp_path)
    coord = dict(tc.C01, max_attempts=3)
    with pytest.raises(QProdContextError, match="max_attempts"):
        tc.lock_coordinate_audit_plan(
            tmp_path / "l" / "coord_c01", coordinate=coord,
            research_plan=payload)


def test_q2_nonzero_block_start_rejected_at_lock(tmp_path):
    import test_curriculum261_qprod_coordinate as tc

    ctx, payload = tc._setup(tmp_path)
    coord = dict(tc.C01, block_start_index=100)
    with pytest.raises(QProdContextError, match="block_start_index"):
        tc.lock_coordinate_audit_plan(
            tmp_path / "l2" / "coord_c01", coordinate=coord,
            research_plan=payload)


def test_q2_ledger_episode_quota_pre_reserve_blocks_generation():
    """叶边界配额:episode 单位预.reserve 在生成前抛出(用 fake 叶
    实现注入,零真实生成)。"""
    from rl_curriculum.curriculum261_qprod_coordinate import (
        QProdQuotaExceeded, _GenerationLedger,
    )

    calls = {"n": 0}

    class _FakeEp:
        def __init__(self):
            import pandas as pd

            self.df = pd.DataFrame({"x": [1.0]})
            self.hidden = pd.DataFrame({"y": [1.0]})

    def fake_once(ladder, seed, ns):
        calls["n"] += 1
        return {"D0": {"A": _FakeEp(), "B": _FakeEp()},
                "D1": {"A": _FakeEp(), "B": _FakeEp()},
                "D2": {"A": _FakeEp(), "B": _FakeEp()},
                "D3": {"A": _FakeEp(), "B": _FakeEp()}}

    ledger = _GenerationLedger(
        quota_max_episode_leaf_calls=8, coordinate_id="cx")
    ledger._once_impl = fake_once

    def guarded(ladder, seed, ns):
        ledger._reserve("once")
        ledger.leaf_calls["once"] += 1
        return fake_once(ladder, seed, ns)

    guarded(None, 1, "ns")
    with pytest.raises(QProdQuotaExceeded):
        guarded(None, 2, "ns")
    assert calls["n"] == 1, "超限调用在生成前被拦,fake 未执行"
    t = ledger.totals()
    assert t["episode_leaf_calls"] == 8
    assert "unit_note" in t


def test_q2_ledger_records_episode_unit_totals():
    from rl_curriculum.curriculum261_qprod_coordinate import (
        _GenerationLedger,
    )

    ledger = _GenerationLedger(quota_max_episode_leaf_calls=320,
                               coordinate_id="cx")
    ledger.leaf_calls = {"once": 2, "attempts": 2, "bitwise_replay": 2}
    t = ledger.totals()
    assert t["leaf_calls_total"] == 6, "外层 block 调用保留原口径"
    assert t["episode_leaf_calls"] == 48, "1 block=8 episode 叶调用"
    assert "unit_note" in t


# ---------------------------------------------------------------- Q3
def _valid_coord(art, state, digest, sd="c01", **kw):
    ta._build_coordinate(art, sd, plan_digest=digest, **kw)


def test_q3_empty_member_set_rejected(tmp_path):
    from rl_curriculum.curriculum261_qprod_aggregate import (
        _verify_coordinate,
    )

    art, state, digest = ta._setup_plan(tmp_path)
    _valid_coord(art, state, digest)
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    seal["members_sha256"] = {}
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    assert v["state"] == "invalid_structure_identity"
    assert any("成员集合" in p for p in v["problems"])


def test_q3_fake_audit_digest_rejected(tmp_path):
    from rl_curriculum.curriculum261_qprod_aggregate import (
        _verify_coordinate,
    )

    art, state, digest = ta._setup_plan(tmp_path)
    _valid_coord(art, state, digest)
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    seal["audit_digest"] = "r15ca-FABRICATED"
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    assert v["state"] == "invalid_structure_identity"
    assert any("audit_digest" in p for p in v["problems"])


def test_q3_block_index_swap_rejected_by_per_block_binding(tmp_path):
    """validation 事件 block 0<->1 换位(多重集/召回不变)——per-block
    事件摘要绑定检出。"""
    from rl_curriculum.curriculum261_qprod_aggregate import (
        _verify_coordinate,
    )

    art, state, digest = ta._setup_plan(tmp_path)
    _valid_coord(art, state, digest, blocks=2)
    tp_ = art / "c01" / "cue_event_trace.jsonl"
    rows = [json.loads(x) for x in tp_.read_text().splitlines() if x]
    for r in rows:
        if r["corpus"] == "validation":
            r["block_index"] = 1 - r["block_index"]
    tp_.write_text("\n".join(json.dumps(r, sort_keys=True)
                             for r in rows) + "\n", encoding="utf-8")
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    import hashlib

    seal["members_sha256"]["cue_event_trace.jsonl"] = hashlib.sha256(
        tp_.read_bytes()).hexdigest()
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    assert v["state"] == "invalid_structure_identity"
    assert any("per-block" in p or "block 集合" in p
               for p in v["problems"]), v["problems"]


def test_q3_missing_validation_seeds_rejected(tmp_path):
    from rl_curriculum.curriculum261_qprod_aggregate import (
        _verify_coordinate,
    )

    art, state, digest = ta._setup_plan(tmp_path)
    _valid_coord(art, state, digest)
    lp = art / "c01" / "qprod_block_seed_log.jsonl"
    rows = [json.loads(x) for x in lp.read_text().splitlines() if x]
    rows = [r for r in rows if r.get("kind") != "attempts"]
    lp.write_text("\n".join(json.dumps(r, sort_keys=True)
                            for r in rows) + "\n", encoding="utf-8")
    sp = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(sp.read_text())
    import hashlib

    seal["members_sha256"]["qprod_block_seed_log.jsonl"] = (
        hashlib.sha256(lp.read_bytes()).hexdigest())
    sp.write_text(json.dumps(seal), encoding="utf-8")
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    assert v["state"] == "invalid_structure_identity"
    assert any("validation seeds" in p or "attempts" in p
               for p in v["problems"])


def test_q3_missing_frozen_coordinate_plan_rejected(tmp_path):
    from rl_curriculum.curriculum261_qprod_aggregate import (
        _verify_coordinate,
    )

    art, state, digest = ta._setup_plan(tmp_path)
    _valid_coord(art, state, digest)
    (art / "c01" / "qprod_coordinate_audit_plan.json").unlink()
    plan = json.loads((state / "qprod_research_plan.json").read_text())
    v = _verify_coordinate(art / "c01", plan["coordinate_manifest"][0],
                           plan)
    assert v["state"] == "invalid_structure_identity"
    assert any("冻结坐标审计计划缺失" in p for p in v["problems"])


def test_q3_early_stop_excludes_post_stop_coordinates(tmp_path):
    """早停后生产/存在的坐标不进入主分析(标记违规且被排除);
    有效消费集只到停点。"""
    art, state, digest = ta._setup_plan(
        tmp_path, stop_mode="early_stop_on_first_negative")
    _valid_coord(art, state, digest, hits_per_block=10, n_events=55)
    _valid_coord(art, state, digest, sd="c02", seed_tag=2)
    r = ta.aggregate_research(art, state_root=state)
    assert r["early_stopped_at"] == "c01"
    by_id = {c["coordinate_id"]: c for c in r["coordinates"]}
    assert by_id["c02"]["state"] == "post_stop_not_consumed"
    assert by_id["c02"].get("protocol_violation")
    assert r["valid_coordinate_count"] == 1, "停后坐标不得计入有效消费"
    assert r["primary"]["not_resolved_reason"] == (
        "insufficient_coordinates")


def test_q3_early_stop_launch_guard_blocks_post_stop_coordinate(
        tmp_path):
    """启动侧:早停已触发后,其后坐标 run-coordinate 拒绝(零叶)。"""
    import test_curriculum261_qprod_coordinate as tc
    from rl_curriculum.curriculum261_qprod_coordinate import (
        run_coordinate_audit_locked,
    )
    from rl_curriculum.curriculum261_qprod_plan import (
        freeze_research_plan, load_research_plan,
    )

    (tmp_path / "coord").mkdir(parents=True, exist_ok=True)
    adir = tmp_path / "coord" / "authority"
    adir.mkdir(exist_ok=True)
    adir.joinpath("authority_identity.json").write_text(json.dumps(
        {"authority_id": tc.AUTHORITY_ID}), encoding="utf-8")
    ctx = tc.build_engineering_context(
        level="level_b", iteration_id="i1",
        base_dir=tmp_path / "coord" / "base", code_freeze_sha="sha-x",
        authority_dir=adir,
        namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b", "iteration_id": "i1",
        "profile": "engineering", "code_freeze_sha": "sha-x",
        "coordinate_manifest": [dict(tc.C01), dict(tc.C02)],
        "rules": {
            "p0_fixed_reference": 0.9504, "p0_source_label": "eng",
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
            "planned_k": 11},
        "quota": {"max_leaf_calls_total": 640},
        "code_identity": tc.coord_mod.qprod_coordinate_code_identity(),
        "stop_mode": "early_stop_on_first_negative",
    }
    freeze_research_plan(ctx.state_root, payload)
    plan = load_research_plan(ctx.state_root)
    # c01:合成 seal 触发早停(recall 远低于 P0,SE>0);
    # builder 以 coordinate_id 为键,先建 c01 再按 manifest 改名
    ta._build_coordinate(ctx.artifact_root, "c01",
                         plan_digest=plan["research_plan_digest"],
                         hits_per_block=10, n_events=55)
    import shutil

    shutil.move(str(ctx.artifact_root / "c01"),
                str(ctx.artifact_root / "coord_c01"))
    live = tc._FakePermit()
    with pytest.raises(QProdContextError, match="early_stop"):
        run_coordinate_audit_locked(
            ctx, live, "c02",
            coord_dir=ctx.artifact_root / "coord_c02",
            ledger_path=tmp_path / "l.jsonl")
    refusal = list(ctx.artifact_root.glob("refusal_c02.json"))
    assert refusal
    ref = json.loads(refusal[0].read_text())
    assert ref["leaf_calls_snapshot"]["leaf_calls_total"] == 0


def test_f1_nonquota_failure_writes_interrupted_marker_and_ledger(
        tmp_path):
    """F1(reviewer):非配额失败(生成器 RuntimeError)必须写中断标记
    +账本 interrupted 行——不得只让配额分支记账(曾为死代码回归)。"""
    import shutil

    import test_curriculum261_qprod_coordinate as tc
    import rl_curriculum.curriculum261_qprod_coordinate as cmod
    from rl_curriculum.curriculum261_qprod_coordinate import (
        run_coordinate_audit_locked,
    )
    from rl_curriculum.curriculum261_qprod_plan import (
        freeze_research_plan, load_research_plan,
    )

    (tmp_path / "coord").mkdir(parents=True, exist_ok=True)
    adir = tmp_path / "coord" / "authority"
    adir.mkdir(exist_ok=True)
    adir.joinpath("authority_identity.json").write_text(json.dumps(
        {"authority_id": tc.AUTHORITY_ID}), encoding="utf-8")
    ctx = tc.build_engineering_context(
        level="level_b", iteration_id="i1",
        base_dir=tmp_path / "coord" / "base", code_freeze_sha="sha-x",
        authority_dir=adir,
        namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b", "iteration_id": "i1",
        "profile": "engineering", "code_freeze_sha": "sha-x",
        "coordinate_manifest": [dict(tc.C01)],
        "rules": {
            "p0_fixed_reference": 0.9504, "p0_source_label": "eng",
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
            "planned_k": 11},
        "quota": {"max_leaf_calls_total": 640},
        "code_identity": cmod.qprod_coordinate_code_identity(),
        "stop_mode": "collect_all_k",
    }
    freeze_research_plan(ctx.state_root, payload)
    plan = load_research_plan(ctx.state_root)
    cd = ctx.artifact_root / "coord_c01"
    cmod.lock_coordinate_audit_plan(
        cd, coordinate=dict(tc.C01), research_plan=plan)
    ledger_path = tmp_path / "l.jsonl"
    live = tc._FakePermit()
    live.quota = {"max_leaf_calls_per_coordinate": 320}

    def boom(*a, **k):
        raise RuntimeError("simulated generator failure")

    import rl_curriculum.curriculum261_r17_cue_contract as cue_mod
    orig = cue_mod._run_cue_contract_audit_core
    cue_mod._run_cue_contract_audit_core = boom
    try:
        with pytest.raises(RuntimeError, match="simulated generator"):
            run_coordinate_audit_locked(ctx, live, "c01",
                                        coord_dir=cd,
                                        ledger_path=ledger_path)
    finally:
        cue_mod._run_cue_contract_audit_core = orig
    assert (cd / cmod.QPROD_COORDINATE_INTERRUPTED_NAME).is_file(), (
        "非配额失败必须写中断标记")
    rows = [json.loads(x) for x in
            ledger_path.read_text().splitlines() if x]
    actions = [r["action"] for r in rows]
    assert actions == ["start", "interrupted"], actions
    assert rows[-1]["error"].startswith("RuntimeError")
    # 中断目录重入拒绝(不冒充新鲜)
    with pytest.raises(QProdContextError, match="中断"):
        run_coordinate_audit_locked(ctx, tc._FakePermit(), "c01",
                                    coord_dir=cd,
                                    ledger_path=ledger_path)
