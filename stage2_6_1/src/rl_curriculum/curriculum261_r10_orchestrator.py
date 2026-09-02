# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R10:共享 calibration/final orchestration(§12)。

R9 确认输入(orchestration 缺陷):
- cmd_calibrate 是一条手写长流程:holdout 三处评估错传 v2_main、
  supervised 少传 namespace、reference equivalence 只留布尔值;
  正式 CLI 与 preplan rehearsal 走两套代码 —— rehearsal 通过不代表
  正式路径可用。

R10 修复(§12.4 共享 Orchestrator):
- 正式 calibrate(main/holdout)与 preplan rehearsal 调用同一
  orchestration 函数 orchestrate_calibration_bundle_r10;
- 唯一差异通过 R10ExecutionProfile 表达:namespace 集合与样本量
  (§12:只允许 execution profile 改变样本量和 namespace);
- 每个 evaluator 显式收到 routing(fail closed,§9);
- supervised 调用 keyword-only(§7);reference equivalence 走
  canonical 合同并落盘逐 mismatch 明细(§10/§11);
- main 与 holdout 各自独立评估、独立 gate(禁 pooled rescue)。
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
)
from rl_curriculum.curriculum261_r10_reference import (
    reference_equivalence_run_r10,
)
from rl_curriculum.curriculum261_r10_routing import (
    R10BundleRouting,
    RoutingLedgerR10,
    require_eval_routing_r10,
)
from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    validate_observation_space_v2,
)
from rl_curriculum.curriculum261_r3_calibration import (
    fit_matrix_from_records,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
    numerical_equivalence_report,
)
from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG
from rl_curriculum.curriculum261_r4_preprocessing import (
    fit_manifest_multiset_hash,
)
from rl_curriculum.curriculum261_r6_calibration import (
    fit_preprocessor_v2_from_bank_r6,
)

#: R10 supervised 正式 model seeds(§17:3 个全新 seeds)。
R10_SUPERVISED_MODEL_SEEDS: tuple[int, ...] = (
    20261001, 20261002, 20261003)
R10_SUPERVISED_GATE: dict[str, Any] = {
    "min_seeds_passing": 2,
    "n_model_seeds": 3,
    "heldout_balanced_accuracy_min": 0.60,
    "behavior_gap_min": 0.20,
    "mlp_arch": [128, 128],
    "gated_controls": ["W", "B"],
}
CALIBRATION_PAIRS_PER_RUNG_R10 = 10
C2_INDEPENDENT_PAIRS_PER_RUNG_R10 = 20
SEMANTIC_BLOCKS_PER_CORPUS_R10 = 160
EQUIVALENCE_PAIRS_PER_RUNG_R10 = 3


@dataclass(frozen=True)
class R10ExecutionProfile:
    """execution profile:样本量与 namespace(唯一允许的差异维度)。"""

    name: str
    preplan: bool
    c13_eval_namespace: str
    equivalence_namespace: str
    supervised_namespace: str
    semantic_namespace: str
    c2_matched_namespace: str
    c2_independent_namespace: str
    c13_pairs_per_rung: int
    c2_blocks: int
    semantic_blocks: int
    c2_independent_pairs_per_rung: int
    supervised_pairs_per_rung: int
    supervised_train_pair_limit: int
    supervised_model_seeds: tuple
    equivalence_pairs_per_rung: int
    write_artifacts: bool = True
    artifact_suffix: str = ""

    def artifact(self, base: str) -> str:
        return f"{base}{self.artifact_suffix}"


