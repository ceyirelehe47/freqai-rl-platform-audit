"""阶段 2.6.1 Repair R4 CLI(WP 串联)。

子命令(按 §36 回归顺序):
- audit:              production preprocessing 审计 + 数值等价;
- design:             §14 D3 design/power 阶段(candidate 网格锁定 ->
                      评估 -> 功效 -> 选定并锁定 parameter pack);
- calibrate:          完整 calibration(V2 fit banks + 双语料 +
                      supervised + 双 robustness gate);
- lock-plan:          plan 构建与锁定(双 gate PASS + design pack 前置);
- qualify:            一次性 final qualification(120 pairs);
- smoke:              256-step PPO plumbing smoke(V2 outer adapter);
- namespace-integrity:§17 R4 namespace 隔离验证。

CLI output 目录与 lock-marker 目录统一(默认均为
artifacts/route_c_stage2_6_1_repair4 = CURRICULUM261_R4_LOCK_DIR)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rl_curriculum.curriculum261_r4_namespaces import (
    qualification_r4_lock_dir,
    verify_r4_namespace_isolation,
)

#: 本轮 baseline(Stage 2.6.1 Repair R3 诚实 FAIL checkpoint)。
BASELINE_COMMIT_R4 = "d105405e5ddd989d6faf0601e912907746ad8980"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
PRIOR_R2_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99")
PRIOR_DIAG262R2_PLAN_DIGEST = (
    "dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60")
PRIOR_R3_BASELINE_COMMIT = "1b47db474461a82b07c6b863894b7f9c4b4dce98"


def _default_art() -> Path:
    return qualification_r4_lock_dir()


def _write_json(out_dir: Path, name: str, payload: object) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")


def _dump_txt(out_dir: Path, name: str, text: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(text, encoding="utf-8")


def _pack(out_dir: Path) -> dict:
    from rl_curriculum.curriculum261_r4_param_pack import load_selected_pack

    return load_selected_pack(out_dir)


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

    out = Path(args.out_dir)
    audit = production_preprocessing_audit()
    _write_json(out, "production_preprocessing_audit.json", audit)
    _write_json(out, "production_runtime_config.json",
                audit["source_hashes"][
                    "production_runtime_config_identity"])
    _write_json(out, "production_pipeline_identity.json", {
        "steps": audit["pipeline_built_from_steps"],
        "builder": "pinned vendor IFreqaiModel.define_data_pipeline",
        "freqai_interface_sha256": audit["source_hashes"][
            "freqai_interface_sha256"],
        "base_rl_model_sha256": audit["source_hashes"][
            "base_rl_model_sha256"],
        "library_versions": audit["library_versions"],
    })
    _write_json(out, "preprocessing_v2_contract.json", {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "digest": preprocessing_v2_contract_digest(),
        "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
        "position_slot": POSITION_SLOT_SEMANTICS_V2,
        "numerics": "与 V1 逐位一致(vendor pipeline 直接复用)",
    })
    _dump_txt(out, "preprocessing_v2_contract_digest.txt",
              preprocessing_v2_contract_digest())
    _write_json(out, "observation_space_contract.json",
                OBSERVATION_SPACE_SEMANTICS_V2)
    records = generate_fit_bank(
        "preprocess_fit_design_r4", args.fit_pairs)
    fit_df = fit_matrix_from_records(records)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", eq)
    print(f"[audit] equivalence pass={eq['pass']} "
          f"state_hash={eq['state_hash']}")
    return 0 if eq["pass"] else 1


def cmd_design(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_power import run_design_stage

    results = run_design_stage(Path(args.out_dir))
    return 0 if results["pass"] else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_calibration import (
        run_c2_diagnostics_r4,
        run_calibration_corpus_r4,
        run_generator_stress_r4,
        supervised_learnability_run_r4,
        preprocessing_robustness_checks_r4,
    )
    from rl_curriculum.curriculum261_r3_calibration import (
        CONDITIONING_GATE,
        SUPERVISED_GATE,
    )
    from rl_curriculum.curriculum261_r4_pairs import (
        CALIBRATION_PAIRS_PER_RUNG_R4,
        ROBUSTNESS_KAPPA_R4,
        curriculum_robustness_gate_r4,
    )
    from rl_curriculum.curriculum261_r4_param_pack import (
        frozen_parameter_identity,
    )

    from rl_curriculum.curriculum261_r4_calibration import (
        fit_preprocessor_v2_from_bank,
        generate_fit_bank_r4,
    )

    out = Path(args.out_dir)
    pack = _pack(out)

    # 1) namespace integrity
    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity.json", ns)

    # 2) fit banks(main + holdout)+ V2 preprocessor
    print("[calibrate] fitting main preprocessor "
          "(preprocess_fit_calibration_r4)...")
    records_main = generate_fit_bank_r4(
        "preprocess_fit_calibration_r4", pack)
    v2_main, manifest_main = fit_preprocessor_v2_from_bank(
        "preprocess_fit_calibration_r4", pack, records=records_main,
        parameter_pack_identity=pack["digest"])
    print("[calibrate] fitting holdout preprocessor "
          "(preprocess_fit_holdout_r4)...")
    records_hold = generate_fit_bank_r4(
        "preprocess_fit_holdout_r4", pack)
    v2_hold, manifest_hold = fit_preprocessor_v2_from_bank(
        "preprocess_fit_holdout_r4", pack, records=records_hold,
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
        "eval_namespaces": ["calibration_r4", "calibration_holdout_r4"],
        "fit_bank_used_for_metrics": False,
        "protocol": "offline training-corpus fit -> frozen transform;"
                    "fit bank 只用于拟合 preprocessor",
    })

    # 3) preprocessing robustness 全电池(含 production 数值等价)
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r4_param_pack import (
        r4_override_for,
    )

    eval_records = [
        generate_pair(f, r, 0, namespace="calibration_r4",
                      rung_params_override=r4_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    equiv_records = [
        generate_pair(f, r, i, namespace="calibration_r4",
                      rung_params_override=r4_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS
        for i in range(3)]
    prep_rob = preprocessing_robustness_checks_r4(
        v2_main, v2_hold, records_main, records_hold,
        eval_records, equiv_records, pack)
    _write_json(out, "preprocessing_robustness_checks.json", prep_rob)
    _write_json(out, "production_equivalence.json",
                prep_rob["equivalence_report"])
    _write_json(out, "fit_manifest_identity_validation.json", {
        "manifest_order_invariant": prep_rob["checks"][
            "manifest_order_invariant_multiset_hash"],
        "different_multiset_same_params_same_param_hash": prep_rob[
            "checks"]["different_multiset_same_params_same_param_hash"],
        "different_multiset_different_bundle": prep_rob["checks"][
            "different_multiset_different_bundle"],
        "manifest_tamper_rejected": prep_rob["checks"][
            "manifest_tamper_rejected"],
        "parameter_state_tamper_rejected": prep_rob["checks"][
            "parameter_state_tamper_rejected"],
        "bundle_verification_main": prep_rob["checks"][
            "bundle_verification_main"],
        "bundle_verification_holdout": prep_rob["checks"][
            "bundle_verification_holdout"],
        "fit_manifest_provenance_complete": prep_rob["checks"][
            "fit_manifest_provenance_complete"],
        "pass": bool(
            prep_rob["checks"]["manifest_order_invariant_multiset_hash"]
            and prep_rob["checks"][
                "different_multiset_same_params_same_param_hash"]
            and prep_rob["checks"]["different_multiset_different_bundle"]
            and prep_rob["checks"]["manifest_tamper_rejected"]
            and prep_rob["checks"]["parameter_state_tamper_rejected"]
            and prep_rob["checks"]["bundle_verification_main"]["pass"]
            and prep_rob["checks"]["bundle_verification_holdout"]["pass"]
            and prep_rob["checks"]["fit_manifest_provenance_complete"]),
    })
    _write_json(out, "serialization_reproducibility.json", {
        "envelope_reload_bundle_identity_stable": prep_rob["checks"][
            "envelope_reload_bundle_identity_stable"],
        "envelope_reload_transform_bitwise_equal": prep_rob["checks"][
            "envelope_reload_transform_bitwise_equal"],
        "staged_mixed_same_parameter_state_hash": prep_rob["checks"][
            "staged_mixed_same_parameter_state_hash"],
        "staged_mixed_same_bundle_hash": prep_rob["checks"][
            "staged_mixed_same_bundle_hash"],
        "pass": bool(
            prep_rob["checks"]["envelope_reload_bundle_identity_stable"]
            and prep_rob["checks"][
                "envelope_reload_transform_bitwise_equal"]
            and prep_rob["checks"]["staged_mixed_same_parameter_state_hash"]
            and prep_rob["checks"]["staged_mixed_same_bundle_hash"]),
    })
    _write_json(out, "staged_mixed_fit_equivalence.json", {
        "same_multiset_same_bundle": prep_rob["checks"][
            "staged_mixed_same_bundle_hash"],
        "different_multiset_different_bundle": prep_rob["checks"][
            "different_multiset_different_bundle"],
        "manifest_order_invariant": prep_rob["checks"][
            "manifest_order_invariant_multiset_hash"],
    })
    _write_json(out, "observation_space_validation.json", {
        "calibration_corpora": prep_rob["checks"]["observation_space_v2"],
        "adversarial_out_of_range": prep_rob["checks"][
            "adversarial_out_of_range_probe"],
    })

    # 4) conditioning(fit=main fit bank;eval=calibration_r4)
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile,
    )

    cond = conditioning_profile(v2_main.inner, records_main, eval_records)
    _write_json(out, "conditioning_profile.json", cond)

    # 5) supervised learnability
    print("[calibrate] supervised learnability (3 families x 3 seeds)...")
    supervised = supervised_learnability_run_r4(v2_main, pack)
    _write_json(out, "supervised_learnability.json", supervised)

    # 6) curriculum calibration(main + holdout)
    print("[calibrate] curriculum calibration_r4...")
    calib_main = run_calibration_corpus_r4(
        v2_main, pack, "calibration_r4", out_dir=out,
        prefix="calibration")
    print("[calibrate] curriculum calibration_holdout_r4...")
    calib_hold = run_calibration_corpus_r4(
        v2_main, pack, "calibration_holdout_r4", out_dir=out,
        prefix="calibration_holdout")

    # 7) C2 诊断 + stress
    print("[calibrate] C2 diagnostics (calibration_r4 + holdout)...")
    c2_diag = run_c2_diagnostics_r4()
    _write_json(out, "c2_local_cue_context_independence.json",
                c2_diag["local_cue_independence"])
    _write_json(out, "c2_context_observability.json",
                c2_diag["context_observability"])
    print("[calibrate] generator stress (stress_r4)...")
    stress = run_generator_stress_r4(pack)
    _write_json(out, "generator_stress_summary.json", stress)

    # 8) 双 robustness gate
    preprocessing_gate = {
        "format": "cur261-r4-preprocessing-robustness-gate-v1",
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
    curriculum_gate = curriculum_robustness_gate_r4(
        calib_main, calib_hold, kappa=ROBUSTNESS_KAPPA_R4,
        stress=stress, c2_diagnostics=c2_diag)
    _write_json(out, "preprocessing_robustness_gate.json",
                preprocessing_gate)
    _write_json(out, "curriculum_robustness_gate.json", curriculum_gate)
    overall = {
        "format": "cur261-r4-robustness-gate-v1",
        "iteration": "r4",
        "preprocessing_gate": {
            "pass": preprocessing_gate["pass"]},
        "curriculum_gate": {"pass": curriculum_gate["pass"]},
        "supervised_gate": {
            "pass": supervised["pass"],
            "note": "representation gate(与 conditioning 一并作为 "
                    "preprocessing 资格证据;§31 PASS 条件)"},
        "pass": bool(preprocessing_gate["pass"]
                     and curriculum_gate["pass"]
                     and supervised["pass"]),
    }
    _write_json(out, "robustness_gate.json", overall)

    # 供 lock-plan 使用的 evidence 摘要
    from rl_curriculum.curriculum261_r4_param_pack import (
        r4_family_rung_params,
    )

    _write_json(out, "calibration_evidence.json", {
        "parameter_pack_digest": pack["digest"],
        "rung_params_by_family": {
            f: r4_family_rung_params(f, pack)
            for f in ("c1_opportunity", "c2_context", "c3_cost")},
        "frozen_parameter_identity": frozen_parameter_identity(),
        "reference_thresholds_by_family": calib_main["thresholds"],
        "bundle_hash_main": v2_main.bundle_hash,
        "bundle_hash_holdout": v2_hold.bundle_hash,
        "conditioning_gate_constants": CONDITIONING_GATE,
        "supervised_gate_constants": SUPERVISED_GATE,
        "kappa": ROBUSTNESS_KAPPA_R4,
    })
    print(f"[calibrate] preprocessing gate = "
          f"{preprocessing_gate['pass']}; curriculum gate = "
          f"{curriculum_gate['pass']}; supervised = "
          f"{supervised['pass']}")
    if not overall["pass"]:
        print("[calibrate] robustness gate FAIL——禁止 lock plan(§25)")
        return 1
    return 0


def _verify_namespace_safe() -> dict:
    try:
        return verify_r4_namespace_isolation()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def cmd_lock_plan(args: argparse.Namespace) -> int:
    out = Path(args.out_dir)
    gate = json.loads((out / "robustness_gate.json").read_text(
        encoding="utf-8"))
    if not gate.get("pass"):
        print("[lock-plan] robustness gate 非 PASS,拒绝 lock")
        return 1
    from rl_curriculum.curriculum261_final import _frozen_contract_integrity
    from rl_curriculum.curriculum261_r4_param_pack import (
        frozen_parameter_identity,
        load_selected_pack,
    )
    from rl_curriculum.curriculum261_r4_plan import (
        build_plan_r4,
        lock_plan_r4,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
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
    design_digest = None
    design_results = out / "r4_parameter_design_results.json"
    if design_results.is_file():
        import hashlib

        design_digest = "r4dr-" + hashlib.sha256(
            design_results.read_bytes()).hexdigest()
    plan = build_plan_r4(
        baseline_commit=BASELINE_COMMIT_R4,
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
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        prior_r3_baseline_commit=PRIOR_R3_BASELINE_COMMIT,
        equivalence_report=eq,
        design_results_digest=design_digest,
    )
    path, digest = lock_plan_r4(plan)
    _write_json(out, "qualification_plan_digest.txt.json",
                {"digest": digest})
    print(f"[lock-plan] locked {path} digest={digest}")
    return 0


def cmd_qualify(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_final import (
        run_final_qualification_r4,
    )

    result = run_final_qualification_r4(Path(args.out_dir))
    print(f"[qualify] verdict={result['verdict']} "
          f"checks={result['n_checks_passed']}/{result['n_checks']}")
    return 0 if result["verdict"] == "PASS" else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_smoke import run_ppo_smoke_r4

    envelope = Path(args.out_dir) / (
        "qualification_preprocessor_state.json")
    result = run_ppo_smoke_r4(
        envelope_path=envelope if envelope.is_file() else None,
        pack=_pack(Path(args.out_dir)))
    _write_json(Path(args.out_dir), "ppo_256step_smoke.json", result)
    print(f"[smoke] pass={result['pass']}")
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="curriculum261-r4",
        description="Stage 2.6.1 Repair R4:正式预处理合同 V2、"
                    "D3 统计功效与重新 Qualification")
    parser.add_argument("--out-dir", default=str(_default_art()),
                        help="artifacts 目录(默认与 lock-marker 目录统一)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("audit", "design", "calibrate", "lock-plan", "qualify",
                 "smoke", "namespace-integrity"):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", default=str(_default_art()))
        if name == "audit":
            p.add_argument("--fit-pairs", type=int, default=2)
        if name == "calibrate":
            p.add_argument("--pairs-per-rung", type=int, default=10)
    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "design":
        return cmd_design(args)
    if args.cmd == "calibrate":
        return cmd_calibrate(args)
    if args.cmd == "lock-plan":
        return cmd_lock_plan(args)
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
