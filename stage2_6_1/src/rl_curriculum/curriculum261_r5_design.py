# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:两级预注册 C2 candidate design 与功效分析。

§10/§13/§14/§15/§16/§17 流程:
1. 在生成任何 design_r5_* episode 前锁定 design plan(候选网格、Tier B
   机械触发条件、统计方法、功效阈值、密度阈值、选择规则、bootstrap
   seeds、code identity 全部绑定);
2. Tier A(C2-D3-only,6 candidate)在两个独立 design corpus
   (main/validation)各 40 pairs 评估;冻结 D0/D1/D2 语料逐 corpus 生成
   一次、全部 candidate 共享(相同 pair-index schedule);
3. Tier A 存在满足全部硬门槛的 candidate -> 选定(maximin score 最大,
   平局取参数偏离历史最小),**禁止访问 Tier B**;
4. Tier A 全部不合格 -> 写 design decision(tier_b_authorized=true,
   此后 design_r5_tier_b_* namespace 才解锁)-> Tier B(D2+D3 joint,
   3 candidate)同流程;
5. Tier B 也无合格 candidate -> R5 = FAIL(不生成 pack,不进 calibration);
6. 选定 candidate -> CurriculumR5LadderPack-v1(C1/C3 继承 R4 + C2 选定)
   -> r5_parameter_pack.json + digest 锁定。

功效硬门槛(§15,预注册;n=10 expected SE = sd/√10,sd 来自 40-pair
design corpus):
A. gap(D2-D3)> 0 且 gap >= 3.0 × SE_gap(n=10)(二次合成);
B. D3-vs-flat(difficulty)mean >= 2.5 × SE(n=10);
C. D2/D3 对每个固定 required baseline 的 margin > 0 且 >= 2.5×SE(n=10);
D. strict 全条件 formal-gate(n=10 bootstrap,20000 次)P(pass) >= 0.90;
密度:median reference trades >= 8(n_trades 双腿口径)且 long label
rate >= 1.5%;结构:integrity=1.0、oracle positive、ordering。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES
from rl_curriculum.curriculum261_r5_param_pack import (
    C2_TIER_A_CANDIDATES,
    C2_TIER_B_CANDIDATES,
    R4_PARAMETER_PACK_DIGEST,
    ladder_pack_payload,
    param_distance_from_historical,
    r5_candidate_grid,
    write_selected_pack,
)
from rl_curriculum.curriculum261_r5_pairs import (
    C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES,
    C2_DENSITY_MIN_REFERENCE_LONG_RATE,
    R5_GATE_SIM_RESAMPLES,
    R5_GATE_SIM_SEED,
    c2_density_summary,
    density_gate_r5,
    simulate_formal_gate_pass_r5,
    strict_gate_rule_identity,
)
from rl_curriculum.curriculum261_r4_pairs import (
    EVAL_CFG,
    RAW_SCHEMA,
    bootstrap_mean_ci,
    build_pair_evidence_table,
    cluster_stats,
    difficulty_series,
    evaluate_pair_corpus_r4,
    margin_series,
)

DESIGN_FORMAT_R5 = "cur261-r5-design-plan-v1"
DESIGN_PAIRS_PER_RUNG_R5 = 40
DESIGN_TIER_A_NAMESPACES = ("design_r5_tier_a_main",
                            "design_r5_tier_a_validation")
DESIGN_TIER_B_NAMESPACES = ("design_r5_tier_b_main",
                            "design_r5_tier_b_validation")

#: §15 预注册功效阈值。
DESIGN_TARGET_GAP_FACTOR = 3.0
DESIGN_TARGET_D3_FACTOR = 2.5
DESIGN_TARGET_MARGIN_FACTOR = 2.5
DESIGN_TARGET_GATE_PROB = 0.90

