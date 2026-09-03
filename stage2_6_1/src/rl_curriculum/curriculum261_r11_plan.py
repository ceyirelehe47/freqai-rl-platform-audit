# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11:final qualification plan(§26)。

双 strict gate(calibration + holdout 各自独立 PASS;无 pooled 救援)
前置强制;plan 绑定 R11 pack/cue semantic 合同/p_contract/recall
floor/selected block count/final namespaces/code identity;plan 锁定后
禁止任何代码修改(§26)。
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r6_pairs import (
    BLOCK_TABLE_SCHEMA,
    STRICT_GATE_RULE_IDENTITY,
    block_table_schema_identity,
    strict_gate_rule_identity,
)
from rl_curriculum.curriculum261_r6_tape import (
    C2_MATCHED_LADDER_BLOCK_VERSION,
    matched_ladder_contract_identity,
)
from rl_curriculum.curriculum261_r11_cue_contract import (
    C2_CUE_SEMANTIC_CONTRACT_VERSION,
    cue_semantic_contract_digest,
)
from rl_curriculum.curriculum261_r11_cue_eval import (
    cue_semantic_rule_identity,
)
from rl_curriculum.curriculum261_r11_namespaces import (
    CURRICULUM261_ITERATION_ID_R11,
    qualification_r11_digest_path,
    qualification_r11_plan_path,
)

PLAN_FORMAT_R11 = "cur261-r11-qualification-plan-v1"

#: R11 代码身份(逐模块内容哈希;进入 plan;final 复算比对)。
PLAN_CODE_MODULES_R11 = (
    "curriculum261_api.py",
    "curriculum261_production_obs.py",
    "curriculum261_c1.py",
    "curriculum261_c2.py",
    "curriculum261_c3.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "curriculum261_r3_preprocessing.py",
    "curriculum261_r3_obs.py",
    "curriculum261_r3_calibration.py",
    "curriculum261_r4_preprocessing.py",
    "curriculum261_r4_pairs.py",
    "curriculum261_r4_param_pack.py",
    "curriculum261_r4_namespaces.py",
    "curriculum261_r4_obs.py",
    "curriculum261_r5_pairs.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r6_param_pack.py",
    "curriculum261_r6_namespaces.py",
    "curriculum261_r6_pairs.py",
    "curriculum261_r6_calibration.py",
    "curriculum261_r11_noise_replay.py",
    "curriculum261_r11_cue_contract.py",
    "curriculum261_r11_cue_eval.py",
    "curriculum261_r11_dependencies.py",
    "curriculum261_r11_routing.py",
    "curriculum261_r11_reference.py",
    "curriculum261_r11_labels.py",
    "curriculum261_r11_orchestrator.py",
    "curriculum261_r11_delegation.py",
    "curriculum261_r11_rehearsal.py",
    "curriculum261_r11_namespaces.py",
    "curriculum261_r11_param_pack.py",
    "curriculum261_r11_preplan.py",
    "curriculum261_r11_design.py",
    "curriculum261_r11_calibration.py",
    "curriculum261_r11_preflight.py",
    "curriculum261_r11_plan.py",
    "curriculum261_r11_final.py",
    "curriculum261_r11_smoke.py",
    "curriculum261_r11_cli.py",
)


