# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6 CLI:audit → design-plan-lock → design →
calibrate → preflight-static → lock-plan → preflight-sealed → qualify →
smoke → namespace-integrity。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from rl_curriculum.curriculum261_r6_namespaces import (
    qualification_r6_lock_dir,
    verify_r6_namespace_isolation,
)

BASELINE_COMMIT_R6 = "40a0d9ae4ac8fcfa6f643f584a8fb63ec5579afc"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
PRIOR_R5_PARENT_COMMIT = "95bb927f3ba46fa18b98602ea05c37ed67df198b"
PRIOR_R2_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99")
PRIOR_DIAG262R2_PLAN_DIGEST = (
    "dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60")
PRIOR_R4_PARAMETER_PACK_DIGEST = (
    "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99")
PRIOR_R5_DESIGN_PLAN_DIGEST = (
    "r5dp-0c1eb69f95336f7d649192bc4293eaf768b37508f47c8c21c919009eb3afe52d")


def _default_art() -> Path:
    return qualification_r6_lock_dir()


def _write_json(out_dir: Path, name: str, payload: object) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")


def _dump_txt(out_dir: Path, name: str, text: str) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(text, encoding="utf-8")


def _pack(out_dir: Path) -> dict:
    from rl_curriculum.curriculum261_r6_param_pack import load_selected_pack

    return load_selected_pack(out_dir)


