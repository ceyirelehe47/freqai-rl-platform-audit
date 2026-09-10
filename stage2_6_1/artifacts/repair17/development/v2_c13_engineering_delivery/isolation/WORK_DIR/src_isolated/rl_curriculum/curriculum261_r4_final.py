"""阶段 2.6.1 Repair R4:一次性 final qualification(§27-§29)。

§27 流程(一旦开始即写 exposure marker,无论 PASS/FAIL/crash 本轮
R4 final corpus 均视为已暴露):

1. 身重复核(冻结合同/vendor/plan code identity/runtime config/
   preprocessing V2 contract digest/parameter pack 绑定);
2. 生成全新 final fit bank(preprocess_fit_qualification_r4,plan
   lock 后首次访问)→ manifest → fit → V2 envelope → 三层哈希 →
   V2 observation space 验证 → 对抗探针;
3. qualification_r4 全新 120 pairs(3 family x 4 rung x 10 x A/B,
   D3 override 经 parameter pack);
4. §28 全套验证:preprocessing(数值等价/无界空间/存活/序列化/
   reload/manifest/bundle/staged-mixed/position/no NaN)、reference
   (全部 240 episode 逐 bar 等价/固定基线身份/latent/因果)、
   curriculum(pair integrity/复现/fresh seed/难度排序/D3 margin/
   逐基线 margin/oracle/C2/C3/pair-cluster/bootstrap)、contract
   (parameter pack/历史参数保持/plan-code-runtime-vendor identity);
5. 判定输出 PASS/FAIL(核心项任一失败即 FAIL,禁止 conditional
   pass)。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_pairs import generate_pair
from rl_curriculum.curriculum261_r3_calibration import (
    CONDITIONING_GATE,
    SUPERVISED_GATE,
    fit_matrix_from_records,
)
from rl_curriculum.curriculum261_r3_obs import reference_equivalence_check
from rl_curriculum.curriculum261_r3_preprocessing import (
    numerical_equivalence_report,
)
from rl_curriculum.curriculum261_r4_calibration import (
    CALIBRATION_PAIRS_PER_RUNG_R4,
    generate_fit_bank_r4,
    fit_preprocessor_v2_from_bank,
    run_calibration_corpus_r4,
    supervised_learnability_run_r4,
)
from rl_curriculum.curriculum261_r4_namespaces import (
    qualification_r4_exposed,
    write_qualification_r4_exposure,
)
from rl_curriculum.curriculum261_r4_obs import r4_observation_identity
from rl_curriculum.curriculum261_r4_param_pack import (
    load_selected_pack,
    r4_family_rung_params,
    r4_override_for,
)
from rl_curriculum.curriculum261_r4_pairs import (
    EVAL_CFG,
    RAW_SCHEMA,
    corpus_conditions_r4,
    difficulty_metric_validation,
    rung_report_r4,
)
from rl_curriculum.curriculum261_r4_plan import (
    _code_identity_r4,
    load_locked_plan_r4,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    preprocessing_v2_contract_digest,
    production_pipeline_identity_light,
    validate_observation_space_v2,
)
from rl_curriculum.curriculum261_qualification import (
    check_latent_isolation,
    check_observation_causality,
    check_production_feature_equivalence,
    check_reference_causality,
    check_reproducibility,
)


def _fresh_seed_validity_r4(n_checks: int = 10) -> dict[str, Any]:
    """fresh_holdout_r4 namespace 的合法生成检查。"""
    rng = np.random.default_rng(20260901)
    results = []
    for _ in range(n_checks):
        family = CURRICULUM261_FAMILIES[int(rng.integers(0, 3))]
        rung = CURRICULUM261_RUNGS[int(rng.integers(0, 4))]
        idx = int(rng.integers(0, 20))
        try:
            rec = generate_pair(
                family, rung, idx, namespace="fresh_holdout_r4")
            results.append({
                "family": family, "rung": rung, "pair": idx,
                "integrity_ok": bool(rec.integrity_ok), "ok": True})
        except Exception as exc:  # noqa: BLE001 - 记录失败本身
            results.append({
                "family": family, "rung": rung, "pair": idx,
                "error": str(exc)[:200], "ok": False})
    return {
        "format": "cur261-r4-fresh-seed-v1",
        "namespace": "fresh_holdout_r4",
        "n_checks": n_checks,
        "results": results,
        "pass": bool(all(r["ok"] for r in results)),
    }


def run_final_qualification_r4(out_dir: Path,
                               vendor_dir: Path | None = None,
                               ) -> dict[str, Any]:
    """执行一次性 R4 final qualification(§27/§28)。"""
    if qualification_r4_exposed():
        raise RuntimeError(
            "R4 final qualification 已执行过(exposure marker 存在)——"
            "同一 qualification_r4 corpus 不得再次执行;继续必须使用"
            "新迭代身份(R4.1/R5)与全新 seed space")
    plan, digest = load_locked_plan_r4()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R4 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    pack = load_selected_pack(qualification_r4_lock_dir_default())
    if pack["digest"] != plan["parameter_pack"]["digest"]:
        raise RuntimeError(
            "plan 绑定的 parameter pack digest 与 artifact 不一致"
            "(fail closed)")
    write_qualification_r4_exposure(digest, status="running")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 身重复核
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
        _upstream_integrity,
    )

    frozen = _frozen_contract_integrity()
    vendor_dir = vendor_dir or (Path(__file__).resolve().parents[2]
                                / "vendor" / "freqtrade")
    upstream = _upstream_integrity(vendor_dir)
    upstream_ok = (upstream["sha"] == plan["vendor_pin"]
                   and upstream["clean"])
    v2_digest = preprocessing_v2_contract_digest()
    contract_ok = (v2_digest == plan["preprocessing_v2"]["contract_digest"])
    code_ok = (plan["code_identity"] == _code_identity_r4())

    identities = {
        "frozen_contracts_unchanged": bool(frozen["pass"]),
        "vendor_pin_unchanged_and_clean": bool(upstream_ok),
        "preprocessing_v2_contract_digest": bool(contract_ok),
        "plan_code_identity_matches_tree": bool(code_ok),
        "robustness_gate_passed_before_lock": bool(
            (plan.get("robustness_gate") or {}).get("pass") is True),
        "parameter_pack_binding": bool(
            pack["digest"] == plan["parameter_pack"]["digest"]),
    }

    # 2) final fit bank(lock 后首次)+ manifest + V2 + 验证
    final_records = generate_fit_bank_r4(
        "preprocess_fit_qualification_r4", pack)
    final_v2, final_manifest = fit_preprocessor_v2_from_bank(
        "preprocess_fit_qualification_r4", pack,
        records=final_records,
        parameter_pack_identity=pack["digest"])
    survival = list(final_v2.retained_columns)
    survival_ok = (
        survival == list(
            plan["preprocessing_v2"]["ordered_feature_columns"]
            or survival) and len(survival) == 8)
    envelope_path = out_dir / "qualification_preprocessor_state.json"
    final_v2.serialize_envelope(envelope_path)
    reloaded = RouteCPreprocessorV2.load_envelope(envelope_path)
    probe_df = fit_matrix_from_records(final_records[:6])
    reload_ok = bool(
        reloaded.bundle_hash == final_v2.bundle_hash
        and np.array_equal(
            final_v2.transform(probe_df).to_numpy(),
            reloaded.transform(probe_df).to_numpy()))

    eq_fit = fit_matrix_from_records(final_records)
    half = len(eq_fit) // 2
    equivalence = numerical_equivalence_report(
        eq_fit.iloc[:half], eq_fit.iloc[half:])

    contain_records = final_records[:6]
    contain_dfs = [r.episodes[s].df for r in contain_records
                   for s in ("A", "B")]
    scaled_contain = [final_v2.transform_episode_df(d)
                      for d in contain_dfs]
    space_validation = validate_observation_space_v2(
        scaled_contain, scaled_contain, EVAL_CFG,
        [int(r.episodes[s].spec.seed) for r in contain_records
         for s in ("A", "B")], context="final_fit_space_v2")
    adversarial = adversarial_out_of_range_probe(final_v2, EVAL_CFG)

    # 3) qualification_r4 120 pairs(D3 override 生效)
    thresholds = plan["reference_thresholds_by_family"]
    n_pairs = plan["qualification_bank_schedule"]["pairs_per_rung"]
    family_reports: dict[str, Any] = {}
    all_records: dict[str, list] = {}
    for family in CURRICULUM261_FAMILIES:
        override = r4_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(n_pairs):
                records.append(generate_pair(
                    family, rung, idx, namespace="qualification_r4",
                    rung_params_override=override))
        all_records[family] = records
        family_reports[family] = rung_report_r4(
            records, family, r4_family_rung_params(family, pack),
            thresholds[family], final_v2, corpus="qualification_r4")

    # 4) reference 等价:全部 120 pairs x A/B(§21,禁止抽样)
    reference_eq = []
    for family in CURRICULUM261_FAMILIES:
        for rec in all_records[family]:
            rung_params = r4_family_rung_params(family, pack)[rec.rung]
            rung_params["cur261_rung"] = rec.rung
            for side in ("A", "B"):
                reference_eq.append(reference_equivalence_check(
                    rec.episodes[side], family, rung_params,
                    thresholds[family], final_v2.inner, EVAL_CFG,
                    RAW_SCHEMA))

    causality = {
        "observation_causality": [
            check_observation_causality(f, "D2", 0,
                                        namespace="qualification_r4")
            for f in CURRICULUM261_FAMILIES],
        "production_feature_equivalence": [
            check_production_feature_equivalence(
                f, "D2", 0, namespace="qualification_r4")
            for f in CURRICULUM261_FAMILIES],
        "reference_causality": [
            check_reference_causality(
                f, r4_family_rung_params(f, pack)["D2"], thresholds[f])
            for f in CURRICULUM261_FAMILIES],
    }
    repro = [check_reproducibility(f, r, 0, "qualification_r4")
             for f in CURRICULUM261_FAMILIES for r in ("D1", "D2")]
    # pack-D3 复现(override 下同 seed 确定性):check_reproducibility
    # 不接受 override,此处内联等价检查(生成两次逐位比对)。
    repro_pack_d3 = []
    for family in CURRICULUM261_FAMILIES:
        ov = r4_override_for(family, pack)
        r1 = generate_pair(family, "D3", 0,
                           namespace="qualification_r4",
                           rung_params_override=ov)
        r2 = generate_pair(family, "D3", 0,
                           namespace="qualification_r4",
                           rung_params_override=ov)
        repro_pack_d3.append({
            "family": family,
            "identical": bool(all(
                r1.episodes[s].df.equals(r2.episodes[s].df)
                and r1.episodes[s].hidden.equals(r2.episodes[s].hidden)
                for s in ("A", "B"))),
        })
    repro.append({
        "check": "pack_d3_override_reproducibility",
        "pass": bool(all(x["identical"] for x in repro_pack_d3)),
        "detail": repro_pack_d3,
    })
    latent = check_latent_isolation([
        r for recs in all_records.values() for r in recs])
    fresh = _fresh_seed_validity_r4(10)

    # representation(final fit state 下重跑)
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile as _cond,
    )

    cond_records = generate_fit_bank_r4(
        "preprocess_fit_calibration_r4", pack)
    cond_eval_records = [
        rec for recs in all_records.values() for rec in recs[:8]]
    conditioning = _cond(final_v2.inner, cond_records, cond_eval_records)
    supervised = supervised_learnability_run_r4(final_v2, pack)

    # 课程条件(qualification corpus 单语料,与 gate 同一函数源)
    conditions = {f: corpus_conditions_r4(family_reports[f])
                  for f in CURRICULUM261_FAMILIES}
    diff_validation = {f: difficulty_metric_validation(
        family_reports[f]["pair_table"], f)
        for f in CURRICULUM261_FAMILIES}

    # 5) 判定
    checks = dict(identities)
    checks.update({
        "preprocessing_numerical_equivalence": bool(equivalence["pass"]),
        "observation_space_unbounded_contract": bool(
            space_validation["pass"]),
        "adversarial_out_of_range_probe": bool(adversarial["pass"]),
        "no_clipping": bool(
            space_validation["pass"]
            and space_validation["wrapper_pass_through_bitwise"]
            and adversarial["pass"]),
        "feature_survival_8_of_8": bool(survival_ok),
        "position_not_scaled": bool(
            final_v2.identity()["position_slot"][
                "participates_in_fit"] is False),
        "state_serialization_reload": bool(reload_ok),
        "preprocessor_bundle_identity": bool(
            final_v2.bundle_hash == reloaded.bundle_hash
            and final_v2.verify()["pass"]),
        "staged_mixed_invariance_final": bool(
            # final 语料上重验:行序打乱同 bundle(manifest 不变)
            _final_staged_mixed_check(final_v2, final_records, pack)),
        "qualification_before_final_seeds_unavailable": bool(
            final_manifest["namespace"]
            == "preprocess_fit_qualification_r4"),
        "reference_transformed_action_equal_raw": bool(
            all(e["pass"] for e in reference_eq)),
        "reference_equivalence_coverage_complete": bool(
            len(reference_eq) == 240),
        "latent_isolation": bool(latent["pass"]),
        "future_mutation_causality": bool(all(
            c["pass"] for c in causality["observation_causality"])),
        "reference_causality": bool(all(
            c["pass"] for c in causality["reference_causality"])),
        "production_feature_equivalence": bool(all(
            c["pass"]
            for c in causality["production_feature_equivalence"])),
        "pair_integrity_all": bool(all(
            family_reports[f]["pair_integrity_pass_rate"] == 1.0
            for f in CURRICULUM261_FAMILIES)),
        "reproducibility": bool(all(r["pass"] for r in repro)),
        "fresh_seed_validity": bool(fresh["pass"]),
        "difficulty_ordering_all": bool(all(
            family_reports[f]["difficulty_ordering_ok"]
            for f in CURRICULUM261_FAMILIES)),
        "d3_positive_all": bool(all(
            conditions[f]["d3_positive"] for f in CURRICULUM261_FAMILIES)),
        "d3_pair_margin_ge_kappa_se_all": bool(all(
            conditions[f]["d3_mean_ge_kappa_se_strict_corpus"]
            for f in CURRICULUM261_FAMILIES)),
        "gaps_ge_kappa_se_all": bool(all(
            conditions[f]["gaps_ge_kappa_se_strict_corpus"]
            for f in CURRICULUM261_FAMILIES)),
        "fixed_baseline_margins_all": bool(all(
            conditions[f]["margins_ok"]
            for f in CURRICULUM261_FAMILIES)),
        "oracle_positive_all": bool(all(
            conditions[f]["oracle_positive"]
            for f in CURRICULUM261_FAMILIES)),
        "difficulty_metric_unified": bool(all(
            diff_validation[f]["pass"] for f in CURRICULUM261_FAMILIES)),
        "conditioning_gate": bool(conditioning["pass"]),
        "supervised_learnability_gate": bool(supervised["pass"]),
        "no_nan_inf": bool(conditioning["checks"]["all_finite"]),
        "frozen_parameters_unchanged": bool(
            _frozen_parameter_check(plan)),
    })
    passed = bool(all(checks.values()))

    result = {
        "format": "cur261-r4-final-qualification-v1",
        "iteration": "r4",
        "started_utc": started,
        "plan_digest": digest,
        "parameter_pack_digest": pack["digest"],
        "preprocessing_parameter_state_hash":
            final_v2.parameter_state_hash,
        "fit_manifest_multiset_hash": final_v2.manifest_multiset_hash,
        "preprocessor_bundle_hash": final_v2.bundle_hash,
        "qualification_namespace": "qualification_r4",
        "n_pairs_total": sum(len(v) for v in all_records.values()),
        "checks": checks,
        "n_checks": len(checks),
        "n_checks_passed": int(sum(1 for v in checks.values() if v)),
        "conditions_by_family": conditions,
        "difficulty_ladders": {
            f: {r: family_reports[f]["difficulty_ladder"][r]["mean"]
                for r in CURRICULUM261_RUNGS}
            for f in CURRICULUM261_FAMILIES},
        "verdict": "PASS" if passed else "FAIL",
        "c3_ppo_branch_d_remains_open": True,
        "stage_2_6_2_official_status": "FAIL(未变;R4 不重跑 2.6.2)",
    }
    write_qualification_r4_exposure(digest, status="completed")

    def _dump(name: str, payload: Any) -> None:
        (out_dir / name).write_text(json.dumps(
            payload, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")

    _dump("qualification_result.json", result)
    _dump("qualification_raw.json", {
        f: [{
            "family": r.family, "rung": r.rung,
            "pair_index": r.pair_index,
            "attempt_log": r.attempt_log.canonical(),
            "integrity_ok": bool(r.integrity_ok),
        } for r in recs] for f, recs in all_records.items()})
    _dump("qualification_exposure.json", {
        "plan_digest": digest, "iteration": "r4",
        "status": "completed"})
    _dump("qualification_fit_manifest.json", final_manifest)
    _dump("qualification_preprocessor_bundle.json",
          final_v2.identity())
    _dump("production_equivalence.json", equivalence)
    _dump("observation_space_validation.json", {
        "space_validation": space_validation,
        "adversarial_out_of_range": adversarial,
        "observation_identity": r4_observation_identity(final_v2),
    })
    _dump("reference_action_equivalence.json", {
        "n_episodes": len(reference_eq),
        "coverage": "全部 120 pairs x A/B,全部 observation-aware 策略",
        "all_pass": bool(all(e["pass"] for e in reference_eq)),
        "reports": reference_eq,
    })
    _dump("causality.json", causality)
    _dump("latent_isolation.json", latent)
    _dump("fresh_seed.json", fresh)
    _dump("conditioning_profile.json", conditioning)
    _dump("supervised_learnability.json", supervised)
    _dump("calibration_summary.json", {
        "note": "qualification corpus 的 family 报告(与 pair 表同源)",
        "families": family_reports})
    _dump("difficulty_metric_validation.json", diff_validation)
    return result


def qualification_r4_lock_dir_default() -> Path:
    from rl_curriculum.curriculum261_r4_namespaces import (
        qualification_r4_lock_dir,
    )

    return qualification_r4_lock_dir()


def _final_staged_mixed_check(
        final_v2: RouteCPreprocessorV2,
        final_records: list[Any], pack: dict[str, Any]) -> bool:
    """final 语料上的 staged/mixed 不变性:行序打乱 -> 同 bundle。"""
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor,
    )

    fit_df = fit_matrix_from_records(final_records)
    rng = np.random.default_rng(61803)
    perm = rng.permutation(len(fit_df))
    inner_shuffled = RouteCPreprocessor.build_and_fit(fit_df.iloc[perm])
    v2_shuffled = RouteCPreprocessorV2(
        inner_shuffled, final_v2.entries, final_v2.namespace)
    return bool(v2_shuffled.bundle_hash == final_v2.bundle_hash)


def _frozen_parameter_check(plan: dict[str, Any]) -> bool:
    """C2 全部 + C1/C3 D0-D2 与 plan 锁定 identity 一致(未漂移)。"""
    from rl_curriculum.curriculum261_r4_param_pack import (
        frozen_parameter_identity,
    )

    return bool(
        frozen_parameter_identity()["identity"]
        == plan["frozen_parameter_identity"]["identity"])