def formal_main_profile_r10(n_blocks: int) -> R10ExecutionProfile:
    return R10ExecutionProfile(
        name="formal_main", preplan=False,
        c13_eval_namespace="calibration_r10",
        equivalence_namespace="calibration_r10",
        supervised_namespace="supervised_main_r10",
        semantic_namespace="cue_semantic_calibration_r10",
        c2_matched_namespace="calibration_r10",
        c2_independent_namespace="c2_independent_calibration_r10",
        c13_pairs_per_rung=CALIBRATION_PAIRS_PER_RUNG_R10,
        c2_blocks=int(n_blocks),
        semantic_blocks=SEMANTIC_BLOCKS_PER_CORPUS_R10,
        c2_independent_pairs_per_rung=C2_INDEPENDENT_PAIRS_PER_RUNG_R10,
        supervised_pairs_per_rung=CALIBRATION_PAIRS_PER_RUNG_R10,
        supervised_train_pair_limit=6,
        supervised_model_seeds=R10_SUPERVISED_MODEL_SEEDS,
        equivalence_pairs_per_rung=EQUIVALENCE_PAIRS_PER_RUNG_R10,
    )


def formal_holdout_profile_r10(n_blocks: int) -> R10ExecutionProfile:
    return R10ExecutionProfile(
        name="formal_holdout", preplan=False,
        c13_eval_namespace="calibration_holdout_r10",
        equivalence_namespace="calibration_holdout_r10",
        supervised_namespace="supervised_holdout_r10",
        semantic_namespace="cue_semantic_holdout_r10",
        c2_matched_namespace="calibration_holdout_r10",
        c2_independent_namespace="c2_independent_holdout_r10",
        c13_pairs_per_rung=CALIBRATION_PAIRS_PER_RUNG_R10,
        c2_blocks=int(n_blocks),
        semantic_blocks=SEMANTIC_BLOCKS_PER_CORPUS_R10,
        c2_independent_pairs_per_rung=C2_INDEPENDENT_PAIRS_PER_RUNG_R10,
        supervised_pairs_per_rung=CALIBRATION_PAIRS_PER_RUNG_R10,
        supervised_train_pair_limit=6,
        supervised_model_seeds=R10_SUPERVISED_MODEL_SEEDS,
        equivalence_pairs_per_rung=EQUIVALENCE_PAIRS_PER_RUNG_R10,
    )


def rehearsal_main_profile_r10() -> R10ExecutionProfile:
    return R10ExecutionProfile(
        name="rehearsal_main", preplan=True,
        c13_eval_namespace="preplan_calibration_main_r10",
        equivalence_namespace="preplan_calibration_main_r10",
        supervised_namespace="preplan_supervised_main_r10",
        semantic_namespace="preplan_semantic_main_r10",
        c2_matched_namespace="preplan_calibration_main_r10",
        c2_independent_namespace="preplan_calibration_main_r10",
        c13_pairs_per_rung=1,
        c2_blocks=2,
        semantic_blocks=4,
        c2_independent_pairs_per_rung=2,
        supervised_pairs_per_rung=4,
        supervised_train_pair_limit=2,
        supervised_model_seeds=(20261111,),
        equivalence_pairs_per_rung=1,
        write_artifacts=False,
    )


def rehearsal_holdout_profile_r10() -> R10ExecutionProfile:
    return R10ExecutionProfile(
        name="rehearsal_holdout", preplan=True,
        c13_eval_namespace="preplan_calibration_holdout_r10",
        equivalence_namespace="preplan_calibration_holdout_r10",
        supervised_namespace="preplan_supervised_holdout_r10",
        semantic_namespace="preplan_semantic_validation_r10",
        c2_matched_namespace="preplan_calibration_holdout_r10",
        c2_independent_namespace="preplan_calibration_holdout_r10",
        c13_pairs_per_rung=1,
        c2_blocks=2,
        semantic_blocks=4,
        c2_independent_pairs_per_rung=2,
        supervised_pairs_per_rung=4,
        supervised_train_pair_limit=2,
        supervised_model_seeds=(20261111,),
        equivalence_pairs_per_rung=1,
        write_artifacts=False,
    )


