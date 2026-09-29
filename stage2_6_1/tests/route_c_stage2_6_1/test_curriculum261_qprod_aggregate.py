# -*- coding: utf-8 -*-
"""QProd 聚合测试(K01/K02/C03:合成坐标夹具,零原生生成)。

合成事件手工可复算(SYNTHETIC_ONLY);不复刻正式 K=11 抽样,
只测聚合 reader 的身份/复算/分类/停止语义。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import rl_curriculum.curriculum261_qprod_aggregate as agg_mod
from rl_curriculum.curriculum261_qprod_aggregate import (
    aggregate_research, write_aggregate_report,
)
from rl_curriculum.curriculum261_qprod_plan import freeze_research_plan
from rl_curriculum.curriculum261_r17_cue_contract import (
    _cluster_bootstrap, _per_block_event_counts,
)

SYNTHETIC_NOTE = "SYNTHETIC_ONLY:手工合成事件夹具,无研究代表性"


def _events_for(blocks: int, *, hits_per_block: int, n_events: int,
                seed_tag: int) -> list[dict]:
    """确定性合成事件表(手工可复算;事件结构=core 落盘 schema)。"""
    events = []
    for b in range(blocks):
        for j in range(n_events):
            detected = 1 if j < hits_per_block else 0
            events.append({
                "corpus": "validation", "block_index": b,
                "cue_bar": 20 + ((j * 7 + seed_tag) % 200),
                "primary_present": 1, "k_actual": (j + seed_tag) % 5,
                "mirror_positions": [1, 2], "mirror_candidates": 2,
                "effective_sigma_bps": 26.0,
                "actual_noise": 0.001, "cue_read": 0.0106,
                "detected": bool(detected),
            })
    return events


def _build_coordinate(art_dir: Path, subdir: str, *, blocks=4,
                      hits_per_block=52, n_events=55, seed_tag=0,
                      state="valid", plan_digest="qbpl-x",
                      events_override=None):
    coord_dir = art_dir / subdir
    coord_dir.mkdir(parents=True, exist_ok=True)
    events = events_override if events_override is not None else (
        _events_for(blocks, hits_per_block=hits_per_block,
                    n_events=n_events, seed_tag=seed_tag))
    trace = coord_dir / "cue_event_trace.jsonl"
    trace.write_text("\n".join(json.dumps(e, sort_keys=True)
                               for e in events) + "\n", encoding="utf-8")
    validation = [e for e in events if e["corpus"] == "validation"]
    boot = _cluster_bootstrap(_per_block_event_counts(validation))
    if state == "interrupted":
        (coord_dir / "qprod_coordinate_interrupted.json").write_text(
            json.dumps({"reason": "simulated"}), encoding="utf-8")
        return coord_dir
    if state == "missing":
        trace.unlink()
        return coord_dir
    model_ns = NS_MODEL[subdir]
    validation_ns = NS_VALIDATION[subdir]
    report = {
        "format": "cur261-r17-cue-contract-audit-v1",
        "audit_namespaces": {"model": model_ns,
                             "validation": validation_ns},
        "audit_blocks_per_corpus": blocks,
        "p_contract": 0.94 + 0.001 * seed_tag,
        "direct_generator": {
            "validation": {
                "empirical_recall": boot["point"],
                "block_cluster": {"point": boot["point"],
                                  "se": boot["se"]}}},
    }
    (coord_dir / "cue_contract_audit.json").write_text(
        json.dumps(report), encoding="utf-8")
    # block seed 日志(model once + validation attempts;seed 与派生
    # 公式对拍由 reader 复算——合成夹具用真实派生公式生成)
    from rl_curriculum.curriculum261_r6_tape import derive261_block_seed

    log = []
    for i in range(blocks):
        log.append({"kind": "once", "namespace": model_ns,
                    "block_seed": int(derive261_block_seed(
                        model_ns, i, 0))})
        log.append({"kind": "attempts",
                    "namespace": validation_ns,
                    "block_index": i,
                    "block_seed": int(derive261_block_seed(
                        validation_ns, i, 0)),
                    "selected_attempt": 0, "attempts_made": 1})
    (coord_dir / "qprod_block_seed_log.jsonl").write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in log) + "\n",
        encoding="utf-8")
    members = {}
    for name in ("cue_contract_audit.json", "cue_event_trace.jsonl",
                 "qprod_block_seed_log.jsonl"):
        members[name] = hashlib.sha256(
            (coord_dir / name).read_bytes()).hexdigest()
    (coord_dir / "qprod_coordinate_seal.json").write_text(json.dumps({
        "format": "cur261-qprod-coordinate-seal-v1",
        "coordinate_id": subdir,
        "research_plan_digest": plan_digest,
        "audit_digest": "r15ca-synth",
        "members_sha256": members,
        "summary": {
            "recall_validation": boot["point"],
            "se_validation": boot["se"],
            "p_contract_local": report["p_contract"],
            "audit_pass": True, "engineering_only": True,
        },
        "generation": {"leaf_calls_total": 8},
    }), encoding="utf-8")
    (coord_dir / "SYNTHETIC_ONLY.md").write_text(
        f"# SYNTHETIC_ONLY\n\n{SYNTHETIC_NOTE}\n", encoding="utf-8")
    return coord_dir


COORDS = [
    {"coordinate_id": f"c{i:02d}",
     "model_namespace": f"cue_dev_r25_c{i:02d}_model",
     "validation_namespace": f"cue_dev_r25_c{i:02d}_validation",
     "artifact_subdir": f"c{i:02d}"}
    for i in range(1, 12)
]
NS_MODEL = {c["coordinate_id"]: c["model_namespace"] for c in COORDS}
NS_VALIDATION = {c["coordinate_id"]: c["validation_namespace"]
                 for c in COORDS}


def _setup_plan(tmp_path: Path, *, coords=None, stop_mode="collect_all_k",
                planned_k=11):
    coords = coords if coords is not None else COORDS
    art = tmp_path / "artifacts"
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b", "iteration_id": "agg",
        "profile": "engineering", "code_freeze_sha": "s",
        "coordinate_manifest": coords,
        "rules": {
            "p0_fixed_reference": 0.950431552876822,
            "p0_source_label": "synthetic test",
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
            "planned_k": planned_k},
        "quota": {}, "code_identity": {}, "stop_mode": stop_mode,
    }
    _, digest = freeze_research_plan(state, payload)
    return art, state, digest


def test_full_k11_synthetic_recomputable(tmp_path):
    art, state, digest = _setup_plan(tmp_path)
    for i, c in enumerate(COORDS):
        _build_coordinate(art, c["artifact_subdir"], seed_tag=i,
                          plan_digest=digest)
    report = aggregate_research(art, state_root=state)
    assert report["valid_coordinate_count"] == 11
    primary = report["primary"]
    # delta/SE 独立复算
    recalls = []
    ses = []
    for i, c in enumerate(COORDS):
        events = [json.loads(x) for x in (
            art / c["artifact_subdir"] /
            "cue_event_trace.jsonl").read_text().splitlines() if x.strip()]
        boot = _cluster_bootstrap(_per_block_event_counts(events))
        recalls.append(boot["point"])
        ses.append(boot["se"])
    p0 = 0.950431552876822
    import math

    delta_bar = sum(p0 - r for r in recalls) / 11
    s_raw = math.sqrt(sum(s * s for s in ses)) / 11
    assert abs(primary["delta_bar"] - delta_bar) < 1e-12
    assert abs(primary["s_raw"] - s_raw) < 1e-12
    assert abs(primary["s_analysis"] - 1.5 * s_raw) < 1e-12
    # v4 分类互斥;方向独立
    assert primary["magnitude"] in (
        "within_equivalence_bounds", "beyond_positive_margin",
        "beyond_negative_margin", "inconclusive")
    assert primary["planned_k"] == 11
    assert primary["k_coordinates"] == 11


def test_fewer_than_k_forced_inconclusive(tmp_path):
    art, state, digest = _setup_plan(tmp_path)
    for i, c in enumerate(COORDS[:5]):
        _build_coordinate(art, c["artifact_subdir"], seed_tag=i,
                          plan_digest=digest)
    report = aggregate_research(art, state_root=state)
    assert report["valid_coordinate_count"] == 5
    assert report["primary"]["magnitude"] == "inconclusive"
    assert report["primary"]["not_resolved_reason"] == (
        "insufficient_coordinates")
    assert report["primary"].get("descriptive_only") is True


def test_duplicate_events_across_coordinates_invalid(tmp_path):
    art, state, digest = _setup_plan(tmp_path)
    shared = _events_for(4, hits_per_block=52, n_events=55, seed_tag=3)
    _build_coordinate(art, "c01", events_override=shared,
                      plan_digest=digest, seed_tag=0)
    _build_coordinate(art, "c02", events_override=list(shared),
                      plan_digest=digest, seed_tag=1)
    report = aggregate_research(art, state_root=state)
    by_id = {c["coordinate_id"]: c for c in report["coordinates"]}
    assert by_id["c01"]["state"] == "invalid_structure_identity"
    for c in COORDS[:5]:
        _build_coordinate(art, c["artifact_subdir"], seed_tag=1,
                          plan_digest=digest)

def test_summary_only_json_without_originals_rejected(tmp_path):
    """只有 recall/SE 汇总(无事件原件)不能充当有效坐标。"""
    art, state, digest = _setup_plan(tmp_path)
    c = COORDS[0]
    d = art / c["artifact_subdir"]
    d.mkdir(parents=True, exist_ok=True)
    # seal 声称了 recall/SE 但成员事件文件缺失
    (d / "qprod_coordinate_seal.json").write_text(json.dumps({
        "format": "cur261-qprod-coordinate-seal-v1",
        "coordinate_id": c["coordinate_id"],
        "research_plan_digest": digest,
        "members_sha256": {
            "cue_contract_audit.json": "0" * 64,
            "cue_event_trace.jsonl": "0" * 64,
            "qprod_block_seed_log.jsonl": "0" * 64},
        "summary": {"recall_validation": 0.95, "se_validation": 0.001,
                    "p_contract_local": 0.95, "audit_pass": True},
    }), encoding="utf-8")
    report = aggregate_research(art, state_root=state)
    assert report["coordinates"][0]["state"] == (
        "invalid_structure_identity")


def test_tampered_summary_vs_events_rejected(tmp_path):
    """seal recall 与事件复算矛盾(缓存污染/换来源)拒绝。"""
    art, state, digest = _setup_plan(tmp_path)
    _build_coordinate(art, "c01", plan_digest=digest)
    seal_path = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["summary"]["recall_validation"] = 0.999999
    seal_path.write_text(json.dumps(seal), encoding="utf-8")
    report = aggregate_research(art, state_root=state)
    assert report["coordinates"][0]["state"] == (
        "invalid_structure_identity")
    assert any("复算" in p for p in report["coordinates"][0]["problems"])


def test_namespace_attribution_mismatch_rejected(tmp_path):
    """报告实际 namespace 与清单不一致(清单外来源)拒绝。"""
    art, state, digest = _setup_plan(tmp_path)
    _build_coordinate(art, "c01", plan_digest=digest)
    rp = art / "c01" / "cue_contract_audit.json"
    report_json = json.loads(rp.read_text(encoding="utf-8"))
    report_json["audit_namespaces"]["validation"] = "rogue_ns"
    rp.write_text(json.dumps(report_json), encoding="utf-8")
    # 更新 seal 成员摘要保持自洽(分离 namespace 归属检查)
    seal_path = art / "c01" / "qprod_coordinate_seal.json"
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["members_sha256"]["cue_contract_audit.json"] = hashlib.sha256(
        rp.read_bytes()).hexdigest()
    seal_path.write_text(json.dumps(seal), encoding="utf-8")
    r = aggregate_research(art, state_root=state)
    assert r["coordinates"][0]["state"] == "invalid_structure_identity"
    assert any("namespace" in p
               for p in r["coordinates"][0]["problems"])


def test_interrupted_and_missing_classification(tmp_path):
    art, state, digest = _setup_plan(tmp_path)
    _build_coordinate(art, "c01", state="interrupted",
                      plan_digest=digest)
    _build_coordinate(art, "c02", state="missing", plan_digest=digest)
    report = aggregate_research(art, state_root=state)
    by_id = {c["coordinate_id"]: c for c in report["coordinates"]}
    assert by_id["c01"]["state"] == "interrupted_incomplete"
    assert by_id["c02"]["state"] == "missing"
    assert report["primary"]["not_resolved_reason"] == (
        "no_valid_coordinates")


def test_local_anchor_not_equal_p0_is_not_a_deletion_reason(tmp_path):
    """局部 p_contract ≠ P0 不删坐标(C03:两个统计对象分离)。"""
    art, state, digest = _setup_plan(tmp_path)
    for i, c in enumerate(COORDS):
        _build_coordinate(art, c["artifact_subdir"], seed_tag=i,
                          plan_digest=digest)
    # 每坐标局部锚(p_contract_local)互不相同且 != P0
    report = aggregate_research(art, state_root=state)
    locals_ = [c["p_contract_local"] for c in report["coordinates"]]
    assert all(abs(v - 0.950431552876822) > 1e-9 for v in locals_)
    assert report["valid_coordinate_count"] == 11
    assert report["anchor"]["p0_fixed_reference"] == 0.950431552876822
    assert "局部" in json.dumps(report["anchor"], ensure_ascii=False)


def test_stop_modes_early_stop_vs_collect_all(tmp_path):
    """两个事前可选停止模式(K02);早停=首个统计负结果即停。"""
    # collect_all:全 11 收齐,统计负结果保留
    art, state, digest = _setup_plan(
        tmp_path / "all", stop_mode="collect_all_k")
    for i, c in enumerate(COORDS):
        # 大 miss(52/55→ 低 recall ⇒ delta 远超 margin)制造负结果
        _build_coordinate(art, c["artifact_subdir"], seed_tag=i,
                          hits_per_block=10, n_events=55,
                          plan_digest=digest)
    r = aggregate_research(art, state_root=state)
    assert r["stop_mode"] == "collect_all_k"
    assert r["early_stopped_at"] is None
    assert r["valid_coordinate_count"] == 11
    assert r["primary"]["magnitude"] == "beyond_positive_margin"

    # early_stop:首个负结果即停,后续坐标未生产也如实描述
    art2, state2, digest2 = _setup_plan(
        tmp_path / "early", stop_mode="early_stop_on_first_negative")
    _build_coordinate(art2, "c01", seed_tag=0, hits_per_block=10,
                      n_events=55, plan_digest=digest2)
    r2 = aggregate_research(art2, state_root=state2)
    assert r2["early_stopped_at"] == "c01"
    assert r2["coordinates"][0].get("statistical_negative") is True
    assert r2["valid_coordinate_count"] == 1
    assert r2["primary"]["not_resolved_reason"] == (
        "insufficient_coordinates")


def test_degenerate_zero_se_coordinate_kept_but_primary_not_resolved(
        tmp_path):
    """SE=0(validation 全中,极小样本)坐标保留;v4 适用条件不满足
    ⇒ 主分类如实不决,不删坐标、不另立公式(E01 run2 c02 实况)。"""
    art, state, digest = _setup_plan(tmp_path)
    # c01 正常;c02 全中事件(hit=n)⇒ bootstrap SE=0
    _build_coordinate(art, "c01", plan_digest=digest, seed_tag=1)
    _build_coordinate(art, "c02", plan_digest=digest, seed_tag=2,
                      hits_per_block=55, n_events=55)
    report = aggregate_research(art, state_root=state)
    assert report["valid_coordinate_count"] == 2, (
        "退化 SE 坐标不得被删除")
    assert report["primary"]["magnitude"] == "inconclusive"
    assert report["primary"]["not_resolved_reason"] == (
        "degenerate_se_prevents_v4_application")
    assert report["primary"]["degenerate_se_coordinates"] == ["c02"]
    assert report["primary"]["descriptive_only"] is True


def test_level_b_aggregation_does_not_touch_level_a(tmp_path):
    art, state, digest = _setup_plan(tmp_path)
    a_state = tmp_path / "level_a_state"
    a_state.mkdir()
    (a_state / "qprod_run_journal.jsonl").write_text(json.dumps({
        "event": "run_terminal_recorded", "status": "completed",
        "verdict": "FAIL", "plan_digest": "qapl-a",
        "utc": "2026-09-30T00:00:00+00:00"}) + "\n", encoding="utf-8")
    _build_coordinate(art, "c01", plan_digest=digest)
    report = aggregate_research(art, state_root=state,
                                level_a_state_root=a_state)
    # B 只读引用 A 终态;A 终态仍为 FAIL(B 不能救绿)
    assert report["level_a_terminal"]["terminal_events"][0][
        "verdict"] == "FAIL"
    after = json.loads((a_state / "qprod_run_journal.jsonl")
                       .read_text(encoding="utf-8").splitlines()[0])
    assert after["verdict"] == "FAIL"
