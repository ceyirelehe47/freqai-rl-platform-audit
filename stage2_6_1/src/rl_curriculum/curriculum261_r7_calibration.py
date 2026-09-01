# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R7:calibration/holdout 语料执行与 C2 R7 条件组装。

fit bank / C1/C3 / C2 matched / C2 independent / supervised / V2
robustness / stress 全部复用 R6 冻结实现(namespace 参数化,R7 传
r7 namespace + R7 pack;R6 模块零修改)。R7 新增:
- C2 matched strict 条件 = R6 _blockwise_conditions(ordering/gaps
  κ=1.5×blockSE/D3/基线 margins/block integrity/oracle) +
  shared tape + 密度 + local cue independence + context
  observability + cluster-aware cue semantics(shared LCB/UCB +
  candidate-specific payoff-fc UCB / precision LCB)(§24);
- C2 independent marginal guard 的 cue semantics =
  independent_cue_semantics(pair cluster;§21/§24)。
"""

from __future__ import annotations

from typing import Any

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r6_calibration import (
    generate_fit_bank_r6 as _generate_fit_bank,
    fit_preprocessor_v2_from_bank_r6 as _fit_v2_from_bank,
    run_calibration_corpus_c13_r6 as _run_c13,
    run_c2_matched_corpus_r6 as _run_c2_matched,
    run_c2_independent_corpus_r6 as _run_c2_independent,
    run_generator_stress_r6 as _run_generator_stress,
    supervised_learnability_run_r6 as _supervised_run,
)
from rl_curriculum.curriculum261_r5_pairs import (
    c2_density_summary,
    density_gate_r5,
)
from rl_curriculum.curriculum261_r6_pairs import (
    c2_matched_conditions,
)
from rl_curriculum.curriculum261_r5_pairs import density_gate_r5
from rl_curriculum.curriculum261_r7_cue_eval import (
    candidate_cue_semantics,
    independent_cue_semantics,
    shared_cue_semantic_gate,
)
from rl_curriculum.curriculum261_r7_design import (
    _reference_long_label_rate,
)
from rl_curriculum.curriculum261_r7_param_pack import (
    load_selected_pack,
    r7_family_rung_params,
)

CALIBRATION_PAIRS_PER_RUNG_R7 = 10
C2_INDEPENDENT_PAIRS_PER_RUNG_R7 = 20


def generate_fit_bank_r7(
        namespace: str, pack: dict[str, Any],
        pairs_per_rung: int | None = None,
) -> list[Any]:
    return _generate_fit_bank(
        namespace, pack, pairs_per_rung or 6)


def fit_preprocessor_v2_from_bank_r7(
        namespace: str, pack: dict[str, Any],
        records: list[Any] | None = None,
        pairs_per_rung: int | None = None,
        parameter_pack_identity: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    return _fit_v2_from_bank(
        namespace, pack, records,
        pairs_per_rung or 6,
        parameter_pack_identity=parameter_pack_identity)


def run_calibration_corpus_c13_r7(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R7,
) -> dict[str, Any]:
    return _run_c13(preproc_v2, pack, namespace, pairs_per_rung)


def run_c2_matched_corpus_r7(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        n_blocks: int,
) -> dict[str, Any]:
    return _run_c2_matched(preproc_v2, pack, namespace, n_blocks)


def run_c2_independent_corpus_r7(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        pairs_per_rung: int = C2_INDEPENDENT_PAIRS_PER_RUNG_R7,
) -> dict[str, Any]:
    return _run_c2_independent(preproc_v2, pack, namespace,
                               pairs_per_rung)


def c2_r7_semantics_block(
        matched: dict[str, Any], pack: dict[str, Any],
        recall_floor_value: float,
) -> dict[str, Any]:
    """§24 C2 matched 的 cluster-aware cue 语义(shared + candidate)。

    shared gate 在 calibration/holdout/final 语料上重算(该语料的
    blocks;candidate 只有一个(selected),cross-candidate digest
    退化为单 candidate——一致性由 matched tape 合同保证,design 阶段
    已显式验证)。
    """
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    blocks = matched["blocks"]
    shared = shared_cue_semantic_gate(
        {"__selected__": blocks}, thresholds,
        recall_floor_value=recall_floor_value)
    candidate = candidate_cue_semantics(
        blocks, pack.get("selected_c2_candidate", "selected"),
        thresholds)
    return {
        "shared": shared,
        "candidate": candidate,
        "pass": bool(shared["pass"] and candidate["pass"]),
    }


def c2_matched_conditions_r7(
        matched: dict[str, Any], pack: dict[str, Any],
        recall_floor_value: float,
) -> dict[str, Any]:
    """§24 C2 matched 完整 gate(R6 统计条件 + R7 cue 语义)。"""
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    base = c2_matched_conditions(matched["block_table"])
    records = [blk.pair_records[rung]
               for blk in matched["blocks"]
               for rung in CURRICULUM261_RUNGS]
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    ladder = r7_family_rung_params(FAMILY_C2, pack)
    density: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        d = c2_density_summary(
            [blk.pair_records[r] for blk in matched["blocks"]], r)
        d["reference_long_label_rate"] = _reference_long_label_rate(
            [blk.pair_records[r] for blk in matched["blocks"]],
            ladder[r], thresholds)
        density[r] = density_gate_r5(d)
    semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
    }
    cue = c2_r7_semantics_block(matched, pack, recall_floor_value)
    summary = matched["block_corpus_summary"]
    checks = {
        "statistical_block_conditions": base["pass"],
        "shared_tape_cross_rung": bool(
            summary["all_cross_rung_matching_pass"]),
        "block_pair_integrity": bool(
            summary["all_rung_pair_integrity_pass"]),
        "density_pass": bool(all(d["pass"] for d in density.values())),
        "local_cue_independence": bool(
            semantics["local_cue_independence"]["pass"]),
        "context_observability": bool(
            semantics["context_observability"]["pass"]),
        "cluster_aware_cue_semantics": cue["pass"],
    }
    return {
        "format": "cur261-r7-c2-matched-conditions-v1",
        "statistical": base,
        "density_gates": density,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk != "per_quadrant"}
                      for k, v in semantics.items()},
        "cue_semantics": cue,
        "checks": checks,
        "pass": bool(all(checks.values())),
    }


def c2_independent_marginal_guard_r7(
        indep: dict[str, Any], pack: dict[str, Any],
        recall_floor_value: float,
) -> dict[str, Any]:
    """§24 C2 independent marginal guard(密度 + 三语义 + R7 cue)。"""
    from rl_curriculum.curriculum261_r4_pairs import rung_report_r4
    from rl_curriculum.curriculum261_r6_pairs import (
        c2_marginal_guard_conditions,
    )
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    ladder = r7_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    report = indep["report"]
    density_gates: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        d = c2_density_summary(
            [row for row in report["by_rung"][r]["episodes"]
             if row["rung"] == r], r)
        d["reference_long_label_rate"] = _reference_long_label_rate(
            [rec for rec in indep["records"] if rec.rung == r],
            ladder[r], thresholds)
        density_gates[r] = density_gate_r5(d)
    records = indep["records"]
    cue = independent_cue_semantics(
        records, pack.get("selected_c2_candidate", "selected"),
        thresholds, recall_floor_value=recall_floor_value)
    semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
        "cue_semantics": cue,
    }
    guard = c2_marginal_guard_conditions(
        report,
        density={"pass": all(d["pass"] for d in density_gates.values())},
        semantics=semantics)
    return {
        "format": "cur261-r7-c2-independent-marginal-v1",
        "namespace": indep["seed_namespace"],
        "pairs_per_rung": indep["pairs_per_rung"],
        "guard": guard,
        "density_gates": density_gates,
        "cue_semantics": cue,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk not in ("per_quadrant", "per_rung")}
                      for k, v in semantics.items()},
    }


def supervised_learnability_run_r7(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        **kwargs: Any) -> dict[str, Any]:
    """§24 supervised gate(transformed-observation 可学性;复用 R6)。"""
    return _supervised_run(preproc_v2, pack, namespace, **kwargs)


def run_generator_stress_r7(pack: dict[str, Any],
                            **kwargs: Any) -> dict[str, Any]:
    return _run_generator_stress(pack, **kwargs)


def run_c2_density_diagnostics_r7(
        matched_main: dict[str, Any],
        matched_holdout: dict[str, Any],
        pack: dict[str, Any],
) -> dict[str, Any]:
    """C2 行为密度诊断(matched 双语料;复用 R6 实现,calibration/
    holdout/final 均可传同结构 matched 语料)。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        run_c2_density_diagnostics_r6 as _impl,
    )

    return _impl(matched_main, matched_holdout, pack)


def run_c2_diagnostics_r7(records: list[Any]) -> dict[str, Any]:
    """C2 三语义诊断(local cue/context observability/R6 点阈值
    separation——最后一项仅诊断对照,R7 资格判定用 cluster-aware
    cue semantics)。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        run_c2_diagnostics_r6 as _impl,
    )

    return _impl(records)


__all__ = [
    "generate_fit_bank_r7", "fit_preprocessor_v2_from_bank_r7",
    "run_calibration_corpus_c13_r7", "run_c2_matched_corpus_r7",
    "run_c2_independent_corpus_r7", "c2_r7_semantics_block",
    "c2_matched_conditions_r7", "c2_independent_marginal_guard_r7",
    "supervised_learnability_run_r7", "run_generator_stress_r7",
    "run_c2_density_diagnostics_r7", "run_c2_diagnostics_r7",
    "load_selected_pack",
]
