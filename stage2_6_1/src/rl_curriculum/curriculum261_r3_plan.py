"""阶段 2.6.1 Repair R3:final qualification plan 构建、digest 与锁定(WP-I)。

§26 plan 绑定:R3 iteration identity、production preprocessing
implementation identity、vendor preprocessing identity、runtime config
hash、ordered feature columns、fit protocol、fit bank schedule、
qualification bank schedule、feature-survival requirement、
observation-space semantics、reference-wrapper identity、family/rung
generator config、metrics、thresholds、pair-cluster uncertainty 方法、
seed derivation、code identity、baseline Git SHA、vendor SHA、Route C
identities、prior R2 and diagnostic digests。

只有 preprocessing 与 curriculum 两个 robustness gate 均 PASS 才允许
生成 plan(Layer A/B/C 三层强制与 R2 相同)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r3_namespaces import (
    CURRICULUM261_ITERATION_ID_R3,
    R3_PLAN_DIGEST_FILENAME,
    R3_PLAN_FILENAME,
    qualification_r3_digest_path,
    qualification_r3_plan_path,
)

PLAN_FORMAT_R3 = "cur261-r3-qualification-plan-v1"

#: R3 课程代码身份(逐模块内容哈希;进入 plan;final 复算比对)。
PLAN_CODE_MODULES_R3 = (
    "curriculum261_api.py",
    "curriculum261_production_obs.py",
    "curriculum261_c1.py",
    "curriculum261_c2.py",
    "curriculum261_c3.py",
    "curriculum261_pairs.py",
    "curriculum261_r3_preprocessing.py",
    "curriculum261_r3_obs.py",
    "curriculum261_r3_namespaces.py",
    "curriculum261_r3_calibration.py",
    "curriculum261_r3_plan.py",
    "curriculum261_r3_final.py",
    "curriculum261_r3_smoke.py",
    "curriculum261_r3_cli.py",
)


def _code_identity_r3() -> dict[str, str]:
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES_R3:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def build_plan_r3(
    *,
    baseline_commit: str,
    vendor_pin: str,
    frozen_contracts: dict[str, str],
    preprocessing_contract_digest: str,
    calibration_state_hash: str,
    holdout_state_hash: str,
    preprocessing_robustness_gate: dict[str, Any],
    curriculum_robustness_gate: dict[str, Any],
    conditioning_gate_constants: dict[str, Any],
    supervised_gate_constants: dict[str, Any],
    kappa: float,
    rung_params_by_family: dict[str, Any],
    reference_thresholds_by_family: dict[str, Any],
    prior_r2_plan_digest: str,
    prior_diag262r2_plan_digest: str,
    equivalence_report: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建 R3 final qualification plan(gate 双 PASS 前置强制)。"""
    if not (isinstance(preprocessing_robustness_gate, dict)
            and preprocessing_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "preprocessing robustness gate 未 PASS,禁止生成 R3 plan"
            "(§22:任一 gate FAIL -> STOP,不得 lock)")
    if not (isinstance(curriculum_robustness_gate, dict)
            and curriculum_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "curriculum robustness gate 未 PASS,禁止生成 R3 plan"
            "(§22:任一 gate FAIL -> STOP,不得 lock)")
    from rl_curriculum.curriculum261_r3_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS,
        POSITION_SLOT_SEMANTICS,
        ROUTE_C_FEATURE_PREPROCESSING_VERSION,
    )
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
        production_runtime_config_identity,
    )
    from rl_platform.versions import (
        ENV_CORE_VERSION,
        OBSERVATION_SPEC_VERSION,
    )

    plan: dict[str, Any] = {
        "format": PLAN_FORMAT_R3,
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "frozen_contracts": frozen_contracts,
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
        },
        "preprocessing": {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_VERSION,
            "contract_digest": preprocessing_contract_digest,
            "implementation": "pinned vendor IFreqaiModel."
                              "define_data_pipeline(直接复用)",
            "vendor_pipeline_steps": [
                "ds.VarianceThreshold(threshold=0)",
                "SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))",
            ],
            "runtime_config_identity": (
                production_runtime_config_identity()),
            "ordered_feature_columns": list(PRODUCTION_FEATURE_COLUMNS),
            "feature_survival_requirement": "8/8 全部存活,"
                                            "observation dim 恒为 9",
            "position_slot": POSITION_SLOT_SEMANTICS,
            "observation_space": OBSERVATION_SPACE_SEMANTICS,
            "fit_protocol": "offline training-corpus fit -> frozen "
                            "deployment transform;统一 single "
                            "preprocessor,C1/C2/C3 共享;position 不"
                            "参与 fit;staged/mixed 同 multiset 同 state",
        },
        "fit_bank_schedule": {
            "calibration": {
                "namespace": "preprocess_fit_calibration_r3",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "main fit corpus(preprocessor only)"},
            "holdout": {
                "namespace": "preprocess_fit_holdout_r3",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "independent fit holdout(preprocessor only)"},
            "final": {
                "namespace": "preprocess_fit_qualification_r3",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "final fit bank(plan lock 后首次生成)"},
        },
        "qualification_bank_schedule": {
            "namespace": "qualification_r3",
            "families": 3, "rungs": 4, "pairs_per_rung": 10,
            "sides": ["A", "B"], "total_pairs": 120,
            "fresh_seed_namespace": "fresh_holdout_r3",
        },
        "calibration_state_hash": calibration_state_hash,
        "holdout_state_hash": holdout_state_hash,
        "conditioning_gate_constants": conditioning_gate_constants,
        "supervised_gate_constants": supervised_gate_constants,
        "reference_wrapper_identity": "PreprocessingAwarePolicy("
                                      "inverse-transform wrapper,方式 B;"
                                      "仅 scaled obs + frozen state)",
        "rung_params_by_family": rung_params_by_family,
        "reference_thresholds_by_family": reference_thresholds_by_family,
        "metrics": {
            "difficulty_metric": "pair-cluster reference net return - "
                                 "max(0, always_long pair-cluster mean)",
            "uncertainty": "pair cluster(A/B 均值为单一样本;bootstrap "
                           "与 SE 均 cluster 口径)",
            "kappa": float(kappa),
        },
        "thresholds": {
            "ordering": "D0>D1>D2>D3",
            "d3_positive": True,
            "reference_beats_required": True,
            "pair_integrity_unity": True,
            "gap_ge_kappa_pair_se": True,
            "d3_ge_kappa_pair_se": True,
            "reference_margin_ge_kappa_pair_se": True,
        },
        "seed_derivation": "derive261_seed(namespace, family, rung, "
                           "pair, attempt);R3 namespace 白名单;"
                           "qualification_r3/preprocess_fit_"
                           "qualification_r3 lock 前封闭(完整守卫:"
                           "plan+digest 重算+gate)",
        "code_identity": _code_identity_r3(),
        "prior_digests": {
            "stage2_6_1_r2_qualification_plan_digest": prior_r2_plan_digest,
            "stage2_6_2_r2_diagnostic_plan_digest": (
                prior_diag262r2_plan_digest),
        },
        "robustness_gate": {
            "preprocessing": {
                "pass": preprocessing_robustness_gate["pass"],
                "format": preprocessing_robustness_gate.get("format"),
            },
            "curriculum": {
                "pass": curriculum_robustness_gate["pass"],
                "format": curriculum_robustness_gate.get("format"),
            },
            "pass": True,
        },
        "equivalence_pass": bool(
            equivalence_report["pass"]) if equivalence_report else None,
        "audit_config_sha256": (
            audit.get("config_sha256") if audit else None),
    }
    return plan


def plan_digest_r3(plan: dict[str, Any]) -> str:
    """plan digest(canonical JSON 去 created_utc;与 R2 同规则)。"""
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "qp3-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def lock_plan_r3(plan: dict[str, Any]) -> tuple[Path, str]:
    """写 plan JSON + digest txt(lock 目录=R3 artifacts)。"""
    from datetime import datetime, timezone

    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = qualification_r3_plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = plan_digest_r3(plan)
    dpath = qualification_r3_digest_path()
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_plan_r3() -> tuple[dict[str, Any], str]:
    """读回锁定 plan 并复算 digest(防篡改;fail closed)。"""
    path = qualification_r3_plan_path()
    if not path.is_file():
        raise RuntimeError(f"R3 plan 不存在: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = plan_digest_r3(plan)
    locked = qualification_r3_digest_path().read_text(
        encoding="utf-8").strip()
    if digest != locked:
        raise RuntimeError(
            f"R3 plan digest 漂移(重算 {digest} != 锁定 {locked});"
            f"fail closed")
    return plan, digest
