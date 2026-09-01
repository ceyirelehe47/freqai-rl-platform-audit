# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:一次性 final qualification(§27-§30)。

§27 硬合同顺序:
1. 检查 exposure(marker OR ledger;已暴露即拒绝);
2. 加载锁定 plan(digest 复算)+ robustness gate + pack 绑定;
3. 验证 sealed final preflight attestation(digest 复算 + plan 绑定
   + 零 final seed 访问声明);
4. 完成全部不需要 final seed 的静态身份检查(冻结合同/vendor 路径与
   SHA/V2 digest/code identity);
5. 获取 final 文件锁(并发 final 只有一个成功);
6. 原子写 exposure marker(running;ledger 先行);
7. 第一次派生 final seed(final fit bank);
8. 执行 final:120 pairs + 全套验证 + strict final conditions;
9. marker -> completed;任何异常 -> marker -> crashed + crash evidence
   落盘 + re-raise(保留 marker,禁止修复后复用 qualification_r5)。
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_r3_calibration import (
    fit_matrix_from_records,
)
from rl_curriculum.curriculum261_r3_obs import reference_equivalence_check
from rl_curriculum.curriculum261_r3_preprocessing import (
    numerical_equivalence_report,
)
from rl_curriculum.curriculum261_r5_calibration import (
    generate_fit_bank_r5,
    fit_preprocessor_v2_from_bank_r5,
    run_calibration_corpus_r5,
    supervised_learnability_run_r5,
)
from rl_curriculum.curriculum261_r5_namespaces import (
    QualificationR5FileLock,
    qualification_r5_exposed,
    write_qualification_r5_exposure,
)
from rl_curriculum.curriculum261_r5_param_pack import (
    load_selected_pack,
    r5_family_rung_params,
    r5_override_for,
)
from rl_curriculum.curriculum261_r5_pairs import (
    EVAL_CFG,
    RAW_SCHEMA,
    ROBUSTNESS_KAPPA_R5,
    c2_density_summary,
    corpus_conditions_r5,
    density_gate_r5,
    difficulty_metric_validation,
    rung_report_r4,
)
from rl_curriculum.curriculum261_r5_plan import (
    _code_identity_r5,
    load_locked_plan_r5,
)
from rl_curriculum.curriculum261_r5_preflight import (
    vendor_dir_default,
    verify_sealed_attestation,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    preprocessing_v2_contract_digest,
    validate_observation_space_v2,
)
from rl_curriculum.curriculum261_qualification import (
    check_latent_isolation,
    check_observation_causality,
    check_production_feature_equivalence,
    check_reference_causality,
    check_reproducibility,
)


def qualification_r5_lock_dir_default() -> Path:
    from rl_curriculum.curriculum261_r5_namespaces import (
        qualification_r5_lock_dir,
    )

    return qualification_r5_lock_dir()


def _fresh_seed_validity_r5(n_checks: int = 10) -> dict[str, Any]:
    """fresh_holdout_r5 namespace 的合法生成检查。"""
    rng = np.random.default_rng(20260911)
    results = []
    for _ in range(n_checks):
        family = CURRICULUM261_FAMILIES[int(rng.integers(0, 3))]
        rung = CURRICULUM261_RUNGS[int(rng.integers(0, 4))]
        idx = int(rng.integers(0, 20))
        try:
            rec = generate_pair(
                family, rung, idx, namespace="fresh_holdout_r5")
            results.append({
                "family": family, "rung": rung, "pair": idx,
                "integrity_ok": bool(rec.integrity_ok), "ok": True})
        except Exception as exc:  # noqa: BLE001 - 记录失败本身
            results.append({
                "family": family, "rung": rung, "pair": idx,
                "error": str(exc)[:200], "ok": False})
    return {
        "format": "cur261-r5-fresh-seed-v1",
        "namespace": "fresh_holdout_r5",
        "n_checks": n_checks,
        "results": results,
        "pass": bool(all(r["ok"] for r in results)),
    }


