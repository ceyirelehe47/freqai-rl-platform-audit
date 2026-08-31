"""阶段 2.6.1 Repair R4:D3 design / power-analysis 阶段(§14-§16)。

在正式 calibration 前增加统计功效设计阶段,只用于选择 C1-D3 / C3-D3
参数:

- 全新 design namespace(design_r4),与 calibration_r4 /
  calibration_holdout_r4 / qualification_r4 / 历史 R2/R3 / 2.6.2
  namespace 完全隔离;
- candidate 网格在生成 design episodes 前预注册锁定(digest 落盘;
  重跑校验网格未变,禁止看结果后改网格);
- 每 family 3-8 个 candidate(本轮各 6 个),禁止大规模搜索;
- 配对设计:同一 family 的全部 candidate 共享同一 seed schedule
  (design_r4 namespace 下相同 pair/attempt 序列)、相同 episode
  count(30 pairs/rung)、相同评估代码;D2 语料参数冻结,全部
  candidate 共享同一 D2 corpus;noise realization 受限于冻结
  generator 的 seed 派生合同(derive_seed payload 含 rung 参数,
  不同参数必然不同噪声流)——以 antithetic A/B 配对 + 30 pair 样本
  + bootstrap 缓解,并如实登记于 design plan;
- 功效规则(预注册,不得看结果后调整):
  design target: estimated mean >= 2.5 x expected SE at n=10
                 AND bootstrap P(formal-gate PASS) >= 0.80
  formal gate:   mean >= 1.5 x observed SE(kappa = 1.5)
- 选择规则(预注册):全部合格 candidate 中取 gate-pass probability
  最高者;平局取 difficulty mean 较小者(保持 D3 更难);无合格
  candidate -> R4 FAIL,不进入 calibration。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_pairs import (
    generate_pair,
    family_specs,
)
from rl_curriculum.curriculum261_r4_namespaces import (
    CURRICULUM261_ITERATION_ID_R4,
)
from rl_curriculum.curriculum261_r4_param_pack import (
    C1_D3_CANDIDATES,
    C3_D3_CANDIDATES,
    R4_PACK_VERSION,
    pack_digest,
    pack_payload,
    write_selected_pack,
)
from rl_curriculum.curriculum261_r4_pairs import (
    EVAL_CFG,
    FORMAL_PAIRS_PER_RUNG,
    ROBUSTNESS_KAPPA_R4,
    R4_GATE_SIM_RESAMPLES,
    R4_GATE_SIM_SEED,
    bootstrap_mean_ci,
    build_pair_evidence_table,
    cluster_stats,
    difficulty_series,
    evaluate_pair_corpus_r4,
    margin_series,
    simulate_formal_gate_pass,
    table_series,
)

#: design corpus 规模(每 family/rung;大于正式 10,用于估计分布)。
DESIGN_PAIRS_PER_RUNG = 30

#: 预注册功效目标(§15)。
DESIGN_EFFECT_TARGET = 2.5
DESIGN_GATE_PROB_MIN = 0.80

#: C3 结构性机会充分性(design 级;高于生成器最低要求)。
C3_MIN_MEAN_ABOVE_COST = 6.0
C3_MIN_MEAN_BELOW_COST_SIGNALS = 10.0


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def design_plan_payload() -> dict[str, Any]:
    """预注册 design plan(candidate 网格 + 规则;episode 生成前锁定)。"""
    from rl_curriculum.curriculum261_r4_param_pack import (
        r4_candidate_grid,
    )

    return {
        "format": "cur261-r4-parameter-design-plan-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "namespace": "design_r4",
        "candidate_grid": r4_candidate_grid(),
        "grid_locked_before_episode_generation": True,
        "design_pairs_per_rung": DESIGN_PAIRS_PER_RUNG,
        "evaluated_rungs": ["D2", "D3"],
        "d2_corpus_rule": "D2 参数冻结 -> 全部 candidate 共享同一 D2 "
                          "design corpus(同 namespace 同 pair 序列)",
        "paired_design": {
            "same_seed_schedule": True,
            "same_episode_count": True,
            "same_evaluation_code": True,
            "same_noise_realization": "结构性不可达(冻结 generator 的 "
                                      "derive_seed payload 含 rung 参数;"
                                      "不改 generator 即无法跨参数共享"
                                      "噪声流);缓解:antithetic A/B + "
                                      "30 pair 样本 + bootstrap",
        },
        "power_rules": {
            "formal_gate": "mean >= 1.5 x observed pair-cluster SE "
                           "(kappa=1.5)",
            "design_target_effect": f"mean >= {DESIGN_EFFECT_TARGET} x "
                                    "expected SE at n=10 (sd/sqrt(10))",
            "design_target_gate_prob": f"bootstrap P(formal-gate PASS) "
                                       f">= {DESIGN_GATE_PROB_MIN}",
            "n_formal_pairs": FORMAL_PAIRS_PER_RUNG,
            "gate_sim_resamples": R4_GATE_SIM_RESAMPLES,
            "gate_sim_seed": R4_GATE_SIM_SEED,
            "kappa": ROBUSTNESS_KAPPA_R4,
        },
        "structural_criteria": {
            "both_families": [
                "D2 > D3(design means);D2-D3 gap 明显"
                "(>= kappa x SE_gap,与正式 gate 同规则)",
                "pair integrity = 1.0", "oracle positive",
                "margin vs always_long:mean > 0 且 effect size 达标",
            ],
            "c3_extra": [
                f"mean above-cost 事件数/episode >= "
                f"{C3_MIN_MEAN_ABOVE_COST}",
                f"mean below-cost 信号数/episode >= "
                f"{C3_MIN_MEAN_BELOW_COST_SIGNALS}"
                "(marginal/weak 诱饵仍大量存在)",
            ],
        },
        "selection_rule": "合格 candidate 中取 gate_pass_probability "
                          "最高;平局取 difficulty mean 较小者;无合格 "
                          "candidate -> R4 FAIL(不进入 calibration)",
    }


def design_plan_digest(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("created_utc", None)
    return "r4dp-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def _thresholds(family: str) -> dict[str, Any]:
    return dict(family_specs()[family].reference_defaults)


def _design_corpus(family: str, d3_params: dict[str, Any] | None,
                   pairs: int, rung: str) -> list[Any]:
    override = {rung: dict(d3_params)} if d3_params is not None else None
    return [generate_pair(family, rung, i, namespace="design_r4",
                          rung_params_override=override)
            for i in range(pairs)]


def _c3_event_counts(records: list[Any]) -> dict[str, float]:
    above, below, distractors = [], [], []
    for rec in records:
        h = rec.episodes["A"].hidden
        is_sig = (h["sig_dir"].to_numpy() != 0) & \
                 (h["distractor_flag"].to_numpy() == 0)
        n_sig = int(is_sig.sum())
        above.append(int(np.count_nonzero(
            h["above_cost"].to_numpy())))
        below.append(n_sig - above[-1])
        distractors.append(int(h["distractor_flag"].sum()))
    return {"mean_above_cost": float(np.mean(above)),
            "mean_below_cost_signals": float(np.mean(below)),
            "mean_distractors": float(np.mean(distractors))}


def evaluate_candidate(
        family: str, candidate_id: str | None,
        d3_params: dict[str, Any] | None,
        d2_report_cache: dict[str, Any],
        pairs: int = DESIGN_PAIRS_PER_RUNG,
) -> dict[str, Any]:
    """评估一个 D3 candidate(或共享的 D2 冻结语料)。"""
    thresholds = _thresholds(family)
    specs = family_specs()
    rung_params = {r: dict(specs[family].rung_params[r])
                   for r in ("D2", "D3")}
    if d3_params is not None:
        rung_params["D3"] = dict(d3_params)

    if "D2" not in d2_report_cache:
        d2_records = _design_corpus(family, None, pairs, "D2")
        d2_table = build_pair_evidence_table(
            _episode_rows(family, d2_records, rung_params, thresholds,
                          "D2"), family, "design_r4_D2")
        d2_report_cache["D2"] = {
            "table": d2_table,
            "records_integrity": float(
                sum(1 for r in d2_records if r.integrity_ok))
            / len(d2_records),
            "oracle": float(np.mean(
                table_series(d2_table, "D2", "oracle"))),
        }
    d2 = d2_report_cache["D2"]

    d3_records = _design_corpus(family, d3_params, pairs, "D3")
    d3_rows = _episode_rows(family, d3_records, rung_params, thresholds,
                            "D3")
    d3_table = build_pair_evidence_table(d3_rows, family, "design_r4_D3")

    d3_diff = difficulty_series(d3_table, "D3")
    d2_diff = difficulty_series(d2["table"], "D2")
    margins = {b: margin_series(d3_table, "D3", b) for b in
               ("always_flat", "always_long")}
    if family == "c3_cost":
        margins["c3_cost_ignorant"] = margin_series(
            d3_table, "D3", "c3_cost_ignorant")
    d3_stats = cluster_stats(d3_diff)
    d2_stats = cluster_stats(d2_diff)
    power = simulate_formal_gate_pass(
        d3_diff, d2_diff, margins)
    expected_se_n10 = float(d3_stats["sd"] / np.sqrt(
        FORMAL_PAIRS_PER_RUNG))
    effect_ratio = float(d3_stats["mean"] / expected_se_n10) \
        if expected_se_n10 > 0 else float("inf")
    margin_stats = {b: cluster_stats(v) for b, v in margins.items()}
    margin_effect = {b: (float(st["mean"] / (st["sd"] / np.sqrt(
        FORMAL_PAIRS_PER_RUNG))) if st["sd"] > 0 else float("inf"))
        for b, st in margin_stats.items()}

    report: dict[str, Any] = {
        "candidate": candidate_id,
        "family": family,
        "d3_params": dict(d3_params) if d3_params else None,
        "n_pairs_per_rung": pairs,
        "d2_shared": {
            "difficulty_mean": d2_stats["mean"],
            "difficulty_sd": d2_stats["sd"],
            "oracle_mean": d2["oracle"],
        },
        "d3": {
            **d3_stats,
            "bootstrap_ci": bootstrap_mean_ci(d3_diff),
            "margin_stats": margin_stats,
            "oracle_mean": float(np.mean(
                table_series(d3_table, "D3", "oracle"))),
            "integrity_rate": float(
                sum(1 for r in d3_records if r.integrity_ok))
            / len(d3_records),
        },
        "gap_d2_d3": {
            "gap": float(d2_stats["mean"] - d3_stats["mean"]),
            "se": float(np.sqrt(d2_stats["se"] ** 2 + d3_stats["se"] ** 2)),
        },
        "margins_effect_ratio_n10": margin_effect,
        "power": {
            "effect_ratio_n10": effect_ratio,
            "expected_se_n10": expected_se_n10,
            "gate_pass_probability": power["gate_pass_probability"],
            "per_condition": power["per_condition_pass_probability"],
        },
    }
    if family == "c3_cost":
        report["c3_event_counts"] = _c3_event_counts(d3_records)

    # ---- 资格判定(全部预注册规则)
    reasons: list[str] = []
    if not report["d3"]["integrity_rate"] == 1.0:
        reasons.append("pair_integrity_not_unity")
    if not report["d3"]["oracle_mean"] > 0:
        reasons.append("oracle_not_positive")
    if not d2_stats["mean"] > d3_stats["mean"]:
        reasons.append("d2_not_above_d3")
    gap = report["gap_d2_d3"]
    if not (gap["gap"] > 0 and gap["gap"] >= ROBUSTNESS_KAPPA_R4
            * gap["se"]):
        reasons.append("d2_d3_gap_not_significant")
    if not d3_stats["mean"] > 0:
        reasons.append("d3_mean_not_positive")
    if effect_ratio < DESIGN_EFFECT_TARGET:
        reasons.append("effect_ratio_below_target")
    for b, ratio in margin_effect.items():
        if not margin_stats[b]["mean"] > 0:
            reasons.append(f"margin_{b}_not_positive")
        if not ratio >= DESIGN_EFFECT_TARGET:
            reasons.append(f"margin_{b}_effect_below_target")
    if power["gate_pass_probability"] < DESIGN_GATE_PROB_MIN:
        reasons.append("gate_pass_probability_below_target")
    if family == "c3_cost":
        cnt = report["c3_event_counts"]
        if cnt["mean_above_cost"] < C3_MIN_MEAN_ABOVE_COST:
            reasons.append("insufficient_above_cost_opportunities")
        if cnt["mean_below_cost_signals"] < (
                C3_MIN_MEAN_BELOW_COST_SIGNALS):
            reasons.append("insufficient_below_cost_decoys")
    report["qualification_reasons"] = reasons
    report["qualified"] = not reasons
    return report


def _episode_rows(family: str, records: list[Any],
                  rung_params: dict[str, dict[str, Any]],
                  thresholds: dict[str, Any], rung: str,
                  ) -> list[dict[str, Any]]:
    ev = evaluate_pair_corpus_r4(
        records, family, rung_params, thresholds, preproc=None,
        corpus=f"design_r4_{rung}")
    return ev["episodes"]


def run_design_stage(out_dir: Path) -> dict[str, Any]:
    """完整 design 阶段:锁网格 -> 评估 -> 功效 -> 选定 -> 锁 pack。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "r4_parameter_design_plan.json"
    if plan_path.is_file():
        locked = json.loads(plan_path.read_text(encoding="utf-8"))
        current = design_plan_payload()
        if design_plan_digest(locked) != design_plan_digest(current):
            raise RuntimeError(
                "design plan 网格/规则与已锁定版本不一致(禁止看结果后"
                "改网格;fail closed)")
        plan = locked
    else:
        from datetime import datetime, timezone

        plan = design_plan_payload()
        plan["created_utc"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds")
        plan_path.write_text(json.dumps(plan, indent=2,
                                        ensure_ascii=False),
                             encoding="utf-8")
        (out_dir / "r4_parameter_design_plan_digest.txt").write_text(
            design_plan_digest(plan), encoding="utf-8")

    results: dict[str, Any] = {
        "format": "cur261-r4-parameter-design-results-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "design_plan_digest": design_plan_digest(plan),
        "families": {},
    }
    d2_cache: dict[str, Any] = {}
    selection: dict[str, Any] = {}
    overall = True
    for family, candidates in (
            ("c1_opportunity", C1_D3_CANDIDATES),
            ("c3_cost", C3_D3_CANDIDATES)):
        fam_out: dict[str, Any] = {}
        for cid, params in candidates.items():
            print(f"[design] {family} candidate {cid} "
                  f"({DESIGN_PAIRS_PER_RUNG} pairs/rung)...")
            fam_out[cid] = evaluate_candidate(
                family, cid, params, d2_cache)
        qualified = {cid: r for cid, r in fam_out.items() if r["qualified"]}
        results["families"][family] = fam_out
        if not qualified:
            overall = False
            selection[family] = {"selected": None,
                                 "reason": "no_qualified_candidate"}
            continue
        best = sorted(
            qualified.items(),
            key=lambda kv: (-kv[1]["power"]["gate_pass_probability"],
                            kv[1]["d3"]["mean"]))[0]
        selection[family] = {
            "selected": best[0],
            "params": dict(candidates[best[0]]),
            "gate_pass_probability": best[1]["power"][
                "gate_pass_probability"],
            "effect_ratio_n10": best[1]["power"]["effect_ratio_n10"],
            "n_qualified": len(qualified),
        }
    results["selection"] = selection
    results["pass"] = bool(overall)

    (out_dir / "r4_parameter_design_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "d3_power_analysis.json").write_text(json.dumps({
        "format": "cur261-r4-d3-power-analysis-v1",
        "power_rules": plan["power_rules"],
        "families": {f: {cid: {
            "d3_mean": r["d3"]["mean"], "d3_sd": r["d3"]["sd"],
            "effect_ratio_n10": r["power"]["effect_ratio_n10"],
            "gate_pass_probability": r["power"][
                "gate_pass_probability"],
            "per_condition": r["power"]["per_condition"],
            "qualified": r["qualified"],
            "reasons": r["qualification_reasons"],
        } for cid, r in fam.items()} for f, fam in
            results["families"].items()},
        "selection": selection,
    }, indent=2, ensure_ascii=False, default=float), encoding="utf-8")

    if not overall:
        print("[design] 无合格 D3 candidate -> R4 FAIL(不进入 "
              "calibration)")
        return results

    pack = pack_payload(
        {f: {"candidate": selection[f]["selected"],
             "params": selection[f]["params"]} for f in selection},
        evidence={
            "design_plan_digest": design_plan_digest(plan),
            "selection": selection,
        })
    write_selected_pack(out_dir, pack)
    print(f"[design] pack locked: digest={pack_digest(pack)} "
          f"selected={ {f: selection[f]['selected'] for f in selection} }")
    return results