# ------------------------------------------------ robustness battery(§18)
def preprocessing_robustness_checks_r10(
        routing_main: R10BundleRouting,
        routing_holdout: R10BundleRouting,
        records_main: list, records_holdout: list,
        eval_records_main: list, eval_records_holdout: list,
        equiv_records_main: list, equiv_records_holdout: list,
        pack: dict[str, Any], *,
        profile: R10ExecutionProfile,
        ledger: RoutingLedgerR10,
        profile_holdout: R10ExecutionProfile | None = None) -> dict[str, Any]:
    """§18 Preprocessing V2 重新资格审查(R10 版;结构承 R6 电池)。

    与 R6 的差异(全部为 R9 缺陷修复):
    - reference equivalence 不再用单一 v2_main:main/holdout 各自的
      equiv records 绑定各自 bundle,经显式 routing 校验;
    - equivalence 走 canonical 合同(§11),逐 mismatch 明细落盘,
      unexplained==0 才 pass;
    - eval/isolation 检查按 role 分开记录。
    """
    from rl_curriculum.curriculum261_r6_param_pack import verify_r4_inheritance

    checks: dict[str, Any] = {}
    v2_main = routing_main.bundle(
        expected_role="main", context="robustness_battery")
    v2_holdout = routing_holdout.bundle(
        expected_role="holdout", context="robustness_battery")

    checks["survival_main"] = bool(
        v2_main.retained_columns == list(PRODUCTION_FEATURE_COLUMNS))
    checks["survival_holdout"] = bool(
        v2_holdout.retained_columns == list(PRODUCTION_FEATURE_COLUMNS))
    checks["fit_bank_integrity"] = bool(
        all(r.integrity_ok for r in records_main)
        and all(r.integrity_ok for r in records_holdout))

    fit_df = fit_matrix_from_records(records_main)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(fit_df.iloc[:half],
                                      fit_df.iloc[half:])
    checks["production_numerical_equivalence"] = bool(eq["pass"])

    with tempfile.TemporaryDirectory() as td:
        epath = Path(td) / "envelope.json"
        v2_main.serialize_envelope(epath)
        reloaded = RouteCPreprocessorV2.load_envelope(epath)
        sample = fit_matrix_from_records(eval_records_main[:4])
        t1 = v2_main.transform(sample)
        t2 = reloaded.transform(sample)
        checks["envelope_reload_bundle_identity_stable"] = bool(
            reloaded.bundle_hash == v2_main.bundle_hash)
        checks["envelope_reload_transform_bitwise_equal"] = bool(
            np.array_equal(t1.to_numpy(), t2.to_numpy()))
        tampered = json.loads(epath.read_text(encoding="utf-8"))
        tampered["fit_manifest"]["entries"][0]["episode_hash"] = \
            "ce-tampered"
        tpath = Path(td) / "tampered_manifest.json"
        tpath.write_text(json.dumps(tampered), encoding="utf-8")
        try:
            RouteCPreprocessorV2.load_envelope(tpath)
            checks["manifest_tamper_rejected"] = False
        except RuntimeError:
            checks["manifest_tamper_rejected"] = True
        tampered2 = json.loads(epath.read_text(encoding="utf-8"))
        tampered2["parameter_state"]["scaler"]["data_min_"][0] += 1e-6
        tpath2 = Path(td) / "tampered_params.json"
        tpath2.write_text(json.dumps(tampered2), encoding="utf-8")
        try:
            RouteCPreprocessorV2.load_envelope(tpath2)
            checks["parameter_state_tamper_rejected"] = False
        except RuntimeError:
            checks["parameter_state_tamper_rejected"] = True

    rng = np.random.default_rng(31415)
    perm = rng.permutation(len(fit_df))
    inner_shuffled = RouteCPreprocessor.build_and_fit(
        fit_df.iloc[perm])
    v2_shuffled = RouteCPreprocessorV2(
        inner_shuffled, v2_main.entries, v2_main.namespace)
    checks["staged_mixed_same_parameter_state_hash"] = bool(
        v2_shuffled.parameter_state_hash == v2_main.parameter_state_hash)
    checks["staged_mixed_same_bundle_hash"] = bool(
        v2_shuffled.bundle_hash == v2_main.bundle_hash)

    shuffled_entries = list(v2_main.entries)
    rng2 = np.random.default_rng(27182)
    order = rng2.permutation(len(shuffled_entries))
    checks["manifest_order_invariant_multiset_hash"] = bool(
        fit_manifest_multiset_hash(
            [shuffled_entries[i] for i in order])
        == v2_main.manifest_multiset_hash)

    dup_records = list(records_main) + [records_main[0]]
    v2_dup = fit_preprocessor_v2_from_bank_r6(
        v2_main.namespace, pack, records=dup_records,
        parameter_pack_identity=pack.get("digest"))[0]
    checks["different_multiset_same_params_same_param_hash"] = bool(
        v2_dup.parameter_state_hash == v2_main.parameter_state_hash)
    checks["different_multiset_different_bundle"] = bool(
        v2_dup.bundle_hash != v2_main.bundle_hash)

    scaled_dfs = [v2_main.transform_episode_df(
        rec.episodes[s].df) for rec in eval_records_main[:8]
        for s in ("A", "B")]
    space_validation = validate_observation_space_v2(
        scaled_dfs, scaled_dfs, EVAL_CFG,
        [int(rec.episodes[s].spec.seed)
         for rec in eval_records_main[:8] for s in ("A", "B")],
        context="preprocessing_robustness_r10")
    checks["observation_space_v2"] = space_validation
    adversarial = adversarial_out_of_range_probe(v2_main, EVAL_CFG)
    checks["adversarial_out_of_range_probe"] = adversarial
    checks["no_nan_inf"] = bool(all(
        np.isfinite(sdf[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy()
                    ).all() for sdf in scaled_dfs))

    state = v2_main.inner.fitted_state()
    checks["position_identity"] = bool(
        len(state["input_columns"]) == 8
        and len(state["retained_columns"]) == 8
        and state["position_slot"]["participates_in_fit"] is False
        and state["position_slot"]["scaled"] is False)

    checks["bundle_verification_main"] = v2_main.verify()
    checks["bundle_verification_holdout"] = v2_holdout.verify()
    n_expected = 2 * len(records_main)
    checks["fit_manifest_provenance_complete"] = bool(
        len(v2_main.entries) == n_expected
        and all(e.episode_hash and e.feature_matrix_hash
                and e.generator_identity for e in v2_main.entries))

    sample_t_main = v2_main.transform(sample).to_numpy()
    sample_t_hold = v2_holdout.transform(sample).to_numpy()
    checks["dual_fit_transform_max_abs_diff"] = float(np.max(np.abs(
        sample_t_main - sample_t_hold)))
    checks["state_hashes_distinct"] = bool(
        v2_main.parameter_state_hash
        != v2_holdout.parameter_state_hash)

    checks["r4_inheritance_verified"] = verify_r4_inheritance(pack)

    # ---- reference equivalence(main/holdout 各自;canonical 合同)----
    profile_hold = profile_holdout or profile
    for role, routing, equiv_records, prof in (
            ("main", routing_main, equiv_records_main, profile),
            ("holdout", routing_holdout, equiv_records_holdout,
             profile_hold)):
        v2 = require_eval_routing_r10(
            routing, prof.equivalence_namespace,
            context=f"reference_equivalence_{role}", ledger=ledger)
        report = reference_equivalence_run_r10(
            equiv_records, v2, pack,
            eval_namespace=prof.equivalence_namespace,
            ledger=ledger)
        checks[f"reference_equivalence_{role}"] = {
            "pass": report["pass"],
            "n_episodes": report["n_episodes"],
            "canonical_scaled_full_equality": report[
                "canonical_scaled_full_equality"],
            "legacy_action_diffs_total": report[
                "legacy_action_diffs_total"],
            "unexplained_mismatches": report["unexplained_mismatches"],
            "float64_math_path_pass": report["float64_math_path"]["pass"],
        }
        if role == "main":
            checks["reference_equivalence_main_detail"] = report
        else:
            checks["reference_equivalence_holdout_detail"] = report
    checks["reference_equivalence_all"] = bool(
        checks["reference_equivalence_main"]["pass"]
        and checks["reference_equivalence_holdout"]["pass"])
    checks["routing_matrix_all_pass"] = ledger.all_pass()

    core_ok = bool(
        checks["survival_main"] and checks["survival_holdout"]
        and checks["fit_bank_integrity"]
        and checks["production_numerical_equivalence"]
        and checks["envelope_reload_bundle_identity_stable"]
        and checks["envelope_reload_transform_bitwise_equal"]
        and checks["manifest_tamper_rejected"]
        and checks["parameter_state_tamper_rejected"]
        and checks["staged_mixed_same_parameter_state_hash"]
        and checks["staged_mixed_same_bundle_hash"]
        and checks["manifest_order_invariant_multiset_hash"]
        and checks["different_multiset_same_params_same_param_hash"]
        and checks["different_multiset_different_bundle"]
        and space_validation["pass"] and adversarial["pass"]
        and checks["no_nan_inf"] and checks["position_identity"]
        and checks["bundle_verification_main"]["pass"]
        and checks["bundle_verification_holdout"]["pass"]
        and checks["fit_manifest_provenance_complete"]
        and checks["reference_equivalence_all"]
        and checks["r4_inheritance_verified"]["pass"]
        and checks["routing_matrix_all_pass"])
    return {
        "format": "cur261-r10-preprocessing-robustness-v1",
        "iteration": "r10",
        "profile": profile.name,
        "checks": checks,
        "production_equivalence": eq,
        "routing_matrix": ledger.matrix(),
        "pass": core_ok,
    }


# ------------------------------------------------------ 共享编排(§12.4)
def _generate_eval_records(
        pack: dict[str, Any], namespace: str,
        pairs_per_rung: int, override_fn: Any) -> list:
    """按 namespace 生成 C1/C3 评估 records(每 family 每 rung)。"""
    from rl_curriculum.curriculum261_pairs import generate_pair as _gp

    records = []
    for family in ("c1_opportunity", "c3_cost"):
        override = override_fn(family, pack)
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(_gp(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
    return records


def _generate_equiv_records(
        pack: dict[str, Any], namespace: str,
        pairs_per_rung: int, override_fn: Any) -> list:
    """equiv records 覆盖全部三个 family(reference equivalence 电池)。"""
    from rl_curriculum.curriculum261_pairs import generate_pair as _gp

    records = []
    for family in CURRICULUM261_FAMILIES:
        override = override_fn(family, pack)
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(_gp(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
    return records


def orchestrate_calibration_stage_r10(
        out_dir: Path, pack: dict[str, Any], *,
        n_blocks: int, recall_floor_value: float,
        routing_main: R10BundleRouting,
        routing_holdout: R10BundleRouting,
        records_main: list, records_holdout: list,
        profile_main: R10ExecutionProfile,
        profile_holdout: R10ExecutionProfile,
        override_fn: Any,
        design_digest: str | None = None,
        write_artifacts: bool = True) -> dict[str, Any]:
    """§12.4 正式 calibrate 与 preplan rehearsal 共享的唯一编排。

    正式:CLI cmd_calibrate 以 formal_main/holdout profiles 调用;
    rehearsal:preplan 以 rehearsal_* profiles 调用(仅样本量与
    namespace 不同;同一函数、同一代码路径)。
    """
    from rl_curriculum.curriculum261_r10_calibration import (
        c2_independent_marginal_guard_r10,
        c2_matched_conditions_r10,
        run_c2_density_diagnostics_r10,
        run_c2_independent_corpus_r10,
        run_c2_matched_corpus_r10,
        run_c2_semantic_corpus_r10,
        run_calibration_corpus_c13_r10,
        supervised_learnability_run_r10,
    )
    from rl_curriculum.curriculum261_r6_pairs import (
        ROBUSTNESS_KAPPA_R6,
        corpus_conditions_r6_pair,
    )

    out_dir = Path(out_dir)
    ledger = RoutingLedgerR10()
    result: dict[str, Any] = {
        "format": "cur261-r10-calibration-orchestration-v1",
        "iteration": "r10",
        "profiles": [profile_main.name, profile_holdout.name],
        "design_plan_digest": design_digest,
        "preplan": profile_main.preplan,
        "roles": {},
    }

    def _write(name: str, payload: Any) -> None:
        if write_artifacts:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=1,
                           default=str), encoding="utf-8")

    # ---- §18/§9:robustness 电池(main/holdout 显式 routing)----
    eval_main = _generate_eval_records(
        pack, profile_main.c13_eval_namespace,
        max(profile_main.c13_pairs_per_rung, 1), override_fn)
    eval_hold = _generate_eval_records(
        pack, profile_holdout.c13_eval_namespace,
        max(profile_holdout.c13_pairs_per_rung, 1), override_fn)
    equiv_main = _generate_equiv_records(
        pack, profile_main.equivalence_namespace,
        profile_main.equivalence_pairs_per_rung, override_fn)
    equiv_hold = _generate_equiv_records(
        pack, profile_holdout.equivalence_namespace,
        profile_holdout.equivalence_pairs_per_rung, override_fn)
    prep_rob = preprocessing_robustness_checks_r10(
        routing_main, routing_holdout, records_main, records_holdout,
        eval_main, eval_hold, equiv_main, equiv_hold, pack,
        profile=profile_main, ledger=ledger,
        profile_holdout=profile_holdout)
    _write("preprocessing_v2_requalification.json", prep_rob)
    _write("production_equivalence.json", prep_rob["production_equivalence"])
    _write("observation_space_validation.json", {
        "calibration_corpora": prep_rob["checks"]["observation_space_v2"],
        "adversarial_out_of_range": prep_rob["checks"][
            "adversarial_out_of_range_probe"],
    })
    _write("bundle_routing_validation.json", {
        "contract": "cur261-r10-bundle-routing-contract-v1",
        "matrix": ledger.matrix(),
        "all_pass": ledger.all_pass(),
    })

    # ---- §17:supervised main/holdout(keyword-only;显式 routing)----
    supervised: dict[str, Any] = {}
    for role, routing, profile in (
            ("main", routing_main, profile_main),
            ("holdout", routing_holdout, profile_holdout)):
        v2_sup = require_eval_routing_r10(
            routing, profile.supervised_namespace,
            context=f"supervised_{role}", ledger=ledger)
        supervised[role] = supervised_learnability_run_r10(
            v2_sup, pack,
            namespace=profile.supervised_namespace,
            pairs_per_rung=profile.supervised_pairs_per_rung,
            train_pair_limit=profile.supervised_train_pair_limit,
            model_seeds=profile.supervised_model_seeds)
        _write(f"supervised_learnability_{role}.json", supervised[role])
        _write(f"supervised_label_alignment_{role}.json",
               supervised[role].get("label_alignment", {}))
        _write(f"supervised_dataset_identity_{role}.json",
               supervised[role].get("dataset_identity", {}))

    # ---- §19:C1/C3 + semantic + C2 matched + C2 independent(双 role)----
    stage_roles: dict[str, Any] = {}
    for role, routing, profile in (
            ("main", routing_main, profile_main),
            ("holdout", routing_holdout, profile_holdout)):
        v2 = require_eval_routing_r10(
            routing, profile.c13_eval_namespace,
            context=f"c13_{role}", ledger=ledger)
        c13 = run_calibration_corpus_c13_r10(
            v2, pack, profile.c13_eval_namespace,
            pairs_per_rung=profile.c13_pairs_per_rung)
        _write(f"pair_evidence_table_{role}.json", {
            f: c13["families"][f]["pair_table"]
            for f in ("c1_opportunity", "c3_cost")})
        v2_m = require_eval_routing_r10(
            routing, profile.c2_matched_namespace,
            context=f"c2_matched_{role}", ledger=ledger)
        c2_matched = run_c2_matched_corpus_r10(
            v2_m, pack, profile.c2_matched_namespace,
            n_blocks=profile.c2_blocks)
        _write(f"c2_block_evidence_table_{role}.json",
               c2_matched["block_table"])
        from rl_curriculum.curriculum261_r10_design import (
            semantic_artifact_filename_r10,
        )

        semantic = run_c2_semantic_corpus_r10(
            pack, profile.semantic_namespace,
            n_blocks=profile.semantic_blocks,
            out_dir=out_dir if write_artifacts else None,
            artifact_name=semantic_artifact_filename_r10(
                profile.semantic_namespace))
        v2_i = require_eval_routing_r10(
            routing, profile.c2_independent_namespace,
            context=f"c2_independent_{role}", ledger=ledger)
        c2_indep = run_c2_independent_corpus_r10(
            v2_i, pack, profile.c2_independent_namespace,
            pairs_per_rung=profile.c2_independent_pairs_per_rung)
        marginal = c2_independent_marginal_guard_r10(
            c2_indep, pack, recall_floor_value)
        matched_conditions = c2_matched_conditions_r10(c2_matched, pack)
        _write(f"c2_independent_marginal_{role}.json", marginal)
        # per-role strict curriculum gate(独立;禁 pooled)
        c13_conditions = {
            f: corpus_conditions_r6_pair(
                c13["families"][f], kappa=ROBUSTNESS_KAPPA_R6)
            for f in ("c1_opportunity", "c3_cost")}
        curriculum_gate = {
            "c1": c13_conditions["c1_opportunity"],
            "c3": c13_conditions["c3_cost"],
            "c2_matched": matched_conditions,
            "semantic": semantic,
            "marginal": marginal,
        }
        stage_roles[role] = {
            "c13": c13, "c2_matched": c2_matched,
            "semantic": semantic, "c2_independent": c2_indep,
            "marginal": marginal, "curriculum_gate": curriculum_gate,
        }
        result["roles"][role] = {
            "curriculum_gate_pass": bool(
                curriculum_gate["c1"]["pass"]
                and curriculum_gate["c3"]["pass"]
                and matched_conditions["pass"]
                and semantic["pass"] and marginal["pass"]),
        }
    # 密度诊断(跨双语料;诊断性质)
    density = run_c2_density_diagnostics_r10(
        stage_roles["main"]["c2_matched"],
        stage_roles["holdout"]["c2_matched"], pack)
    _write("c2_density_diagnostics.json", density)

    result["preprocessing_robustness_pass"] = prep_rob["pass"]
    result["routing_matrix_all_pass"] = ledger.all_pass()
    result["routing_matrix"] = ledger.matrix()
    result["supervised_main_pass"] = supervised["main"]["pass"]
    result["supervised_holdout_pass"] = supervised["holdout"]["pass"]
    result["main_independent_pass"] = result["roles"]["main"][
        "curriculum_gate_pass"]
    result["holdout_independent_pass"] = result["roles"]["holdout"][
        "curriculum_gate_pass"]
    result["density_pass"] = density["pass"]
    result["pass"] = bool(
        prep_rob["pass"] and ledger.all_pass()
        and result["supervised_main_pass"]
        and result["supervised_holdout_pass"]
        and result["main_independent_pass"]
        and result["holdout_independent_pass"])
    return result
