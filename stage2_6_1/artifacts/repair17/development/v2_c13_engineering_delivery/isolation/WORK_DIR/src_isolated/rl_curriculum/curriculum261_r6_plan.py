# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6:final qualification plan 构建、digest 与锁定(§30)。

§30 plan 绑定清单:R6 iteration、R6 parameter-pack digest、C2 四档
参数、selected formal block count、matched-ladder contract、base
random tape identity、block attempt 语义、V2 contract、fit protocol、
统计定义(strict per-corpus + block-cluster/marginal guard)、final
namespaces、final sample counts(80 + 4×selected_block_count)、
code identity、vendor/runtime/Route C identities、R4/R5 历史 digests。

只有 design PASS + calibration strict PASS + holdout strict PASS +
independent marginal guards PASS + preprocessing PASS + supervised PASS
才允许生成 plan;plan lock 后禁止任何代码/统计规则/parameter pack
修改。final runner 额外要求 sealed preflight attestation
(qualification_r6_unlocked 六要素)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r6_namespaces import (
    CURRICULUM261_ITERATION_ID_R6,
    qualification_r6_plan_path,
    qualification_r6_digest_path,
)

PLAN_FORMAT_R6 = "cur261-r6-qualification-plan-v1"

#: R6 代码身份(逐模块内容哈希;进入 plan;final 复算比对)。
PLAN_CODE_MODULES_R6 = (
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
    "curriculum261_r6_design.py",
    "curriculum261_r6_calibration.py",
    "curriculum261_r6_preflight.py",
    "curriculum261_r6_plan.py",
    "curriculum261_r6_final.py",
    "curriculum261_r6_smoke.py",
    "curriculum261_r6_cli.py",
)


def _code_identity_r6() -> dict[str, str]:
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES_R6:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def build_plan_r6(
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
        equivalence_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 R6 final qualification plan(双 strict gate 前置强制)。"""
    if not (isinstance(preprocessing_robustness_gate, dict)
            and preprocessing_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "preprocessing robustness gate 未 PASS,禁止生成 R6 plan"
            "(§28:任一 gate FAIL -> STOP,不得 lock)")
    if not (isinstance(curriculum_robustness_gate, dict)
            and curriculum_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "curriculum robustness gate(strict per-corpus + C2 matched "
            "block + marginal guard)未 PASS,禁止生成 R6 plan")
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
    )
    from rl_curriculum.curriculum261_r4_pairs import (
        PAIR_TABLE_SCHEMA, pair_table_schema_identity)
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
    total_pairs = 80 + 4 * n_blocks
    plan: dict[str, Any] = {
        "format": PLAN_FORMAT_R6,
        "iteration": CURRICULUM261_ITERATION_ID_R6,
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "frozen_contracts": frozen_contracts,
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
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
        },
        "design": {
            "design_plan_digest": design_plan_digest,
            "selected_c2_candidate": selected_c2_candidate,
        },
        "matched_ladder": {
            "contract_version": C2_MATCHED_LADDER_BLOCK_VERSION,
            "contract_identity": matched_ladder_contract_identity(),
            "block_integrity_identity": parameter_pack[
                "block_integrity_identity"],
            "block_attempt_semantics": "block-level max_attempts=5;"
                                       "任一 rung 或跨 rung matching 失败"
                                       " → 整 block 重试;禁止只重采样失败"
                                       " rung / 按 PnL 拒绝 / 无限重采样",
            "statistical_unit": "matched block(四 rung 同结构带配对差分;"
                                "gap SE = std(blockwise)/sqrt(n_blocks);"
                                "禁止独立 SE 二次合成)",
            "scrambled_control": "仅诊断(不参与 PASS 判定)",
            "independent_marginal_guard": "独立-rung 语料 mean ordering/"
                                          "D3/逐基线 positive/integrity/"
                                          "密度/语义(matched PASS 不可覆盖)",
        },
        "preprocessing_v2": {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
            "contract_digest": preprocessing_v2_contract_digest,
            "implementation": "pinned vendor IFreqaiModel."
                              "define_data_pipeline(直接复用;与 R4 逐位"
                              "同实现,R6 全新语料重新资格验证)",
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
                                "block(四 rung 配对差分)",
        },
        "statistics_rule": {
            **STRICT_GATE_RULE_IDENTITY,
            "rule_identity": strict_gate_rule_identity(),
            "kappa": float(kappa),
            "pooled_role": "仅诊断;不得把任一 corpus FAIL 救成 PASS",
        },
        "density_thresholds": density_thresholds,
        "fit_bank_schedule": {
            "calibration": {
                "namespace": "preprocess_fit_calibration_r6",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "main fit corpus(preprocessor only)"},
            "holdout": {
                "namespace": "preprocess_fit_holdout_r6",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "independent fit holdout(preprocessor only)"},
            "final": {
                "namespace": "preprocess_fit_qualification_r6",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "final fit bank(plan lock + sealed preflight "
                        "后首次生成)"},
        },
        "final_sample_counts": {
            "c1_pairs": 40, "c3_pairs": 40,
            "c2_matched_blocks": n_blocks,
            "c2_pairs": 4 * n_blocks,
            "total_pairs": total_pairs,
            "total_note": "C1:4 rungs x 10 pairs;C3:4 rungs x 10 pairs;"
                          "C2:selected blocks x 4 rung pairs(实际数量随"
                          " selected_block_count:10->120/15->140/20->160)",
        },
        "qualification_bank_schedule": {
            "namespace": "qualification_r6",
            "c2_independent_marginal_namespace":
                "c2_independent_qualification_r6",
            "fresh_seed_namespace": "fresh_holdout_r6",
        },
        "calibration_bundle_hash": calibration_bundle_hash,
        "holdout_bundle_hash": holdout_bundle_hash,
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
        },
        "robustness_gate": {
            "preprocessing": {
                "pass": preprocessing_robustness_gate["pass"],
                "format": preprocessing_robustness_gate.get("format"),
            },
            "curriculum": {
                "pass": curriculum_robustness_gate["pass"],
                "format": curriculum_robustness_gate.get("format"),
                "rule": "strict per-corpus AND + C2 matched block + "
                        "independent marginal guard",
            },
            "pass": True,
        },
        "equivalence_pass": bool(
            equivalence_report["pass"]) if equivalence_report else None,
        "code_identity": _code_identity_r6(),
    }
    return plan


def plan_digest_r6(plan: dict[str, Any]) -> str:
    """plan digest(canonical JSON 去 created_utc)。"""
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "qp6-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def lock_plan_r6(plan: dict[str, Any]) -> tuple[Path, str]:
    """写 plan JSON + digest txt(lock 目录=R6 artifacts)。"""
    from datetime import datetime, timezone

    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = qualification_r6_plan_path()
    if path.is_file():
        raise RuntimeError(
            "R6 qualification plan 已存在;plan lock 后禁止重写(代码/"
            "规则/pack 修改须新 iteration)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = plan_digest_r6(plan)
    dpath = qualification_r6_digest_path()
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_plan_r6() -> tuple[dict[str, Any], str]:
    """读回锁定 plan 并复算 digest(防篡改;fail closed)。"""
    path = qualification_r6_plan_path()
    if not path.is_file():
        raise RuntimeError(f"R6 plan 不存在: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = plan_digest_r6(plan)
    locked = qualification_r6_digest_path().read_text(
        encoding="utf-8").strip()
    if digest != locked:
        raise RuntimeError(
            f"R6 plan digest 漂移(重算 {digest} != 锁定 {locked});"
            f"fail closed")
    return plan, digest
