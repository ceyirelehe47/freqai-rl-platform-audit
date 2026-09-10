# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R12:一次性 final qualification(§27-§29)。

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
   落盘 + re-raise(保留 marker,禁止修复后复用 qualification_r12)。

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
from rl_curriculum.curriculum261_r12_calibration import (
    C2_INDEPENDENT_PAIRS_PER_RUNG_R12,
    SEMANTIC_BLOCKS_PER_CORPUS_R12,
    c2_independent_marginal_guard_r12,
    c2_matched_conditions_r12,
    fit_preprocessor_v2_from_bank_r12,
    generate_fit_bank_r12,
    run_c2_density_diagnostics_r12,
    run_c2_diagnostics_r12,
    run_c2_independent_corpus_r12,
    run_c2_matched_corpus_r12,
    run_c2_semantic_corpus_r12,
    supervised_learnability_run_r12,
)
from rl_curriculum.curriculum261_r12_namespaces import (
    QualificationR12FileLock,
    qualification_r12_exposed,
    require_r12_iteration_active,
    write_qualification_r12_exposure,
)
from rl_curriculum.curriculum261_r12_param_pack import (
    load_selected_pack,
    r12_family_rung_params,
    r12_override_for,
)
from rl_curriculum.curriculum261_r6_pairs import (
    ROBUSTNESS_KAPPA_R6,
    corpus_conditions_r6_pair,
    scrambled_gap_control,
)
from rl_curriculum.curriculum261_r12_plan import (
    _code_identity_r12,
    load_locked_plan_r12,
)
from rl_curriculum.curriculum261_r12_preflight import (
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

FINAL_FORMAT_R12 = "cur261-r12-final-qualification-v1"


from rl_curriculum.curriculum261_r12_routing import (
    build_routing_r12,
)
from rl_curriculum.curriculum261_r12_reference import (
    reference_equivalence_run_r12,
    write_reference_equivalence_artifacts_r12,
)
from rl_curriculum.curriculum261_r12_orchestrator import (
    CALIBRATION_PAIRS_PER_RUNG_R12,
    R12_SUPERVISED_MODEL_SEEDS,
)


def qualification_r12_lock_dir_default() -> Path:
    from rl_curriculum.curriculum261_r12_namespaces import (
        qualification_r12_lock_dir,
    )

    return qualification_r12_lock_dir()


def _fresh_seed_validity_r12(n_checks: int = 10) -> dict[str, Any]:
    """fresh_holdout_r12 与 qualification_r12 的 seed 不相交验证。"""
    from rl_curriculum.curriculum261_api import derive261_seed

    mismatches = []
    for i in range(n_checks):
        for family in CURRICULUM261_FAMILIES:
            q = derive261_seed("qualification_r12", family, "D2", i, 0)
            for rung in CURRICULUM261_RUNGS:
                f = derive261_seed("fresh_holdout_r12", family, rung, i, 0)
                if q == f:
                    mismatches.append((family, rung, i))
    return {
        "n_checks": int(n_checks * len(CURRICULUM261_FAMILIES)),
        "collisions": mismatches,
        "pass": not mismatches,
    }


def run_final_qualification_r12(out_dir: Path,
                               vendor_dir: Path | None = None,
                               ) -> dict[str, Any]:
    """执行一次性 R12 final qualification(§28)。"""
    require_r12_iteration_active()
    if qualification_r12_exposed():
        raise RuntimeError(
            "R12 final qualification 已执行过(exposure marker/ledger "
            "存在)——同一 qualification_r12 corpus 不得再次执行;继续必须"
            "使用新迭代身份(R12)与全新 seed space")
    plan, digest = load_locked_plan_r12()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R12 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    pack = load_selected_pack(qualification_r12_lock_dir_default())
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
    code_ok = (plan["code_identity"] == _code_identity_r12())
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
            "之前 fail closed——本轮 qualification_r12 未消耗")

    from rl_curriculum.curriculum261_r12_dependencies import (
        verify_r12_code_freeze,
    )

    freeze = verify_r12_code_freeze(Path(out_dir))
    if not freeze["pass"]:
        raise RuntimeError(
            f"R12 code freeze 校验失败(正式数据开始后源码漂移;"
            f"§6/§21 永久结束):{freeze}")
    plan_freeze = (plan.get("code_freeze") or {}).get("code_freeze_sha")
    if plan_freeze and freeze.get("code_freeze_sha") != plan_freeze:
        raise RuntimeError("plan 绑定的 code freeze SHA 与冻结清单不一致")

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with QualificationR12FileLock(blocking=False):
            write_qualification_r12_exposure(digest, status="running")
            result = execute_final_core_r12(
                out_dir, plan, pack, digest=digest, started=started,
                profile_name="formal_final",
                final_namespace="qualification_r12",
                fit_namespace="preprocess_fit_qualification_r12",
                c13_pairs_per_rung=10,
                c2_blocks=int(plan["final_sample_counts"][
                    "c2_matched_blocks"]),
                semantic_block_count=160,
                independent_pairs_per_rung=20)
        write_qualification_r12_exposure(
            digest, status="completed"
            if result["verdict"] == "PASS" else "failed")
        return result
    except Exception:
        exc = traceback.format_exc()
        try:
            (out_dir / "qualification_crash_traceback.log").write_text(
                exc, encoding="utf-8")
            write_qualification_r12_exposure(digest, status="crashed")
        except Exception:  # noqa: BLE001 - 崩溃路径不得掩盖原始异常
            pass
        raise