def _c2_final_density(family_report: dict[str, Any],
                      records: list[Any],
                      rung_params: dict[str, dict[str, Any]],
                      thresholds: dict[str, Any]) -> dict[str, Any]:
    """final 语料 C2 密度 gate(§11 字段 + 门槛)。"""
    from rl_curriculum.curriculum261_r5_design import (
        _reference_long_label_rate,
    )

    episodes = family_report["by_rung"]["D3"]["episodes"]
    dens = c2_density_summary(episodes, "D3")
    d3_records = [r for r in records if r.rung == "D3"]
    dens["reference_long_label_rate"] = _reference_long_label_rate(
        d3_records, rung_params["D3"], thresholds)
    gate = density_gate_r5(dens)
    d2_dens = c2_density_summary(
        family_report["by_rung"]["D2"]["episodes"], "D2")
    d2_records = [r for r in records if r.rung == "D2"]
    d2_dens["reference_long_label_rate"] = _reference_long_label_rate(
        d2_records, rung_params["D2"], thresholds)
    return {
        "D3": {**dens, "density_gate": gate},
        "D2": {**d2_dens, "density_gate": density_gate_r5(d2_dens)},
        "pass": bool(gate["pass"]
                     and density_gate_r5(d2_dens)["pass"]),
    }


def run_final_qualification_r5(out_dir: Path,
                               vendor_dir: Path | None = None,
                               ) -> dict[str, Any]:
    """执行一次性 R5 final qualification(§27-§30)。"""
    if qualification_r5_exposed():
        raise RuntimeError(
            "R5 final qualification 已执行过(exposure marker/ledger "
            "存在)——同一 qualification_r5 corpus 不得再次执行;继续必须"
            "使用新迭代身份(R5.1/R6)与全新 seed space")
    plan, digest = load_locked_plan_r5()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R5 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    pack = load_selected_pack(qualification_r5_lock_dir_default())
    if pack["digest"] != plan["parameter_pack"]["digest"]:
        raise RuntimeError(
            "plan 绑定的 parameter pack digest 与 artifact 不一致"
            "(fail closed)")
    attestation = verify_sealed_attestation(Path(out_dir))
    if not attestation["pass"]:
        raise RuntimeError(
            f"sealed final preflight attestation 验证失败:"
            f"{attestation}(final 前置条件;fail closed)")
    if attestation["attestation"]["plan_digest"] != digest:
        raise RuntimeError("attestation 绑定的 plan digest 与当前 plan 不符")

    # ---- 不需要 final seed 的静态身份检查(marker 之前完成)----
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
        _upstream_integrity,
    )

    frozen = _frozen_contract_integrity()
    vendor_dir = vendor_dir or vendor_dir_default()
    upstream = _upstream_integrity(vendor_dir)
    upstream_ok = (upstream["sha"] == plan["vendor_pin"]
                   and upstream["clean"])
    v2_digest = preprocessing_v2_contract_digest()
    contract_ok = (v2_digest
                   == plan["preprocessing_v2"]["contract_digest"])
    code_ok = (plan["code_identity"] == _code_identity_r5())
    static_ok = bool(frozen["pass"] and upstream_ok and contract_ok
                     and code_ok)
    if not static_ok:
        raise RuntimeError(
            "final 静态身份检查失败(frozen contracts/vendor/V2 digest/"
            "code identity);在 exposure marker 之前 fail closed——"
            "本轮 qualification_r5 未消耗")

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with QualificationR5FileLock(blocking=False):
            # ---- 原子 exposure marker(ledger 先行)----
            write_qualification_r5_exposure(digest, status="running")
            result = _execute_final_r5(
                out_dir, plan, digest, pack, started)
        write_qualification_r5_exposure(
            digest, status="completed"
            if result["verdict"] == "PASS" else "failed")
        return result
    except Exception:
        exc = traceback.format_exc()
        try:
            (out_dir / "qualification_crash_traceback.log").write_text(
                exc, encoding="utf-8")
            write_qualification_r5_exposure(digest, status="crashed")
        except Exception:  # noqa: BLE001 - 崩溃路径不得掩盖原始异常
            pass
        raise


