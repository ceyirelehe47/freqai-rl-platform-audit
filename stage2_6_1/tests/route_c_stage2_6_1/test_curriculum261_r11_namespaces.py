# -*- coding: utf-8 -*-
"""R11 工作包 D 测试:namespace 隔离 / 解锁守卫 / abort 守卫 /
exposure 一次性(§12 类别 21/22/23/24)。"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture()
def r11_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R11_LOCK_DIR", str(tmp_path))
    return tmp_path


def test_r11_namespace_set_isolated_from_history():
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R11_NAMESPACES,
        CURRICULUM261_SEED_NAMESPACES,
    )
    r11 = set(CURRICULUM261_R11_NAMESPACES)
    hist = set(CURRICULUM261_SEED_NAMESPACES) - r11
    assert not (r11 & hist)
    # 工作包 D 的职责 namespace 全部在位
    for needed in (
            "cue_contract_model_r11", "cue_contract_validation_r11",
            "preplan_engineering_smoke_r11",
            "shadow_calibration_main_r11", "shadow_calibration_holdout_r11",
            "shadow_supervised_main_r11", "shadow_supervised_holdout_r11",
            "shadow_fit_main_r11", "shadow_fit_holdout_r11",
            "shadow_semantic_main_r11", "shadow_semantic_validation_r11",
            "shadow_semantic_final_r11",
            "shadow_c2_independent_main_r11",
            "shadow_c2_independent_holdout_r11",
            "reference_diagnostic_r11",
            "cue_semantic_design_main_r11",
            "cue_semantic_design_validation_r11",
            "design_r11_matched_main", "design_r11_matched_validation",
            "design_r11_independent_marginal",
            "preprocess_fit_calibration_r11",
            "preprocess_fit_holdout_r11",
            "preprocess_fit_qualification_r11",
            "supervised_main_r11", "supervised_holdout_r11",
            "cue_semantic_calibration_r11", "cue_semantic_holdout_r11",
            "cue_semantic_qualification_r11",
            "calibration_r11", "calibration_holdout_r11",
            "qualification_r11",
            "c2_independent_calibration_r11",
            "c2_independent_holdout_r11",
            "c2_independent_qualification_r11",
            "stress_r11", "fresh_holdout_r11", "training_r11",
            "ppo_smoke_r11"):
        assert needed in r11, needed


def test_qualification_r11_locked_before_use(r11_lock_dir):
    """§12 类别 22:qualification namespace 提前访问拒绝。"""
    from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed

    for ns in ("qualification_r11",
               "preprocess_fit_qualification_r11",
               "c2_independent_qualification_r11",
               "cue_semantic_qualification_r11"):
        with pytest.raises(GeneratorError, match="不可访问"):
            derive261_seed(ns, "c1_opportunity", "D0", 0, 0)


def test_seed_payload_contains_namespace_string():
    from rl_curriculum.curriculum261_api import _derive261_seed_raw

    a = _derive261_seed_raw("calibration_r11", "c3_cost", "D0", 0, 0)
    b = _derive261_seed_raw("calibration_r10", "c3_cost", "D0", 0, 0)
    assert a != b, "namespace 字符串必须进入 seed payload"


def test_abort_guard_blocks_all_stages(r11_lock_dir):
    """§12 类别 23:abort 后所有 R11 正式阶段拒绝。"""
    from rl_curriculum.curriculum261_r11_namespaces import (
        mark_design_data_started,
        require_r11_iteration_active,
        write_r11_iteration_aborted,
    )

    mark_design_data_started()
    write_r11_iteration_aborted("测试:模拟 R11 abort")
    with pytest.raises(RuntimeError, match="aborted"):
        require_r11_iteration_active()
    with pytest.raises(RuntimeError, match="aborted"):
        mark_design_data_started()


def test_abort_marker_not_deletable_by_api(r11_lock_dir):
    from rl_curriculum.curriculum261_r11_namespaces import (
        r11_iteration_aborted,
        write_r11_iteration_aborted,
    )

    write_r11_iteration_aborted("测试")
    # marker 删除后 ledger 仍判定 aborted(双保险)
    from rl_curriculum.curriculum261_r11_namespaces import (
        r11_aborted_marker_path,
    )
    r11_aborted_marker_path().unlink()
    assert r11_iteration_aborted() is True


def test_exposure_marker_one_shot(r11_lock_dir):
    """§12 类别 24:exposure 一次性(running 原子独占;terminal 单向)。"""
    from rl_curriculum.curriculum261_r11_namespaces import (
        write_qualification_r11_exposure,
    )

    write_qualification_r11_exposure("qp11-test", "running")
    with pytest.raises(RuntimeError):
        write_qualification_r11_exposure("qp11-test", "running")
    write_qualification_r11_exposure("qp11-test", "completed")
    with pytest.raises(RuntimeError):
        write_qualification_r11_exposure("qp11-test", "failed")
    with pytest.raises(RuntimeError):
        write_qualification_r11_exposure("qp11-other", "running")


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


def test_r10_abort_binding_hard_gate(tmp_path, r11_lock_dir):
    """§12 R10 abort 硬闸:marker 内容/digest/零 exposure 全验证。"""
    from rl_curriculum.curriculum261_r11_cli import _r10_abort_binding

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
