# -*- coding: utf-8 -*-
"""R10 §36 测试:preflight(§30)与 plan roundtrip(§8.3)。

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
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    # torch 线程面隔离(v2 轮 S3 全量回归归因):静态 preflight 的
    # imports/依赖解析/evaluator 探针检查在主进程 import 全部声明
    # 依赖(stable_baselines3/rl_platform → torch),并触发 CUDA
    # driver probe 线程(SigBlk=0),使字母序在后的直调形态 supervisor
    # 测试截止点前提核验 rc=7(与 conftest 的 BLAS 缓解同族;生产
    # preflight 在独立 CLI 进程执行,本无此线程面)。整个 preflight
    # 在一次性子进程真实执行,全部断言语义不变。
    _src = str(Path(__file__).resolve().parents[2] / 'src')
    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR", str(tmp_path / "lock"))

    def _run_preflight_in_subprocess(out_dir: str, vendor: str) -> dict:
        code = (
            'import json, sys\n'
            'from rl_curriculum.curriculum261_r10_preflight import (\n'
            '    run_prelock_static_preflight_r10)\n'
            'result = run_prelock_static_preflight_r10(\n'
            '    sys.argv[1], sys.argv[2])\n'
            'def _jsonable(o):\n'
            '    if hasattr(o, "item"): return o.item()\n'
            '    if hasattr(o, "tolist"): return o.tolist()\n'
            '    return str(o)\n'
            'sys.stdout.write(json.dumps(result, default=_jsonable))\n')
        env = dict(os.environ)
        env['PYTHONPATH'] = _src + (
            os.pathsep + env['PYTHONPATH']
            if env.get('PYTHONPATH') else '')
        proc = subprocess.run(
            [sys.executable, '-c', code, out_dir, vendor],
            capture_output=True, text=True, timeout=600, env=env)
        assert proc.returncode == 0, proc.stderr[-2000:]
        return json.loads(proc.stdout)

    result = _run_preflight_in_subprocess(
        str(tmp_path), "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
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
    assert result["namespaces_touched"] == ["ppo_smoke_r10"]


def test_sealed_preflight_digest_and_zero_seed(tmp_path):
    from rl_curriculum.curriculum261_r10_preflight import (
        sealed_preflight_digest,
        verify_sealed_attestation,
    )

    att = {
        "format": "cur261-r10-sealed-final-preflight-v1",
        "iteration": "r10",
        "pass": True,
        "plan_digest": "qp10-" + "0" * 64,
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
        "audit_digest": "r10ca-" + "0" * 64,
    }), encoding="utf-8")
    (out / "preplan_engineering_smoke.json").write_text(json.dumps({
        "identity": {"sentinel_digest": "r10smoke-" + "0" * 64},
        "pass": True,
    }), encoding="utf-8")


def test_cli_plan_roundtrip_subcommand(tmp_path, monkeypatch):
    """§8.3:CLI plan-roundtrip 在临时目录执行真实生产路径。

    torch 线程面隔离(v2 轮 S3 归因):CLI 的 plan-roundtrip 检查链在
    主进程 import 依赖时触发 CUDA driver probe 线程(SigBlk=0),污染
    后续直调形态 supervisor 测试;CLI 整体在一次性子进程执行,
    rc/产物断言语义不变。
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[2] / 'src')
    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR",
                       str(tmp_path / "lock"))
    out = tmp_path / "art"
    _write_preplan_inputs(out)
    code = (
        'import sys\n'
        'from rl_curriculum.curriculum261_r10_cli import main\n'
        'rc = main(["plan-roundtrip", "--out-dir", sys.argv[1]])\n'
        'sys.exit(rc)\n')
    env = dict(os.environ)
    env['PYTHONPATH'] = src + (
        os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    proc = subprocess.run(
        [sys.executable, '-c', code, str(out)],
        capture_output=True, text=True, timeout=600, env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]
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
    """§20/§8.3:无 roundtrip 证据时拒绝锁 plan。(CLI 同样在子进程
    执行,线程面隔离理由同上。)"""
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[2] / 'src')
    monkeypatch.setenv("CURRICULUM261_R10_LOCK_DIR", str(tmp_path))
    out = tmp_path / "art2"
    _write_preplan_inputs(out)
    code = (
        'import sys\n'
        'from rl_curriculum.curriculum261_r10_cli import main\n'
        'rc = main(["design-plan-lock", "--out-dir", sys.argv[1]])\n'
        'sys.exit(rc)\n')
    env = dict(os.environ)
    env['PYTHONPATH'] = src + (
        os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    proc = subprocess.run(
        [sys.executable, '-c', code, str(out)],
        capture_output=True, text=True, timeout=600, env=env)
    assert proc.returncode == 1
    assert not (out / "r10_design_plan.json").exists()
