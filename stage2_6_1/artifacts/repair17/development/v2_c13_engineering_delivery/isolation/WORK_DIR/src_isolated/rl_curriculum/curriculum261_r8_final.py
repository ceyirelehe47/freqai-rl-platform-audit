# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R8:一次性 final qualification(§27-§29)。

§28 硬合同顺序:
1. 检查 exposure(marker OR ledger;已暴露即拒绝)+ iteration 未 aborted;
2. 加载锁定 plan(digest 复算)+ robustness gate + pack 绑定;
3. 验证 sealed final preflight attestation(digest 复算 + plan 绑定
   + 零 final seed 访问声明);
4. 完成全部不需要 final seed 的静态身份检查(冻结合同/vendor/V2
   digest/code identity/matched + cue semantic 合同身份);
5. 获取 final 文件锁(并发 final 只有一个成功);
6. 原子写 exposure marker(running;ledger 先行);
7. 第一次派生 final seed(final fit bank);
8. 执行 final:C1/C3 各 40 pairs + C2 matched blocks(selected n)+
   C2 独立 marginal guard 语料(80 pairs)+ 全套验证 + strict final
   conditions;core/independent/total pair counts 分别报告(§27);
9. marker -> completed;任何异常 -> marker -> crashed + crash evidence
   落盘 + re-raise(保留 marker,禁止修复后复用 qualification_r8)。

§29 final 必须验证:preprocessing(production equivalence/unbounded/
no clip/provenance/fit-eval isolation/survival/position/serialization/
containment/adversarial/no NaN)、reference(全部 episodes 逐 bar
raw/transformed 等价/return 等价/无 raw side channel/latent/future/
reference causality)、C1/C3 strict、C2 matched(block integrity/
shared tape/attempts/gaps/D3/baselines/density/context/local cue/
cluster-aware cue recall/precision/non-cue FP/payoff false cue/
positive-gap rate/bootstrap)、C2 independent guard、contract(历史
hashes/pack identity/block + cue 合同/selected n/plan/code/vendor/
runtime/exposure identity)。
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
from rl_curriculum.curriculum261_r4_pairs import (
    EVAL_CFG,
    RAW_SCHEMA,
    rung_report_r4,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    preprocessing_v2_contract_digest,
    validate_observation_space_v2,
)
from rl_curriculum.curriculum261_r8_calibration import (
    C2_INDEPENDENT_PAIRS_PER_RUNG_R8,
    SEMANTIC_BLOCKS_PER_CORPUS_R8,
    c2_independent_marginal_guard_r8,
    c2_matched_conditions_r8,
    fit_preprocessor_v2_from_bank_r8,
    generate_fit_bank_r8,
    run_c2_density_diagnostics_r8,
    run_c2_diagnostics_r8,
    run_c2_independent_corpus_r8,
    run_c2_matched_corpus_r8,
    run_c2_semantic_corpus_r8,
    supervised_learnability_run_r8,
)
from rl_curriculum.curriculum261_r8_namespaces import (
    QualificationR8FileLock,
    qualification_r8_exposed,
    require_r8_iteration_active,
    write_qualification_r8_exposure,
)
from rl_curriculum.curriculum261_r8_param_pack import (
    load_selected_pack,
    r8_family_rung_params,
    r8_override_for,
)
from rl_curriculum.curriculum261_r6_pairs import (
    ROBUSTNESS_KAPPA_R6,
    corpus_conditions_r6_pair,
    scrambled_gap_control,
)
from rl_curriculum.curriculum261_r8_plan import (
    _code_identity_r8,
    load_locked_plan_r8,
)
from rl_curriculum.curriculum261_r8_preflight import (
    vendor_dir_default,
    verify_sealed_attestation,
)
from rl_curriculum.curriculum261_r6_tape import (
    C2_MATCHED_LADDER_BLOCK_VERSION,
    generate_matched_block_with_attempts,
    matched_ladder_contract_identity,
)
from rl_curriculum.curriculum261_qualification import (
    check_latent_isolation,
    check_observation_causality,
    check_production_feature_equivalence,
    check_reference_causality,
    check_reproducibility,
)

FINAL_FORMAT_R8 = "cur261-r8-final-qualification-v1"


def qualification_r8_lock_dir_default() -> Path:
    from rl_curriculum.curriculum261_r8_namespaces import (
        qualification_r8_lock_dir,
    )

    return qualification_r8_lock_dir()


