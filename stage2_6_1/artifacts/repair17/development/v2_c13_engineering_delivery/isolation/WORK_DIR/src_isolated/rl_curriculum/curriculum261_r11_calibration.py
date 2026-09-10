# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11:calibration/holdout 语料执行与 C2 条件组装。

R9 确认输入(本模块直接修复的两类缺陷):
- supervised wrapper 的 namespace 是必填位置参数,而 CLI 少传导致
  TypeError;且 wrapper 内部把 namespace 传进 R6 实现的第三位置参数
  pairs_per_rung(R11 全部 keyword-only,§7);
- supervised 标签 = raw reference policy 直接读 scaled observation
  (R11 换 PolicyVisibleSupervisedLabel-v1,§8)。

其余 runner(fit bank / C1/C3 / C2 matched / C2 independent /
robustness 基元 / density / diagnostics)复用 R6 冻结实现 —— 全部
显式关键字转发(§7.2);semantic corpus 与条件组装沿用 R9 语义
(recall/precision 由 dedicated 160-block semantic corpus 承担;
marginal guard 以 semantics=None 调 R6 统计条件再显式 AND 三语义)。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r6_calibration import (
    generate_fit_bank_r6 as _generate_fit_bank,
    fit_preprocessor_v2_from_bank_r6 as _fit_v2_from_bank,
    run_calibration_corpus_c13_r6 as _run_c13,
    run_c2_matched_corpus_r6 as _run_c2_matched,
    run_c2_independent_corpus_r6 as _run_c2_independent,
    run_generator_stress_r6 as _run_generator_stress,
)
from rl_curriculum.curriculum261_r3_calibration import _binary_metrics
from rl_curriculum.curriculum261_r5_pairs import (
    c2_density_summary,
    density_gate_r5,
)
from rl_curriculum.curriculum261_r6_pairs import (
    c2_matched_conditions,
)
from rl_curriculum.curriculum261_r11_labels import (
    SUPERVISED_LABEL_CONTRACT,
    collect_policy_visible_dataset_r11,
    supervised_dataset_identity_r11,
)
from rl_curriculum.curriculum261_r11_orchestrator import (
    CALIBRATION_PAIRS_PER_RUNG_R11,
    C2_INDEPENDENT_PAIRS_PER_RUNG_R11,
    R11_SUPERVISED_GATE,
    R11_SUPERVISED_MODEL_SEEDS,
    SEMANTIC_BLOCKS_PER_CORPUS_R11,
)
from rl_curriculum.curriculum261_r11_cue_eval import (
    candidate_cue_semantics,
    independent_cue_semantics,
    semantic_cue_gate,
)
from rl_curriculum.curriculum261_r11_design import (
    _reference_long_label_rate,
)
from rl_curriculum.curriculum261_r11_param_pack import (
    load_selected_pack,
    r11_family_rung_params,
    r11_override_for,
)

#: §12.1 rehearsal fit bank 每 rung 对数(tiny)。
REHEARSAL_FIT_PAIRS_PER_RUNG_R11 = 2


def generate_fit_bank_r11(
        namespace: str, pack: dict[str, Any],
        *, pairs_per_rung: int | None = None) -> list[Any]:
    """R6 fit bank 的 keyword-only 转发(§7.1/§7.2)。"""
    return _generate_fit_bank(
        namespace, pack, pairs_per_rung=pairs_per_rung or 6)


