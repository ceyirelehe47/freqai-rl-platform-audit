# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R7 CLI(audit → cue-audit → preplan-smoke →
design-plan-lock → design → calibrate → preflight-static → lock-plan
→ preflight-sealed → qualify → smoke → namespace-integrity)。

§16.1 顺序硬约束:全部代码/测试/合同审计/candidate grid 在 plan 锁定
前完成;preplan smoke 只用 sentinel ladder;design plan 在第一条
design episode 前锁定;calibration/holdout 独立 PASS(无 pooled 救援)
后才允许 lock-plan。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASELINE_COMMIT_R7 = "7970d2096b6a5a93a85d32620b9b2b3a24826568"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
PRIOR_R5_BASELINE_COMMIT = "40a0d9ae4ac8fcfa6f643f584a8fb63ec5579afc"
PRIOR_R2_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99")
PRIOR_DIAG262R2_PLAN_DIGEST = (
    "dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60")
PRIOR_R4_PARAMETER_PACK_DIGEST = (
    "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99")
PRIOR_R5_DESIGN_PLAN_DIGEST = (
    "r5dp-0c1eb69f95336f7d649192bc4293eaf768b37508f47c8c21c919009eb3afe52d")
PRIOR_R6_DESIGN_PLAN_DIGEST = (
    "r6dp-db74ed109a7bf7a955c74f1bd248213002d3c08f79512abf0faf93f8941e03c7")


def _default_art() -> Path:
    from rl_curriculum.curriculum261_r7_namespaces import (
        qualification_r7_lock_dir,
    )

    return qualification_r7_lock_dir()


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
    from rl_curriculum.curriculum261_r7_param_pack import load_selected_pack

    return load_selected_pack(out_dir)


def _git_head(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _historical_binding() -> dict:
    binding = {
        "r2_plan_digest_expected": PRIOR_R2_PLAN_DIGEST,
        "diag262r2_plan_digest_expected": PRIOR_DIAG262R2_PLAN_DIGEST,
        "r4_parameter_pack_digest_expected":
            PRIOR_R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest_expected": PRIOR_R5_DESIGN_PLAN_DIGEST,
        "r6_design_plan_digest_expected": PRIOR_R6_DESIGN_PLAN_DIGEST,
        "r6_parent_of_baseline": PRIOR_R5_BASELINE_COMMIT,
    }
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo:
        checks = [
            ("stage2_6_1/artifacts/repair2/qualification_plan_digest.txt",
             "r2_plan_digest_actual"),
            ("stage2_6_2/artifacts/repair2/diagnostic_plan_digest.txt",
             "diag262r2_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair4/r4_parameter_pack_digest.txt",
             "r4_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair5/r5_design_plan_digest.txt",
             "r5_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair6/r6_design_plan_digest.txt",
             "r6_design_plan_digest_actual"),
        ]
        for rel, key in checks:
            p = release_repo / rel
            if p.is_file():
                binding[key] = p.read_text(encoding="utf-8").strip()
    binding["digests_match"] = bool(
        binding.get("r2_plan_digest_actual") == PRIOR_R2_PLAN_DIGEST
        and binding.get("diag262r2_plan_digest_actual")
        == PRIOR_DIAG262R2_PLAN_DIGEST
        and binding.get("r4_parameter_pack_digest_actual")
        == PRIOR_R4_PARAMETER_PACK_DIGEST
        and binding.get("r5_design_plan_digest_actual")
        == PRIOR_R5_DESIGN_PLAN_DIGEST
        and binding.get("r6_design_plan_digest_actual")
        == PRIOR_R6_DESIGN_PLAN_DIGEST)
    return binding


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
    _write_json(out, "baseline_integrity.json", {
        "expected_baseline": BASELINE_COMMIT_R7,
        "release_repo_head": head,
        "baseline_matches": bool(head == BASELINE_COMMIT_R7),
        "note": "发布仓库 HEAD 应等于 R6 诚实 FAIL checkpoint"
                "(或其明确后继;组装 R7 产物前)",
    })
    _write_json(out, "historical_binding.json", _historical_binding())

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
        "numerics": "与 R4-R6 逐位一致(vendor pipeline 直接复用);"
                    "R7 在全新语料重新资格验证",
    })
    _dump_txt(out, "preprocessing_v2_contract_digest.txt",
              preprocessing_v2_contract_digest())
    records = generate_fit_bank("preplan_smoke_r7", args.fit_pairs)
    fit_df = fit_matrix_from_records(records)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", eq)
    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity_pre_design.json", ns)
    print(f"[audit] equivalence pass={eq['pass']} "
          f"ns pass={ns.get('pass')} "
          f"digests_match={_historical_binding()['digests_match']}")
    ok = bool(eq["pass"] and ns.get("pass")
              and _historical_binding()["digests_match"]
              and vendor.get("sha") == VENDOR_PIN and vendor.get("clean"))
    return 0 if ok else 1


