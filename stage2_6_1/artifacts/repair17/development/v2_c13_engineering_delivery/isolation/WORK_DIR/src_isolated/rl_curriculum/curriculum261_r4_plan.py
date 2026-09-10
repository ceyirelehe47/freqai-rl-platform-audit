"""阶段 2.6.1 Repair R4:final qualification plan 构建、digest 与锁定。

§26 plan 绑定(全部机器可验证):
R4 iteration、R4 parameter-pack digest 与正式 D3 参数、C2/D0-D2 历史
参数 identity、preprocessing V2 contract digest、vendor pipeline
identity、runtime config identity、feature construction identity、
observation-space identity(V2 无界语义)、fit protocol、fit manifest
derivation、pair table schema identity、difficulty metric identity、
fixed-baseline margin identity、pair-cluster/bootstrap 方法、κ、
qualification seed schedule、final fit bank schedule、metrics 与
thresholds、code identity、baseline Git SHA、vendor SHA、Route C 六项
identity、R2/R3 历史 digests。

只有 preprocessing 与 curriculum 两个 robustness gate 均 PASS 才允许
生成 plan(fail closed)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r4_namespaces import (
    CURRICULUM261_ITERATION_ID_R4,
    R4_PLAN_DIGEST_FILENAME,
    R4_PLAN_FILENAME,
    qualification_r4_digest_path,
    qualification_r4_plan_path,
)

PLAN_FORMAT_R4 = "cur261-r4-qualification-plan-v1"

#: R4 课程代码身份(逐模块内容哈希;进入 plan;final 复算比对)。
PLAN_CODE_MODULES_R4 = (
    "curriculum261_api.py",
    "curriculum261_production_obs.py",
    "curriculum261_c1.py",
    "curriculum261_c2.py",
    "curriculum261_c3.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "evaluator.py",
    "curriculum261_r3_preprocessing.py",
    "curriculum261_r3_obs.py",
    "curriculum261_r4_namespaces.py",
    "curriculum261_r4_param_pack.py",
    "curriculum261_r4_preprocessing.py",
    "curriculum261_r4_obs.py",
    "curriculum261_r4_pairs.py",
    "curriculum261_r4_power.py",
    "curriculum261_r4_calibration.py",
    "curriculum261_r4_plan.py",
    "curriculum261_r4_final.py",
    "curriculum261_r4_smoke.py",
    "curriculum261_r4_cli.py",
)


def _code_identity_r4() -> dict[str, str]:
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES_R4:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def build_plan_r4(
        *,
        baseline_commit: str,
        vendor_pin: str,
        frozen_contracts: dict[str, str],
        parameter_pack: dict[str, Any],
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
        prior_r2_plan_digest: str,
        prior_diag262r2_plan_digest: str,
        prior_r3_baseline_commit: str,
        equivalence_report: dict[str, Any] | None = None,
        design_results_digest: str | None = None,
) -> dict[str, Any]:
    """构建 R4 final qualification plan(gate 双 PASS 前置强制)。"""
    if not (isinstance(preprocessing_robustness_gate, dict)
            and preprocessing_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "preprocessing robustness gate 未 PASS,禁止生成 R4 plan"
            "(§25:任一 gate FAIL -> STOP,不得 lock)")
    if not (isinstance(curriculum_robustness_gate, dict)
            and curriculum_robustness_gate.get("pass") is True):
        raise RuntimeError(
            "curriculum robustness gate 未 PASS,禁止生成 R4 plan"
            "(§25:任一 gate FAIL -> STOP,不得 lock)")
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
        production_runtime_config_identity,
    )
    from rl_curriculum.curriculum261_r4_param_pack import (
        R4_PACK_VERSION,
        pack_digest as _pack_digest,
    )
    from rl_curriculum.curriculum261_r4_pairs import (
        PAIR_TABLE_SCHEMA,
        pair_table_schema_identity,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
        feature_construction_identity_light,
        fit_protocol_digest,
        production_pipeline_identity_light,
    )
    from rl_platform.versions import (
        ENV_CORE_VERSION,
        OBSERVATION_SPEC_VERSION,
    )

    plan: dict[str, Any] = {
        "format": PLAN_FORMAT_R4,
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "frozen_contracts": frozen_contracts,
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
            "note": "内层 AlignedLongFlatEnv 冻结声明(Box(-10,10)为其"
                    "内部 layout)不变;V2 正式 preprocessing 后空间由"
                    "外层 wrapper 声明(无界 feature + [0,1] position)",
        },
        "parameter_pack": {
            "pack_version": R4_PACK_VERSION,
            "digest": parameter_pack.get("digest")
                      or _pack_digest(parameter_pack),
            "selected": parameter_pack["selected"],
            "d3_overrides": parameter_pack["d3_overrides"],
            "design_results_digest": design_results_digest,
        },
        "frozen_parameter_identity": frozen_parameter_identity,
        "preprocessing_v2": {
            "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
            "contract_digest": preprocessing_v2_contract_digest,
            "numerics": "与 RouteCFeaturePreprocessing-v1 逐位一致"
                        "(vendor pipeline 直接复用)",
            "vendor_pipeline_steps": [
                "ds.VarianceThreshold(threshold=0)",
                "SKLearnWrapper(MinMaxScaler(feature_range=(-1,1)))",
            ],
            "production_pipeline_identity":
                production_pipeline_identity_light(),
            "runtime_config_identity": production_runtime_config_identity(),
            "feature_construction_identity":
                feature_construction_identity_light(),
            "ordered_feature_columns": list(
                PRODUCTION_FEATURE_COLUMNS),
            "feature_survival_requirement": "8/8 全部存活,"
                                            "observation dim 恒为 9",
            "position_slot": POSITION_SLOT_SEMANTICS_V2,
            "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
            "outer_wrapper": "RouteCPreprocessingEnvV2",
            "identity_layers": {
                "parameter_state_hash": "r4ps-",
                "fit_manifest_multiset_hash": "r4fm-",
                "preprocessor_bundle_hash": "r4pb-",
            },
            "fit_protocol_digest": fit_protocol_digest(),
            "fit_manifest_derivation": "每 fit bank episode 一条 entry"
                                       "(namespace/family/rung/pair/"
                                       "side/episode hash/feature-"
                                       "matrix hash/generator+pack "
                                       "identity);multiset hash 行序"
                                       "不敏感",
        },
        "fit_bank_schedule": {
            "calibration": {
                "namespace": "preprocess_fit_calibration_r4",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "main fit corpus(preprocessor only)"},
            "holdout": {
                "namespace": "preprocess_fit_holdout_r4",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "independent fit holdout(preprocessor only)"},
            "final": {
                "namespace": "preprocess_fit_qualification_r4",
                "pairs_per_rung": 4, "sides": ["A", "B"],
                "role": "final fit bank(plan lock 后首次生成)"},
        },
        "qualification_bank_schedule": {
            "namespace": "qualification_r4",
            "families": 3, "rungs": 4, "pairs_per_rung": 10,
            "sides": ["A", "B"], "total_pairs": 120,
            "fresh_seed_namespace": "fresh_holdout_r4",
        },
        "calibration_bundle_hash": calibration_bundle_hash,
        "holdout_bundle_hash": holdout_bundle_hash,
        "conditioning_gate_constants": conditioning_gate_constants,
        "supervised_gate_constants": supervised_gate_constants,
        "reference_wrapper_identity": "PreprocessingAwarePolicy("
                                      "inverse-transform wrapper,方式 B;"
                                      "仅 scaled obs + frozen state)",
        "reference_thresholds_by_family": reference_thresholds_by_family,
        "statistics": {
            "pair_table_schema": PAIR_TABLE_SCHEMA,
            "pair_table_schema_identity": pair_table_schema_identity(),
            "difficulty_metric": "difficulty_pair[p] = reference_pair[p]"
                                 " - always_flat_pair[p]",
            "fixed_baseline_margin": "margin[p,b] = reference_pair[p] - "
                                     "baseline_b_pair[p](逐固定基线;"
                                     "禁止 episode 级 hindsight max)",
            "uncertainty": "pair cluster(A/B 均值为单一 cluster 样本;"
                           "SE = sd/sqrt(n_pairs))",
            "bootstrap": "percentile;按 pair 重采样(A/B 不拆散);"
                         "seed=20260901;resamples=5000;辅助证据,"
                         "不替代 κ gate",
            "kappa": float(kappa),
        },
        "thresholds": {
            "ordering": "D0>D1>D2>D3",
            "d3_positive": True,
            "d3_ge_kappa_pair_se": True,
            "gap_ge_kappa_pair_se": True,
            "fixed_baseline_margin_positive_and_ge_kappa_pair_se": True,
            "pair_integrity_unity": True,
            "oracle_positive": True,
        },
        "seed_derivation": "derive261_seed(namespace, family, rung, "
                           "pair, attempt);R4 namespace 白名单;"
                           "qualification_r4/preprocess_fit_"
                           "qualification_r4 lock 前封闭(完整守卫:"
                           "plan+digest 重算+gate+parameter pack 绑定)",
        "code_identity": _code_identity_r4(),
        "prior_digests": {
            "stage2_6_1_r2_qualification_plan_digest": prior_r2_plan_digest,
            "stage2_6_2_r2_diagnostic_plan_digest": (
                prior_diag262r2_plan_digest),
            "stage2_6_1_r3_baseline_commit": prior_r3_baseline_commit,
            "stage2_6_1_r3_status": "FAIL(R3 plan 从未 lock;其全部"
                                    "资格证据与 FAIL 判定保留)",
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
    }
    return plan


def plan_digest_r4(plan: dict[str, Any]) -> str:
    """plan digest(canonical JSON 去 created_utc;与 R2/R3 同规则)。"""
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "qp4-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def lock_plan_r4(plan: dict[str, Any]) -> tuple[Path, str]:
    """写 plan JSON + digest txt(lock 目录=R4 artifacts)。"""
    from datetime import datetime, timezone

    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = qualification_r4_plan_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = plan_digest_r4(plan)
    dpath = qualification_r4_digest_path()
    dpath.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_plan_r4() -> tuple[dict[str, Any], str]:
    """读回锁定 plan 并复算 digest(防篡改;fail closed)。"""
    path = qualification_r4_plan_path()
    if not path.is_file():
        raise RuntimeError(f"R4 plan 不存在: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = plan_digest_r4(plan)
    locked = qualification_r4_digest_path().read_text(
        encoding="utf-8").strip()
    if digest != locked:
        raise RuntimeError(
            f"R4 plan digest 漂移(重算 {digest} != 锁定 {locked});"
            f"fail closed")
    return plan, digest
