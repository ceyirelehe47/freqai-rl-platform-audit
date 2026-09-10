# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:唯一 pair 统计、strict per-corpus gate、
全-ladder n=10 功效模拟与 C2 行为密度 gate。

§19 唯一 PASS 口径(在生成任何 calibration data 前冻结):
- calibration_r5 与 calibration_holdout_r5 **各自独立**满足全部条件
  (AND);pooled 双语料统计仅作诊断字段,**不得把任一 corpus FAIL 救成
  PASS**;
- κ = 1.5(逐 corpus pair-cluster SE 口径)。

strict per-corpus 条件(每 family 每 corpus):
1. D0 > D1 > D2 > D3(难度 = reference_pair − always_flat_pair);
2. 每个相邻 gap > 0 且 >= 1.5 × pair-cluster SE(二次合成);
3. D3 difficulty > 0 且 >= 1.5 × pair-cluster SE;
4. 每个固定 required baseline 的 margin(逐基线,全部 rung):
   mean > 0 且 >= 1.5 × SE(无 hindsight);
5. pair integrity = 1.0;6. oracle positive;
7. attempts 纪律;8. C2 密度 gate(median reference trades >= 8、
   reference long label rate >= 1.5%)。

全部统计从唯一 pair 证据表(curriculum261_r4_pairs 原语,R5 复用同一
实现——evaluator 与 gate 逐数值一致)派生。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_r4_pairs import (
    CALIBRATION_PAIRS_PER_RUNG_R4,
    EVAL_CFG,
    FORMAL_PAIRS_PER_RUNG,
    PAIR_TABLE_SCHEMA,
    RAW_SCHEMA,
    ROBUSTNESS_KAPPA_R4,
    bootstrap_mean_ci,
    build_pair_evidence_table,
    cluster_stats,
    difficulty_metric_validation,
    difficulty_series,
    evaluate_pair_corpus_r4,
    margin_series,
    pair_table_schema_identity,
    pooled_conditions_r4,
    rung_report_r4,
    table_series,
)
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES

#: R5 正式 κ(§19 冻结;与 R4 相同数值,但口径唯一 strict per-corpus)。
ROBUSTNESS_KAPPA_R5 = 1.5
#: 正式 qualification 每 rung pair 数。
FORMAL_PAIRS_PER_RUNG_R5 = FORMAL_PAIRS_PER_RUNG
CALIBRATION_PAIRS_PER_RUNG_R5 = CALIBRATION_PAIRS_PER_RUNG_R4
#: bootstrap/模拟常量(与 R4 数值口径一致;RNG seed 独立登记)。
R5_BOOTSTRAP_RESAMPLES = 5000
R5_BOOTSTRAP_SEED = 20260911
R5_GATE_SIM_RESAMPLES = 20000
R5_GATE_SIM_SEED = 20260912

#: C2 行为密度门槛(§11 预注册;n_trades = buy+sell 双腿口径,与
#: evaluator EpisodeResult 一致;历史分布 ~12-13 >> 8,label rate
#: ~3.3% >> 1.5%,门槛取任务书建议值,不做放宽)。
C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES = 8.0
C2_DENSITY_MIN_REFERENCE_LONG_RATE = 0.015

#: R5 strict gate 合同描述(进入 plan/design plan)。
STRICT_GATE_RULE_IDENTITY = {
    "rule": "strict per-corpus AND(calibration_r5 AND "
            "calibration_holdout_r5 各自独立满足全部条件;pooled 仅诊断)",
    "kappa": ROBUSTNESS_KAPPA_R5,
    "per_corpus_conditions": [
        "ordering D0>D1>D2>D3",
        "每个相邻 gap > 0 且 >= 1.5 x pair-cluster SE(二次合成)",
        "D3 > 0 且 >= 1.5 x pair-cluster SE",
        "逐固定基线 margin(全部 rung)> 0 且 >= 1.5 x SE",
        "pair integrity = 1.0", "oracle positive",
        "attempts 纪律", "C2 密度 gate(仅 c2)",
    ],
    "pooled_rule": "仅诊断字段;不得覆盖任何 corpus FAIL",
    "locked_before_data": "本字典进入 design plan 与 qualification "
                          "plan;calibration data 生成后禁止修改",
}