def _verify_namespace_safe() -> dict:
    try:
        from rl_curriculum.curriculum261_r7_namespaces import (
            verify_r7_namespace_isolation,
        )

        return verify_r7_namespace_isolation()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def cmd_cue_audit(args: argparse.Namespace) -> int:
    """§9 合同审计(在任何 R7 candidate design data 之前运行)。"""
    from rl_curriculum.curriculum261_r7_cue_contract import (
        cue_semantic_contract_digest,
        cue_semantic_contract_payload,
        run_cue_contract_audit,
    )

    out = Path(args.out_dir)
    report = run_cue_contract_audit(out)
    _dump_txt(out, "cue_semantic_contract_digest.txt",
              cue_semantic_contract_digest())
    _write_json(out, "cue_semantic_contract.json",
                cue_semantic_contract_payload())
    print(f"[cue-audit] p_contract={report['p_contract']:.6f} "
          f"mc={report['monte_carlo']['p_hat']:.6f}"
          f"(se={report['monte_carlo']['se']:.6f}) "
          f"bridge={report['bridge']['empirical_recall']:.6f} "
          f"(z={report['bridge']['bridge_z_vs_analytic']:.2f}) "
          f"floor={report['noninferiority']['recall_floor']:.6f}")
    bridge_z = abs(report["bridge"]["bridge_z_vs_analytic"])
    if bridge_z > 4.0:
        print("[cue-audit] 警告:bridge 实测与解析差 >4σ——解析层可能"
              "漏项;不得继续,人工复核(§9)")
        return 1
    return 0


def cmd_preplan_smoke(args: argparse.Namespace) -> int:
    """§16.1 preplan engineering smoke(固定 sentinel ladder;极小规模;
    不参与参数选择;不用 design/calibration/holdout/final namespace)。"""
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
    from rl_curriculum.curriculum261_r7_cue_eval import (
        canonical_cue_observations,
        cluster_bootstrap_rate,
    )
    from rl_curriculum.curriculum261_r6_tape import (
        generate_matched_block_with_attempts,
    )
    import hashlib as _hashlib

    out = Path(args.out_dir)
    sentinel = {r: dict(p) for r, p in C2_RUNG_PARAMS.items()}
    blocks = [generate_matched_block_with_attempts(
        sentinel, namespace="preplan_smoke_r7", block_index=i)
        for i in range(3)]
    obs = canonical_cue_observations(blocks)
    pos = [{"n": sum(1 for e in pb["events"] if e["is_positive"]),
            "hit": sum(1 for e in pb["events"]
                       if e["is_positive"] and e["over"])}
           for pb in obs["per_block"]]
    rate = cluster_bootstrap_rate(pos, side="lower")
    identity = {
        "sentinel": {r: {k: sentinel[r][k]
                         for k in ("alpha_bps", "wick_kappa")}
                     for r in sentinel},
        "sentinel_digest": "r7smoke-" + _hashlib.sha256(json.dumps(
            {r: sorted(sentinel[r].items()) for r in sorted(sentinel)},
            default=str).encode("utf-8")).hexdigest(),
        "n_blocks": len(blocks),
        "namespace": "preplan_smoke_r7",
        "role": "仅证明代码不会立即 crash;不使用正式 candidate;"
                "不参与任何参数选择;不得使用 design/calibration/"
                "holdout/final namespace(§16.1)",
    }
    _write_json(out, "preplan_engineering_smoke.json", {
        "format": "cur261-r7-preplan-smoke-v1",
        "identity": identity,
        "violations": obs["violations"],
        "positive_cue_recall_lower_bound": rate["bound"],
        "n_unique_positive_cues": sum(p["n"] for p in pos),
        "cue_table_digest": obs["cue_table_digest"],
        "no_crash": True,
        "pass": bool(not obs["violations"]
                     and sum(p["n"] for p in pos) > 0),
    })
    print("[preplan-smoke] pass(no crash;sentinel ladder only)")
    return 0


