#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R20 研究设计计算 v3(design-only;修复 v2 的最低K公式与SE/行动分类模型)。

范围与边界(与提案 route_c_stage2_6_1_r20_research_design_v3.md 一致):
- 只做抽象正态已知SE解析计算 + 固定种子 design-only 蒙特卡洛自洽复核;
  不读取/生成任何项目语料,不注册 R20 namespace/坐标/claim,不触碰
  正式实验状态;R19 终态原样。
- VALID_SE 等为 R19 原件只读历史锚(READ-ONLY),不是本轮新观测。
- Delta=0.003 是"待审开发界限"(PENDING_REVIEW);本脚本不为其提供
  下游容忍度依据,只给 Delta∈{0.002,0.003,0.004} 敏感性。
- 已知SE正态模型是唯一主分析路径的设计层:实际分析把每坐标
  block-cluster bootstrap SE 代入同一区间式;SE 估计误差/低估以
  rho∈{1.0,1.25,1.5} 敏感性覆盖,不另立第二套竞争框架。

相对 v2(r20_research_design_calc.py)的修复清单:
1) 零偏差功效 = max(0, 2*Phi(Delta*sqrt(K)/s - z_(1-alpha)) - 1);
   达到 90%(alpha=0.05)需要 z_0.95 + z_0.95(=3.2897...),
   不是 v2 的 z_0.95 + z_0.90(=2.9264...,连续边界只有 80%)。
2) 最低K = 用同一个功效函数自 K=1 向上逐点搜索,并验证 K-1 未达标;
   不用稀疏K表跳过真正最小值。
3) "分析SE已按rho修正后的功效"与"不修正但真实SE放大时的假等效
   概率"是两张分开的表,绝不合并。
4) 等权平均SE = sqrt(sum(SE_k^2))/K(mean(SE_k)/sqrt(K) 仅在全部
   相等时成立);共享解析锚只加一次、不随K缩小;bootstrap 次数
   (20000)的数值误差与有限原始blocks/跨坐标的统计不确定性分开表述。
5) 行动主类别互斥(within/beyond+/beyond-/inconclusive),方向标签
   (positive/negative/not_resolved)分离;触界、跨界、缺数据→不决。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from statistics import NormalDist

NORMAL = NormalDist()

# ---- 只读历史输入(R19 原件;不新增抽样) ------------------------------
P_ANALYTIC = 0.950431552876822       # 解析侧点(合同锚)
VALID_POINT = 0.9459313536444273     # validation 语料点(R19 观测)
VALID_SE = 0.0019410552950364546     # 500块 block-cluster bootstrap(20000重抽)单坐标SE;只读
N_CLUSTERS_ANCHOR = 500              # R19 锚的每语料原始 blocks 数
N_BOOTSTRAP_REPS = 20000             # 历史 bootstrap 重抽次数(只读锚属性)

# ---- 设计常量(全部待审;见提案正文) --------------------------------
ALPHA = 0.05
TARGET_POWER = 0.90
DELTA_STAR = 0.003                   # 待审开发界限(非已批准合同)
DELTA_STAR_SENSITIVITY = (0.002, 0.003, 0.004)
RHO_GRID = (1.0, 1.25, 1.5)          # SE 膨胀敏感性(设计旋钮,非观测量)
PLANNING_RHO = 1.5                   # 主案规划场景(保守)
K_REFERENCE = 8                      # 仅作对照列展示(v2 曾推荐;不再作设计目标)
# 事先声明的真偏差情景(计算前先列出,防事后挑值):
NEAR_ZERO_DELTA = 0.0005             # 近零(半幅度以下一个数量级)
BEYOND_DELTA = 0.005                 # 明确界外
DELTA_SCENARIOS = (0.0, NEAR_ZERO_DELTA, DELTA_STAR, -DELTA_STAR, BEYOND_DELTA)

MC_SEED = 20260925
MC_REPS_DEFAULT = 100_000
MAX_K_SEARCH = 100_000

MAGNITUDE_CLASSES = ("within_equivalence_bounds", "beyond_positive_margin",
                     "beyond_negative_margin", "inconclusive")


