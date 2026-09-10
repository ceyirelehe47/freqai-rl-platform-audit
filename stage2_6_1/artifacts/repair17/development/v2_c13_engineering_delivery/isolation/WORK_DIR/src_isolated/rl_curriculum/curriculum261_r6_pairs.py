# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6:matched-ladder block 统计、strict gate、
formal block-count 功效模拟、scrambled control 与 marginal guard。

§13 统计单位升级:C2 的统计单位从 independent rung pair 升级为
matched-ladder block。每个 block 内先计算各 rung 的
pair_return[rung] = mean(A_return, B_return),然后直接计算配对 gap:

    gap_D0_D1[block] = pair_return[D0] - pair_return[D1](同理 D1-D2/D2-D3)

Adjacent-gap SE = std(blockwise gap, ddof=1) / sqrt(n_blocks)。
**禁止** sqrt(SE_D0^2 + SE_D1^2) 的独立二次合成(四个 rung 已在同一
block 内匹配;独立合成只在 scrambled control 的诊断口径中出现)。

D3 absolute margin 与 fixed-baseline margin 以 block 内该 rung 的
A/B pair 均值为 cluster 值(同一 block 表派生)。

§14 两级证据表:C1/C3 继续使用 R4 pair 表(evaluate_pair_corpus_r4
唯一实现,R6 复用同一代码源);C2 的 ladder ordering/gap SE/formal
simulation 全部从唯一 block 证据表派生,evaluator 与 gate 同源。

§15 独立-rung control 只作诊断:scrambled(打乱 block 对应)不得
参与任何 PASS 判定,不得在看到数据后选择 matched/unpaired 口径。

§16 独立 marginal guard:matched PASS 不能掩盖 rung marginal 分布
异常;independent-rung 语料的 mean ordering/D3 positive/逐基线
positive margin 失败 → R6 = FAIL(无 SE 要求,但不可被 matched 覆盖)。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_c2 import C2_REFERENCE_DEFAULTS
from rl_curriculum.curriculum261_pairs import PairRecord
from rl_curriculum.curriculum261_qualification import REQUIRED_BASELINES
from rl_curriculum.curriculum261_r4_pairs import (
    ROBUSTNESS_KAPPA_R4,
    cluster_stats,
)
from rl_curriculum.curriculum261_r5_pairs import (
    C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES,
    C2_DENSITY_MIN_REFERENCE_LONG_RATE,
    corpus_conditions_r5,
    density_gate_r5,
)

#: R6 正式 κ(§28 冻结;C1/C3 pair-cluster 与 C2 block-cluster 同值)。
ROBUSTNESS_KAPPA_R6 = 1.5
#: §19 正式 block 数选项(design 机械选择;数据后禁止增删)。
FORMAL_BLOCK_OPTIONS = (10, 15, 20)
#: bootstrap/模拟常量。
R6_BOOTSTRAP_RESAMPLES = 5000
R6_BOOTSTRAP_SEED = 20260921
R6_GATE_SIM_RESAMPLES = 20000
R6_GATE_SIM_SEED = 20260922
R6_SCRAMBLE_SIM_RESAMPLES = 2000
R6_SCRAMBLE_SIM_SEED = 20260923
#: §21E positive-gap block rate 门槛(设计边界;design plan 冻结)。
R6_POSITIVE_GAP_RATE_MIN = 0.65
#: §18 cue/payoff separation 预注册阈值(design plan 冻结)。
#: 依据:cue bar 读数 = pulse150±vol20 对 thr105 触发率 ~98.8%(R2
#: 合同);payoff-bar 误触发只来自正注入端 eps+alpha>105——历史
#: D0(α=68) 实测 ~1.6%,阈值 0.06 容许扩间距至 ~3.7 倍(α=80 理论
#: ~5.3% 在内);超过后 reference 每集误交易 >1.4 笔、摩擦损耗 >7%,
#: 语义合同边缘,candidate 机械 FAIL。
#: cue precision 是冗余护栏(由 recall + 两条 false-positive 上界
#: 蕴含):在 fc=6% 边界,cue 密度 ~12 正 cue vs ~24 payoff bar 时
#: precision >= 11.4/(11.4+1.44) ≈ 0.888——下限取 0.85 与 fc 边界
#: 自洽;历史 ladder 实测 ~0.94 有余量。
C2_CUE_RECALL_MIN = 0.95
C2_CUE_PRECISION_MIN = 0.85
C2_NON_CUE_FALSE_POSITIVE_MAX = 0.01
C2_PAYOFF_BAR_FALSE_CUE_MAX = 0.06