def _git_head(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def cmd_audit(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
        generate_fit_bank,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        numerical_equivalence_report,
        production_preprocessing_audit,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r6_preflight import (
        _route_c_identity,
        _vendor_state,
        vendor_dir_default,
    )

    out = Path(args.out_dir)
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    head = _git_head(release_repo) if release_repo else ""
    parent = ""
    if release_repo:
        try:
            parent = subprocess.run(
                ["git", "rev-parse", "HEAD~1"], cwd=str(release_repo),
                capture_output=True, text=True,
                timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            parent = ""
    historical_binding = {
        "r2_plan_digest_expected": PRIOR_R2_PLAN_DIGEST,
        "diag262r2_plan_digest_expected": PRIOR_DIAG262R2_PLAN_DIGEST,
        "r4_parameter_pack_digest_expected":
            PRIOR_R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest_expected": PRIOR_R5_DESIGN_PLAN_DIGEST,
        "r5_parent_of_baseline": PRIOR_R5_PARENT_COMMIT,
    }
    if release_repo and release_repo.is_dir():
        p2 = (release_repo / "stage2_6_1/artifacts/repair2/"
              "qualification_plan_digest.txt")
        if p2.is_file():
            historical_binding["r2_plan_digest_actual"] = p2.read_text(
                encoding="utf-8").strip()
        p262 = (release_repo / "stage2_6_2/artifacts/repair2/"
                "diagnostic_plan_digest.txt")
        if p262.is_file():
            historical_binding["diag262r2_plan_digest_actual"] = (
                p262.read_text(encoding="utf-8").strip())
        p4 = (release_repo / "stage2_6_1/artifacts/repair4/"
              "r4_parameter_pack_digest.txt")
        if p4.is_file():
            historical_binding["r4_parameter_pack_digest_actual"] = (
                p4.read_text(encoding="utf-8").strip())
        p5 = (release_repo / "stage2_6_1/artifacts/repair5/"
              "r5_design_plan_digest.txt")
        if p5.is_file():
            historical_binding["r5_design_plan_digest_actual"] = (
                p5.read_text(encoding="utf-8").strip())
    historical_binding["digests_match"] = bool(
        historical_binding.get("r2_plan_digest_actual")
        == PRIOR_R2_PLAN_DIGEST
        and historical_binding.get("diag262r2_plan_digest_actual")
        == PRIOR_DIAG262R2_PLAN_DIGEST
        and historical_binding.get("r4_parameter_pack_digest_actual")
        == PRIOR_R4_PARAMETER_PACK_DIGEST
        and historical_binding.get("r5_design_plan_digest_actual")
        == PRIOR_R5_DESIGN_PLAN_DIGEST)
    _write_json(out, "baseline_integrity.json", {
        "expected_baseline": BASELINE_COMMIT_R6,
        "release_repo_head": head,
        "release_repo_parent": parent,
        "baseline_matches": bool(head == BASELINE_COMMIT_R6),
        "parent_is_r5_checkpoint": bool(parent == PRIOR_R5_PARENT_COMMIT),
        "note": "发布仓库 HEAD 应等于 R5 诚实 FAIL checkpoint "
                "(或其明确后继;组装 R6 产物前)",
    })
    _write_json(out, "historical_binding.json", historical_binding)

    vendor = _vendor_state(vendor_dir_default())
    _write_json(out, "route_c_integrity.json", {
        **_route_c_identity(),
        "vendor": vendor,
        "vendor_pin_matches": bool(vendor.get("sha") == VENDOR_PIN
                                   and vendor.get("clean")),
    })

    audit = production_preprocessing_audit()
    _write_json(out, "production_preprocessing_audit.json", audit)
    _write_json(out, "preprocessing_v2_contract.json", {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "digest": preprocessing_v2_contract_digest(),
        "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
        "position_slot": POSITION_SLOT_SEMANTICS_V2,
        "numerics": "与 R4/V1 逐位一致(vendor pipeline 直接复用);"
                    "R6 在全新语料重新资格验证",
    })
    _dump_txt(out, "preprocessing_v2_contract_digest.txt",
              preprocessing_v2_contract_digest())
    records = generate_fit_bank("ppo_smoke_r6", args.fit_pairs)
    fit_df = fit_matrix_from_records(records)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", eq)
    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity_pre_design.json", ns)
    print(f"[audit] equivalence pass={eq['pass']} "
          f"ns pass={ns.get('pass')} "
          f"digests_match={historical_binding['digests_match']}")
    ok = bool(eq["pass"] and ns.get("pass")
              and historical_binding["digests_match"]
              and vendor.get("sha") == VENDOR_PIN and vendor.get("clean"))
    return 0 if ok else 1


def cmd_design_plan_lock(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r6_design import (
        design_plan_payload,
        lock_design_plan,
    )

    out = Path(args.out_dir)
    plan = design_plan_payload(
        baseline_commit=BASELINE_COMMIT_R6,
        vendor_pin=VENDOR_PIN,
        v2_contract_digest=preprocessing_v2_contract_digest(),
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
    )
    path, digest = lock_design_plan(out, plan)
    print(f"[design-plan-lock] locked {path} digest={digest}")
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r6_design import (
        load_locked_design_plan,
        run_design_stage,
    )

    out = Path(args.out_dir)
    plan, digest = load_locked_design_plan(out)
    results = run_design_stage(out, plan, digest,
                               baseline_commit=BASELINE_COMMIT_R6)
    print(f"[design] pass={results['pass']} "
          f"selected={results.get('selected_candidate')} "
          f"n_blocks={results.get('selected_block_count')}")
    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity_post_design.json", ns)
    return 0 if results["pass"] else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r3_calibration import (
        CONDITIONING_GATE,
        SUPERVISED_GATE,
        conditioning_profile,
    )
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
    from rl_curriculum.curriculum261_r6_calibration import (
        c2_independent_marginal_guard_r6,
        fit_preprocessor_v2_from_bank_r6,
        generate_fit_bank_r6,
        preprocessing_robustness_checks_r6,
        run_c2_density_diagnostics_r6,
        run_c2_diagnostics_r6,
        run_c2_independent_corpus_r6,
        run_c2_matched_corpus_r6,
        run_calibration_corpus_c13_r6,
        run_generator_stress_r6,
        supervised_learnability_run_r6,
    )
    from rl_curriculum.curriculum261_r6_param_pack import (
        frozen_parameter_identity_r6,
        r6_family_rung_params,
        r6_override_for,
    )
    from rl_curriculum.curriculum261_r6_pairs import (
        C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
        C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6,
        ROBUSTNESS_KAPPA_R6,
        curriculum_robustness_gate_r6,
    )

    out = Path(args.out_dir)
    pack = _pack(out)
    n_blocks = int(pack["selected_block_count"])

    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity.json", ns)

    print("[calibrate] fitting main preprocessor "
          "(preprocess_fit_calibration_r6)...")
    records_main = generate_fit_bank_r6(
        "preprocess_fit_calibration_r6", pack)
    v2_main, manifest_main = fit_preprocessor_v2_from_bank_r6(
        "preprocess_fit_calibration_r6", pack, records=records_main,
        parameter_pack_identity=pack["digest"])
    print("[calibrate] fitting holdout preprocessor "
          "(preprocess_fit_holdout_r6)...")
    records_hold = generate_fit_bank_r6(
        "preprocess_fit_holdout_r6", pack)
    v2_hold, manifest_hold = fit_preprocessor_v2_from_bank_r6(
        "preprocess_fit_holdout_r6", pack, records=records_hold,
        parameter_pack_identity=pack["digest"])
    _write_json(out, "fit_manifest_calibration.json", manifest_main)
    _write_json(out, "fit_manifest_holdout.json", manifest_hold)
    _write_json(out, "preprocessor_bundle_calibration.json",
                v2_main.identity())
    _write_json(out, "preprocessor_bundle_holdout.json",
                v2_hold.identity())
    _write_json(out, "fit_eval_isolation.json", {
        "main": {k: manifest_main[k] for k in (
            "namespace", "pairs_per_rung", "n_pairs", "n_episodes",
            "n_rows", "integrity_all_ok", "multiset_hash")},
        "holdout": {k: manifest_hold[k] for k in (
            "namespace", "pairs_per_rung", "n_pairs", "n_episodes",
            "n_rows", "integrity_all_ok", "multiset_hash")},
        "eval_namespaces": ["calibration_r6", "calibration_holdout_r6"],
        "c2_matched_namespaces": ["calibration_r6",
                                  "calibration_holdout_r6"],
        "c2_independent_namespaces": [
            "c2_independent_calibration_r6",
            "c2_independent_holdout_r6"],
        "fit_bank_used_for_metrics": False,
        "protocol": "offline training-corpus fit -> frozen transform;"
                    "fit bank 只用于拟合 preprocessor",
    })

    print("[calibrate] preprocessing robustness 全电池...")
    eval_records = [
        generate_pair(f, r, 0, namespace="calibration_r6",
                      rung_params_override=r6_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    equiv_records = [
        generate_pair(f, r, i, namespace="calibration_r6",
                      rung_params_override=r6_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS
        for i in range(3)]
    prep_rob = preprocessing_robustness_checks_r6(
        v2_main, v2_hold, records_main, records_hold,
        eval_records, equiv_records, pack)
    _write_json(out, "preprocessing_v2_requalification.json", prep_rob)
    _write_json(out, "production_equivalence.json",
                prep_rob["equivalence_report"])
    _write_json(out, "observation_space_validation.json", {
        "calibration_corpora": prep_rob["checks"]["observation_space_v2"],
        "adversarial_out_of_range": prep_rob["checks"][
            "adversarial_out_of_range_probe"],
    })

    cond = conditioning_profile(v2_main.inner, records_main, eval_records)
    _write_json(out, "conditioning_profile.json", cond)

    print("[calibrate] supervised learnability (3 families x 3 seeds)...")
    supervised = supervised_learnability_run_r6(v2_main, pack)
    _write_json(out, "supervised_learnability.json", supervised)

    print("[calibrate] C1/C3 calibration_r6 + calibration_holdout_r6...")
    calib_main_c13 = run_calibration_corpus_c13_r6(
        v2_main, pack, "calibration_r6")
    calib_hold_c13 = run_calibration_corpus_c13_r6(
        v2_main, pack, "calibration_holdout_r6")
    _write_json(out, "pair_evidence_table_calibration.json", {
        f: calib_main_c13["families"][f]["pair_table"]
        for f in ("c1_opportunity", "c3_cost")})
    _write_json(out, "pair_evidence_table_holdout.json", {
        f: calib_hold_c13["families"][f]["pair_table"]
        for f in ("c1_opportunity", "c3_cost")})

    print(f"[calibrate] C2 matched blocks x2 corpora "
          f"(n={n_blocks})...")
    c2_matched_main = run_c2_matched_corpus_r6(
        v2_main, pack, "calibration_r6", n_blocks)
    c2_matched_hold = run_c2_matched_corpus_r6(
        v2_main, pack, "calibration_holdout_r6", n_blocks)
    _write_json(out, "c2_block_evidence_table_calibration.json",
                c2_matched_main["block_table"])
    _write_json(out, "c2_block_evidence_table_holdout.json",
                c2_matched_hold["block_table"])
    _write_json(out, "matched_ladder_integrity.json", {
        "main": c2_matched_main["block_corpus_summary"],
        "holdout": c2_matched_hold["block_corpus_summary"],
    })

    print("[calibrate] C2 independent marginal guard x2 corpora...")
    c2_indep_main = run_c2_independent_corpus_r6(
        v2_main, pack, "c2_independent_calibration_r6")
    c2_indep_hold = run_c2_independent_corpus_r6(
        v2_main, pack, "c2_independent_holdout_r6")
    marginal_main = c2_independent_marginal_guard_r6(c2_indep_main, pack)
    marginal_hold = c2_independent_marginal_guard_r6(c2_indep_hold, pack)
    _write_json(out, "c2_independent_marginal_calibration.json",
                marginal_main)
    _write_json(out, "c2_independent_marginal_holdout.json",
                marginal_hold)

    print("[calibrate] C2 三语义 + 密度 + stress...")
    c2_sem_records = [
        rec for blk in c2_matched_main["blocks"]
        for rec in blk.pair_records.values()]
    c2_diag = run_c2_diagnostics_r6(c2_sem_records)
    _write_json(out, "c2_local_cue_independence.json",
                c2_diag["local_cue_independence"])
    _write_json(out, "c2_context_observability.json",
                c2_diag["context_observability"])
    _write_json(out, "c2_cue_payoff_separation.json",
                c2_diag["cue_payoff_separation"])
    c2_density = run_c2_density_diagnostics_r6(
        c2_matched_main, c2_matched_hold, pack)
    _write_json(out, "c2_density_diagnostics.json", c2_density)
    stress = run_generator_stress_r6(pack)
    _write_json(out, "generator_stress_summary.json", stress)
    from rl_curriculum.curriculum261_r6_pairs import (
        scrambled_gap_control,
    )

    _write_json(out, "matched_vs_scrambled_variance.json", {
        "main": scrambled_gap_control(c2_matched_main["block_table"]),
        "holdout": scrambled_gap_control(c2_matched_hold["block_table"]),
        "note": "仅诊断(matched 方差缩减说明);不参与 PASS 判定(§15)",
    })

    preprocessing_gate = {
        "format": "cur261-r6-preprocessing-robustness-gate-v1",
        "equivalence_pass": bool(
            prep_rob["equivalence_report"]["pass"]),
        "robustness_checks_pass": bool(prep_rob["pass"]),
        "conditioning_pass": bool(cond["pass"]),
        "observation_space_v2_pass": bool(
            prep_rob["checks"]["observation_space_v2"]["pass"]
            and prep_rob["checks"][
                "adversarial_out_of_range_probe"]["pass"]),
        "parameter_state_hash_main": v2_main.parameter_state_hash,
        "parameter_state_hash_holdout": v2_hold.parameter_state_hash,
        "bundle_hash_main": v2_main.bundle_hash,
        "bundle_hash_holdout": v2_hold.bundle_hash,
        "pass": bool(prep_rob["pass"] and cond["pass"]),
    }
    curriculum_gate = curriculum_robustness_gate_r6(
        {"families": {
            **calib_main_c13["families"],
            "c2_context": {"attempt_stats": c2_matched_main[
                "block_attempt_stats"]}},
         "seed_namespace": "calibration_r6"},
        {"families": {
            **calib_hold_c13["families"],
            "c2_context": {"attempt_stats": c2_matched_hold[
                "block_attempt_stats"]}},
         "seed_namespace": "calibration_holdout_r6"},
        c2_block_main=c2_matched_main["block_table"],
        c2_block_holdout=c2_matched_hold["block_table"],
        c2_marginal_main=marginal_main["guard"],
        c2_marginal_holdout=marginal_hold["guard"],
        kappa=ROBUSTNESS_KAPPA_R6,
        stress=stress,
        c2_diagnostics=c2_diag,
        c2_density={
            "main": {"pass": c2_density["main"]["pass"]},
            "holdout": {"pass": c2_density["holdout"]["pass"]}},
    )
    _write_json(out, "strict_gate_definition.json",
                curriculum_gate["rule_identity"])
    _write_json(out, "preprocessing_robustness_gate.json",
                preprocessing_gate)
    _write_json(out, "curriculum_robustness_gate.json", curriculum_gate)
    _write_json(out, "pair_cluster_uncertainty.json", {
        f: {r: calib_main_c13["families"][f]["difficulty_ladder"][r]
            for r in CURRICULUM261_RUNGS}
        for f in ("c1_opportunity", "c3_cost")})
    from rl_curriculum.curriculum261_r6_pairs import matched_gap_stats
    _write_json(out, "block_cluster_uncertainty.json", {
        "main": matched_gap_stats(c2_matched_main["block_table"]),
        "holdout": matched_gap_stats(c2_matched_hold["block_table"]),
    })
    overall = {
        "format": "cur261-r6-robustness-gate-v1",
        "iteration": "r6",
        "preprocessing_gate": {
            "pass": preprocessing_gate["pass"]},
        "curriculum_gate": {
            "pass": curriculum_gate["pass"],
            "rule": "strict per-corpus AND + C2 matched block + "
                    "independent marginal guard(唯一口径;无 pooled 救援)"},
        "supervised_gate": {
            "pass": supervised["pass"],
            "note": "representation gate(§28 PASS 条件)"},
        "c2_density_gate": {"pass": c2_density["pass"]},
        "c2_marginal_guard": {
            "main": marginal_main["guard"]["pass"],
            "holdout": marginal_hold["guard"]["pass"]},
        "pass": bool(preprocessing_gate["pass"]
                     and curriculum_gate["pass"]
                     and supervised["pass"]
                     and c2_density["pass"]),
    }
    _write_json(out, "robustness_gate.json", overall)

    _write_json(out, "calibration_evidence.json", {
        "parameter_pack_digest": pack["digest"],
        "selected_c2_candidate": pack["selected_c2_candidate"],
        "selected_block_count": n_blocks,
        "design_plan_digest": (out / "r6_design_plan_digest.txt"
                               ).read_text(encoding="utf-8").strip(),
        "rung_params_by_family": {
            f: r6_family_rung_params(f, pack)
            for f in ("c1_opportunity", "c2_context", "c3_cost")},
        "frozen_parameter_identity": frozen_parameter_identity_r6(),
        "reference_thresholds_by_family": {
            f: dict(family_specs()[f].reference_defaults)
            for f in CURRICULUM261_FAMILIES},
        "bundle_hash_main": v2_main.bundle_hash,
        "bundle_hash_holdout": v2_hold.bundle_hash,
        "conditioning_gate_constants": CONDITIONING_GATE,
        "supervised_gate_constants": SUPERVISED_GATE,
        "kappa": ROBUSTNESS_KAPPA_R6,
        "density_thresholds": {
            "median_reference_trades_per_episode_min":
                C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
            "reference_long_label_rate_min":
                C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6,
        },
    })
    _write_json(out, "calibration_summary.json", {
        "format": "cur261-r6-calibration-summary-v1",
        "c1_c3_main": {f: {
            "difficulty_ladder":
                calib_main_c13["families"][f]["difficulty_ladder"],
            "conditions": curriculum_gate["families"][f][
                "calibration_r6_conditions_strict"]}
            for f in ("c1_opportunity", "c3_cost")},
        "c2_matched_main_conditions": curriculum_gate["families"][
            "c2_context"]["calibration_r6_matched_conditions"],
    })
    _write_json(out, "calibration_holdout_summary.json", {
        "format": "cur261-r6-calibration-holdout-summary-v1",
        "c1_c3_holdout": {f: {
            "difficulty_ladder":
                calib_hold_c13["families"][f]["difficulty_ladder"],
            "conditions": curriculum_gate["families"][f][
                "calibration_holdout_r6_conditions_strict"]}
            for f in ("c1_opportunity", "c3_cost")},
        "c2_matched_holdout_conditions": curriculum_gate["families"][
            "c2_context"]["calibration_holdout_r6_matched_conditions"],
    })
    print(f"[calibrate] preprocessing gate = "
          f"{preprocessing_gate['pass']}; curriculum gate (strict) = "
          f"{curriculum_gate['pass']}; supervised = "
          f"{supervised['pass']}; density = {c2_density['pass']}")
    if not overall["pass"]:
        print("[calibrate] robustness gate FAIL——禁止 lock plan(§30);"
              "R6 = FAIL,修复须 R6.1/R7 + 全新 namespaces")
        return 1
    return 0


def _verify_namespace_safe() -> dict:
    try:
        return verify_r6_namespace_isolation()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def cmd_preflight_static(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r6_preflight import (
        run_prelock_static_preflight,
    )

    result = run_prelock_static_preflight(Path(args.out_dir), VENDOR_PIN)
    print(f"[preflight-static] pass={result['pass']}")
    return 0 if result["pass"] else 1


def cmd_lock_plan(args: argparse.Namespace) -> int:
    out = Path(args.out_dir)
    gate = json.loads((out / "robustness_gate.json").read_text(
        encoding="utf-8"))
    if not gate.get("pass"):
        print("[lock-plan] robustness gate 非 PASS,拒绝 lock(§30)")
        return 1
    from rl_curriculum.curriculum261_final import _frozen_contract_integrity
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r6_param_pack import (
        frozen_parameter_identity_r6,
        load_selected_pack,
    )
    from rl_curriculum.curriculum261_r6_plan import (
        build_plan_r6,
        lock_plan_r6,
    )
    from rl_platform.versions import (
        ACTION_SPEC_VERSION,
        ENV_CORE_VERSION,
        EXECUTION_CONTRACT_VERSION,
        OBSERVATION_SPEC_VERSION,
        REWARD_SPEC_VERSION,
        TERMINAL_LIQUIDATION_VERSION,
    )

    evidence = json.loads(
        (out / "calibration_evidence.json").read_text(encoding="utf-8"))
    prep_gate = json.loads(
        (out / "preprocessing_robustness_gate.json").read_text(
            encoding="utf-8"))
    cur_gate = json.loads(
        (out / "curriculum_robustness_gate.json").read_text(
            encoding="utf-8"))
    eq = json.loads((out / "production_equivalence.json").read_text(
        encoding="utf-8"))
    pack = load_selected_pack(out)
    frozen = _frozen_contract_integrity()
    if not frozen["pass"]:
        print("[lock-plan] 冻结合同完整性 FAIL,拒绝 lock")
        return 1
    static = json.loads(
        (out / "prelock_static_preflight.json").read_text(
            encoding="utf-8")) if (out / "prelock_static_preflight.json"
                                    ).is_file() else {"pass": None}
    if static.get("pass") is not True:
        print("[lock-plan] pre-lock static preflight 未 PASS(§29A 前置)"
              "——拒绝 lock")
        return 1
    plan = build_plan_r6(
        baseline_commit=BASELINE_COMMIT_R6,
        vendor_pin=VENDOR_PIN,
        frozen_contracts={
            "env_core": ENV_CORE_VERSION,
            "observation_spec": OBSERVATION_SPEC_VERSION,
            "action_spec": ACTION_SPEC_VERSION,
            "reward_spec": REWARD_SPEC_VERSION,
            "execution": EXECUTION_CONTRACT_VERSION,
            "terminal_liquidation": TERMINAL_LIQUIDATION_VERSION,
        },
        parameter_pack=pack,
        design_plan_digest=evidence["design_plan_digest"],
        selected_c2_candidate=pack["selected_c2_candidate"],
        frozen_parameter_identity=evidence["frozen_parameter_identity"],
        preprocessing_v2_contract_digest=preprocessing_v2_contract_digest(),
        calibration_bundle_hash=evidence["bundle_hash_main"],
        holdout_bundle_hash=evidence["bundle_hash_holdout"],
        preprocessing_robustness_gate=prep_gate,
        curriculum_robustness_gate=cur_gate,
        conditioning_gate_constants=evidence[
            "conditioning_gate_constants"],
        supervised_gate_constants=evidence[
            "supervised_gate_constants"],
        kappa=evidence["kappa"],
        reference_thresholds_by_family=evidence[
            "reference_thresholds_by_family"],
        density_thresholds=evidence["density_thresholds"],
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        prior_r4_parameter_pack_digest=PRIOR_R4_PARAMETER_PACK_DIGEST,
        prior_r5_design_plan_digest=PRIOR_R5_DESIGN_PLAN_DIGEST,
        equivalence_report=eq,
    )
    path, digest = lock_plan_r6(plan)
    print(f"[lock-plan] locked {path} digest={digest}")
    return 0


def cmd_preflight_sealed(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r6_preflight import (
        run_postlock_sealed_preflight,
    )

    att = run_postlock_sealed_preflight(Path(args.out_dir), VENDOR_PIN)
    print(f"[preflight-sealed] pass={att['pass']} "
          f"digest={att.get('digest')}")
    return 0 if att["pass"] else 1


def cmd_qualify(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r6_final import (
        run_final_qualification_r6,
    )

    result = run_final_qualification_r6(Path(args.out_dir))
    print(f"[qualify] verdict={result['verdict']} "
          f"total_pairs={result['total_pairs']}")
    return 0 if result["verdict"] == "PASS" else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r6_smoke import run_ppo_smoke_r6

    envelope = Path(args.out_dir) / (
        "qualification_preprocessor_bundle.json")
    pack = None
    try:
        pack = _pack(Path(args.out_dir))
    except RuntimeError:
        pack = None
    result = run_ppo_smoke_r6(
        envelope_path=envelope if envelope.is_file() else None, pack=pack)
    _write_json(Path(args.out_dir), "ppo_256step_smoke.json", result)
    print(f"[smoke] pass={result['pass']}")
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="curriculum261-r6",
        description="Stage 2.6.1 Repair R6:C2 全局 Ladder 重构、"
                    "Matched-Ladder 统计与 Clean Qualification")
    parser.add_argument("--out-dir", default=str(_default_art()),
                        help="artifacts 目录(默认与 lock-marker 目录统一)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("audit", "design-plan-lock", "design", "calibrate",
                 "preflight-static", "lock-plan", "preflight-sealed",
                 "qualify", "smoke", "namespace-integrity"):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", default=str(_default_art()))
        if name == "audit":
            p.add_argument("--fit-pairs", type=int, default=2)
    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "design-plan-lock":
        return cmd_design_plan_lock(args)
    if args.cmd == "design":
        return cmd_design(args)
    if args.cmd == "calibrate":
        return cmd_calibrate(args)
    if args.cmd == "preflight-static":
        return cmd_preflight_static(args)
    if args.cmd == "lock-plan":
        return cmd_lock_plan(args)
    if args.cmd == "preflight-sealed":
        return cmd_preflight_sealed(args)
    if args.cmd == "qualify":
        return cmd_qualify(args)
    if args.cmd == "smoke":
        return cmd_smoke(args)
    if args.cmd == "namespace-integrity":
        rep = _verify_namespace_safe()
        _write_json(Path(args.out_dir), "seed_namespace_integrity.json",
                    rep)
        print(f"[namespace-integrity] pass={rep['pass']}")
        return 0 if rep["pass"] else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