def fit_preprocessor_v2_from_bank_r11(
        namespace: str, pack: dict[str, Any], *,
        records: list[Any] | None = None,
        pairs_per_rung: int | None = None,
        parameter_pack_identity: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """R6 V2 fit 的 keyword-only 转发(§7.1/§7.2)。"""
    return _fit_v2_from_bank(
        namespace, pack, records=records,
        pairs_per_rung=pairs_per_rung or 6,
        parameter_pack_identity=parameter_pack_identity)


def run_calibration_corpus_c13_r11(
        preproc_v2: Any, pack: dict[str, Any], namespace: str, *,
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R11,
) -> dict[str, Any]:
    """C1/C3 pair 语料(R6 冻结实现;keyword-only 转发)。"""
    return _run_c13(preproc_v2, pack, namespace,
                    pairs_per_rung=pairs_per_rung)


def run_c2_matched_corpus_r11(
        preproc_v2: Any, pack: dict[str, Any], namespace: str, *,
        n_blocks: int) -> dict[str, Any]:
    """C2 matched block 语料(R6 冻结实现;keyword-only 转发)。"""
    return _run_c2_matched(preproc_v2, pack, namespace,
                           n_blocks=int(n_blocks))


def run_c2_independent_corpus_r11(
        preproc_v2: Any, pack: dict[str, Any], namespace: str, *,
        pairs_per_rung: int = C2_INDEPENDENT_PAIRS_PER_RUNG_R11,
) -> dict[str, Any]:
    """C2 independent marginal 语料(R6 冻结实现;keyword-only 转发)。"""
    return _run_c2_independent(preproc_v2, pack, namespace,
                               pairs_per_rung=pairs_per_rung)


def run_c2_semantic_corpus_r11(
        pack: dict[str, Any], namespace: str, *,
        n_blocks: int = SEMANTIC_BLOCKS_PER_CORPUS_R11,
        out_dir: Path | None = None,
        artifact_name: str | None = None) -> dict[str, Any]:
    """§18/§19 dedicated cue semantic corpus(R9 语义;R11 namespace)。

    gate = candidate-independent 检查(recall LCB ≥ floor / non-cue FP
    UCB ≤0.01 / coverage / per-event K / noise replay)+ selected
    ladder candidate-specific 检查(precision LCB ≥0.85 / payoff
    false-cue UCB ≤0.06)。
    """
    from rl_curriculum.curriculum261_r6_tape import (
        block_attempt_statistics,
        generate_matched_block_with_attempts,
        matched_block_corpus_summary,
    )

    ladder = r11_family_rung_params(FAMILY_C2, pack)
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace=namespace, block_index=i)
        for i in range(int(n_blocks))]
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
        "format": "cur261-r11-semantic-corpus-v1",
        "namespace": namespace,
        "ladder": pack.get("selected_c2_candidate"),
        "n_blocks": int(n_blocks),
        "semantic_blocks_per_corpus_expected":
            SEMANTIC_BLOCKS_PER_CORPUS_R11,
        "shared": shared,
        "candidate": candidate,
        "n_semantic_episodes": 8 * int(n_blocks),
        "pass": bool(shared["pass"] and candidate["pass"]),
    }
    if out_dir is not None:
        from rl_curriculum.curriculum261_r11_design import (
            semantic_artifact_filename_r11,
            write_semantic_artifact_r11,
        )

        expected_name = semantic_artifact_filename_r11(namespace)
        if artifact_name is not None and artifact_name != expected_name:
            raise RuntimeError(
                f"semantic artifact 名 {artifact_name} 与 namespace "
                f"{namespace} 的显式映射 {expected_name} 不一致"
                f"(R11 §8:禁止模糊文件名)")
        dump = dict(result)
        dump["shared"] = {k: v for k, v in shared.items()
                          if k != "event_trace"}
        write_semantic_artifact_r11(
            Path(out_dir), namespace, dump,
            str(pack.get("design_plan_digest", "")),
            event_rows=trace_rows)
        shared["event_trace"] = trace_rows
    return result


def c2_matched_conditions_r11(
        matched: dict[str, Any], pack: dict[str, Any],
) -> dict[str, Any]:
    """C2 matched 完整 gate(R6 统计 + 完整性 + 密度 + local cue +
    context;cue 语义由 dedicated semantic corpus 承担)。"""
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
    ladder = r11_family_rung_params(FAMILY_C2, pack)
    density: dict[str, Any] = {}
    episode_rows = matched["episodes"]  # evaluate 的 per-episode 行
    for r in CURRICULUM261_RUNGS:
        d = c2_density_summary(
            [row for row in episode_rows if row["rung"] == r], r)
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
            "160-block semantic corpus(cue_semantic_*_r11 namespace)"),
    }
    return {
        "format": "cur261-r11-c2-matched-conditions-v1",
        "statistical": base,
        "density_gates": density,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk != "per_quadrant"}
                      for k, v in semantics.items()},
        "checks": checks,
        "pass": bool(all(v for v in checks.values()
                         if isinstance(v, bool))),
    }


def c2_independent_marginal_guard_r11(
        indep: dict[str, Any], pack: dict[str, Any],
        recall_floor_value: float,
) -> dict[str, Any]:
    """C2 independent marginal guard(密度 + 三语义 + point recall)。"""
    from rl_curriculum.curriculum261_r6_pairs import (
        c2_marginal_guard_conditions,
    )
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    ladder = r11_family_rung_params(FAMILY_C2, pack)
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
    r11_semantics_ok = bool(
        semantics["local_cue_independence"]["pass"]
        and semantics["context_observability"]["pass"]
        and cue["pass"])
    guard = dict(base)
    guard["format"] = "cur261-r11-c2-marginal-guard-v1"
    guard["r11_semantics_rule"] = (
        "local cue ∧ context observability ∧ independent cue semantics"
        "(point recall ≥ 0.90 灾难护栏)")
    guard["r11_semantics_pass"] = r11_semantics_ok
    guard["semantics_pass"] = r11_semantics_ok
    guard["pass"] = bool(base["pass"] and r11_semantics_ok)
    return {
        "format": "cur261-r11-c2-independent-marginal-v1",
        "namespace": indep["seed_namespace"],
        "pairs_per_rung": indep["pairs_per_rung"],
        "guard": guard,
        "density_gates": density_gates,
        "cue_semantics": cue,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk not in ("per_quadrant", "per_rung")}
                      for k, v in semantics.items()},
    }