#: C2 行为密度门槛(沿用 R5 预注册值;§18)。
C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6 = (
    C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES)
C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6 = (
    C2_DENSITY_MIN_REFERENCE_LONG_RATE)

#: R6 strict gate 合同描述(进入 design plan / qualification plan)。
STRICT_GATE_RULE_IDENTITY = {
    "rule": "strict per-corpus AND(calibration_r6 AND "
            "calibration_holdout_r6 各自独立满足全部条件;pooled 仅诊断)",
    "kappa": ROBUSTNESS_KAPPA_R6,
    "c1_c3": "R4/R5 pair-cluster 口径(ordering/gaps κ×SE/D3 κ×SE/"
             "逐基线 margin κ×SE/integrity/oracle);统计实现复用"
             "corpus_conditions_r5(同源)",
    "c2_matched": [
        "D0>D1>D2>D3(blockwise difficulty 均值)",
        "三段 matched gap > 0 且 >= 1.5 x block-cluster SE"
        "(SE = std(blockwise gap)/sqrt(n_blocks);禁止独立二次合成)",
        "D3 > 0 且 >= 1.5 x SE",
        "逐固定基线 margin(全部 rung,blockwise)> 0 且 >= 1.5 x SE",
        "positive-gap block rate >= 0.65(每段 gap)",
        "block integrity = 1.0(pair + cross-rung matching)",
        "oracle positive", "密度 gate",
        "local cue independence + context observability(A/B 双 carrier)"
        " + cue/payoff separation",
    ],
    "c2_marginal_guard": "独立-rung 语料 mean ordering / D3 positive / "
                         "逐基线 positive margin / integrity / 密度 / "
                         "context+cue 语义(matched PASS 不可覆盖 FAIL;"
                         "无 SE 要求)",
    "pooled_rule": "仅诊断字段;不得覆盖任何 corpus FAIL",
    "scrambled_control": "仅诊断(matched vs unpaired 方差缩减说明);"
                         "禁止参与 PASS 判定或事后口径选择",
    "locked_before_data": "本字典进入 design plan 与 qualification "
                          "plan;design/calibration data 生成后禁止修改",
}


