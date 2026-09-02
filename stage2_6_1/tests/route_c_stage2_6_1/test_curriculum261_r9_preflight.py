# -*- coding: utf-8 -*-
"""R9 §36 测试:preflight(§30)与 plan roundtrip(§8.3)。

覆盖:prelock static preflight(真实 PPO smoke + matched generator +
exact replay 探针;只用非 final namespace);sealed attestation digest
不自引用 + 零 final seed 字段;CLI plan-roundtrip 子命令在临时目录
执行真实生产路径(build→lock→new process load→recompute→compare→
不可覆盖→无 alternate loader)。
"""

from __future__ import annotations

import json

import pytest


def test_prelock_static_preflight(tmp_path, monkeypatch):
    from rl_curriculum.curriculum261_r9_preflight import (
        run_prelock_static_preflight_r9,
    )

    monkeypatch.setenv("CURRICULUM261_R9_LOCK_DIR", str(tmp_path / "lock"))
    result = run_prelock_static_preflight_r9(
        tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    checks = result["checks"]
    assert result["pass"], json.dumps(
        {k: v for k, v in checks.items()
         if isinstance(v, dict) and not v.get("pass", True)},
        ensure_ascii=False)
    assert checks["matched_generator_and_cue_evaluator"]["pass"]
    assert checks["matched_generator_and_cue_evaluator"][
        "noise_replay_bitwise_ok"]
    # §6.3/§7:依赖解析 + 真实(非 monkeypatch)evaluator 探针
    assert checks["dependency_resolution"]["pass"]
    assert checks["matched_generator_and_cue_evaluator"][
        "real_candidate_evaluator_runs"]
    assert checks["marker_atomic_exclusive"]
    assert checks["concurrent_final_lock_rejected"]
    assert result["final_namespaces_touched"] == []
    assert result["namespaces_touched"] == ["ppo_smoke_r9"]


def test_sealed_preflight_digest_and_zero_seed(tmp_path):
    from rl_curriculum.curriculum261_r9_preflight import (
        sealed_preflight_digest,
        verify_sealed_attestation,
    )

    att = {
        "format": "cur261-r9-sealed-final-preflight-v1",
        "iteration": "r9",
        "pass": True,
        "plan_digest": "qp9-" + "0" * 64,
        "final_seed_derivations_performed": 0,
        "final_namespaces_touched": [],
        "exposure_marker_written": False,
    }
    att["digest"] = sealed_preflight_digest(att)
    # digest 不自引用(排除 digest 字段)
    assert sealed_preflight_digest(att) == att["digest"]
    (tmp_path / "sealed_final_preflight.json").write_text(
        json.dumps(att), encoding="utf-8")
    (tmp_path / "sealed_final_preflight_digest.txt").write_text(
        att["digest"], encoding="utf-8")
    verified = verify_sealed_attestation(tmp_path)
    assert verified["pass"]
    assert verified["zero_final_seed"]
    # 篡改 → 失败
    att2 = dict(att)
    att2["final_seed_derivations_performed"] = 1
    (tmp_path / "sealed_final_preflight.json").write_text(
        json.dumps(att2), encoding="utf-8")
    assert not verify_sealed_attestation(tmp_path)["pass"]


def _write_preplan_inputs(out: "pathlib.Path") -> None:
    """合成 plan-roundtrip 所需的 audit + smoke 输入(小规模)。"""
    out.mkdir(parents=True, exist_ok=True)
    (out / "cue_contract_audit.json").write_text(json.dumps({
        "p_contract": 0.9509, "pass": True,
        "audit_digest": "r9ca-" + "0" * 64,
    }), encoding="utf-8")
    (out / "preplan_engineering_smoke.json").write_text(json.dumps({
        "identity": {"sentinel_digest": "r9smoke-" + "0" * 64},
        "pass": True,
    }), encoding="utf-8")


def test_cli_plan_roundtrip_subcommand(tmp_path, monkeypatch):
    """§8.3:CLI plan-roundtrip 在临时目录执行真实生产路径。"""
    import pathlib

    from rl_curriculum.curriculum261_r9_cli import main

    monkeypatch.setenv("CURRICULUM261_R9_LOCK_DIR",
                       str(tmp_path / "lock"))
    out = tmp_path / "art"
    _write_preplan_inputs(out)
    rc = main(["plan-roundtrip", "--out-dir", str(out)])
    assert rc == 0
    result = json.loads(
        (out / "plan_roundtrip_validation.json").read_text(
            encoding="utf-8"))
    assert result["pass"] is True
    checks = result["checks"]
    assert checks["lock_ok"]
    assert checks["payload_bit_identical"]
    assert checks["new_process_load_digest_match"]
    assert checks["candidate_grid_identical"]
    assert checks["formal_block_options_identical"]
    assert checks["semantic_blocks_identical"]
    assert checks["existing_plan_not_overwritable"]
    assert checks["digest_file_matches"]
    assert checks["qualification_plan_build"]
    assert checks["qualification_lock_ok"]
    assert checks["qualification_new_process_load"]
    assert checks["qualification_not_overwritable"]
    assert checks["no_alternate_loader"]
    assert result["namespaces_touched"] == []
    # §8.1:digest 不自引用的设计(排除字段清单)
    assert checks["digest_not_self_referential"]


def test_design_plan_lock_requires_roundtrip(tmp_path, monkeypatch):
    """§20/§8.3:无 roundtrip 证据时拒绝锁 plan。"""
    from rl_curriculum.curriculum261_r9_cli import main

    monkeypatch.setenv("CURRICULUM261_R9_LOCK_DIR", str(tmp_path))
    out = tmp_path / "art2"
    _write_preplan_inputs(out)
    rc = main(["design-plan-lock", "--out-dir", str(out)])
    assert rc == 1
    assert not (out / "r9_design_plan.json").exists()
