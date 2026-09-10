# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:final qualification plan 构建、digest 与锁定(§28)。

§28 plan 绑定清单:R5 iteration、R5 parameter-pack digest、Tier A/B
执行状态、selected C2 candidate、Preprocessing V2 contract、
observation-space identity、vendor pipeline、runtime config、feature
construction、fit protocol、fit manifest derivation、pair table
identity、difficulty identity、fixed baseline margin identity、strict
per-corpus rule、pair-cluster SE、bootstrap 方法、κ、density
thresholds、supervised thresholds、final fit schedule、final
qualification schedule、final namespaces、code identity、baseline SHA、
vendor SHA、Route C identities、R4 历史 digests。

只有 strict calibration 与 strict holdout 双 PASS + preprocessing gate
PASS + supervised PASS 才允许生成 plan;plan lock 后禁止任何代码/统计
规则/parameter pack 修改。final runner 额外要求 sealed preflight
attestation(qualification_r5_unlocked 六要素)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r5_namespaces import (
    CURRICULUM261_ITERATION_ID_R5,
    qualification_r5_plan_path,
    qualification_r5_digest_path,
)

PLAN_FORMAT_R5 = "cur261-r5-qualification-plan-v1"

#: R5 代码身份(逐模块内容哈希;进入 plan;final 复算比对)。
PLAN_CODE_MODULES_R5 = (
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
    "curriculum261_r5_param_pack.py",
    "curriculum261_r5_namespaces.py",
    "curriculum261_r5_pairs.py",
    "curriculum261_r5_design.py",
    "curriculum261_r5_calibration.py",
    "curriculum261_r5_preflight.py",
    "curriculum261_r5_plan.py",
    "curriculum261_r5_final.py",
    "curriculum261_r5_smoke.py",
    "curriculum261_r5_cli.py",
)


def _code_identity_r5() -> dict[str, str]:
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES_R5:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def build_plan_r5(
        *,
        baseline_commit: str,
        vendor_pin: str,
        frozen_contracts: dict[str, str],
        parameter_pack: dict[str, Any],
        design_plan_digest: str,
        selected_c2_candidate: str,
        tier_executed: str,
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
        prior_r4_baseline_commit: str,
        prior_r4_parameter_pack_digest: str,
        equivalence_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 R5 final qualification plan(双 strict gate 前置强制)。"""
    if not (isinstance(preprocessing_robustness_gate, dict)
            and preprocessing_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "preprocessing robustness gate 未 PASS,禁止生成 R5 plan"
            "(§22:任一 gate FAIL -> STOP,不得 lock)")
    if not (isinstance(curriculum_robustness_gate, dict)
            and curriculum_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "curriculum robustness gate(strict per-corpus)未 PASS,"
            "禁止生成 R5 plan(§22:任一 corpus/family FAIL -> STOP)")
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
    )
    from rl_curriculum.curriculum261_r4_pairs import (
        PAIR_TABLE_SCHEMA, pair_table_schema_identity)
    from rl_curriculum.curriculum261_r5_pairs import (
        STRICT_GATE_RULE_IDENTITY, strict_gate_rule_identity)
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
        production_runtime_config_identity,
    )
    from rl_platform.versions import (
        ENV_CORE_VERSION,
        OBSERVATION_SPEC_VERSION,
    )

    plan: dict[str, Any] = {
        "format": PLAN_FORMAT_R5,
        "iteration": CURRICULUM261_ITERATION_ID_R5,
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
            "tier": parameter_pack["tier"],
            "selected_c2_candidate": parameter_pack[
                "selected_c2_candidate"],
            "r4_parameter_pack_digest": parameter_pack[
                "r4_parameter_pack_digest"],
        },
        "design": {
            "design_plan_digest": design_plan_digest,
            "tier_executed": tier_executed,
            "selected_c2_candidate": selected_c2_candidate,
        },
        "preprocessing_v2": {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
            "contract_digest": preprocessing_v2_contract_digest,
            "implementation": "pinned vendor IFreqaiModel."
                              "define_data_pipeline(直接复用;与 R4 逐位"
                              "同实现,R5 全新语料重新资格验证)",
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
            "difficulty": "reference_pair - always_flat_pair",
            "fixed_baseline_margin": "逐固定基线,无 hindsight"
                                     "(禁止 episode 级 max/动态选对手)",
            "statistical_unit": "pair cluster(A/B 均值)",
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
                "namespace": "preprocess_fit_calibration_r5",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "main fit corpus(preprocessor only)"},
            "holdout": {
                "namespace": "preprocess_fit_holdout_r5",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "independent fit holdout(preprocessor only)"},
            "final": {
                "namespace": "preprocess_fit_qualification_r5",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "final fit bank(plan lock + sealed preflight "
                        "后首次生成)"},
        },
        "qualification_bank_schedule": {
            "namespace": "qualification_r5",
            "families": 3, "rungs": 4, "pairs_per_rung": 10,
            "sides": ["A", "B"], "total_pairs": 120,
            "fresh_seed_namespace": "fresh_holdout_r5",
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
            "stage2_6_1_r4_baseline_commit": prior_r4_baseline_commit,
            "stage2_6_1_r4_parameter_pack_digest":
                prior_r4_parameter_pack_digest,
        },
        "robustness_gate": {
            "preprocessing": {
                "pass": preprocessing_robustness_gate["pass"],
                "format": preprocessing_robustness_gate.get("format"),
            },
            "curriculum": {
                "pass": curriculum_robustness_gate["pass"],
                "format": curriculum_robustness_gate.get("format"),
                "rule": "strict per-corpus AND",
            },
            "pass": True,
        },
        "equivalence_pass": bool(
            equivalence_report["pass"]) if equivalence_report else None,
        "code_identity": _code_identity_r5(),
    }
    return plan


def plan_digest_r5(plan: dict[str, Any]) -> str:
    """plan digest(canonical JSON 去 created_utc)。"""
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "qp5-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def lock_plan_r5(plan: dict[str, Any]) -> tuple[Path, str]:
    """写 plan JSON + digest txt(lock 目录=R5 artifacts)。"""
    from datetime import datetime, timezone

    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = qualification_r5_plan_path()
    if path.is_file():
        raise RuntimeError(
            "R5 qualification plan 已存在;plan lock 后禁止重写(代码/"
            "规则/pack 修改须新 iteration)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = plan_digest_r5(plan)
    dpath = qualification_r5_digest_path()
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_plan_r5() -> tuple[dict[str, Any], str]:
    """读回锁定 plan 并复算 digest(防篡改;fail closed)。"""
    path = qualification_r5_plan_path()
    if not path.is_file():
        raise RuntimeError(f"R5 plan 不存在: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = plan_digest_r5(plan)
    locked = qualification_r5_digest_path().read_text(
        encoding="utf-8").strip()
    if digest != locked:
        raise RuntimeError(
            f"R5 plan digest 漂移(重算 {digest} != 锁定 {locked});"
            f"fail closed")
    return plan, digest