#: design 阶段代码身份(影响 design 数值的模块)。
DESIGN_CODE_MODULES_R5 = (
    "curriculum261_api.py",
    "curriculum261_c2.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "curriculum261_r4_pairs.py",
    "curriculum261_r5_param_pack.py",
    "curriculum261_r5_namespaces.py",
    "curriculum261_r5_pairs.py",
    "curriculum261_r5_design.py",
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _code_identity_design() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in DESIGN_CODE_MODULES_R5:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    return out


# ------------------------------------------------------------- plan
def design_plan_payload(*, baseline_commit: str, vendor_pin: str,
                        v2_contract_digest: str,
                        prior_r2_plan_digest: str,
                        prior_diag262r2_plan_digest: str,
                        ) -> dict[str, Any]:
    """构建并返回 design plan payload(锁定后不得修改任何字段)。"""
    from rl_platform.versions import (
        ENV_CORE_VERSION, OBSERVATION_SPEC_VERSION)

    return {
        "format": DESIGN_FORMAT_R5,
        "iteration": "r5",
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "preprocessing_v2_contract_digest": v2_contract_digest,
        "prior_digests": {
            "stage2_6_1_r2_qualification_plan_digest": prior_r2_plan_digest,
            "stage2_6_2_r2_diagnostic_plan_digest":
                prior_diag262r2_plan_digest,
        },
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
        },
        "tier_a": {
            "namespaces": list(DESIGN_TIER_A_NAMESPACES),
            "candidates": {k: dict(v)
                           for k, v in C2_TIER_A_CANDIDATES.items()},
            "scope": "C2-D3-only(键集与历史 D3 一致;仅 alpha_bps/"
                     "vol_bps/wick_kappa 可变)",
            "frozen_rungs": ["D0", "D1", "D2"],
            "frozen_sharing": "冻结 rung 语料逐 design corpus 生成一次,"
                              "全部 candidate 共享(相同 pair-index "
                              "schedule 0..39;参数不入 seed 派生,候选间"
                              "仅通过 generator 内部派生流区分——噪声流"
                              "共享结构性不可达,以 A/B antithetic + 双 "
                              "corpus + 40 pairs 缓解)",
        },
        "tier_b": {
            "namespaces": list(DESIGN_TIER_B_NAMESPACES),
            "candidates": {k: {r: dict(v[r]) for r in ("D2", "D3")}
                           for k, v in C2_TIER_B_CANDIDATES.items()},
            "scope": "C2-D2+D3 joint(键集与历史一致;D2 上调受 D1 约束)",
            "mechanical_trigger": "当且仅当 Tier A 的 6 个 candidate 中"
                                  "满足全部硬门槛者为 0 时,tier_b_"
                                  "authorized=true 写入 design decision,"
                                  "tier B namespace 解锁;一旦 Tier A 存在"
                                  "合格 candidate,Tier B 永久封闭",
        },
        "design_data": {
            "pairs_per_candidate_per_corpus": DESIGN_PAIRS_PER_RUNG_R5,
            "corpora_per_tier": 2,
            "corpora_role": "main/validation 均为参数开发数据,不得称为"
                            "holdout",
            "evaluation_mode": "raw(preproc=None;reference 数值与 scaled "
                               "逐位一致由 R4 reference 等价证明背书)",
        },
        "statistics": {
            "pair_table": "唯一 pair 证据表(r4pt schema;A/B 均值;键 "
                          "(rung, pair_index))",
            "difficulty": "reference_pair - always_flat_pair",
            "margins": "逐固定基线(无 hindsight;禁止 episode 级 max)",
            "se_n10": "expected SE at n=10 = sd(ddof=1)/sqrt(10);gap SE "
                      "为二次合成 sqrt(se_hi^2 + se_lo^2)",
            "kappa": 1.5,
            "strict_gate_rule_identity": strict_gate_rule_identity(),
        },
        "power_targets": {
            "gap_d2_d3_positive_and_ge": DESIGN_TARGET_GAP_FACTOR,
            "d3_vs_flat_ge": DESIGN_TARGET_D3_FACTOR,
            "margins_d2_d3_ge": DESIGN_TARGET_MARGIN_FACTOR,
            "formal_gate_pass_probability_min": DESIGN_TARGET_GATE_PROB,
            "formal_gate_simulation": {
                "n_formal_pairs": 10,
                "n_sim": R5_GATE_SIM_RESAMPLES,
                "seed": R5_GATE_SIM_SEED,
                "method": "按 pair 重采样(A/B 不拆散);模拟 corpus 内"
                          "复算 mean/sd(ddof=1)/SE;条件=ordering+3 gaps"
                          "(κ×SE)+D3(>0,κ×SE)+逐基线 margin(全部 rung,"
                          "κ×SE);密度门槛按 design corpus 实测值直接"
                          "判定",
            },
        },
        "density_thresholds": {
            "median_reference_trades_per_episode_min":
                C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES,
            "reference_long_label_rate_min":
                C2_DENSITY_MIN_REFERENCE_LONG_RATE,
            "n_trades_semantics": "buy+sell 双腿(evaluator EpisodeResult)",
            "historical_reference": "R4 qualification C2 ref trades "
                                    "~11.8-12.8(双腿)/label rate ~3.3%"
                                    "——门槛为任务书建议值,未放宽",
        },
        "selection_rule": {
            "qualification": "candidate 在两个 design corpus 均满足全部"
                             "硬门槛(A/B/C/D + 密度 + 结构)才合格",
            "maximin_score": "score = min over {gap_D2_D3/SE_gap_n10, "
                             "d3_vs_flat/SE_n10, d3_vs_long/SE_n10, "
                             "d3_vs_local_only/SE_n10, "
                             "min(median_trades/8, label_rate/0.015)} "
                             "x min over 两个 design corpus",
            "tie_breaker": "参数偏离历史最小(Σ|new-hist|/hist,键 "
                           "alpha_bps/vol_bps/wick_kappa;Tier B 含 D2 "
                           "侧同式累加)",
            "hard_rule": "maximin score 最高者胜;平局取 distance 最小;"
                         "不得看 Tier B 结果后回选 Tier A",
        },
        "code_identity": _code_identity_design(),
    }


