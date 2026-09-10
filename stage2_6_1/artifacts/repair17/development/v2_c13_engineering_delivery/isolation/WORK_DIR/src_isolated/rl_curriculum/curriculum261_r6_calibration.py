# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6:calibration(strict 双 corpus)、C2 matched
block 语料、独立-rung marginal guard、supervised gate、preprocessing
V2 重新资格电池、stress 与 C2 三语义诊断(§27-§28)。

结构沿 R5(curriculum261_r5_calibration),差异:
- C1/C3:pair 语料(10 pairs/rung,R4/R5 口径)经 R6 pack 的 override
  (D3 继承 R4);
- C2:**matched block 语料**(calibration_r6 / calibration_holdout_r6 下
  selected_block_count 个 block,block 统计口径)+ **独立-rung 语料**
  (c2_independent_calibration_r6 / c2_independent_holdout_r6,20
  pairs/rung,marginal guard);
- C2 语义诊断为三项(local cue independence / context observability /
  cue-payoff separation,§18);
- V2 数值实现逐位复用 R4(vendor pipeline 不动),R6 全新语料重新验证。
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
from rl_curriculum.curriculum261_c2 import FAMILY_C2
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
from rl_curriculum.curriculum261_r4_preprocessing import (
    FitManifestEntry,
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    build_fit_manifest_entries,
    fit_manifest_multiset_hash,
    validate_observation_space_v2,
)
from rl_curriculum.curriculum261_r4_pairs import (
    EVAL_CFG,
    RAW_SCHEMA,
    evaluate_pair_corpus_r4,
    rung_report_r4,
)
from rl_curriculum.curriculum261_r5_pairs import (
    CALIBRATION_PAIRS_PER_RUNG_R5,
    c2_density_summary,
    density_gate_r5,
    difficulty_metric_validation,
)
from rl_curriculum.curriculum261_r6_namespaces import (
    CURRICULUM261_ITERATION_ID_R6,
)
from rl_curriculum.curriculum261_r6_param_pack import (
    r6_family_rung_params,
    r6_override_for,
)
from rl_curriculum.curriculum261_r6_pairs import (
    ROBUSTNESS_KAPPA_R6,
    build_c2_block_evidence_table,
    c2_matched_conditions,
    c2_marginal_guard_conditions,
    check_c2_cue_payoff_separation,
)
from rl_curriculum.curriculum261_r6_tape import (
    block_attempt_statistics,
    generate_matched_block_with_attempts,
    matched_block_corpus_summary,
)
from rl_curriculum.curriculum261_qualification import (
    REQUIRED_BASELINES,
    check_c2_context_observability,
    check_c2_local_cue_independence,
)
from rl_curriculum.evaluator import run_policy_episode

#: 独立-rung marginal guard 语料规模(§16 建议;calibration/holdout 沿用)。
C2_INDEPENDENT_PAIRS_PER_RUNG_R6 = 20


# ------------------------------------------------------------ fit bank
def generate_fit_bank_r6(
        namespace: str, pack: dict[str, Any],
        pairs_per_rung: int = FIT_BANK_PAIRS_PER_RUNG,
) -> list[PairRecord]:
    """生成一个 R6 preprocessing fit bank(pack override 生效)。"""
    records: list[PairRecord] = []
    for family in CURRICULUM261_FAMILIES:
        override = r6_override_for(family, pack)
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
    return records


def fit_preprocessor_v2_from_bank_r6(
        namespace: str, pack: dict[str, Any],
        records: list[PairRecord] | None = None,
        pairs_per_rung: int = FIT_BANK_PAIRS_PER_RUNG,
        parameter_pack_identity: str | None = None,
) -> tuple[RouteCPreprocessorV2, dict[str, Any]]:
    """R6 fit bank -> manifest -> 统一 fit -> V2(三层 identity)。"""
    if records is None:
        records = generate_fit_bank_r6(namespace, pack, pairs_per_rung)
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


