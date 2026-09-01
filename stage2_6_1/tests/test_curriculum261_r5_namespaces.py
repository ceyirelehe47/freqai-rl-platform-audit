"""R5 测试:namespace 隔离、qualification_r5 六要素守卫、Tier B 机械
授权与 exposure 硬合同(§34)。

- R5 namespace 与全部历史 261(R0-R4)+ 262 namespace 无碰撞;
- qualification_r5 / preprocess_fit_qualification_r5 在 plan 完整锁定
  (plan + digest + gate + pack + sealed preflight attestation)前封闭;
- design_r5_tier_b_* 在 design decision(tier_b_authorized)前封闭;
- exposure marker:原子创建、状态单向一次、ledger 兜底删除检测、
  无 delete API、并发锁互斥。
"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_api import GeneratorError, derive261_seed
from rl_curriculum.curriculum261_r5_namespaces import (
    QualificationR5FileLock,
    qualification_r5_exposed,
    qualification_r5_unlocked_detail,
    ledger_entries,
    tier_b_authorized,
    verify_r5_namespace_isolation,
    write_qualification_r5_exposure,
)


def test_r5_namespace_isolation():
    rep = verify_r5_namespace_isolation()
    assert rep["pass"] is True
    assert rep["r5_vs_historical_overlap"] == 0
    assert rep["name_space_disjoint"] is True
    assert len(rep["r5_namespaces"]) == 14


def test_final_namespaces_closed_before_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    for ns in ("qualification_r5", "preprocess_fit_qualification_r5"):
        with pytest.raises(GeneratorError):
            derive261_seed(ns, "c2_context", "D0", 0, 0)
    assert qualification_r5_unlocked_detail()["unlocked"] is False


def test_tier_b_namespaces_mechanically_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    # 无 decision 文件:封闭
    assert tier_b_authorized() is False
    with pytest.raises(GeneratorError):
        derive261_seed("design_r5_tier_b_main", "c2_context", "D3", 0, 0)
    # tier A 存在合格 candidate(tier_b_authorized=false):永久封闭
    from rl_curriculum.curriculum261_r5_design import write_design_decision

    write_design_decision(tmp_path, tier_b_authorized=False,
                          tier_a_n_qualified=2,
                          tier_a_candidates=["c2_a_alpha26_vol16"])
    assert tier_b_authorized() is False
    with pytest.raises(GeneratorError):
        derive261_seed("design_r5_tier_b_validation", "c2_context", "D3",
                       0, 0)
    # 机械触发:tier A 全部不合格 -> 解锁
    write_design_decision(tmp_path, tier_b_authorized=True,
                          tier_a_n_qualified=0, tier_a_candidates=[])
    assert tier_b_authorized() is True
    seed = derive261_seed("design_r5_tier_b_main", "c2_context", "D3", 0, 0)
    assert isinstance(seed, int) and seed > 0


def _fake_gate(pass_: bool) -> dict:
    return {"pass": pass_, "format": "f"}


def _make_plan(iteration: str = "r5", gate_pass: bool = True,
               pack_digest: str = "r5pk-test") -> dict:
    return {
        "iteration": iteration,
        "robustness_gate": {"pass": gate_pass},
        "parameter_pack": {"digest": pack_digest},
    }


def _write_pack(root, variant: str = "c2_a_alpha26_vol16") -> str:
    from rl_curriculum.curriculum261_r5_param_pack import (
        pack_digest as _pd,
    )

    pack = {
        "format": "cur261-r5-ladder-pack-v1",
        "pack_version": "CurriculumR5LadderPack-v1",
        "iteration": "r5", "tier": "A",
        "selected_c2_candidate": variant,
        "d3_overrides": {}, "c2_d2_override": None,
        "design_plan_digest": "r5dp-test", "candidate_evidence": {},
        "r4_parameter_pack_digest": "r4pk-x",
    }
    pack["digest"] = _pd(pack)
    (root / "r5_parameter_pack.json").write_text(
        json.dumps(pack), encoding="utf-8")
    (root / "r5_parameter_pack_digest.txt").write_text(
        pack["digest"], encoding="utf-8")
    return pack["digest"]


def _write_sealed(root, plan_digest: str, pass_: bool = True) -> None:
    from rl_curriculum.curriculum261_r5_preflight import (
        sealed_preflight_digest,
    )

    att = {
        "format": "cur261-r5-sealed-final-preflight-v1",
        "pass": pass_,
        "plan_digest": plan_digest,
        "final_seed_derivations_performed": 0,
        "final_namespaces_touched": [],
    }
    att["digest"] = sealed_preflight_digest(att)
    (root / "sealed_final_preflight.json").write_text(
        json.dumps(att), encoding="utf-8")
    (root / "sealed_final_preflight_digest.txt").write_text(
        att["digest"], encoding="utf-8")


def _lock_full_plan(root, plan: dict) -> str:
    from rl_curriculum.curriculum261_r5_plan import plan_digest_r5

    digest = plan_digest_r5(plan)
    (root / "qualification_plan_r5.json").write_text(
        json.dumps(plan), encoding="utf-8")
    (root / "qualification_plan_digest_r5.txt").write_text(
        digest, encoding="utf-8")
    return digest


def test_unlock_six_elements(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    pack_digest = _write_pack(tmp_path)
    plan = _make_plan(pack_digest=pack_digest)

    # 缺 plan:封闭
    assert qualification_r5_unlocked_detail()["unlocked"] is False
    digest = _lock_full_plan(tmp_path, plan)

    # 缺 sealed preflight:仍封闭(第六要素)
    detail = qualification_r5_unlocked_detail()
    assert detail["plan_exists"] and detail["digest_exists"]
    assert detail["digest_matches"] and detail["gate_pass"]
    assert detail["parameter_pack_bound"] is True
    assert detail["sealed_preflight_valid"] is False
    assert detail["unlocked"] is False
    with pytest.raises(GeneratorError):
        derive261_seed("qualification_r5", "c2_context", "D0", 0, 0)

    # sealed preflight 齐备且绑定同一 plan:解锁
    _write_sealed(tmp_path, digest)
    assert qualification_r5_unlocked_detail()["unlocked"] is True
    seed = derive261_seed("preprocess_fit_qualification_r5",
                          "c2_context", "D0", 0, 0)
    assert seed > 0

    # attestation 绑定别的 plan digest:重新封闭
    _write_sealed(tmp_path, "qp5-other-plan")
    assert qualification_r5_unlocked_detail()["unlocked"] is False


def test_unlock_element_breaks(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    pack_digest = _write_pack(tmp_path)
    plan = _make_plan(pack_digest=pack_digest)
    digest = _lock_full_plan(tmp_path, plan)
    _write_sealed(tmp_path, digest)
    assert qualification_r5_unlocked_detail()["unlocked"] is True

    # iteration 错误
    bad = _make_plan(iteration="r4", pack_digest=pack_digest)
    _lock_full_plan(tmp_path, bad)
    assert qualification_r5_unlocked_detail()["unlocked"] is False

    # 恢复后破坏 gate
    digest = _lock_full_plan(tmp_path, plan)
    _write_sealed(tmp_path, digest)
    bad = _make_plan(gate_pass=False, pack_digest=pack_digest)
    _lock_full_plan(tmp_path, bad)
    assert qualification_r5_unlocked_detail()["unlocked"] is False

    # 恢复后破坏 pack 绑定(换一个不同内容的 pack -> plan 绑定失配)
    digest = _lock_full_plan(tmp_path, plan)
    _write_sealed(tmp_path, digest)
    _write_pack(tmp_path, variant="c2_c_alpha24_vol16")
    assert qualification_r5_unlocked_detail()["unlocked"] is False


def test_exposure_marker_hard_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    assert qualification_r5_exposed() is False

    write_qualification_r5_exposure("qp5-x", status="running")
    assert qualification_r5_exposed() is True

    # 重复创建 running(并发 final):拒绝
    with pytest.raises(RuntimeError):
        write_qualification_r5_exposure("qp5-x", status="running")

    # running -> completed 允许一次
    write_qualification_r5_exposure("qp5-x", status="completed")
    # terminal -> 任何更新永久拒绝
    for status in ("completed", "failed", "crashed", "running"):
        with pytest.raises(RuntimeError):
            write_qualification_r5_exposure("qp5-x", status=status)

    # ledger 兜底:删除 marker 后仍判定已暴露(不可恢复为未暴露)
    (tmp_path / "qualification_exposure_r5.json").unlink()
    assert qualification_r5_exposed() is True
    entries = ledger_entries()
    assert any(e.get("event") == "marker_create" for e in entries)
    assert any(e.get("event") == "status_update"
               and e.get("status") == "completed" for e in entries)

    # 无 running marker 时写 terminal:拒绝
    with pytest.raises(RuntimeError):
        write_qualification_r5_exposure("qp5-x", status="failed")


def test_no_delete_marker_api():
    """§27:不存在任何 delete/重置 exposure marker 的 API。"""
    import rl_curriculum.curriculum261_r5_namespaces as ns_mod

    for name in dir(ns_mod):
        low = name.lower()
        assert not ("delete" in low or "reset" in low or "clear" in low), (
            f"R5 namespaces 模块不得暴露 marker 删除/重置 API: {name}")


def test_concurrent_final_lock(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    with QualificationR5FileLock(blocking=False):
        with pytest.raises(RuntimeError):
            with QualificationR5FileLock(blocking=False):
                pass
    # 释放后可重新获取
    with QualificationR5FileLock(blocking=False):
        pass