def design_plan_digest(plan: dict[str, Any]) -> str:
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    return "r5dp-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def lock_design_plan(out_dir: Path, plan: dict[str, Any]) -> tuple[Path, str]:
    """写 design plan JSON + digest(生成任何 design data 前调用)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = out_dir / "r5_design_plan.json"
    digest_path = out_dir / "r5_design_plan_digest.txt"
    if path.is_file():
        raise RuntimeError(
            "design plan 已存在;锁定后不得重写(修复须新 iteration + "
            "全新 design namespaces)")
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    digest = design_plan_digest(plan)
    digest_path.write_text(digest, encoding="utf-8")
    return path, digest


def load_locked_design_plan(out_dir: Path) -> tuple[dict[str, Any], str]:
    """读回锁定 design plan 并复算 digest + 校验网格未漂移(fail closed)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r5_design_plan.json"
    digest_path = out_dir / "r5_design_plan_digest.txt"
    if not path.is_file() or not digest_path.is_file():
        raise RuntimeError(
            f"design plan 不存在: {path}(必须先 lock-design-plan 再生成"
            "任何 design episode)")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = design_plan_digest(plan)
    locked = digest_path.read_text(encoding="utf-8").strip()
    if digest != locked:
        raise RuntimeError("design plan digest 漂移(fail closed)")
    current_grid = r5_candidate_grid()
    if plan["tier_a"]["candidates"] != current_grid["tier_a_c2_d3_only"] \
            or plan["tier_b"]["candidates"] != current_grid["tier_b_c2_joint"]:
        raise RuntimeError(
            "design plan 候选网格与代码常量漂移(锁定后禁止增删/修改候选)")
    if plan["code_identity"] != _code_identity_design():
        raise RuntimeError(
            "design plan code identity 与当前代码树不一致(design 代码"
            "修改后 plan 失效;须新 iteration)")
    return plan, digest


