# -*- coding: utf-8 -*-
"""QProd 计划层测试(A03:两阶段计划/冻结时序/结构校验/create-only)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rl_curriculum.curriculum261_qprod_plan as plan_mod
from rl_curriculum.curriculum261_qprod_plan import (
    freeze_qualification_plan, freeze_research_plan,
    load_qualification_plan, load_research_plan,
    qualification_plan_digest, research_plan_digest,
    research_plan_structure_problems,
)


def _level_b_payload(**over):
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b",
        "iteration_id": "i1",
        "profile": "engineering",
        "code_freeze_sha": "sha",
        "coordinate_manifest": [
            {"coordinate_id": "c01",
             "model_namespace": "cue_qprod_v1_c01_model",
             "validation_namespace": "cue_qprod_v1_c01_validation",
             "artifact_subdir": "coord_c01"},
            {"coordinate_id": "c02",
             "model_namespace": "cue_qprod_v1_c02_model",
             "validation_namespace": "cue_qprod_v1_c02_validation",
             "artifact_subdir": "coord_c02"},
        ],
        "rules": {
            "p0_fixed_reference": 0.950431552876822,
            "p0_source_label": "historical engineering reference",
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
            "planned_k": 11},
        "quota": {"max_leaf_calls_total": 640},
        "code_identity": {"m.py": "h1"},
        "stop_mode": "collect_all_k",
    }
    payload.update(over)
    return payload


def test_research_plan_freeze_and_digest_roundtrip(tmp_path):
    _, digest = freeze_research_plan(tmp_path, _level_b_payload())
    assert digest.startswith("qbpl-")
    loaded = load_research_plan(tmp_path)
    assert loaded["research_plan_digest"] == digest
    assert research_plan_digest(loaded) == digest


def test_research_plan_create_only(tmp_path):
    freeze_research_plan(tmp_path, _level_b_payload())
    with pytest.raises(Exception, match="禁止修改/重锁"):
        freeze_research_plan(tmp_path, _level_b_payload())


def test_research_plan_tamper_detected(tmp_path):
    freeze_research_plan(tmp_path, _level_b_payload())
    path = tmp_path / plan_mod.QPROD_RESEARCH_PLAN_NAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["rules"]["margin"] = 0.5
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="复算不一致"):
        load_research_plan(tmp_path)


def test_stop_mode_must_be_predeclared(tmp_path):
    with pytest.raises(Exception, match="事前选定"):
        freeze_research_plan(
            tmp_path, _level_b_payload(stop_mode="decide_later"))


class TestLevelBStructure:
    def test_duplicate_coordinate_id(self):
        p = _level_b_payload()
        p["coordinate_manifest"][1]["coordinate_id"] = "c01"
        assert any("id 重复" in x
                   for x in research_plan_structure_problems(p))

    def test_same_sampling_space_impersonation(self):
        p = _level_b_payload()
        p["coordinate_manifest"][1]["validation_namespace"] = (
            p["coordinate_manifest"][1]["model_namespace"])
        assert any("相同抽样空间" in x
                   for x in research_plan_structure_problems(p))

    def test_namespace_reuse_across_coordinates(self):
        p = _level_b_payload()
        p["coordinate_manifest"][1]["model_namespace"] = (
            p["coordinate_manifest"][0]["model_namespace"])
        assert any("跨坐标重复" in x
                   for x in research_plan_structure_problems(p))

    def test_wrong_delta_definition(self):
        p = _level_b_payload()
        p["rules"]["delta_definition"] = "recall - P0"
        assert any("delta_definition" in x
                   for x in research_plan_structure_problems(p))

    def test_missing_artifact_location(self):
        p = _level_b_payload()
        del p["coordinate_manifest"][0]["artifact_subdir"]
        assert any("独立产物位置" in x
                   for x in research_plan_structure_problems(p))


class TestLevelARunPlan:
    def test_level_a_run_scope_shape(self):
        p = _level_b_payload(level="level_a")
        p.pop("coordinate_manifest")
        p["run_scope"] = {
            "entry": "e", "gate_set": ["g1"], "budget": {"b": 1},
            "exposure_policy": "one_shot_window"}
        p["rules"] = {"gate_semantics_ref": "judge_qualification_gates"}
        assert research_plan_structure_problems(p) == []

    def test_level_a_missing_run_scope(self):
        p = _level_b_payload(level="level_a")
        p.pop("coordinate_manifest")
        assert any("run_scope" in x
                   for x in research_plan_structure_problems(p))

    def test_unknown_level(self):
        p = _level_b_payload(level="level_c")
        assert any("非法" in x
                   for x in research_plan_structure_problems(p))


class TestQualificationPlan:
    def test_requires_prior_plan_and_calibration(self, tmp_path):
        payload = {
            "format": "cur261-qprod-qualification-plan-v1",
            "level": "level_a", "iteration_id": "i",
            "profile": "engineering", "scope": "engineering",
        }
        with pytest.raises(Exception, match="prior_plan_digest"):
            freeze_qualification_plan(tmp_path, dict(payload))
        payload["prior_plan_digest"] = "qbpl-x"
        with pytest.raises(Exception, match="calibration"):
            freeze_qualification_plan(tmp_path, dict(payload))
        payload["calibration_artifacts"] = {"a.json": "h"}
        _, digest = freeze_qualification_plan(tmp_path, payload)
        assert digest.startswith("qapl-")
        assert digest != payload["prior_plan_digest"], (
            "两种计划 digest 前缀不同,不能用同名 digest 混为一件")
        loaded = load_qualification_plan(tmp_path)
        assert qualification_plan_digest(loaded) == digest

    def test_create_only(self, tmp_path):
        payload = {
            "format": "cur261-qprod-qualification-plan-v1",
            "level": "level_a", "iteration_id": "i",
            "profile": "engineering", "scope": "engineering",
            "prior_plan_digest": "qbpl-x",
            "calibration_artifacts": {"a.json": "h"},
        }
        freeze_qualification_plan(tmp_path, dict(payload))
        with pytest.raises(Exception, match="禁止修改/重锁"):
            freeze_qualification_plan(tmp_path, dict(payload))
