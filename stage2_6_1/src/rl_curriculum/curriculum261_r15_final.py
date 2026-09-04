# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R15:一次性 final qualification(§27-§29)。

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
   落盘 + re-raise(保留 marker,禁止修复后复用 qualification_r15)。

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
from rl_curriculum.curriculum261_r15_calibration import (
    C2_INDEPENDENT_PAIRS_PER_RUNG_R15,
    SEMANTIC_BLOCKS_PER_CORPUS_R15,
    c2_independent_marginal_guard_r15,
    c2_matched_conditions_r15,
    fit_preprocessor_v2_from_bank_r15,
    generate_fit_bank_r15,
    run_c2_density_diagnostics_r15,
    run_c2_diagnostics_r15,
    run_c2_independent_corpus_r15,
    run_c2_matched_corpus_r15,
    run_c2_semantic_corpus_r15,
    supervised_learnability_run_r15,
)
from rl_curriculum.curriculum261_r15_namespaces import (
    QualificationR15FileLock,
    qualification_r15_exposed,
    require_r15_iteration_active,
    write_qualification_r15_exposure,
)
from rl_curriculum.curriculum261_r15_param_pack import (
    load_selected_pack,
    r15_family_rung_params,
    r15_override_for,
)
from rl_curriculum.curriculum261_r6_pairs import (
    ROBUSTNESS_KAPPA_R6,
    corpus_conditions_r6_pair,
    scrambled_gap_control,
)
from rl_curriculum.curriculum261_r15_plan import (
    _code_identity_r15,
    load_locked_plan_r15,
)
from rl_curriculum.curriculum261_r15_preflight import (
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

FINAL_FORMAT_R15 = "cur261-r15-final-qualification-v1"


from rl_curriculum.curriculum261_r15_routing import (
    build_routing_r15,
)
from rl_curriculum.curriculum261_r15_reference import (
    reference_equivalence_run_r15,
    write_reference_equivalence_artifacts_r15,
)
from rl_curriculum.curriculum261_r15_orchestrator import (
    CALIBRATION_PAIRS_PER_RUNG_R15,
    R15_SUPERVISED_MODEL_SEEDS,
)


def qualification_r15_lock_dir_default() -> Path:
    from rl_curriculum.curriculum261_r15_namespaces import (
        qualification_r15_lock_dir,
    )

    return qualification_r15_lock_dir()


def _fresh_seed_validity_r15(n_checks: int = 10) -> dict[str, Any]:
    """fresh_holdout_r15 与 qualification_r15 的 seed 不相交验证。"""
    from rl_curriculum.curriculum261_api import derive261_seed

    mismatches = []
    for i in range(n_checks):
        for family in CURRICULUM261_FAMILIES:
            q = derive261_seed("qualification_r15", family, "D2", i, 0)
            for rung in CURRICULUM261_RUNGS:
                f = derive261_seed("fresh_holdout_r15", family, rung, i, 0)
                if q == f:
                    mismatches.append((family, rung, i))
    return {
        "n_checks": int(n_checks * len(CURRICULUM261_FAMILIES)),
        "collisions": mismatches,
        "pass": not mismatches,
    }


def run_final_qualification_r15(out_dir: Path,
                               vendor_dir: Path | None = None,
                               *,
                               rehearsal_profile: dict[str, Any] | None
                               = None,
                               ) -> dict[str, Any]:
    """执行一次性 R15 final qualification(§28)。

    rehearsal_profile(R15RealArtifactCliRoundTrip-v1;§四-4):非 None
    时执行 round-trip rehearsal 的 final 阶段——治理外壳(plan/pack/
    attestation 加载、静态身份检查、freeze 复验、exposure marker、
    文件锁)与正式路径完全同代码;仅 execute_final_core 的 namespace
    与样本量来自 rehearsal_profile(rt_*_r15 rehearsal-only namespace
    + 缩小规模;verdict 在缩小规模下不作资格判定,artifact 写盘供
    PPO smoke / 下游 reader 真实读取)。exposure marker 写入
    rehearsal 隔离目录(CURRICULUM261_R15_LOCK_DIR 指向 rehearsal
    目录;正式 namespace 不消耗)。
    """
    rt = rehearsal_profile is not None
    require_r15_iteration_active()
    if qualification_r15_exposed():
        raise RuntimeError(
            "R15 final qualification 已执行过(exposure marker/ledger "
            "存在)——同一 qualification_r15 corpus 不得再次执行;继续必须"
            "使用新迭代身份(R15)与全新 seed space")
    plan, digest = load_locked_plan_r15()
    if (plan.get("robustness_gate") or {}).get("pass") is not True:
        raise RuntimeError(
            "R15 plan 的 robustness_gate.pass != true——final "
            "qualification fail closed")
    pack = load_selected_pack(qualification_r15_lock_dir_default())
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
    code_ok = (plan["code_identity"] == _code_identity_r15())
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
            "之前 fail closed——本轮 qualification_r15 未消耗")

    from rl_curriculum.curriculum261_r15_dependencies import (
        verify_r15_code_freeze,
    )

    freeze = verify_r15_code_freeze(Path(out_dir))
    if not freeze["pass"]:
        raise RuntimeError(
            f"R15 code freeze 校验失败(正式数据开始后源码漂移;"
            f"§6/§21 永久结束):{freeze}")
    plan_freeze = (plan.get("code_freeze") or {}).get("code_freeze_sha")
    if plan_freeze and freeze.get("code_freeze_sha") != plan_freeze:
        raise RuntimeError("plan 绑定的 code freeze SHA 与冻结清单不一致")

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if rt:
        core_kwargs = dict(
            profile_name="rt_final",
            final_namespace=str(rehearsal_profile["final_namespace"]),
            fit_namespace=str(rehearsal_profile["fit_namespace"]),
            c13_pairs_per_rung=int(
                rehearsal_profile["c13_pairs_per_rung"]),
            c2_blocks=int(rehearsal_profile["c2_blocks"]),
            semantic_block_count=int(
                rehearsal_profile["semantic_block_count"]),
            independent_pairs_per_rung=int(
                rehearsal_profile["independent_pairs_per_rung"]),
            rehearsal=False, shadow=False, rt=True,
            independent_namespace=str(
                rehearsal_profile["independent_namespace"]),
            semantic_namespace_override=str(
                rehearsal_profile["semantic_namespace"]),
            semantic_out_dir=out_dir,
            supervised_namespace_override=str(
                rehearsal_profile["supervised_namespace"]),
            supervised_model_seeds_override=tuple(
                rehearsal_profile["supervised_model_seeds"]),
            supervised_training_config=dict(
                rehearsal_profile["supervised_training_config"]),
            conditioning_fit_namespace=str(
                rehearsal_profile["conditioning_fit_namespace"]))
    else:
        core_kwargs = dict(
            profile_name="formal_final",
            final_namespace="qualification_r15",
            fit_namespace="preprocess_fit_qualification_r15",
            c13_pairs_per_rung=10,
            c2_blocks=int(plan["final_sample_counts"][
                "c2_matched_blocks"]),
            semantic_block_count=160,
            independent_pairs_per_rung=20)
    try:
        with QualificationR15FileLock(blocking=False):
            write_qualification_r15_exposure(digest, status="running")
            result = execute_final_core_r15(
                out_dir, plan, pack, digest=digest, started=started,
                **core_kwargs)
        write_qualification_r15_exposure(
            digest, status="completed"
            if result["verdict"] == "PASS" else "failed")
        return result
    except Exception:
        exc = traceback.format_exc()
        try:
            (out_dir / "qualification_crash_traceback.log").write_text(
                exc, encoding="utf-8")
            write_qualification_r15_exposure(digest, status="crashed")
        except Exception:  # noqa: BLE001 - 崩溃路径不得掩盖原始异常
            pass
        raise