# ------------------------------------------------------------- 评估
def _ladder_from_table(table: dict[str, Any],
                       required_baselines: tuple[str, ...],
                       ) -> dict[str, Any]:
    """从 pair 表派生 ladder/margins/gaps(与 rung_report_r4 同公式)。

    供 design 阶段合并冻结 rung 与 candidate rung 的统计;一致性由
    测试(test_curriculum261_r5_statistics)对拍 rung_report_r4 锁定。
    """
    ladder: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        diff = difficulty_series(table, r)
        st = cluster_stats(diff)
        st["bootstrap_ci"] = bootstrap_mean_ci(diff)
        ladder[r] = st
    margins: dict[str, dict[str, Any]] = {}
    for b in required_baselines:
        margins[b] = {}
        for r in CURRICULUM261_RUNGS:
            m = margin_series(table, r, b)
            st = cluster_stats(m)
            st["bootstrap_ci"] = bootstrap_mean_ci(m)
            margins[b][r] = st
    gaps: dict[str, Any] = {}
    for k in range(3):
        r_hi, r_lo = CURRICULUM261_RUNGS[k], CURRICULUM261_RUNGS[k + 1]
        gap = ladder[r_hi]["mean"] - ladder[r_lo]["mean"]
        se = float(np.sqrt(ladder[r_hi]["se"] ** 2 + ladder[r_lo]["se"] ** 2))
        gaps[f"{r_hi}-{r_lo}"] = {
            "gap": float(gap), "se_pair_cluster": se,
            "gap_over_se": float(gap / se) if se > 0 else None,
        }
    means = [ladder[r]["mean"] for r in CURRICULUM261_RUNGS]
    return {
        "pair_table": table,
        "difficulty_ladder": ladder,
        "difficulty_ordering_ok": bool(
            means[0] > means[1] > means[2] > means[3]),
        "fixed_baseline_margins": margins,
        "adjacent_rung_gaps": gaps,
    }


def _reference_long_label_rate(records: list[Any], rung_params: dict,
                               thresholds: dict) -> float:
    """reference 动作的 long bar 占比(raw 模式;与 supervised 集合同源
    ——同一 run_policy_episode 动作序列)。"""
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.evaluator import run_policy_episode

    pol = build_policy_set(FAMILY_C2, dict(rung_params), thresholds)[
        "reference"]
    n_long = 0
    n_total = 0
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            r = run_policy_episode(pol, ep, EVAL_CFG, RAW_SCHEMA,
                                   return_observations=True)
            actions = np.asarray(r[1])
            n_long += int((actions == 1).sum())
            n_total += int(len(actions))
    return float(n_long / n_total) if n_total else float("nan")


def _eval_rung(records: list[Any], rung_params: dict, corpus: str,
               thresholds: dict) -> dict[str, Any]:
    """评估单一 rung 的 records(raw 模式),返回 episodes 行 + pair 表。"""
    ev = evaluate_pair_corpus_r4(
        records, FAMILY_C2, {records[0].rung: rung_params},
        thresholds, preproc=None, corpus=corpus)
    return ev


def _se_n10(sd: float) -> float:
    return float(sd) / np.sqrt(10.0)


def _gap_se_n10(sd_hi: float, sd_lo: float) -> float:
    return float(np.sqrt(sd_hi ** 2 + sd_lo ** 2)) / np.sqrt(10.0)