# ---------------------------------------------------- supervised(§8/§17)
def supervised_learnability_run_r11(
        preproc_v2: Any, pack: dict[str, Any], *,
        namespace: str,
        pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG_R11,
        train_pair_limit: int = 6,
        model_seeds: tuple | list = R11_SUPERVISED_MODEL_SEEDS,
        training_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """§17 supervised 正式 gate(PolicyVisibleSupervisedLabel-v1)。

    与 R6/R9 的差异(§2.3/§2.4/§8):
    - namespace / pairs_per_rung / train_pair_limit / model_seeds /
      training_config 全部 keyword-only —— 位置参数错传在签名层杜绝;
    - 数据集不再把 raw reference policy 跑在 scaled episode 上:
      输入 = scaled float32 observation(生产投影),标签 = canonical
      reference 的 causal action(双 env 同步 replay 对齐);
    - 训练循环结构保持 R6(control U/W/B;gated W/B;pair-level
      train/held-out split;[128,128] MLP);
    - 任一 family 的 label 对齐失败 → fail closed(不产出 gate pass)。
    """
    import numpy as np
    from rl_curriculum.ppo262_r2_supervised import train_supervised_mlp

    training_config = dict(training_config or {})
    model_seeds = tuple(int(s) for s in model_seeds)
    out: dict[str, Any] = {
        "format": "cur261-r11-supervised-learnability-v1",
        "iteration": "r11",
        "namespace": namespace,
        "label_contract": SUPERVISED_LABEL_CONTRACT,
        "label_source": "canonical_reference_on_canonical_obs",
        "gate_constants": R11_SUPERVISED_GATE,
        "model_seeds": list(model_seeds),
        "training_config": training_config,
        "families": {},
    }
    alignment_all = True
    overall = True
    for family in CURRICULUM261_FAMILIES:
        override = r11_override_for(family, pack)
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(int(pairs_per_rung)):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace,
                    rung_params_override=override))
        rung_params = r11_family_rung_params(family, pack)
        dataset = collect_policy_visible_dataset_r11(
            records, family, rung_params, preproc_v2,
            eval_namespace=namespace)
        if not dataset["alignment_ok"]:
            alignment_all = False
            out["families"][family] = {
                "error": "label alignment 失败(§8.5)",
                "alignment_failures": dataset["alignment_failures"][:20],
                "pass": False,
            }
            overall = False
            continue
        # ---- pair identity split(§8.3:禁按 bar 打散)----
        train_rows = [r for r in dataset["rows"]
                      if r["pair"] < train_pair_limit]
        test_rows = [r for r in dataset["rows"]
                     if r["pair"] >= train_pair_limit]
        Xtr = np.stack([r["obs"] for r in train_rows]).astype(np.float32)
        ytr = np.asarray([r["action"] for r in train_rows],
                         dtype=np.int64)
        Xte = np.stack([r["obs"] for r in test_rows]).astype(np.float32)
        yte = np.asarray([r["action"] for r in test_rows],
                         dtype=np.int64)
        test_pairs = sorted({(r["rung"], r["pair"]) for r in test_rows})

        controls = ["U", "W", "B"]
        gated_controls = list(R11_SUPERVISED_GATE["gated_controls"])
        seed_reports: list[dict[str, Any]] = []
        # ---- repair R11(B2):distinct model-seed 计数 ----
        # R10 缺陷:n_passing 把 W/B 每个通过的 run 各计 1 —— 同一
        # model seed 的 W+B 双通过被误算成"两个 seeds 通过"
        # (control-run count 冒充 seed count)。R11 合同:对每个
        # gated control(W、B)分别统计通过的 distinct model seeds;
        # W 至少 min_seeds_passing 个 distinct seeds 通过,B 同理;
        # family pass = W 条件 AND B 条件;U 只作诊断,不进入计数;
        # 重复记录同一 seed 不增加计数(集合语义)。
        passing_seeds_by_control: dict[str, set[int]] = {
            c: set() for c in gated_controls}
        per_seed_wb: dict[int, dict[str, bool]] = {}
        for seed in model_seeds:
            for control in controls:
                trained = train_supervised_mlp(
                    Xtr, ytr, control=control, seed=seed,
                    **training_config)
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
                    >= R11_SUPERVISED_GATE[
                        "heldout_balanced_accuracy_min"]
                    and metrics["behavior_gap"]
                    >= R11_SUPERVISED_GATE["behavior_gap_min"])
                if control in gated_controls:
                    if gated:
                        passing_seeds_by_control[control].add(int(seed))
                    per_seed_wb.setdefault(int(seed), {})[control] = gated
                seed_reports.append({
                    "seed": int(seed), "control": control,
                    "gated": gated, "metrics": metrics,
                })
        control_pass = {
            c: len(passing_seeds_by_control[c])
            >= R11_SUPERVISED_GATE["min_seeds_passing"]
            for c in gated_controls}
        family_pass = bool(all(control_pass.values()))
        overall = overall and family_pass
        out["families"][family] = {
            "n_pairs": len(records),
            "pairs_per_rung": int(pairs_per_rung),
            "train_pair_limit": int(train_pair_limit),
            "n_train_rows": int(len(train_rows)),
            "n_test_rows": int(len(test_rows)),
            "distinct_seed_gate": {
                "rule": (
                    "gated controls = W、B;对每个 gated control 分别统计"
                    "通过的 distinct model seeds;W 与 B 各至少 "
                    f"{R11_SUPERVISED_GATE['min_seeds_passing']}/"
                    f"{R11_SUPERVISED_GATE['n_model_seeds']} distinct "
                    "seeds 通过;family pass = W AND B;U 仅诊断不计数;"
                    "重复记录同一 seed 不增加计数"),
                "passing_seed_ids_by_control": {
                    c: sorted(passing_seeds_by_control[c])
                    for c in gated_controls},
                "distinct_seed_count_by_control": {
                    c: len(passing_seeds_by_control[c])
                    for c in gated_controls},
                "control_pass": control_pass,
                "per_seed_wb_results": {
                    str(seed): dict(wb) for seed, wb in
                    sorted(per_seed_wb.items())},
                "u_diagnostic_only": True,
            },
            "n_passing_gated": int(sum(
                len(passing_seeds_by_control[c])
                for c in gated_controls)),
            "pass": family_pass,
            "seed_reports": seed_reports,
            "label_evidence_sample": dataset["evidence"][:3],
        }
        out.setdefault("label_alignment", {})[family] = {
            "alignment_ok": dataset["alignment_ok"],
            "n_alignment_failures": len(dataset["alignment_failures"]),
            "n_rows": dataset["n_rows"],
        }
        out.setdefault("dataset_identity", {})[family] = (
            supervised_dataset_identity_r11(dataset))
    out["alignment_all_ok"] = alignment_all
    out["pass"] = bool(overall and alignment_all)
    return out


