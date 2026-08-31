"""阶段 2.6.1 Repair R4:calibration、supervised gate 与双层
robustness gate(preprocessing V2 + 统一 pair 统计)。

结构沿 R3(curriculum261_r3_calibration),差异:
- fit bank 生成经 R4 parameter pack 的 D3 override(C1/C3);
- preprocessor 为 V2(三层 identity:parameter state / fit manifest
  multiset / bundle);
- 课程统计全部来自唯一 pair 证据表(curriculum261_r4_pairs);
- 难度 = reference_pair − always_flat_pair;required baseline margin
  逐基线(无 hindsight);
- preprocessing robustness 检查扩展 V2 合同面(unbounded outer
  observation space、bundle verification、不同 multiset 不同 bundle、
  adversarial out-of-range probe 等)。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_pairs import (
    PairRecord,
    generate_pair,
    family_specs,
)
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
)
from rl_curriculum.curriculum261_r3_calibration import (
    CONDITIONING_GATE,
    FIT_BANK_PAIRS_PER_RUNG,
    SUPERVISED_GATE,
    SUPERVISED_MODEL_SEEDS,
    _binary_metrics,
    conditioning_profile,
    fit_matrix_from_records,
)
from rl_curriculum.curriculum261_r3_obs import (
    reference_equivalence_check,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
    numerical_equivalence_report,
)
from rl_curriculum.curriculum261_r4_namespaces import (
    CURRICULUM261_ITERATION_ID_R4,
)
from rl_curriculum.curriculum261_r4_param_pack import (
    r4_override_for,
)
from rl_curriculum.curriculum261_r4_pairs import (
    CALIBRATION_PAIRS_PER_RUNG_R4,
    EVAL_CFG,
    RAW_SCHEMA,
    ROBUSTNESS_KAPPA_R4,
    curriculum_robustness_gate_r4,
    difficulty_metric_validation,
    rung_report_r4,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    FitManifestEntry,
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    build_fit_manifest_entries,
    fit_manifest_multiset_hash,
    validate_observation_space_v2,
)
from rl_curriculum.curriculum261_qualification import (
    check_c2_context_observability,
    check_c2_local_cue_independence,
)
from rl_curriculum.evaluator import run_policy_episode


# ------------------------------------------------------------ fit bank
def generate_fit_bank_r4(
        namespace: str, pack: dict[str, Any],
        pairs_per_rung: int = FIT_BANK_PAIRS_PER_RUNG,
) -> list[PairRecord]:
    """生成一个 R4 preprocessing fit bank(D3 override 生效)。"""
    records: list[PairRecord] = []
    for family in CURRICULUM261_FAMILIES:
        override = r4_override_for(family, pack)
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
    return records


def fit_preprocessor_v2_from_bank(
        namespace: str, pack: dict[str, Any],
        records: list[PairRecord] | None = None,
        pairs_per_rung: int = FIT_BANK_PAIRS_PER_RUNG,
        parameter_pack_identity: str | None = None,
) -> tuple[RouteCPreprocessorV2, dict[str, Any]]:
    """fit bank -> manifest -> 统一 fit -> V2(三层 identity)。"""
    if records is None:
        records = generate_fit_bank_r4(namespace, pack, pairs_per_rung)
    identity = parameter_pack_identity or pack.get("digest", "no-pack")
    entries = build_fit_manifest_entries(records, namespace, identity)
    fit_df = fit_matrix_from_records(records)
    inner = RouteCPreprocessor.build_and_fit(fit_df)
    v2 = RouteCPreprocessorV2(inner, entries, namespace)
    manifest = {
        "namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "n_pairs": len(records),
        "n_episodes": 2 * len(records),
        "n_rows": int(len(fit_df)),
        "columns": list(PRODUCTION_FEATURE_COLUMNS),
        "integrity_all_ok": bool(all(r.integrity_ok for r in records)),
        "multiset_hash": v2.manifest_multiset_hash,
        "document": v2.manifest_document(),
    }
    return v2, manifest


# ---------------------------------------------------- calibration corpus
def run_calibration_corpus_r4(
        preproc_v2: RouteCPreprocessorV2, pack: dict[str, Any],
        namespace: str,
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R4,
        out_dir: Path | None = None, prefix: str = "calibration",
) -> dict[str, Any]:
    """R4 calibration 语料(calibration_r4 / calibration_holdout_r4)。"""
    from rl_curriculum.curriculum261_r4_param_pack import (
        r4_family_rung_params,
    )

    specs = family_specs()
    thresholds = {
        f: dict(specs[f].reference_defaults) for f in CURRICULUM261_FAMILIES}
    family_reports: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        override = r4_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
        rung_params = r4_family_rung_params(family, pack)
        family_reports[family] = rung_report_r4(
            records, family, rung_params, thresholds[family], preproc_v2,
            corpus=namespace)
    summary = {
        "format": "cur261-r4-calibration-summary-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "stage": prefix,
        "seed_namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "parameter_pack_digest": pack.get("digest"),
        "preprocessing_parameter_state_hash": preproc_v2.parameter_state_hash,
        "preprocessing_bundle_hash": preproc_v2.bundle_hash,
        "thresholds": thresholds,
        "difficulty_metric": "reference_pair - always_flat_pair",
        "families": family_reports,
    }
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{prefix}_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        (out_dir / f"pair_evidence_table_{prefix}.json").write_text(
            json.dumps({
                "schema_identity": family_reports[
                    CURRICULUM261_FAMILIES[0]]["pair_table"][
                    "schema_identity"],
                "tables": {f: family_reports[f]["pair_table"]
                           for f in CURRICULUM261_FAMILIES},
            }, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        (out_dir / "difficulty_metric_validation.json").write_text(
            json.dumps({f: difficulty_metric_validation(
                family_reports[f]["pair_table"], f)
                for f in CURRICULUM261_FAMILIES}, indent=2,
                ensure_ascii=False, default=float), encoding="utf-8")
    return summary


# ------------------------------------------------ supervised learnability
def _collect_supervised_dataset_r4(
        records: list[PairRecord], family: str,
        rung_params_by_rung: dict[str, dict[str, Any]],
        preproc_v2: RouteCPreprocessorV2,
) -> list[dict[str, Any]]:
    """scaled obs + reference action(R4 rung 参数,含 D3 override)。"""
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
    from rl_curriculum.curriculum261_qualification import build_policy_set

    thresholds = dict(family_specs()[family].reference_defaults)
    schema = r4_observation_schema(preproc_v2)
    from rl_curriculum.curriculum261_r3_obs import scaled_episode

    rows: list[dict[str, Any]] = []
    for rec in records:
        rung_params = dict(rung_params_by_rung[rec.rung])
        rung_params["cur261_rung"] = rec.rung
        raw_set = build_policy_set(family, rung_params, thresholds)
        ref = raw_set["reference"]
        for side in ("A", "B"):
            ep = rec.episodes[side]
            scaled_ep = scaled_episode(ep, preproc_v2.inner)
            r = run_policy_episode(
                ref, scaled_ep, EVAL_CFG, schema,
                return_observations=True)
            obs_list, actions = r[2], r[1]
            for o, a in zip(obs_list, actions):
                rows.append({
                    "family": family, "rung": rec.rung,
                    "pair": rec.pair_index, "side": side,
                    "obs": np.asarray(o, dtype=np.float32),
                    "action": int(a),
                })
    return rows


def supervised_learnability_run_r4(
        preproc_v2: RouteCPreprocessorV2, pack: dict[str, Any],
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R4,
        namespace: str = "calibration_r4",
        train_pair_limit: int = 6,
) -> dict[str, Any]:
    """§23 supervised learnability gate(与 R3 同阈值/seed/控制)。"""
    from rl_curriculum.ppo262_r2_supervised import train_supervised_mlp
    from rl_curriculum.curriculum261_r4_param_pack import (
        r4_family_rung_params,
    )

    out: dict[str, Any] = {
        "format": "cur261-r4-supervised-learnability-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "namespace": namespace,
        "gate_constants": SUPERVISED_GATE,
        "model_seeds": list(SUPERVISED_MODEL_SEEDS),
        "families": {},
    }
    overall = True
    for family in CURRICULUM261_FAMILIES:
        override = r4_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
        rung_params = r4_family_rung_params(family, pack)
        rows = _collect_supervised_dataset_r4(
            records, family, rung_params, preproc_v2)
        train_rows = [r for r in rows if r["pair"] < train_pair_limit]
        test_rows = [r for r in rows if r["pair"] >= train_pair_limit]
        Xtr = np.stack([r["obs"] for r in train_rows]).astype(np.float32)
        ytr = np.asarray([r["action"] for r in train_rows], dtype=np.int64)
        Xte = np.stack([r["obs"] for r in test_rows]).astype(np.float32)
        yte = np.asarray([r["action"] for r in test_rows], dtype=np.int64)
        test_pairs = sorted({(r["rung"], r["pair"]) for r in test_rows})

        controls = ["U", "W", "B"]
        gated_controls = ["W", "B"]
        seed_reports: list[dict[str, Any]] = []
        n_passing = 0
        for seed in SUPERVISED_MODEL_SEEDS:
            for control in controls:
                trained = train_supervised_mlp(
                    Xtr, ytr, control=control, seed=seed)
                net = trained["net"]
                import torch

                with torch.no_grad():
                    logits = net(torch.as_tensor(Xte))
                    p_long = torch.softmax(logits, dim=-1)[:, 1].numpy()
                metrics = _binary_metrics(yte, p_long)
                pair_accs = []
                for rung, pid in test_pairs:
                    sel = np.asarray([
                        (r["rung"], r["pair"]) == (rung, pid)
                        for r in test_rows])
                    if sel.sum() > 0 and len(set(yte[sel].tolist())) > 1:
                        pair_accs.append(_binary_metrics(
                            yte[sel], p_long[sel])["balanced_accuracy"])
                metrics["heldout_pair_balanced_accuracy_min"] = (
                    float(np.min(pair_accs)) if pair_accs else None)
                metrics["heldout_pair_balanced_accuracy_mean"] = (
                    float(np.mean(pair_accs)) if pair_accs else None)
                gated = bool(
                    metrics["balanced_accuracy"]
                    >= SUPERVISED_GATE["heldout_balanced_accuracy_min"]
                    and metrics["behavior_gap"]
                    >= SUPERVISED_GATE["behavior_gap_min"])
                if control in gated_controls:
                    n_passing += int(gated)
                seed_reports.append({
                    "seed": int(seed), "control": control,
                    "gated": gated, "metrics": metrics,
                })
        family_pass = bool(
            n_passing >= SUPERVISED_GATE["min_seeds_passing"])
        overall = overall and family_pass
        out["families"][family] = {
            "n_train_rows": int(len(train_rows)),
            "n_test_rows": int(len(test_rows)),
            "train_long_rate": float(ytr.mean()),
            "test_long_rate": float(yte.mean()),
            "controls": controls,
            "gated_controls": gated_controls,
            "n_gated_runs_passing": n_passing,
            "min_seeds_passing": SUPERVISED_GATE["min_seeds_passing"],
            "runs": seed_reports,
            "pass": family_pass,
        }
    out["pass"] = bool(overall)
    return out


# --------------------------------------------- preprocessing robustness
def preprocessing_robustness_checks_r4(
        v2_main: RouteCPreprocessorV2,
        v2_holdout: RouteCPreprocessorV2,
        records_main: list[PairRecord],
        records_holdout: list[PairRecord],
        eval_records: list[PairRecord],
        equivalence_records: list[PairRecord],
        pack: dict[str, Any],
) -> dict[str, Any]:
    """§22 V2 preprocessing robustness 全电池。"""
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
    )
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema

    checks: dict[str, Any] = {}
    inner = v2_main.inner

    # 8/8 存活 + 列序 + fit bank integrity
    checks["survival_main"] = bool(
        v2_main.retained_columns == list(PRODUCTION_FEATURE_COLUMNS))
    checks["survival_holdout"] = bool(
        v2_holdout.retained_columns == list(PRODUCTION_FEATURE_COLUMNS))
    checks["fit_bank_integrity"] = bool(
        all(r.integrity_ok for r in records_main)
        and all(r.integrity_ok for r in records_holdout))

    # production 数值等价(fit bank 对拍 vendor pipeline)
    fit_df = fit_matrix_from_records(records_main)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(fit_df.iloc[:half],
                                      fit_df.iloc[half:])
    checks["production_numerical_equivalence"] = bool(eq["pass"])

    # V2 envelope 序列化/重载:identity 不变 + transform 逐位
    with tempfile.TemporaryDirectory() as td:
        epath = Path(td) / "envelope.json"
        v2_main.serialize_envelope(epath)
        reloaded = RouteCPreprocessorV2.load_envelope(epath)
        sample = fit_matrix_from_records(eval_records[:4])
        t1 = v2_main.transform(sample)
        t2 = reloaded.transform(sample)
        checks["envelope_reload_bundle_identity_stable"] = bool(
            reloaded.bundle_hash == v2_main.bundle_hash)
        checks["envelope_reload_transform_bitwise_equal"] = bool(
            np.array_equal(t1.to_numpy(), t2.to_numpy()))
        # 篡改检测:manifest entry 篡改 / 参数篡改
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

    # staged/mixed:行序不变 -> 同 param hash + 同 bundle(manifest 不变)
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

    # manifest 行序不变 -> 同 multiset hash
    shuffled_entries = list(v2_main.entries)
    rng2 = np.random.default_rng(27182)
    order = rng2.permutation(len(shuffled_entries))
    checks["manifest_order_invariant_multiset_hash"] = bool(
        fit_manifest_multiset_hash(
            [shuffled_entries[i] for i in order])
        == v2_main.manifest_multiset_hash)

    # 不同 multiset、同 scaler 参数 -> 不同 bundle(重复一个 episode:
    # min/max 不变 -> param hash 不变;multiset 改变)
    dup_records = list(records_main) + [records_main[0]]
    v2_dup = fit_preprocessor_v2_from_bank(
        v2_main.namespace, pack, records=dup_records,
        parameter_pack_identity=pack.get("digest"))[0]
    checks["different_multiset_same_params_same_param_hash"] = bool(
        v2_dup.parameter_state_hash == v2_main.parameter_state_hash)
    checks["different_multiset_different_bundle"] = bool(
        v2_dup.bundle_hash != v2_main.bundle_hash)

    # V2 observation space 合同:校准语料 containment + 对抗探针
    scaled_dfs = [v2_main.transform_episode_df(
        rec.episodes[s].df) for rec in eval_records[:8]
        for s in ("A", "B")]
    space_validation = validate_observation_space_v2(
        scaled_dfs, scaled_dfs, EVAL_CFG,
        [int(rec.episodes[s].spec.seed) for rec in eval_records[:8]
         for s in ("A", "B")],
        context="preprocessing_robustness_v2")
    checks["observation_space_v2"] = space_validation
    adversarial = adversarial_out_of_range_probe(v2_main, EVAL_CFG)
    checks["adversarial_out_of_range_probe"] = adversarial

    # no NaN / Inf
    checks["no_nan_inf"] = bool(all(
        np.isfinite(sdf[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy()
                    ).all() for sdf in scaled_dfs))

    # position identity(fit 输入 8 列;输出 8 列;第 9 维 env 追加)
    state = inner.fitted_state()
    checks["position_identity"] = bool(
        len(state["input_columns"]) == 8
        and len(state["retained_columns"]) == 8
        and state["position_slot"]["participates_in_fit"] is False
        and state["position_slot"]["scaled"] is False)

    # bundle 自校验 + fit manifest provenance 完整性
    checks["bundle_verification_main"] = v2_main.verify()
    checks["bundle_verification_holdout"] = v2_holdout.verify()
    n_expected = 2 * len(records_main)
    checks["fit_manifest_provenance_complete"] = bool(
        len(v2_main.entries) == n_expected
        and all(e.episode_hash and e.feature_matrix_hash
                and e.generator_identity for e in v2_main.entries))

    # 双 fit state 分布稳定性
    sample_t_main = v2_main.transform(sample).to_numpy()
    sample_t_hold = v2_holdout.transform(sample).to_numpy()
    checks["dual_fit_transform_max_abs_diff"] = float(np.max(np.abs(
        sample_t_main - sample_t_hold)))
    checks["state_hashes_distinct"] = bool(
        v2_main.parameter_state_hash
        != v2_holdout.parameter_state_hash)

    # reference 等价(§21:每 family x rung x 多 pair x A/B)
    specs = family_specs()
    thresholds = {
        f: dict(specs[f].reference_defaults) for f in CURRICULUM261_FAMILIES}
    from rl_curriculum.curriculum261_r4_param_pack import (
        r4_family_rung_params,
    )

    eq_reports = []
    for rec in equivalence_records:
        rung_params = r4_family_rung_params(rec.family, pack)[rec.rung]
        rung_params["cur261_rung"] = rec.rung
        for side in ("A", "B"):
            eq_reports.append(reference_equivalence_check(
                rec.episodes[side], rec.family, rung_params,
                thresholds[rec.family], v2_main.inner, EVAL_CFG,
                RAW_SCHEMA))
    checks["reference_equivalence_all"] = bool(
        all(e["pass"] for e in eq_reports))
    checks["reference_equivalence_n_episodes"] = len(eq_reports)

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
        and checks["reference_equivalence_all"])
    return {
        "format": "cur261-r4-preprocessing-robustness-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "checks": checks,
        "equivalence_report": eq,
        "pass": core_ok,
    }


# ------------------------------------------------------ stress / C2 diag
def run_generator_stress_r4(pack: dict[str, Any], pairs_per_rung: int = 12,
                            namespace: str = "stress_r4",
                            ) -> dict[str, Any]:
    """R4 generator stress(stress_r4;D3 override 生效)。"""
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        override = r4_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
        n_ok = sum(1 for r in records if r.integrity_ok)
        families_out[family] = {
            "namespace": namespace,
            "pairs_per_rung": pairs_per_rung,
            "n_pairs": len(records),
            "n_integrity_ok": n_ok,
            "integrity_pass_ratio": n_ok / len(records),
            "accepted_implies_integrity": bool(n_ok == len(records)),
        }
    return {
        "format": "cur261-r4-generator-stress-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "namespace": namespace,
        "families": families_out,
        "pass": bool(all(
            v["accepted_implies_integrity"] for v in families_out.values())),
    }


def run_c2_diagnostics_r4(pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R4,
                          ) -> dict[str, Any]:
    """R4 C2 双诊断(calibration_r4 + calibration_holdout_r4 语料;
    C2 参数无 override,与 R3 同参数)。"""
    records: list[PairRecord] = []
    for ns in ("calibration_r4", "calibration_holdout_r4"):
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    "c2_context", rung, idx, namespace=ns))
    lc = check_c2_local_cue_independence(records)
    ob = check_c2_context_observability(records)
    return {"local_cue_independence": lc, "context_observability": ob}
