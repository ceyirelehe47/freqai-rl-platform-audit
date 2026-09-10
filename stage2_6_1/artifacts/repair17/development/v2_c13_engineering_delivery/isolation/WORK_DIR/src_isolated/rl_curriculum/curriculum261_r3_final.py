"""阶段 2.6.1 Repair R3:一次性 final qualification(WP-J)。

§27 流程(一旦开始即写 exposure marker,无论 PASS/FAIL/crash 本轮
R3 final corpus 均视为已暴露):

1. 六重身份复核(冻结合同/vendor/production observation/plan code
   identity/runtime config/preprocessing contract digest);
2. 生成全新 final fit bank(preprocess_fit_qualification_r3,plan
   lock 后首次访问)→ fit → 冻结保存 → 8 特征存活验证 → state hash
   → observation containment 验证;
3. qualification_r3 全新 120 pairs(3 family x 4 rung x 10 pair
   x A/B);
4. §28 全套验证:preprocessing(数值等价/隔离/存活/列序/序列化/
   reload/确定性/顺序不变/containment/position 恒等/无 NaN)、
   reference semantics(transformed 逐 bar 等价/收益等价/latent
   隔离/未来变异因果)、curriculum(pair integrity/复现/fresh seed/
   难度排序/D3 正/reference>基线/oracle 正/C2 双诊断/C3 成本选择
   性/pair-cluster uncertainty)、representation(conditioning/
   supervised learnability/C2 类失衡控制);
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
from rl_curriculum.curriculum261_pairs import (
    attempt_statistics,
    generate_pair,
)
from rl_curriculum.curriculum261_r3_calibration import (
    CALIBRATION_PAIRS_PER_RUNG,
    CONDITIONING_GATE,
    EVAL_CFG,
    FIT_BANK_PAIRS_PER_RUNG,
    RAW_SCHEMA,
    SUPERVISED_GATE,
    conditioning_profile,
    evaluate_pair_corpus_r3,
    fit_matrix_from_records,
    fit_preprocessor_from_bank,
    generate_fit_bank,
    rung_report_r3,
    supervised_learnability_run,
)
from rl_curriculum.curriculum261_r3_namespaces import (
    qualification_r3_exposed,
    write_qualification_r3_exposure,
)
from rl_curriculum.curriculum261_r3_obs import (
    r3_observation_identity,
    reference_equivalence_check,
    validate_observation_containment,
)
from rl_curriculum.curriculum261_r3_plan import (
    _code_identity_r3,
    load_locked_plan_r3,
    plan_digest_r3,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
    numerical_equivalence_report,
    preprocessing_contract_digest,
    production_preprocessing_audit,
)
from rl_curriculum.curriculum261_qualification import (
    check_latent_isolation,
    check_observation_causality,
    check_production_feature_equivalence,
    check_reference_causality,
    check_reproducibility,
)


def _fresh_seed_validity_r3(n_checks: int = 10) -> dict[str, Any]:
    """fresh_holdout_r3 namespace 的合法生成检查(R3 版)。"""
    rng = np.random.default_rng(20260901)
    results = []
    for _ in range(n_checks):
        family = CURRICULUM261_FAMILIES[int(rng.integers(0, 3))]
        rung = CURRICULUM261_RUNGS[int(rng.integers(0, 4))]
        idx = int(rng.integers(0, 20))
        try:
            rec = generate_pair(
                family, rung, idx, namespace="fresh_holdout_r3")
            results.append({
                "family": family, "rung": rung, "pair": idx,
                "integrity_ok": bool(rec.integrity_ok), "ok": True})
        except Exception as exc:  # noqa: BLE001 - 记录失败本身
            results.append({
                "family": family, "rung": rung, "pair": idx,
                "error": str(exc)[:200], "ok": False})
    return {
        "format": "cur261-r3-fresh-seed-v1",
        "namespace": "fresh_holdout_r3",
        "n_checks": n_checks,
        "results": results,
        "pass": bool(all(r["ok"] for r in results)),
    }


def run_final_qualification_r3(out_dir: Path,
                               vendor_dir: Path | None = None,
                               ) -> dict[str, Any]:
    """执行一次性 R3 final qualification(§27/§28)。"""
    if qualification_r3_exposed():
        raise RuntimeError(
            "R3 final qualification 已执行过(exposure marker 存在)——"
            "同一 qualification_r3 corpus 不得再次执行;继续必须使用"
            "新迭代身份(R3.1/R4)与全新 seed space")
    plan, digest = load_locked_plan_r3()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R3 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed(Layer C;生成任何 qualification "
            "pair 之前终止)")
    write_qualification_r3_exposure(digest, status="running")
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 六重身份复核
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
        _upstream_integrity,
    )

    frozen = _frozen_contract_integrity()
    vendor_dir = vendor_dir or (Path(__file__).resolve().parents[3]
                                / "vendor" / "freqtrade")
    upstream = _upstream_integrity(vendor_dir)
    upstream_ok = (upstream["sha"] == plan["vendor_pin"]
                   and upstream["clean"])
    contract_digest = preprocessing_contract_digest()
    contract_ok = (contract_digest == plan["preprocessing"][
        "contract_digest"])
    current_ids = _code_identity_r3()
    code_ok = (
        plan["code_identity"] == current_ids)
    audit = production_preprocessing_audit()
    runtime_ok = (audit["config_sha256"] == plan["preprocessing"][
        "runtime_config_identity"]["config_sha256"])

    identities = {
        "frozen_contracts_unchanged": bool(frozen["pass"]),
        "vendor_pin_unchanged_and_clean": bool(upstream_ok),
        "preprocessing_contract_digest": bool(contract_ok),
        "plan_code_identity_matches_tree": bool(code_ok),
        "runtime_config_identity": bool(runtime_ok),
        "robustness_gate_passed_before_lock": bool(
            (plan.get("robustness_gate") or {}).get("pass") is True),
    }

    # 2) final fit bank(lock 后首次)+ fit + 冻结 + 验证
    final_preproc, final_fit_manifest = fit_preprocessor_from_bank(
        "preprocess_fit_qualification_r3", FIT_BANK_PAIRS_PER_RUNG)
    survival = list(final_preproc.retained_columns)
    survival_ok = (survival == list(
        plan["preprocessing"]["ordered_feature_columns"])
        and len(survival) == 8)
    state_path = out_dir / "qualification_preprocessor_state.json"
    final_preproc.serialize(state_path)
    reloaded = RouteCPreprocessor.load(state_path)
    fit_bank_records = generate_fit_bank(
        "preprocess_fit_qualification_r3", FIT_BANK_PAIRS_PER_RUNG)
    probe_df = fit_matrix_from_records(fit_bank_records[:6])
    reload_ok = bool(
        reloaded.state_hash() == final_preproc.state_hash()
        and np.array_equal(
            final_preproc.transform(probe_df).to_numpy(),
            reloaded.transform(probe_df).to_numpy()))
    determinism_ok = bool(np.array_equal(
        final_preproc.transform(probe_df).to_numpy(),
        final_preproc.transform(probe_df).to_numpy()))

    # 数值等价(final fit bank 独立对拍 vendor pipeline)
    eq_fit = fit_matrix_from_records(fit_bank_records)
    half = len(eq_fit) // 2
    equivalence = numerical_equivalence_report(
        eq_fit.iloc[:half], eq_fit.iloc[half:])
    equivalence["state_hash"] = final_preproc.state_hash()

    # containment(final fit state + qualification 预检 episodes)
    from rl_curriculum.generator_api import PRICE_COLUMNS

    contain_records = fit_bank_records[:6]
    contain_dfs = [r.episodes[s].df for r in contain_records
                   for s in ("A", "B")]
    contain = validate_observation_containment(
        [final_preproc.transform_episode_df(d) for d in contain_dfs],
        [d[list(PRICE_COLUMNS)] for d in contain_dfs],
        EVAL_CFG,
        [int(r.episodes[s].spec.seed) for r in contain_records
         for s in ("A", "B")],
        context="final_fit_containment",
    )

    preprocessing_checks = {
        "production_numerical_equivalence": bool(equivalence["pass"]),
        "fit_eval_isolation": bool(
            final_fit_manifest["namespace"]
            == "preprocess_fit_qualification_r3"
            and final_fit_manifest["integrity_all_ok"]),
        "feature_survival_8_of_8": bool(survival_ok),
        "column_order": survival,
        "state_serialization_reload_bitwise": bool(reload_ok),
        "transform_determinism": bool(determinism_ok),
        "observation_containment": bool(contain["pass"]),
        "state_hash": final_preproc.state_hash(),
    }

    # 3) qualification_r3 120 pairs
    thresholds = plan["reference_thresholds_by_family"]
    rung_params = plan["rung_params_by_family"]
    n_pairs = plan["qualification_bank_schedule"]["pairs_per_rung"]
    family_reports: dict[str, Any] = {}
    all_records: dict[str, list] = {}
    for family in CURRICULUM261_FAMILIES:
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(n_pairs):
                records.append(generate_pair(
                    family, rung, idx, namespace="qualification_r3"))
        all_records[family] = records
        family_reports[family] = rung_report_r3(
            records, family, rung_params[family], thresholds,
            final_preproc)
        family_reports[family]["attempt_stats"] = attempt_statistics(
            records)
        family_reports[family]["pair_integrity_pass_ratio"] = float(
            sum(1 for r in records if r.integrity_ok) / len(records))

    # 4) reference semantics / 因果 / latent / 复现 / fresh
    equivalence_records = [
        all_records[f][0] for f in CURRICULUM261_FAMILIES]
    reference_eq = []
    for rec in equivalence_records:
        rp = dict(rung_params[rec.family][rec.rung])
        rp["cur261_rung"] = rec.rung
        reference_eq.append(reference_equivalence_check(
            rec.episodes["A"], rec.family, rp,
            thresholds[rec.family], final_preproc, EVAL_CFG, RAW_SCHEMA))
    causality = {
        "observation_causality": [
            check_observation_causality(f, "D2", 0,
                                        namespace="qualification_r3")
            for f in CURRICULUM261_FAMILIES],
        "production_feature_equivalence": [
            check_production_feature_equivalence(
                f, "D2", 0, namespace="qualification_r3")
            for f in CURRICULUM261_FAMILIES],
        "reference_causality": [
            check_reference_causality(
                f, rung_params[f]["D2"], thresholds[f])
            for f in CURRICULUM261_FAMILIES],
    }
    repro = [check_reproducibility(f, r, 0, "qualification_r3")
             for f in CURRICULUM261_FAMILIES for r in ("D1", "D3")]
    latent = check_latent_isolation([
        r for recs in all_records.values() for r in recs])
    fresh = _fresh_seed_validity_r3(10)

    # representation(final fit state 下重跑 conditioning + supervised)
    cond_records = generate_fit_bank(
        "preprocess_fit_calibration_r3", FIT_BANK_PAIRS_PER_RUNG)
    cond_eval_records = [
        rec for recs in all_records.values() for rec in recs[:8]]
    conditioning = conditioning_profile(
        final_preproc, cond_records, cond_eval_records)
    supervised = supervised_learnability_run(final_preproc)

    # 5) 判定
    checks = dict(identities)
    checks.update({
        "preprocessing_numerical_equivalence":
            preprocessing_checks["production_numerical_equivalence"],
        "feature_survival_8_of_8": preprocessing_checks[
            "feature_survival_8_of_8"],
        "observation_dim_9_constant": bool(
            survival_ok and len(survival) == 8),
        "position_not_scaled": bool(cond_ok_position(final_preproc)),
        "state_serialization_reload": bool(reload_ok),
        "qualification_before_final_seeds_unavailable": bool(
            final_fit_manifest["namespace"]
            == "preprocess_fit_qualification_r3"),
        "reference_transformed_action_equal_raw": bool(
            all(e["pass"] for e in reference_eq)),
        "raw_transformed_net_return_equal": bool(
            all(e["pass"] for e in reference_eq)),
        "latent_isolation": bool(latent["pass"]),
        "future_mutation_causality": bool(all(
            c["pass"] for c in causality["observation_causality"])),
        "reference_causality": bool(all(
            c["pass"] for c in causality["reference_causality"])),
        "production_feature_equivalence": bool(all(
            c["pass"]
            for c in causality["production_feature_equivalence"])),
        "pair_integrity_all": bool(all(
            family_reports[f]["pair_integrity_pass_ratio"] == 1.0
            for f in CURRICULUM261_FAMILIES)),
        "reproducibility": bool(all(r["pass"] for r in repro)),
        "fresh_seed_validity": bool(fresh["pass"]),
        "difficulty_ordering_all": bool(all(
            family_reports[f]["ordering_ok"]
            for f in CURRICULUM261_FAMILIES)),
        "d3_positive_all": bool(all(
            family_reports[f]["d3_metric_positive"]
            for f in CURRICULUM261_FAMILIES)),
        "reference_beats_required_all": bool(all(
            family_reports[f]["reference_beats_required_all_rungs"]
            for f in CURRICULUM261_FAMILIES)),
        "oracle_positive_all": bool(all(
            family_reports[f]["oracle_positive_all_rungs"]
            for f in CURRICULUM261_FAMILIES)),
        "conditioning_gate": bool(conditioning["pass"]),
        "supervised_learnability_gate": bool(supervised["pass"]),
        "observation_containment": bool(contain["pass"]),
        "no_nan_inf": bool(conditioning["checks"]["all_finite"]),
    })
    passed = bool(all(checks.values()))

    result = {
        "format": "cur261-r3-final-qualification-v1",
        "iteration": "r3",
        "started_utc": started,
        "plan_digest": digest,
        "preprocessing_state_hash": final_preproc.state_hash(),
        "qualification_namespace": "qualification_r3",
        "n_pairs_total": sum(
            len(v) for v in all_records.values()),
        "checks": checks,
        "n_checks": len(checks),
        "n_checks_passed": int(sum(1 for v in checks.values() if v)),
        "difficulty_ladders": {
            f: family_reports[f]["difficulty_metric_ladder"]
            for f in CURRICULUM261_FAMILIES},
        "verdict": "PASS" if passed else "FAIL",
        "c3_ppo_branch_d_remains_open": True,
        "stage_2_6_2_official_status": "FAIL(未变;R3 不重跑 2.6.2)",
    }
    write_qualification_r3_exposure(digest, status="completed")

    # artifacts
    (out_dir / "qualification_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "qualification_raw.json").write_text(
        json.dumps({f: [r.canonical() for r in recs]
                    for f, recs in all_records.items()},
                   indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "qualification_exposure.json").write_text(
        json.dumps({"plan_digest": digest, "iteration": "r3"},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "preprocessing_checks.json").write_text(
        json.dumps(preprocessing_checks, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "production_equivalence.json").write_text(
        json.dumps(equivalence, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "observation_space_validation.json").write_text(
        json.dumps(contain, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "reference_action_equivalence.json").write_text(
        json.dumps(reference_eq, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "causality.json").write_text(
        json.dumps(causality, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "latent_isolation.json").write_text(
        json.dumps(latent, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "fresh_seed.json").write_text(
        json.dumps(fresh, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "conditioning_profile.json").write_text(
        json.dumps(conditioning, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "supervised_learnability.json").write_text(
        json.dumps(supervised, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "difficulty_ordering.json").write_text(
        json.dumps({f: {
            "ladder": family_reports[f]["difficulty_metric_ladder"],
            "pair_se": family_reports[f]["difficulty_metric_pair_se"],
            "ordering_ok": family_reports[f]["ordering_ok"],
            "d3_positive": family_reports[f]["d3_metric_positive"],
        } for f in CURRICULUM261_FAMILIES}, indent=2,
            ensure_ascii=False, default=float), encoding="utf-8")
    (out_dir / "pair_integrity.json").write_text(
        json.dumps({f: {
            "pass_ratio": family_reports[f][
                "pair_integrity_pass_ratio"],
            "attempt_stats": family_reports[f]["attempt_stats"],
        } for f in CURRICULUM261_FAMILIES}, indent=2,
            ensure_ascii=False, default=float), encoding="utf-8")
    (out_dir / "calibration_summary.json").write_text(
        json.dumps(family_reports, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "final_fit_manifest.json").write_text(
        json.dumps(final_fit_manifest, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "preprocessing_contract_identity.json").write_text(
        json.dumps(final_preproc.identity(), indent=2,
                   ensure_ascii=False, default=str),
        encoding="utf-8")
    return result


def cond_ok_position(preproc: RouteCPreprocessor) -> bool:
    """position slot 恒等验证:fit 输入 8 列无 position;transform 输出
    8 列;第 9 维由 env 追加且不缩放。"""
    state = preproc.fitted_state()
    return bool(
        len(state["input_columns"]) == 8
        and len(state["retained_columns"]) == 8
        and state["position_slot"]["participates_in_fit"] is False
        and state["position_slot"]["scaled"] is False)