def _evaluate_candidate(
        candidate_id: str, tier: str,
        corpus_ns: str,
        frozen_eval: dict[str, dict[str, Any]],
        frozen_records: dict[str, list[Any]],
        candidate: dict[str, Any],
        thresholds: dict,
) -> dict[str, Any]:
    """单 candidate 在单 design corpus 上的完整评估 + 硬门槛判定。"""
    override: dict[str, dict[str, Any]] = {}
    if tier == "A":
        override = {"D3": dict(candidate)}
        d3_params, d2_params = dict(candidate), frozen_eval["D2"]["params"]
    else:
        override = {"D2": dict(candidate["D2"]),
                    "D3": dict(candidate["D3"])}
        d3_params, d2_params = dict(candidate["D3"]), dict(candidate["D2"])

    cand_records: dict[str, list[Any]] = {}
    for rung, params in override.items():
        recs = [generate_pair(FAMILY_C2, rung, idx, namespace=corpus_ns,
                              rung_params_override={rung: dict(params)})
                for idx in range(DESIGN_PAIRS_PER_RUNG_R5)]
        cand_records[rung] = recs

    rows: list[dict[str, Any]] = []
    for rung in CURRICULUM261_RUNGS:
        if rung in cand_records:
            ev = _eval_rung(cand_records[rung], override[rung],
                            corpus_ns, thresholds)
            rows.extend(ev["episodes"])
        else:
            rows.extend(frozen_eval[rung]["episodes"])
    table = build_pair_evidence_table(rows, FAMILY_C2, corpus_ns)
    baselines = REQUIRED_BASELINES[FAMILY_C2]
    report = _ladder_from_table(table, baselines)

    ladder = report["difficulty_ladder"]
    sd2, sd3 = ladder["D2"]["sd"], ladder["D3"]["sd"]
    mean2, mean3 = ladder["D2"]["mean"], ladder["D3"]["mean"]
    gap = mean2 - mean3
    gap_se10 = _gap_se_n10(sd2, sd3)
    d3_se10 = _se_n10(sd3)

    margins = report["fixed_baseline_margins"]
    margin_checks: dict[str, Any] = {}
    for b in baselines:
        for r in ("D2", "D3"):
            st = margins[b][r]
            margin_checks[f"{b}_{r}"] = {
                "mean": st["mean"],
                "ratio_n10": float(st["mean"] / _se_n10(st["sd"])),
                "ok": bool(st["mean"] > 0 and st["mean"]
                           >= DESIGN_TARGET_MARGIN_FACTOR
                           * _se_n10(st["sd"])),
            }

    d3_density = c2_density_summary(
        [row for row in rows if row["rung"] == "D3"], "D3")
    d3_density["reference_long_label_rate"] = _reference_long_label_rate(
        cand_records["D3"], d3_params, thresholds)
    d2_rows = ([row for row in rows if row["rung"] == "D2"]
               if "D2" in cand_records
               else frozen_eval["D2"]["episodes"])
    d2_density = c2_density_summary(d2_rows, "D2")
    d2_density["reference_long_label_rate"] = (
        frozen_eval["D2"]["label_rate"] if "D2" not in cand_records
        else _reference_long_label_rate(
            cand_records["D2"], d2_params, thresholds))
    density_d3 = density_gate_r5(d3_density)
    density_d2 = density_gate_r5(d2_density)

    sim = simulate_formal_gate_pass_r5(
        {r: difficulty_series(table, r) for r in CURRICULUM261_RUNGS},
        {r: {b: margin_series(table, r, b) for b in baselines}
         for r in CURRICULUM261_RUNGS},
        baselines,
    )
    integrity_ok = bool(all(
        rec.integrity_ok
        for recs in list(cand_records.values())
        + [frozen_records[r] for r in ("D0", "D1", "D2")
           if r in frozen_records]
        for rec in recs))
    oracle_pos = bool(all(
        float(np.mean([row["oracle"] for row in rows
                       if row["rung"] == r])) > 0
        for r in CURRICULUM261_RUNGS))

    gap_ok = bool(gap > 0
                  and gap >= DESIGN_TARGET_GAP_FACTOR * gap_se10)
    d3_ok = bool(mean3 >= DESIGN_TARGET_D3_FACTOR * d3_se10)
    margins_ok = bool(all(v["ok"] for v in margin_checks.values()))
    sim_ok = bool(sim["gate_pass_probability"] >= DESIGN_TARGET_GATE_PROB)
    ordering_ok = bool(report["difficulty_ordering_ok"])
    reasons = {
        "ordering_ok": ordering_ok,
        "gap_d2_d3_ge_3x_se_n10": gap_ok,
        "d3_vs_flat_ge_2p5x_se_n10": d3_ok,
        "margins_d2_d3_ge_2p5x_se_n10": margins_ok,
        "formal_gate_probability_ge_0p90": sim_ok,
        "density_d3_pass": bool(density_d3["pass"]),
        "density_d2_pass": bool(density_d2["pass"]),
        "pair_integrity_unity": integrity_ok,
        "oracle_positive": oracle_pos,
    }
    maximin_metrics = {
        "gap_d2_d3_over_se_n10": float(gap / gap_se10),
        "d3_vs_flat_over_se_n10": float(mean3 / d3_se10),
        "d3_vs_long_over_se_n10": margin_checks[
            f"always_long_D3"]["ratio_n10"],
        "d3_vs_local_over_se_n10": margin_checks[
            f"c2_local_only_D3"]["ratio_n10"],
        "density_margin_ratio": float(min(
            d3_density["median_reference_trades_per_episode"]
            / C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES,
            d3_density["reference_long_label_rate"]
            / C2_DENSITY_MIN_REFERENCE_LONG_RATE)),
    }
    return {
        "candidate": candidate_id,
        "corpus": corpus_ns,
        "tier": tier,
        "rung_params_effective": {
            "D2": d2_params, "D3": d3_params},
        "difficulty_ladder": {r: {k: ladder[r][k] for k in (
            "n", "mean", "sd", "se")} for r in CURRICULUM261_RUNGS},
        "gaps": report["adjacent_rung_gaps"],
        "gap_d2_d3": {"gap": float(gap), "se_n10": gap_se10,
                      "ratio": float(gap / gap_se10), "ok": gap_ok},
        "d3_positive_margin": {"mean": float(mean3), "se_n10": d3_se10,
                               "ratio": float(mean3 / d3_se10),
                               "ok": d3_ok},
        "margin_checks": margin_checks,
        "density_d3": d3_density,
        "density_d2": d2_density,
        "density_gate_d3": density_d3,
        "density_gate_d2": density_d2,
        "formal_gate_simulation": sim,
        "maximin_metrics": maximin_metrics,
        "reasons": reasons,
        "qualified_in_corpus": bool(all(reasons.values())),
        "pair_table_rows": table["rows"],
    }