def _execute_final_r5(out_dir: Path, plan: dict[str, Any], digest: str,
                      pack: dict[str, Any], started: str,
                      ) -> dict[str, Any]:
    """marker=running 之后的 final 主流程(任何异常 -> crashed)。"""
    # 1) final fit bank(plan+sealed preflight 后首次访问)
    final_records = generate_fit_bank_r5(
        "preprocess_fit_qualification_r5", pack)
    final_v2, final_manifest = fit_preprocessor_v2_from_bank_r5(
        "preprocess_fit_qualification_r5", pack,
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
         for s in ("A", "B")], context="final_fit_space_v2_r5")
    adversarial = adversarial_out_of_range_probe(final_v2, EVAL_CFG)

    # 2) qualification_r5 120 pairs(pack override 生效)
    thresholds = plan["reference_thresholds_by_family"]
    n_pairs = plan["qualification_bank_schedule"]["pairs_per_rung"]
    family_reports: dict[str, Any] = {}
    all_records: dict[str, list] = {}
    for family in CURRICULUM261_FAMILIES:
        override = r5_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(n_pairs):
                records.append(generate_pair(
                    family, rung, idx, namespace="qualification_r5",
                    rung_params_override=override))
        all_records[family] = records
        family_reports[family] = rung_report_r4(
            records, family, r5_family_rung_params(family, pack),
            thresholds[family], final_v2, corpus="qualification_r5")

    # 3) reference 等价:全部 120 pairs x A/B(禁止抽样)
    reference_eq = []
    for family in CURRICULUM261_FAMILIES:
        for rec in all_records[family]:
            rung_params = r5_family_rung_params(family, pack)[rec.rung]
            rung_params["cur261_rung"] = rec.rung
            for side in ("A", "B"):
                reference_eq.append(reference_equivalence_check(
                    rec.episodes[side], family, rung_params,
                    thresholds[family], final_v2.inner, EVAL_CFG,
                    RAW_SCHEMA))

    causality = {
        "observation_causality": [
            check_observation_causality(f, "D2", 0,
                                        namespace="qualification_r5")
            for f in CURRICULUM261_FAMILIES],
        "production_feature_equivalence": [
            check_production_feature_equivalence(
                f, "D2", 0, namespace="qualification_r5")
            for f in CURRICULUM261_FAMILIES],
        "reference_causality": [
            check_reference_causality(
                f, r5_family_rung_params(f, pack)["D2"], thresholds[f])
            for f in CURRICULUM261_FAMILIES],
    }
    repro = [check_reproducibility(f, r, 0, "qualification_r5")
             for f in CURRICULUM261_FAMILIES for r in ("D1", "D2")]
    # pack 覆盖 rung 的复现(override 下同 seed 确定性;内联逐位比对)
    repro_pack_override = []
    for family in CURRICULUM261_FAMILIES:
        ov = r5_override_for(family, pack) or {}
        for rung in sorted(ov):
            r1 = generate_pair(family, rung, 0,
                               namespace="qualification_r5",
                               rung_params_override={rung: dict(ov[rung])})
            r2 = generate_pair(family, rung, 0,
                               namespace="qualification_r5",
                               rung_params_override={rung: dict(ov[rung])})
            repro_pack_override.append({
                "family": family, "rung": rung,
                "identical": bool(all(
                    r1.episodes[s].df.equals(r2.episodes[s].df)
                    and r1.episodes[s].hidden.equals(
                        r2.episodes[s].hidden)
                    for s in ("A", "B"))),
            })
    repro.append({
        "check": "pack_override_reproducibility",
        "pass": bool(all(x["identical"] for x in repro_pack_override)),
        "detail": repro_pack_override,
    })
    latent = check_latent_isolation([
        r for recs in all_records.values() for r in recs])
    fresh = _fresh_seed_validity_r5(10)

    # 4) representation(final fit state 下重跑)
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile as _cond,
    )

    cond_records = generate_fit_bank_r5(
        "preprocess_fit_calibration_r5", pack)
    cond_eval_records = [
        rec for recs in all_records.values() for rec in recs[:8]]
    conditioning = _cond(final_v2.inner, cond_records, cond_eval_records)
    supervised = supervised_learnability_run_r5(final_v2, pack)

    # 5) strict final conditions(单 corpus;与 gate 同一函数源)
    conditions = {f: corpus_conditions_r5(family_reports[f],
                                          ROBUSTNESS_KAPPA_R5)
                  for f in CURRICULUM261_FAMILIES}
    diff_validation = {f: difficulty_metric_validation(
        family_reports[f]["pair_table"], f)
        for f in CURRICULUM261_FAMILIES}
    c2_density = _c2_final_density(
        family_reports[FAMILY_C2], all_records[FAMILY_C2],
        r5_family_rung_params(FAMILY_C2, pack),
        thresholds[FAMILY_C2])

    # 6) staged/mixed invariance(final 语料)
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor,
    )

    fit_df = fit_matrix_from_records(final_records)
    rng = np.random.default_rng(61803)
    perm = rng.permutation(len(fit_df))
    inner_shuffled = RouteCPreprocessor.build_and_fit(fit_df.iloc[perm])
    v2_shuffled = RouteCPreprocessorV2(
        inner_shuffled, final_v2.entries, final_v2.namespace)
    staged_mixed_ok = bool(
        v2_shuffled.bundle_hash == final_v2.bundle_hash)

    from rl_curriculum.curriculum261_r5_param_pack import (
        frozen_parameter_identity_r5,
        verify_r4_inheritance,
    )

    # 7) 判定(全部核心项;禁止 conditional pass)
    checks = {
        "sealed_preflight_attestation_verified": True,
        "frozen_contracts_unchanged": True,
        "vendor_pin_unchanged_and_clean": True,
        "preprocessing_v2_contract_digest": True,
        "plan_code_identity_matches_tree": True,
        "parameter_pack_binding": True,
        "r4_inheritance_verified": bool(
            verify_r4_inheritance(pack)["pass"]),
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
        "staged_mixed_invariance_final": staged_mixed_ok,
        "qualification_before_final_seeds_unavailable": bool(
            final_manifest["namespace"]
            == "preprocess_fit_qualification_r5"),
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
            conditions[f]["ordering_ok"]
            for f in CURRICULUM261_FAMILIES)),
        "gaps_ge_kappa_se_all": bool(all(
            conditions[f]["gaps_ge_kappa_se"]
            for f in CURRICULUM261_FAMILIES)),
        "d3_positive_all": bool(all(
            conditions[f]["d3_positive"]
            for f in CURRICULUM261_FAMILIES)),
        "d3_pair_margin_ge_kappa_se_all": bool(all(
            conditions[f]["d3_mean_ge_kappa_se"]
            for f in CURRICULUM261_FAMILIES)),
        "fixed_baseline_margins_all": bool(all(
            conditions[f]["margins_ok"]
            for f in CURRICULUM261_FAMILIES)),
        "c2_density_gate": bool(c2_density["pass"]),
        "oracle_positive_all": bool(all(
            conditions[f]["oracle_positive"]
            for f in CURRICULUM261_FAMILIES)),
        "difficulty_metric_unified": bool(all(
            diff_validation[f]["pass"] for f in CURRICULUM261_FAMILIES)),
        "conditioning_gate": bool(conditioning["pass"]),
        "supervised_learnability_gate": bool(supervised["pass"]),
        "no_nan_inf": bool(conditioning["checks"]["all_finite"]),
        "frozen_parameters_unchanged": bool(
            frozen_parameter_identity_r5(pack["tier"])[
                "identity"]
            == plan["frozen_parameter_identity"]["identity"]),
    }
    passed = bool(all(checks.values()))

    result = {
        "format": "cur261-r5-final-qualification-v1",
        "iteration": "r5",
        "started_utc": started,
        "plan_digest": digest,
        "parameter_pack_digest": pack["digest"],
        "parameter_pack_tier": pack["tier"],
        "selected_c2_candidate": pack["selected_c2_candidate"],
        "preprocessing_parameter_state_hash":
            final_v2.parameter_state_hash,
        "fit_manifest_multiset_hash": final_v2.manifest_multiset_hash,
        "preprocessor_bundle_hash": final_v2.bundle_hash,
        "qualification_namespace": "qualification_r5",
        "n_pairs_total": sum(len(v) for v in all_records.values()),
        "checks": checks,
        "n_checks": len(checks),
        "n_checks_passed": int(sum(1 for v in checks.values() if v)),
        "conditions_by_family": conditions,
        "c2_density": c2_density,
        "difficulty_ladders": {
            f: {r: family_reports[f]["difficulty_ladder"][r]["mean"]
                for r in CURRICULUM261_RUNGS}
            for f in CURRICULUM261_FAMILIES},
        "verdict": "PASS" if passed else "FAIL",
        "c3_ppo_branch_d_remains_open": True,
        "stage_2_6_2_official_status": "FAIL(未变;R5 不重跑 2.6.2)",
    }

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
        "plan_digest": digest, "iteration": "r5",
        "status": "completed" if passed else "failed"})
    _dump("qualification_fit_manifest.json", final_manifest)
    _dump("qualification_preprocessor_bundle.json",
          final_v2.identity())
    _dump("production_equivalence.json", equivalence)
    _dump("observation_space_validation.json", {
        "space_validation": space_validation,
        "adversarial_out_of_range": adversarial,
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
    _dump("qualification_pair_evidence_table.json", {
        "schema_identity": family_reports[
            CURRICULUM261_FAMILIES[0]]["pair_table"]["schema_identity"],
        "tables": {f: family_reports[f]["pair_table"]
                   for f in CURRICULUM261_FAMILIES}})
    _dump("c2_density_diagnostics.json", c2_density)
    return result