def _code_identity_r11() -> dict[str, str]:
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES_R11:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def build_plan_r11(
        *,
        baseline_commit: str,
        vendor_pin: str,
        frozen_contracts: dict[str, str],
        parameter_pack: dict[str, Any],
        design_plan_digest: str,
        selected_c2_candidate: str,
        frozen_parameter_identity: dict[str, Any],
        preprocessing_v2_contract_digest: str,
        calibration_bundle_hash: str,
        holdout_bundle_hash: str,
        preprocessing_robustness_gate: dict[str, Any],
        curriculum_robustness_gate: dict[str, Any],
        conditioning_gate_constants: dict[str, Any],
        supervised_gate_constants: dict[str, Any],
        kappa: float,
        reference_thresholds_by_family: dict[str, Any],
        density_thresholds: dict[str, Any],
        prior_r2_plan_digest: str,
        prior_diag262r2_plan_digest: str,
        prior_r4_parameter_pack_digest: str,
        prior_r5_design_plan_digest: str,
        prior_r6_design_plan_digest: str,
        prior_r7_design_plan_digest: str,
        prior_r8_design_plan_digest: str,
        r8_abort_evidence: dict[str, Any],
        prior_r9_design_plan_digest: str = "",
        r9_abort_evidence: dict[str, Any] | None = None,
        prior_r10_design_plan_digest: str = "",
        r10_abort_evidence: dict[str, Any] | None = None,
        generation_determinism_binding: dict[str, Any] | None = None,
        code_freeze_sha: str = "",
        policy_visible_reference_contract_digest: str = "",
        bundle_routing_contract_digest: str = "",
        supervised_label_contract: str = "PolicyVisibleSupervisedLabel-v1",
        final_bundle_hash: str = "",
        equivalence_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 R11 final qualification plan(双 strict gate 前置强制)。"""
    if not (isinstance(preprocessing_robustness_gate, dict)
            and preprocessing_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "preprocessing robustness gate 未 PASS,禁止生成 R11 plan"
            "(§24:任一条件失败 -> STOP,不得 lock)")
    if not (isinstance(curriculum_robustness_gate, dict)
            and curriculum_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "curriculum robustness gate(strict per-corpus AND + C2 "
            "matched block + cluster-aware cue + marginal guard)未 "
            "PASS,禁止生成 R11 plan")
    from rl_curriculum.curriculum261_r4_pairs import (
        PAIR_TABLE_SCHEMA, pair_table_schema_identity)
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
    )
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
        production_runtime_config_identity,
    )
    from rl_platform.versions import (
        ENV_CORE_VERSION,
        OBSERVATION_SPEC_VERSION,
    )

    n_blocks = int(parameter_pack["selected_block_count"])
    if n_blocks not in (10, 15, 20):
        raise RuntimeError(
            f"selected_block_count {n_blocks} 非法(必须 ∈ {{10,15,20}})")
    core_pairs = 80 + 4 * n_blocks
    independent_guard_pairs = 80
    plan: dict[str, Any] = {
        "format": PLAN_FORMAT_R11,
        "iteration": CURRICULUM261_ITERATION_ID_R11,
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "frozen_contracts": frozen_contracts,
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
        },
        "code_freeze": {
            "code_freeze_sha": code_freeze_sha,
            "contract": ("正式 R11 数据开始前全部源码+测试已提交;"
                         "正式数据开始后任何源码变化 -> R11 永久结束"
                         "(§6/§21)"),
        },
        "policy_visible_reference": {
            "contract_digest": policy_visible_reference_contract_digest,
            "bundle_routing_contract_digest":
                bundle_routing_contract_digest,
            "supervised_label_contract": supervised_label_contract,
        },
        "prior_r9": {
            "design_plan_digest": prior_r9_design_plan_digest,
            "abort_evidence": r9_abort_evidence or {},
            "role": ("R9 design 全部结果仅作 development evidence;"
                     "R11 在全新 namespace 重做"),
        },
        "prior_r10": {
            "design_plan_digest": prior_r10_design_plan_digest,
            "abort_evidence": r10_abort_evidence or {},
            "root_cause_statement": (
                "historically underdetermined due to missing "
                "invocation-state evidence(R10 生成失败重放不可复现)"),
            "role": ("R10 design/pack 全部结果仅作 development "
                     "evidence;R11 在全新 namespace 重做机械 design"),
        },
        "generation_determinism_contract": {
            "binding": generation_determinism_binding or {},
            "role": ("工作包 A6:同一 invocation 跨进程 identity 完全"
                     "一致的合同证据(audit 阶段硬前置)"),
        },
        "parameter_pack": {
            "digest": parameter_pack["digest"],
            "pack_version": parameter_pack["pack_version"],
            "selected_c2_candidate": parameter_pack[
                "selected_c2_candidate"],
            "selected_block_count": n_blocks,
            "c2_ladder": parameter_pack["c2_ladder"],
            "r4_parameter_pack_digest": parameter_pack[
                "r4_parameter_pack_digest"],
            "r5_design_plan_digest": parameter_pack[
                "r5_design_plan_digest"],
            "r6_design_plan_digest": parameter_pack[
                "r6_design_plan_digest"],
            "r7_design_plan_digest": parameter_pack[
                "r7_design_plan_digest"],
            "semantic_blocks_per_corpus": parameter_pack[
                "semantic_blocks_per_corpus"],
            "noninferiority_delta": parameter_pack[
                "noninferiority_delta"],
        },
        "design": {
            "design_plan_digest": design_plan_digest,
            "selected_c2_candidate": selected_c2_candidate,
        },
        "matched_ladder": {
            "contract_version": C2_MATCHED_LADDER_BLOCK_VERSION,
            "contract_identity": matched_ladder_contract_identity(),
            "implementation": "R6 冻结实现零修改复用(import);R6 tape/"
                              "pairs 模块 sha256 进入 code_identity",
            "block_integrity_identity": parameter_pack[
                "block_integrity_identity"],
            "block_attempt_semantics": "block-level max_attempts=5;"
                                       "任一 rung 或跨 rung matching 失败"
                                       " → 整 block 重试",
            "statistical_unit": "matched block(四 rung 同结构带配对差分;"
                                "gap SE = std(blockwise)/sqrt(n_blocks);"
                                "禁止独立 SE 二次合成)",
            "scrambled_control": "仅诊断(不参与 PASS 判定)",
            "independent_marginal_guard": "独立-rung 语料 mean ordering/"
                                          "D3/逐基线 positive/integrity/"
                                          "密度/cluster-aware cue 语义"
                                          "(matched PASS 不可覆盖)",
        },
        "cue_semantic_contract": {
            "version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
            "contract_digest": cue_semantic_contract_digest(),
            "rule_identity": cue_semantic_rule_identity(),
            "audit_digest": parameter_pack["cue_contract_audit_digest"],
            "p_contract": float(parameter_pack["p_contract"]),
            "noninferiority_delta":
                float(parameter_pack.get("noninferiority_delta", 0.02)),
            "recall_floor": float(parameter_pack["recall_floor"]),
            "recall_pass_rule": "dedicated 160-block semantic corpus "
                                "的 block-cluster bootstrap 单侧 95% LCB "
                                ">= recall_floor(unique event 去重;"
                                "canonical D0/A;marginal guard 只用点估计"
                                "≥0.90 灾难护栏)",
            "cluster_unit": "matched block / independent pair",
            "mirror_bound": "lo = max(1, t-16); hi = min(t-8, n-17)",
            "semantic_blocks_per_corpus": 160,
        },
        "preprocessing_v2": {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
            "contract_digest": preprocessing_v2_contract_digest,
            "implementation": "pinned vendor IFreqaiModel."
                              "define_data_pipeline(直接复用;R11 全新"
                              "语料重新资格验证)",
            "vendor_pipeline_steps": [
                "ds.VarianceThreshold(threshold=0)",
                "SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))",
            ],
            "runtime_config_identity": (
                production_runtime_config_identity()),
            "ordered_feature_columns": list(PRODUCTION_FEATURE_COLUMNS),
            "feature_survival_requirement": "8/8 全部存活,"
                                            "observation dim 恒为 9",
            "position_slot": POSITION_SLOT_SEMANTICS_V2,
            "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
            "fit_protocol": "offline training-corpus fit -> frozen "
                            "deployment transform;统一 single "
                            "preprocessor,C1/C2/C3 共享;position 不"
                            "参与 fit;staged/mixed 同 multiset 同 state",
            "fit_manifest_derivation": "build_fit_manifest_entries"
                                       "(逐 episode provenance;"
                                       "multiset hash 行序不敏感)",
        },
        "pair_table": {
            "schema": PAIR_TABLE_SCHEMA,
            "schema_identity": pair_table_schema_identity(),
            "c2_block_table": BLOCK_TABLE_SCHEMA,
            "c2_block_table_identity": block_table_schema_identity(),
            "difficulty": "reference_pair - always_flat_pair",
            "fixed_baseline_margin": "逐固定基线,无 hindsight",
            "statistical_unit": "C1/C3 pair cluster(A/B 均值);C2 matched "
                                "block(四 rung 配对差分);cue 语义 = "
                                "unique event 去重 + block cluster "
                                "bootstrap",
        },
        "statistics_rule": {
            **STRICT_GATE_RULE_IDENTITY,
            "rule_identity": strict_gate_rule_identity(),
            "cue_rule_identity": cue_semantic_rule_identity(),
            "kappa": float(kappa),
            "pooled_role": "仅诊断;不得把任一 corpus FAIL 救成 PASS",
        },
        "density_thresholds": density_thresholds,
        "fit_bank_schedule": {
            "calibration": {
                "namespace": "preprocess_fit_calibration_r11",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "main fit corpus(preprocessor only)"},
            "holdout": {
                "namespace": "preprocess_fit_holdout_r11",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "independent fit holdout(preprocessor only)"},
            "final": {
                "namespace": "preprocess_fit_qualification_r11",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "final fit bank(plan lock + sealed preflight "
                        "后首次生成)"},
        },
        "semantic_corpus_schedule": {
            "design": {
                "namespaces": ["cue_semantic_design_main_r11",
                               "cue_semantic_design_validation_r11"],
                "blocks_per_corpus": 160,
                "ladder": "sentinel(candidate-independent)"},
            "calibration": {
                "namespace": "cue_semantic_calibration_r11",
                "blocks_per_corpus": 160,
                "ladder": "selected(pack)"},
            "holdout": {
                "namespace": "cue_semantic_holdout_r11",
                "blocks_per_corpus": 160,
                "ladder": "selected(pack)"},
            "final": {
                "namespace": "cue_semantic_qualification_r11",
                "blocks_per_corpus": 160,
                "ladder": "selected(pack)"},
        },
        "final_sample_counts": {
            "c1_pairs": 40, "c3_pairs": 40,
            "c2_matched_blocks": n_blocks,
            "c2_pairs": 4 * n_blocks,
            "core_qualification_pairs": core_pairs,
            "c2_independent_guard_pairs": independent_guard_pairs,
            "semantic_blocks": 160,
            "semantic_episodes": 160 * 8,
            "total_generated_episodes": (2 * core_pairs
                                         + 2 * independent_guard_pairs
                                         + 160 * 8),
            "total_note": "§33:core pairs = 80 + 4n;independent pairs = "
                          "80;semantic blocks = 160(×8 episodes = 1280);"
                          "报告必须分别列出 core pairs / independent "
                          "pairs / semantic blocks / semantic episodes / "
                          "total generated episodes,不得混成一个总数",
        },
        "qualification_bank_schedule": {
            "namespace": "qualification_r11",
            "c2_independent_marginal_namespace":
                "c2_independent_qualification_r11",
            "cue_semantic_namespace": "cue_semantic_qualification_r11",
            "fresh_seed_namespace": "fresh_holdout_r11",
        },
        "calibration_bundle_hash": calibration_bundle_hash,
        "holdout_bundle_hash": holdout_bundle_hash,
        "final_bundle_hash": final_bundle_hash,
        "conditioning_gate_constants": conditioning_gate_constants,
        "supervised_gate_constants": supervised_gate_constants,
        "reference_wrapper_identity": "PreprocessingAwarePolicy("
                                      "inverse-transform wrapper,方式 B;"
                                      "仅 scaled obs + frozen state)",
        "reference_thresholds_by_family": reference_thresholds_by_family,
        "frozen_parameter_identity": frozen_parameter_identity,
        "sealed_preflight_requirement": "final runner 启动前必须验证 "
                                        "sealed_final_preflight "
                                        "attestation(六要素守卫之一)",
        "prior_digests": {
            "stage2_6_1_r2_qualification_plan_digest": prior_r2_plan_digest,
            "stage2_6_2_r2_diagnostic_plan_digest":
                prior_diag262r2_plan_digest,
            "stage2_6_1_r4_parameter_pack_digest":
                prior_r4_parameter_pack_digest,
            "stage2_6_1_r5_design_plan_digest": prior_r5_design_plan_digest,
            "stage2_6_1_r6_design_plan_digest": prior_r6_design_plan_digest,
            "stage2_6_1_r7_design_plan_digest": prior_r7_design_plan_digest,
            "stage2_6_1_r8_design_plan_digest": prior_r8_design_plan_digest,
        },
        "r8_abort_evidence": r8_abort_evidence,
        "robustness_gate": {
            "preprocessing": {
                "pass": preprocessing_robustness_gate["pass"],
                "format": preprocessing_robustness_gate.get("format"),
            },
            "curriculum": {
                "pass": curriculum_robustness_gate["pass"],
                "format": curriculum_robustness_gate.get("format"),
                "rule": "strict per-corpus AND + C2 matched block + "
                        "cluster-aware cue semantics + independent "
                        "marginal guard",
            },
            "pass": True,
        },
        "equivalence_pass": bool(
            equivalence_report["pass"]) if equivalence_report else None,
        "code_identity": _code_identity_r11(),
    }
    return plan


def plan_digest_r11(plan: dict[str, Any]) -> str:
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "qp10-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def lock_plan_r11(plan: dict[str, Any]) -> tuple[Path, str]:
    from datetime import datetime, timezone

    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = qualification_r11_plan_path()
    if path.is_file():
        raise RuntimeError(
            "R11 qualification plan 已存在;plan lock 后禁止重写(§16.2/"
            "§26:任何修改须新 iteration R11)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = plan_digest_r11(plan)
    dpath = qualification_r11_digest_path()
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_plan_r11() -> tuple[dict[str, Any], str]:
    path = qualification_r11_plan_path()
    dpath = qualification_r11_digest_path()
    if not path.is_file() or not dpath.is_file():
        raise RuntimeError("R11 qualification plan 未锁定")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = plan_digest_r11(plan)
    if dpath.read_text(encoding="utf-8").strip() != digest:
        raise RuntimeError("R11 plan digest 复算不一致(fail closed)")
    return plan, digest


# ---------------------------------------------------- rehearsal plan(§12)
def build_rehearsal_qualification_plan_r11(
        *, pack: dict[str, Any], stage_summary: dict[str, Any],
        final_namespace: str,
        fit_namespace: str) -> tuple[dict[str, Any], str]:
    """§12 rehearsal 用精简 plan(临时目录;preplan namespace;非正式)。

    绕过正式 build_plan_r11 的双 gate 断言(rehearsal 的小样本 gate
    结果不作资格判定),绑定 rehearsal digest 与共享 orchestrator
    身份;正式 plan 仍走 build_plan_r11 + lock_plan_r11。
    """
    plan = {
        "format": "cur261-r11-rehearsal-qualification-plan-v1",
        "iteration": "r11",
        "rehearsal": True,
        "final_namespace": final_namespace,
        "fit_namespace": fit_namespace,
        "pack_digest": pack.get("digest"),
        "orchestrator": "orchestrate_calibration_stage_r11",
        "calibration_stage_pass": bool(stage_summary.get("pass")),
        "profiles": stage_summary.get("profiles"),
        "routing_matrix_all_pass": stage_summary.get(
            "routing_matrix_all_pass"),
        "supervised_main_pass": stage_summary.get("supervised_main_pass"),
        "supervised_holdout_pass": stage_summary.get(
            "supervised_holdout_pass"),
        "namespaces_preplan_only": True,
    }
    return plan, plan_digest_r11(plan)


def lock_qualification_plan_r11(
        lock_dir: Path, plan: dict[str, Any]) -> tuple[Path, str]:
    """把 plan 锁进指定目录(O_EXCL;禁覆盖)。"""
    import json as _json

    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / "qualification_plan_r11.json"
    digest = plan_digest_r11(plan)
    plan = dict(plan)
    plan["plan_digest"] = digest
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     0o644)
    except FileExistsError as exc:
        raise RuntimeError(
            "rehearsal plan 已存在;禁止删除/覆盖/重锁(§21)") from exc
    try:
        os.write(fd, _json.dumps(
            plan, indent=1, ensure_ascii=False,
            default=str).encode("utf-8"))
    finally:
        os.close(fd)
    (lock_dir / "qualification_plan_digest_r11.txt").write_text(
        digest, encoding="utf-8")
    return path, digest


def load_locked_qualification_plan_r11(
        lock_dir: Path) -> tuple[dict[str, Any], str]:
    """读取并复算 rehearsal plan(fail closed)。"""
    import json as _json

    lock_dir = Path(lock_dir)
    path = lock_dir / "qualification_plan_r11.json"
    plan = _json.loads(path.read_text(encoding="utf-8"))
    stored = plan.get("plan_digest")
    plan.pop("plan_digest", None)
    digest = plan_digest_r11(plan)
    if stored != digest:
        raise RuntimeError("rehearsal plan digest 复算不一致(fail closed)")
    plan["plan_digest"] = digest
    return plan, digest