def _frozen_rung_eval(corpus_ns: str, rungs: tuple[str, ...],
                      thresholds: dict) -> tuple[dict[str, Any],
                                                 dict[str, list[Any]]]:
    """生成并评估冻结 rung 语料(逐 corpus 一次;全部 candidate 共享)。"""
    specs = family_specs()[FAMILY_C2]
    out: dict[str, Any] = {}
    records_out: dict[str, list[Any]] = {}
    for rung in rungs:
        params = dict(specs.rung_params[rung])
        recs = [generate_pair(FAMILY_C2, rung, idx, namespace=corpus_ns)
                for idx in range(DESIGN_PAIRS_PER_RUNG_R5)]
        ev = _eval_rung(recs, params, corpus_ns, thresholds)
        out[rung] = {
            "params": params,
            "episodes": ev["episodes"],
            "pair_table": ev["pair_table"],
            "label_rate": _reference_long_label_rate(
                recs, params, thresholds),
            "records": recs,
        }
        records_out[rung] = recs
    return out, records_out


def _score_candidate(corpus_results: list[dict[str, Any]]) -> float:
    """maximin:全部 metric x 全部 corpus 取最小。"""
    vals: list[float] = []
    for res in corpus_results:
        vals.extend(float(v) for v in res["maximin_metrics"].values())
    return float(min(vals))


def run_tier(tier: str, plan: dict[str, Any],
             out_dir: Path) -> dict[str, Any]:
    """运行一个 tier(全部 candidate x 两 corpus)+ 汇总资格与选择评分。"""
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    namespaces = (DESIGN_TIER_A_NAMESPACES if tier == "A"
                  else DESIGN_TIER_B_NAMESPACES)
    grid = (plan["tier_a"]["candidates"] if tier == "A"
            else plan["tier_b"]["candidates"])
    frozen_rungs = ("D0", "D1", "D2") if tier == "A" else ("D0", "D1")
    frozen_eval_by_ns: dict[str, dict[str, Any]] = {}
    frozen_records_by_ns: dict[str, dict[str, list[Any]]] = {}
    for ns in namespaces:
        frozen_eval_by_ns[ns], frozen_records_by_ns[ns] = \
            _frozen_rung_eval(ns, frozen_rungs, thresholds)
    results: dict[str, Any] = {}
    for cand_id, cand in grid.items():
        corpus_results = []
        for ns in namespaces:
            frozen_eval = dict(frozen_eval_by_ns[ns])
            if tier == "B":
                frozen_eval["D2"] = None  # D2 由 candidate 提供
            corpus_results.append(_evaluate_candidate(
                cand_id, tier, ns, frozen_eval,
                frozen_records_by_ns[ns], cand, thresholds))
        qualified = bool(all(c["qualified_in_corpus"]
                             for c in corpus_results))
        hist = family_specs()[FAMILY_C2].rung_params
        if tier == "A":
            distance = param_distance_from_historical(
                cand, dict(hist["D3"]))
        else:
            distance = param_distance_from_historical(
                cand["D3"], dict(hist["D3"])) + \
                param_distance_from_historical(
                    cand["D2"], dict(hist["D2"]))
        results[cand_id] = {
            "tier": tier,
            "candidate_params": cand,
            "corpora": corpus_results,
            "qualified_both_corpora": qualified,
            "maximin_score": _score_candidate(corpus_results),
            "param_distance_from_historical": float(distance),
        }
    return {
        "tier": tier,
        "namespaces": list(namespaces),
        "frozen_rungs": list(frozen_rungs),
        "candidates": results,
        "n_qualified": int(sum(1 for v in results.values()
                               if v["qualified_both_corpora"])),
    }