# ---------------------------------------------------- C1/C3 calibration
def run_calibration_corpus_c13_r6(
        preproc_v2: RouteCPreprocessorV2, pack: dict[str, Any],
        namespace: str,
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R5,
) -> dict[str, Any]:
    """C1/C3 calibration 语料(pair 口径,R4/R5 统计实现同源)。"""
    specs = family_specs()
    family_reports: dict[str, Any] = {}
    for family in ("c1_opportunity", "c3_cost"):
        thresholds = dict(specs[family].reference_defaults)
        override = r6_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
        rung_params = r6_family_rung_params(family, pack)
        family_reports[family] = rung_report_r4(
            records, family, rung_params, thresholds, preproc_v2,
            corpus=namespace)
    return {
        "seed_namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "families": family_reports,
    }


# ---------------------------------------------------- C2 matched calibration
def run_c2_matched_corpus_r6(
        preproc_v2: RouteCPreprocessorV2 | None, pack: dict[str, Any],
        namespace: str, n_blocks: int,
) -> dict[str, Any]:
    """C2 matched block 语料(selected_block_count 个 block)。

    preproc_v2=None -> raw(design 语义);否则 scaled(calibration/
    holdout/final)。评估走 evaluate_pair_corpus_r4 唯一实现,统计从
    唯一 block 表派生。
    """
    ladder = r6_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace=namespace, block_index=i)
        for i in range(int(n_blocks))]
    records = [blk.pair_records[rung]
               for blk in blocks for rung in CURRICULUM261_RUNGS]
    ev = evaluate_pair_corpus_r4(
        records, FAMILY_C2, ladder, thresholds,
        preproc=preproc_v2, corpus=namespace)
    block_table = build_c2_block_evidence_table(
        ev["pair_table"], blocks, namespace)
    return {
        "seed_namespace": namespace,
        "n_blocks": int(n_blocks),
        "block_corpus_summary": matched_block_corpus_summary(blocks),
        "block_attempt_stats": block_attempt_statistics(blocks),
        "block_table": block_table,
        "pair_table": ev["pair_table"],
        "episodes": ev["episodes"],
        "matched_conditions": c2_matched_conditions(block_table),
        "blocks": blocks,
    }


def run_c2_independent_corpus_r6(
        preproc_v2: RouteCPreprocessorV2 | None, pack: dict[str, Any],
        namespace: str,
        pairs_per_rung: int = C2_INDEPENDENT_PAIRS_PER_RUNG_R6,
) -> dict[str, Any]:
    """C2 独立-rung marginal guard 语料(普通独立生成;§16/§28)。"""
    ladder = r6_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    records: list[PairRecord] = []
    for rung in CURRICULUM261_RUNGS:
        for idx in range(pairs_per_rung):
            records.append(generate_pair(
                FAMILY_C2, rung, idx, namespace=namespace,
                rung_params_override=r6_override_for(FAMILY_C2, pack)))
    report = rung_report_r4(
        records, FAMILY_C2, ladder, thresholds, preproc_v2,
        corpus=namespace)
    return {
        "seed_namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "report": report,
        "records": records,
    }


def c2_independent_marginal_guard_r6(
        indep: dict[str, Any], pack: dict[str, Any],
) -> dict[str, Any]:
    """独立语料 -> 密度 + 三语义 -> marginal guard 条件(§16)。"""
    ladder = r6_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    report = indep["report"]
    density_gates: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        d = c2_density_summary(
            [row for row in report["by_rung"][r]["episodes"]
             if row["rung"] == r], r)
        d["reference_long_label_rate"] = _reference_long_label_rate_r6(
            [rec for rec in indep["records"] if rec.rung == r],
            ladder[r], thresholds)
        density_gates[r] = density_gate_r5(d)
    records = indep["records"]
    semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
        "cue_payoff_separation": check_c2_cue_payoff_separation(
            records),
    }
    guard = c2_marginal_guard_conditions(
        report,
        density={"pass": all(d["pass"] for d in density_gates.values())},
        semantics=semantics)
    return {
        "format": "cur261-r6-c2-independent-marginal-v1",
        "namespace": indep["seed_namespace"],
        "pairs_per_rung": indep["pairs_per_rung"],
        "guard": guard,
        "density_gates": {r: d for r, d in density_gates.items()},
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk != "per_quadrant"}
                      for k, v in semantics.items()},
    }