def strict_gate_rule_identity() -> str:
    import hashlib
    import json

    return "r5sg-" + hashlib.sha256(json.dumps(
        STRICT_GATE_RULE_IDENTITY, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8")).hexdigest()


# ------------------------------------------------- strict per-corpus 条件
def corpus_conditions_r5(family_report: dict[str, Any],
                         kappa: float = ROBUSTNESS_KAPPA_R5,
                         ) -> dict[str, Any]:
    """单 corpus 的 R5 strict 全条件(gate/final 共用同一函数源)。

    与 R4 corpus_conditions_r4 的差异:D3>=κ×SE 与全部相邻 gap>=κ×SE
    是 **pass 的组成部分**(strict per-corpus 口径),不再是诊断字段。
    """
    ladder = family_report["difficulty_ladder"]
    rungs = CURRICULUM261_RUNGS
    means = [ladder[r]["mean"] for r in rungs]
    ordering_ok = bool(means[0] > means[1] > means[2] > means[3])
    d3 = ladder["D3"]
    d3_positive = bool(d3["mean"] > 0.0)
    d3_ge_kappa_se = bool(
        d3["mean"] >= kappa * d3["se"] if np.isfinite(d3["se"])
        else False)
    gaps_ok = True
    gap_detail: dict[str, Any] = {}
    for k in range(3):
        r_hi, r_lo = rungs[k], rungs[k + 1]
        g = family_report["adjacent_rung_gaps"][f"{r_hi}-{r_lo}"]
        ok = bool(g["gap"] > 0 and g["gap"] >= kappa * g["se_pair_cluster"]
                  if np.isfinite(g["se_pair_cluster"]) else False)
        gaps_ok = gaps_ok and ok
        gap_detail[f"{r_hi}-{r_lo}"] = {
            **g, "kappa_times_se": kappa * g["se_pair_cluster"],
            "ok": ok}
    margins_ok = True
    margin_detail: dict[str, Any] = {}
    for b, per_rung in family_report["fixed_baseline_margins"].items():
        margin_detail[b] = {}
        for r in rungs:
            st = per_rung[r]
            ok = bool(st["mean"] > 0.0 and st["mean"] >= kappa * st["se"]
                      if np.isfinite(st["se"]) else False)
            margins_ok = margins_ok and ok
            margin_detail[b][r] = {
                "mean": st["mean"], "se": st["se"],
                "kappa_times_se": kappa * st["se"],
                "bootstrap_ci": st["bootstrap_ci"], "ok": ok}
    return {
        "rule": "strict per-corpus(R5 唯一口径)",
        "kappa": float(kappa),
        "ordering_ok": ordering_ok,
        "gaps_ge_kappa_se": gaps_ok,
        "gaps": gap_detail,
        "d3_positive": d3_positive,
        "d3_mean_ge_kappa_se": d3_ge_kappa_se,
        "d3_mean": d3["mean"], "d3_se": d3["se"],
        "d3_bootstrap_ci": d3["bootstrap_ci"],
        "margins_ok": margins_ok,
        "fixed_baseline_margins": margin_detail,
        "pair_integrity_unity": bool(
            family_report["pair_integrity_pass_rate"] == 1.0),
        "oracle_positive": bool(
            family_report["oracle_positive_all_rungs"]),
        "pass": bool(
            ordering_ok and gaps_ok and d3_positive and d3_ge_kappa_se
            and margins_ok
            and family_report["pair_integrity_pass_rate"] == 1.0
            and family_report["oracle_positive_all_rungs"]),
    }


def pooled_conditions_r5_diagnostic(
        family_reports: list[dict[str, Any]],
        kappa: float = ROBUSTNESS_KAPPA_R5) -> dict[str, Any]:
    """pooled 双语料统计——**仅诊断字段,禁止用于 PASS 判定**。"""
    out = pooled_conditions_r4(family_reports, kappa)
    out["diagnostic_only"] = True
    out["note"] = ("R5 唯一 PASS 口径是 strict per-corpus;pooled 结果"
                   "不得把任何 corpus FAIL 救成 PASS(§19)")
    return out


# ------------------------------------------------- 全-ladder 功效模拟
def simulate_formal_gate_pass_r5(
        ladder_arrays: dict[str, np.ndarray],
        margin_arrays: dict[str, dict[str, np.ndarray]],
        required_baselines: tuple[str, ...],
        *, kappa: float = ROBUSTNESS_KAPPA_R5,
        n_formal: int = FORMAL_PAIRS_PER_RUNG_R5,
        n_sim: int = R5_GATE_SIM_RESAMPLES,
        seed: int = R5_GATE_SIM_SEED,
) -> dict[str, Any]:
    """bootstrap 模拟 n=10 正式 corpus 下 strict 全条件通过概率。

    每次模拟独立重采样每 rung 的 n_formal 个 pair(按 pair 重采样,
    A/B 不拆散;跨 rung 独立),在模拟 corpus 内用同一公式复算
    mean/sd(ddof=1)/SE 并检查全部 strict 条件:
    - ordering(D0>D1>D2>D3);
    - 每个相邻 gap > 0 且 >= kappa×SE_gap(模拟 corpus 内二次合成);
    - D3 > 0 且 >= kappa×SE;
    - 逐基线 margin(全部 rung)> 0 且 >= kappa×SE。
    密度门槛按 design corpus 实测值直接判定(不随 pair 重采样模拟),
    在 candidate 资格层并入。
    """
    rng = np.random.default_rng(seed)
    rungs = CURRICULUM261_RUNGS
    lad = {r: np.asarray(ladder_arrays[r], dtype=np.float64)
           for r in rungs}
    mar = {r: {b: np.asarray(margin_arrays[r][b], dtype=np.float64)
               for b in required_baselines}
           for r in rungs}
    cond_counts = {
        "ordering": 0,
        **{f"gap_{rungs[k]}-{rungs[k + 1]}": 0 for k in range(3)},
        "d3_positive": 0, "d3_ge_kappa_se": 0,
        **{f"margin_{b}_{r}": 0
           for b in required_baselines for r in rungs},
    }
    n_pass = 0
    idx = {r: rng.integers(0, len(lad[r]), size=(n_sim, n_formal))
           for r in rungs}
    samples = {r: lad[r][idx[r]] for r in rungs}
    means = {r: samples[r].mean(axis=1) for r in rungs}
    sds = {r: samples[r].std(axis=1, ddof=1) for r in rungs}
    ses = {r: sds[r] / np.sqrt(n_formal) for r in rungs}
    ok_order = (means["D0"] > means["D1"]) & (means["D1"] > means["D2"]) \
        & (means["D2"] > means["D3"])
    cond_counts["ordering"] = int(ok_order.sum())
    gap_ok = np.ones(n_sim, dtype=bool)
    for k in range(3):
        r_hi, r_lo = rungs[k], rungs[k + 1]
        gap = means[r_hi] - means[r_lo]
        se_gap = np.sqrt(ses[r_hi] ** 2 + ses[r_lo] ** 2)
        ok = (gap > 0) & (gap >= kappa * se_gap)
        cond_counts[f"gap_{r_hi}-{r_lo}"] = int(ok.sum())
        gap_ok &= ok
    ok_pos = means["D3"] > 0
    ok_kse = means["D3"] >= kappa * ses["D3"]
    cond_counts["d3_positive"] = int(ok_pos.sum())
    cond_counts["d3_ge_kappa_se"] = int(ok_kse.sum())
    margin_ok = np.ones(n_sim, dtype=bool)
    for b in required_baselines:
        for r in rungs:
            msamp = mar[r][b][idx[r]]
            mmean = msamp.mean(axis=1)
            mse = msamp.std(axis=1, ddof=1) / np.sqrt(n_formal)
            ok = (mmean > 0) & (mmean >= kappa * mse)
            cond_counts[f"margin_{b}_{r}"] = int(ok.sum())
            margin_ok &= ok
    passed = ok_order & gap_ok & ok_pos & ok_kse & margin_ok
    n_pass = int(passed.sum())
    return {
        "format": "cur261-r5-formal-gate-simulation-v1",
        "n_sim": int(n_sim),
        "n_formal_pairs": int(n_formal),
        "kappa": float(kappa),
        "seed": int(seed),
        "conditions": "ordering + 3 gaps(κ×SE)+ D3(>0, κ×SE)"
                      "+ 逐基线 margin(全部 rung,κ×SE)",
        "gate_pass_probability": float(n_pass / n_sim),
        "per_condition_pass_probability": {
            k: float(v / n_sim) for k, v in cond_counts.items()},
    }


# ------------------------------------------------- C2 行为密度 gate
def density_gate_r5(density_summary: dict[str, Any]) -> dict[str, Any]:
    """§11 密度门槛(median reference trades >= 8;long label rate
    >= 1.5%;n_trades 为 buy+sell 双腿口径)。"""
    trades_ok = bool(
        density_summary["median_reference_trades_per_episode"]
        >= C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES)
    rate_ok = bool(
        density_summary["reference_long_label_rate"]
        >= C2_DENSITY_MIN_REFERENCE_LONG_RATE)
    return {
        "format": "cur261-r5-c2-density-gate-v1",
        "thresholds": {
            "median_reference_trades_per_episode_min":
                C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES,
            "reference_long_label_rate_min":
                C2_DENSITY_MIN_REFERENCE_LONG_RATE,
        },
        "median_reference_trades_per_episode":
            density_summary["median_reference_trades_per_episode"],
        "reference_long_label_rate":
            density_summary["reference_long_label_rate"],
        "trades_ok": trades_ok,
        "label_rate_ok": rate_ok,
        "pass": bool(trades_ok and rate_ok),
    }


def c2_density_summary(episode_rows: list[dict[str, Any]],
                       rung: str) -> dict[str, Any]:
    """从评估 episode 行聚合 C2 某 rung 的行为密度统计。

    episode_rows 来自 evaluate_pair_corpus_r4 的 per-episode 行
    (含 reference_trades);long label rate 由调用方按 rung 聚合提供
    (r5_design/r5_calibration 用同一 reference 动作序列计算)。
    """
    rows = [r for r in episode_rows if r["rung"] == rung]
    trades = np.asarray([float(r["reference_trades"]) for r in rows],
                        dtype=np.float64)
    return {
        "rung": rung,
        "n_episodes": int(len(rows)),
        "median_reference_trades_per_episode": float(np.median(trades)),
        "mean_reference_trades_per_episode": float(np.mean(trades)),
        "min_reference_trades_per_episode": float(np.min(trades)),
        "max_reference_trades_per_episode": float(np.max(trades)),
    }


# ------------------------------------------------- R5 课程 gate(双 corpus)
def curriculum_robustness_gate_r5(
        main: dict[str, Any], holdout: dict[str, Any],
        kappa: float = ROBUSTNESS_KAPPA_R5,
        stress: dict[str, Any] | None = None,
        c2_diagnostics: dict[str, Any] | None = None,
        c2_density: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """§22 R5 课程稳健性 gate——strict per-corpus 唯一口径。

    每 family:calibration_r5 与 calibration_holdout_r5 各自独立满足
    corpus_conditions_r5 全条件(AND);pooled 为诊断字段不参与判定;
    attempts/stress/C2 双诊断/C2 密度 gate 并入。
    """
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        fm = main["families"][family]
        fh = holdout["families"][family]
        cond_main = corpus_conditions_r5(fm, kappa)
        cond_hold = corpus_conditions_r5(fh, kappa)
        pooled_diag = pooled_conditions_r5_diagnostic([fm, fh], kappa)
        attempts_ok = True
        for rep in (fm, fh):
            stats = rep.get("attempt_stats", {})
            attempts_ok = attempts_ok and bool(
                stats.get("n_pairs", 0) > 0
                and stats.get("mean_attempts", 9.0)
                < stats.get("max_attempts", 5)
                and stats.get("max_attempts_used", 0) <= 5)
        stress_ok = True
        if stress is not None:
            fam_stress = stress.get("families", {}).get(family)
            stress_ok = bool(
                fam_stress is not None
                and fam_stress["accepted_implies_integrity"])
        c2_flags: dict[str, bool] | None = None
        if family == "c2_context":
            density = (c2_density or {}).get("main", {})
            density_ok = bool(density.get("pass")) if density else False
            density_hold = (c2_density or {}).get("holdout", {})
            density_ok = density_ok and bool(density_hold.get("pass"))
            c2_flags = {
                "local_cue_independence": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["local_cue_independence"]["pass"]),
                "context_observability": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["context_observability"]["pass"]),
                "behavior_density_gate": density_ok,
            }
        family_pass = bool(
            cond_main["pass"] and cond_hold["pass"]
            and attempts_ok and stress_ok
            and (c2_flags is None or all(c2_flags.values())))
        families_out[family] = {
            "calibration_r5_conditions_strict": cond_main,
            "calibration_holdout_r5_conditions_strict": cond_hold,
            "pooled_diagnostic_not_for_pass": pooled_diag,
            "attempts_distribution_ok": bool(attempts_ok),
            "stress_accepted_implies_integrity": bool(stress_ok),
            "c2_diagnostics": c2_flags,
            "pass": family_pass,
        }
    overall = bool(all(v["pass"] for v in families_out.values()))
    return {
        "format": "cur261-r5-curriculum-robustness-gate-v1",
        "iteration": "r5",
        "kappa": float(kappa),
        "rule_identity": strict_gate_rule_identity(),
        "statistical_unit": "pair cluster(A/B 均值;唯一 pair 证据表"
                            "派生;禁止 episode 假独立与 hindsight max)",
        "difficulty_metric": "reference_pair - always_flat_pair",
        "corpus_rule": "strict per-corpus AND:calibration_r5 与 "
                       "calibration_holdout_r5 各自独立满足全部条件"
                       "(ordering/gaps κ×SE/D3 κ×SE/逐基线 margin/"
                       "integrity/oracle);pooled 仅诊断,不得救援 FAIL;"
                       "规则在 calibration data 生成前冻结(§19)",
        "contract": [
            "1 ordering(逐 corpus)", "2 gaps_ge_kappa_se(逐 corpus)",
            "3 d3_positive_ge_kappa_se(逐 corpus)",
            "4 fixed_baseline_margin_ge_kappa_pair_se(逐 corpus,逐基线,"
            "全部 rung,无 hindsight)",
            "5 integrity_unity(+stress)", "6 oracle_positive",
            "7 attempts_distribution", "8 c2 local cue+observability"
            "+density(c2)",
        ],
        "main_namespace": main.get("seed_namespace", "calibration_r5"),
        "holdout_namespace": holdout.get(
            "seed_namespace", "calibration_holdout_r5"),
        "c2_local_cue_independence": (
            c2_diagnostics["local_cue_independence"]
            if c2_diagnostics else None),
        "c2_context_observability": (
            c2_diagnostics["context_observability"]
            if c2_diagnostics else None),
        "c2_density_gate": c2_density,
        "families": families_out,
        "pass": overall,
    }