def _select_from_tier(tier_results: dict[str, Any]) -> tuple[str, dict]:
    """maximin 最大 -> 平局 distance 最小(预注册;不得回选)。"""
    qualified = {k: v for k, v in tier_results["candidates"].items()
                 if v["qualified_both_corpora"]}
    if not qualified:
        raise RuntimeError("Tier 内无合格 candidate(不应到达选择阶段)")
    ranked = sorted(
        qualified.items(),
        key=lambda kv: (-kv[1]["maximin_score"],
                        kv[1]["param_distance_from_historical"],
                        kv[0]))
    return ranked[0][0], ranked[0][1]


def write_design_decision(out_dir: Path, *, tier_b_authorized: bool,
                          tier_a_n_qualified: int,
                          tier_a_candidates: list[str]) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "r5_design_decision.json"
    payload = {
        "format": "cur261-r5-design-decision-v1",
        "iteration": "r5",
        "tier_b_authorized": bool(tier_b_authorized),
        "tier_a_n_qualified": int(tier_a_n_qualified),
        "tier_a_candidates": list(tier_a_candidates),
        "rule": "tier_b_authorized 当且仅当 Tier A 全部 candidate 不满足"
                "全部硬门槛;该文件是 design_r5_tier_b_* namespace 的唯一"
                "解锁凭据(写入后 derive261_seed 才放行 tier B)",
        "written_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def run_design_stage(out_dir: Path, plan: dict[str, Any],
                     design_digest: str,
                     baseline_commit: str = "") -> dict[str, Any]:
    """design 主流程:plan 已锁 -> Tier A ->(机械)Tier B -> 选择 -> pack。"""
    out_dir = Path(out_dir)
    tier_a = run_tier("A", plan, out_dir)
    tier_a_results_path = out_dir / "r5_tier_a_results.json"
    tier_a_results_path.write_text(json.dumps(
        tier_a, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    tier_b: dict[str, Any] | None = None
    tier_b_used = False
    if tier_a["n_qualified"] >= 1:
        write_design_decision(
            out_dir, tier_b_authorized=False,
            tier_a_n_qualified=tier_a["n_qualified"],
            tier_a_candidates=sorted(tier_a["candidates"]))
    else:
        # 机械升级:先写 decision 解锁 tier B namespace,再生成数据。
        write_design_decision(
            out_dir, tier_b_authorized=True, tier_a_n_qualified=0,
            tier_a_candidates=sorted(tier_a["candidates"]))
        tier_b = run_tier("B", plan, out_dir)
        (out_dir / "r5_tier_b_results.json").write_text(json.dumps(
            tier_b, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        tier_b_used = True
        if tier_b["n_qualified"] == 0:
            summary = {
                "format": "cur261-r5-design-stage-v1",
                "iteration": "r5",
                "design_plan_digest": design_digest,
                "tier_a": {
                    "n_candidates": len(tier_a["candidates"]),
                    "n_qualified": tier_a["n_qualified"]},
                "tier_b": {
                    "triggered": True,
                    "n_candidates": len(tier_b["candidates"]),
                    "n_qualified": 0},
                "pass": False,
                "verdict": "R5 FAIL:Tier A 与 Tier B 均无合格 candidate"
                           "(§17);不生成 parameter pack,禁止进入 "
                           "calibration",
            }
            (out_dir / "r5_candidate_selection.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=False),
                encoding="utf-8")
            return summary

    source = tier_b if tier_b_used else tier_a
    tier = "B" if tier_b_used else "A"
    selected_id, selected = _select_from_tier(source)
    cand = selected["candidate_params"]
    if tier == "A":
        pack = ladder_pack_payload(
            tier="A", selected_c2_candidate=selected_id,
            c2_d3_params=dict(cand),
            design_plan_digest=design_digest,
            candidate_evidence={
                "maximin_score": selected["maximin_score"],
                "param_distance": selected[
                    "param_distance_from_historical"],
                "corpora": [c["corpus"] for c in selected["corpora"]],
                "gate_probability": [
                    c["formal_gate_simulation"]["gate_pass_probability"]
                    for c in selected["corpora"]],
                "gap_d2_d3": [c["gap_d2_d3"] for c in selected["corpora"]],
                "density_d3": [c["density_d3"] for c in
                               selected["corpora"]],
            },
            baseline_commit=baseline_commit,
        )
    else:
        pack = ladder_pack_payload(
            tier="B", selected_c2_candidate=selected_id,
            c2_d3_params=dict(cand["D3"]),
            c2_d2_params=dict(cand["D2"]),
            design_plan_digest=design_digest,
            candidate_evidence={
                "maximin_score": selected["maximin_score"],
                "param_distance": selected[
                    "param_distance_from_historical"],
                "corpora": [c["corpus"] for c in selected["corpora"]],
                "gate_probability": [
                    c["formal_gate_simulation"]["gate_pass_probability"]
                    for c in selected["corpora"]],
                "gap_d2_d3": [c["gap_d2_d3"] for c in selected["corpora"]],
                "density_d3": [c["density_d3"] for c in
                               selected["corpora"]],
            },
            baseline_commit=baseline_commit,
        )
    write_selected_pack(out_dir, pack)

    selection = {
        "format": "cur261-r5-candidate-selection-v1",
        "iteration": "r5",
        "design_plan_digest": design_digest,
        "tier_executed": tier,
        "tier_b_triggered": tier_b_used,
        "tier_a_n_qualified": tier_a["n_qualified"],
        "selected_candidate": selected_id,
        "selected_params": cand,
        "maximin_score": selected["maximin_score"],
        "param_distance_from_historical": selected[
            "param_distance_from_historical"],
        "qualified_candidates": sorted(
            k for k, v in source["candidates"].items()
            if v["qualified_both_corpora"]),
        "parameter_pack_digest": pack["digest"],
        "pass": True,
    }
    (out_dir / "r5_candidate_selection.json").write_text(json.dumps(
        selection, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    power = {
        "format": "cur261-r5-power-analysis-v1",
        "iteration": "r5",
        "design_plan_digest": design_digest,
        "tier_a": {k: {
            "qualified": v["qualified_both_corpora"],
            "maximin_score": v["maximin_score"],
            "gate_probability": [
                c["formal_gate_simulation"]["gate_pass_probability"]
                for c in v["corpora"]],
            "gap_d2_d3_ratio_n10": [
                c["gap_d2_d3"]["ratio"] for c in v["corpora"]],
            "d3_ratio_n10": [
                c["d3_positive_margin"]["ratio"] for c in v["corpora"]],
            "density_d3_median_trades": [
                c["density_d3"]["median_reference_trades_per_episode"]
                for c in v["corpora"]],
            "density_d3_label_rate": [
                c["density_d3"]["reference_long_label_rate"]
                for c in v["corpora"]],
        } for k, v in tier_a["candidates"].items()},
        "tier_b": ({k: {
            "qualified": v["qualified_both_corpora"],
            "maximin_score": v["maximin_score"],
            "gate_probability": [
                c["formal_gate_simulation"]["gate_pass_probability"]
                for c in v["corpora"]],
        } for k, v in tier_b["candidates"].items()} if tier_b else None),
        "selected": selected_id,
    }
    (out_dir / "r5_power_analysis.json").write_text(json.dumps(
        power, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return selection
