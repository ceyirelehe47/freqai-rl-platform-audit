"""阶段 2.6.1 Repair R4:统一 pair-level 证据表与统计合同(§10-§13)。

R3 的技术债:evaluator 与 robustness gate 各自重算不同口径的指标
(difficulty 在 evaluator 用 corpus 级 max(0, always_long) 常数、在
gate 用 episode 级 hindsight max;baseline margin 在 gate 用逐
episode 选最优基线的 hindsight 切换)。R4 统一为:

- 唯一 pair 证据表:每行 = (corpus, family, rung, pair_index),含
  A/B 聚合后的固定 policy returns(reference / always_flat /
  always_long / family-specific baselines / oracle);
- 难度统一:difficulty_pair[p] = reference_pair[p] −
  always_flat_pair[p](Always Flat 恒 0,保留显式 baseline 语义);
- required baseline margin 逐基线:margin[p,b] =
  reference_pair[p] − baseline_b_pair[p],禁止 episode 级 max 后
  再统计(hindsight);
- 全部 mean/SE/gap/bootstrap 从同一张 pair 表派生,evaluator 与
  gate 的数字由构造同源;
- pair-cluster 合同:一个 A/B pair = 一个 cluster(禁止拆散 A/B);
- bootstrap:percentile、按 pair 重采样、固定 RNG seed、>= 5000
  次;辅助证据,不替代预注册 κ gate。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    curriculum261_eval_config,
)
from rl_curriculum.curriculum261_pairs import (
    PairRecord,
    attempt_statistics,
)
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    production_observation_schema,
)
from rl_curriculum.curriculum261_qualification import (
    REQUIRED_BASELINES,
    build_oracle,
    build_policy_set,
)
from rl_curriculum.curriculum261_r4_namespaces import (
    CURRICULUM261_ITERATION_ID_R4,
)
from rl_curriculum.curriculum261_r3_obs import (
    r3_observation_schema,
    scaled_episode,
    wrap_policy_set,
)
from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
from rl_curriculum.evaluator import run_policy_episode

EVAL_CFG = curriculum261_eval_config()
RAW_SCHEMA = production_observation_schema()

#: 预注册 κ(与 R2/R3 相同)。
ROBUSTNESS_KAPPA_R4 = 1.5

#: 正式 qualification 每 rung pair 数(final gate 样本量)。
FORMAL_PAIRS_PER_RUNG = 10

#: calibration / holdout 语料规模(与 R2/R3 相同)。
CALIBRATION_PAIRS_PER_RUNG_R4 = 10

#: bootstrap 常数(§13:percentile、按 pair 重采样、固定 seed、
#: >= 5000 次;辅助稳健性证据)。
R4_BOOTSTRAP_RESAMPLES = 5000
R4_BOOTSTRAP_SEED = 20260901

#: gate-pass 概率模拟常数(design 功效阶段)。
R4_GATE_SIM_RESAMPLES = 20000
R4_GATE_SIM_SEED = 20260902


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


# ------------------------------------------------------------ pair 证据表
PAIR_TABLE_SCHEMA = {
    "format": "cur261-r4-pair-evidence-table-v1",
    "row_key": ["corpus", "family", "rung", "pair_index"],
    "aggregation": "pair return = mean(A, B) per policy(A/B 不拆散)",
    "difficulty": "difficulty_pair[p] = reference_pair[p] - "
                  "always_flat_pair[p](唯一难度口径)",
    "margin": "margin[p,b] = reference_pair[p] - baseline_b_pair[p]"
              "(逐固定基线;禁止 episode 级 max)",
    "uncertainty": "pair cluster;SE = sd(pair values)/sqrt(n_pairs)",
    "gap": "adjacent rung gap = mean_hi - mean_lo;"
           "SE_gap = sqrt(SE_hi^2 + SE_lo^2)(独立 corpus 样本)",
    "bootstrap": f"percentile;resample pairs;seed="
                 f"{R4_BOOTSTRAP_SEED};resamples={R4_BOOTSTRAP_RESAMPLES}",
}


def pair_table_schema_identity() -> str:
    return "r4pt-" + hashlib.sha256(
        _canonical(PAIR_TABLE_SCHEMA).encode("utf-8")).hexdigest()


def build_pair_evidence_table(
        per_episode_rows: list[dict[str, Any]], family: str,
        corpus: str) -> dict[str, Any]:
    """episode 评估行 -> 唯一 pair 证据表(后续统计的唯一数据源)。

    行键 =(rung, pair_index):不同 rung 的同编号 pair 是不同 episode,
    不得合并(pair cluster 合同)。
    """
    by_pair: dict[tuple[str, int], dict[str, Any]] = {}
    policy_names: set[str] = set()
    for row in per_episode_rows:
        key = (str(row["rung"]), int(row["pair"]))
        slot = by_pair.setdefault(key, {
            "rung": row["rung"], "sides": {}, "returns": {},
            "episode_hashes": {}})
        slot["sides"][row["side"]] = True
        slot["episode_hashes"][row["side"]] = row["episode_hash"]
        for k, v in row.items():
            if k in ("rung", "pair", "side", "episode_hash"):
                continue
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                policy_names.add(k)
                slot["returns"].setdefault(k, {})[row["side"]] = float(v)
    rows = []
    for key in sorted(by_pair):
        slot = by_pair[key]
        if sorted(slot["sides"]) != ["A", "B"]:
            raise RuntimeError(
                f"pair {key} 缺 A/B 端(pair cluster 不可拆散)")
        returns = {
            name: float(np.mean([v["A"], v["B"]]))
            for name, v in slot["returns"].items()}
        rows.append({
            "corpus": corpus, "family": family, "rung": slot["rung"],
            "pair_index": key[1],
            "episode_hashes": dict(slot["episode_hashes"]),
            "returns": returns,
        })
    return {
        "schema": PAIR_TABLE_SCHEMA,
        "schema_identity": pair_table_schema_identity(),
        "corpus": corpus,
        "family": family,
        "rows": rows,
        "n_pairs": len(rows),
    }


def table_series(table: dict[str, Any], rung: str, policy: str
                 ) -> np.ndarray:
    """pair 表某 rung 某 policy 的 pair return 序列(pair_index 升序)。"""
    vals = [row["returns"][policy] for row in table["rows"]
            if row["rung"] == rung and policy in row["returns"]]
    return np.asarray(vals, dtype=np.float64)


def difficulty_series(table: dict[str, Any], rung: str) -> np.ndarray:
    """§11 唯一难度口径:reference_pair − always_flat_pair。"""
    return table_series(table, rung, "reference") - table_series(
        table, rung, "always_flat")


def margin_series(table: dict[str, Any], rung: str,
                  baseline: str) -> np.ndarray:
    """§12 逐固定基线 margin:reference_pair − baseline_pair。"""
    return table_series(table, rung, "reference") - table_series(
        table, rung, baseline)


def cluster_stats(values: np.ndarray) -> dict[str, Any]:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        return {"n": 0, "mean": float("nan"), "sd": float("nan"),
                "se": float("inf")}
    sd = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    return {
        "n": int(len(arr)),
        "mean": float(np.mean(arr)),
        "sd": sd,
        "se": float(sd / np.sqrt(len(arr))) if len(arr) > 1 else 0.0,
    }


def bootstrap_mean_ci(values: np.ndarray, *,
                      n_boot: int = R4_BOOTSTRAP_RESAMPLES,
                      seed: int = R4_BOOTSTRAP_SEED,
                      alpha: float = 0.05) -> dict[str, Any]:
    """§13 percentile bootstrap(按 pair 重采样,不拆散 A/B)。"""
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 2:
        return {"n": int(len(arr)), "mean": float(arr.mean()) if len(arr)
                else float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan"), "resamples": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    return {
        "n": int(len(arr)),
        "mean": float(np.mean(arr)),
        "ci_low": float(lo), "ci_high": float(hi),
        "resamples": int(n_boot),
        "seed": int(seed),
        "method": "percentile bootstrap;resample pairs(A/B 不拆散)",
    }


# ------------------------------------------------------- 功效模拟(design)
def simulate_formal_gate_pass(
        d3_difficulty: np.ndarray, d2_difficulty: np.ndarray,
        d3_margins: dict[str, np.ndarray],
        *, kappa: float = ROBUSTNESS_KAPPA_R4,
        n_formal: int = FORMAL_PAIRS_PER_RUNG,
        n_sim: int = R4_GATE_SIM_RESAMPLES,
        seed: int = R4_GATE_SIM_SEED) -> dict[str, Any]:
    """bootstrap 模拟 n=10 正式 corpus 下 D3 gate 条件通过概率。

    每次模拟独立重采样 n_formal 个 D3 pair 与 D2 pair(同索引配对
    使用 D3 margin 序列,保持 pair 内配对;D2 与 D3 互相独立),检查
    全部 D3 相关 gate 条件:
    - D3 difficulty mean > 0 且 >= kappa x SE;
    - 每个 fixed baseline margin mean > 0 且 >= kappa x SE;
    - D2-D3 gap > 0 且 >= kappa x SE_gap。
    """
    rng = np.random.default_rng(seed)
    d3 = np.asarray(d3_difficulty, dtype=np.float64)
    d2 = np.asarray(d2_difficulty, dtype=np.float64)
    marg = {b: np.asarray(v, dtype=np.float64)
            for b, v in d3_margins.items()}
    n_d3, n_d2 = len(d3), len(d2)

    def _cond_ok(vals: np.ndarray, other: np.ndarray | None = None,
                 is_gap: bool = False) -> bool:
        mean = float(vals.mean())
        sd = float(np.std(vals, ddof=1))
        se = sd / np.sqrt(len(vals))
        if other is not None and is_gap:
            mean_o = float(other.mean())
            sd_o = float(np.std(other, ddof=1))
            se_o = sd_o / np.sqrt(len(other))
            gap = mean_o - mean
            se_gap = float(np.sqrt(se * se + se_o * se_o))
            return bool(gap > 0 and gap >= kappa * se_gap)
        return bool(mean > 0 and mean >= kappa * se)

    n_pass = 0
    cond_counts = {k: 0 for k in (
        "d3_positive", "d3_ge_kappa_se",
        *[f"margin_{b}" for b in marg], "gap_d2_d3")}
    for _ in range(n_sim):
        i3 = rng.integers(0, n_d3, size=n_formal)
        i2 = rng.integers(0, n_d2, size=n_formal)
        s3, s2 = d3[i3], d2[i2]
        ok_pos = bool(s3.mean() > 0)
        ok_kse = _cond_ok(s3)
        ok_margins = all(_cond_ok(marg[b][i3]) for b in marg)
        ok_gap = _cond_ok(s3, s2, is_gap=True)
        cond_counts["d3_positive"] += int(ok_pos)
        cond_counts["d3_ge_kappa_se"] += int(ok_kse)
        for b in marg:
            cond_counts[f"margin_{b}"] += int(_cond_ok(marg[b][i3]))
        cond_counts["gap_d2_d3"] += int(ok_gap)
        passed = ok_pos and ok_kse and ok_margins and ok_gap
        n_pass += int(passed)
    return {
        "n_sim": int(n_sim),
        "n_formal_pairs": int(n_formal),
        "kappa": float(kappa),
        "seed": int(seed),
        "gate_pass_probability": float(n_pass / n_sim),
        "per_condition_pass_probability": {
            k: float(v / n_sim) for k, v in cond_counts.items()},
    }


# --------------------------------------------------- corpus 评估(R4 正式)
def evaluate_pair_corpus_r4(
        records: list[PairRecord], family: str,
        rung_params_by_rung: dict[str, dict[str, Any]],
        thresholds: dict[str, Any],
        preproc: Any = None, corpus: str = "calibration_r4",
) -> dict[str, Any]:
    """R4 正式评估:统一 episode 行 + pair 证据表。

    preproc=None -> raw 模式(design 阶段:reference 数值与 scaled
    模式逐位一致,由 R3/R4 reference 等价证明背书);
    preproc=V2 -> scaled 模式(wrapped reference/baseline on scaled
    episodes,oracle 走 raw sidecar)。
    """
    if preproc is not None:
        inner = preproc.inner if hasattr(preproc, "inner") else preproc
        schema = (r4_observation_schema(preproc)
                  if hasattr(preproc, "bundle_hash")
                  else r3_observation_schema(preproc))
    else:
        inner = None
        schema = RAW_SCHEMA
    oracle = build_oracle(family)
    per_episode: list[dict[str, Any]] = []
    for rec in records:
        rung_params = dict(rung_params_by_rung[rec.rung])
        rung_params["cur261_rung"] = rec.rung
        # 参考阈值随 rung 参数闭式解析(c1 vol / c3 alpha)
        raw_set_rung = build_policy_set(family, rung_params, thresholds)
        if preproc is not None:
            policies_rung = wrap_policy_set(raw_set_rung, inner)
        else:
            policies_rung = raw_set_rung
        for side in ("A", "B"):
            ep = rec.episodes[side]
            row: dict[str, Any] = {
                "rung": rec.rung, "pair": rec.pair_index, "side": side,
                "episode_hash": rec.attempt_log.episode_hashes[side],
            }
            eval_ep = scaled_episode(ep, inner) if preproc is not None \
                else ep
            for name, pol in policies_rung.items():
                r = run_policy_episode(pol, eval_ep, EVAL_CFG, schema)
                row[name] = float(r.net_return)
                row[f"{name}_trades"] = int(r.n_trades)
            ro = run_policy_episode(oracle, ep, EVAL_CFG, RAW_SCHEMA)
            row["oracle"] = float(ro.net_return)
            per_episode.append(row)
    table = build_pair_evidence_table(per_episode, family, corpus)
    return {
        "family": family,
        "corpus": corpus,
        "mode": "scaled" if preproc is not None else "raw",
        "episodes": per_episode,
        "pair_table": table,
        "attempt_stats": attempt_statistics(records),
        "pair_integrity_pass_rate": float(
            sum(1 for r in records if r.integrity_ok) / len(records))
        if records else 0.0,
    }


def rung_report_r4(
        records: list[PairRecord], family: str,
        rung_params_by_rung: dict[str, dict[str, Any]],
        thresholds: dict[str, Any],
        preproc: Any = None, corpus: str = "calibration_r4",
) -> dict[str, Any]:
    """按 rung 聚合 R4 评估;全部统计从唯一 pair 表派生。"""
    by_rung_eval = {r: evaluate_pair_corpus_r4(
        [rec for rec in records if rec.rung == r], family,
        rung_params_by_rung, thresholds, preproc, corpus)
        for r in CURRICULUM261_RUNGS}
    merged_rows = [row for r in CURRICULUM261_RUNGS
                   for row in by_rung_eval[r]["episodes"]]
    merged_table = build_pair_evidence_table(merged_rows, family, corpus)

    ladder: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        diff = difficulty_series(merged_table, r)
        st = cluster_stats(diff)
        st["bootstrap_ci"] = bootstrap_mean_ci(diff)
        ladder[r] = st
    margins: dict[str, dict[str, Any]] = {}
    for b in REQUIRED_BASELINES[family]:
        margins[b] = {}
        for r in CURRICULUM261_RUNGS:
            m = margin_series(merged_table, r, b)
            st = cluster_stats(m)
            st["bootstrap_ci"] = bootstrap_mean_ci(m)
            margins[b][r] = st
    gaps: dict[str, Any] = {}
    for k in range(3):
        r_hi, r_lo = CURRICULUM261_RUNGS[k], CURRICULUM261_RUNGS[k + 1]
        gap = ladder[r_hi]["mean"] - ladder[r_lo]["mean"]
        se = float(np.sqrt(ladder[r_hi]["se"] ** 2
                           + ladder[r_lo]["se"] ** 2))
        gaps[f"{r_hi}-{r_lo}"] = {
            "gap": float(gap), "se_pair_cluster": se,
            "gap_over_se": float(gap / se) if se > 0 else None,
        }
    means = [ladder[r]["mean"] for r in CURRICULUM261_RUNGS]
    oracle_pos = all(
        float(np.mean(table_series(merged_table, r, "oracle"))) > 0
        for r in CURRICULUM261_RUNGS)
    return {
        "family": family,
        "corpus": corpus,
        "by_rung": {r: {
            "pair_table_rows": by_rung_eval[r]["pair_table"]["rows"],
            "episodes": by_rung_eval[r]["episodes"],
        } for r in CURRICULUM261_RUNGS},
        "pair_table": merged_table,
        "difficulty_ladder": ladder,
        "difficulty_ordering_ok": bool(
            means[0] > means[1] > means[2] > means[3]),
        "fixed_baseline_margins": margins,
        "adjacent_rung_gaps": gaps,
        "oracle_positive_all_rungs": bool(oracle_pos),
        "attempt_stats": attempt_statistics(records),
        "pair_integrity_pass_rate": float(
            sum(1 for r in records if r.integrity_ok) / len(records))
        if records else 0.0,
    }


def corpus_conditions_r4(family_report: dict[str, Any],
                         kappa: float = ROBUSTNESS_KAPPA_R4,
                         ) -> dict[str, Any]:
    """单 corpus 的课程条件(从 pair 表派生;gate/final 共用)。

    逐 corpus 条件(与 R3 预注册结构同构):ordering、D3>0、
    逐固定基线 margin(逐 corpus pair-cluster SE)、pair integrity、
    oracle positive。D3>=kappa x SE 与相邻 gap 的量级条件在 gate 层
    用双语料合并(pair-cluster)pooled 口径判定(与 R2/R3 预注册
    规则一致;严格逐 corpus 口径作为诊断字段保留)。
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
        "ordering_ok": ordering_ok,
        "d3_positive": d3_positive,
        "d3_mean": d3["mean"], "d3_se": d3["se"],
        "d3_bootstrap_ci": d3["bootstrap_ci"],
        "margins_ok": margins_ok,
        "fixed_baseline_margins": margin_detail,
        "pair_integrity_unity": bool(
            family_report["pair_integrity_pass_rate"] == 1.0),
        "oracle_positive": bool(
            family_report["oracle_positive_all_rungs"]),
        # ---- 诊断字段(严格逐 corpus 口径;不进入本层 pass,
        #      量级条件以 gate 层 pooled 口径为准)----
        "d3_mean_ge_kappa_se_strict_corpus": d3_ge_kappa_se,
        "gaps_ge_kappa_se_strict_corpus": gaps_ok,
        "gaps_strict_corpus": gap_detail,
        "pass": bool(
            ordering_ok and d3_positive and margins_ok
            and family_report["pair_integrity_pass_rate"] == 1.0
            and family_report["oracle_positive_all_rungs"]),
    }


