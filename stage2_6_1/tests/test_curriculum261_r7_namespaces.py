# -*- coding: utf-8 -*-
"""R7 §34 测试:Governance(§15/§16)——namespace 隔离、六要素守卫、
marker 硬合同、§16.2 aborted/plan 不可删/不重锁、并发锁。"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture()
def r7_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R7_LOCK_DIR", str(tmp_path))
    return tmp_path


def test_namespace_isolation(r7_lock_dir):
    from rl_curriculum.curriculum261_r7_namespaces import (
        verify_r7_namespace_isolation,
    )

    rep = verify_r7_namespace_isolation()
    assert len(rep["r7_namespaces"]) == 18
    assert rep["name_space_disjoint"] is True
    assert rep["r7_vs_historical_overlap"] == 0
    assert rep["pairwise_collisions"] == []
    assert rep["pass"] is True
    for ns in rep["r7_namespaces"]:
        assert "_r7" in ns


def test_qualification_guard_locked_before_unlock(r7_lock_dir):
    """六要素守卫:无 plan/pack/attestation 时 final namespace 不可派生。"""
    from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed

    for ns in ("qualification_r7", "preprocess_fit_qualification_r7",
               "c2_independent_qualification_r7"):
        with pytest.raises(GeneratorError):
            derive261_seed(ns, "c2_context", "D0", 0, 0)
    # 非 final 的 r7 namespace 畅通
    s = derive261_seed("calibration_r7", "c2_context", "D0", 0, 0)
    assert isinstance(s, int)


def test_marker_exclusive_and_one_way(r7_lock_dir):
    from rl_curriculum.curriculum261_r7_namespaces import (
        write_qualification_r7_exposure,
    )

    write_qualification_r7_exposure("qp7-test", "running")
    with pytest.raises(RuntimeError):
        write_qualification_r7_exposure("qp7-test", "running")
    write_qualification_r7_exposure("qp7-test", "completed")
    with pytest.raises(RuntimeError):
        write_qualification_r7_exposure("qp7-test", "failed")
    with pytest.raises(RuntimeError):
        write_qualification_r7_exposure("qp7-test", "running")


def test_no_delete_api_in_source():
    """源码断验:模块不提供任何 marker/plan/ledger 删除或重置 API。"""
    from pathlib import Path

    import rl_curriculum.curriculum261_r7_namespaces as ns_mod

    src = Path(ns_mod.__file__).read_text(encoding="utf-8")
    for banned in ("def delete", "def reset", ".unlink()", "os.remove",
                   "shutil.rmtree"):
        assert banned not in src, f"禁止出现 {banned!r}"


def test_ledger_survives_marker_deletion(r7_lock_dir):
    """marker 被手动删除时 ledger 仍判定已暴露。"""
    from rl_curriculum.curriculum261_r7_namespaces import (
        ledger_entries,
        qualification_r7_exposed,
        qualification_r7_exposure_marker,
        write_qualification_r7_exposure,
    )

    write_qualification_r7_exposure("qp7-x", "running")
    assert qualification_r7_exposed() is True
    qualification_r7_exposure_marker().unlink()  # 模拟手动删除
    assert qualification_r7_exposed() is True  # ledger 兜底
    assert any(e.get("event") == "marker_create"
               for e in ledger_entries())


def test_concurrent_lock_rejected(r7_lock_dir):
    from rl_curriculum.curriculum261_r7_namespaces import (
        QualificationR7FileLock,
    )

    with QualificationR7FileLock(blocking=False):
        with pytest.raises(RuntimeError):
            with QualificationR7FileLock(blocking=False):
                pass


def test_aborted_contract(r7_lock_dir):
    """§16.2:design data 已生成后 aborted => 一切继续执行被拒绝。"""
    from rl_curriculum.curriculum261_r7_namespaces import (
        design_data_started,
        mark_design_data_started,
        r7_iteration_aborted,
        require_r7_iteration_active,
        write_r7_iteration_aborted,
    )

    assert not design_data_started() and not r7_iteration_aborted()
    mark_design_data_started()
    assert design_data_started()
    require_r7_iteration_active()  # 未 aborted 仍可执行
    write_r7_iteration_aborted("test: 统计代码缺陷")
    assert r7_iteration_aborted()
    with pytest.raises(RuntimeError):
        require_r7_iteration_active()
    with pytest.raises(RuntimeError):
        mark_design_data_started()  # aborted 后不得再生成数据


def test_design_plan_lock_no_overwrite(r7_lock_dir):
    """design plan 已存在即拒——不删旧重锁(§16.2/R6 教训)。"""
    from rl_curriculum.curriculum261_r7_design import (
        lock_design_plan_r7,
    )

    plan = {"format": "x", "iteration": "r7"}
    path, digest = lock_design_plan_r7(r7_lock_dir, plan)
    assert path.is_file() and digest.startswith("r7dp-")
    with pytest.raises(RuntimeError):
        lock_design_plan_r7(r7_lock_dir, {"format": "x2"})


def test_qualification_plan_lock_no_overwrite(r7_lock_dir):
    from rl_curriculum.curriculum261_r7_plan import (
        lock_plan_r7,
        plan_digest_r7,
    )

    plan = {"format": "x", "iteration": "r7", "code_identity": {}}
    path, digest = lock_plan_r7(plan)
    assert digest.startswith("qp7-")
    with pytest.raises(RuntimeError):
        lock_plan_r7({**plan, "extra": 1})
    # digest 复算稳定
    assert plan_digest_r7(plan) == digest
