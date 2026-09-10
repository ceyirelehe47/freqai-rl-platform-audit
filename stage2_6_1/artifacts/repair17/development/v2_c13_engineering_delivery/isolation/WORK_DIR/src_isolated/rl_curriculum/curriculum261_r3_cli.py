"""阶段 2.6.1 Repair R3 CLI(WP 串联)。

子命令:
- audit:              WP-A production preprocessing 审计 + 数值等价;
- calibrate:          WP-E/F/G/H 完整 calibration + 双 robustness gate;
- lock-plan:          WP-I plan 构建与锁定(gate 双 PASS 前置);
- qualify:            WP-J 一次性 final qualification(120 pairs);
- smoke:              WP-K 256-step PPO plumbing smoke;
- namespace-integrity:§16 R3 namespace 隔离验证。

§32 技术债修复:CLI output 目录与 lock-marker 目录统一(默认均为
artifacts/route_c_stage2_6_1_repair3 = CURRICULUM261_R3_LOCK_DIR
默认值);默认命令自包含运行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rl_curriculum.curriculum261_r3_namespaces import (
    qualification_r3_lock_dir,
    verify_r3_namespace_isolation,
)

#: 本轮 baseline(Stage 2.6.2 Repair R2 Diagnostics PASS checkpoint)。
BASELINE_COMMIT = "1b47db474461a82b07c6b863894b7f9c4b4dce98"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
PRIOR_R2_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99")
PRIOR_DIAG262R2_PLAN_DIGEST = (
    "dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60")


def _default_art() -> Path:
    return qualification_r3_lock_dir()


def _write_json(out_dir: Path, name: str, payload: object) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")


def cmd_audit(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
        generate_fit_bank,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        numerical_equivalence_report,
        preprocessing_contract_digest,
        production_preprocessing_audit,
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
    _write_json(out, "preprocessing_contract.json", {
        "digest": preprocessing_contract_digest(),
        "audit_format": audit["format"],
    })
    records = generate_fit_bank(
        "preprocess_fit_calibration_r3", args.fit_pairs)
    fit_df = fit_matrix_from_records(records)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", eq)
    print(f"[audit] equivalence pass={eq['pass']} "
          f"state_hash={eq['state_hash']}")
    return 0 if eq["pass"] else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_api import CURRICULUM261_FAMILIES
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r3_calibration import (
        CALIBRATION_PAIRS_PER_RUNG,
        CONDITIONING_GATE,
        FIT_BANK_PAIRS_PER_RUNG,
        ROBUSTNESS_KAPPA_R3,
        SUPERVISED_GATE,
        conditioning_profile,
        curriculum_robustness_gate_r3,
        fit_preprocessor_from_bank,
        generate_fit_bank,
        preprocessing_robustness_checks,
        run_c2_diagnostics_r3,
        run_calibration_corpus_r3,
        run_generator_stress_r3,
        supervised_learnability_run,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        numerical_equivalence_report,
    )

    out = Path(args.out_dir)
    specs = family_specs()

    # 1) namespace integrity
    ns = verify_r3_namespace_isegrity_safe()
    _write_json(out, "seed_namespace_integrity.json", ns)

    # 2) fit banks(main + holdout)与统一 preprocessor
    print("[calibrate] fitting main preprocessor "
          "(preprocess_fit_calibration_r3)...")
    pre_main, manifest_main = fit_preprocessor_from_bank(
        "preprocess_fit_calibration_r3", FIT_BANK_PAIRS_PER_RUNG)
    print("[calibrate] fitting holdout preprocessor "
          "(preprocess_fit_holdout_r3)...")
    pre_hold, manifest_hold = fit_preprocessor_from_bank(
        "preprocess_fit_holdout_r3", FIT_BANK_PAIRS_PER_RUNG)
    _write_json(out, "preprocessing_state_schema_identity.json",
                pre_main.identity())
    _write_json(out, "fit_eval_isolation.json", {
        "main": manifest_main, "holdout": manifest_hold,
        "eval_namespaces": ["calibration_r3", "calibration_holdout_r3"],
        "fit_bank_used_for_metrics": False,
        "protocol": "offline training-corpus fit -> frozen transform;"
                    "fit bank 只用于拟合 preprocessor",
    })

    # 3) production 数值等价(main fit bank 对拍)
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
    )

    fit_df = fit_matrix_from_records(generate_fit_bank(
        manifest_main["namespace"], FIT_BANK_PAIRS_PER_RUNG))
    half = len(fit_df) // 2
    equivalence = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", equivalence)

    # 4) preprocessing robustness(eval records 用 calibration_r3 语料:
    #    每 family x rung 各 1 pair,兼作 reference 等价检查集)
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS

    eval_records = [
        generate_pair(f, r, 0, namespace="calibration_r3")
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    equiv_records = eval_records
    prep_rob = preprocessing_robustness_checks(
        pre_main, manifest_main, pre_hold, manifest_hold,
        eval_records, equiv_records)
    _write_json(out, "preprocessing_robustness_checks.json", prep_rob)

    # 5) conditioning profile(fit=main fit bank;eval=calibration_r3)
    cond = conditioning_profile(pre_main, generate_fit_bank(
        manifest_main["namespace"], FIT_BANK_PAIRS_PER_RUNG),
        eval_records)
    _write_json(out, "conditioning_profile.json", cond)
    _write_json(out, "activation_profile.json", {
        "tanh_saturation_scaled": cond["checks"][
            "tanh_saturation_scaled"],
        "tanh_saturation_unscaled": cond["checks"][
            "tanh_saturation_unscaled"],
        "raw_ohlc_share_scaled": cond["checks"][
            "raw_ohlc_share_scaled"],
        "raw_ohlc_share_unscaled": cond["checks"][
            "raw_ohlc_share_unscaled"],
    })

    # 6) supervised learnability
    print("[calibrate] supervised learnability (3 families x 3 seeds)...")
    supervised = supervised_learnability_run(pre_main)
    _write_json(out, "supervised_learnability.json", supervised)

    # 7) curriculum calibration(main + holdout)
    print("[calibrate] curriculum calibration_r3...")
    calib_main = run_calibration_corpus_r3(
        pre_main, "calibration_r3", out_dir=out, prefix="calibration")
    print("[calibrate] curriculum calibration_holdout_r3...")
    calib_hold = run_calibration_corpus_r3(
        pre_main, "calibration_holdout_r3", out_dir=out,
        prefix="calibration_holdout")

    # 8) C2 诊断 + stress
    print("[calibrate] C2 diagnostics (calibration_r3 + holdout)...")
    c2_diag = run_c2_diagnostics_r3()
    _write_json(out, "c2_local_cue_context_independence.json",
                c2_diag["local_cue_independence"])
    _write_json(out, "c2_context_observability.json",
                c2_diag["context_observability"])
    print("[calibrate] generator stress (stress_r3)...")
    stress = run_generator_stress_r3()
    _write_json(out, "generator_stress_summary.json", stress)

    # 9) 双 robustness gate
    preprocessing_gate = {
        "format": "cur261-r3-preprocessing-robustness-gate-v1",
        "equivalence_pass": bool(equivalence["pass"]),
        "robustness_checks_pass": bool(prep_rob["pass"]),
        "conditioning_pass": bool(cond["pass"]),
        "state_hash_main": pre_main.state_hash(),
        "state_hash_holdout": pre_hold.state_hash(),
        "pass": bool(equivalence["pass"] and prep_rob["pass"]
                     and cond["pass"]),
    }
    curriculum_gate = curriculum_robustness_gate_r3(
        calib_main, calib_hold, kappa=ROBUSTNESS_KAPPA_R3,
        stress=stress, c2_diagnostics=c2_diag)
    _write_json(out, "preprocessing_robustness_gate.json",
                preprocessing_gate)
    _write_json(out, "curriculum_robustness_gate.json", curriculum_gate)
    overall = {
        "format": "cur261-r3-robustness-gate-v1",
        "iteration": "r3",
        "preprocessing_gate": {
            "pass": preprocessing_gate["pass"]},
        "curriculum_gate": {"pass": curriculum_gate["pass"]},
        "supervised_gate": {
            "pass": supervised["pass"],
            "note": "representation gate(与 conditioning 一并作为 "
                    "preprocessing 资格证据;§30 PASS 条件)"},
        "pass": bool(preprocessing_gate["pass"]
                     and curriculum_gate["pass"]
                     and supervised["pass"]),
    }
    _write_json(out, "robustness_gate.json", overall)

    # 供 lock-plan 使用的 evidence 摘要
    _write_json(out, "calibration_evidence.json", {
        "preprocessing_state_hash_main": pre_main.state_hash(),
        "preprocessing_state_hash_holdout": pre_hold.state_hash(),
        "rung_params_by_family": {
            f: dict(specs[f].rung_params) for f in CURRICULUM261_FAMILIES},
        "reference_thresholds_by_family": {
            f: dict(specs[f].reference_defaults)
            for f in CURRICULUM261_FAMILIES},
        "conditioning_gate_constants": CONDITIONING_GATE,
        "supervised_gate_constants": SUPERVISED_GATE,
        "kappa": ROBUSTNESS_KAPPA_R3,
    })
    print(f"[calibrate] preprocessing gate = "
          f"{preprocessing_gate['pass']}; curriculum gate = "
          f"{curriculum_gate['pass']}; supervised = "
          f"{supervised['pass']}")
    if not overall["pass"]:
        print("[calibrate] robustness gate FAIL——禁止 lock plan(§22)")
        return 1
    return 0


def verify_r3_namespace_isegrity_safe() -> dict:
    try:
        return verify_r3_namespace_isolation()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def cmd_lock_plan(args: argparse.Namespace) -> int:
    out = Path(args.out_dir)
    gate = json.loads((out / "robustness_gate.json").read_text(
        encoding="utf-8"))
    if not gate.get("pass"):
        print("[lock-plan] robustness gate 非 PASS,拒绝 lock")
        return 1
    from rl_curriculum.curriculum261_r3_calibration import (
        CONDITIONING_GATE,
        SUPERVISED_GATE,
    )
    from rl_curriculum.curriculum261_r3_plan import (
        build_plan_r3,
        lock_plan_r3,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        preprocessing_contract_digest,
    )
    from rl_curriculum.curriculum261_final import _frozen_contract_integrity
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
    frozen = _frozen_contract_integrity()
    if not frozen["pass"]:
        print("[lock-plan] 冻结合同完整性 FAIL,拒绝 lock")
        return 1
    plan = build_plan_r3(
        baseline_commit=BASELINE_COMMIT,
        vendor_pin=VENDOR_PIN,
        frozen_contracts={
            "env_core": ENV_CORE_VERSION,
            "observation_spec": OBSERVATION_SPEC_VERSION,
            "action_spec": ACTION_SPEC_VERSION,
            "reward_spec": REWARD_SPEC_VERSION,
            "execution": EXECUTION_CONTRACT_VERSION,
            "terminal_liquidation": TERMINAL_LIQUIDATION_VERSION,
        },
        preprocessing_contract_digest=preprocessing_contract_digest(),
        calibration_state_hash=evidence[
            "preprocessing_state_hash_main"],
        holdout_state_hash=evidence[
            "preprocessing_state_hash_holdout"],
        preprocessing_robustness_gate=prep_gate,
        curriculum_robustness_gate=cur_gate,
        conditioning_gate_constants=CONDITIONING_GATE,
        supervised_gate_constants=SUPERVISED_GATE,
        kappa=evidence["kappa"],
        rung_params_by_family=evidence["rung_params_by_family"],
        reference_thresholds_by_family=evidence[
            "reference_thresholds_by_family"],
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        equivalence_report=eq,
    )
    path, digest = lock_plan_r3(plan)
    _write_json(Path(args.out_dir), "qualification_plan_digest.txt.json",
                {"digest": digest})
    print(f"[lock-plan] locked {path} digest={digest}")
    return 0


def cmd_qualify(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r3_final import (
        run_final_qualification_r3,
    )

    result = run_final_qualification_r3(Path(args.out_dir))
    print(f"[qualify] verdict={result['verdict']} "
          f"checks={result['n_checks_passed']}/{result['n_checks']}")
    return 0 if result["verdict"] == "PASS" else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r3_smoke import run_ppo_smoke_r3

    state_path = Path(args.out_dir) / (
        "qualification_preprocessor_state.json")
    result = run_ppo_smoke_r3(
        state_path=state_path if state_path.is_file() else None)
    _write_json(Path(args.out_dir), "ppo_256step_smoke.json", result)
    print(f"[smoke] pass={result['pass']}")
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="curriculum261-r3",
        description="Stage 2.6.1 Repair R3:production preprocessing "
                    "合同与课程重新 qualification")
    parser.add_argument("--out-dir", default=str(_default_art()),
                        help="artifacts 目录(默认与 lock-marker 目录统一)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("audit", "calibrate", "lock-plan", "qualify",
                 "smoke", "namespace-integrity"):
        p = sub.add_parser(name)
        p.add_argument("--out-dir", default=str(_default_art()))
        if name == "audit":
            p.add_argument("--fit-pairs", type=int, default=2)
        if name == "calibrate":
            p.add_argument("--pairs-per-rung", type=int,
                           default=CALIBRATION_PAIRS_PER_RUNG_DEFAULT)
    args = parser.parse_args(argv)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "calibrate":
        return cmd_calibrate(args)
    if args.cmd == "lock-plan":
        return cmd_lock_plan(args)
    if args.cmd == "qualify":
        return cmd_qualify(args)
    if args.cmd == "smoke":
        return cmd_smoke(args)
    if args.cmd == "namespace-integrity":
        rep = verify_r3_namespace_isegrity_safe()
        _write_json(Path(args.out_dir), "seed_namespace_integrity.json",
                    rep)
        print(f"[namespace-integrity] pass={rep['pass']}")
        return 0 if rep["pass"] else 1
    return 2


CALIBRATION_PAIRS_PER_RUNG_DEFAULT = 10


if __name__ == "__main__":
    sys.exit(main())