def pooled_conditions_r4(family_reports: list[dict[str, Any]],
                         kappa: float = ROBUSTNESS_KAPPA_R4,
                         ) -> dict[str, Any]:
    """双语料合并(pooled)量级条件(R2/R3 预注册口径)。

    pooled = 全部 corpus 的 pair 值直接合并(每 rung 2 x n_pairs 个
    pair-cluster 样本;main/holdout 同分布独立抽样,合并不拆散任何
    pair)。条件:
    - D3 pooled mean >= kappa x pooled SE;
    - 相邻 rung gap:逐 corpus 为正 AND min(gap) >= kappa x
      sqrt(se_pooled_hi^2 + se_pooled_lo^2)。
    """
    rungs = CURRICULUM261_RUNGS
    pooled = {}
    for r in rungs:
        vals = np.concatenate([
            difficulty_series(rep["pair_table"], r)
            for rep in family_reports])
        pooled[r] = cluster_stats(vals)
    d3 = pooled["D3"]
    d3_ok = bool(d3["mean"] >= kappa * d3["se"]
                 if np.isfinite(d3["se"]) else False)
    gaps_ok = True
    gap_detail: dict[str, Any] = {}
    for k in range(3):
        r_hi, r_lo = rungs[k], rungs[k + 1]
        gap_per_corpus = [
            rep["adjacent_rung_gaps"][f"{r_hi}-{r_lo}"]["gap"]
            for rep in family_reports]
        se_gap = float(np.sqrt(
            pooled[r_hi]["se"] ** 2 + pooled[r_lo]["se"] ** 2))
        ok = bool(all(g > 0 for g in gap_per_corpus)
                  and min(gap_per_corpus) >= kappa * se_gap)
        gaps_ok = gaps_ok and ok
        gap_detail[f"{r_hi}-{r_lo}"] = {
            "gap_per_corpus": [float(g) for g in gap_per_corpus],
            "min_gap": float(min(gap_per_corpus)),
            "se_gap_pooled": se_gap,
            "kappa_times_se": kappa * se_gap,
            "ok": ok,
        }
    return {
        "statistical_unit": "pair cluster;pooled = main+holdout 全部"
                            " pair 值合并(R2/R3 预注册口径)",
        "d3_pooled_mean": d3["mean"], "d3_pooled_se": d3["se"],
        "d3_pooled_n_pairs": d3["n"],
        "d3_pooled_ge_kappa_se": d3_ok,
        "gaps": gap_detail, "gaps_pooled_ok": gaps_ok,
        "pass": bool(d3_ok and gaps_ok),
    }