def _reference_long_label_rate_r6(records: list[PairRecord],
                                  rung_params: dict,
                                  thresholds: dict) -> float:
    """reference 动作 long bar 占比(raw 模式)。"""
    from rl_curriculum.curriculum261_qualification import build_policy_set

    pol = build_policy_set(FAMILY_C2, dict(rung_params), thresholds)[
        "reference"]
    n_long = 0
    n_total = 0
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            r = run_policy_episode(pol, ep, EVAL_CFG, RAW_SCHEMA,
                                   return_observations=True)
            actions = np.asarray(r[1])
            n_long += int((actions == 1).sum())
            n_total += int(len(actions))
    return float(n_long / n_total) if n_total else float("nan")


# ------------------------------------------------ C2 密度诊断(matched)
def run_c2_density_diagnostics_r6(
        matched_main: dict[str, Any],
        matched_holdout: dict[str, Any],
        pack: dict[str, Any],
) -> dict[str, Any]:
    """C2 行为密度诊断(matched 双语料;§18 字段)。"""
    from rl_curriculum.curriculum261_c2 import c2_pair_integrity_metrics

    ladder = r6_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    out: dict[str, Any] = {}
    for key, matched in (("main", matched_main),
                         ("holdout", matched_holdout)):
        per_rung: dict[str, Any] = {}
        for rung in CURRICULUM261_RUNGS:
            dens = c2_density_summary(
                [row for row in matched["episodes"]
                 if row["rung"] == rung], rung)
            dens["reference_long_label_rate"] = _reference_long_label_rate_r6(
                [blk.pair_records[rung] for blk in matched["blocks"]],
                ladder[rung], thresholds)
            cue_counts = [c2_pair_integrity_metrics(rec.episodes[s])
                          for blk in matched["blocks"]
                          for rec in [blk.pair_records[rung]]
                          for s in ("A", "B")]
            dens["mean_n_cues"] = float(np.mean(
                [c["n_cues"] for c in cue_counts]))
            dens["mean_next1_dir_aligned_bps"] = float(np.nanmean(
                [c["next1_dir_aligned_bps"] for c in cue_counts]))
            dens["mean_next1_width_aligned_bps"] = float(np.nanmean(
                [c["next1_width_aligned_bps"] for c in cue_counts]))
            dens["density_gate"] = density_gate_r5(dens)
            per_rung[rung] = dens
        out[key] = {
            "namespace": matched["seed_namespace"],
            "per_rung": per_rung,
            "pass": bool(all(per_rung[r]["density_gate"]["pass"]
                             for r in CURRICULUM261_RUNGS)),
        }
    return {
        "format": "cur261-r6-c2-density-diagnostics-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R6,
        "thresholds": {
            "median_reference_trades_per_episode_min": 8.0,
            "reference_long_label_rate_min": 0.015,
        },
        "main": out["main"],
        "holdout": out["holdout"],
        "pass": bool(out["main"]["pass"] and out["holdout"]["pass"]),
    }


# ------------------------------------------------ supervised learnability
def _collect_supervised_dataset_r6(
        records: list[PairRecord], family: str,
        rung_params_by_rung: dict[str, dict[str, Any]],
        preproc_v2: RouteCPreprocessorV2,
) -> list[dict[str, Any]]:
    """scaled obs + reference action(R6 rung 参数,pack override)。"""
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.curriculum261_r3_obs import scaled_episode

    thresholds = dict(family_specs()[family].reference_defaults)
    schema = r4_observation_schema(preproc_v2)
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


