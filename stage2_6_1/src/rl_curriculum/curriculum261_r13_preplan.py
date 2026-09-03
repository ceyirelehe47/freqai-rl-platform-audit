# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R13:preplan 工程闭环(§7/§8/§9)。

三个组件(全部真实执行,禁止 monkeypatch;只用非正式 namespace):

1. §7 真实 candidate evaluator 集成 smoke(preplan_candidate_eval_r13):
   1 candidate × 1 corpus × 4 matched blocks 完整执行
   generate_matched_block_with_attempts → evaluate_pair_corpus_r4 →
   build_c2_block_evidence_table → c2_density_summary(r5_pairs!) →
   density_gate_r5 → candidate_cue_semantics → local cue independence →
   context observability → formal block 计算 → scrambled diagnostic →
   result serialization → result reload。
   这正是 R8 ImportError 的爆发路径——R8 的测试 monkeypatch 了
   evaluator,使其从未在测试中真实执行;R13 将该路径变成 plan lock 的
   硬前置项。

2. §8 semantic artifact writer 显式映射验证:穷尽映射 / exclusive
   create / embedded namespace 一致 / main+validation 双文件同时存在
   且哈希不同 / 覆盖尝试失败 / 未知 namespace 立即报错。

3. §9 preplan end-to-end rehearsal:cue contract v2 小规模 audit(非
   正式 namespace/规模)+ semantic 显式分流 + 真实 evaluator + pack
   builder dry construction + final plan builder dry construction +
   sealed preflight builder / final runner 静态 import + exposure
   marker 临时目录测试。全部 artifacts 写临时目录或 preplan/ 子目录;
   不产生参数选择结果、不产生正式 parameter pack、不解锁
   qualification。
