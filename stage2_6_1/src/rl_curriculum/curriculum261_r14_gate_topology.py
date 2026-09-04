"""R14 权威 cue semantic gate topology 注册表(单一权威来源)。

R13 暴露的拓扑冲突(机械坐标):
- curriculum261_r13_calibration.py 的 c2_matched_conditions_r13 声明
  cue recall/precision/false-cue 的正式 gate 由 dedicated 160-block
  semantic corpus 承担(delegated note);
- run_c2_diagnostics_r13 的 docstring 定位为"诊断对照";
- 但 r13 final aggregator 把 20-block matched corpus 上的
  cue/payoff 点估计 gate(经 check_c2_cue_payoff_separation,
  cue_recall >= 0.95 等)重新绑定为 verdict 级 c2_semantics_pass
  ——R13 即败于此处(0.948571 < 0.95,差 6 个事件,而 dedicated
  cluster LCB gate 通过)。

R14 权威语义(本模块是唯一来源;design plan / qualification plan /
final aggregator / report / tests 全部从这里取得 binding status):

1. C2 matched corpus(20 blocks)的正式职责(全部 binding):
   difficulty ordering / blockwise adjacent gaps / D3 absolute
   margin / fixed-baseline margins / positive-gap block rate /
   block-pair-cross-rung integrity / density / local cue
   independence / context observability。

2. cue recall / cue precision / non-cue false positive /
   payoff-bar false-cue 的正式 binding gate 仅由 dedicated
   160-block semantic corpus 提供(cluster-aware LCB/UCB,既有
   recall floor;不改阈值/不降样本/不按 R13 结果重定标)。

3. matched corpus 上的 R6 点估计分离检查继续执行并报告,但
   diagnostic_only = True / binding_gate = False;诊断失败不得
   改变 R14 verdict。

4. independent marginal guard 承担 marginal ordering / D3
   positive / fixed-baseline positive margins / integrity /
   density / local/context structural checks;其中 cue 点估计
   仅保留 0.90 灾难护栏(point recall)+ noncue UCB(既有语义)。

不以 R13 observed recall 数值作为任何规则选择依据。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

R14_GATE_TOPOLOGY_VERSION = "GateTopologyReconciliation-v1"

#: matched corpus 点估计诊断保留的 R6 冻结阈值(仅诊断对照)。
R14_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS = {
    "cue_recall_min": 0.95,
    "cue_precision_min": 0.85,
    "non_cue_false_positive_max": 0.01,
    "payoff_bar_false_cue_max": 0.06,
}

#: 唯一 binding source 标识(dedicated 160-block semantic corpus)。
R14_CUE_SEMANTIC_BINDING_SOURCE = (
    "dedicated_160_block_semantic_corpus")

#: matched corpus 的正式职责清单(R14 §四-1;与 R13 delegated note
#: 一致——冲突只在 final aggregator,R14 兑现该声明)。
R14_MATCHED_CORPUS_RESPONSIBILITIES = (
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

#: independent marginal guard 的正式职责清单(R14 §四-4)。
R14_INDEPENDENT_MARGINAL_RESPONSIBILITIES = (
    "marginal_ordering",
    "d3_positive",
    "fixed_baseline_positive_margins",
    "integrity",
    "density",
    "local_context_structural_checks",
)


def _binding(name: str, source: str, rule: str,
             **extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "check": name,
        "binding": True,
        "diagnostic_only": False,
        "authoritative_source": source,
        "rule": rule,
    }
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
R14_GATE_REGISTRY: dict[str, dict[str, Any]] = {
    # --- 工程完整性(binding) ---
    "preprocessing_survival_8_of_8": _binding(
        "preprocessing_survival_8_of_8", "preprocessing_v2_survival",
        "8/8 family survival(fail closed)"),
    "preprocessing_envelope_reload": _binding(
        "preprocessing_envelope_reload", "preprocessor_bundle_reload",
        "final fit state envelope 落盘重载等价"),
    "production_numerical_equivalence": _binding(
        "production_numerical_equivalence",
        "production_preprocessing_equivalence",
        "production 8-feature 逐 bar 数值等价"),
    "observation_space_v2": _binding(
        "observation_space_v2", "observation_space_validation",
        "V2 outer 无界空间契约"),
    "adversarial_out_of_range": _binding(
        "adversarial_out_of_range", "adversarial_probe",
        "out-of-range 输入 fail closed"),
    "reference_equivalence_all": _binding(
        "reference_equivalence_all", "canonical_reference_equivalence",
        "policy-visible canonical reference 全等"),
    "reference_equivalence_canonical_full": _binding(
        "reference_equivalence_canonical_full",
        "canonical_reference_equivalence",
        "canonical scaled full equality"),
    "routing_final_bundle_verified": _binding(
        "routing_final_bundle_verified", "bundle_routing",
        "final namespace routing contract"),
    "reproducibility_all": _binding(
        "reproducibility_all", "determinism_replay",
        "seed 重放全等"),
    "matched_block_reproducibility": _binding(
        "matched_block_reproducibility", "determinism_replay",
        "matched block 重放全等"),
    "latent_isolation": _binding(
        "latent_isolation", "latent_probe",
        "latent 通道隔离"),
    "fresh_seed_disjoint": _binding(
        "fresh_seed_disjoint", "fresh_seed_validity",
        "fresh seed 与正式 seed 不相交"),
    # --- 家族统计 gates(binding) ---
    "c1_strict_pass": _binding(
        "c1_strict_pass", "c1_opportunity_corpus",
        "strict per-corpus AND(kappa;相邻 gap;D3 margin;"
        "fixed-baseline margins)"),
    "c3_strict_pass": _binding(
        "c3_strict_pass", "c3_cost_corpus",
        "strict per-corpus AND(kappa;相邻 gap;D3 margin;"
        "fixed-baseline margins)"),
    "c2_matched_strict_pass": _binding(
        "c2_matched_strict_pass", "matched_ladder_20_blocks",
        "matched corpus 9 项正式职责(difficulty ordering/adjacent "
        "gaps/D3 margin/fixed-baseline margins/positive-gap block "
        "rate/integrity/density/local cue independence/context "
        "observability);cue 点估计不在其中",
        responsibilities=list(R14_MATCHED_CORPUS_RESPONSIBILITIES)),
    "c2_independent_marginal_pass": _binding(
        "c2_independent_marginal_pass",
        "independent_marginal_corpus",
        "marginal ordering/D3 positive/fixed-baseline positive "
        "margins/integrity/density/local-context structural;"
        "cue 点估计仅 0.90 灾难护栏 + noncue UCB(既有语义)",
        responsibilities=list(
            R14_INDEPENDENT_MARGINAL_RESPONSIBILITIES)),
    "c2_dedicated_semantic_corpus_pass": _binding(
        "c2_dedicated_semantic_corpus_pass",
        R14_CUE_SEMANTIC_BINDING_SOURCE,
        "cluster-aware block bootstrap 单侧 95% LCB >= recall_floor"
        "(既有);noncue FP UCB <= 0.01;precision LCB >= 0.85;"
        "payoff-bar false-cue UCB <= 0.06——cue recall/precision/"
        "false-cue 的唯一 binding source",
        metric_scope=("cue_recall", "cue_precision",
                      "non_cue_false_positive",
                      "payoff_bar_false_cue"),
        semantic_blocks_per_corpus=160),
    "c2_local_cue_independence_pass": _binding(
        "c2_local_cue_independence_pass", "matched_ladder_20_blocks",
        "local cue independence(matched corpus 诊断器;binding——"
        "R14 §四-1 matched 正式职责)"),
    "c2_context_observability_pass": _binding(
        "c2_context_observability_pass", "matched_ladder_20_blocks",
        "context observability A/B 双 carrier(matched corpus 诊断器;"
        "binding——R14 §四-1 matched 正式职责)"),
    "c2_density_pass": _binding(
        "c2_density_pass", "matched_ladder_20_blocks",
        "cue-adjacent bar 密度带宽"),
    "conditioning_gate": _binding(
        "conditioning_gate", "conditioning_profile",
        "conditioning 单调性/幅值"),
    "supervised_gate": _binding(
        "supervised_gate", "supervised_learnability",
        "min_seeds_passing gate(既有)"),
    "block_contract_identity": _binding(
        "block_contract_identity", "parameter_pack_binding",
        "pack 绑定 matched ladder contract identity"),
    "cue_semantic_contract_identity": _binding(
        "cue_semantic_contract_identity", "parameter_pack_binding",
        "pack 绑定 cue semantic contract digest"),
    "semantic_block_count_consistent": _binding(
        "semantic_block_count_consistent",
        R14_CUE_SEMANTIC_BINDING_SOURCE,
        "dedicated semantic corpus 块数 == 160 == plan 声明"),
    "selected_block_count_consistent": _binding(
        "selected_block_count_consistent", "parameter_pack_binding",
        "selected block count == pack == 实际"),
    "gate_topology_digest_consistent": _binding(
        "gate_topology_digest_consistent", "r14_gate_registry",
        "plan 携带的 gate_topology_digest == 注册表重算 digest"
        "(单一权威来源的一致性自证)"),
    # --- 诊断(非 binding;失败不得改变 verdict) ---
    "c2_matched_cue_point_diagnostics": _diagnostic(
        "c2_matched_cue_point_diagnostics",
        "matched_ladder_point_estimates",
        "R6 点估计分离检查(check_c2_cue_payoff_separation)在 "
        "matched corpus 上继续执行并报告;阈值冻结保留;"
        "diagnostic_only=True;binding_gate=False;诊断失败不得"
        "改变 R14 verdict(R14 §四-3)",
        thresholds=dict(R14_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS),
        historical_note=("R6 STRICT_GATE_RULE_IDENTITY 曾把该项列入 "
                         "c2_matched binding 条目;R13 plan 原样继承,"
                         "R13 final 据此把点估计 gate 绑定为 "
                         "c2_semantics_pass 并 FAIL——R14 权威注册表"
                         "将该项永久降级为诊断")),
}


def r14_gate_registry() -> dict[str, dict[str, Any]]:
    """注册表深拷贝(调用方不得原地修改权威状态)。"""
    return json.loads(json.dumps(R14_GATE_REGISTRY))


def r14_gate_topology_payload() -> dict[str, Any]:
    """进 plan/final/report 的拓扑声明 payload。"""
    registry = r14_gate_registry()
    binding_checks = sorted(
        k for k, v in registry.items() if v["binding"])
    diagnostic_checks = sorted(
        k for k, v in registry.items() if not v["binding"])
    return {
        "version": R14_GATE_TOPOLOGY_VERSION,
        "iteration": "r14",
        "binding_checks": binding_checks,
        "diagnostic_only_checks": diagnostic_checks,
        "cue_semantic_binding_source": R14_CUE_SEMANTIC_BINDING_SOURCE,
        "matched_responsibilities": list(
            R14_MATCHED_CORPUS_RESPONSIBILITIES),
        "independent_marginal_responsibilities": list(
            R14_INDEPENDENT_MARGINAL_RESPONSIBILITIES),
        "matched_point_diagnostic_thresholds": dict(
            R14_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS),
        "registry": registry,
    }


def r14_gate_topology_digest(payload: dict[str, Any] | None = None
                             ) -> str:
    """注册表内容的规范 digest(r14gt- 前缀)。"""
    body = payload if payload is not None else r14_gate_topology_payload()
    return "r14gt-" + hashlib.sha256(json.dumps(
        body, sort_keys=True, ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def r14_cue_semantic_binding_uniqueness() -> dict[str, Any]:
    """校验:cue recall/precision/false-cue 的 binding source 唯一。

    遍历注册表,任何 binding=True 且 metric_scope 覆盖 cue 语义
    度量的条目,其 authoritative_source 必须等于 dedicated
    semantic corpus。这是"同一 metric 不得在两个 corpus 上以两套
    判据重复决定 verdict"的机器化(R14 §四-4/§四-5)。
    """
    registry = R14_GATE_REGISTRY
    cue_metrics = {"cue_recall", "cue_precision",
                   "non_cue_false_positive", "payoff_bar_false_cue"}
    sources: dict[str, list[str]] = {}
    for name, entry in registry.items():
        scope = set(entry.get("metric_scope", ()))
        if entry["binding"] and scope & cue_metrics:
            sources.setdefault(
                entry["authoritative_source"], []).append(name)
    unique_ok = list(sources) == [R14_CUE_SEMANTIC_BINDING_SOURCE]
    return {
        "pass": unique_ok,
        "binding_sources_for_cue_semantics": sources,
        "expected_unique_source": R14_CUE_SEMANTIC_BINDING_SOURCE,
    }


def r14_binding_status(check: str) -> dict[str, Any]:
    """查询单个 check 的权威 binding status(fail closed:未注册即错)。"""
    try:
        entry = R14_GATE_REGISTRY[check]
    except KeyError as exc:
        raise RuntimeError(
            f"check '{check}' 未在 R14 gate topology 注册表注册——"
            "所有 verdict 级 check 必须在单一权威来源登记 binding "
            "status(R14 §四-5)") from exc
    return {"binding": entry["binding"],
            "diagnostic_only": entry["diagnostic_only"],
            "authoritative_source": entry["authoritative_source"]}


def r14_overridden_strict_gate_rule_text() -> dict[str, str]:
    """R6 STRICT_GATE_RULE_IDENTITY 的 R14 修正覆盖键。

    R6 字典的 c2_matched/c2_marginal_guard 条目携带旧拓扑文字
    ("cue/payoff separation" 列为 matched binding 条目)。R14 plan
    展开时用本函数的键覆盖之——不修改共享历史模块 r6_pairs.py。
    """
    return {
        "c2_matched": (
            "difficulty ordering + blockwise adjacent gaps + D3 "
            "absolute margin + fixed-baseline margins + "
            "positive-gap block rate + block/pair/cross-rung "
            "integrity + density + local cue independence + "
            "context observability(A/B 双 carrier);cue/payoff "
            "点估计分离检查仅 diagnostic_only(R14 "
            "GateTopologyReconciliation-v1)"),
        "c2_marginal_guard": (
            "marginal ordering + D3 positive + fixed-baseline "
            "positive margins + integrity + density + "
            "local/context structural checks;cue 点估计仅 0.90 "
            "灾难护栏 + noncue UCB;matched PASS 不可覆盖 FAIL;"
            "无 SE 要求(R14 GateTopologyReconciliation-v1)"),
        "cue_semantic_gate_topology": (
            "cue recall/precision/non-cue FP/payoff-bar false-cue "
            "的唯一 binding source = dedicated 160-block semantic "
            "corpus(cluster-aware LCB/UCB,既有阈值);matched "
            "corpus 点估计 diagnostic_only"),
    }