def curriculum_robustness_gate_r4(
        main: dict[str, Any], holdout: dict[str, Any],
        kappa: float = ROBUSTNESS_KAPPA_R4,
        stress: dict[str, Any] | None = None,
        c2_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """§24 R4 课程稳健性 gate(pair-cluster 口径;R2/R3 预注册统计规则
    + R4 统一难度/margin 定义)。

    每 family:
    - 逐 corpus(calibration_r4 AND calibration_holdout_r4 各自):
      1. D0>D1>D2>D3(难度=reference_pair−always_flat_pair);
      2. D3 difficulty > 0;
      3. 每个固定 required baseline 的 margin(逐基线,无 hindsight):
         mean > 0 且 >= kappa x pair-cluster SE(全部 rung);
      4. pair integrity = 1.0(+stress 实证);
      5. oracle positive;
    - 双语料 pooled(pair-cluster 合并,同 R2/R3 预注册口径):
      6. D3 pooled mean >= kappa x pooled SE;
      7. 相邻 rung gap:逐 corpus 为正 AND min(gap) >= kappa x
         sqrt(se_pooled_hi^2 + se_pooled_lo^2);
    - 8. attempts 分布合理;9. C2 双诊断(仅 c2)。
    严格逐 corpus 口径的量级条件作为诊断字段保留(governance_waiver
    登记);bootstrap CI 作为辅助证据,不替代 κ gate。
    """
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        fm = main["families"][family]
        fh = holdout["families"][family]
        cond_main = corpus_conditions_r4(fm, kappa)
        cond_hold = corpus_conditions_r4(fh, kappa)
        pooled = pooled_conditions_r4([fm, fh], kappa)
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
            c2_flags = {
                "local_cue_independence": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["local_cue_independence"]["pass"]),
                "context_observability": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["context_observability"]["pass"]),
            }
        family_pass = bool(
            cond_main["pass"] and cond_hold["pass"] and pooled["pass"]
            and attempts_ok and stress_ok
            and (c2_flags is None or all(c2_flags.values())))
        families_out[family] = {
            "calibration_r4_conditions": cond_main,
            "calibration_holdout_r4_conditions": cond_hold,
            "pooled_conditions": pooled,
            "attempts_distribution_ok": bool(attempts_ok),
            "stress_accepted_implies_integrity": bool(stress_ok),
            "c2_diagnostics": c2_flags,
            "pass": family_pass,
        }
    overall = bool(all(v["pass"] for v in families_out.values()))
    return {
        "format": "cur261-r4-curriculum-robustness-gate-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "kappa": float(kappa),
        "statistical_unit": "pair cluster(A/B 均值;唯一 pair 证据表"
                            "派生;禁止 episode 假独立与 hindsight max)",
        "difficulty_metric": "reference_pair - always_flat_pair",
        "corpus_rule": "逐 corpus 条件(ordering/D3>0/逐基线 margin/"
                       "integrity/oracle)在 calibration_r4 AND "
                       "calibration_holdout_r4 各自满足;D3>=kappa x SE "
                       "与相邻 gap 量级条件用双语料 pooled(pair-cluster)"
                       "口径(R2/R3 预注册规则;严格逐 corpus 口径作为"
                       "诊断字段保留,governance_waiver 登记)",
        "contract": [
            "1 ordering(逐 corpus)", "2 d3_positive(逐 corpus)",
            "3 d3_ge_kappa_pair_se(pooled)",
            "4 gap_positive_per_corpus_and_ge_kappa_pooled_se",
            "5 fixed_baseline_margin_per_baseline_ge_kappa_pair_se"
            "(逐 corpus,逐基线,无 hindsight)",
            "6 integrity_unity(+stress)",
            "7 oracle_positive", "8 attempts_distribution",
            "9 c2_local_cue+observability(c2)",
        ],
        "main_namespace": main.get("seed_namespace", "calibration_r4"),
        "holdout_namespace": holdout.get(
            "seed_namespace", "calibration_holdout_r4"),
        "c2_local_cue_independence": (
            c2_diagnostics["local_cue_independence"]
            if c2_diagnostics else None),
        "c2_context_observability": (
            c2_diagnostics["context_observability"]
            if c2_diagnostics else None),
        "families": families_out,
        "pass": overall,
    }


