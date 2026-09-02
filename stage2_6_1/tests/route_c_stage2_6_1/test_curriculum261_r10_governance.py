# -*- coding: utf-8 -*-
"""R10 §29 Governance 测试:code freeze SHA / formal data 后 source
drift 拒绝 / plan 不可删除 / abort 不可恢复 / exposure 原子 / final
namespace 不可重跑。"""

from __future__ import annotations

import json

import pytest


def test_code_freeze_write_and_verify(tmp_path):
    from rl_curriculum.curriculum261_r10_dependencies import (
        source_tree_digest_r10,
        verify_r10_code_freeze,
        write_r10_code_freeze,
    )

    payload = write_r10_code_freeze(tmp_path, code_freeze_sha="A" * 40)
    assert payload["code_freeze_sha"] == "A" * 40
    first = verify_r10_code_freeze(tmp_path)
    assert first["pass"] is True
    assert first["code_freeze_sha"] == "A" * 40
    # 篡改 freeze 清单中的一个模块哈希 -> fail closed
    doc = json.loads((tmp_path / "r10_code_freeze.json").read_text(
        encoding="utf-8"))
    some_mod = next(iter(doc["modules"]))
    doc["modules"][some_mod] = "0" * 64
    (tmp_path / "r10_code_freeze.json").write_text(
        json.dumps(doc), encoding="utf-8")
    drifted = verify_r10_code_freeze(tmp_path)
    assert drifted["pass"] is False
    assert some_mod in drifted["drifted_modules"]


def test_code_freeze_requires_existing_file(tmp_path):
    from rl_curriculum.curriculum261_r10_dependencies import (
        verify_r10_code_freeze,
    )

    result = verify_r10_code_freeze(tmp_path)
    assert result["pass"] is False
    assert "不存在" in result["error"]


def test_source_tree_digest_covers_all_r10_modules():
    from rl_curriculum.curriculum261_r10_dependencies import (
        R10_CODE_MODULES,
        source_tree_digest_r10,
    )

    tree = source_tree_digest_r10()
    assert tree["all_present"] is True
    assert set(tree["modules"]) == set(R10_CODE_MODULES)
    assert len(R10_CODE_MODULES) == 21
    assert tree["source_tree_digest"].startswith("r10src-")


def test_rehearsal_plan_not_overwritable(tmp_path):
    from rl_curriculum.curriculum261_r10_plan import (
        build_rehearsal_qualification_plan_r10,
        load_locked_qualification_plan_r10,
        lock_qualification_plan_r10,
    )

    plan, digest = build_rehearsal_qualification_plan_r10(
        pack={"digest": "r10pk-x"}, stage_summary={"pass": True},
        final_namespace="preplan_final_r10",
        fit_namespace="preplan_fit_main_r10")
    lock_qualification_plan_r10(tmp_path, plan)
    loaded, d2 = load_locked_qualification_plan_r10(tmp_path)
    assert d2 == digest
    assert json.dumps(loaded, sort_keys=True) == json.dumps(
        {**plan, "plan_digest": digest}, sort_keys=True)
    with pytest.raises(RuntimeError, match="禁止删除/覆盖/重锁"):
        lock_qualification_plan_r10(tmp_path, plan)


def test_rehearsal_plan_tamper_rejected(tmp_path):
    from rl_curriculum.curriculum261_r10_plan import (
        build_rehearsal_qualification_plan_r10,
        load_locked_qualification_plan_r10,
        lock_qualification_plan_r10,
    )

    plan, _ = build_rehearsal_qualification_plan_r10(
        pack={"digest": "r10pk-x"}, stage_summary={"pass": True},
        final_namespace="preplan_final_r10",
        fit_namespace="preplan_fit_main_r10")
    lock_qualification_plan_r10(tmp_path, plan)
    doc = json.loads((tmp_path / "qualification_plan_r10.json"
                      ).read_text(encoding="utf-8"))
    doc["rehearsal"] = False  # 篡改
    (tmp_path / "qualification_plan_r10.json").write_text(
        json.dumps(doc), encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest 复算不一致"):
        load_locked_qualification_plan_r10(tmp_path)


def test_iteration_aborted_blocks_everything(tmp_path, monkeypatch):
    from rl_curriculum import curriculum261_r10_namespaces as ns

    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR", str(tmp_path))
    ns.write_r10_iteration_aborted("测试:代码缺陷演练")
    with pytest.raises(RuntimeError, match="永久结束"):
        ns.require_r10_iteration_active()
    with pytest.raises(RuntimeError, match="永久结束"):
        ns.mark_design_data_started()
    # marker 不可删除的等价检查:无 delete/reset API
    public = [n for n in dir(ns) if not n.startswith("_")]
    assert not any("delete" in n or "reset" in n for n in public)


def test_exposure_marker_atomic_and_terminal(tmp_path, monkeypatch):
    from rl_curriculum import curriculum261_r10_namespaces as ns

    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR", str(tmp_path))
    ns.write_qualification_r10_exposure("qp10-" + "a" * 64,
                                        status="running")
    with pytest.raises(RuntimeError, match="不得重跑"):
        ns.write_qualification_r10_exposure("qp10-" + "a" * 64,
                                            status="running")
    ns.write_qualification_r10_exposure("qp10-" + "a" * 64,
                                        status="completed")
    with pytest.raises(RuntimeError, match="永久拒绝"):
        ns.write_qualification_r10_exposure("qp10-" + "a" * 64,
                                            status="failed")
    assert ns.qualification_r10_exposed() is True


def test_qualification_seeds_locked_before_unlock(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR", str(tmp_path))
    from rl_curriculum.curriculum261_api import GeneratorError, \
        derive261_seed

    for ns in ("qualification_r10", "preprocess_fit_qualification_r10",
               "c2_independent_qualification_r10",
               "cue_semantic_qualification_r10"):
        with pytest.raises(GeneratorError):
            derive261_seed(ns, "c2_context", "D0", 0, 0)


def test_r10_namespaces_declared_and_disjoint():
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R10_NAMESPACES,
        CURRICULUM261_R9_NAMESPACES,
        CURRICULUM261_SEED_NAMESPACES,
    )

    assert len(CURRICULUM261_R10_NAMESPACES) == 38
    assert len(set(CURRICULUM261_R10_NAMESPACES)) == 38
    assert not (set(CURRICULUM261_R10_NAMESPACES)
                & set(CURRICULUM261_R9_NAMESPACES))
    assert set(CURRICULUM261_R10_NAMESPACES) <= set(
        CURRICULUM261_SEED_NAMESPACES)
    # 规范点名的关键 namespace 全部存在
    for required in ("reference_diagnostic_main_r10",
                     "preplan_full_pipeline_placeholder",
                     "preplan_fit_main_r10", "preplan_fit_holdout_r10",
                     "preplan_final_r10", "supervised_main_r10",
                     "supervised_holdout_r10", "qualification_r10",
                     "calibration_r10", "calibration_holdout_r10"):
        if required == "preplan_full_pipeline_placeholder":
            continue
        assert required in CURRICULUM261_R10_NAMESPACES


def test_next_round_wording_is_r11():
    import inspect

    from rl_curriculum import curriculum261_r10_namespaces as ns

    src = inspect.getsource(ns.write_r10_iteration_aborted)
    assert "下一轮必须 R11" in src
    src2 = inspect.getsource(ns.write_qualification_r10_exposure)
    assert "R11" in src2 or "R11" in inspect.getsource(ns)
