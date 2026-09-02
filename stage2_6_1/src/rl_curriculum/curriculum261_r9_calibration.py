# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R9:calibration/holdout 语料执行与 C2 R9 条件组装。

fit bank / C1/C3 / C2 matched / C2 independent / supervised / V2
robustness / stress 全部复用 R6 冻结实现(namespace 参数化,R9 传
r9 namespace + R9 pack;R6 模块零修改)。R9 变更:
- §28/§29 新增 dedicated cue semantic corpus(160 matched blocks,
  selected ladder;calibration/holdout/final 三阶段独立执行并各自
  gate:recall LCB ≥ floor / non-cue FP UCB / selected ladder precision
  LCB ≥0.85 / payoff false-cue UCB ≤0.06 / per-event K / noise replay);
- C2 matched strict 条件 = R6 _blockwise_conditions(ordering/gaps
  κ=1.5×blockSE/D3/基线 margins/block integrity/oracle)+ shared
  tape + 密度 + local cue independence + context observability
  (cue recall/precision 移交 dedicated semantic corpus;§29);
- C2 independent marginal guard 语义修正:R6 冻结实现的 semantics 槽
  检查 cue_payoff_separation 键(R7 误传 cue_semantics;R7 未执行
  故未暴露)——R9 以 semantics=None 调用统计条件,显式 AND
  (local cue ∧ context ∧ v2 independent cue semantics:point recall
  ≥0.90 灾难护栏)。