def supervised_learnability_run_r6(
        preproc_v2: RouteCPreprocessorV2, pack: dict[str, Any],
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R5,
        namespace: str = "calibration_r6",
        train_pair_limit: int = 6,
) -> dict[str, Any]:
    """§28 supervised learnability gate(阈值/seed/控制与 R3/R4/R5 相同)。"""
    from rl_curriculum.ppo262_r2_supervised import train_supervised_mlp

    out: dict[str, Any] = {
        "format": "cur261-r6-supervised-learnability-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R6,
        "namespace": namespace,
        "gate_constants": SUPERVISED_GATE,
        "model_seeds": list(SUPERVISED_MODEL_SEEDS),
        "families": {},
    }
    overall = True
    for family in CURRICULUM261_FAMILIES:
        override = r6_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
        rung_params = r6_family_rung_params(family, pack)
        rows = _collect_supervised_dataset_r6(
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


# --------------------------------------------- preprocessing V2 重新资格
def preprocessing_robustness_checks_r6(
        v2_main: RouteCPreprocessorV2,
        v2_holdout: RouteCPreprocessorV2,
        records_main: list[PairRecord],
        records_holdout: list[PairRecord],
        eval_records: list[PairRecord],
        equivalence_records: list[PairRecord],
        pack: dict[str, Any],
) -> dict[str, Any]:
    """§28 V2 preprocessing 在 R6 全新 fit 语料上的重新资格全电池
    (结构沿 R5;override/继承验证换 R6 实现)。"""
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
    from rl_curriculum.curriculum261_r6_param_pack import (
        verify_r4_inheritance,
    )

    checks: dict[str, Any] = {}
    inner = v2_main.inner

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
        sample = fit_matrix_from_records(eval_records[:4])
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
        rec.episodes[s].df) for rec in eval_records[:8]
        for s in ("A", "B")]
    space_validation = validate_observation_space_v2(
        scaled_dfs, scaled_dfs, EVAL_CFG,
        [int(rec.episodes[s].spec.seed) for rec in eval_records[:8]
         for s in ("A", "B")],
        context="preprocessing_robustness_r6")
    checks["observation_space_v2"] = space_validation
    adversarial = adversarial_out_of_range_probe(v2_main, EVAL_CFG)
    checks["adversarial_out_of_range_probe"] = adversarial

    checks["no_nan_inf"] = bool(all(
        np.isfinite(sdf[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy()
                    ).all() for sdf in scaled_dfs))

    state = inner.fitted_state()
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

    specs = family_specs()
    thresholds = {
        f: dict(specs[f].reference_defaults) for f in CURRICULUM261_FAMILIES}
    eq_reports = []
    for rec in equivalence_records:
        rung_params = r6_family_rung_params(rec.family, pack)[rec.rung]
        rung_params["cur261_rung"] = rec.rung
        for side in ("A", "B"):
            eq_reports.append(reference_equivalence_check(
                rec.episodes[side], rec.family, rung_params,
                thresholds[rec.family], v2_main.inner, EVAL_CFG,
                RAW_SCHEMA))
    checks["reference_equivalence_all"] = bool(
        all(e["pass"] for e in eq_reports))
    checks["reference_equivalence_n_episodes"] = len(eq_reports)

    checks["r4_inheritance_verified"] = verify_r4_inheritance(pack)

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
        and checks["r4_inheritance_verified"]["pass"])
    return {
        "format": "cur261-r6-preprocessing-robustness-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R6,
        "checks": checks,
        "equivalence_report": eq,
        "pass": core_ok,
    }


# ------------------------------------------------------ stress / C2 diag
def run_generator_stress_r6(pack: dict[str, Any], pairs_per_rung: int = 12,
                            namespace: str = "stress_r6",
                            ) -> dict[str, Any]:
    """R6 generator stress(stress_r6;pack override 生效)。"""
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        override = r6_override_for(family, pack)
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
        "format": "cur261-r6-generator-stress-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R6,
        "namespace": namespace,
        "families": families_out,
        "pass": bool(all(
            v["accepted_implies_integrity"] for v in families_out.values())),
    }


def run_c2_diagnostics_r6(
        records: list[PairRecord],
) -> dict[str, Any]:
    """C2 三语义诊断(local cue / context observability / cue-payoff
    separation;§18)。records 须为 R6 pack override 下的语料。"""
    return {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
        "cue_payoff_separation": check_c2_cue_payoff_separation(
            records),
    }
