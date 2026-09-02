# -*- coding: utf-8 -*-
"""R10 §36 治理测试:namespace 隔离、qualification 锁前不可访问、
exposure 原子性/状态机、iteration aborted、无删除/重置 API。"""

from __future__ import annotations

import json
import os

import pytest


def _env_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR", str(tmp_path))
    return tmp_path


def test_r10_namespaces_declared_and_disjoint():
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R10_NAMESPACES,
        CURRICULUM261_SEED_NAMESPACES,
    )

    assert len(CURRICULUM261_R10_NAMESPACES) == 38
    assert len(set(CURRICULUM261_R10_NAMESPACES)) == 38
    expected = {
        "reference_diagnostic_main_r10", "reference_diagnostic_holdout_r10",
        "cue_contract_model_r10", "cue_contract_validation_r10",
        "preplan_smoke_r10", "preplan_candidate_eval_r10",
        "preplan_semantic_main_r10", "preplan_semantic_validation_r10",
        "preplan_fit_main_r10", "preplan_fit_holdout_r10",
        "preplan_supervised_main_r10", "preplan_supervised_holdout_r10",
        "preplan_calibration_main_r10", "preplan_calibration_holdout_r10",
        "preplan_final_r10",
        "cue_semantic_design_main_r10",
        "cue_semantic_design_validation_r10", "design_r10_matched_main",
        "design_r10_matched_validation", "design_r10_independent_marginal",
        "preprocess_fit_calibration_r10", "preprocess_fit_holdout_r10",
        "preprocess_fit_qualification_r10", "cue_semantic_calibration_r10",
        "cue_semantic_holdout_r10", "cue_semantic_qualification_r10",
        "supervised_main_r10", "supervised_holdout_r10",
        "calibration_r10", "calibration_holdout_r10", "qualification_r10",
        "c2_independent_calibration_r10", "c2_independent_holdout_r10",
        "c2_independent_qualification_r10", "stress_r10", "fresh_holdout_r10",
        "training_r10", "ppo_smoke_r10"}
    assert set(CURRICULUM261_R10_NAMESPACES) == expected
    # 全部进入白名单
    assert set(CURRICULUM261_R10_NAMESPACES) <= set(
        CURRICULUM261_SEED_NAMESPACES)


def test_namespace_isolation_vs_history():
    from rl_curriculum.curriculum261_r10_namespaces import (
        verify_r10_namespace_isolation,
    )

    ns = verify_r10_namespace_isolation()
    assert ns["pass"], ns.get("pairwise_collisions")
    assert ns["r10_vs_historical_overlap"] == 0
    assert ns["name_space_disjoint"] is True


def test_qualification_seeds_locked_before_unlock(tmp_path, monkeypatch):
    """final namespaces 锁前不可访问(六要素守卫)。"""
    from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed

    _env_lock_dir(tmp_path, monkeypatch)
    for ns in ("qualification_r10", "preprocess_fit_qualification_r10",
               "c2_independent_qualification_r10",
               "cue_semantic_qualification_r10"):
        with pytest.raises(GeneratorError):
            derive261_seed(ns, "c2_context", "D1", 0, 0)
    # 非 final 的 R10 namespace 可访问
    s = derive261_seed("calibration_r10", "c2_context", "D1", 0, 0)
    assert isinstance(s, int) and s > 0


def test_exposure_marker_atomic_and_terminal(tmp_path, monkeypatch):
    from rl_curriculum.curriculum261_r10_namespaces import (
        QualificationR10FileLock,
        ledger_entries,
        qualification_r10_exposed,
        write_qualification_r10_exposure,
    )

    _env_lock_dir(tmp_path, monkeypatch)
    write_qualification_r10_exposure("r10dp-x", "running")
    assert qualification_r10_exposed()
    # 重复 running 拒绝(原子 O_CREAT|O_EXCL)
    with pytest.raises(RuntimeError, match="不得重跑"):
        write_qualification_r10_exposure("r10dp-x", "running")
    # ledger 先行记录
    assert any(e.get("event") == "marker_create"
               for e in ledger_entries())
    # 单向状态机:running -> completed -> 拒绝一切更新
    write_qualification_r10_exposure("r10dp-x", "completed")
    with pytest.raises(RuntimeError, match="terminal"):
        write_qualification_r10_exposure("r10dp-x", "failed")
    # 并发锁互斥
    with QualificationR10FileLock(blocking=False):
        with pytest.raises(RuntimeError, match="持有锁"):
            with QualificationR10FileLock(blocking=False):
                pass


def test_iteration_aborted_blocks_everything(tmp_path, monkeypatch):
    from rl_curriculum.curriculum261_r10_namespaces import (
        iteration_ledger_entries,
        mark_design_data_started,
        require_r10_iteration_active,
        r10_iteration_aborted,
        write_r10_iteration_aborted,
    )

    _env_lock_dir(tmp_path, monkeypatch)
    assert not r10_iteration_aborted()
    mark_design_data_started()
    assert any(e.get("event") == "design_data_started"
               for e in iteration_ledger_entries())
    write_r10_iteration_aborted("测试:评估器缺陷")
    assert r10_iteration_aborted()
    # aborted 后:design data 标记与各阶段入口全部拒绝
    with pytest.raises(RuntimeError, match="aborted"):
        mark_design_data_started()
    with pytest.raises(RuntimeError, match="aborted"):
        require_r10_iteration_active()
    # marker 不可覆盖(O_EXCL;第二次静默返回但 ledger/状态不变)
    write_r10_iteration_aborted("第二次原因不会覆盖")
    marker = json.loads(
        (tmp_path / "r10_iteration_aborted.json").read_text(
            encoding="utf-8"))
    assert marker["reason"] == "测试:评估器缺陷"


def test_no_delete_or_reset_api():
    """§16 治理:不提供 plan/marker/ledger 的删除或重置 API。"""
    import rl_curriculum.curriculum261_r10_namespaces as ns_mod

    public = [n for n in dir(ns_mod) if not n.startswith("_")]
    forbidden_words = ("delete", "reset", "remove", "clear", "unlink",
                       "rollback", "relock", "unlock_plan")
    for name in public:
        low = name.lower()
        for w in forbidden_words:
            assert w not in low, f"发现可疑 API: {name}"


def test_seed_isolation_between_r10_and_r7_namespaces():
    from rl_curriculum.curriculum261_api import _derive261_seed_raw

    vals_r7, vals_r10 = set(), set()
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        for rung in ("D0", "D1", "D2", "D3", "matched_block"):
            for p in (0, 1, 7, 39):
                for att in range(3):
                    vals_r7.add(_derive261_seed_raw(
                        "qualification_r7", fam, rung, p, att))
                    vals_r10.add(_derive261_seed_raw(
                        "qualification_r10", fam, rung, p, att))
    assert not (vals_r7 & vals_r10)
    # r10 与 r8 qualification namespace 同样零重叠
    vals_r8 = set()
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        for rung in ("D0", "D1", "D2", "D3", "matched_block"):
            for p in range(4):
                for att in range(2):
                    vals_r8.add(_derive261_seed_raw(
                        "qualification_r8", fam, rung, p, att))
    assert not (vals_r8 & vals_r10)