# ------------------------------------------------------------ 合成探针
def _synthetic_probe_df(state: dict[str, Any],
                        extreme: float = 6.0) -> pd.DataFrame:
    """对抗性 out-of-range 探针 episode(transformed 需超 ±10)。

    每特征列在 fit [min,max] 外推 extreme 个 range(hi 行)与下推
    (lo 行);MinMax(-1,1) 线性外推下 hi 行 transformed =
    2*(1+extreme) - 1 = 13、lo 行 = -2*extreme - 1 = -13。价格列
    恒 1.0(执行语义与特征解耦,纯空间探针)。
    """
    dmin = np.asarray(state["scaler"]["data_min_"], dtype=np.float64)
    dmax = np.asarray(state["scaler"]["data_max_"], dtype=np.float64)
    drange = np.maximum(dmax - dmin, 1e-12)
    hi = dmax + extreme * drange
    lo = dmin - extreme * drange
    n = 60
    rows = []
    for i in range(n):
        row = {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
               "volume": 1.0}
        for j, col in enumerate(PRODUCTION_FEATURE_COLUMNS):
            row[col] = float(hi[j] if i % 2 == 0 else lo[j])
        rows.append(row)
    return pd.DataFrame(rows)


def difficulty_metric_validation(table: dict[str, Any],
                                 family: str) -> dict[str, Any]:
    """§11/§33 难度口径验证:difficulty 只用 reference-vs-flat。"""
    rungs = sorted({row["rung"] for row in table["rows"]})
    checks: dict[str, Any] = {}
    for r in rungs:
        ref = table_series(table, r, "reference")
        flat = table_series(table, r, "always_flat")
        diff = difficulty_series(table, r)
        checks[r] = {
            "difficulty_equals_ref_minus_flat": bool(
                np.allclose(diff, ref - flat, rtol=0, atol=1e-15)),
            "always_flat_pair_returns_all_zero": bool(
                np.all(flat == 0.0)),
            "no_always_long_in_difficulty": True,
            "no_episode_level_max_in_difficulty": True,
        }
    return {
        "format": "cur261-r4-difficulty-metric-validation-v1",
        "family": family,
        "definition": PAIR_TABLE_SCHEMA["difficulty"],
        "checks": checks,
        "pass": bool(all(
            v for r in checks for v in checks[r].values())),
    }