def _fresh_seed_validity_r8(n_checks: int = 10) -> dict[str, Any]:
    """fresh_holdout_r8 与 qualification_r8 的 seed 不相交验证。"""
    from rl_curriculum.curriculum261_api import derive261_seed

    mismatches = []
    for i in range(n_checks):
        for family in CURRICULUM261_FAMILIES:
            q = derive261_seed("qualification_r8", family, "D2", i, 0)
            for rung in CURRICULUM261_RUNGS:
                f = derive261_seed("fresh_holdout_r8", family, rung, i, 0)
                if q == f:
                    mismatches.append((family, rung, i))
    return {
        "n_checks": int(n_checks * len(CURRICULUM261_FAMILIES)),
        "collisions": mismatches,
        "pass": not mismatches,
    }


def run_final_qualification_r8(out_dir: Path,
                               vendor_dir: Path | None = None,
                               ) -> dict[str, Any]:
    """执行一次性 R8 final qualification(§28)。"""
    require_r8_iteration_active()
    if qualification_r8_exposed():
        raise RuntimeError(
            "R8 final qualification 已执行过(exposure marker/ledger "
            "存在)——同一 qualification_r8 corpus 不得再次执行;继续必须"
            "使用新迭代身份(R8.1/R8)与全新 seed space")
    plan, digest = load_locked_plan_r8()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R8 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    pack = load_selected_pack(qualification_r8_lock_dir_default())
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
    code_ok = (plan["code_identity"] == _code_identity_r8())
    cue_plan = plan.get("cue_semantic_contract", {})
    cue_contract_ok = bool(
        pack.get("cue_semantic_contract_digest")
        == cue_plan.get("contract_digest")
        and pack.get("cue_semantic_rule_identity")
        == cue_plan.get("rule_identity")
        and float(pack.get("p_contract", -1))
        == float(cue_plan.get("p_contract", -2))
        and float(pack.get("recall_floor", -1))
        == float(cue_plan.get("recall_floor", -2)))
    static_ok = bool(frozen["pass"] and upstream_ok and contract_ok
                     and code_ok and cue_contract_ok)
    if not static_ok:
        raise RuntimeError(
            "final 静态身份检查失败(frozen contracts/vendor/V2 digest/"
            "code identity/cue semantic contract);在 exposure marker "
            "之前 fail closed——本轮 qualification_r8 未消耗")

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with QualificationR8FileLock(blocking=False):
            write_qualification_r8_exposure(digest, status="running")
            result = _execute_final_r8(
                out_dir, plan, digest, pack, started)
        write_qualification_r8_exposure(
            digest, status="completed"
            if result["verdict"] == "PASS" else "failed")
        return result
    except Exception:
        exc = traceback.format_exc()
        try:
            (out_dir / "qualification_crash_traceback.log").write_text(
                exc, encoding="utf-8")
            write_qualification_r8_exposure(digest, status="crashed")
        except Exception:  # noqa: BLE001 - 崩溃路径不得掩盖原始异常
            pass
        raise