def run_generator_stress_r11(
        pack: dict[str, Any], *,
        pairs_per_rung: int = 12,
        namespace: str = "stress_r11") -> dict[str, Any]:
    """generator stress(R6 冻结实现;namespace 显式 stress_r11)。

    R9 缺陷修复:R9 CLI 调用未传 namespace,R6 默认回落历史
    stress_r6 —— R11 wrapper 把 namespace 变为显式 keyword-only
    参数,默认 stress_r11。
    """
    return _run_generator_stress(
        pack, pairs_per_rung=pairs_per_rung, namespace=namespace)


def run_c2_density_diagnostics_r11(
        matched_main: dict[str, Any],
        matched_holdout: dict[str, Any],
        pack: dict[str, Any],
) -> dict[str, Any]:
    """C2 行为密度诊断(matched 双语料;R6 实现)。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        run_c2_density_diagnostics_r6 as _impl,
    )

    return _impl(matched_main, matched_holdout, pack)


def run_c2_diagnostics_r11(records: list[Any]) -> dict[str, Any]:
    """C2 三语义诊断(诊断对照;资格判定用 dedicated semantic corpus)。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        run_c2_diagnostics_r6 as _impl,
    )

    return _impl(records)


__all__ = [
    "generate_fit_bank_r11", "fit_preprocessor_v2_from_bank_r11",
    "run_calibration_corpus_c13_r11", "run_c2_matched_corpus_r11",
    "run_c2_independent_corpus_r11", "run_c2_semantic_corpus_r11",
    "c2_matched_conditions_r11", "c2_independent_marginal_guard_r11",
    "supervised_learnability_run_r11", "run_generator_stress_r11",
    "run_c2_density_diagnostics_r11", "run_c2_diagnostics_r11",
    "load_selected_pack", "SEMANTIC_BLOCKS_PER_CORPUS_R11",
    "REHEARSAL_FIT_PAIRS_PER_RUNG_R11",
]
