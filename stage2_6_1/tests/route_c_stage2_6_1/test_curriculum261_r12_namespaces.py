# -*- coding: utf-8 -*-
"""R12 工作包 D 测试:namespace 隔离 / 解锁守卫 / abort 守卫 /
exposure 一次性(§12 类别 21/22/23/24)。"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture()
def r12_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R12_LOCK_DIR", str(tmp_path))
    return tmp_path


def test_r12_namespace_set_isolated_from_history():
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R12_NAMESPACES,
        CURRICULUM261_SEED_NAMESPACES,
    )
    r12 = set(CURRICULUM261_R12_NAMESPACES)
    hist = set(CURRICULUM261_SEED_NAMESPACES) - r12
    assert not (r12 & hist)
    # 工作包 D 的职责 namespace 全部在位
    for needed in (
            "cue_contract_model_r12", "cue_contract_validation_r12",
            "preplan_engineering_smoke_r12",
            "shadow_calibration_main_r12", "shadow_calibration_holdout_r12",
            "shadow_supervised_main_r12", "shadow_supervised_holdout_r12",
            "shadow_fit_main_r12", "shadow_fit_holdout_r12",
            "shadow_semantic_main_r12", "shadow_semantic_validation_r12",
            "shadow_semantic_final_r12",
            "shadow_c2_independent_main_r12",
            "shadow_c2_independent_holdout_r12",
            "reference_diagnostic_r12",
            "cue_semantic_design_main_r12",
            "cue_semantic_design_validation_r12",
            "design_r12_matched_main", "design_r12_matched_validation",
            "design_r12_independent_marginal",
            "preprocess_fit_calibration_r12",
            "preprocess_fit_holdout_r12",
            "preprocess_fit_qualification_r12",
            "supervised_main_r12", "supervised_holdout_r12",
            "cue_semantic_calibration_r12", "cue_semantic_holdout_r12",
            "cue_semantic_qualification_r12",
            "calibration_r12", "calibration_holdout_r12",
            "qualification_r12",
            "c2_independent_calibration_r12",
            "c2_independent_holdout_r12",
            "c2_independent_qualification_r12",
            "stress_r12", "fresh_holdout_r12", "training_r12",
            "ppo_smoke_r12"):
        assert needed in r12, needed


def test_qualification_r12_locked_before_use(r12_lock_dir):
    """§12 类别 22:qualification namespace 提前访问拒绝。"""
    from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed

    for ns in ("qualification_r12",
               "preprocess_fit_qualification_r12",
               "c2_independent_qualification_r12",
               "cue_semantic_qualification_r12"):
        with pytest.raises(GeneratorError, match="不可访问"):
            derive261_seed(ns, "c1_opportunity", "D0", 0, 0)


def test_seed_payload_contains_namespace_string():
    from rl_curriculum.curriculum261_api import _derive261_seed_raw

    a = _derive261_seed_raw("calibration_r12", "c3_cost", "D0", 0, 0)
    b = _derive261_seed_raw("calibration_r10", "c3_cost", "D0", 0, 0)
    assert a != b, "namespace 字符串必须进入 seed payload"


def test_abort_guard_blocks_all_stages(r12_lock_dir):
    """§12 类别 23:abort 后所有 R12 正式阶段拒绝。"""
    from rl_curriculum.curriculum261_r12_namespaces import (
        mark_design_data_started,
        require_r12_iteration_active,
        write_r12_iteration_aborted,
    )

    mark_design_data_started()
    write_r12_iteration_aborted("测试:模拟 R12 abort")
    with pytest.raises(RuntimeError, match="aborted"):
        require_r12_iteration_active()
    with pytest.raises(RuntimeError, match="aborted"):
        mark_design_data_started()


def test_abort_marker_not_deletable_by_api(r12_lock_dir):
    from rl_curriculum.curriculum261_r12_namespaces import (
        r12_iteration_aborted,
        write_r12_iteration_aborted,
    )

    write_r12_iteration_aborted("测试")
    # marker 删除后 ledger 仍判定 aborted(双保险)
    from rl_curriculum.curriculum261_r12_namespaces import (
        r12_aborted_marker_path,
    )
    r12_aborted_marker_path().unlink()
    assert r12_iteration_aborted() is True


def test_exposure_marker_one_shot(r12_lock_dir):
    """§12 类别 24:exposure 一次性(running 原子独占;terminal 单向)。"""
    from rl_curriculum.curriculum261_r12_namespaces import (
        write_qualification_r12_exposure,
    )

    write_qualification_r12_exposure("qp11-test", "running")
    with pytest.raises(RuntimeError):
        write_qualification_r12_exposure("qp11-test", "running")
    write_qualification_r12_exposure("qp11-test", "completed")
    with pytest.raises(RuntimeError):
        write_qualification_r12_exposure("qp11-test", "failed")
    with pytest.raises(RuntimeError):
        write_qualification_r12_exposure("qp11-other", "running")


def test_r10_namespaces_sealed():
    """R10 namespace 永久封存:qualification_r10 在无 plan 时不可访问。"""
    from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed

    saved = os.environ.pop("CURRICULUM261_R10_LOCK_DIR", None)
    try:
        with pytest.raises(GeneratorError):
            derive261_seed("qualification_r10", "c1_opportunity",
                           "D0", 0, 0)
    finally:
        if saved is not None:
            os.environ["CURRICULUM261_R10_LOCK_DIR"] = saved


def test_r10_abort_binding_hard_gate(tmp_path, r12_lock_dir):
    """§12 R10 abort 硬闸:marker 内容/digest/零 exposure 全验证。"""
    from rl_curriculum.curriculum261_r12_cli import _r10_abort_binding

    binding = _r10_abort_binding(tmp_path)
    assert binding["retained"] is True
    assert "PairGenerationError" in binding["reason_head"]
    assert binding["r10_exposure_absent"] is True
    assert binding["r10_qualification_never_run"] is True
    assert binding["r10_design_plan_digest"].startswith("r10dp-")
    # 落盘的 artifact 可复算
    data = json.loads((tmp_path / "r10_abort_binding.json").read_text(
        encoding="utf-8"))
    assert data["root_cause_statement"].startswith(
        "historically underdetermined")