# ---- 基础校验(与参考包同口径:bool 不是合法计数) --------------------
def _finite(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite real number")
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite real number") from exc
    if not math.isfinite(out):
        raise ValueError(f"{name} must be finite")
    return out


def _positive(value: float, name: str) -> float:
    out = _finite(value, name)
    if out <= 0.0:
        raise ValueError(f"{name} must be positive")
    return out


def _count(value: int, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def critical_z(alpha: float = ALPHA) -> float:
    """单侧 z_(1-alpha);alpha=0.05 时 = 1.6448536269514722。"""
    alpha = _finite(alpha, "alpha")
    if not 0.0 < alpha < 0.5:
        raise ValueError("alpha must lie in (0, 0.5)")
    return NORMAL.inv_cdf(1.0 - alpha)


# ---- TOST 概率与功效(修复后的口径) --------------------------------
def equivalence_probability(
    delta: float,
    margin: float,
    k: int,
    true_single_se: float,
    analysis_single_se: float | None = None,
    alpha: float = ALPHA,
) -> float:
    """正态已知SE模型中,均值估计的 z-CI 整体落入 ±margin 的概率。

    K 个独立同方差坐标取等权平均。true_single_se 管真实数据离散;
    analysis_single_se 管报告区间;两者失配即量化"分析端SE不修正"
    情形下的假等效概率。接受区间为空(lo>=hi)返回 0;概率裁剪到 [0,1]。
    """
    delta = _finite(delta, "delta")
    margin = _positive(margin, "margin")
    k = _count(k, "k")
    true_single_se = _positive(true_single_se, "true_single_se")
    if analysis_single_se is None:
        analysis_single_se = true_single_se
    analysis_single_se = _positive(analysis_single_se, "analysis_single_se")
    half_width = critical_z(alpha) * analysis_single_se / math.sqrt(k)
    lower, upper = -margin + half_width, margin - half_width
    if lower >= upper:
        return 0.0
    true_mean_se = true_single_se / math.sqrt(k)
    probability = (NORMAL.cdf((upper - delta) / true_mean_se)
                   - NORMAL.cdf((lower - delta) / true_mean_se))
    return min(1.0, max(0.0, probability))


def zero_bias_power(margin: float, k: int, single_se: float,
                    alpha: float = ALPHA) -> float:
    """对称TOST在真偏差=0处的功效(合同公式,裁剪到[0,1])。

    max(0, 2*Phi(margin*sqrt(K)/s - z_(1-alpha)) - 1)
    """
    margin = _positive(margin, "margin")
    k = _count(k, "k")
    single_se = _positive(single_se, "single_se")
    arg = margin * math.sqrt(k) / single_se - critical_z(alpha)
    return min(1.0, max(0.0, 2.0 * NORMAL.cdf(arg) - 1.0))


def minimum_k(single_se: float, margin: float,
              target_power: float = TARGET_POWER, alpha: float = ALPHA,
              max_k: int = MAX_K_SEARCH) -> int:
    """同一功效函数自 K=1 向上逐点搜索的最小整数K。

    返回值保证 power(K) >= target 且(由向上搜索逐点验证)
    power(j) < target 对一切 1<=j<K 成立,即 K-1 未达标。
    """
    single_se = _positive(single_se, "single_se")
    margin = _positive(margin, "margin")
    target_power = _finite(target_power, "target_power")
    if not 0.0 < target_power < 1.0:
        raise ValueError("target_power must lie in (0, 1)")
    max_k = _count(max_k, "max_k")
    k = 1
    while k <= max_k:
        if zero_bias_power(margin, k, single_se, alpha) >= target_power:
            return k
        k += 1
    raise ValueError("target power not attainable within max_k")


# ---- 聚合SE模型(C03) ------------------------------------------------
def aggregate_se_independent(standard_errors: list[float]) -> float:
    """独立坐标等权平均的SE基线:sqrt(sum(SE_k^2))/K。

    仅当全部 SE_k 相等时才等于 mean(SE_k)/sqrt(K)。
    """
    ses = [_positive(s, "coordinate_se") for s in standard_errors]
    if not ses:
        raise ValueError("at least one coordinate SE is required")
    return math.sqrt(math.fsum(s * s for s in ses)) / len(ses)


def aggregate_se_with_anchor(standard_errors: list[float],
                             shared_anchor_se: float) -> float:
    """独立坐标 + 一个共享独立解析锚:Var(mean)=sum(s_k^2)/K^2 + Var(anchor)。

    锚对所有坐标相同,只进入一次,不随K缩小。
    更一般的跨坐标/锚协方差须另行用协方差阵表达(见提案/JSON D 表)。
    """
    ses = [_positive(s, "coordinate_se") for s in standard_errors]
    if not ses:
        raise ValueError("at least one coordinate SE is required")
    shared = _finite(shared_anchor_se, "shared_anchor_se")
    if shared < 0.0:
        raise ValueError("shared_anchor_se must be nonnegative")
    return math.sqrt(math.fsum(s * s for s in ses) / len(ses) ** 2
                     + shared * shared)


def aggregate_se_equal_correlated(single_se: float, k: int,
                                  pairwise_correlation: float) -> float:
    """等SE、等两两相关 rho_c 的等权平均SE:s*sqrt((1+(K-1)*rho_c)/K)。

    正相关使聚合SE按 sqrt(1+(K-1)*rho_c) 放大;主设计假设 rho_c=0
    (预注册新坐标=新 namespace/attempt/种子),这是设计假设而非
    已验证事实。
    """
    single_se = _positive(single_se, "single_se")
    k = _count(k, "k")
    pairwise_correlation = _finite(pairwise_correlation, "pairwise_correlation")
    if not -1.0 / (k - 1) <= pairwise_correlation <= 1.0:
        raise ValueError("pairwise_correlation outside valid PSD range")
    return single_se * math.sqrt((1.0 + (k - 1) * pairwise_correlation) / k)


# ---- blocks/坐标尺度外推(C03/G) -----------------------------------
def se_at_blocks(blocks: int) -> float:
    """经验尺度假设 SE ∝ 1/sqrt(B),锚定 R19 的 B=500、SE=VALID_SE。

    单点锚无法验证该指数;1/sqrt(B) 是标准独立簇尺度,外推远离 500
    属假设外推,提案中明示。
    """
    blocks = _count(blocks, "blocks")
    return VALID_SE * math.sqrt(N_CLUSTERS_ANCHOR / blocks)


def blocks_to_offset_rho(rho: float) -> int:
    """在固定每坐标SE目标(=VALID_SE)下,抵消 rho 膨胀所需 blocks。

    B_needed = 500 * rho^2(SE∝1/sqrt(B) 反解),向上取整。
    """
    rho = _positive(rho, "rho")
    return math.ceil(N_CLUSTERS_ANCHOR * rho * rho)


# ---- 行动分类(C05) --------------------------------------------------
def classify_result(lower: float | None, upper: float | None,
                    margin: float) -> dict[str, str]:
    """互斥幅度主类别 + 独立方向标签;触界保守归不决;缺数据归不决。

    幅度类别(互斥,四选一):
      within_equivalence_bounds  CI 严格落在 (-margin, margin) 内
      beyond_positive_margin     CI 下界严格大于 +margin
      beyond_negative_margin     CI 上界严格小于 -margin
      inconclusive               其余一切(含触界、跨界、缺数据)
    方向(辅助描述,另报):positive / negative / not_resolved。
    """
    margin = _positive(margin, "margin")
    if lower is None or upper is None:
        return {"magnitude": "inconclusive", "direction": "not_resolved"}
    lower, upper = _finite(lower, "lower"), _finite(upper, "upper")
    if lower > upper:
        raise ValueError("lower must not exceed upper")
    if lower > -margin and upper < margin:
        magnitude = "within_equivalence_bounds"
    elif lower > margin:
        magnitude = "beyond_positive_margin"
    elif upper < -margin:
        magnitude = "beyond_negative_margin"
    else:
        magnitude = "inconclusive"
    direction = ("positive" if lower > 0.0 else
                 "negative" if upper < 0.0 else "not_resolved")
    return {"magnitude": magnitude, "direction": direction}


ACTION_MAPPING = {
    "within_equivalence_bounds":
        "报告:在待审开发界限内等效(条件结论);方向偏差另报;无强制后续动作",
    "beyond_positive_margin":
        "研究建议:实测系统性偏高超过待审界限,转校准路线(先修analytic/语料缺口);不自动授予正式实验权限",
    "beyond_negative_margin":
        "研究建议:实测系统性偏低超过待审界限,转校准路线;不自动授予正式实验权限",
    "inconclusive":
        "不决:如实报告设计能力不足/数据缺失;不得改称'涨落主导';无强制后续动作",
}


# ---- A:最低K与零偏差功效表(C01/C02) -------------------------------
def part_a_min_k_and_power() -> dict:
    rows = []
    for margin in DELTA_STAR_SENSITIVITY:
        for rho in RHO_GRID:
            s = rho * VALID_SE
            k_min = minimum_k(s, margin)
            rows.append({
                "margin": margin,
                "rho": rho,
                "single_se": s,
                "min_K_power90_at_zero": k_min,
                "power_at_min_K": zero_bias_power(margin, k_min, s),
                "power_at_K_minus_one": zero_bias_power(margin, k_min - 1, s),
                "power_at_K8": zero_bias_power(margin, K_REFERENCE, s),
            })
    return {
        "formula": "max(0, 2*Phi(margin*sqrt(K)/s - z_(1-alpha)) - 1)",
        "search_rule": "same power function evaluated upward from K=1; "
                       "power(j) < target for all j < K is verified pointwise",
        "required_margin_over_se_for_90pct": critical_z() + NORMAL.inv_cdf(0.95),
        "old_v2_wrong_ratio_z95_plus_z90": critical_z() + NORMAL.inv_cdf(0.90),
        "old_v2_ratio_actual_continuous_power":
            2.0 * NORMAL.cdf(NORMAL.inv_cdf(0.90)) - 1.0,
        "rows": rows,
    }


# ---- B:情景功效表,分析SE已按rho修正(C04a,与C表分开) -------------
def part_b_power_scenarios_corrected_se() -> dict:
    out_rows = []
    for rho in RHO_GRID:
        s = rho * VALID_SE  # rho 同时作用于真实分布与分析区间(口径声明)
        k_min = minimum_k(s, DELTA_STAR)
        for delta in DELTA_SCENARIOS:
            out_rows.append({
                "rho": rho,
                "delta_true": delta,
                "analysis_se_corrected": True,
                "power_at_K_min_for_rho": equivalence_probability(
                    delta, DELTA_STAR, k_min, s, s),
                "power_at_K8": equivalence_probability(
                    delta, DELTA_STAR, K_REFERENCE, s, s),
                "power_at_K11_recommended": equivalence_probability(
                    delta, DELTA_STAR, 11, s, s),
                "K_min_for_rho": k_min,
            })
    return {
        "margin": DELTA_STAR,
        "alpha": ALPHA,
        "scenario_deltas_pre_stated": list(DELTA_SCENARIOS),
        "se_model": "s_analysis = s_true = rho * VALID_SE on both truth and interval",
        "rows": out_rows,
    }


# ---- C:假等效概率表,分析SE不修正(C04b,与B表分开) ----------------
def part_c_false_equivalence_unadjusted_se() -> dict:
    rows = []
    for rho in RHO_GRID:
        for k in (K_REFERENCE, 11):
            rows.append({
                "rho": rho,
                "K": k,
                "true_delta": DELTA_STAR,
                "true_single_se": rho * VALID_SE,
                "analysis_single_se": VALID_SE,
                "analysis_se_corrected": False,
                "false_equivalence_probability": equivalence_probability(
                    DELTA_STAR, DELTA_STAR, k, rho * VALID_SE, VALID_SE),
            })
    return {
        "margin": DELTA_STAR,
        "true_delta": DELTA_STAR,
        "definition": "P(z-CI built with ORIGINAL SE falls inside +/-margin) "
                      "while true SE is rho*SE and true delta = +margin",
        "rows": rows,
    }


# ---- D:聚合SE模型与敏感性(C03) ------------------------------------
def part_d_aggregate_se_model() -> dict:
    # 反例:异方差下 mean/sqrt(K) 低估
    counter_se = [0.001, 0.003]
    wrong = (sum(counter_se) / len(counter_se)) / math.sqrt(len(counter_se))
    # 主案(K=11, rho=1.5)下的共享锚敏感性
    k_rec, rho_rec = 11, PLANNING_RHO
    s_rec = rho_rec * VALID_SE
    anchor_rows = []
    for anchor in (0.0, 0.0002, 0.0005):
        agg = aggregate_se_with_anchor([s_rec] * k_rec, anchor)
        ratio = DELTA_STAR / agg
        power0 = min(1.0, max(0.0, 2.0 * NORMAL.cdf(ratio - critical_z()) - 1.0))
        anchor_rows.append({
            "K": k_rec, "rho": rho_rec, "shared_anchor_se": anchor,
            "aggregate_se": agg,
            "margin_over_se": ratio,
            "power_at_zero": power0,
        })
    # 锚不随K缩小:同一锚下 K 增大聚合SE趋近锚本身
    convergence_rows = []
    for k in (1, 11, 100, 1000):
        convergence_rows.append({
            "K": k,
            "aggregate_se": aggregate_se_with_anchor([s_rec] * k, 0.0005),
        })
    # 90%目标的锚SE盈亏平衡值
    required_se = DELTA_STAR / (critical_z() + NORMAL.inv_cdf(0.95))
    var_indep = s_rec * s_rec / k_rec
    slack = required_se * required_se - var_indep
    breakeven_anchor = math.sqrt(slack) if slack > 0.0 else None
    # 跨坐标相关放大因子(等SE特例)
    correlation_rows = [
        {"pairwise_correlation": c,
         "inflation_factor": math.sqrt(1.0 + (k_rec - 1) * c)}
        for c in (0.05, 0.1, 0.2)
    ]
    return {
        "equal_weight_independent_formula": "sqrt(sum(SE_k**2))/K",
        "mean_over_sqrtK_valid_only_if_equal": (
            "mean(SE_k)/sqrt(K) equals the baseline only when all SE_k are equal"),
        "counterexample": {
            "coordinate_SEs": counter_se,
            "correct_mean_SE": aggregate_se_independent(counter_se),
            "incorrect_mean_over_sqrtK": wrong,
        },
        "shared_anchor_formula":
            "Var(mean) = sum(s_k^2)/K^2 + Var(anchor); anchor enters ONCE",
        "anchor_sensitivity_at_recommended_design": anchor_rows,
        "anchor_does_not_shrink_with_K": convergence_rows,
        "breakeven_shared_anchor_se_for_90pct_at_K11_rho1p5": breakeven_anchor,
        "cross_coordinate_correlation_formula":
            "equal-SE case: SE(mean) = s*sqrt((1+(K-1)*rho_c)/K); "
            "general case requires full covariance, stated not hand-waved",
        "correlation_inflation_at_K11": correlation_rows,
    }


# ---- E:bootstrap 次数的数值误差边界(C03) ---------------------------
def part_e_bootstrap_numerical_error() -> dict:
    rel = 1.0 / math.sqrt(2.0 * N_BOOTSTRAP_REPS)
    return {
        "bootstrap_reps": N_BOOTSTRAP_REPS,
        "resampling_relative_error_bound": rel,
        "of_what": (
            "该 0.5% 是'给定固定原始 blocks 时,bootstrap SE 估计本身的"
            "重抽样数值误差'的近似上界(正态理论下 SD 估计的相对MC误差"
            "~1/sqrt(2B));它不是统计不确定性的整体度量"),
        "not_covered": [
            "有限原始 blocks(500/语料)导致的 SE 统计不确定性",
            "跨坐标/实现级散布(需 K 个坐标的经验,单坐标 bootstrap 无法给出)",
            "percentile bootstrap 的模型误差与正态近似偏差",
        ],
        "handling": (
            "上述未覆盖项由 rho 敏感性与 K 的保守规划部分覆盖,"
            "不能靠增加 bootstrap 次数消除"),
    }


# ---- F:行动分类规则与工作示例(C05) --------------------------------
def part_f_classification() -> dict:
    z = critical_z()
    half = z * VALID_SE / math.sqrt(K_REFERENCE)
    example_lower, example_upper = 0.0015 - half, 0.0015 + half
    example = classify_result(example_lower, example_upper, DELTA_STAR)
    cases = {
        "in_bounds": classify_result(0.0005, 0.0025, DELTA_STAR),
        "beyond_positive": classify_result(0.0031, 0.0040, DELTA_STAR),
        "beyond_negative": classify_result(-0.0050, -0.0035, DELTA_STAR),
        "touching_bound": classify_result(0.0010, 0.0030, DELTA_STAR),
        "straddling_bound": classify_result(0.0020, 0.0040, DELTA_STAR),
        "missing_data": classify_result(None, None, DELTA_STAR),
    }
    return {
        "magnitude_classes_mutually_exclusive": list(MAGNITUDE_CLASSES),
        "direction_labels": ["positive", "negative", "not_resolved"],
        "touching_or_crossing_or_missing": "inconclusive",
        "action_mapping": dict(ACTION_MAPPING),
        "worked_example": {
            "estimate_delta": 0.0015, "K": K_REFERENCE,
            "analysis_single_se": VALID_SE, "alpha": ALPHA,
            "lower90": example_lower, "upper90": example_upper,
            "margin": DELTA_STAR,
            "magnitude": example["magnitude"],
            "direction": example["direction"],
            "statement": ("检测到正向小偏差,且在待审等效界内;"
                          "不触发'超过重要界→必须校准'动作"),
        },
        "cases": cases,
    }


# ---- G:每坐标 blocks 推导(C06) -------------------------------------
def part_g_blocks_derivation() -> dict:
    k_rec = 11
    ratio = (lambda k, b: DELTA_STAR * math.sqrt(k) / se_at_blocks(b))
    return {
        "scaling_assumption": "SE(B) = VALID_SE * sqrt(500/B); "
                              "single-anchor extrapolation, exponent not verifiable "
                              "from one point (stated assumption)",
        "recommended_blocks_per_coordinate_corpus": N_CLUSTERS_ANCHOR,
        "why_anchor_matched": [
            "与 R19 锚同规模,避免把 1/sqrt(B) 外推到远离 500 的区域",
            "每坐标 bootstrap 的原始簇数保持历史可复算口径",
        ],
        "blocks_to_offset_rho_at_fixed_se_target": {
            "target_single_se": VALID_SE,
            "formula": "B = ceil(500 * rho^2)",
            "rows": [{"rho": rho, "blocks": blocks_to_offset_rho(rho)}
                     for rho in RHO_GRID],
        },
        "k_times_b_invariance": {
            "formula": "zero-bias margin ratio = margin*sqrt(K*B/500)/VALID_SE "
                       "depends only on the product K*B",
            "recommended_KB": k_rec * N_CLUSTERS_ANCHOR,
            "equal_power_splits": [
                {"K": k_rec, "B": 500, "ratio": ratio(k_rec, 500)},
                {"K": 5, "B": 1100, "ratio": ratio(5, 1100)},
                {"K": 10, "B": 550, "ratio": ratio(10, 550)},
            ],
            "why_more_coordinates":
                "同等总预算下多坐标还能覆盖跨坐标/实现级散布,"
                "而加blocks只压缩单坐标重抽噪声;故选 (K=11, B=500)",
        },
        "se_scaling_examples": [
            {"blocks": 125, "se": se_at_blocks(125)},
            {"blocks": 500, "se": se_at_blocks(500)},
            {"blocks": 2000, "se": se_at_blocks(2000)},
        ],
    }


# ---- H:design-only 蒙特卡洛自洽复核( coherence check only ) -------
def mc_coherence(reps: int = MC_REPS_DEFAULT, seed: int = MC_SEED) -> list[dict]:
    """固定种子/次数的抽象正态试算;只验证公式算术自洽,不验证真实模型。

    仿真世界假设与被检的分析端假设在此分开声明;二者一致,因此一致
    性只证明算术实现正确(coherence),不证明模型对真实生成器成立。
    """
    reps = _count(reps, "reps")
    rng = random.Random(seed)
    scenarios = [
        # (rho, corrected_analysis_se, delta_true, K)
        (1.25, True, 0.0, K_REFERENCE),
        (1.25, False, 0.0, K_REFERENCE),
        (1.25, False, DELTA_STAR, K_REFERENCE),
        (1.5, True, 0.0, 11),
        (1.0, True, DELTA_STAR, K_REFERENCE),
    ]
    rows = []
    for rho, corrected, delta, k in scenarios:
        true_se = rho * VALID_SE
        used_se = true_se if corrected else VALID_SE
        half = critical_z() * used_se / math.sqrt(k)
        lo, hi = -DELTA_STAR + half, DELTA_STAR - half
        hits = 0
        for _ in range(reps):
            estimate = rng.gauss(delta, true_se / math.sqrt(k))
            hits += lo < estimate < hi
        exact = equivalence_probability(delta, DELTA_STAR, k, true_se, used_se)
        sim = hits / reps
        mc_se = math.sqrt(exact * (1.0 - exact) / reps)
        rows.append({
            "rho": rho, "analysis_se_corrected": corrected,
            "true_delta": delta, "K": k,
            "exact_probability": exact, "simulation_probability": sim,
            "repetitions": reps, "mc_standard_error": mc_se,
            "within_five_mc_se": abs(sim - exact) <= 5.0 * mc_se + 1.0 / reps,
        })
    return rows


def part_h_mc_coherence(reps: int = MC_REPS_DEFAULT) -> dict:
    rows = mc_coherence(reps)
    if not all(r["within_five_mc_se"] for r in rows):
        raise RuntimeError("MC coherence check failed; retain the result")
    return {
        "coherence_check_only": True,
        "seed": MC_SEED,
        "repetitions": reps,
        "sim_world_assumptions": [
            "delta_hat ~ N(delta_true, s_true/sqrt(K)), K个独立等方差坐标",
            "s_true = rho * VALID_SE(设计旋钮,非观测量)",
        ],
        "analysis_side_assumptions": [
            "区间 = delta_hat ± z_(1-alpha) * s_analysis/sqrt(K),z=1.6449",
            "s_analysis 按场景取 rho*VALID_SE(修正)或 VALID_SE(不修正)",
        ],
        "interpretation": (
            "仿真世界与分析端假设同源;一致仅证明公式算术正确,"
            "不证明该正态已知SE模型对真实生成器/簇结构成立"),
        "rows": rows,
    }


# ---- I:推荐设计与预算/停止规则(C07) -------------------------------
def part_i_recommended_design() -> dict:
    rho = PLANNING_RHO
    k_rec = 11
    s_rec = rho * VALID_SE
    agg = aggregate_se_independent([s_rec] * k_rec)
    alt_margin = 0.002
    alt_k = minimum_k(1.25 * VALID_SE, alt_margin)
    alt_k_cons = minimum_k(1.5 * VALID_SE, alt_margin)
    return {
        "status": "待审设计;本轮不批准任何新抽样,R20 未注册",
        "primary_analysis_path": (
            "每坐标正态点估计(有符号偏差 delta_k = p_analytic - "
            "recall(validation)) + R19 同口径 block-cluster bootstrap SE; "
            "聚合 SE = sqrt(sum(SE_k^2))/K(等SE特例=s/√K),共享解析锚可选项"
            "显式条件化;判定 = 聚合均值对称TOST(双侧90%CI落入±Delta);"
            "设计层用已知SE正态公式,rho敏感性覆盖SE估计误差;"
            "不引入第二套竞争框架"),
        "design_targets": {
            "margin_delta_star": DELTA_STAR,
            "margin_status": "待审开发界限(PENDING_REVIEW);无下游容忍度依据,"
                             "不得由R19噪声倒写",
            "alpha": ALPHA,
            "target_power_at_zero_delta": TARGET_POWER,
            "planning_rho": rho,
        },
        "K_derivation": {
            "rule": "min K with zero-bias power >= 0.90 at alpha=0.05, "
                    "single-SE = rho*VALID_SE (rho=1.5 conservative)",
            "K": k_rec,
            "power_at_K": zero_bias_power(DELTA_STAR, k_rec, s_rec),
            "power_at_K_minus_one": zero_bias_power(DELTA_STAR, k_rec - 1, s_rec),
            "aggregate_se_equal_se_case": agg,
        },
        "blocks_per_coordinate": {
            "validation_corpus": N_CLUSTERS_ANCHOR,
            "model_corpus": N_CLUSTERS_ANCHOR,
            "note": "model 语料仅描述性次要结果,同规模以保持同口径",
        },
        "budget_and_stop_rules": [
            "每坐标一次 audit 叶(语料生成+既有三路闭合重算);主判定语料="
            "validation;K 与坐标清单批准后冻结,无追加、无重抽、无失败替换",
            "首坐标兼作预算标定:若单坐标实测超15分钟即停止并披露实际成本,"
            "重新申请后再继续;总预算以用户/启动器为准",
            "提前停止时只按已完成坐标做描述性报告,不得以完整K=11预注册"
            "TOST作推断,不得宣称达到90%功效设计",
            "研究(dev)数据与未来正式确认数据物理隔离:独立 namespace 前缀 + "
            "只读归档,不写 journal/准入面;等效成立不自动许可正式链",
        ],
        "alternative_single": {
            "margin": alt_margin,
            "K_at_rho1p25": alt_k,
            "power_at_alt_K_rho1p25": zero_bias_power(
                alt_margin, alt_k, 1.25 * VALID_SE),
            "K_at_rho1p5": alt_k_cons,
            "power_at_alt_K_rho1p5": zero_bias_power(
                alt_margin, alt_k_cons, 1.5 * VALID_SE),
            "when": "仅当审查方认定 0.002 以下偏差亦重要;预算约翻倍,不推荐首选",
        },
    }


def build_output(mc_reps: int = MC_REPS_DEFAULT) -> dict:
    return {
        "format": "r20-design-calc-v3",
        "generated_by": "stage2_6_1/report/r20_design_calc_v3.py (design-only)",
        "inputs": {
            "p_analytic": P_ANALYTIC,
            "valid_point": VALID_POINT,
            "valid_se": VALID_SE,
            "valid_se_status": "READ-ONLY historical R19 anchor",
            "n_clusters_r19_anchor": N_CLUSTERS_ANCHOR,
            "n_bootstrap_reps": N_BOOTSTRAP_REPS,
            "alpha": ALPHA,
            "target_power": TARGET_POWER,
            "delta_star_proposed": DELTA_STAR,
            "delta_star_status": "待审开发界限 PENDING_REVIEW (no downstream tolerance basis)",
            "delta_star_sensitivity": list(DELTA_STAR_SENSITIVITY),
            "rho_grid": list(RHO_GRID),
            "planning_rho": PLANNING_RHO,
            "near_zero_delta_pre_stated": NEAR_ZERO_DELTA,
            "beyond_delta_pre_stated": BEYOND_DELTA,
            "delta_scenarios_pre_stated": list(DELTA_SCENARIOS),
            "direction_convention": "delta = p_analytic - recall(validation); "
                                    "delta>0 即实测 recall 低于解析预测",
        },
        "A_min_k_and_zero_bias_power": part_a_min_k_and_power(),
        "B_power_scenarios_corrected_analysis_se": part_b_power_scenarios_corrected_se(),
        "C_false_equivalence_unadjusted_analysis_se": part_c_false_equivalence_unadjusted_se(),
        "D_aggregate_se_model": part_d_aggregate_se_model(),
        "E_bootstrap_numerical_error": part_e_bootstrap_numerical_error(),
        "F_action_classification": part_f_classification(),
        "G_blocks_derivation": part_g_blocks_derivation(),
        "H_design_only_mc_coherence": part_h_mc_coherence(mc_reps),
        "I_recommended_design": part_i_recommended_design(),
        "assumptions_and_limits": [
            "已知SE正态模型是主分析路径的设计层近似;实际分析以bootstrap "
            "估计SE代入同一区间式,其操作特性与已知SE情形的差异已披露,"
            "由rho敏感性与保守规划部分覆盖,不另立t分布第二框架",
            "坐标独立性(rho_c=0)是设计假设:预注册新namespace/attempt/种子;"
            "正相关会使聚合SE按sqrt(1+(K-1)rho_c)放大,超出rho敏感性口径",
            "SE∝1/sqrt(B) 为单点锚外推假设,指数未经第二锚点验证",
            "Delta=0.003待审;敏感性Delta∈{0.002,0.003,0.004}已给出",
            "MC仅为算术自洽复核(coherence),不证明真实簇结构/解析锚满足模型",
            "本轮无新项目抽样;R19终态、journal、准入面原样",
        ],
    }


# ---- 自检 -----------------------------------------------------------
def selftest() -> None:
    z = critical_z()
    assert abs(z - 1.6448536269514722) < 1e-12
    # 1) 零偏差公式与一般概率函数一致(同一功效函数)
    for k in (1, 2, 5, 8, 11, 17):
        for rho in RHO_GRID:
            s = rho * VALID_SE
            a = zero_bias_power(DELTA_STAR, k, s)
            b = equivalence_probability(0.0, DELTA_STAR, k, s)
            assert abs(a - b) < 1e-12, (k, rho, a, b)
    # 2) C01 验收数(Delta=.003, alpha=.05, SE=rho*VALID_SE 双侧同调)
    c01 = {
        1.0: (5, 0.9298751722715561, 0.851892463372879, 0.9936014252023164),
        1.25: (8, 0.9360214241815692, 0.8961484388557075, 0.9360214241815692),
        1.5: (11, 0.9236864589708058, 0.8933540960149853, 0.7957248528496748),
    }
    for rho, (k_exp, p_k, p_km1, p_k8) in c01.items():
        s = rho * VALID_SE
        k = minimum_k(s, DELTA_STAR)
        assert k == k_exp, (rho, k, k_exp)
        assert abs(zero_bias_power(DELTA_STAR, k, s) - p_k) < 1e-9
        assert abs(zero_bias_power(DELTA_STAR, k - 1, s) - p_km1) < 1e-9
        assert abs(zero_bias_power(DELTA_STAR, 8, s) - p_k8) < 1e-9
        # 向上搜索逐点证明:j<K 全部未达标
        for j in range(1, k):
            assert zero_bias_power(DELTA_STAR, j, s) < TARGET_POWER
    # 3) 90%所需比值与 v2 错比值
    req = z + NORMAL.inv_cdf(0.95)
    assert abs(req - 3.2897072539029311) < 1e-9
    old = z + NORMAL.inv_cdf(0.90)
    assert abs((2.0 * NORMAL.cdf(old - z) - 1.0) - 0.8) < 1e-12  # v2 实际 80%
    # 4) 空接受区间与裁剪
    assert equivalence_probability(0.0, 0.00001, 1, 0.002) == 0.0
    assert zero_bias_power(0.00001, 1, 0.002) == 0.0
    for d in (-0.03, -0.003, 0.0, 0.003, 0.03):
        for k in (1, 5, 15):
            p = equivalence_probability(d, DELTA_STAR, k, 0.002)
            assert 0.0 <= p <= 1.0
    # 5) 对称性
    for d in (0.001, 0.002, 0.003, 0.01):
        assert abs(equivalence_probability(d, DELTA_STAR, 8, 0.002)
                   - equivalence_probability(-d, DELTA_STAR, 8, 0.002)) < 1e-14
    # 6) 正确SE下边界概率≈alpha且不超
    for k in (4, 8, 11, 15):
        p = equivalence_probability(DELTA_STAR, DELTA_STAR, k, VALID_SE)
        assert p <= ALPHA + 1e-12
        assert abs(p - ALPHA) < 1e-5, (k, p)
    # 7) C04 两张表分开:不修正时的假等效
    c04 = {1.0: 0.04999999999936777, 1.25: 0.09410666745056218,
           1.5: 0.13641379282587873}
    for rho, expected in c04.items():
        p = equivalence_probability(DELTA_STAR, DELTA_STAR, 8,
                                    rho * VALID_SE, VALID_SE)
        assert abs(p - expected) < 1e-9, (rho, p, expected)
    # 8) 异方差反例与锚
    ce = aggregate_se_independent([0.001, 0.003])
    wrong = (0.002) / math.sqrt(2)
    assert abs(ce - 0.0015811388300841897) < 1e-12
    assert abs(wrong - 0.001414213562373095) < 1e-12
    assert ce > wrong
    assert abs(aggregate_se_independent([0.002] * 8) - 0.002 / math.sqrt(8)) < 1e-15
    assert abs(aggregate_se_with_anchor([0.001, 0.003], 0.001)
               - 0.0018708286933869708) < 1e-12
    a1000 = aggregate_se_with_anchor([0.002] * 1000, 0.001)
    assert 0.001 < a1000 < 0.00101  # 锚不随K缩小(K=1000仍高0.2%)
    # 9) 相关公式
    assert abs(aggregate_se_equal_correlated(0.002, 8, 0.0)
               - 0.002 / math.sqrt(8)) < 1e-15
    assert abs(aggregate_se_equal_correlated(0.002, 11, 0.1)
               - 0.002 * math.sqrt(2.0 / 11.0)) < 1e-15
    # 10) blocks 尺度
    assert blocks_to_offset_rho(1.0) == 500
    assert blocks_to_offset_rho(1.25) == 782
    assert blocks_to_offset_rho(1.5) == 1125
    assert abs(se_at_blocks(2000) - VALID_SE / 2.0) < 1e-18
    assert abs(se_at_blocks(125) - 2.0 * VALID_SE) < 1e-18
    r1 = DELTA_STAR * math.sqrt(11) / se_at_blocks(500)
    r2 = DELTA_STAR * math.sqrt(5) / se_at_blocks(1100)
    assert abs(r1 - r2) < 1e-15  # K*B 不变性
    # 11) 分类工作示例与用例
    half = critical_z() * VALID_SE / math.sqrt(8)
    lo, hi = 0.0015 - half, 0.0015 + half
    assert abs(lo - 0.00037119176088350756) < 1e-15
    assert abs(hi - 0.0026288082391164925) < 1e-15
    got = classify_result(lo, hi, DELTA_STAR)
    assert got == {"magnitude": "within_equivalence_bounds", "direction": "positive"}
    assert "校准" not in ACTION_MAPPING[got["magnitude"]]
    assert "校准" in ACTION_MAPPING["beyond_positive_margin"]
    assert classify_result(0.001, 0.003, DELTA_STAR)["magnitude"] == "inconclusive"
    assert classify_result(0.002, 0.004, DELTA_STAR)["magnitude"] == "inconclusive"
    assert classify_result(None, None, DELTA_STAR) == {
        "magnitude": "inconclusive", "direction": "not_resolved"}
    assert classify_result(-0.005, -0.0035, DELTA_STAR) == {
        "magnitude": "beyond_negative_margin", "direction": "negative"}
    # 12) MC 自洽(降次数,固定种子,确定性)
    rows = mc_coherence(reps=20000)
    assert all(r["within_five_mc_se"] for r in rows)
    # 13) 输出可构建且情景覆盖完整
    out = build_output(mc_reps=20000)
    assert out["format"] == "r20-design-calc-v3"
    assert out["inputs"]["delta_scenarios_pre_stated"] == [
        0.0, 0.0005, 0.003, -0.003, 0.005]
    json.dumps(out, ensure_ascii=False, allow_nan=False)
    # 14) 非法输入拒绝
    for bad in ({"k": True}, {"k": 0}, {"k": 1.5}, {"margin": -1.0},
                {"delta": float("nan")}, {"true_single_se": 0.0},
                {"analysis_single_se": -1.0}, {"alpha": 0.5}):
        kwargs = dict(delta=0.0, margin=0.003, k=8, true_single_se=0.002)
        kwargs.update(bad)
        try:
            equivalence_probability(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"bad input accepted: {bad}")
    print("selftest OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true",
                        help="只运行内部自检,不写文件")
    parser.add_argument("--out", type=Path, default=None,
                        help="输出JSON路径(默认:脚本同目录 r20_design_calc_v3.json)")
    parser.add_argument("--mc-reps", type=int, default=MC_REPS_DEFAULT,
                        help="MC自洽复核次数(默认 100000,固定种子)")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.mc_reps < 1:
        parser.error("--mc-reps must be a positive integer")
    out_path = args.out or (Path(__file__).resolve().parent
                            / "r20_design_calc_v3.json")
    result = build_output(mc_reps=args.mc_reps)
    body = json.dumps(result, indent=1, ensure_ascii=False, allow_nan=False) + "\n"
    out_path.write_text(body, encoding="utf-8")
    krow = result["I_recommended_design"]["K_derivation"]
    print(f" wrote {out_path}")
    print(f" recommended K={krow['K']} power={krow['power_at_K']:.6f} "
          f"(rho={PLANNING_RHO}, Delta={DELTA_STAR}, target={TARGET_POWER})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