"""

from __future__ import annotations

import json

import hashlib
import inspect
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS, FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r6_tape import (
    generate_matched_block_with_attempts,
)

SMOKE_NAMESPACE_R13 = "preplan_candidate_eval_r13"
SEMANTIC_MAIN_NAMESPACE_R13 = "preplan_semantic_main_r13"
SEMANTIC_VALIDATION_NAMESPACE_R13 = "preplan_semantic_validation_r13"
AUDIT_MODEL_NAMESPACE_R13 = "preplan_smoke_r13"
AUDIT_VALIDATION_NAMESPACE_R13 = "preplan_candidate_eval_r13"

EXPECTED_EVALUATOR_KEYS = (
    "candidate", "corpus", "n_blocks", "block_corpus_summary",
    "block_attempt_stats", "block_table", "pair_table_rows",
    "difficulty_means", "per_formal_block_count", "density_gates",
    "semantics", "semantics_pass", "density_pass",
    "pair_integrity_unity", "oracle_positive",
    "scrambled_control_diagnostic",
)


def _thresholds() -> dict[str, Any]:
    return dict(family_specs()[FAMILY_C2].reference_defaults)


def _all_finite(obj: Any) -> bool:
    if isinstance(obj, dict):
        return all(_all_finite(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return all(_all_finite(v) for v in obj)
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return bool(np.isfinite(obj))
    return True


def run_candidate_evaluator_integration_smoke_r13(
        out_dir: Path | None = None,
        n_blocks: int = 4) -> dict[str, Any]:
    """§7:真实(非 monkeypatch)candidate evaluator 集成 smoke。

    1 candidate(sentinel ladder)× 1 corpus(preplan_candidate_eval_r13)
    × 4 matched blocks;完整执行 evaluator 全链并序列化/重载。
    Smoke 不用于任何参数选择或 PASS 指标。
    """
    from rl_curriculum.curriculum261_r13_design import (
        _evaluate_candidate_matched_r13,
    )

    ladder = {rung: dict(params) for rung, params in C2_RUNG_PARAMS.items()}
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace=SMOKE_NAMESPACE_R13, block_index=i)
        for i in range(n_blocks)]
    result = _evaluate_candidate_matched_r13(
        "preplan_sentinel", ladder, SMOKE_NAMESPACE_R13, _thresholds(),
        blocks=blocks, n_blocks=n_blocks)
    keys_present = {k: bool(k in result) for k in EXPECTED_EVALUATOR_KEYS}
    rungs_ok = (set(result.get("difficulty_means", {}))
                == {"D0", "D1", "D2", "D3"})
    density_schema_ok = bool(
        set(result.get("density_gates", {})) == {"D0", "D1", "D2", "D3"}
        and all(isinstance(v, dict) and "pass" in v for v in
                result["density_gates"].values()))
    cue_sem = result.get("semantics", {}).get(
        "candidate_cue_semantics_r13_cluster_aware", {})
    cue_schema_ok = bool(
        set(cue_sem.get("per_rung", {})) == {"D0", "D1", "D2", "D3"})
    per_n_ok = set(result.get("per_formal_block_count", {})) == {
        "10", "15", "20"}
    values_finite = _all_finite(result.get("difficulty_means", {}))
    blob = json.dumps(result, indent=2, ensure_ascii=False, default=float)
    reloaded = json.loads(blob)
    reload_ok = bool(
        reloaded.get("candidate") == result.get("candidate")
        and reloaded.get("n_blocks") == result.get("n_blocks")
        and set(reloaded.get("per_formal_block_count", {}))
        == {"10", "15", "20"})
    report = {
        "format": "cur261-r13-candidate-evaluator-smoke-v1",
        "namespace": SMOKE_NAMESPACE_R13,
        "n_blocks": int(n_blocks),
        "monkeypatch_used": False,
        "execution_chain": [
            "generate_matched_block_with_attempts",
            "evaluate_pair_corpus_r4",
            "build_c2_block_evidence_table",
            "c2_density_summary (r5_pairs)",
            "density_gate_r5",
            "candidate_cue_semantics",
            "check_c2_local_cue_independence",
            "check_c2_context_observability",
            "formal block calculations (10/15/20)",
            "scrambled diagnostic",
            "result serialization",
            "result reload",
        ],
        "checks": {
            "no_crash": True,
            "keys_present": keys_present,
            "all_keys_present": all(keys_present.values()),
            "expected_rungs": rungs_ok,
            "density_schema_ok": density_schema_ok,
            "cue_semantic_schema_ok": cue_schema_ok,
            "formal_block_options_present": per_n_ok,
            "numeric_finite": values_finite,
            "json_serializable_and_reloadable": reload_ok,
        },
        "difficulty_means": result.get("difficulty_means"),
        "density_pass": result.get("density_pass"),
        "semantics_pass": result.get("semantics_pass"),
        "oracle_positive": result.get("oracle_positive"),
        "pair_integrity_unity": result.get("pair_integrity_unity"),
    }
    report["checks"]["pass_all"] = bool(
        all(report["checks"].values()))
    report["pass"] = report["checks"]["pass_all"]
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "candidate_evaluator_integration_smoke.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
    return report


def run_semantic_writer_validation_r13(out_dir: Path | None = None,
                                     ) -> dict[str, Any]:
    """§8:semantic artifact writer 显式映射机制验证(合成 payload;
    机制测试不掺真实语义数据;全部写入临时目录)。"""
    from rl_curriculum.curriculum261_r13_design import (
        SEMANTIC_ARTIFACT_MAP_R13,
        semantic_artifact_filename_r13,
        write_semantic_artifact_r13,
    )

    checks: dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        main_ns = "cue_semantic_design_main_r13"
        validation_ns = "cue_semantic_design_validation_r13"
        p_main = write_semantic_artifact_r13(
            tdp, main_ns, {"n_blocks": 2, "marker": "main"},
            "r13dp-writer-validation", event_rows=[{"cue_bar": 5}])
        p_valid = write_semantic_artifact_r13(
            tdp, validation_ns, {"n_blocks": 2, "marker": "validation"},
            "r13dp-writer-validation", event_rows=[{"cue_bar": 5}])
        checks["filename_mapping_exact"] = bool(
            p_main.name == "semantic_design_main.json"
            and p_valid.name == "semantic_design_validation.json"
            and semantic_artifact_filename_r13(main_ns)
            == "semantic_design_main.json")
        back_main = json.loads(p_main.read_text(encoding="utf-8"))
        back_valid = json.loads(p_valid.read_text(encoding="utf-8"))
        checks["embedded_namespace_consistent"] = bool(
            back_main["namespace"] == main_ns
            and back_main["corpus_role"] == "main"
            and back_valid["namespace"] == validation_ns
            and back_valid["corpus_role"] == "validation"
            and back_main["design_plan_digest"]
            == "r13dp-writer-validation")
        h_main = hashlib.sha256(p_main.read_bytes()).hexdigest()
        h_valid = hashlib.sha256(p_valid.read_bytes()).hexdigest()
        checks["both_files_exist"] = bool(p_main.is_file()
                                          and p_valid.is_file())
        checks["hashes_differ"] = bool(h_main != h_valid)
        overwrite_rejected = False
        try:
            write_semantic_artifact_r13(
                tdp, main_ns, {"n_blocks": 2, "marker": "overwrite"},
                "r13dp-writer-validation")
        except (OSError, RuntimeError, FileExistsError):
            overwrite_rejected = True
        checks["overwrite_attempt_rejected"] = overwrite_rejected
        unknown_ns_rejected = False
        try:
            semantic_artifact_filename_r13("cue_semantic_design_main")
        except RuntimeError:
            unknown_ns_rejected = True
        checks["unknown_namespace_rejected"] = unknown_ns_rejected
        suffix_heuristic_absent = not any(
            "endswith" in str(v) for v in SEMANTIC_ARTIFACT_MAP_R13)
        checks["no_suffix_heuristic_in_mapping"] = suffix_heuristic_absent
    report = {
        "format": "cur261-r13-semantic-writer-validation-v1",
        "mapping": {k: v for k, v in SEMANTIC_ARTIFACT_MAP_R13.items()},
        "checks": checks,
        "pass": bool(all(checks.values())),
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "semantic_artifact_writer_validation.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
    return report


def _exposure_marker_rehearsal() -> dict[str, Any]:
    """§9:exposure marker 临时目录测试(running 原子独占 → 单向
    terminal;临时目录 + 环境变量重定向,不触碰正式目录)。"""
    from rl_curriculum.curriculum261_r13_namespaces import (
        qualification_r13_exposed,
        write_qualification_r13_exposure,
    )

    env_key = "CURRICULUM261_R13_LOCK_DIR"
    old = os.environ.get(env_key)
    try:
        with tempfile.TemporaryDirectory() as td:
            os.environ[env_key] = td
            write_qualification_r13_exposure(
                "r13dp-rehearsal-exposure", "running")
            running_exposed = qualification_r13_exposed()
            duplicate_rejected = False
            try:
                write_qualification_r13_exposure(
                    "r13dp-rehearsal-exposure", "running")
            except Exception:  # noqa: BLE001
                duplicate_rejected = True
            write_qualification_r13_exposure(
                "r13dp-rehearsal-exposure", "completed")
            terminal_single_shot = False
            try:
                write_qualification_r13_exposure(
                    "r13dp-rehearsal-exposure", "failed")
            except Exception:  # noqa: BLE001
                terminal_single_shot = True
            return {
                "running_atomic_exclusive": bool(
                    running_exposed and duplicate_rejected),
                "terminal_one_way": bool(terminal_single_shot),
                "pass": bool(running_exposed and duplicate_rejected
                             and terminal_single_shot),
            }
    finally:
        if old is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = old


def _static_builder_rehearsal() -> dict[str, Any]:
    """§9:pack/plan/sealed/final builder 静态构造与导入检查。"""
    from rl_curriculum.curriculum261_r13_param_pack import (
        ladder_pack_payload_r13,
        pack_digest_r13,
    )
    from rl_curriculum.curriculum261_r13_plan import plan_digest_r13
    from rl_curriculum.curriculum261_r13_preflight import (
        run_postlock_sealed_preflight_r13,
    )
    from rl_curriculum.curriculum261_r13_final import (
        run_final_qualification_r13,
    )
    from rl_curriculum.curriculum261_r13_calibration import (
        run_c2_semantic_corpus_r13,
    )
    from rl_curriculum.curriculum261_r13_cue_contract import (
        lock_cue_audit_plan_r13,
        load_locked_cue_audit_plan_r13,
        run_cue_contract_audit,
    )
    from rl_curriculum.curriculum261_r13_design import (
        design_plan_payload_r13,
        lock_design_plan_r13,
        load_locked_design_plan_r13,
    )

    # parameter-pack builder dry construction(合成 evidence,不落正式
    # 目录,不产生正式 pack)
    pack = ladder_pack_payload_r13(
        selected_c2_candidate="rehearsal_sentinel",
        c2_ladder={r: dict(p) for r, p in C2_RUNG_PARAMS.items()},
        selected_block_count=10,
        design_plan_digest="r13dp-rehearsal",
        matched_contract_identity="rehearsal",
        block_integrity_identity="rehearsal",
        cue_semantic_contract_digest="r13cue-rehearsal",
        cue_semantic_rule_identity="r13csg-rehearsal",
        cue_audit_digest="r13ca-rehearsal",
        p_contract=0.95, recall_floor_value=0.93,
        noninferiority_delta=0.02,
        semantic_blocks_per_corpus=160,
        candidate_evidence={"rehearsal": True},
        marginal_guard_evidence={"rehearsal": True},
        baseline_commit="rehearsal")
    pack_digest = pack_digest_r13(pack)
    pack_ok = bool(pack["semantic_blocks_per_corpus"] == 160
                   and pack_digest.startswith("r13pk-"))
    # final plan builder dry construction:qp12- 前缀 + PRIOR 绑定存在
    probe_digest = plan_digest_r13({"rehearsal": True})
    qp9_ok = bool(probe_digest.startswith("qp12-"))
    sig_final = str(inspect.signature(run_final_qualification_r13))
    final_static_ok = bool("out_dir" in sig_final
                           or "plan" in sig_final)
    return {
        "parameter_pack_builder_dry": pack_ok,
        "pack_digest_prefix": pack_digest[:5],
        "final_plan_builder_qp9_prefix": qp9_ok,
        "calibration_runner_importable": bool(
            callable(run_c2_semantic_corpus_r13)),
        "sealed_preflight_builder_importable": bool(
            callable(run_postlock_sealed_preflight_r13)),
        "final_runner_static_import_ok": final_static_ok,
        "cue_audit_plan_lock_functions_importable": bool(
            callable(lock_cue_audit_plan_r13)
            and callable(load_locked_cue_audit_plan_r13)
            and callable(run_cue_contract_audit)),
        "design_plan_lock_functions_importable": bool(
            callable(design_plan_payload_r13)
            and callable(lock_design_plan_r13)
            and callable(load_locked_design_plan_r13)),
        "pass": bool(pack_ok and qp9_ok and final_static_ok),
    }


def _semantic_mini_corpora(n_blocks: int = 4) -> dict[str, Any]:
    """§9:semantic main/validation 小规模真实分流(preplan namespace;
    只验证生成与 gate 路径,schema/no-crash;统计 PASS 留给正式)。"""
    from rl_curriculum.curriculum261_r13_cue_eval import semantic_cue_gate

    ladder = {rung: dict(params) for rung, params in C2_RUNG_PARAMS.items()}
    out: dict[str, Any] = {}
    for label, ns in (("main", SEMANTIC_MAIN_NAMESPACE_R13),
                      ("validation", SEMANTIC_VALIDATION_NAMESPACE_R13)):
        blocks = [generate_matched_block_with_attempts(
            ladder, namespace=ns, block_index=i)
            for i in range(n_blocks)]
        gate = semantic_cue_gate(
            blocks, ladder, _thresholds(),
            recall_floor_value=0.90, min_unique_positive_cues=1,
            label=f"rehearsal@{ns}")
        out[label] = {
            "namespace": ns,
            "n_blocks": gate["n_blocks"],
            "n_unique_positive_cues": gate["n_unique_positive_cues"],
            "checks_schema_ok": bool(
                "recall" in gate and "noncue_false_positive" in gate
                and "checks" in gate),
            "finite": _all_finite(gate.get("recall", {})),
        }
    out["pass"] = bool(all(
        v["checks_schema_ok"] and v["finite"]
        for v in out.values() if isinstance(v, dict)))
    return out


def run_preplan_rehearsal_r13(out_dir: Path) -> dict[str, Any]:
    """§9:完整工程 rehearsal(plan lock 前;全部非正式 namespace)。

    覆盖:cue contract v2 小规模 audit / semantic 显式分流 / 真实
    candidate evaluator / pack+plan+sealed+final builder dry / exposure
    marker 临时目录测试。任一失败 => rehearsal FAIL(允许在 plan lock
    前修复并重跑)。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        from rl_curriculum.curriculum261_r13_cue_contract import (
            run_cue_contract_audit,
        )

        mini_audit = run_cue_contract_audit(
            tdp, blocks_per_corpus=8, mc_events=50000,
            model_namespace=AUDIT_MODEL_NAMESPACE_R13,
            validation_namespace=AUDIT_VALIDATION_NAMESPACE_R13,
            require_locked_plan=False)
        audit_schema_ok = bool(
            "p_contract" in mini_audit
            and "direct_generator" in mini_audit
            and mini_audit["direct_generator"]["model"]["generation_mode"]
            == "once"
            and mini_audit["direct_generator"]["validation"][
                "generation_mode"] == "attempts"
            and "once_vs_attempts" in mini_audit)
        audit_finite = _all_finite({"p": mini_audit.get("p_contract", 0.0)})
    writer = run_semantic_writer_validation_r13(out_dir)
    evaluator = run_candidate_evaluator_integration_smoke_r13(out_dir)
    semantic_mini = _semantic_mini_corpora()
    statics = _static_builder_rehearsal()
    marker = _exposure_marker_rehearsal()
    dep = None
    try:
        from rl_curriculum.curriculum261_r13_dependencies import (
            resolve_dependency_identity_r13,
        )

        dep = resolve_dependency_identity_r13()
    except Exception as exc:  # noqa: BLE001
        dep = {"pass": False, "error": str(exc)[:200]}
    sections = {
        "cue_audit_mini_schema": audit_schema_ok,
        "cue_audit_mini_finite": audit_finite,
        "semantic_writer_validation": writer["pass"],
        "real_candidate_evaluator_smoke": evaluator["pass"],
        "semantic_mini_corpora": semantic_mini["pass"],
        "static_builders": statics["pass"],
        "exposure_marker_rehearsal": marker["pass"],
        "dependency_resolution": bool(dep.get("pass")),
    }
    report = {
        "format": "cur261-r13-preplan-rehearsal-v1",
        "formal_namespaces_used": False,
        "monkeypatch_used": False,
        "namespaces": {
            "audit_model": AUDIT_MODEL_NAMESPACE_R13,
            "audit_validation": AUDIT_VALIDATION_NAMESPACE_R13,
            "evaluator_smoke": SMOKE_NAMESPACE_R13,
            "semantic_main": SEMANTIC_MAIN_NAMESPACE_R13,
            "semantic_validation": SEMANTIC_VALIDATION_NAMESPACE_R13},
        "sections": sections,
        "detail": {
            "cue_audit_mini": {
                "p_contract": mini_audit.get("p_contract"),
                "model_empirical": mini_audit["direct_generator"][
                    "model"]["empirical_recall"],
                "validation_empirical": mini_audit["direct_generator"][
                    "validation"]["empirical_recall"],
                "once_vs_attempts": {
                    k: v for k, v in mini_audit.get(
                        "once_vs_attempts", {}).items()
                    if k in ("recall_model", "recall_validation",
                             "recall_modes_consistent",
                             "k_modes_consistent",
                             "first_pass_bitwise_check")},
                "statistical_pass_recorded_only": mini_audit.get("pass"),
            },
            "semantic_writer_validation": writer["checks"],
            "evaluator_smoke": evaluator["checks"],
            "semantic_mini_corpora": semantic_mini,
            "static_builders": statics,
            "exposure_marker": marker,
            "dependency_resolution": {
                "pass": dep.get("pass"),
                "digest": dep.get("digest"),
                "problems": dep.get("problems", [])[:5]},
        },
    }
    report["pass"] = bool(all(sections.values()))
    core = {k: v for k, v in report.items() if k not in ("detail",)}
    report["rehearsal_digest"] = "r13pr-" + hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        default=float).encode("utf-8")).hexdigest()
    (out_dir / "preplan_end_to_end_rehearsal.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return report


# --------------------------------------------- §10 reference 根因诊断
def run_reference_root_cause_diagnosis_r13(out_dir: Path) -> dict[str, Any]:
    """§10:在 reference_diagnostic_main_r13 namespace 重现并定位
    R9 的 reference_equivalence_all=false。

    两层数值路径(§10.1)+ 逐 mismatch 全字段落盘(§10.2)+ policy
    state 排查记录(§10.3)+ 根因分类(§10.4);任何 unexplained 都会
    置 pass=false(正式 design plan 不得锁定)。
    """
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r13_calibration import (
        fit_preprocessor_v2_from_bank_r13,
        generate_fit_bank_r13,
    )
    from rl_curriculum.curriculum261_r13_param_pack import (
        r13_override_for,
    )
    from rl_curriculum.curriculum261_r13_reference import (
        reference_equivalence_run_r13,
        write_reference_equivalence_artifacts_r13,
    )
    from rl_curriculum.curriculum261_r13_rehearsal import _rehearsal_pack
    from rl_curriculum.curriculum261_r13_routing import build_routing_r13

    out_dir = Path(out_dir)
    pack = _rehearsal_pack()
    records = generate_fit_bank_r13(
        "preplan_fit_main_r13", pack, pairs_per_rung=2)
    v2, _manifest = fit_preprocessor_v2_from_bank_r13(
        "preplan_fit_main_r13", pack, records=records,
        parameter_pack_identity=pack["digest"])
    routing = build_routing_r13(
        "diagnostic", v2, preplan=True)
    equiv_records = []
    for family in CURRICULUM261_FAMILIES:
        override = r13_override_for(family, pack)
        for rung in CURRICULUM261_RUNGS:
            equiv_records.append(generate_pair(
                family, rung, 0,
                namespace="reference_diagnostic_main_r13",
                rung_params_override=override))
    report = reference_equivalence_run_r13(
        equiv_records, routing.bundle(), pack,
        eval_namespace="reference_diagnostic_main_r13",
        detailed=True, mismatch_limit=50)
    write_reference_equivalence_artifacts_r13(
        out_dir, report, stem="reference_equivalence_diagnostic")
    categories: dict[str, int] = {}
    for m in report["mismatches"]:
        if m.get("explainable_by_float32_boundary"):
            categories["float32_projection_boundary"] = (
                categories.get("float32_projection_boundary", 0) + 1)
        else:
            categories["unexplained"] = (
                categories.get("unexplained", 0) + 1)
    root_cause = {
        "format": "cur261-r13-reference-root-cause-v1",
        "iteration": "r13",
        "target": "R9 preprocessing_v2_requalification:"
                  "reference_equivalence_all=false(仅布尔值落盘)",
        "diagnostic_namespace": "reference_diagnostic_main_r13",
        "fit_namespace": "preplan_fit_main_r13",
        "n_episodes": report["n_episodes"],
        "float64_math_path": report["float64_math_path"],
        "runtime_projection_stats": report["runtime_projection_stats"],
        "canonical_vs_scaled_full_equality": report[
            "canonical_scaled_full_equality"],
        "legacy_action_diffs_total": report[
            "legacy_action_diffs_total"],
        "n_mismatches_recorded": report["n_mismatches_recorded"],
        "mismatch_categories": categories,
        "unexplained_mismatches": report["unexplained_mismatches"],
        "branch_verdict": (
            "Branch B(pure float32 projection)" if report[
                "unexplained_mismatches"] == 0
            and report["float64_math_path"]["pass"]
            else "Branch A/C 待修(存在 unexplained 或数学逆失败)"),
        "canonicalization_contract": (
            "PolicyVisibleReferenceCanonicalization-v1"
            if report["unexplained_mismatches"] == 0 else ""),
        "pass": bool(report["unexplained_mismatches"] == 0
                     and report["float64_math_path"]["pass"]),
    }
    (out_dir / "reference_root_cause.json").write_text(
        json.dumps(root_cause, ensure_ascii=False, indent=1,
                   default=str), encoding="utf-8")
    return root_cause
