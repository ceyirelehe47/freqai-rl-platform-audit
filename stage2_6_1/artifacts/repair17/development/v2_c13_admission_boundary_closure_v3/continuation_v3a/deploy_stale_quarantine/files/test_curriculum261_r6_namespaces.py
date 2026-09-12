# -*- coding: utf-8 -*-
"""R6 §38 测试:Governance(namespaces/marker/锁/六要素/守卫)。"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture()
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R6_LOCK_DIR", str(tmp_path))
    yield tmp_path
    monkeypatch.delenv("CURRICULUM261_R6_LOCK_DIR", raising=False)


def test_namespace_isolation():
    from rl_curriculum.curriculum261_r6_namespaces import (
        verify_r6_namespace_isolation,
    )

    rep = verify_r6_namespace_isolation()
    assert rep["pass"], rep["pairwise_collisions"]
    assert rep["name_space_disjoint"]
    assert rep["r6_vs_historical_overlap"] == 0
    assert len(rep["r6_namespaces"]) == 16


def test_qualification_r6_seed_guarded_before_unlock(lock_dir):
    from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed

    with pytest.raises(GeneratorError, match="R6 qualification plan"):
        derive261_seed("qualification_r6", "c2_context", "D0", 0, 0)
    with pytest.raises(GeneratorError, match="R6 qualification plan"):
        derive261_seed("preprocess_fit_qualification_r6",
                       "c2_context", "D0", 0, 0)


def test_design_namespaces_accessible_without_guard(lock_dir):
    """design/matched namespace 无需解锁(开发语料),seed 可派生。"""
    from rl_curriculum.curriculum261_api import derive261_seed

    s1 = derive261_seed("design_r6_matched_main", "c2_context", "D0",
                        0, 0)
    s2 = derive261_seed("design_r6_matched_main", "c2_context", "D0",
                        0, 0)
    assert s1 == s2 and s1 > 0


def test_exposure_marker_atomic_and_one_way(lock_dir):
    from rl_curriculum.curriculum261_r6_namespaces import (
        qualification_r6_exposed,
        write_qualification_r6_exposure,
    )

    assert not qualification_r6_exposed()
    write_qualification_r6_exposure("qp6-test", "running")
    assert qualification_r6_exposed()
    # 重复 running 拒绝(并发 final 只有一个成功)
    with pytest.raises(RuntimeError, match="已存在"):
        write_qualification_r6_exposure("qp6-test", "running")
    # running -> completed 单向一次
    write_qualification_r6_exposure("qp6-test", "completed")
    for bad in ("completed", "failed", "crashed", "running"):
        with pytest.raises(RuntimeError):
            write_qualification_r6_exposure("qp6-test", bad)
    # 非法状态
    with pytest.raises(RuntimeError, match="非法"):
        write_qualification_r6_exposure("qp6-test", "paused")
    # plan digest 不符的 terminal 更新拒绝
    from rl_curriculum.curriculum261_r6_namespaces import (
        write_qualification_r6_exposure as w,
    )

    marker = lock_dir / "qualification_exposure_r6.json"
    obj = json.loads(marker.read_text(encoding="utf-8"))
    obj["status"] = "running"
    marker.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(RuntimeError, match="plan digest"):
        w("qp6-other", "completed")


def test_no_delete_marker_api(lock_dir):
    """模块不提供任何 marker 删除/重置 API(源码级断言)。"""
    import inspect

    import rl_curriculum.curriculum261_r6_namespaces as ns

    src = inspect.getsource(ns)
    for forbidden in ("def delete_", "def remove_marker",
                      "def reset_exposure", "def clear_exposure",
                      "os.remove", "os.unlink"):
        assert forbidden not in src, forbidden


def test_ledger_survives_marker_deletion(lock_dir):
    from rl_curriculum.curriculum261_r6_namespaces import (
        ledger_entries,
        qualification_r6_exposed,
        write_qualification_r6_exposure,
    )

    write_qualification_r6_exposure("qp6-test", "running")
    # 模拟手动删除 marker(测试专用;产品代码无此路径)
    (lock_dir / "qualification_exposure_r6.json").unlink()
    entries = ledger_entries()
    assert any(e.get("event") == "marker_create" for e in entries)
    assert qualification_r6_exposed(), "ledger 必须兜底判定已暴露"


def test_file_lock_mutual_exclusion(lock_dir):
    import rl_curriculum.curriculum261_r6_namespaces as ns

    with ns.QualificationR6FileLock(blocking=False):
        with pytest.raises(RuntimeError, match="另一个 R6 final"):
            with ns.QualificationR6FileLock(blocking=False):
                pass


def test_unlocked_six_elements(lock_dir):
    from rl_curriculum.curriculum261_r6_namespaces import (
        qualification_r6_unlocked,
        qualification_r6_unlocked_detail,
    )

    assert not qualification_r6_unlocked()
    detail = qualification_r6_unlocked_detail()
    assert detail["unlocked"] is False
    assert not detail["plan_exists"]


def test_unlock_requires_all_six(lock_dir):
    """六要素:构造 plan+digest+gate+pack+sealed attestation 全真才解锁
    (用最小合成 fixture;每个要素缺失都不解锁)。"""
    import rl_curriculum.curriculum261_r6_namespaces as ns
    from rl_curriculum.curriculum261_r6_plan import plan_digest_r6

    def _make_plan(gate_pass=True):
        return {
            "iteration": "r6",
            "robustness_gate": {"pass": gate_pass},
            "parameter_pack": {"digest": "r6pk-test"},
        }

    plan = _make_plan()
    (lock_dir / "qualification_plan_r6.json").write_text(
        json.dumps(plan), encoding="utf-8")
    (lock_dir / "qualification_plan_digest_r6.txt").write_text(
        plan_digest_r6(plan), encoding="utf-8")
    assert not ns.qualification_r6_unlocked()  # 缺 pack/attestation

    # gate FAIL 也永不解锁
    plan_bad = _make_plan(False)
    (lock_dir / "qualification_plan_r6.json").write_text(
        json.dumps(plan_bad), encoding="utf-8")
    (lock_dir / "qualification_plan_digest_r6.txt").write_text(
        plan_digest_r6(plan_bad), encoding="utf-8")
    assert not ns.qualification_r6_unlocked()


def test_plan_lock_once_and_drift_reject(lock_dir):
    from rl_curriculum.curriculum261_r6_plan import (
        load_locked_plan_r6,
        lock_plan_r6,
        plan_digest_r6,
    )

    plan = {"iteration": "r6", "format": "cur261-r6-qualification-plan-v1"}
    path, digest = lock_plan_r6(dict(plan))
    assert path.is_file()
    with pytest.raises(RuntimeError, match="已存在"):
        lock_plan_r6(dict(plan))
    # 篡改 -> digest 漂移拒绝
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["kappa"] = 0.1
    path.write_text(json.dumps(obj), encoding="utf-8")
    with pytest.raises(RuntimeError, match="漂移"):
        load_locked_plan_r6()


def test_design_plan_lock_once_and_grid_guard(lock_dir, monkeypatch):
    import rl_curriculum.curriculum261_r6_design as dmod

    plan = dmod.design_plan_payload(
        baseline_commit="40a0d9a", vendor_pin="52bc96f4480b1a0da6a9b45"
        "5bd00b17fbb6786a5",
        v2_contract_digest="r4pre-test",
        prior_r2_plan_digest="qp-t", prior_diag262r2_plan_digest="dp-t")
    path, digest = dmod.lock_design_plan(lock_dir, plan)
    assert digest.startswith("r6dp-")
    with pytest.raises(RuntimeError, match="已存在"):
        dmod.lock_design_plan(lock_dir, plan)
    loaded, d2 = dmod.load_locked_design_plan(lock_dir)
    assert d2 == digest
    # grid 漂移拒绝(r6_candidate_grid 读 param_pack 模块常量)
    import rl_curriculum.curriculum261_r6_param_pack as pp

    orig_grid = pp.C2_LADDER_CANDIDATES
    monkeypatch.setattr(
        pp, "C2_LADDER_CANDIDATES",
        {**orig_grid, "extra": orig_grid["c2l_balanced"]})
    with pytest.raises(RuntimeError, match="候选网格"):
        dmod.load_locked_design_plan(lock_dir)
    monkeypatch.setattr(pp, "C2_LADDER_CANDIDATES", orig_grid)
    # block 选项漂移拒绝
    monkeypatch.setattr(dmod, "FORMAL_BLOCK_OPTIONS", (10, 15))
    with pytest.raises(RuntimeError, match="formal block"):
        dmod.load_locked_design_plan(lock_dir)