def _execute_final_r8(out_dir: Path, plan: dict[str, Any], digest: str,
                      pack: dict[str, Any], started: str,
                      ) -> dict[str, Any]:
    """marker=running 之后的 final 主流程(任何异常 -> crashed)。"""
    kappa = float(plan["statistics_rule"]["kappa"])
    n_blocks = int(plan["final_sample_counts"]["c2_matched_blocks"])
    recall_floor_value = float(
        plan["cue_semantic_contract"]["recall_floor"])

    # 1) final fit bank(plan+sealed preflight 后首次访问)
    final_records = generate_fit_bank_r8(
        "preprocess_fit_qualification_r8", pack)
    final_v2, final_manifest = fit_preprocessor_v2_from_bank_r8(
        "preprocess_fit_qualification_r8", pack,
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
         for s in ("A", "B")], context="final_fit_space_v2_r8")
    adversarial = adversarial_out_of_range_probe(final_v2, EVAL_CFG)

    # 2) qualification_r8 C1/C3 40 pairs(pack override 生效)
    thresholds = plan["reference_thresholds_by_family"]
    family_reports: dict[str, Any] = {}
    all_records: dict[str, list] = {}
    for family in CURRICULUM261_FAMILIES:
        if family == FAMILY_C2:
            continue
        override = r8_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(10):
                records.append(generate_pair(
                    family, rung, idx, namespace="qualification_r8",
                    rung_params_override=override))
        all_records[family] = records
        family_reports[family] = rung_report_r4(
            records, family, r8_family_rung_params(family, pack),
            thresholds[family], final_v2, corpus="qualification_r8")

    # 3) C2 matched blocks(selected n)+ independent marginal 语料
    c2_matched = run_c2_matched_corpus_r8(
        final_v2, pack, "qualification_r8", n_blocks)
    c2_indep = run_c2_independent_corpus_r8(
        final_v2, pack, "c2_independent_qualification_r8",
        pairs_per_rung=C2_INDEPENDENT_PAIRS_PER_RUNG_R8)
    c2_conditions = c2_matched_conditions_r8(c2_matched, pack)
    c2_marginal = c2_independent_marginal_guard_r8(
        c2_indep, pack, recall_floor_value)
    # §32/§33:dedicated cue semantic corpus(160 blocks × 8 episodes,
    # selected ladder;与 core qualification 同批暴露的一次性语料)
    semantic = run_c2_semantic_corpus_r8(
        pack, "cue_semantic_qualification_r8",
        n_blocks=SEMANTIC_BLOCKS_PER_CORPUS_R8, out_dir=out_dir,
        artifact_name="qualification_cue_semantics.json")

    # 4) reference 等价:全部 core episodes(禁止抽样)
    c2_ladder = r8_family_rung_params(FAMILY_C2, pack)
    reference_eq = []
    for family in CURRICULUM261_FAMILIES:
        if family == FAMILY_C2:
            for blk in c2_matched["blocks"]:
                for rung in CURRICULUM261_RUNGS:
                    rec = blk.pair_records[rung]
                    rung_params = dict(c2_ladder[rung])
                    rung_params["cur261_rung"] = rung
                    for side in ("A", "B"):
                        reference_eq.append(reference_equivalence_check(
                            rec.episodes[side], family, rung_params,
                            thresholds[family], final_v2.inner, EVAL_CFG,
                            RAW_SCHEMA))
        else:
            for rec in all_records[family]:
                rung_params = r8_family_rung_params(family, pack)[
                    rec.rung]
                rung_params["cur261_rung"] = rec.rung
                for side in ("A", "B"):
                    reference_eq.append(reference_equivalence_check(
                        rec.episodes[side], family, rung_params,
                        thresholds[family], final_v2.inner, EVAL_CFG,
                        RAW_SCHEMA))

    causality = {
        "observation_causality": [
            check_observation_causality(f, "D2", 0,
                                        namespace="qualification_r8")
            for f in CURRICULUM261_FAMILIES],
        "production_feature_equivalence": [
            check_production_feature_equivalence(
                f, "D2", 0, namespace="qualification_r8")
            for f in CURRICULUM261_FAMILIES],
        "reference_causality": [
            check_reference_causality(
                f, r8_family_rung_params(f, pack)["D2"], thresholds[f])
            for f in CURRICULUM261_FAMILIES],
    }
    repro = [check_reproducibility(f, r, 0, "qualification_r8")
             for f in CURRICULUM261_FAMILIES for r in ("D1", "D2")]
    repro_pack_override = []
    for family in CURRICULUM261_FAMILIES:
        ov = r8_override_for(family, pack) or {}
        for rung in sorted(ov):
            r1 = generate_pair(family, rung, 0,
                               namespace="qualification_r8",
                               rung_params_override={rung: dict(ov[rung])})
            r2 = generate_pair(family, rung, 0,
                               namespace="qualification_r8",
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
    repro_blk1 = generate_matched_block_with_attempts(
        c2_ladder, namespace="qualification_r8", block_index=0)
    repro_blk2 = generate_matched_block_with_attempts(
        c2_ladder, namespace="qualification_r8", block_index=0)
    matched_repro_ok = bool(all(
        repro_blk1.episodes[r][s].df.equals(
            repro_blk2.episodes[r][s].df)
        and repro_blk1.episodes[r][s].hidden.equals(
            repro_blk2.episodes[r][s].hidden)
        for r in CURRICULUM261_RUNGS for s in ("A", "B")))
    repro.append({
        "check": "matched_block_reproducibility",
        "pass": matched_repro_ok,
        "block_index": 0,
        "shared_tape_digest": repro_blk1.shared_tape_digest,
    })

    latent_records = (
        [r for recs in all_records.values() for r in recs]
        + [rec for blk in c2_matched["blocks"]
           for rec in blk.pair_records.values()] + c2_indep["records"])
    latent = check_latent_isolation(latent_records)
    fresh = _fresh_seed_validity_r8(10)

    # 5) representation + supervised(final fit state)
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile as _cond,
    )

    cond_records = generate_fit_bank_r8(
        "preprocess_fit_calibration_r8", pack)
    cond_eval_records = [
        rec for recs in all_records.values() for rec in recs[:8]]
    conditioning = _cond(final_v2.inner, cond_records, cond_eval_records)
    supervised = supervised_learnability_run_r8(
        final_v2, pack, namespace="qualification_r8")

    # 6) 密度 + matched 语义诊断 + scrambled
    density = run_c2_density_diagnostics_r8(
        c2_matched, c2_matched, pack)
    semantics = run_c2_diagnostics_r8(
        [rec for blk in c2_matched["blocks"]
         for rec in blk.pair_records.values()])
    scrambled = scrambled_gap_control(c2_matched["block_table"])

    # 7) strict final conditions
    conditions: dict[str, Any] = {}
    for family in ("c1_opportunity", "c3_cost"):
        conditions[family] = corpus_conditions_r6_pair(
            family_reports[family], kappa)
    conditions[FAMILY_C2] = c2_conditions
    marginal_pass = bool(c2_marginal["guard"]["pass"])
    checks: dict[str, Any] = {
        "preprocessing_survival_8_of_8": bool(survival_ok),
        "preprocessing_envelope_reload": bool(reload_ok),
        "production_numerical_equivalence": bool(equivalence["pass"]),
        "observation_space_v2": bool(space_validation["pass"]),
        "adversarial_out_of_range": bool(adversarial["pass"]),
        "reference_equivalence_all": bool(
            all(e["pass"] for e in reference_eq)),
        "reference_equivalence_n_episodes": len(reference_eq),
        "causality_observation": bool(all(
            c["pass"] if isinstance(c, dict) else bool(c)
            for c in causality["observation_causality"])),
        "causality_production_features": bool(all(
            c["pass"] if isinstance(c, dict) else bool(c)
            for c in causality["production_feature_equivalence"])),
        "causality_reference": bool(all(
            c["pass"] if isinstance(c, dict) else bool(c)
            for c in causality["reference_causality"])),
        "reproducibility_all": bool(all(
            r["pass"] for r in repro)),
        "matched_block_reproducibility": matched_repro_ok,
        "latent_isolation": bool(latent["pass"]),
        "fresh_seed_disjoint": bool(fresh["pass"]),
        "c1_strict_pass": bool(conditions["c1_opportunity"]["pass"]),
        "c3_strict_pass": bool(conditions["c3_cost"]["pass"]),
        "c2_matched_strict_pass": bool(c2_conditions["pass"]),
        "c2_independent_marginal_pass": marginal_pass,
        "c2_dedicated_semantic_corpus_pass": bool(
            semantic["pass"]),
        "semantic_block_count_consistent": bool(
            semantic["n_blocks"]
            == int(plan["final_sample_counts"]["semantic_blocks"])),
        "c2_density_pass": bool(density["pass"]),
        "c2_semantics_pass": bool(all(
            v["pass"] for v in semantics.values())),
        "conditioning_gate": bool(conditioning["pass"]),
        "supervised_gate": bool(supervised["pass"]),
        "block_contract_identity": bool(
            pack["matched_ladder_contract_identity"]
            == matched_ladder_contract_identity()),
        "cue_semantic_contract_identity": bool(cue_contract_identity_ok(
            pack, plan)),
        "selected_block_count_consistent": bool(
            n_blocks == int(pack["selected_block_count"])
            and c2_matched["n_blocks"] == n_blocks),
    }
    verdict_pass = bool(all(
        v for v in checks.values() if isinstance(v, bool)))
    core_pairs = 80 + 4 * n_blocks
    independent_guard_pairs = int(
        4 * c2_indep["pairs_per_rung"])
    semantic_blocks = int(semantic["n_blocks"])
    semantic_episodes = int(semantic["n_semantic_episodes"])

    result = {
        "format": FINAL_FORMAT_R8,
        "iteration": "r8",
        "plan_digest": digest,
        "parameter_pack_digest": pack["digest"],
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "namespace": "qualification_r8",
        "c2_independent_namespace": "c2_independent_qualification_r8",
        "selected_block_count": n_blocks,
        "cue_semantic_namespace": "cue_semantic_qualification_r8",
        "core_qualification_pairs": core_pairs,
        "c2_independent_guard_pairs": independent_guard_pairs,
        "semantic_blocks": semantic_blocks,
        "semantic_episodes": semantic_episodes,
        "total_generated_pairs": core_pairs + independent_guard_pairs,
        "total_generated_episodes": (2 * core_pairs
                                     + 2 * independent_guard_pairs
                                     + semantic_episodes),
        "c1_pairs": 40, "c3_pairs": 40, "c2_pairs": 4 * n_blocks,
        "kappa": kappa,
        "checks": checks,
        "conditions": conditions,
        "c2_independent_marginal": c2_marginal,
        "c2_dedicated_semantic_corpus": {
            "namespace": semantic["namespace"],
            "n_blocks": semantic["n_blocks"],
            "n_semantic_episodes": semantic["n_semantic_episodes"],
            "n_unique_positive_cues": semantic["shared"][
                "n_unique_positive_cues"],
            "recall_point": semantic["shared"]["recall"]["point"],
            "recall_lcb": semantic["shared"]["recall"]["bound"],
            "recall_floor": semantic["shared"]["recall_floor"],
            "noncue_fp_ucb": semantic["shared"]["noncue_false_positive"][
                "bound"],
            "candidate_pass": semantic["candidate"]["pass"],
            "shared_pass": semantic["shared"]["pass"],
            "pass": semantic["pass"],
        },
        "c2_density": density,
        "c2_semantics": {
            k: {kk: vv for kk, vv in v.items() if kk != "per_quadrant"}
            for k, v in semantics.items()},
        "c2_scrambled_control_diagnostic": scrambled,
        "verdict": "PASS" if verdict_pass else "FAIL",
    }

    # ---- 全套 artifacts dump ----
    def _dump(name: str, obj: Any) -> None:
        (out_dir / name).write_text(json.dumps(
            obj, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")

    _dump("qualification_result.json", result)
    (out_dir / "qualification_raw.json").write_text(json.dumps({
        "families": {f: {
            "pair_table": family_reports[f]["pair_table"],
            "difficulty_ladder": family_reports[f]["difficulty_ladder"],
            "fixed_baseline_margins": family_reports[f][
                "fixed_baseline_margins"],
            "adjacent_rung_gaps": family_reports[f][
                "adjacent_rung_gaps"],
            "attempt_stats": family_reports[f]["attempt_stats"],
            "pair_integrity_pass_rate": family_reports[f][
                "pair_integrity_pass_rate"],
        } for f in ("c1_opportunity", "c3_cost")},
        "c2_matched": {
            "block_corpus_summary": c2_matched["block_corpus_summary"],
            "block_attempt_stats": c2_matched["block_attempt_stats"],
            "block_table": c2_matched["block_table"],
            "pair_table": c2_matched["pair_table"],
            "matched_conditions": c2_conditions,
        },
        "reference_equivalence_reports": [
            {"pass": e["pass"]} for e in reference_eq],
        "reproducibility": repro,
        "fresh_seed_validity": fresh,
        "latent_isolation": latent,
        "conditioning": conditioning,
        "supervised": supervised,
    }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    _dump("qualification_pair_evidence_table.json", {
        f: family_reports[f]["pair_table"]
        for f in ("c1_opportunity", "c3_cost")})
    _dump("qualification_c2_block_evidence_table.json",
          c2_matched["block_table"])
    _dump("qualification_c2_independent_marginal.json", c2_marginal)
    _dump("qualification_fit_manifest.json", final_manifest)
    _dump("qualification_preprocessor_bundle.json", {
        "bundle_hash": final_v2.bundle_hash,
        "state_hash": final_v2.state_hash_r3(),
        "manifest_multiset_hash": final_v2.manifest_multiset_hash,
        "namespace": "preprocess_fit_qualification_r8",
    })
    _dump("qualification_exposure.json", {
        "status": "running(will be updated atomically)",
        "plan_digest": digest,
        "contract": C2_MATCHED_LADDER_BLOCK_VERSION,
    })
    return result


def cue_contract_identity_ok(pack: dict[str, Any],
                             plan: dict[str, Any]) -> bool:
    cue_plan = plan.get("cue_semantic_contract", {})
    return bool(
        pack.get("cue_semantic_contract_digest")
        == cue_plan.get("contract_digest")
        and pack.get("cue_semantic_rule_identity")
        == cue_plan.get("rule_identity")
        and float(pack.get("p_contract", -1))
        == float(cue_plan.get("p_contract", -2))
        and float(pack.get("recall_floor", -1))
        == float(cue_plan.get("recall_floor", -2)))