def strict_gate_rule_identity() -> str:
    return "r6sg-" + hashlib.sha256(json.dumps(
        STRICT_GATE_RULE_IDENTITY, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8")).hexdigest()


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


# ------------------------------------------------- C2 block 证据表
BLOCK_TABLE_SCHEMA = {
    "format": "cur261-r6-c2-block-evidence-table-v1",
    "row_key": ["corpus", "family", "block_index"],
    "pair_metrics": "每 rung 的 pair(A/B 均值)return 指标,来自唯一 "
                    "R4 pair 表(evaluate_pair_corpus_r4 同源)",
    "gaps": "gap[block] = pair_return[hi] - pair_return[lo]"
            "(blockwise 配对差分)",
    "uncertainty": "block cluster;SE = std(blockwise values)/"
                   "sqrt(n_blocks)",
    "bootstrap": f"percentile;resample whole blocks(A/B 与四 rung 不"
                 f"拆散);seed={R6_GATE_SIM_SEED};resamples="
                 f"{R6_GATE_SIM_RESAMPLES}",
}


def block_table_schema_identity() -> str:
    return "r6bt-" + hashlib.sha256(
        _canonical(BLOCK_TABLE_SCHEMA).encode("utf-8")).hexdigest()


def build_c2_block_evidence_table(
        pair_table: dict[str, Any],
        blocks: list[Any], corpus: str) -> dict[str, Any]:
    """唯一 C2 block 证据表:pair 表行(行键 (rung, pair_index=block))
    × block 元数据(attempt/tape hash/cross-rung integrity)。

    全部后续统计(ordering/gap SE/margin/bootstrap/positive-gap
    rate)从本表派生;evaluator 与 gate 同源。
    """
    by_block: dict[int, dict[str, Any]] = {}
    for row in pair_table["rows"]:
        b = int(row["pair_index"])
        slot = by_block.setdefault(b, {"block_index": b, "pair_returns": {}})
        rets = row["returns"]
        difficulty = rets["reference"] - rets["always_flat"]
        # margins 覆盖全部 required 基线(含 always_flat;与 R4/R5 的
        # margin_series 口径一致——difficulty 是 margin vs always_flat
        # 的别名);oracle 是诊断量,不入 margins。
        margins = {bname: rets["reference"] - rets[bname]
                   for bname in rets
                   if bname not in ("reference", "oracle")}
        slot["pair_returns"][row["rung"]] = {
            "returns": dict(rets),
            "difficulty": float(difficulty),
            "margins": margins,
        }
    block_meta = {blk.block_index: blk for blk in blocks}
    rows = []
    for b in sorted(by_block):
        if b not in block_meta:
            raise RuntimeError(
                f"block {b} 在 pair 表中存在但 block 元数据缺失")
        meta = block_meta[b]
        slot = by_block[b]
        for rung in CURRICULUM261_RUNGS:
            if rung not in slot["pair_returns"]:
                raise RuntimeError(
                    f"block {b} 缺 rung {rung}(matched block 不可拆散)")
        gaps = {
            f"{CURRICULUM261_RUNGS[k]}-{CURRICULUM261_RUNGS[k + 1]}": (
                slot["pair_returns"][CURRICULUM261_RUNGS[k]]["difficulty"]
                - slot["pair_returns"][CURRICULUM261_RUNGS[k + 1]]
                ["difficulty"])
            for k in range(3)}
        rows.append({
            "corpus": corpus, "family": "c2_context",
            "block_index": b,
            "shared_tape_digest": meta.shared_tape_digest,
            "selected_attempt": int(
                meta.attempt_log.selected_attempt or 0),
            "cross_rung_integrity_pass": bool(
                meta.cross_rung_integrity.get("pass")),
            "pair_integrity_all_pass": bool(all(
                rec.integrity_ok for rec in meta.pair_records.values())),
            "pair_metrics": slot["pair_returns"],
            "gaps": gaps,
        })
    return {
        "schema": BLOCK_TABLE_SCHEMA,
        "schema_identity": block_table_schema_identity(),
        "corpus": corpus,
        "family": "c2_context",
        "rows": rows,
        "n_blocks": len(rows),
    }


def block_difficulty_series(block_table: dict[str, Any],
                            rung: str) -> np.ndarray:
    vals = [row["pair_metrics"][rung]["difficulty"]
            for row in block_table["rows"]]
    return np.asarray(vals, dtype=np.float64)


def block_gap_series(block_table: dict[str, Any], hi: str,
                     lo: str) -> np.ndarray:
    """blockwise 配对 gap 序列(唯一 gap 口径;§13)。"""
    key = f"{hi}-{lo}"
    vals = [row["gaps"][key] for row in block_table["rows"]]
    return np.asarray(vals, dtype=np.float64)


def block_margin_series(block_table: dict[str, Any], rung: str,
                        baseline: str) -> np.ndarray:
    vals = [row["pair_metrics"][rung]["margins"][baseline]
            for row in block_table["rows"]]
    return np.asarray(vals, dtype=np.float64)


def matched_gap_stats(block_table: dict[str, Any]) -> dict[str, Any]:
    """三段 matched gap 的统计(mean/sd/SE = std/sqrt(n))。"""
    rungs = CURRICULUM261_RUNGS
    out: dict[str, Any] = {}
    for k in range(3):
        hi, lo = rungs[k], rungs[k + 1]
        series = block_gap_series(block_table, hi, lo)
        st = cluster_stats(series)
        st["positive_gap_block_rate"] = (
            float(np.mean(series > 0)) if len(series) else 0.0)
        out[f"{hi}-{lo}"] = st
    return out


def _blockwise_conditions(block_table: dict[str, Any],
                          kappa: float = ROBUSTNESS_KAPPA_R6,
                          ) -> dict[str, Any]:
    """C2 matched strict 条件(从唯一 block 表派生;gate/final 共用)。"""
    rungs = CURRICULUM261_RUNGS
    ladder = {r: cluster_stats(block_difficulty_series(block_table, r))
              for r in rungs}
    means = [ladder[r]["mean"] for r in rungs]
    ordering_ok = bool(means[0] > means[1] > means[2] > means[3])
    gap_stats = matched_gap_stats(block_table)
    gaps_ok = True
    gap_detail: dict[str, Any] = {}
    for name, st in gap_stats.items():
        ok = bool(st["n"] >= 2 and st["mean"] > 0
                  and st["mean"] >= kappa * st["se"]
                  and st["positive_gap_block_rate"]
                  >= R6_POSITIVE_GAP_RATE_MIN)
        gaps_ok = gaps_ok and ok
        gap_detail[name] = {
            **st, "kappa_times_se": kappa * st["se"],
            "positive_gap_rate_min": R6_POSITIVE_GAP_RATE_MIN,
            "ok": ok}
    d3 = ladder["D3"]
    d3_positive = bool(d3["mean"] > 0.0)
    d3_ge_kse = bool(d3["mean"] >= kappa * d3["se"]
                     if np.isfinite(d3["se"]) else False)
    margins_ok = True
    margin_detail: dict[str, Any] = {}
    required = tuple(REQUIRED_BASELINES["c2_context"])
    for b in required:
        margin_detail[b] = {}
        for r in rungs:
            st = cluster_stats(block_margin_series(block_table, r, b))
            ok = bool(st["mean"] > 0.0 and st["mean"] >= kappa * st["se"]
                      if np.isfinite(st["se"]) else False)
            margins_ok = margins_ok and ok
            margin_detail[b][r] = {
                "mean": st["mean"], "se": st["se"],
                "kappa_times_se": kappa * st["se"], "ok": ok}
    integrity_ok = bool(block_table["n_blocks"] > 0 and all(
        row["cross_rung_integrity_pass"] and row["pair_integrity_all_pass"]
        for row in block_table["rows"]))
    oracle_ok = bool(all(
        np.mean([row["pair_metrics"][r]["returns"].get("oracle", 0.0)
                 for row in block_table["rows"]]) > 0
        for r in rungs))
    return {
        "kappa": float(kappa),
        "n_blocks": int(block_table["n_blocks"]),
        "difficulty_ladder_blockwise": ladder,
        "ordering_ok": ordering_ok,
        "gaps_ge_kappa_block_se": gaps_ok,
        "gaps": gap_detail,
        "gap_se_formula": "std(blockwise gap, ddof=1)/sqrt(n_blocks)"
                          "(禁止 sqrt(SE_hi^2+SE_lo^2))",
        "d3_positive": d3_positive,
        "d3_mean_ge_kappa_se": d3_ge_kse,
        "d3_mean": d3["mean"], "d3_block_se": d3["se"],
        "margins_ok": margins_ok,
        "fixed_baseline_margins": margin_detail,
        "block_integrity_unity": integrity_ok,
        "oracle_positive": oracle_ok,
        "pass": bool(ordering_ok and gaps_ok and d3_positive and d3_ge_kse
                     and margins_ok and integrity_ok and oracle_ok),
    }


#: 兼容别名(明确语义:c2 matched strict 条件)。
c2_matched_conditions = _blockwise_conditions


# ------------------------------------------------- formal block 功效模拟
def simulate_formal_gate_pass_r6_matched(
        block_table: dict[str, Any],
        *, kappa: float = ROBUSTNESS_KAPPA_R6,
        n_formal_blocks: int, n_sim: int = R6_GATE_SIM_RESAMPLES,
        seed: int = R6_GATE_SIM_SEED,
) -> dict[str, Any]:
    """block bootstrap 模拟:重采样 n_formal_blocks 个**完整 block**
    (不拆 A/B、不拆四 rung),模拟样本内重算 mean/sd(ddof=1)/SE 与
    全部 formal 条件(§21 A-D)。

    密度/语义门槛按 design corpus 实测直接判定(不随 block 重采样
    模拟),在 candidate 资格层并入。
    """
    if int(n_formal_blocks) not in FORMAL_BLOCK_OPTIONS:
        raise RuntimeError(
            f"n_formal_blocks 必须 ∈ {FORMAL_BLOCK_OPTIONS},"
            f"收到 {n_formal_blocks!r}(§19)")
    rungs = CURRICULUM261_RUNGS
    required = tuple(REQUIRED_BASELINES["c2_context"])
    n_pool = block_table["n_blocks"]
    diff = np.stack([block_difficulty_series(block_table, r)
                     for r in rungs], axis=0)  # (4, n_pool)
    marg = np.stack([[block_margin_series(block_table, r, b)
                      for r in rungs] for b in required], axis=0)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_pool, size=(n_sim, int(n_formal_blocks)))
    samples = diff[:, idx]  # (4, n_sim, n)
    means = samples.mean(axis=2)
    sds = samples.std(axis=2, ddof=1)
    ses = sds / np.sqrt(n_formal_blocks)
    cond_counts: dict[str, int] = {"ordering": 0}
    ok_order = ((means[0] > means[1]) & (means[1] > means[2])
                & (means[2] > means[3]))
    cond_counts["ordering"] = int(ok_order.sum())
    gap_ok = np.ones(n_sim, dtype=bool)
    for k in range(3):
        # blockwise:模拟样本内逐 block 配对差分重算 SE;gap 均值 =
        # means[k] - means[k+1](线性恒等,数值同源)
        gap_mean = means[k] - means[k + 1]  # (n_sim,)
        gap_series = samples[k] - samples[k + 1]  # (n_sim, n)
        gap_se = gap_series.std(axis=1, ddof=1) / np.sqrt(n_formal_blocks)
        ok = (gap_mean > 0) & (gap_mean >= kappa * gap_se)
        cond_counts[f"gap_{rungs[k]}-{rungs[k + 1]}"] = int(ok.sum())
        gap_ok &= ok
    ok_pos = means[3] > 0
    ok_kse = means[3] >= kappa * ses[3]
    cond_counts["d3_positive"] = int(ok_pos.sum())
    cond_counts["d3_ge_kappa_se"] = int(ok_kse.sum())
    margin_ok = np.ones(n_sim, dtype=bool)
    for bi, b in enumerate(required):
        for ri, r in enumerate(rungs):
            msamp = marg[bi, ri][idx]  # (n_sim, n)
            mmean = msamp.mean(axis=1)
            mse = msamp.std(axis=1, ddof=1) / np.sqrt(n_formal_blocks)
            ok = (mmean > 0) & (mmean >= kappa * mse)
            cond_counts[f"margin_{b}_{r}"] = int(ok.sum())
            margin_ok &= ok
    passed = ok_order & gap_ok & ok_pos & ok_kse & margin_ok
    n_pass = int(passed.sum())
    return {
        "format": "cur261-r6-formal-block-gate-simulation-v1",
        "n_sim": int(n_sim),
        "n_formal_blocks": int(n_formal_blocks),
        "kappa": float(kappa),
        "seed": int(seed),
        "resample_unit": "complete matched block(A/B 与四 rung 不拆散)",
        "gap_se_formula": "std(blockwise gap)/sqrt(n_blocks)",
        "conditions": "ordering + 3 matched gaps(κ×blockSE)"
                      "+ D3(>0, κ×SE) + 逐基线 margin(全部 rung,κ×SE)",
        "gate_pass_probability": float(n_pass / n_sim),
        "per_condition_pass_probability": {
            k: float(v / n_sim) for k, v in cond_counts.items()},
    }


# ------------------------------------------------- §15 scrambled control
def scrambled_gap_control(
        block_table: dict[str, Any],
        *, n_sim: int = R6_SCRAMBLE_SIM_RESAMPLES,
        seed: int = R6_SCRAMBLE_SIM_SEED,
) -> dict[str, Any]:
    """独立-rung diagnostic(仅诊断):保留每 rung marginal 值不变,
    随机打乱 rung 间的 block 对应,重新估计 unpaired gap SE。

    输出 matched vs scrambled SE 对比与方差缩减比——只用于说明
    matching 降低了多少路径噪声;禁止用于 PASS 判定或口径选择。
    """
    rungs = CURRICULUM261_RUNGS
    n = block_table["n_blocks"]
    diff = {r: block_difficulty_series(block_table, r) for r in rungs}
    rng = np.random.default_rng(seed)
    out: dict[str, Any] = {}
    for k in range(3):
        hi, lo = rungs[k], rungs[k + 1]
        matched = block_gap_series(block_table, hi, lo)
        matched_se = float(matched.std(ddof=1) / np.sqrt(n))
        scrambled_ses: list[float] = []
        for _ in range(n_sim):
            perm_hi = rng.permutation(diff[hi])
            perm_lo = rng.permutation(diff[lo])
            var_hi = perm_hi.var(ddof=1) / n
            var_lo = perm_lo.var(ddof=1) / n
            scrambled_ses.append(float(np.sqrt(var_hi + var_lo)))
        scrambled_se = float(np.mean(scrambled_ses))
        corr = float(np.corrcoef(diff[hi], diff[lo])[0, 1])
        out[f"{hi}-{lo}"] = {
            "matched_se": matched_se,
            "scrambled_unpaired_se_mean": scrambled_se,
            "scrambled_unpaired_se_min": float(np.min(scrambled_ses)),
            "scrambled_unpaired_se_max": float(np.max(scrambled_ses)),
            "variance_reduction_ratio": (
                float((scrambled_se / matched_se) ** 2)
                if matched_se > 0 else None),
            "se_ratio_scrambled_over_matched": (
                float(scrambled_se / matched_se)
                if matched_se > 0 else None),
            "adjacent_rung_block_correlation": corr,
        }
    return {
        "format": "cur261-r6-scrambled-control-v1",
        "diagnostic_only": True,
        "note": "scrambled/unpaired 结果仅说明 matching 的方差缩减;"
                "禁止用于救援 matched FAIL 或事后选择 PASS 口径(§15)",
        "n_sim": int(n_sim), "seed": int(seed),
        "gaps": out,
    }


# ------------------------------------------------- §18 cue/payoff separation
def check_c2_cue_payoff_separation(
        records: list[PairRecord],
        thresholds: dict[str, float] | None = None,
) -> dict[str, Any]:
    """cue/payoff 分离合同(raw 特征域;§18)。

    - cue recall:P(%-ret-1 > cue_thr | cue_dir == +1)(reference 只买
      正 cue,负 cue 端天然不触发);
    - cue precision:P(cue_dir == +1 | 读数 > cue_thr);
    - non-cue false-positive:无 cue 且无 payoff 注入 bar 的越界率;
    - payoff-bar false-cue:P(读数 > cue_thr | payoff_active == 1)
      (全部 payoff bar 口径,含正负注入两端)。
    提高难度不允许 payoff bar 被 reference 误识别为新 cue。
    """
    thr = dict(C2_REFERENCE_DEFAULTS)
    if thresholds:
        thr.update(thresholds)
    cue_thr = float(thr["cue_thr"])
    n = {"cue_pos": 0, "cue_pos_hit": 0, "read_over_thr": 0,
         "read_over_thr_true_cue": 0, "noncue_bar": 0,
         "noncue_over": 0, "payoff_bar": 0, "payoff_over": 0}
    per_rung: dict[str, dict[str, list[float]]] = {}
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            h = ep.hidden
            df = ep.df
            r1 = df["%-ret-1"].to_numpy(dtype=np.float64)
            cue = h["cue_dir"].to_numpy()
            active = h["payoff_active"].to_numpy()
            over = r1 > cue_thr
            sel_cue = cue == 1
            n["cue_pos"] += int(sel_cue.sum())
            n["cue_pos_hit"] += int((sel_cue & over).sum())
            n["read_over_thr"] += int(over.sum())
            n["read_over_thr_true_cue"] += int((over & sel_cue).sum())
            sel_noncue = (cue == 0) & (active == 0)
            n["noncue_bar"] += int(sel_noncue.sum())
            n["noncue_over"] += int((sel_noncue & over).sum())
            n["payoff_bar"] += int((active == 1).sum())
            n["payoff_over"] += int(((active == 1) & over).sum())
            slot = per_rung.setdefault(rec.rung, {
                "payoff_false_cue": [], "cue_recall": []})
            rec_active = active == 1
            if rec_active.sum():
                slot["payoff_false_cue"].append(float(
                    (over & rec_active).sum() / rec_active.sum()))
            rec_cue = cue == 1
            if rec_cue.sum():
                slot["cue_recall"].append(float(
                    (over & rec_cue).sum() / rec_cue.sum()))
    recall = (n["cue_pos_hit"] / n["cue_pos"]
              if n["cue_pos"] else 0.0)
    precision = (n["read_over_thr_true_cue"] / n["read_over_thr"]
                 if n["read_over_thr"] else 0.0)
    noncue_fp = (n["noncue_over"] / n["noncue_bar"]
                 if n["noncue_bar"] else 0.0)
    payoff_fc = (n["payoff_over"] / n["payoff_bar"]
                 if n["payoff_bar"] else 0.0)
    checks = {
        "cue_recall_ge_min": bool(recall >= C2_CUE_RECALL_MIN),
        "cue_precision_ge_min": bool(precision >= C2_CUE_PRECISION_MIN),
        "non_cue_fp_le_max": bool(noncue_fp
                                  <= C2_NON_CUE_FALSE_POSITIVE_MAX),
        "payoff_bar_false_cue_le_max": bool(
            payoff_fc <= C2_PAYOFF_BAR_FALSE_CUE_MAX),
    }
    return {
        "format": "cur261-r6-c2-cue-payoff-separation-v1",
        "thresholds": {
            "cue_thr": cue_thr,
            "cue_recall_min": C2_CUE_RECALL_MIN,
            "cue_precision_min": C2_CUE_PRECISION_MIN,
            "non_cue_false_positive_max": C2_NON_CUE_FALSE_POSITIVE_MAX,
            "payoff_bar_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
        },
        "cue_recall": float(recall),
        "cue_precision": float(precision),
        "non_cue_false_positive_rate": float(noncue_fp),
        "payoff_bar_false_cue_rate": float(payoff_fc),
        "counts": dict(n),
        "per_rung_mean": {
            r: {k: (float(np.mean(v)) if v else None)
                for k, v in d.items()} for r, d in per_rung.items()},
        "checks": checks,
        "pass": bool(all(checks.values())),
    }


# ------------------------------------------------- §16 marginal guard
def c2_marginal_guard_conditions(
        independent_report: dict[str, Any],
        density: dict[str, Any] | None = None,
        semantics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """独立-rung marginal guard(§16/§28;无 SE 要求,不可被覆盖)。

    independent_report 来自 evaluate_pair_corpus_r4 + rung_report_r4
    的普通独立语料(与 matched 相同评估实现,不同 seed 采样)。
    """
    ladder = independent_report["difficulty_ladder"]
    rungs = CURRICULUM261_RUNGS
    means = [ladder[r]["mean"] for r in rungs]
    ordering_ok = bool(means[0] > means[1] > means[2] > means[3])
    d3_ok = bool(ladder["D3"]["mean"] > 0)
    margins_ok = True
    margin_detail: dict[str, Any] = {}
    for b, per_rung in independent_report[
            "fixed_baseline_margins"].items():
        margin_detail[b] = {}
        for r in rungs:
            ok = bool(per_rung[r]["mean"] > 0)
            margins_ok = margins_ok and ok
            margin_detail[b][r] = {"mean": per_rung[r]["mean"], "ok": ok}
    integrity_ok = bool(
        independent_report["pair_integrity_pass_rate"] == 1.0)
    oracle_ok = bool(independent_report["oracle_positive_all_rungs"])
    density_ok = bool(density.get("pass")) if density else False
    semantics_ok = True
    if semantics is not None:
        semantics_ok = bool(
            semantics.get("local_cue_independence", {}).get("pass")
            and semantics.get("context_observability", {}).get("pass")
            and semantics.get("cue_payoff_separation", {}).get("pass"))
    return {
        "format": "cur261-r6-c2-marginal-guard-v1",
        "rule": "independent-rung 语料 mean ordering + D3 positive + "
                "逐基线 positive margin + integrity + oracle + 密度 + "
                "语义(matched sampling 不得掩盖 marginal 分布异常;"
                "无 SE 要求;matched PASS 不能覆盖本 FAIL)",
        "n_pairs_per_rung": int(independent_report["pair_table"]
                                ["n_pairs"] // 4),
        "mean_ordering_ok": ordering_ok,
        "d3_mean_positive": d3_ok,
        "fixed_baseline_means_positive": margins_ok,
        "fixed_baseline_margins": margin_detail,
        "integrity_unity": integrity_ok,
        "oracle_positive": oracle_ok,
        "density_pass": density_ok,
        "semantics_pass": bool(semantics_ok),
        "pass": bool(ordering_ok and d3_ok and margins_ok
                     and integrity_ok and oracle_ok and density_ok
                     and semantics_ok),
    }


# ------------------------------------------------- C1/C3 条件(R6 复用 R5 实现)
def corpus_conditions_r6_pair(family_report: dict[str, Any],
                              kappa: float = ROBUSTNESS_KAPPA_R6,
                              ) -> dict[str, Any]:
    """C1/C3 的 strict per-corpus 条件——统计实现复用 corpus_conditions_r5
    (R4/R5 已锁定的 pair-cluster 口径,R6 同源),仅重标 R6 rule 标签。"""
    out = corpus_conditions_r5(family_report, kappa)
    out["rule"] = "strict per-corpus(R6;实现复用 R5 pair-cluster 口径)"
    out["rule_iteration"] = "r6"
    return out


# ------------------------------------------------- R6 课程 gate(双 corpus)
def curriculum_robustness_gate_r6(
        main: dict[str, Any], holdout: dict[str, Any],
        c2_block_main: dict[str, Any] | None = None,
        c2_block_holdout: dict[str, Any] | None = None,
        c2_marginal_main: dict[str, Any] | None = None,
        c2_marginal_holdout: dict[str, Any] | None = None,
        kappa: float = ROBUSTNESS_KAPPA_R6,
        stress: dict[str, Any] | None = None,
        c2_diagnostics: dict[str, Any] | None = None,
        c2_density: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """§28 R6 课程稳健性 gate——strict per-corpus 唯一口径。

    C1/C3:两 corpus 各自 corpus_conditions_r6_pair 全条件(AND);
    C2:两 corpus 各自 c2_matched_conditions(blockwise 口径)AND
    marginal guard(独立-rung 语料)AND 密度/语义 gate;pooled 仅诊断。
    """
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        fm = main["families"][family]
        fh = holdout["families"][family]
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
        if family == "c2_context":
            cond_main = c2_matched_conditions(c2_block_main, kappa) \
                if c2_block_main else None
            cond_hold = c2_matched_conditions(c2_block_holdout, kappa) \
                if c2_block_holdout else None
            guard_main = c2_marginal_main or {}
            guard_hold = c2_marginal_holdout or {}
            density = (c2_density or {}).get("main", {})
            density_ok = bool(density.get("pass")) if density else False
            density_hold = (c2_density or {}).get("holdout", {})
            density_ok = density_ok and bool(density_hold.get("pass"))
            semantics_ok = bool(
                c2_diagnostics is not None
                and c2_diagnostics["local_cue_independence"]["pass"]
                and c2_diagnostics["context_observability"]["pass"]
                and c2_diagnostics["cue_payoff_separation"]["pass"])
            family_pass = bool(
                cond_main is not None and cond_main["pass"]
                and cond_hold is not None and cond_hold["pass"]
                and guard_main.get("pass") and guard_hold.get("pass")
                and attempts_ok and stress_ok
                and density_ok and semantics_ok)
            families_out[family] = {
                "calibration_r6_matched_conditions": cond_main,
                "calibration_holdout_r6_matched_conditions": cond_hold,
                "c2_marginal_guard_main": guard_main,
                "c2_marginal_guard_holdout": guard_hold,
                "attempts_distribution_ok": bool(attempts_ok),
                "stress_accepted_implies_integrity": bool(stress_ok),
                "c2_semantics_gate": {
                    "local_cue_independence": semantics_ok,
                    "context_observability": bool(semantics_ok),
                    "cue_payoff_separation": bool(semantics_ok),
                    "behavior_density_gate": density_ok,
                },
                "pass": family_pass,
            }
        else:
            cond_main = corpus_conditions_r6_pair(fm, kappa)
            cond_hold = corpus_conditions_r6_pair(fh, kappa)
            family_pass = bool(
                cond_main["pass"] and cond_hold["pass"]
                and attempts_ok and stress_ok)
            families_out[family] = {
                "calibration_r6_conditions_strict": cond_main,
                "calibration_holdout_r6_conditions_strict": cond_hold,
                "attempts_distribution_ok": bool(attempts_ok),
                "stress_accepted_implies_integrity": bool(stress_ok),
                "pass": family_pass,
            }
    overall = bool(all(v["pass"] for v in families_out.values()))
    return {
        "format": "cur261-r6-curriculum-robustness-gate-v1",
        "iteration": "r6",
        "kappa": float(kappa),
        "rule_identity": strict_gate_rule_identity(),
        "statistical_unit": "C1/C3:pair cluster(A/B 均值);C2:matched "
                            "block(同 block 四 rung 配对差分;禁止拆散 "
                            "A/B/四 rung 与独立 SE 二次合成)",
        "difficulty_metric": "reference_pair - always_flat_pair",
        "corpus_rule": "strict per-corpus AND:calibration_r6 与 "
                       "calibration_holdout_r6 各自独立满足全部条件"
                       "(C1/C3 pair-cluster;C2 matched block-cluster"
                       "+marginal guard);pooled 仅诊断,不得救援 FAIL;"
                       "规则在 calibration data 生成前冻结(§28)",
        "main_namespace": main.get("seed_namespace", "calibration_r6"),
        "holdout_namespace": holdout.get(
            "seed_namespace", "calibration_holdout_r6"),
        "c2_local_cue_independence": (
            c2_diagnostics["local_cue_independence"]
            if c2_diagnostics else None),
        "c2_context_observability": (
            c2_diagnostics["context_observability"]
            if c2_diagnostics else None),
        "c2_cue_payoff_separation": (
            c2_diagnostics["cue_payoff_separation"]
            if c2_diagnostics else None),
        "c2_density_gate": c2_density,
        "families": families_out,
        "pass": overall,
    }
