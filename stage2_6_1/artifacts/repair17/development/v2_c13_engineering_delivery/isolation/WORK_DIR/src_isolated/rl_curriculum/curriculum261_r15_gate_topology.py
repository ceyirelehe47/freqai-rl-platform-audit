"""R15 权威 cue semantic gate topology 注册表 v2(单一权威来源)。

R13/R14 暴露的拓扑缺陷(机械坐标;GateTopologyReconciliation-v2
绑定的历史):

1. R13 double binding:matched 20-block corpus 上的 cue/payoff 点
   估计 gate(check_c2_cue_payoff_separation,cue_recall >= 0.95)
   被绑定为 verdict 级 c2_semantics_pass——R13 败于此
   (0.948571 < 0.95,而 dedicated cluster LCB gate 通过)。
   R14 已修复(matched 点估计 → diagnostic_only)。

2. R14 matched point gate 修复(v1)正确。

3. R14 隐藏 double binding(未被 R14 Agent 报告识别):注册表宣称
   四类 cue rate metric 的唯一 binding source 是 dedicated
   160-block semantic corpus,但
   r14_cue_eval.independent_cue_semantics 的 pass 包含
   point recall >= 0.90 与 noncue FP UCB <= 0.01;
   该 pass 被 AND 进 c2_independent_marginal_guard_r14 的
   guard.pass → c2_independent_marginal_pass → final verdict
   ——形成第二个传递性 binding source。

4. R14 uniqueness checker 的 optional metric_scope 漏检:
   r14_gate_topology 只扫描 entry.get("metric_scope", ())
   (缺省空 = fail-open),c2_independent_marginal_pass 条目无
   metric_scope 键 ⇒ 永不参与 uniqueness 检查 ⇒ 隐藏绑定不可见。

R15 权威语义(本模块是唯一来源;design plan / qualification plan /
final aggregator / report / tests 全部从这里取得 binding status):

1. Cue recall / cue precision / non-cue false positive /
   payoff-bar false-cue 的唯一正式 binding source =
   dedicated 160-block semantic corpus(cluster-aware LCB/UCB,
   既有 recall floor;不改阈值/不降样本/不按 R13/R14 结果重定标)。

2. matched corpus 上的 R6 点估计分离检查:diagnostic_only=True /
   binding_gate=False(R14 已降级,R15 继承)。

3. independent marginal corpus 上的 cue 点指标(point recall /
   noncue FP UCB / cue precision / payoff false-cue)也全部
   diagnostic_only——不得进入 independent marginal guard.pass /
   c2_independent_marginal_pass / final verdict /
   failed_binding_checks(R15 §五;对 R14 隐藏绑定的修复)。

4. independent marginal 的正式 binding 职责(v2):
   marginal ordering / D3 positive / fixed-baseline positive
   margins / integrity / oracle / density / local cue
   independence / context observability / independent cue
   canonical consistency(结构而非 cue rate threshold)。

5. binding lineage(§六):每个 binding 条目必须声明 leaf_metrics
   (真实原子叶子传递闭包;缺声明即 fail closed);cue metric 相关
   条目必须有 aggregator 自报 binding_leaf_checks 并与声明一致;
   uniqueness 检查遍历全部 binding 条目的 metric_scope(fail
   closed,不再 optional)并交叉检查 leaf 名不得携带 cue metric。

不以 R13/R14 observed recall 数值作为任何规则选择依据。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

R15_GATE_TOPOLOGY_VERSION = "GateTopologyReconciliation-v2"

#: matched corpus 点估计诊断保留的 R6 冻结阈值(仅诊断对照)。
R15_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS = {
    "cue_recall_min": 0.95,
    "cue_precision_min": 0.85,
    "non_cue_false_positive_max": 0.01,
    "payoff_bar_false_cue_max": 0.06,
}

#: 唯一 binding source 标识(dedicated 160-block semantic corpus)。
R15_CUE_SEMANTIC_BINDING_SOURCE = (
    "dedicated_160_block_semantic_corpus")

#: 四类 cue rate metric 的规范名(uniqueness/lineage 的匹配空间)。
R15_CUE_METRICS: tuple[str, ...] = (
    "cue_recall", "cue_precision", "non_cue_false_positive",
    "payoff_bar_false_cue")

#: matched corpus 的正式职责清单(§四-1;R14 继承)。
R15_MATCHED_CORPUS_RESPONSIBILITIES = (
    "difficulty_ordering",
    "blockwise_adjacent_gaps",
    "d3_absolute_margin",
    "fixed_baseline_margins",
    "positive_gap_block_rate",
    "block_pair_cross_rung_integrity",
    "density",
    "local_cue_independence",
    "context_observability",
)

#: independent marginal guard 的正式职责清单(v2:纯结构,
#: 不含任何 cue 点指标)。
R15_INDEPENDENT_MARGINAL_RESPONSIBILITIES = (
    "marginal_ordering",
    "d3_positive",
    "fixed_baseline_positive_margins",
    "integrity",
    "oracle_positive",
    "density",
    "local_cue_independence",
    "context_observability",
    "independent_cue_canonical_consistency",
)

#: c2_independent_marginal_pass 的 binding 叶子(与
#: c2_independent_marginal_guard_r15 的 guard["binding_leaf_checks"]
#: 自报逐字一致;v2 修复点:不含 point_recall/noncue UCB)。
R15_INDEPENDENT_MARGINAL_LEAVES: tuple[str, ...] = (
    "context_observability",
    "d3_mean_positive",
    "density_pass",
    "fixed_baseline_means_positive",
    "independent_cue_canonical_consistency",
    "integrity_unity",
    "local_cue_independence",
    "mean_ordering_ok",
    "oracle_positive",
)

#: c2_dedicated_semantic_corpus_pass 的 binding 叶子(与
#: run_c2_semantic_corpus_r15 的 result["binding_leaf_checks"]
#: 自报逐字一致)。
R15_DEDICATED_SEMANTIC_LEAVES: tuple[str, ...] = (
    "dedicated_aggregate_recompute_ok",
    "dedicated_candidate_cue_precision_lcb",
    "dedicated_candidate_payoff_false_cue_ucb",
    "dedicated_canonical_consistency",
    "dedicated_coverage_complete",
    "dedicated_n_unique_positive_cues_ge_min",
    "dedicated_noise_replay_integrity",
    "dedicated_noncue_fp_ucb_le_max",
    "dedicated_per_event_k_complete",
    "dedicated_recall_lcb_ge_floor",
)

#: c2_matched_strict_pass 的 binding 叶子(与
#: c2_matched_conditions_r15 的 binding_leaf_checks 自报一致)。
R15_MATCHED_STRICT_LEAVES: tuple[str, ...] = (
    "block_pair_integrity",
    "context_observability",
    "density_pass",
    "local_cue_independence",
    "shared_tape_cross_rung",
    "statistical_block_conditions",
)


def _binding(name: str, source: str, rule: str,
             leaf_metrics: tuple[str, ...],
             metric_scope: tuple[str, ...] = (),
             **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "check": name,
        "binding": True,
        "diagnostic_only": False,
        "authoritative_source": source,
        "rule": rule,
        "metric_scope": tuple(metric_scope),
        "leaf_metrics": tuple(leaf_metrics),
    }
    if not entry["leaf_metrics"]:
        raise RuntimeError(
            f"binding 条目 '{name}' 缺 leaf_metrics 声明——"
            "所有 verdict 级 check 必须声明真实叶子传递闭包"
            "(R15 §六-3:缺 lineage 声明即 fail closed)")
    entry.update(extra)
    return entry


def _diagnostic(name: str, source: str, rule: str,
                **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "check": name,
        "binding": False,
        "diagnostic_only": True,
        "binding_gate": False,
        "authoritative_source": source,
        "rule": rule,
    }
    entry.update(extra)
    return entry


#: 权威注册表:final qualification verdict 级 checks 的 binding
#: status 唯一来源。任何 plan/final/report/tests 不得自带第二套。
#: v2 强约束:binding 条目必有 metric_scope 键(可为空)与
#: leaf_metrics(非空);见 _validate_registry。
R15_GATE_REGISTRY: dict[str, dict[str, Any]] = {
    # --- 工程完整性(binding) ---
    "preprocessing_survival_8_of_8": _binding(
        "preprocessing_survival_8_of_8", "preprocessing_v2_survival",
        "8/8 family survival(fail closed)",
        leaf_metrics=("preprocessing_survival_8_of_8",)),
    "preprocessing_envelope_reload": _binding(
        "preprocessing_envelope_reload", "preprocessor_bundle_reload",
        "final fit state envelope 落盘重载等价",
        leaf_metrics=("preprocessing_envelope_reload",)),
    "production_numerical_equivalence": _binding(
        "production_numerical_equivalence",
        "production_preprocessing_equivalence",
        "production 8-feature 逐 bar 数值等价",
        leaf_metrics=("production_numerical_equivalence",)),
    "observation_space_v2": _binding(
        "observation_space_v2", "observation_space_validation",
        "V2 outer 无界空间契约",
        leaf_metrics=("observation_space_v2",)),
    "adversarial_out_of_range": _binding(
        "adversarial_out_of_range", "adversarial_probe",
        "out-of-range 输入 fail closed",
        leaf_metrics=("adversarial_out_of_range",)),
    "reference_equivalence_all": _binding(
        "reference_equivalence_all", "canonical_reference_equivalence",
        "policy-visible canonical reference 全等",
        leaf_metrics=("reference_equivalence_all",)),
    "reference_equivalence_canonical_full": _binding(
        "reference_equivalence_canonical_full",
        "canonical_reference_equivalence",
        "canonical scaled full equality",
        leaf_metrics=("reference_equivalence_canonical_full",)),
    "routing_final_bundle_verified": _binding(
        "routing_final_bundle_verified", "bundle_routing",
        "final namespace routing contract",
        leaf_metrics=("routing_final_bundle_verified",)),
    "reproducibility_all": _binding(
        "reproducibility_all", "determinism_replay",
        "seed 重放全等",
        leaf_metrics=("reproducibility_all",)),
    "matched_block_reproducibility": _binding(
        "matched_block_reproducibility", "determinism_replay",
        "matched block 重放全等",
        leaf_metrics=("matched_block_reproducibility",)),
    "latent_isolation": _binding(
        "latent_isolation", "latent_probe",
        "latent 通道隔离",
        leaf_metrics=("latent_isolation",)),
    "fresh_seed_disjoint": _binding(
        "fresh_seed_disjoint", "fresh_seed_validity",
        "fresh seed 与正式 seed 不相交",
        leaf_metrics=("fresh_seed_disjoint",)),
    # --- 家族统计 gates(binding) ---
    "c1_strict_pass": _binding(
        "c1_strict_pass", "c1_opportunity_corpus",
        "strict per-corpus AND(kappa;相邻 gap;D3 margin;"
        "fixed-baseline margins)",
        leaf_metrics=("corpus_strict_conditions",),
        aggregator_module="shared_r6(无自报;结构检查)"),
    "c3_strict_pass": _binding(
        "c3_strict_pass", "c3_cost_corpus",
        "strict per-corpus AND(kappa;相邻 gap;D3 margin;"
        "fixed-baseline margins)",
        leaf_metrics=("corpus_strict_conditions",),
        aggregator_module="shared_r6(无自报;结构检查)"),
    "c2_matched_strict_pass": _binding(
        "c2_matched_strict_pass", "matched_ladder_20_blocks",
        "matched corpus 正式职责(difficulty ordering/adjacent "
        "gaps/D3 margin/fixed-baseline margins/positive-gap block "
        "rate/integrity/density/local cue independence/context "
        "observability);cue 点估计不在其中",
        leaf_metrics=R15_MATCHED_STRICT_LEAVES,
        responsibilities=list(R15_MATCHED_CORPUS_RESPONSIBILITIES)),
    "c2_independent_marginal_pass": _binding(
        "c2_independent_marginal_pass",
        "independent_marginal_corpus",
        "structural 全集:marginal ordering/D3 positive/"
        "fixed-baseline positive margins/integrity/oracle/density/"
        "local cue independence/context observability/"
        "independent cue canonical consistency;"
        "四类 cue 点指标(point recall/noncue FP UCB/precision/"
        "payoff false-cue)在独立语料上全部 diagnostic_only——"
        "不进入本 pass(R15 §五;R14 隐藏双绑定修复)",
        leaf_metrics=R15_INDEPENDENT_MARGINAL_LEAVES,
        metric_scope=(),
        responsibilities=list(
            R15_INDEPENDENT_MARGINAL_RESPONSIBILITIES)),
    "c2_dedicated_semantic_corpus_pass": _binding(
        "c2_dedicated_semantic_corpus_pass",
        R15_CUE_SEMANTIC_BINDING_SOURCE,
        "cluster-aware block bootstrap 单侧 95% LCB >= recall_floor"
        "(既有);noncue FP UCB <= 0.01;precision LCB >= 0.85;"
        "payoff-bar false-cue UCB <= 0.06——cue recall/precision/"
        "non-cue FP/payoff false-cue 的唯一 binding source",
        leaf_metrics=R15_DEDICATED_SEMANTIC_LEAVES,
        metric_scope=R15_CUE_METRICS,
        semantic_blocks_per_corpus=160),
    "c2_local_cue_independence_pass": _binding(
        "c2_local_cue_independence_pass", "matched_ladder_20_blocks",
        "local cue independence(matched corpus 诊断器;binding——"
        "matched 正式职责)",
        leaf_metrics=("local_cue_independence",)),
    "c2_context_observability_pass": _binding(
        "c2_context_observability_pass", "matched_ladder_20_blocks",
        "context observability A/B 双 carrier(matched corpus 诊断器;"
        "binding——matched 正式职责)",
        leaf_metrics=("context_observability",)),
    "c2_density_pass": _binding(
        "c2_density_pass", "matched_ladder_20_blocks",
        "cue-adjacent bar 密度带宽",
        leaf_metrics=("density_gate_all_rungs",)),
    "conditioning_gate": _binding(
        "conditioning_gate", "conditioning_profile",
        "conditioning 单调性/幅值",
        leaf_metrics=("conditioning_gate",)),
    "supervised_gate": _binding(
        "supervised_gate", "supervised_learnability",
        "min_seeds_passing gate(既有)",
        leaf_metrics=("supervised_gate",)),
    "block_contract_identity": _binding(
        "block_contract_identity", "parameter_pack_binding",
        "pack 绑定 matched ladder contract identity",
        leaf_metrics=("block_contract_identity",)),
    "cue_semantic_contract_identity": _binding(
        "cue_semantic_contract_identity", "parameter_pack_binding",
        "pack 绑定 cue semantic contract digest",
        leaf_metrics=("cue_semantic_contract_identity",)),
    "semantic_block_count_consistent": _binding(
        "semantic_block_count_consistent",
        R15_CUE_SEMANTIC_BINDING_SOURCE,
        "dedicated semantic corpus 块数 == 160 == plan 声明",
        leaf_metrics=("semantic_block_count_consistent",)),
    "selected_block_count_consistent": _binding(
        "selected_block_count_consistent", "parameter_pack_binding",
        "selected block count == pack == 实际",
        leaf_metrics=("selected_block_count_consistent",)),
    "gate_topology_digest_consistent": _binding(
        "gate_topology_digest_consistent", "r15_gate_registry",
        "plan 携带的 gate_topology_digest == 注册表重算 digest"
        "(单一权威来源的一致性自证)",
        leaf_metrics=("gate_topology_digest_consistent",)),
    "binding_lineage_consistent": _binding(
        "binding_lineage_consistent", "r15_gate_registry_lineage",
        "注册表 leaf_metrics 声明与真实 aggregator 自报"
        "binding_leaf_checks 一致;cue metric 相关条目强制自报"
        "(R15 §六:传递闭包 lineage audit)",
        leaf_metrics=("binding_lineage_consistent",)),
    # --- 诊断(非 binding;失败不得改变 verdict) ---
    "c2_matched_cue_point_diagnostics": _diagnostic(
        "c2_matched_cue_point_diagnostics",
        "matched_ladder_point_estimates",
        "R6 点估计分离检查(check_c2_cue_payoff_separation)在 "
        "matched corpus 上继续执行并报告;阈值冻结保留;"
        "diagnostic_only=True;binding_gate=False;诊断失败不得"
        "改变 R15 verdict(R15 §四-3)",
        thresholds=dict(R15_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS),
        historical_note=(
            "R6 STRICT_GATE_RULE_IDENTITY 曾把该项列入 c2_matched "
            "binding 条目;R13 plan 原样继承,R13 final 据此把点估计 "
            "gate 绑定为 c2_semantics_pass 并 FAIL——R14 权威注册表"
            "将该项永久降级为诊断,R15 继承")),
    "independent_cue_point_diagnostics": _diagnostic(
        "independent_cue_point_diagnostics",
        "independent_marginal_corpus",
        "independent marginal corpus 上的 cue 点指标诊断"
        "(point recall >= 0.90 / noncue FP UCB <= 0.01 /"
        "cue precision / payoff false-cue);diagnostic_only=True;"
        "binding_gate=False;verdict_neutral=True;诊断 FAIL 不得"
        "改变 independent marginal binding result 与 final verdict"
        "(R15 §五;R14 曾将其 AND 进 marginal guard.pass 构成"
        "隐藏双绑定——R15 永久移除)",
        metric_scope=R15_CUE_METRICS,
        thresholds={
            "point_recall_absolute_floor": 0.90,
            "noncue_fp_ucb_max": 0.01,
            "cue_precision_min": 0.85,
            "payoff_bar_false_cue_max": 0.06,
        },
        historical_note=(
            "R14 registry 的 c2_independent_marginal_pass 条目无 "
            "metric_scope 键,r14 uniqueness checker 用 "
            "entry.get('metric_scope',()) fail-open 缺省,漏检该"
            "传递性 binding——GateTopologyReconciliation-v2 绑定")),
}


def _validate_registry() -> None:
    """构造期 fail-closed 校验(v2 核心:杜绝 R14 式漏检)。"""
    for name, entry in R15_GATE_REGISTRY.items():
        if entry["binding"]:
            if "metric_scope" not in entry:
                raise RuntimeError(
                    f"binding 条目 '{name}' 缺 metric_scope 声明"
                    "(R15 fail-closed:R14 的 optional 缺省漏检"
                    "即源于此)")
            if not entry.get("leaf_metrics"):
                raise RuntimeError(
                    f"binding 条目 '{name}' 缺 leaf_metrics 声明")


_validate_registry()


def r15_gate_registry() -> dict[str, dict[str, Any]]:
    """注册表深拷贝(调用方不得原地修改权威状态)。"""
    return json.loads(json.dumps(R15_GATE_REGISTRY))


def r15_gate_topology_payload() -> dict[str, Any]:
    """进 plan/final/report 的拓扑声明 payload。"""
    registry = r15_gate_registry()
    binding_checks = sorted(
        k for k, v in registry.items() if v["binding"])
    diagnostic_checks = sorted(
        k for k, v in registry.items() if not v["binding"])
    return {
        "version": R15_GATE_TOPOLOGY_VERSION,
        "iteration": "r15",
        "binding_checks": binding_checks,
        "diagnostic_only_checks": diagnostic_checks,
        "cue_semantic_binding_source": R15_CUE_SEMANTIC_BINDING_SOURCE,
        "cue_metrics": list(R15_CUE_METRICS),
        "matched_responsibilities": list(
            R15_MATCHED_CORPUS_RESPONSIBILITIES),
        "independent_marginal_responsibilities": list(
            R15_INDEPENDENT_MARGINAL_RESPONSIBILITIES),
        "independent_marginal_leaves": list(
            R15_INDEPENDENT_MARGINAL_LEAVES),
        "dedicated_semantic_leaves": list(
            R15_DEDICATED_SEMANTIC_LEAVES),
        "matched_point_diagnostic_thresholds": dict(
            R15_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS),
        "registry": registry,
    }


def r15_gate_topology_digest(payload: dict[str, Any] | None = None
                             ) -> str:
    """注册表内容的规范 digest(r15gt- 前缀)。"""
    body = payload if payload is not None else r15_gate_topology_payload()
    return "r15gt-" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def r15_cue_semantic_binding_uniqueness() -> dict[str, Any]:
    """v2:cue rate metric 的 binding source 唯一性(fail closed)。

    与 R14 的差异:
    - 遍历全部 binding 条目的 metric_scope(构造期已保证键存在,
      不再有 optional 缺省——R14 漏检的机械根源);
    - 交叉检查:任一 binding 条目的 leaf_metrics 不得携带 cue
      metric 规范名(防止把 cue rate 指标以 leaf 形式塞进任何
      binding 检查——传递闭包防线);
    - independent_cue_point_diagnostics 是 diagnostic 条目,
      其 metric_scope 覆盖 cue metrics 但 binding=False,
      不构成第二 binding source。
    """
    registry = R15_GATE_REGISTRY
    cue_set = set(R15_CUE_METRICS)
    sources: dict[str, list[str]] = {}
    leaf_violations: list[str] = []
    for name, entry in registry.items():
        if not entry["binding"]:
            continue
        scope = set(entry.get("metric_scope", ()))
        if scope & cue_set:
            sources.setdefault(
                entry["authoritative_source"], []).append(name)
        leaf_hit = sorted(set(entry.get("leaf_metrics", ())) & cue_set)
        if leaf_hit:
            leaf_violations.append(
                f"{name}: leaf_metrics 含 cue metric {leaf_hit}"
                "(cue rate 指标只能经 dedicated binding 条目)")
    unique_ok = (list(sources) == [R15_CUE_SEMANTIC_BINDING_SOURCE]
                 and not leaf_violations)
    return {
        "pass": unique_ok,
        "binding_sources_for_cue_semantics": sources,
        "expected_unique_source": R15_CUE_SEMANTIC_BINDING_SOURCE,
        "leaf_metric_violations": leaf_violations,
        "rule": (
            "binding 条目 metric_scope 传递闭包唯一 source + "
            "leaf_metrics 不含 cue metric 名(R15 §六-5)"),
    }


def r15_binding_status(check: str) -> dict[str, Any]:
    """查询单个 check 的权威 binding status(fail closed:未注册即错)。"""
    try:
        entry = R15_GATE_REGISTRY[check]
    except KeyError as exc:
        raise RuntimeError(
            f"check '{check}' 未在 R15 gate topology 注册表注册——"
            "所有 verdict 级 check 必须在单一权威来源登记 binding "
            "status(R15 §四-5)") from exc
    return {"binding": entry["binding"],
            "diagnostic_only": entry["diagnostic_only"],
            "authoritative_source": entry["authoritative_source"]}


def r15_binding_lineage(detail_sources: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
    """v2 binding lineage audit(§六;fail closed)。

    对每个 binding 条目:
    - 声明侧:registry leaf_metrics(构造期已保证非空);
    - 实际侧:detail_sources[check] 若携带 aggregator 自报
      "binding_leaf_checks"(原子叶子清单)则强制比对
      (undeclared leaf / declared-but-missing 都 FAIL——
      测试 E"隐藏添加未声明 cue_recall leaf"的检出通道);
    - cue metric 相关条目(metric_scope 非空):自报缺失即 FAIL
      (fail closed;共享 r6 aggregator 的条目 scope 为空,
      声明侧记录 no_self_report)。
    """
    registry = R15_GATE_REGISTRY
    detail_sources = detail_sources or {}
    cue_set = set(R15_CUE_METRICS)
    entries: dict[str, Any] = {}
    problems: list[str] = []
    for name, entry in registry.items():
        if not entry["binding"]:
            continue
        declared = sorted(entry.get("leaf_metrics", ()))
        if not declared:
            problems.append(f"{name}: 声明 leaf_metrics 为空")
            entries[name] = {"declared": declared, "status": "FAIL"}
            continue
        detail = detail_sources.get(name)
        scope_is_cue = bool(set(entry.get("metric_scope", ())) & cue_set)
        if detail is None:
            status = "no_detail_source(声明侧 only)"
            if scope_is_cue:
                problems.append(
                    f"{name}: cue metric binding 缺 detail 源")
                status = "FAIL"
            entries[name] = {"declared": declared, "status": status}
            continue
        if not isinstance(detail, dict):
            entries[name] = {
                "declared": declared,
                "status": "detail_not_dict(共享 aggregator;"
                          "声明侧 only)",
            }
            continue
        self_reported = detail.get("binding_leaf_checks")
        if self_reported is None:
            status = "no_self_report(共享 aggregator;声明侧 only)"
            if scope_is_cue:
                problems.append(
                    f"{name}: cue metric binding 无 aggregator "
                    "自报 binding_leaf_checks(fail closed)")
                status = "FAIL"
            entries[name] = {"declared": declared, "status": status}
            continue
        actual = sorted(str(x) for x in self_reported)
        undeclared = [x for x in actual if x not in declared]
        missing = [x for x in declared if x not in actual]
        ok = not undeclared and not missing
        if undeclared:
            problems.append(
                f"{name}: aggregator 自报未声明叶子 {undeclared}")
        if missing:
            problems.append(
                f"{name}: 声明叶子无 aggregator 自报 {missing}")
        entries[name] = {
            "declared": declared,
            "actual": actual,
            "match": ok,
            "status": "match" if ok else "FAIL",
        }
    return {
        "format": "cur261-r15-binding-lineage-v2",
        "pass": not problems,
        "problems": problems,
        "entries": entries,
        "rule": (
            "每个 binding check 的 leaf 声明与真实 aggregator 自报"
            "一致;cue metric binding 强制自报(R15 §六)"),
    }


def r15_overridden_strict_gate_rule_text() -> dict[str, str]:
    """R6 STRICT_GATE_RULE_IDENTITY 的 R15 修正覆盖键。

    R6 字典的 c2_matched/c2_marginal_guard 条目携带旧拓扑文字。
    R15 plan 展开时用本函数的键覆盖之——不修改共享历史模块。
    """
    return {
        "c2_matched": (
            "difficulty ordering + blockwise adjacent gaps + D3 "
            "absolute margin + fixed-baseline margins + "
            "positive-gap block rate + block/pair/cross-rung "
            "integrity + density + local cue independence + "
            "context observability(A/B 双 carrier);cue/payoff "
            "点估计分离检查仅 diagnostic_only(R15 "
            "GateTopologyReconciliation-v2)"),
        "c2_marginal_guard": (
            "structural 全集:marginal ordering + D3 positive + "
            "fixed-baseline positive margins + integrity + oracle "
            "+ density + local cue independence + context "
            "observability + independent cue canonical "
            "consistency;四类 cue 点指标在独立语料上仅 "
            "diagnostic(不进入本 pass);matched PASS 不可覆盖 "
            "FAIL;无 SE 要求(R15 GateTopologyReconciliation-v2)"),
        "cue_semantic_gate_topology": (
            "cue recall/precision/non-cue FP/payoff-bar false-cue "
            "的唯一 binding source = dedicated 160-block semantic "
            "corpus(cluster-aware LCB/UCB,既有阈值);matched "
            "corpus 点估计与 independent corpus 点指标均 "
            "diagnostic_only;binding lineage 传递闭包一致"
            "(R15 GateTopologyReconciliation-v2)"),
    }