def execute_final_core_r12(
        out_dir: Path, plan: dict[str, Any], pack: dict[str, Any], *,
        digest: str = "", started: str | None = None,
        profile_name: str = "formal_final",
        final_namespace: str = "qualification_r12",
        fit_namespace: str = "preprocess_fit_qualification_r12",
        c13_pairs_per_rung: int = 10,
        c2_blocks: int | None = None,
        semantic_block_count: int = 160,
        independent_pairs_per_rung: int = 20,
        exposure_dir: Path | None = None,
        rehearsal: bool = False,
        shadow: bool = False,
        independent_namespace: str | None = None,
        semantic_namespace_override: str | None = None,
        supervised_namespace_override: str | None = None,
        supervised_pairs_per_rung_override: int | None = None,
        supervised_train_pair_limit_override: int | None = None,
        supervised_model_seeds_override: tuple | list | None = None,
        supervised_training_config: dict | None = None,
        conditioning_fit_namespace: str | None = None,
        semantic_out_dir: Path | None = None) -> dict[str, Any]:
    """final 主流程(正式与 rehearsal/shadow 共享同一执行核心;§12.4)。

    正式:run_final_qualification_r12(exposure/plan/freeze 治理外壳)
    以 qualification_r12 全量参数调用;
    rehearsal:preplan 以 preplan_final_r12 + 微样本参数 + 临时
    exposure 目录调用(§12.2 final-like runner);
    shadow:full-scale shadow(工作包 C)以 shadow_fit_main_r12 +
    正式规模参数调用(工程;envelope sink 已由本函数打开)。
    *_override 参数仅供 shadow(工程覆盖;正式路径不传,保持
    权威 namespace 选择)。

    R12 变更(§9/§11/§25):
    - final bundle 经显式 routing(final role;fail closed);
    - reference equivalence 走 canonical 合同(reference_equivalence_
      run_r12:canonical vs scaled 逐位 + legacy 差异 + 0 unexplained),
      覆盖全部 final episodes(core C1/C3 + C2 matched + independent);
    - supervised 调用 keyword-only(namespace= 显式)。
    """
    from rl_curriculum.curriculum261_generation_envelope import (
        envelope_sink,
        ledger_sink_factory,
    )

    kappa = float(plan["statistics_rule"]["kappa"]) \
        if "statistics_rule" in plan else 1.5
    if c2_blocks is None:
        c2_blocks = int(plan["final_sample_counts"]["c2_matched_blocks"])
    recall_floor_value = float(
        plan["cue_semantic_contract"]["recall_floor"]) \
        if "cue_semantic_contract" in plan else float(pack["recall_floor"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = started or datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    sink = envelope_sink(ledger_sink_factory(
        out_dir / "generation_invocation_ledger.jsonl",
        stage_label=f"final_core:{profile_name}"))
    with sink:
        return _execute_final_core_inner_r12(
            out_dir, plan, pack, digest=digest, started=started,
            profile_name=profile_name, final_namespace=final_namespace,
            fit_namespace=fit_namespace,
            c13_pairs_per_rung=c13_pairs_per_rung, c2_blocks=c2_blocks,
            semantic_block_count=semantic_block_count,
            independent_pairs_per_rung=independent_pairs_per_rung,
            exposure_dir=exposure_dir, rehearsal=rehearsal, shadow=shadow,
            independent_namespace=independent_namespace,
            semantic_namespace_override=semantic_namespace_override,
            supervised_namespace_override=supervised_namespace_override,
            supervised_pairs_per_rung_override=(
                supervised_pairs_per_rung_override),
            supervised_train_pair_limit_override=(
                supervised_train_pair_limit_override),
            supervised_model_seeds_override=supervised_model_seeds_override,
            supervised_training_config=supervised_training_config,
            conditioning_fit_namespace=conditioning_fit_namespace,
            semantic_out_dir=semantic_out_dir)


def _execute_final_core_inner_r12(
        out_dir: Path, plan: dict[str, Any], pack: dict[str, Any], *,
        digest: str = "", started: str | None = None,
        profile_name: str = "formal_final",
        final_namespace: str = "qualification_r12",
        fit_namespace: str = "preprocess_fit_qualification_r12",
        c13_pairs_per_rung: int = 10,
        c2_blocks: int | None = None,
        semantic_block_count: int = 160,
        independent_pairs_per_rung: int = 20,
        exposure_dir: Path | None = None,
        rehearsal: bool = False,
        shadow: bool = False,
        independent_namespace: str | None = None,
        semantic_namespace_override: str | None = None,
        supervised_namespace_override: str | None = None,
        supervised_pairs_per_rung_override: int | None = None,
        supervised_train_pair_limit_override: int | None = None,
        supervised_model_seeds_override: tuple | list | None = None,
        supervised_training_config: dict | None = None,
        conditioning_fit_namespace: str | None = None,
        semantic_out_dir: Path | None = None) -> dict[str, Any]:
    """execute_final_core_r12 的执行核心(envelope sink 内)。"""
    kappa = float(plan["statistics_rule"]["kappa"]) \
        if "statistics_rule" in plan else 1.5
    if c2_blocks is None:
        c2_blocks = int(plan["final_sample_counts"]["c2_matched_blocks"])
    recall_floor_value = float(
        plan["cue_semantic_contract"]["recall_floor"]) \
        if "cue_semantic_contract" in plan else float(pack["recall_floor"])

    # ---- rehearsal 临时 exposure 状态机(§12.2)----
    if rehearsal and exposure_dir is not None:
        exposure_dir = Path(exposure_dir)
        exposure_dir.mkdir(parents=True, exist_ok=True)
        (exposure_dir / "rehearsal_exposure.json").write_text(
            json.dumps({"status": "running", "profile": profile_name,
                        "started_utc": started}, ensure_ascii=False),
            encoding="utf-8")

    # 1) final fit bank(首次 final seed 派生点)
    final_records = generate_fit_bank_r12(fit_namespace, pack)
    final_v2, final_manifest = fit_preprocessor_v2_from_bank_r12(
        fit_namespace, pack, records=final_records,
        parameter_pack_identity=pack["digest"])
    routing_final = build_routing_r12(
        "final", final_v2, preplan=rehearsal, shadow=shadow)
    final_v2 = routing_final.bundle(
        expected_role="final", context="final_core")
    survival = list(final_v2.retained_columns)
    survival_ok = len(survival) == 8
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
         for s in ("A", "B")], context="final_fit_space_v2_r12")
    adversarial = adversarial_out_of_range_probe(final_v2, EVAL_CFG)

    # 2) C1/C3(正式 10 pairs/rung × 4 rung = 40 pairs/family)
    thresholds = plan["reference_thresholds_by_family"] \
        if "reference_thresholds_by_family" in plan else {
            f: dict(family_specs()[f].reference_defaults)
            for f in CURRICULUM261_FAMILIES}
    family_reports: dict[str, Any] = {}
    all_records: dict[str, list] = {}
    for family in CURRICULUM261_FAMILIES:
        if family == FAMILY_C2:
            continue
        override = r12_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(int(c13_pairs_per_rung)):
                records.append(generate_pair(
                    family, rung, idx, namespace=final_namespace,
                    rung_params_override=override))
        all_records[family] = records
        family_reports[family] = rung_report_r4(
            records, family, r12_family_rung_params(family, pack),
            thresholds[family], final_v2, corpus=final_namespace)

    # 3) C2 matched(selected n)+ independent + dedicated semantic
    c2_matched = run_c2_matched_corpus_r12(
        final_v2, pack, final_namespace, n_blocks=int(c2_blocks))
    c2_indep = run_c2_independent_corpus_r12(
        final_v2, pack,
        independent_namespace
        or ("c2_independent_qualification_r12" if not rehearsal
            else final_namespace),
        pairs_per_rung=int(independent_pairs_per_rung))
    c2_conditions = c2_matched_conditions_r12(c2_matched, pack)
    c2_marginal = c2_independent_marginal_guard_r12(
        c2_indep, pack, recall_floor_value)
    semantic_ns = semantic_namespace_override or (
        "cue_semantic_qualification_r12" if not rehearsal
        else "preplan_semantic_main_r12")
    from rl_curriculum.curriculum261_r12_design import (
        semantic_artifact_filename_r12,
    )

    semantic = run_c2_semantic_corpus_r12(
        pack, semantic_ns,
        n_blocks=int(semantic_block_count),
        out_dir=(semantic_out_dir if semantic_out_dir is not None
                 else out_dir),
        artifact_name=semantic_artifact_filename_r12(semantic_ns))

    # 4) reference equivalence(canonical 合同;全部 final episodes)
    equiv_records: list[Any] = []
    for family in ("c1_opportunity", "c3_cost"):
        equiv_records.extend(all_records[family])
    for blk in c2_matched["blocks"]:
        equiv_records.extend(blk.pair_records[rung]
                             for rung in CURRICULUM261_RUNGS)
    equiv_records.extend(c2_indep["records"])
    reference_report = reference_equivalence_run_r12(
        equiv_records, final_v2, pack,
        eval_namespace=final_namespace, detailed=True)
    write_reference_equivalence_artifacts_r12(
        out_dir, reference_report, stem="qualification_reference")

    causality = {}
    if not rehearsal or shadow:
        causality = {
            "observation_causality": [
                check_observation_causality(
                    f, "D2", 0, namespace=final_namespace)
                for f in CURRICULUM261_FAMILIES],
            "production_feature_equivalence": [
                check_production_feature_equivalence(
                    f, "D2", 0, namespace=final_namespace)
                for f in CURRICULUM261_FAMILIES],
            "reference_causality": [
                check_reference_causality(
                    f, r12_family_rung_params(f, pack)["D2"],
                    thresholds[f])
                for f in CURRICULUM261_FAMILIES],
        }
    repro = []
    if not rehearsal or shadow:
        repro = [check_reproducibility(f, r, 0, final_namespace)
                 for f in CURRICULUM261_FAMILIES for r in ("D1", "D2")]
        repro_pack_override = []
        for family in CURRICULUM261_FAMILIES:
            ov = r12_override_for(family, pack) or {}
            for rung in sorted(ov):
                r1 = generate_pair(family, rung, 0,
                                   namespace=final_namespace,
                                   rung_params_override={
                                       rung: dict(ov[rung])})
                r2 = generate_pair(family, rung, 0,
                                   namespace=final_namespace,
                                   rung_params_override={
                                       rung: dict(ov[rung])})
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
        c2_ladder = r12_family_rung_params(FAMILY_C2, pack)
        repro_blk1 = generate_matched_block_with_attempts(
            c2_ladder, namespace=final_namespace, block_index=0)
        repro_blk2 = generate_matched_block_with_attempts(
            c2_ladder, namespace=final_namespace, block_index=0)
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
    else:
        matched_repro_ok = True

    latent_records = (
        [r for recs in all_records.values() for r in recs]
        + [rec for blk in c2_matched["blocks"]
           for rec in blk.pair_records.values()] + c2_indep["records"])
    latent = check_latent_isolation(latent_records)
    fresh = (_fresh_seed_validity_r12(10)
             if not rehearsal and not shadow else {
                 "pass": True,
                 "skipped": "rehearsal/shadow 不触碰正式 "
                 "qualification/fresh_holdout seed 派生"})

    # 5) conditioning + supervised(final fit state;keyword-only)
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile as _cond,
    )

    cond_records = generate_fit_bank_r12(
        conditioning_fit_namespace or "preprocess_fit_calibration_r12",
        pack) if not rehearsal else final_records
    cond_eval_records = [
        rec for recs in all_records.values() for rec in recs[:8]]
    conditioning = _cond(final_v2.inner, cond_records, cond_eval_records)
    supervised_ns = supervised_namespace_override or (
        final_namespace if not rehearsal
        else "preplan_supervised_main_r12")
    supervised = supervised_learnability_run_r12(
        final_v2, pack, namespace=supervised_ns,
        pairs_per_rung=(supervised_pairs_per_rung_override
                        or (CALIBRATION_PAIRS_PER_RUNG_R12
                            if not rehearsal else 2)),
        train_pair_limit=(supervised_train_pair_limit_override
                          or (6 if not rehearsal else 1)),
        model_seeds=(supervised_model_seeds_override
                     or (R12_SUPERVISED_MODEL_SEEDS
                         if not rehearsal else (20270115,))),
        training_config=supervised_training_config)

    # 6) 密度 + 语义诊断 + scrambled
    density = run_c2_density_diagnostics_r12(
        c2_matched, c2_matched, pack)
    semantics = run_c2_diagnostics_r12(
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
        "reference_equivalence_all": bool(reference_report["pass"]),
        "reference_equivalence_canonical_full": bool(
            reference_report["canonical_scaled_full_equality"]),
        "reference_equivalence_unexplained": int(
            reference_report["unexplained_mismatches"]),
        "reference_equivalence_n_episodes": int(
            reference_report["n_episodes"]),
        "routing_final_bundle_verified": True,
        "reproducibility_all": bool(all(r["pass"] for r in repro))
        if repro else True,
        "matched_block_reproducibility": matched_repro_ok,
        "latent_isolation": bool(latent["pass"]),
        "fresh_seed_disjoint": bool(fresh["pass"]),
        "c1_strict_pass": bool(conditions["c1_opportunity"]["pass"]),
        "c3_strict_pass": bool(conditions["c3_cost"]["pass"]),
        "c2_matched_strict_pass": bool(c2_conditions["pass"]),
        "c2_independent_marginal_pass": marginal_pass,
        "c2_dedicated_semantic_corpus_pass": bool(semantic["pass"]),
        "semantic_block_count_consistent": bool(
            semantic["n_blocks"] == int(semantic_block_count)),
        "c2_density_pass": bool(density["pass"]),
        "c2_semantics_pass": bool(all(
            v["pass"] for v in semantics.values())),
        "conditioning_gate": bool(conditioning["pass"]),
        "supervised_gate": bool(supervised["pass"]),
        "block_contract_identity": bool(
            pack["matched_ladder_contract_identity"]
            == matched_ladder_contract_identity()),
        "cue_semantic_contract_identity": bool(cue_contract_identity_ok(
            pack, plan)) if "cue_semantic_contract" in plan else True,
        "selected_block_count_consistent": bool(
            int(c2_blocks) == int(pack["selected_block_count"])
            and c2_matched["n_blocks"] == int(c2_blocks)),
    }
    verdict_pass = bool(all(
        v for v in checks.values() if isinstance(v, bool)))
    n_blocks = int(c2_blocks)
    core_pairs = (2 * len(CURRICULUM261_RUNGS) * int(c13_pairs_per_rung)
                  + 4 * n_blocks)
    independent_guard_pairs = int(
        len(CURRICULUM261_RUNGS) * c2_indep["pairs_per_rung"])
    semantic_blocks = int(semantic["n_blocks"])
    semantic_episodes = int(semantic["n_semantic_episodes"])

    result = {
        "format": FINAL_FORMAT_R12,
        "iteration": "r12",
        "profile": profile_name,
        "rehearsal": bool(rehearsal),
        "plan_digest": digest,
        "parameter_pack_digest": pack["digest"],
        "started_utc": started,
        "completed_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "namespace": final_namespace,
        "final_bundle_hash": final_v2.bundle_hash,
        "final_fit_namespace": final_v2.namespace,
        "selected_block_count": n_blocks,
        "core_qualification_pairs": core_pairs,
        "c2_independent_guard_pairs": independent_guard_pairs,
        "semantic_blocks": semantic_blocks,
        "semantic_episodes": semantic_episodes,
        "reference_equivalence_episodes": int(
            reference_report["n_episodes"]),
        "reference_equivalence_unexplained": int(
            reference_report["unexplained_mismatches"]),
        "total_generated_pairs": core_pairs + independent_guard_pairs,
        "total_generated_episodes": (2 * core_pairs
                                     + 2 * independent_guard_pairs
                                     + semantic_episodes),
        "c1_pairs": len(CURRICULUM261_RUNGS) * int(c13_pairs_per_rung),
        "c3_pairs": len(CURRICULUM261_RUNGS) * int(c13_pairs_per_rung),
        "c2_pairs": 4 * n_blocks,
        "kappa": kappa,
        "checks": checks,
        "conditions": conditions,
        "c2_independent_marginal": c2_marginal,
        "verdict": "PASS" if verdict_pass else "FAIL",
    }
    if rehearsal:
        result["exposure_status"] = "rehearsal-terminal"
        if exposure_dir is not None:
            (exposure_dir / "rehearsal_exposure.json").write_text(
                json.dumps({"status": result["verdict"],
                            "profile": profile_name,
                            "completed_utc": result["completed_utc"]},
                           ensure_ascii=False), encoding="utf-8")
        return result

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
        "reference_equivalence_summary": {
            k: reference_report[k] for k in (
                "n_episodes", "canonical_scaled_full_equality",
                "legacy_action_diffs_total", "unexplained_mismatches",
                "pass")},
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
        "namespace": final_v2.namespace,
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