def execute_final_core_r15(
        out_dir: Path, plan: dict[str, Any], pack: dict[str, Any], *,
        digest: str = "", started: str | None = None,
        profile_name: str = "formal_final",
        final_namespace: str = "qualification_r15",
        fit_namespace: str = "preprocess_fit_qualification_r15",
        c13_pairs_per_rung: int = 10,
        c2_blocks: int | None = None,
        semantic_block_count: int = 160,
        independent_pairs_per_rung: int = 20,
        exposure_dir: Path | None = None,
        rehearsal: bool = False,
        shadow: bool = False,
        rt: bool = False,
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

    正式:run_final_qualification_r15(exposure/plan/freeze 治理外壳)
    以 qualification_r15 全量参数调用;
    rehearsal:preplan 以 preplan_final_r15 + 微样本参数 + 临时
    exposure 目录调用(§12.2 final-like runner);
    shadow:full-scale shadow(工作包 C)以 shadow_fit_main_r15 +
    正式规模参数调用(工程;envelope sink 已由本函数打开)。
    *_override 参数仅供 shadow(工程覆盖;正式路径不传,保持
    权威 namespace 选择)。

    R15 变更(§9/§11/§25):
    - final bundle 经显式 routing(final role;fail closed);
    - reference equivalence 走 canonical 合同(reference_equivalence_
      run_r15:canonical vs scaled 逐位 + legacy 差异 + 0 unexplained),
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
        return _execute_final_core_inner_r15(
            out_dir, plan, pack, digest=digest, started=started,
            profile_name=profile_name, final_namespace=final_namespace,
            fit_namespace=fit_namespace,
            c13_pairs_per_rung=c13_pairs_per_rung, c2_blocks=c2_blocks,
            semantic_block_count=semantic_block_count,
            independent_pairs_per_rung=independent_pairs_per_rung,
            exposure_dir=exposure_dir, rehearsal=rehearsal, shadow=shadow,
            rt=rt,
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


def _detail_sources_r15(
        *, conditions: dict[str, Any], semantic: dict[str, Any],
        semantics: dict[str, Any], density: dict[str, Any],
        c2_marginal: dict[str, Any], supervised: dict[str, Any],
        conditioning: dict[str, Any], reference_report: dict[str, Any],
        fresh: dict[str, Any], latent: dict[str, Any],
        repro: list[Any] | None) -> dict[str, Any]:
    """gate_evidence 与 binding lineage audit 共用的 detail 源映射。"""
    return {
        "c1_strict_pass": conditions.get("c1_opportunity"),
        "c3_strict_pass": conditions.get("c3_cost"),
        "c2_matched_strict_pass": conditions.get(
            "c2_context"),
        "c2_dedicated_semantic_corpus_pass": semantic,
        "c2_local_cue_independence_pass": semantics.get(
            "local_cue_independence"),
        "c2_context_observability_pass": semantics.get(
            "context_observability"),
        "c2_density_pass": density,
        "c2_independent_marginal_pass": c2_marginal.get("guard"),
        "conditioning_gate": conditioning,
        "supervised_gate": supervised,
        "latent_isolation": latent,
        "fresh_seed_disjoint": fresh,
        "reproducibility_all": repro,
        "reference_equivalence_all": {
            k: reference_report.get(k) for k in (
                "n_episodes", "canonical_scaled_full_equality",
                "legacy_action_diffs_total", "unexplained_mismatches",
                "pass")},
    }


def _build_gate_evidence_r15(
        *, checks: dict[str, Any], conditions: dict[str, Any],
        semantic: dict[str, Any], semantics: dict[str, Any],
        matched_point_diag: dict[str, Any], density: dict[str, Any],
        c2_marginal: dict[str, Any], pack: dict[str, Any],
        plan_digest: str, supervised: dict[str, Any],
        conditioning: dict[str, Any], reference_report: dict[str, Any],
        fresh: dict[str, Any], latent: dict[str, Any],
        repro: list[Any] | None, topology_digest_ok: bool,
        binding_lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """R15 §八:final 一次性保存的逐 gate 详细证据。

    final FAIL 后的一切诊断只读 qualification_result.json /
    qualification_raw.json / qualification_cue_semantics.json 等
    落盘 artifact(不得重生成 corpus;api 层终态 exposure 守卫
    fail closed)。每个 verdict 级 check 的 binding status 从
    权威注册表取得(不得自带第二套);v2 加 leaf 声明
    (declared_leaf_metrics)与 aggregator 自报(actual)的逐条比对
    (binding lineage,§六)。
    """
    from rl_curriculum.curriculum261_r15_gate_topology import (
        r15_binding_status,
    )
    detail_sources = _detail_sources_r15(
        conditions=conditions, semantic=semantic, semantics=semantics,
        density=density, c2_marginal=c2_marginal,
        supervised=supervised, conditioning=conditioning,
        reference_report=reference_report, fresh=fresh, latent=latent,
        repro=repro)
    gates: dict[str, Any] = {}
    for name, value in checks.items():
        if not isinstance(value, bool):
            continue
        status = r15_binding_status(name)
        gate_entry: dict[str, Any] = {
            "binding": status["binding"],
            "diagnostic_only": status["diagnostic_only"],
            "authoritative_source": status["authoritative_source"],
            "result": value,
            "failed": value is False,
            "details": detail_sources.get(name),
        }
        lineage_entry = (binding_lineage or {}).get("entries", {}).get(
            name)
        if lineage_entry is not None:
            gate_entry["declared_leaf_metrics"] = lineage_entry.get(
                "declared")
            if "actual" in lineage_entry:
                gate_entry["aggregator_self_reported_leaves"] = (
                    lineage_entry["actual"])
        gates[name] = gate_entry
    point_results = matched_point_diag.get("results") or {}
    gates["c2_matched_cue_point_diagnostics"] = {
        "binding": False,
        "diagnostic_only": True,
        "authoritative_source": "matched_ladder_point_estimates",
        "result": point_results.get("pass"),
        "failed": point_results.get("pass") is False,
        "diagnostic_verdict_neutral": True,
        "details": matched_point_diag,
        "note": "诊断失败不得改变 R15 verdict(R15 §四-3)",
    }
    failed_binding = sorted(
        k for k, v in checks.items()
        if isinstance(v, bool) and not v
        and r15_binding_status(k)["binding"])
    return {
        "plan_digest": plan_digest,
        "parameter_pack_digest": pack.get("digest"),
        "gate_topology_digest_consistent": topology_digest_ok,
        "binding_lineage": binding_lineage,
        "input_artifacts": {
            "qualification_raw.json": (
                "families/c2_matched/repro/fresh/latent/conditioning/"
                "supervised 原始表"),
            "qualification_pair_evidence_table.json": (
                "c1/c3 pair evidence"),
            "qualification_c2_block_evidence_table.json": (
                "c2 matched block evidence"),
            "qualification_cue_semantics.json": (
                "dedicated 160-block semantic corpus gate 原始输出"
                "(cluster summary/统计)"),
        },
        "gates": gates,
        "failed_binding_checks": failed_binding,
        "post_exposure_policy": (
            "终态 exposure 后本 artifact 即最终证据;只读,不得重生成 "
            "qualification_r15 语料(api 守卫 fail closed)"),
    }


def _execute_final_core_inner_r15(
        out_dir: Path, plan: dict[str, Any], pack: dict[str, Any], *,
        digest: str = "", started: str | None = None,
        profile_name: str = "formal_final",
        final_namespace: str = "qualification_r15",
        fit_namespace: str = "preprocess_fit_qualification_r15",
        c13_pairs_per_rung: int = 10,
        c2_blocks: int | None = None,
        semantic_block_count: int = 160,
        independent_pairs_per_rung: int = 20,
        exposure_dir: Path | None = None,
        rehearsal: bool = False,
        shadow: bool = False,
        rt: bool = False,
        independent_namespace: str | None = None,
        semantic_namespace_override: str | None = None,
        supervised_namespace_override: str | None = None,
        supervised_pairs_per_rung_override: int | None = None,
        supervised_train_pair_limit_override: int | None = None,
        supervised_model_seeds_override: tuple | list | None = None,
        supervised_training_config: dict | None = None,
        conditioning_fit_namespace: str | None = None,
        semantic_out_dir: Path | None = None) -> dict[str, Any]:
    """execute_final_core_r15 的执行核心(envelope sink 内)。"""
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
    final_records = generate_fit_bank_r15(fit_namespace, pack)
    final_v2, final_manifest = fit_preprocessor_v2_from_bank_r15(
        fit_namespace, pack, records=final_records,
        parameter_pack_identity=pack["digest"])
    routing_final = build_routing_r15(
        "final", final_v2, preplan=rehearsal, shadow=shadow, rt=rt)
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
         for s in ("A", "B")], context="final_fit_space_v2_r15")
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
        override = r15_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(int(c13_pairs_per_rung)):
                records.append(generate_pair(
                    family, rung, idx, namespace=final_namespace,
                    rung_params_override=override))
        all_records[family] = records
        family_reports[family] = rung_report_r4(
            records, family, r15_family_rung_params(family, pack),
            thresholds[family], final_v2, corpus=final_namespace)

    # 3) C2 matched(selected n)+ independent + dedicated semantic
    c2_matched = run_c2_matched_corpus_r15(
        final_v2, pack, final_namespace, n_blocks=int(c2_blocks))
    c2_indep = run_c2_independent_corpus_r15(
        final_v2, pack,
        independent_namespace
        or ("c2_independent_qualification_r15" if not rehearsal
            else final_namespace),
        pairs_per_rung=int(independent_pairs_per_rung))
    c2_conditions = c2_matched_conditions_r15(c2_matched, pack)
    c2_marginal = c2_independent_marginal_guard_r15(
        c2_indep, pack, recall_floor_value)
    semantic_ns = semantic_namespace_override or (
        "cue_semantic_qualification_r15" if not rehearsal
        else "preplan_semantic_main_r15")
    from rl_curriculum.curriculum261_r15_design import (
        semantic_artifact_filename_r15,
    )

    semantic = run_c2_semantic_corpus_r15(
        pack, semantic_ns,
        n_blocks=int(semantic_block_count),
        out_dir=(semantic_out_dir if semantic_out_dir is not None
                 else out_dir),
        artifact_name=semantic_artifact_filename_r15(semantic_ns))

    # 4) reference equivalence(canonical 合同;全部 final episodes)
    equiv_records: list[Any] = []
    for family in ("c1_opportunity", "c3_cost"):
        equiv_records.extend(all_records[family])
    for blk in c2_matched["blocks"]:
        equiv_records.extend(blk.pair_records[rung]
                             for rung in CURRICULUM261_RUNGS)
    equiv_records.extend(c2_indep["records"])
    reference_report = reference_equivalence_run_r15(
        equiv_records, final_v2, pack,
        eval_namespace=final_namespace, detailed=True)
    write_reference_equivalence_artifacts_r15(
        out_dir, reference_report, stem="qualification_reference")

    causality = {}
    if not rehearsal or shadow or rt:
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
                    f, r15_family_rung_params(f, pack)["D2"],
                    thresholds[f])
                for f in CURRICULUM261_FAMILIES],
        }
    repro = []
    if not rehearsal or shadow or rt:
        repro = [check_reproducibility(f, r, 0, final_namespace)
                 for f in CURRICULUM261_FAMILIES for r in ("D1", "D2")]
        repro_pack_override = []
        for family in CURRICULUM261_FAMILIES:
            ov = r15_override_for(family, pack) or {}
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
        c2_ladder = r15_family_rung_params(FAMILY_C2, pack)
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
    fresh = (_fresh_seed_validity_r15(10)
             if not rehearsal and not shadow and not rt else {
                 "pass": True,
                 "skipped": "rehearsal/shadow 不触碰正式 "
                 "qualification/fresh_holdout seed 派生"})

    # 5) conditioning + supervised(final fit state;keyword-only)
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile as _cond,
    )

    cond_records = generate_fit_bank_r15(
        conditioning_fit_namespace or "preprocess_fit_calibration_r15",
        pack) if not rehearsal else final_records
    cond_eval_records = [
        rec for recs in all_records.values() for rec in recs[:8]]
    conditioning = _cond(final_v2.inner, cond_records, cond_eval_records)
    supervised_ns = supervised_namespace_override or (
        final_namespace if not rehearsal
        else "preplan_supervised_main_r15")
    supervised = supervised_learnability_run_r15(
        final_v2, pack, namespace=supervised_ns,
        pairs_per_rung=(supervised_pairs_per_rung_override
                        or (CALIBRATION_PAIRS_PER_RUNG_R15
                            if not rehearsal else 2)),
        train_pair_limit=(supervised_train_pair_limit_override
                          or (6 if not rehearsal else 1)),
        model_seeds=(supervised_model_seeds_override
                     or (R15_SUPERVISED_MODEL_SEEDS
                         if not rehearsal else (20270115,))),
        training_config=supervised_training_config)

    # 6) 密度 + 语义诊断 + scrambled
    density = run_c2_density_diagnostics_r15(
        c2_matched, c2_matched, pack)
    semantics = run_c2_diagnostics_r15(
        [rec for blk in c2_matched["blocks"]
         for rec in blk.pair_records.values()])
    scrambled = scrambled_gap_control(c2_matched["block_table"])

    # R15 gate topology(GateTopologyReconciliation-v1):matched corpus
    # 点估计分离检查(cue_payoff_separation)是 diagnostic_only;
    # local cue independence / context observability 保持 binding;
    # cue recall/precision/false-cue 的唯一 binding source 是
    # dedicated 160-block semantic corpus(上方 semantic gate)。
    matched_point_diag = {
        "diagnostic_only": True,
        "binding_gate": False,
        "source": "matched_ladder_point_estimates",
        "results": semantics.get("cue_payoff_separation"),
        "note": ("R6 点估计分离检查继续执行并报告;诊断失败不得改变 "
                 "R15 verdict(R15 §四-3;R13 曾把该项绑定为 "
                 "c2_semantics_pass 并 FAIL——拓扑冲突已由 "
                 "GateTopologyReconciliation-v1 机械证明)"),
    }
    from rl_curriculum.curriculum261_r15_gate_topology import (
        R15_GATE_TOPOLOGY_VERSION,
        r15_binding_lineage,
        r15_binding_status,
        r15_cue_semantic_binding_uniqueness,
        r15_gate_topology_digest,
    )
    plan_topology_digest = plan.get("gate_topology_digest") if isinstance(
        plan, dict) else None
    topology_digest_ok = bool(
        plan_topology_digest == r15_gate_topology_digest())

    # 7) strict final conditions
    conditions: dict[str, Any] = {}
    for family in ("c1_opportunity", "c3_cost"):
        conditions[family] = corpus_conditions_r6_pair(
            family_reports[family], kappa)
    conditions[FAMILY_C2] = c2_conditions
    marginal_pass = bool(c2_marginal["guard"]["pass"])
    # R15 §六:binding lineage audit(声明 leaf 与真实 aggregator
    # 自报一致;cue metric binding 强制自报;fail closed)。
    binding_lineage = r15_binding_lineage(_detail_sources_r15(
        conditions=conditions, semantic=semantic, semantics=semantics,
        density=density, c2_marginal=c2_marginal, supervised=supervised,
        conditioning=conditioning, reference_report=reference_report,
        fresh=fresh, latent=latent, repro=repro))
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
        # R15 拆分:R13 的 c2_semantics_pass(三诊断 AND,含点估计
        # binding)拆为两项 binding(local cue independence /
        # context observability)+ 一项 diagnostic_only(matched
        # 点估计;不进 checks——注册表 c2_matched_cue_point_diagnostics)
        "c2_local_cue_independence_pass": bool(
            semantics["local_cue_independence"]["pass"]),
        "c2_context_observability_pass": bool(
            semantics["context_observability"]["pass"]),
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
        "gate_topology_digest_consistent": topology_digest_ok,
        # R15 §六:binding lineage(传递闭包 leaf 声明与真实
        # aggregator 自报一致;fail closed)
        "binding_lineage_consistent": bool(binding_lineage["pass"]),
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
        "format": FINAL_FORMAT_R15,
        "iteration": "r15",
        "profile": profile_name,
        "rehearsal": bool(rehearsal),
        "rt": bool(rt),
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
        # R15 §五:independent corpus cue 点指标诊断(diagnostic_only;
        # verdict_neutral——R14 隐藏双绑定修复的可审计面)
        "independent_cue_point_diagnostics": c2_marginal.get(
            "independent_cue_point_diagnostics"),
        # R15 gate topology 声明(单一权威注册表来源;v2)
        "gate_topology": {
            "version": R15_GATE_TOPOLOGY_VERSION,
            "digest": r15_gate_topology_digest(),
            "cue_semantic_binding_uniqueness": (
                r15_cue_semantic_binding_uniqueness()),
            "binding_lineage_pass": bool(binding_lineage["pass"]),
            "binding_checks": sorted(
                k for k, v in checks.items()
                if isinstance(v, bool)
                and r15_binding_status(k)["binding"]),
            "diagnostic_only_checks": [
                "c2_matched_cue_point_diagnostics",
                "independent_cue_point_diagnostics"],
            "note": ("binding status 唯一来源 = "
                     "curriculum261_r15_gate_topology.R15_GATE_REGISTRY;"
                     "本 artifact 的每个 check 的 binding 状态见 "
                     "gate_evidence"),
        },
        # R15 §六:binding lineage audit 结果(逐 binding check 的
        # declared/actual leaf 比对)
        "binding_lineage": binding_lineage,
        # R15 §八:matched corpus 点估计诊断(diagnostic_only;
        # 诊断失败不改变 verdict——R13 败于此处)
        "c2_matched_cue_point_diagnostics": matched_point_diag,
        # R15 §八:每个 gate 的详细证据(一次性保存;final FAIL 后
        # 诊断只读本 artifact 与 qualification_raw.json,不得重生成)
        "gate_evidence": _build_gate_evidence_r15(
            checks=checks, conditions=conditions, semantic=semantic,
            semantics=semantics, matched_point_diag=matched_point_diag,
            density=density, c2_marginal=c2_marginal, pack=pack,
            plan_digest=digest, supervised=supervised,
            conditioning=conditioning, reference_report=reference_report,
            fresh=fresh, latent=latent, repro=repro,
            topology_digest_ok=topology_digest_ok,
            binding_lineage=binding_lineage),
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
    # R15 §三精神:单一 canonical 键 preprocessor_bundle_hash(R13 的
    # bundle_hash 旧键在 rehearsal full-cold reader 下暴露——rt 路径
    # 的接口残留;不得同时宽松接受两种键名)
    _dump("qualification_preprocessor_bundle.json", {
        "preprocessor_bundle_hash": final_v2.bundle_hash,
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
