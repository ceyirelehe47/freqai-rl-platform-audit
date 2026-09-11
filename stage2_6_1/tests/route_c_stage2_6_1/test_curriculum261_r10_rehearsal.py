# -*- coding: utf-8 -*-
"""R10 §29 Full Pipeline Rehearsal 测试:非 monkeypatch 完整执行
fit main/holdout → reference equivalence → supervised → C1/C3 →
C2 matched → semantic → independent → gate → plan(temp lock/load)
→ sealed preflight(rehearsal)→ mini final(§12)。

以及 §10 reference 根因诊断测试(preplan namespace 重现 R9 false
机制;Branch 判定)。标记 slow:真实全链,无任何 monkeypatch。
"""

from __future__ import annotations

import json

import pytest


@pytest.mark.slow
def test_full_pipeline_rehearsal_end_to_end_no_monkeypatch(tmp_path):
    # torch 线程面隔离(v2 轮 S3 全量回归归因):完整 rehearsal 链含
    # ppo smoke 步骤(import torch),在 pytest 进程留下未屏蔽 CUDA
    # 线程,使字母序在后的直调形态 supervisor 测试截止点前提核验
    # rc=7(与 conftest 的 BLAS/CUDA 缓解同族;生产 rehearsal 在独立
    # 进程执行)。rehearsal 在一次性子进程真实执行,断言语义不变。
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    src = str(Path(__file__).resolve().parents[2] / 'src')
    code = (
        'import json, sys\n'
        'from rl_curriculum.curriculum261_r10_rehearsal import (\n'
        '    run_preplan_full_pipeline_rehearsal_r10)\n'
        'report = run_preplan_full_pipeline_rehearsal_r10('
        'sys.argv[1])\n'
        'def _jsonable(o):\n'
        '    if hasattr(o, "item"): return o.item()\n'
        '    if hasattr(o, "tolist"): return o.tolist()\n'
        '    return str(o)\n'
        'sys.stdout.write(json.dumps(report, default=_jsonable))\n')
    env = dict(os.environ)
    env['PYTHONPATH'] = src + (
        os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
    proc = subprocess.run(
        [sys.executable, '-c', code, str(tmp_path)],
        capture_output=True, text=True, timeout=1800, env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads(proc.stdout)
    assert report["pass"], {
        k: v for k, v in report["proofs"].items()
        if v is False or (isinstance(v, dict)
                          and v.get("pass") is False)}
    # §12.2 真实执行清单断言
    assert report["calibration_stage_pass"] is True
    assert report["routing_matrix_all_pass"] is True
    assert report["monkeypatch_used"] is False
    proofs = report["proofs"]
    assert proofs["holdout_uses_v2_hold"]["bundles_distinct"] is True
    assert proofs["holdout_uses_v2_hold"][
        "routing_matrix_holdout_rows_all_pass"] is True
    assert all(proofs["artifacts_reload"].values())
    assert proofs["qualification_plan_lock_load_temp"]["locked"] is True
    assert proofs["qualification_plan_lock_load_temp"][
        "digest_match"] is True
    assert proofs["sealed_preflight_rehearsal"]["zero_final_seed"] is True
    assert proofs["final_like_runner"]["executed"] is True
    assert report["rehearsal_digest"].startswith("r10rh-")
    # 零正式 namespace 访问
    formal_prefixes = ("calibration_r10", "calibration_holdout_r10",
                       "qualification_r10", "supervised_main_r10",
                       "supervised_holdout_r10", "cue_semantic_",
                       "c2_independent_calibration_r10",
                       "c2_independent_holdout_r10",
                       "c2_independent_qualification_r10",
                       "preprocess_fit_calibration_r10",
                       "preprocess_fit_holdout_r10",
                       "preprocess_fit_qualification_r10",
                       "design_r10_", "cue_contract_", "training_r10",
                       "stress_r10", "fresh_holdout_r10")
    for ns in report["namespaces_touched"]:
        assert not ns.startswith(formal_prefixes), \
            f"rehearsal 触碰正式 namespace:{ns}"


@pytest.mark.slow
def test_reference_root_cause_diagnosis_branch_b(tmp_path):
    """§10:诊断在 preplan namespace 重现 legacy 差异并全部归类为
    float32 边界(Branch B);0 unexplained。"""
    from rl_curriculum.curriculum261_r10_preplan import (
        run_reference_root_cause_diagnosis_r10,
    )

    rc = run_reference_root_cause_diagnosis_r10(tmp_path)
    assert rc["float64_math_path"]["pass"], rc["float64_math_path"]
    assert rc["unexplained_mismatches"] == 0, rc["mismatch_categories"]
    assert rc["mismatch_categories"].get("unexplained", 0) == 0
    assert "Branch B" in rc["branch_verdict"]
    assert rc["canonicalization_contract"] == \
        "PolicyVisibleReferenceCanonicalization-v1"
    assert rc["pass"] is True
    # 明细落盘(不再只是一个布尔值;§2.6/§10.2)
    mismatch_doc = json.loads(
        (tmp_path / "reference_equivalence_diagnostic_mismatches.json"
         ).read_text(encoding="utf-8"))
    assert "n_mismatches" in mismatch_doc
    assert "explicit" in mismatch_doc


def test_orchestrator_profiles_formal_vs_rehearsal():
    """§12:唯一差异维度是样本量与 namespace(同一 orchestration)。"""
    from rl_curriculum.curriculum261_r10_orchestrator import (
        formal_holdout_profile_r10,
        formal_main_profile_r10,
        rehearsal_holdout_profile_r10,
        rehearsal_main_profile_r10,
    )

    fm = formal_main_profile_r10(10)
    fh = formal_holdout_profile_r10(10)
    rm = rehearsal_main_profile_r10()
    rh = rehearsal_holdout_profile_r10()
    assert fm.c13_pairs_per_rung == 10
    assert fm.semantic_blocks == 160
    assert fm.supervised_model_seeds == (20261001, 20261002, 20261003)
    assert fh.c13_eval_namespace == "calibration_holdout_r10"
    assert rm.c13_pairs_per_rung == 1 and rm.semantic_blocks == 4
    assert rm.preplan is True and fm.preplan is False
    assert rh.c13_eval_namespace == "preplan_calibration_holdout_r10"
    assert rm.name != fm.name