"""

from __future__ import annotations

from pathlib import Path
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
from rl_curriculum.curriculum261_r9_cue_eval import (
    candidate_cue_semantics,
    independent_cue_semantics,
    semantic_cue_gate,
)
from rl_curriculum.curriculum261_r9_design import (
    _reference_long_label_rate,
)
from rl_curriculum.curriculum261_r9_param_pack import (
    load_selected_pack,
    r9_family_rung_params,
)

CALIBRATION_PAIRS_PER_RUNG_R9 = 10
C2_INDEPENDENT_PAIRS_PER_RUNG_R9 = 20
#: §28/§29 dedicated semantic corpus 规模(与 design 阶段一致 = 160)。
SEMANTIC_BLOCKS_PER_CORPUS_R9 = 160


def generate_fit_bank_r9(
        namespace: str, pack: dict[str, Any],
        pairs_per_rung: int | None = None,
) -> list[Any]:
    return _generate_fit_bank(
        namespace, pack, pairs_per_rung or 6)


def fit_preprocessor_v2_from_bank_r9(
        namespace: str, pack: dict[str, Any],
        records: list[Any] | None = None,
        pairs_per_rung: int | None = None,
        parameter_pack_identity: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    return _fit_v2_from_bank(
        namespace, pack, records,
        pairs_per_rung or 6,
        parameter_pack_identity=parameter_pack_identity)


def run_calibration_corpus_c13_r9(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R9,
) -> dict[str, Any]:
    return _run_c13(preproc_v2, pack, namespace, pairs_per_rung)


def run_c2_matched_corpus_r9(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        n_blocks: int,
) -> dict[str, Any]:
    return _run_c2_matched(preproc_v2, pack, namespace, n_blocks)


def run_c2_independent_corpus_r9(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        pairs_per_rung: int = C2_INDEPENDENT_PAIRS_PER_RUNG_R9,
) -> dict[str, Any]:
    return _run_c2_independent(preproc_v2, pack, namespace,
                               pairs_per_rung)


def run_c2_semantic_corpus_r9(
        pack: dict[str, Any], namespace: str,
        n_blocks: int = SEMANTIC_BLOCKS_PER_CORPUS_R9,
        out_dir: Path | None = None,
        artifact_name: str | None = None,
) -> dict[str, Any]:
    """§28/§29 dedicated cue semantic corpus(160 matched blocks,
    selected ladder;calibration/holdout/final 三阶段独立执行)。

    gate = §15 candidate-independent 检查(recall LCB ≥ floor / non-cue
    FP UCB ≤0.01 / coverage ≥3600 / per-event K / noise replay)+
    §29 selected ladder candidate-specific 检查(precision LCB ≥0.85 /
    payoff false-cue UCB ≤0.06 按 rung × side)。
    """
    from rl_curriculum.curriculum261_r6_tape import (
        block_attempt_statistics,
        generate_matched_block_with_attempts,
        matched_block_corpus_summary,
    )

    ladder = r9_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace=namespace, block_index=i)
        for i in range(n_blocks)]
    shared = semantic_cue_gate(
        blocks, ladder, thresholds,
        recall_floor_value=float(pack["recall_floor"]),
        label=f"selected@{namespace}")
    candidate = candidate_cue_semantics(
        blocks, pack.get("selected_c2_candidate", "selected"),
        thresholds)
    shared["block_attempt_stats"] = block_attempt_statistics(blocks)
    shared["block_corpus_summary"] = matched_block_corpus_summary(blocks)
    trace_rows = shared.pop("event_trace", [])
    result = {
        "format": "cur261-r9-semantic-corpus-v1",
        "namespace": namespace,
        "ladder": pack.get("selected_c2_candidate"),
        "n_blocks": n_blocks,
        "semantic_blocks_per_corpus_expected":
            SEMANTIC_BLOCKS_PER_CORPUS_R9,
        "shared": shared,
        "candidate": candidate,
        "n_semantic_episodes": 8 * n_blocks,
        "pass": bool(shared["pass"] and candidate["pass"]),
    }
    if out_dir is not None:
        from rl_curriculum.curriculum261_r9_design import (
            write_semantic_artifact_r9,
        )
        from rl_curriculum.curriculum261_r9_design import (
            semantic_artifact_filename_r9,
        )

        expected_name = semantic_artifact_filename_r9(namespace)
        if artifact_name is not None and artifact_name != expected_name:
            raise RuntimeError(
                f"semantic artifact 名 {artifact_name} 与 namespace "
                f"{namespace} 的显式映射 {expected_name} 不一致"
                f"(§R9-8:禁止模糊文件名)")
        dump = dict(result)
        dump["shared"] = {k: v for k, v in shared.items()
                          if k != "event_trace"}
        write_semantic_artifact_r9(
            Path(out_dir), namespace, dump,
            str(pack.get("design_plan_digest", "")),
            event_rows=trace_rows)
        shared["event_trace"] = trace_rows
    return result


def c2_matched_conditions_r9(
        matched: dict[str, Any], pack: dict[str, Any],
) -> dict[str, Any]:
    """§29 C2 matched 完整 gate(R6 统计条件 + 完整性 + 密度 +
    local cue + context;cue 语义由 dedicated semantic corpus 承担)。"""
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
    ladder = r9_family_rung_params(FAMILY_C2, pack)
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
        "cue_semantics_delegated_note": (
            "cue recall/precision/false-cue 的正式 gate 在 dedicated "
            "160-block semantic corpus(cue_semantic_*_r9 namespace;"
            "§29)"),
    }
    return {
        "format": "cur261-r9-c2-matched-conditions-v1",
        "statistical": base,
        "density_gates": density,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk != "per_quadrant"}
                      for k, v in semantics.items()},
        "checks": checks,
        "pass": bool(all(v for v in checks.values()
                         if isinstance(v, bool))),
    }


def c2_independent_marginal_guard_r9(
        indep: dict[str, Any], pack: dict[str, Any],
        recall_floor_value: float,
) -> dict[str, Any]:
    """§29 C2 independent marginal guard(密度 + 三语义 + v2 cue)。"""
    from rl_curriculum.curriculum261_r4_pairs import rung_report_r4
    from rl_curriculum.curriculum261_r6_pairs import (
        c2_marginal_guard_conditions,
    )
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    ladder = r9_family_rung_params(FAMILY_C2, pack)
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
    base = c2_marginal_guard_conditions(
        report,
        density={"pass": all(d["pass"] for d in density_gates.values())},
        semantics=None)
    r9_semantics_ok = bool(
        semantics["local_cue_independence"]["pass"]
        and semantics["context_observability"]["pass"]
        and cue["pass"])
    guard = dict(base)
    guard["format"] = "cur261-r9-c2-marginal-guard-v1"
    guard["r9_semantics_rule"] = (
        "local cue ∧ context observability ∧ independent cue semantics"
        "(point recall ≥ 0.90 灾难护栏;§26)")
    guard["r9_semantics_pass"] = r9_semantics_ok
    guard["semantics_pass"] = r9_semantics_ok
    guard["pass"] = bool(base["pass"] and r9_semantics_ok)
    return {
        "format": "cur261-r9-c2-independent-marginal-v1",
        "namespace": indep["seed_namespace"],
        "pairs_per_rung": indep["pairs_per_rung"],
        "guard": guard,
        "density_gates": density_gates,
        "cue_semantics": cue,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk not in ("per_quadrant", "per_rung")}
                      for k, v in semantics.items()},
    }


def supervised_learnability_run_r9(
        preproc_v2: Any, pack: dict[str, Any], namespace: str,
        **kwargs: Any) -> dict[str, Any]:
    """§29 supervised gate(transformed-observation 可学性;复用 R6)。"""
    return _supervised_run(preproc_v2, pack, namespace, **kwargs)


def run_generator_stress_r9(pack: dict[str, Any],
                            **kwargs: Any) -> dict[str, Any]:
    return _run_generator_stress(pack, **kwargs)


def run_c2_density_diagnostics_r9(
        matched_main: dict[str, Any],
        matched_holdout: dict[str, Any],
        pack: dict[str, Any],
) -> dict[str, Any]:
    """C2 行为密度诊断(matched 双语料;复用 R6 实现)。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        run_c2_density_diagnostics_r6 as _impl,
    )

    return _impl(matched_main, matched_holdout, pack)


def run_c2_diagnostics_r9(records: list[Any]) -> dict[str, Any]:
    """C2 三语义诊断(local cue/context observability/R6 点阈值
    separation——最后一项仅诊断对照,R9 资格判定用 dedicated semantic
    corpus 的 cluster-aware cue semantics)。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        run_c2_diagnostics_r6 as _impl,
    )

    return _impl(records)


__all__ = [
    "generate_fit_bank_r9", "fit_preprocessor_v2_from_bank_r9",
    "run_calibration_corpus_c13_r9", "run_c2_matched_corpus_r9",
    "run_c2_independent_corpus_r9", "run_c2_semantic_corpus_r9",
    "c2_matched_conditions_r9", "c2_independent_marginal_guard_r9",
    "supervised_learnability_run_r9", "run_generator_stress_r9",
    "run_c2_density_diagnostics_r9", "run_c2_diagnostics_r9",
    "load_selected_pack", "SEMANTIC_BLOCKS_PER_CORPUS_R9",
]