def cmd_design_plan_lock(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r7_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r7_design import (
        design_plan_payload_r7,
        lock_design_plan_r7,
    )
    import hashlib as _hashlib

    out = Path(args.out_dir)
    audit = json.loads((out / "cue_contract_audit.json").read_text(
        encoding="utf-8"))
    smoke = json.loads(
        (out / "preplan_engineering_smoke.json").read_text(
            encoding="utf-8"))
    plan = design_plan_payload_r7(
        baseline_commit=BASELINE_COMMIT_R7,
        vendor_pin=VENDOR_PIN,
        v2_contract_digest=preprocessing_v2_contract_digest(),
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        cue_audit=audit,
        preplan_smoke_identity={
            "sentinel_digest": smoke["identity"]["sentinel_digest"],
            "cue_contract_digest": cue_semantic_contract_digest(),
            "audit_digest": audit["audit_digest"],
        },
    )
    path, digest = lock_design_plan_r7(out, plan)
    print(f"[design-plan-lock] locked {path} digest={digest}")
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r7_design import (
        load_locked_design_plan_r7,
        run_design_stage_r7,
    )

    out = Path(args.out_dir)
    plan, digest = load_locked_design_plan_r7(out)
    selection = run_design_stage_r7(out, plan, digest,
                                    baseline_commit=BASELINE_COMMIT_R7)
    print(f"[design] pass={selection['pass']} "
          f"selected={selection.get('selected_candidate')} "
          f"n={selection.get('selected_block_count')} "
          f"pack={selection.get('parameter_pack_digest')}")
    return 0 if selection["pass"] else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile,
    )
    from rl_curriculum.curriculum261_r6_calibration import (
        preprocessing_robustness_checks_r6,
    )
    from rl_curriculum.curriculum261_r7_calibration import (
        c2_independent_marginal_guard_r7,
        c2_matched_conditions_r7,
        fit_preprocessor_v2_from_bank_r7,
        generate_fit_bank_r7,
        run_c2_density_diagnostics_r7,
        run_c2_diagnostics_r7,
        run_calibration_corpus_c13_r7,
        run_c2_independent_corpus_r7,
        run_c2_matched_corpus_r7,
        run_generator_stress_r7,
        supervised_learnability_run_r7,
    )
    from rl_curriculum.curriculum261_r6_pairs import (
        ROBUSTNESS_KAPPA_R6,
        corpus_conditions_r6_pair,
        matched_gap_stats,
        scrambled_gap_control,
    )
    from rl_curriculum.curriculum261_r7_namespaces import (
        require_r7_iteration_active,
    )
    from rl_curriculum.curriculum261_r7_param_pack import (
        frozen_parameter_identity_r7,
        r7_family_rung_params,
        r7_override_for,
        verify_r4_inheritance_r7,
    )

    require_r7_iteration_active()
    out = Path(args.out_dir)
    pack = _pack(out)
    inheritance = verify_r4_inheritance_r7(pack)
    if not inheritance:
        print("[calibrate] R4 inheritance 验证失败;fail closed")
        return 1
    n_blocks = int(pack["selected_block_count"])
    design_digest = (out / "r7_design_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    recall_floor_value = float(pack["recall_floor"])

    print("[calibrate] fitting main preprocessor "
          "(preprocess_fit_calibration_r7)...")
    records_main = generate_fit_bank_r7(
        "preprocess_fit_calibration_r7", pack)
    v2_main, manifest_main = fit_preprocessor_v2_from_bank_r7(
        "preprocess_fit_calibration_r7", pack, records=records_main,
        parameter_pack_identity=pack["digest"])
    print("[calibrate] fitting holdout preprocessor "
          "(preprocess_fit_holdout_r7)...")
    records_hold = generate_fit_bank_r7(
        "preprocess_fit_holdout_r7", pack)
    v2_hold, manifest_hold = fit_preprocessor_v2_from_bank_r7(
        "preprocess_fit_holdout_r7", pack, records=records_hold,
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
        "eval_namespaces": ["calibration_r7", "calibration_holdout_r7"],
        "c2_matched_namespaces": ["calibration_r7",
                                  "calibration_holdout_r7"],
        "c2_independent_namespaces": [
            "c2_independent_calibration_r7",
            "c2_independent_holdout_r7"],
        "fit_bank_used_for_metrics": False,
        "protocol": "offline training-corpus fit -> frozen transform;"
                    "fit bank 只用于拟合 preprocessor",
    })

    print("[calibrate] preprocessing robustness 全电池...")
    eval_records = [
        generate_pair(f, r, 0, namespace="calibration_r7",
                      rung_params_override=r7_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    equiv_records = [
        generate_pair(f, r, i, namespace="calibration_r7",
                      rung_params_override=r7_override_for(f, pack))
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
    supervised = supervised_learnability_run_r7(v2_main, pack)
    _write_json(out, "supervised_learnability.json", supervised)

    print("[calibrate] C1/C3 calibration_r7 + calibration_holdout_r7...")
    calib_main_c13 = run_calibration_corpus_c13_r7(
        v2_main, pack, "calibration_r7")
    calib_hold_c13 = run_calibration_corpus_c13_r7(
        v2_main, pack, "calibration_holdout_r7")
    _write_json(out, "pair_evidence_table_calibration.json", {
        f: calib_main_c13["families"][f]["pair_table"]
        for f in ("c1_opportunity", "c3_cost")})
    _write_json(out, "pair_evidence_table_holdout.json", {
        f: calib_hold_c13["families"][f]["pair_table"]
        for f in ("c1_opportunity", "c3_cost")})

    print(f"[calibrate] C2 matched blocks x2 corpora (n={n_blocks})...")
    c2_matched_main = run_c2_matched_corpus_r7(
        v2_main, pack, "calibration_r7", n_blocks)
    c2_matched_hold = run_c2_matched_corpus_r7(
        v2_main, pack, "calibration_holdout_r7", n_blocks)
    _write_json(out, "c2_block_evidence_table_calibration.json",
                c2_matched_main["block_table"])
    _write_json(out, "c2_block_evidence_table_holdout.json",
                c2_matched_hold["block_table"])
    _write_json(out, "matched_ladder_identity.json", {
        "main": c2_matched_main["block_corpus_summary"],
        "holdout": c2_matched_hold["block_corpus_summary"],
    })
    c2_conditions_main = c2_matched_conditions_r7(
        c2_matched_main, pack, recall_floor_value)
    c2_conditions_hold = c2_matched_conditions_r7(
        c2_matched_hold, pack, recall_floor_value)
    _write_json(out, "matched_block_integrity.json", {
        "main": c2_conditions_main["checks"],
        "holdout": c2_conditions_hold["checks"],
    })
    _write_json(out, "cue_semantics_calibration.json",
                c2_conditions_main["cue_semantics"])
    _write_json(out, "cue_semantics_holdout.json",
                c2_conditions_hold["cue_semantics"])

    print("[calibrate] C2 independent marginal guard x2 corpora...")
    c2_indep_main = run_c2_independent_corpus_r7(
        v2_main, pack, "c2_independent_calibration_r7")
    c2_indep_hold = run_c2_independent_corpus_r7(
        v2_main, pack, "c2_independent_holdout_r7")
    marginal_main = c2_independent_marginal_guard_r7(
        c2_indep_main, pack, recall_floor_value)
    marginal_hold = c2_independent_marginal_guard_r7(
        c2_indep_hold, pack, recall_floor_value)
    _write_json(out, "c2_independent_marginal_calibration.json",
                marginal_main)
    _write_json(out, "c2_independent_marginal_holdout.json",
                marginal_hold)

    print("[calibrate] C2 三语义诊断 + 密度 + stress + scrambled...")
    c2_sem_records = [
        rec for blk in c2_matched_main["blocks"]
        for rec in blk.pair_records.values()]
    c2_diag = run_c2_diagnostics_r7(c2_sem_records)
    _write_json(out, "candidate_payoff_separation_calibration.json",
                {k: v for k, v in c2_diag["cue_payoff_separation"].items()
                 if k != "per_rung"})
    c2_sem_records_hold = [
        rec for blk in c2_matched_hold["blocks"]
        for rec in blk.pair_records.values()]
    c2_diag_hold = run_c2_diagnostics_r7(c2_sem_records_hold)
    _write_json(out, "candidate_payoff_separation_holdout.json",
                {k: v for k, v in c2_diag_hold["cue_payoff_separation"].items()
                 if k != "per_rung"})
    c2_density = run_c2_density_diagnostics_r7(
        c2_matched_main, c2_matched_hold, pack)
    _write_json(out, "c2_density_diagnostics.json", c2_density)
    stress = run_generator_stress_r7(pack)
    _write_json(out, "generator_stress_summary.json", stress)
    _write_json(out, "matched_vs_scrambled_variance.json", {
        "main": scrambled_gap_control(c2_matched_main["block_table"]),
        "holdout": scrambled_gap_control(
            c2_matched_hold["block_table"]),
        "note": "仅诊断(matched 方差缩减说明);不参与 PASS 判定",
    })

    preprocessing_gate = {
        "format": "cur261-r7-preprocessing-robustness-gate-v1",
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
    # R7 curriculum gate(strict per-corpus AND;R7 版条件组装——不含
    # R6 点阈值 separation;C2 用 cluster-aware R7 条件)
    fam_conditions = {}
    for family in ("c1_opportunity", "c3_cost"):
        fam_conditions[family] = {
            "calibration_r7_conditions_strict": corpus_conditions_r6_pair(
                calib_main_c13["families"][family],
                ROBUSTNESS_KAPPA_R6),
            "calibration_holdout_r7_conditions_strict":
                corpus_conditions_r6_pair(
                    calib_hold_c13["families"][family],
                    ROBUSTNESS_KAPPA_R6),
        }
    curriculum_gate = {
        "format": "cur261-r7-curriculum-robustness-gate-v1",
        "iteration": "r7",
        "kappa": ROBUSTNESS_KAPPA_R6,
        "rule": "strict per-corpus AND + C2 matched block(R7 cluster-"
                "aware cue) + independent marginal guard;唯一口径;"
                "无 pooled 救援(§23/§24)",
        "families": fam_conditions,
        "c2_matched": {
            "calibration_r7_conditions": c2_conditions_main,
            "calibration_holdout_r7_conditions": c2_conditions_hold,
        },
        "c2_marginal": {
            "main": marginal_main["guard"],
            "holdout": marginal_hold["guard"],
        },
        "stress": stress,
        "c2_density": {
            "main": {"pass": c2_density["main"]["pass"]},
            "holdout": {"pass": c2_density["holdout"]["pass"]}},
    }
    curriculum_gate["pass"] = bool(
        all(cond_["calibration_r7_conditions_strict"]["pass"]
            and cond_["calibration_holdout_r7_conditions_strict"]["pass"]
            for cond_ in fam_conditions.values())
        and c2_conditions_main["pass"] and c2_conditions_hold["pass"]
        and marginal_main["guard"]["pass"]
        and marginal_hold["guard"]["pass"]
        and stress.get("pass", False)
        and c2_density["main"]["pass"] and c2_density["holdout"]["pass"])
    _write_json(out, "preprocessing_robustness_gate.json",
                preprocessing_gate)
    _write_json(out, "curriculum_robustness_gate.json", curriculum_gate)
    _write_json(out, "block_cluster_uncertainty.json", {
        "main": matched_gap_stats(c2_matched_main["block_table"]),
        "holdout": matched_gap_stats(c2_matched_hold["block_table"]),
    })
    overall = {
        "format": "cur261-r7-robustness-gate-v1",
        "iteration": "r7",
        "preprocessing_gate": {
            "pass": preprocessing_gate["pass"]},
        "curriculum_gate": {
            "pass": curriculum_gate["pass"],
            "rule": "strict per-corpus AND + C2 matched block + "
                    "cluster-aware cue + independent marginal guard"
                    "(唯一口径;无 pooled 救援)"},
        "supervised_gate": {
            "pass": supervised["pass"],
            "note": "representation gate(§24 PASS 条件)"},
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
        "design_plan_digest": design_digest,
        "rung_params_by_family": {
            f: r7_family_rung_params(f, pack)
            for f in ("c1_opportunity", "c2_context", "c3_cost")},
        "frozen_parameter_identity": frozen_parameter_identity_r7(),
        "reference_thresholds_by_family": {
            f: dict(family_specs()[f].reference_defaults)
            for f in CURRICULUM261_FAMILIES},
        "bundle_hash_main": v2_main.bundle_hash,
        "bundle_hash_holdout": v2_hold.bundle_hash,
        "kappa": ROBUSTNESS_KAPPA_R6,
    })
    _write_json(out, "calibration_summary.json", {
        "format": "cur261-r7-calibration-summary-v1",
        "c1_c3_main": {f: {
            "difficulty_ladder":
                calib_main_c13["families"][f]["difficulty_ladder"],
            "conditions": fam_conditions[f][
                "calibration_r7_conditions_strict"]}
            for f in ("c1_opportunity", "c3_cost")},
        "c2_matched_main_conditions": c2_conditions_main["checks"],
    })
    _write_json(out, "calibration_holdout_summary.json", {
        "format": "cur261-r7-calibration-holdout-summary-v1",
        "c1_c3_holdout": {f: {
            "difficulty_ladder":
                calib_hold_c13["families"][f]["difficulty_ladder"],
            "conditions": fam_conditions[f][
                "calibration_holdout_r7_conditions_strict"]}
            for f in ("c1_opportunity", "c3_cost")},
        "c2_matched_holdout_conditions": c2_conditions_hold["checks"],
    })
    print(f"[calibrate] preprocessing gate = "
          f"{preprocessing_gate['pass']}; curriculum gate (strict) = "
          f"{curriculum_gate['pass']}; supervised = "
          f"{supervised['pass']}; density = {c2_density['pass']}")
    if not overall["pass"]:
        print("[calibrate] robustness gate FAIL——禁止 lock plan(§26);"
              "R7 = FAIL,修复须 R7.1/R8 + 全新 namespaces")
        return 1
    return 0


def cmd_preflight_static(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r7_preflight import (
        run_prelock_static_preflight_r7,
    )

    result = run_prelock_static_preflight_r7(Path(args.out_dir),
                                             VENDOR_PIN)
    print(f"[preflight-static] pass={result['pass']}")
    return 0 if result["pass"] else 1


def cmd_lock_plan(args: argparse.Namespace) -> int:
    out = Path(args.out_dir)
    gate = json.loads((out / "robustness_gate.json").read_text(
        encoding="utf-8"))
    if not gate.get("pass"):
        print("[lock-plan] robustness gate 非 PASS,拒绝 lock(§26)")
        return 1
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
    )
    from rl_curriculum.curriculum261_r7_param_pack import (
        frozen_parameter_identity_r7,
    )
    from rl_curriculum.curriculum261_r7_plan import (
        build_plan_r7,
        lock_plan_r7,
    )

    pack = _pack(out)
    design_digest = (out / "r7_design_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    plan = build_plan_r7(
        baseline_commit=BASELINE_COMMIT_R7,
        vendor_pin=VENDOR_PIN,
        frozen_contracts=_frozen_contract_integrity(),
        parameter_pack=pack,
        design_plan_digest=design_digest,
        selected_c2_candidate=pack["selected_c2_candidate"],
        frozen_parameter_identity=frozen_parameter_identity_r7(),
        preprocessing_v2_contract_digest=(out /
                                          "preprocessing_v2_contract_"
                                          "digest.txt").read_text(
                                              encoding="utf-8").strip(),
        calibration_bundle_hash=json.loads(
            (out / "preprocessor_bundle_calibration.json").read_text(
                encoding="utf-8"))["bundle_hash"],
        holdout_bundle_hash=json.loads(
            (out / "preprocessor_bundle_holdout.json").read_text(
                encoding="utf-8"))["bundle_hash"],
        preprocessing_robustness_gate=json.loads(
            (out / "preprocessing_robustness_gate.json").read_text(
                encoding="utf-8")),
        curriculum_robustness_gate=json.loads(
            (out / "curriculum_robustness_gate.json").read_text(
                encoding="utf-8")),
        conditioning_gate_constants={},
        supervised_gate_constants={},
        kappa=1.5,
        reference_thresholds_by_family=json.loads(
            (out / "calibration_evidence.json").read_text(
                encoding="utf-8"))["reference_thresholds_by_family"],
        density_thresholds={},
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        prior_r4_parameter_pack_digest=PRIOR_R4_PARAMETER_PACK_DIGEST,
        prior_r5_design_plan_digest=PRIOR_R5_DESIGN_PLAN_DIGEST,
        prior_r6_design_plan_digest=PRIOR_R6_DESIGN_PLAN_DIGEST,
    )
    path, digest = lock_plan_r7(plan)
    print(f"[lock-plan] locked {path} digest={digest}")
    return 0


def cmd_preflight_sealed(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r7_preflight import (
        run_postlock_sealed_preflight_r7,
    )

    att = run_postlock_sealed_preflight_r7(Path(args.out_dir),
                                           VENDOR_PIN)
    print(f"[preflight-sealed] pass={att['pass']} "
          f"digest={att['digest']}")
    return 0 if att["pass"] else 1


def cmd_qualify(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r7_final import (
        run_final_qualification_r7,
    )

    result = run_final_qualification_r7(Path(args.out_dir))
    print(f"[qualify] verdict={result['verdict']}")
    _write_json(Path(args.out_dir), "seed_namespace_integrity_post_"
                "final.json", _verify_namespace_safe())
    return 0 if result["verdict"] == "PASS" else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r7_smoke import run_ppo_smoke_r7

    out = Path(args.out_dir)
    pack = None
    try:
        pack = _pack(out)
    except RuntimeError:
        pass
    smoke = run_ppo_smoke_r7(pack=pack)
    _write_json(out, "ppo_256step_smoke.json", smoke)
    print(f"[smoke] pass={smoke['pass']}")
    return 0 if smoke["pass"] else 1


def cmd_namespace_integrity(args: argparse.Namespace) -> int:
    ns = _verify_namespace_safe()
    _write_json(Path(args.out_dir), "seed_namespace_integrity.json", ns)
    print(f"[namespace-integrity] pass={ns.get('pass')} "
          f"namespaces={len(ns.get('r7_namespaces', []))}")
    return 0 if ns.get("pass") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="r7-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _with_out(p):
        p.add_argument("--out-dir", default=None)
        return p

    _with_out(sub.add_parser("audit")).add_argument(
        "--fit-pairs", type=int, default=2)

    for name in ("cue-audit", "preplan-smoke", "design-plan-lock",
                 "design", "calibrate", "preflight-static", "lock-plan",
                 "preflight-sealed", "qualify", "smoke",
                 "namespace-integrity"):
        _with_out(sub.add_parser(name))

    args = parser.parse_args(argv)
    if not args.out_dir:
        args.out_dir = str(_default_art())
    handlers = {
        "audit": cmd_audit,
        "cue-audit": cmd_cue_audit,
        "preplan-smoke": cmd_preplan_smoke,
        "design-plan-lock": cmd_design_plan_lock,
        "design": cmd_design,
        "calibrate": cmd_calibrate,
        "preflight-static": cmd_preflight_static,
        "lock-plan": cmd_lock_plan,
        "preflight-sealed": cmd_preflight_sealed,
        "qualify": cmd_qualify,
        "smoke": cmd_smoke,
        "namespace-integrity": cmd_namespace_integrity,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
