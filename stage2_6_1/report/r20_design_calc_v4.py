#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R20 研究设计计算 v4(design-only;修复 v3 的行动方向反写,并把
固定分析安全系数 r_analysis=1.5 落进实际主分析区间)。

v3 已接受部分原样保留(最低K=5/8/11 的 matched-scale 算术、异方差
聚合SE、互斥幅度类别、触界/跨界/缺数据不决);本版(v4)按
RouteC_PluginLifecycle_AnalysisRule_NextGoal_v1 的设计收敛指令:

  C01 方向贯通:delta = p_analytic - recall(validation) 不变;
      正向重要超界 = 实测 recall **低于**解析预测(解析预测高估),
      负向 = 实测 recall **高于**解析预测(解析预测低估)。v3 的
      ACTION_MAPPING 把两者写反,本版修正并贯通到机读输出。
  C02 主分析固定 r_analysis=1.5:s_k 为原口径 block-cluster
      bootstrap 未乘安全系数的标准误;S_raw=sqrt(sum(s_k^2))/K,
      S_analysis=r_analysis*S_raw,CI90=delta_bar±z_(1-alpha)*
      S_analysis(alpha=0.05)。该倍率是抽样前固定的分析规则,
      实际报告区间与规划同一实现;r_analysis=1 仅作未修正对照,
      不参与结果挑选。
  C03 情景表固定 r_analysis=1.5、只改 r_true(design-only 变量,
      非运行后从结果挑的校正);规划范围外 r_true=2 如实展示。
  C04 最低K:保留 r_analysis=r_true matched-scale 参照(5/8/11),
      并按同一固定分析规则复算(r_true=1/1.25/1.5 → 8/9/11);
      主案规划最坏场景 r_true=1.5 维持 K=11。
  C05 等效界内可有非零方向;触界/跨界/缺数据不决;坐标数不足
      计划K时不冒用完整K推断。
  C06 1.5 是拟议固定安全系数,不是真实误差上界的证明;条件=正态、
      给定尺度、独立坐标、解析锚条件固定;有限 blocks 的 SE 估计
      误差、跨坐标相关、随机锚不确定性不由本表消除。

design-only:无新抽样,R20 未注册,R19 终态不变;不触碰生成器、
journal、准入面。v3 脚本与其 JSON 原件保留为历史(不覆盖)。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
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
#: 主分析固定安全系数:抽样前固定,实际 CI 与规划同一规则。
#: r_analysis=1 仅作"区间未修正"负对照,不参与主要行动选择。
R_ANALYSIS = 1.5
#: design-only 真实误差倍数情景(真实 SE 相对原口径 s_k 的倍数);
#: 非运行后从结果挑选的校正参数。2 为规划范围外失配示例。
R_TRUE_GRID = (1.0, 1.25, 1.5, 2.0)
PLANNING_R_TRUE = 1.5                # 主案规划最坏场景(与 r_analysis 同值)
K_REFERENCE = 8                      # v2 曾推荐;现仅作对照列
K_PROPOSED = 11                      # 主案推荐 K(待审)
# 事先声明的真偏差情景(计算前先列出,防事后挑值):
NEAR_ZERO_DELTA = 0.0005
BEYOND_DELTA = 0.005
DELTA_SCENARIOS = (0.0, NEAR_ZERO_DELTA, DELTA_STAR, -DELTA_STAR,
                   BEYOND_DELTA)

MC_SEED = 20260925
MC_REPS_DEFAULT = 100_000
MAX_K_SEARCH = 100_000

MAGNITUDE_CLASSES = ("within_equivalence_bounds", "beyond_positive_margin",
                     "beyond_negative_margin", "inconclusive")
DIRECTION_CONVENTION = (
    "delta = p_analytic - recall(validation);delta>0 即实测 recall "
    "低于解析预测(解析预测高估),delta<0 即实测 recall 高于解析"
    "预测(解析预测低估)")


# ---- 基础校验(与参考包同口径:bool 不是合法计数) --------------------
def _finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{name} must be a finite number")
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


# ---- 实际主分析(C02:固定 r_analysis 进入 CI) -----------------------
def aggregate_raw_se(standard_errors: list[float]) -> float:
    """原口径聚合SE(独立坐标等权平均):sqrt(sum(s_k^2))/K。

    s_k 为未乘安全系数的 block-cluster bootstrap 单坐标SE;
    异方差下不退化为 mean/sqrt(K)。
    """
    if not isinstance(standard_errors, list) \
            or not standard_errors:
        raise ValueError("standard_errors must be a non-empty list")
    ses = [_positive(se, "s_k") for se in standard_errors]
    return math.sqrt(math.fsum(s * s for s in ses)) / len(ses)


def analysis_se(standard_errors: list[float],
                r_analysis: float = R_ANALYSIS) -> float:
    """实际分析用聚合SE = r_analysis × S_raw(抽样前固定)。"""
    r_analysis = _positive(r_analysis, "r_analysis")
    return r_analysis * aggregate_raw_se(standard_errors)


def analysis_se_with_shared_anchor(standard_errors: list[float],
                                   shared_anchor_se: float,
                                   r_analysis: float = R_ANALYSIS
                                   ) -> float:
    """敏感性(非主案):S_analysis^2 = r^2·sum(s_k^2)/K^2 + s_anchor^2。

    共享锚项只加一次;不得除以 sqrt(K)。主案为条件固定解析锚
    (s_anchor=0)。"""
    shared = _positive(shared_anchor_se, "shared_anchor_se")
    base = aggregate_raw_se(standard_errors)
    return math.sqrt((r_analysis * base) ** 2 + shared * shared)


def analysis_ci(delta_bar: float, standard_errors: list[float], *,
                r_analysis: float = R_ANALYSIS,
                alpha: float = ALPHA) -> tuple[float, float]:
    """拟议主分析区间:delta_bar ± z_(1-alpha) × r_analysis×S_raw。

    alpha=0.05 ⇒ 正态 90% CI。倍率实际改变端点,不是只在规划表
    里出现。"""
    delta_bar = _finite(delta_bar, "delta_bar")
    half = critical_z(alpha) * analysis_se(standard_errors, r_analysis)
    return delta_bar - half, delta_bar + half


# ---- 幅度/方向分类(C01/C05) ----------------------------------------
def classify_result(lower: float | None, upper: float | None,
                    margin: float) -> dict[str, str]:
    """互斥幅度主类别 + 独立方向标签;触界保守归不决;缺数据归不决。

    幅度类别(互斥,四选一):
      within_equivalence_bounds  CI 严格落在 (-margin, margin) 内
      beyond_positive_margin     CI 下界严格大于 +margin
      beyond_negative_margin     CI 上界严格小于 -margin
      inconclusive               其余一切(含触界、跨界、缺数据)
    方向(辅助描述,另报;基于 delta=analytic−recall 的符号):
      positive  = 实测 recall 低于解析预测(区间严格为正)
      negative  = 实测 recall 高于解析预测(区间严格为负)
      not_resolved
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


#: 行动映射(C01 修正:与 delta=analytic−recall 同向)。
#: beyond_positive_margin ⇒ 实测 recall 偏低(解析预测高估);
#: beyond_negative_margin ⇒ 实测 recall 偏高(解析预测低估)。
ACTION_MAPPING = {
    "within_equivalence_bounds":
        "报告:在待审开发界限内等效(条件结论);非零方向偏差另报;"
        "无强制后续动作",
    "beyond_positive_margin":
        "研究建议:实测 recall 系统性偏低(解析预测高估实测 recall)"
        "超过待审界限,转校准路线(先修 analytic/语料缺口);"
        "不自动授予正式实验权限",
    "beyond_negative_margin":
        "研究建议:实测 recall 系统性偏高(解析预测低估实测 recall)"
        "超过待审界限,转校准路线;不自动授予正式实验权限",
    "inconclusive":
        "不决:如实报告设计能力不足/数据缺失;不得改称'涨落主导';"
        "无强制后续动作",
}


def action_statement(magnitude: str) -> str:
    if magnitude not in ACTION_MAPPING:
        raise ValueError(f"unknown magnitude class: {magnitude}")
    return ACTION_MAPPING[magnitude]


def classify_primary(delta_bar: float, standard_errors: list[float],
                     margin: float = DELTA_STAR, *,
                     r_analysis: float = R_ANALYSIS,
                     alpha: float = ALPHA,
                     planned_k: int | None = None) -> dict:
    """实际主分析入口:原始SE → 固定倍率CI → 互斥类别 → 行动文字。

    planned_k 在场且坐标数不足时不冒用完整K推断(magnitude=
    inconclusive,reason=insufficient_coordinates;方向仍如实描述)。
    """
    raw = aggregate_raw_se(standard_errors)
    used = analysis_se(standard_errors, r_analysis)
    lower, upper = analysis_ci(delta_bar, standard_errors,
                               r_analysis=r_analysis, alpha=alpha)
    verdict = classify_result(lower, upper, margin)
    reason = ""
    if planned_k is not None:
        planned_k = _count(planned_k, "planned_k")
        if len(standard_errors) < planned_k:
            reason = "insufficient_coordinates"
            if verdict["magnitude"] != "inconclusive":
                verdict = {"magnitude": "inconclusive",
                           "direction": verdict["direction"]}
    return {
        "delta_bar": delta_bar,
        "k_coordinates": len(standard_errors),
        "planned_k": planned_k,
        "s_raw": raw,
        "s_analysis": used,
        "r_analysis": r_analysis,
        "alpha": alpha,
        "lower90": lower,
        "upper90": upper,
        "margin": margin,
        "magnitude": verdict["magnitude"],
        "direction": verdict["direction"],
        "not_resolved_reason": reason,
        "action": action_statement(verdict["magnitude"]),
    }


# ---- TOST 概率/功效/最低K(C03/C04) ---------------------------------
def equivalence_probability(delta: float, margin: float, k: int,
                            true_single_se: float,
                            analysis_single_se: float,
                            alpha: float = ALPHA) -> float:
    """正态已知SE模型中,均值估计的 z-CI 整体落入 ±margin 的概率。

    区间用 analysis_single_se/sqrt(K)(分析侧规则),真分布用
    true_single_se/sqrt(K)(情景变量);两侧尺度分离正是
    r_analysis 与 r_true 的区别。
    """
    delta = _finite(delta, "delta")
    margin = _positive(margin, "margin")
    k = _count(k, "K")
    s_true = _positive(true_single_se, "true_single_se") / math.sqrt(k)
    s_used = _positive(analysis_single_se,
                       "analysis_single_se") / math.sqrt(k)
    z = critical_z(alpha)
    lower = -margin + z * s_used
    upper = margin - z * s_used
    if lower >= upper:
        return 0.0
    probability = NORMAL.cdf((upper - delta) / s_true) \
        - NORMAL.cdf((lower - delta) / s_true)
    return min(1.0, max(0.0, probability))


def zero_bias_power(margin: float, k: int, single_se: float,
                    alpha: float = ALPHA) -> float:
    """对称TOST在真偏差=0处的功效(matched-scale 契约公式)。"""
    return equivalence_probability(0.0, margin, k, single_se, single_se,
                                   alpha)


def minimum_k(single_se: float, margin: float,
              target_power: float = TARGET_POWER, alpha: float = ALPHA,
              max_k: int = MAX_K_SEARCH) -> int:
    """matched-scale 最低K:v3 已接受的算术参照(5/8/11 由此得)。"""
    for k in range(1, max_k + 1):
        if zero_bias_power(margin, k, single_se, alpha) >= target_power:
            return k
    raise ValueError("target power not attainable within max_k")


def minimum_k_fixed_analysis(margin: float, raw_single_se: float,
                             r_true: float, *,
                             r_analysis: float = R_ANALYSIS,
                             target_power: float = TARGET_POWER,
                             alpha: float = ALPHA,
                             max_k: int = MAX_K_SEARCH) -> int:
    """同一主分析规则(区间固定 r_analysis)下的最低K搜索。

    真分布 = r_true×raw;区间 = r_analysis×raw;两者不得混同,
    也不得按情景改区间倍率。"""
    for k in range(1, max_k + 1):
        if equivalence_probability(0.0, margin, k,
                                   r_true * raw_single_se,
                                   r_analysis * raw_single_se,
                                   alpha) >= target_power:
            return k
    raise ValueError("target power not attainable within max_k")


# ---- 聚合SE模型(v3 保留) --------------------------------------------
def aggregate_se_independent(standard_errors: list[float]) -> float:
    return aggregate_raw_se(standard_errors)


def aggregate_se_with_anchor(standard_errors: list[float],
                             shared_anchor_se: float) -> float:
    """独立坐标 + 一个共享独立解析锚:Var(mean)=sum(s_k^2)/K^2+Var(anchor)。"""
    shared = _positive(shared_anchor_se, "shared_anchor_se")
    base = aggregate_raw_se(standard_errors)
    return math.sqrt(base * base + shared * shared)


def se_at_blocks(blocks: int) -> float:
    """经验尺度假设 SE ∝ 1/sqrt(B),锚定 R19 的 B=500、SE=VALID_SE。"""
    blocks = _count(blocks, "blocks")
    return VALID_SE * math.sqrt(N_CLUSTERS_ANCHOR / blocks)


# ---- L1:实际区间规则与防漏乘对照(C02) ------------------------------
def part_l1_primary_analysis_rule() -> dict:
    contrast_r1 = classify_primary(0.0015, [VALID_SE] * K_REFERENCE,
                                   r_analysis=1.0)
    contrast_r15 = classify_primary(0.0015, [VALID_SE] * K_REFERENCE,
                                    r_analysis=1.5)
    worked = classify_primary(0.0015, [VALID_SE] * K_PROPOSED)
    return {
        "delta_convention": DIRECTION_CONVENTION,
        "formula": (
            "S_raw = sqrt(sum(s_k^2))/K; S_analysis = r_analysis*S_raw; "
            "CI90 = delta_bar ± z_(1-alpha)*S_analysis; alpha=0.05"),
        "r_analysis": R_ANALYSIS,
        "r_analysis_status": (
            "拟议固定安全系数(抽样前固定);不是真实误差上界的证明;"
            "实际报告区间与规划同一实现"),
        "r_analysis_one_role": (
            "r_analysis=1 仅作'区间未修正'负对照,不参与主要行动选择,"
            "不得按哪个区间更容易通过挑选主结果"),
        "worked_example_k11": worked,
        "guard_case_k8_same_inputs": {
            "note": (
                "同一组输入(delta_bar=0.0015,K=8,原SE=VALID_SE):"
                "乘1.5前在拟议等效界内,乘1.5后上端越过0.003 ⇒ 不决;"
                "防止规划表乘1.5而实际报告漏乘"),
            "r_analysis_1": contrast_r1,
            "r_analysis_1_5": contrast_r15,
        },
    }


# ---- L2:固定分析尺度情景表(C03) ------------------------------------
def part_l2_fixed_analysis_scenarios() -> dict:
    rows = []
    for r_true in R_TRUE_GRID:
        row = {
            "r_true": r_true,
            "r_analysis": R_ANALYSIS,
            "K": K_PROPOSED,
            "analysis_se_fixed": R_ANALYSIS * VALID_SE,
            "power_zero": equivalence_probability(
                0.0, DELTA_STAR, K_PROPOSED, r_true * VALID_SE,
                R_ANALYSIS * VALID_SE),
            "power_near_zero_0.0005": equivalence_probability(
                NEAR_ZERO_DELTA, DELTA_STAR, K_PROPOSED,
                r_true * VALID_SE, R_ANALYSIS * VALID_SE),
            "power_at_positive_boundary": equivalence_probability(
                DELTA_STAR, DELTA_STAR, K_PROPOSED, r_true * VALID_SE,
                R_ANALYSIS * VALID_SE),
            "power_at_negative_boundary": equivalence_probability(
                -DELTA_STAR, DELTA_STAR, K_PROPOSED, r_true * VALID_SE,
                R_ANALYSIS * VALID_SE),
            "power_beyond_0.005": equivalence_probability(
                BEYOND_DELTA, DELTA_STAR, K_PROPOSED, r_true * VALID_SE,
                R_ANALYSIS * VALID_SE),
        }
        row["false_equivalence_at_boundary"] = \
            row["power_at_positive_boundary"]
        rows.append(row)
    negative_control = {
        "r_true": 1.5,
        "r_analysis": 1.0,
        "K": K_PROPOSED,
        "false_equivalence_at_positive_boundary":
            equivalence_probability(
                DELTA_STAR, DELTA_STAR, K_PROPOSED,
                1.5 * VALID_SE, VALID_SE),
        "role": "未修正区间负对照(不参与主要行动选择)",
    }
    return {
        "margin": DELTA_STAR,
        "alpha": ALPHA,
        "primary_rule": f"analysis SE fixed at r_analysis={R_ANALYSIS}",
        "r_true_role": (
            "design-only 情景变量(真实误差相对原口径SE的倍数);"
            "不是运行后挑出的校正参数,不进入实际区间"),
        "scenario_deltas_pre_stated": list(DELTA_SCENARIOS),
        "rows": rows,
        "unadjusted_negative_control": negative_control,
        "planning_boundary_note": (
            "r_true=2 为规划范围外失配示例,不构成任何普适保证;"
            "近零/非零真偏差不保证同样功效,如实列出"),
    }


# ---- A:matched-scale 最低K参照(v3 已接受,保留) --------------------
def part_a_min_k_matched_scale() -> dict:
    rows = []
    for margin in DELTA_STAR_SENSITIVITY:
        for rho in (1.0, 1.25, 1.5):
            s = rho * VALID_SE
            k_min = minimum_k(s, margin)
            rows.append({
                "margin": margin,
                "rho": rho,
                "single_se": s,
                "min_K_power90_at_zero": k_min,
                "power_at_min_K": zero_bias_power(margin, k_min, s),
                "power_at_K_minus_one": zero_bias_power(
                    margin, k_min - 1, s),
                "power_at_K8": zero_bias_power(margin, K_REFERENCE, s),
            })
    return {
        "status": "v3 已接受的算术参照(mmatched r_analysis=r_true);"
                  "不是主案随真实情景自动换尺度的执行规则",
        "formula": "max(0, 2*Phi(margin*sqrt(K)/s - z_(1-alpha)) - 1)",
        "rows": rows,
    }


# ---- K:同一主分析规则复算最低K与推荐(C04) ---------------------------
def part_k_recompute_under_primary_rule() -> dict:
    fixed_rows = []
    for r_true in (1.0, 1.25, 1.5):
        k_min = minimum_k_fixed_analysis(DELTA_STAR, VALID_SE, r_true)
        fixed_rows.append({
            "r_true": r_true,
            "r_analysis": R_ANALYSIS,
            "min_K_power90_at_zero": k_min,
            "power_at_min_K": equivalence_probability(
                0.0, DELTA_STAR, k_min, r_true * VALID_SE,
                R_ANALYSIS * VALID_SE),
            "power_at_K_minus_one": equivalence_probability(
                0.0, DELTA_STAR, k_min - 1, r_true * VALID_SE,
                R_ANALYSIS * VALID_SE),
        })
    k_rec = K_PROPOSED
    worst = PLANNING_R_TRUE
    alt_margin = 0.002
    return {
        "rule": (
            "min K with zero-bias power >= 0.90 at alpha=0.05; "
            "interval SE fixed at r_analysis=1.5×VALID_SE, "
            "truth SE = r_true×VALID_SE"),
        "fixed_analysis_min_k": fixed_rows,
        "recommended": {
            "K": k_rec,
            "justification": (
                "主案规划最坏场景 r_true=1.5(与 r_analysis 同值),"
                "matched-scale 与固定分析规则在该场景一致 ⇒ K=11"),
            "power_at_K_zero_bias_worst_case": equivalence_probability(
                0.0, DELTA_STAR, k_rec, worst * VALID_SE,
                R_ANALYSIS * VALID_SE),
            "power_at_K_minus_one_worst_case": equivalence_probability(
                0.0, DELTA_STAR, k_rec - 1, worst * VALID_SE,
                R_ANALYSIS * VALID_SE),
        },
        "alternative_margin_0.002": {
            "K_at_r_true_1.25": minimum_k_fixed_analysis(
                alt_margin, VALID_SE, 1.25),
            "K_at_r_true_1.5": minimum_k_fixed_analysis(
                alt_margin, VALID_SE, 1.5),
            "when": "仅当审查方认定 0.002 以下偏差亦重要;预算更高,不推荐首选",
        },
    }


# ---- F:行动分类规则与方向工作示例(C01/C05) --------------------------
def part_f_classification() -> dict:
    cases = {}
    for name, lo, up in (
        ("beyond_positive", 0.0031, 0.0040),
        ("beyond_negative", -0.0050, -0.0035),
        ("within_bounds_nonzero_direction", 0.0005, 0.0025),
        ("touching_bound", 0.0010, 0.0030),
        ("straddling_bound", 0.0020, 0.0040),
        ("missing_data", None, None),
    ):
        verdict = classify_result(lo, up, DELTA_STAR)
        cases[name] = {**verdict,
                       "action": action_statement(verdict["magnitude"])}
    insufficient = classify_primary(0.0020, [VALID_SE] * 5,
                                    planned_k=K_PROPOSED)
    return {
        "magnitude_classes_mutually_exclusive": list(MAGNITUDE_CLASSES),
        "direction_labels": ["positive", "negative", "not_resolved"],
        "direction_convention": DIRECTION_CONVENTION,
        "touching_or_crossing_or_missing": "inconclusive",
        "action_mapping": dict(ACTION_MAPPING),
        "cases": cases,
        "insufficient_coordinates_not_full_k_inference": {
            "k_coordinates": insufficient["k_coordinates"],
            "planned_k": insufficient["planned_k"],
            "magnitude": insufficient["magnitude"],
            "not_resolved_reason": insufficient["not_resolved_reason"],
            "note": "提前停止只做描述性报告,不得宣称达到完整K设计的推断",
        },
    }


# ---- G:blocks 推导与预算(v3 口径保留,主案 B=500) -------------------
def part_g_blocks_and_budget() -> dict:
    k_rec = K_PROPOSED
    return {
        "scaling_assumption": "SE(B) = VALID_SE * sqrt(500/B); "
                              "single-anchor extrapolation, exponent not "
                              "verifiable from one point (stated assumption)",
        "recommended_blocks_per_coordinate_corpus": N_CLUSTERS_ANCHOR,
        "blocks_to_offset_rho_at_fixed_se_target": {
            "formula": "B = ceil(500 * rho^2)",
            "rows": [{"rho": rho,
                      "blocks": math.ceil(N_CLUSTERS_ANCHOR * rho * rho)}
                     for rho in (1.0, 1.25, 1.5)],
        },
        "k_times_b_invariance": {
            "recommended_KB": k_rec * N_CLUSTERS_ANCHOR,
            "note": "同等总预算下多坐标覆盖跨坐标散布;加blocks只压缩"
                    "单坐标重抽噪声;故选 (K=11, B=500)",
        },
    }


# ---- H:design-only 蒙特卡洛自洽(coherence only) ---------------------
def mc_coherence(reps: int = MC_REPS_DEFAULT,
                 seed: int = MC_SEED) -> list[dict]:
    """固定种子/次数的抽象正态试算;只验证公式算术自洽。

    仿真世界假设与分析端假设在此分开声明;r_analysis≠r_true 的行
    验证的是"区间规则固定"下的概率计算,不证明真实模型。
    """
    reps = _count(reps, "reps")
    rng = random.Random(seed)
    scenarios = [
        # (r_true, r_analysis, delta_true, K)
        (1.5, 1.5, 0.0, K_PROPOSED),
        (1.0, 1.5, 0.0, K_PROPOSED),
        (1.25, 1.5, 0.0, K_PROPOSED),
        (1.5, 1.0, DELTA_STAR, K_PROPOSED),
        (1.5, 1.5, DELTA_STAR, K_REFERENCE),
    ]
    rows = []
    for r_true, r_analysis, delta, k in scenarios:
        half = critical_z() * r_analysis * VALID_SE / math.sqrt(k)
        lo, hi = -DELTA_STAR + half, DELTA_STAR - half
        hits = 0
        for _ in range(reps):
            estimate = rng.gauss(delta, r_true * VALID_SE / math.sqrt(k))
            hits += lo < estimate < hi
        exact = equivalence_probability(delta, DELTA_STAR, k,
                                        r_true * VALID_SE,
                                        r_analysis * VALID_SE)
        sim = hits / reps
        mc_se = math.sqrt(exact * (1.0 - exact) / reps)
        rows.append({
            "r_true": r_true, "r_analysis": r_analysis,
            "true_delta": delta, "K": k,
            "exact_probability": exact, "simulation_probability": sim,
            "repetitions": reps, "mc_standard_error": mc_se,
            "within_five_mc_se": abs(sim - exact) <= 5.0 * mc_se
                                 + 1.0 / reps,
        })
    return rows


def part_h_mc_coherence(reps: int = MC_REPS_DEFAULT) -> dict:
    rows = mc_coherence(reps)
    if not all(row["within_five_mc_se"] for row in rows):
        raise RuntimeError("MC coherence check failed; retain the result")
    return {
        "coherence_check_only": True,
        "seed": MC_SEED,
        "repetitions": reps,
        "interpretation": (
            "仿真世界与分析端假设同源;一致仅证明公式算术正确,"
            "不证明该正态已知SE模型对真实生成器/簇结构成立"),
        "rows": rows,
    }


# ---- I:待审提案(单一可执行;C06) -----------------------------------
def part_i_proposal() -> dict:
    return {
        "status": (
            "待审设计(PENDING_REVIEW);本轮不批准任何新抽样,"
            "R20 未注册;完成 A/C 工程与设计收敛不构成研究授权"),
        "single_pending_decision": (
            "是否采纳本设计及预算:Delta=0.003(待审),alpha=0.05,"
            "主分析固定 r_analysis=1.5,K=11,每语料 500 blocks"),
        "primary_analysis_path": (
            "每坐标有符号偏差 delta_k = p_analytic - recall(validation)"
            " + R19 同口径 block-cluster bootstrap 原始SE s_k;"
            "delta_bar=mean(delta_k);S_raw=sqrt(sum(s_k^2))/K;"
            "S_analysis=1.5*S_raw;CI90=delta_bar±z*S_analysis;"
            "互斥幅度类别+方向标签;坐标数<K=11 时不做完整K推断"),
        "design_targets": {
            "margin_delta_star": DELTA_STAR,
            "margin_status": "待审开发界限;无下游容忍度依据",
            "alpha": ALPHA,
            "target_power_at_zero_delta": TARGET_POWER,
            "r_analysis_fixed": R_ANALYSIS,
            "planning_worst_case_r_true": PLANNING_R_TRUE,
            "K": K_PROPOSED,
        },
        "budget_and_stop_rules": [
            "每坐标一次 audit 叶;K 与坐标清单批准后冻结,无追加、"
            "无重抽、无失败替换",
            "提前停止只按已完成坐标做描述性报告,不得以完整K=11"
            "预注册TOST作推断",
            "研究(dev)数据与未来正式确认数据物理隔离;等效成立不"
            "自动许可正式链",
        ],
        "limits_and_boundaries": [
            "1.5 是拟议固定安全系数,不是真实误差必然小于该值的证明",
            "条件模型:正态、给定尺度、独立坐标、解析锚条件固定;"
            "5% 只按明示条件解释,非真实生成器经验保证",
            "有限原始 blocks 的 SE 统计不确定性、跨坐标相关、随机"
            "解析锚不确定性不被敏感性表或多bootstrap消除;共享锚"
            "敏感性沿用独立加一次公式(s_anchor 只加一次)",
            "若未来流程每坐标重估解析锚、共享随机权重或目标变为"
            "无条件平均,现有简单式不能直接沿用,缺项须显式建模",
            "SE∝1/sqrt(B) 为单点锚外推假设,指数未经第二锚点验证",
        ],
    }


def build_output(mc_reps: int = MC_REPS_DEFAULT) -> dict:
    return {
        "format": "r20-design-calc-v4",
        "generated_by": "stage2_6_1/report/r20_design_calc_v4.py "
                        "(design-only)",
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
            "delta_star_status": "待审开发界限 PENDING_REVIEW",
            "r_analysis_fixed": R_ANALYSIS,
            "r_true_grid": list(R_TRUE_GRID),
            "planning_worst_case_r_true": PLANNING_R_TRUE,
            "K_proposed": K_PROPOSED,
            "scenario_deltas_pre_stated": list(DELTA_SCENARIOS),
            "direction_convention": DIRECTION_CONVENTION,
        },
        "L1_primary_analysis_rule": part_l1_primary_analysis_rule(),
        "L2_fixed_analysis_scenarios": part_l2_fixed_analysis_scenarios(),
        "A_min_k_matched_scale_retained": part_a_min_k_matched_scale(),
        "K_recompute_under_primary_rule": part_k_recompute_under_primary_rule(),
        "F_action_classification": part_f_classification(),
        "G_blocks_and_budget": part_g_blocks_and_budget(),
        "H_design_only_mc_coherence": part_h_mc_coherence(mc_reps),
        "I_proposal_pending_review": part_i_proposal(),
    }


# ---- 自检 -----------------------------------------------------------
def selftest() -> None:
    z = critical_z()
    assert abs(z - 1.6448536269514722) < 1e-12
    # K=11 主案数字(S_raw/S_analysis/CI 半宽,与参考包同值)
    ses = [VALID_SE] * K_PROPOSED
    s_raw = aggregate_raw_se(ses)
    assert abs(s_raw - VALID_SE / math.sqrt(K_PROPOSED)) < 1e-18
    assert abs(analysis_se(ses) - 1.5 * s_raw) < 1e-18
    assert abs(critical_z() * analysis_se(ses)
               - 0.0014439763512465087) < 1e-15
    # 方向贯通:delta>0 ⇒ 实测 recall 低;行动文字同向
    positive = classify_primary(0.0045, ses)
    assert positive["magnitude"] == "beyond_positive_margin"
    assert "偏低" in positive["action"] and "高估" in positive["action"]
    negative = classify_primary(-0.0045, ses)
    assert negative["magnitude"] == "beyond_negative_margin"
    assert "偏高" in negative["action"] and "低估" in negative["action"]
    # 防漏乘守卫:同输入 r=1 界内,r=1.5 不决
    guard1 = classify_primary(0.0015, [VALID_SE] * K_REFERENCE,
                              r_analysis=1.0)
    guard15 = classify_primary(0.0015, [VALID_SE] * K_REFERENCE,
                               r_analysis=1.5)
    assert guard1["magnitude"] == "within_equivalence_bounds"
    assert guard15["magnitude"] == "inconclusive"
    # 情景锚点(r_analysis=1.5 固定):r_true=1/1.5 的零偏差功效
    power1 = equivalence_probability(0.0, DELTA_STAR, K_PROPOSED,
                                     VALID_SE, 1.5 * VALID_SE)
    power15 = equivalence_probability(0.0, DELTA_STAR, K_PROPOSED,
                                      1.5 * VALID_SE, 1.5 * VALID_SE)
    assert abs(power1 - 0.9921564766) < 1e-9
    assert abs(power15 - 0.9236864590) < 1e-9
    # 未修正负对照 ≈13.64%(K 无关的边界值)
    control = equivalence_probability(DELTA_STAR, DELTA_STAR, K_PROPOSED,
                                      1.5 * VALID_SE, VALID_SE)
    assert abs(control - 0.1364148993) < 1e-9
    # matched-scale 最低K 保留 5/8/11
    assert minimum_k(VALID_SE, DELTA_STAR) == 5
    assert minimum_k(1.25 * VALID_SE, DELTA_STAR) == 8
    assert minimum_k(1.5 * VALID_SE, DELTA_STAR) == 11
    # 同一固定分析规则复算
    assert minimum_k_fixed_analysis(DELTA_STAR, VALID_SE, 1.5) == 11
    # 互斥类别与缺数据/不足坐标
    assert classify_result(None, None, DELTA_STAR)["magnitude"] == \
        "inconclusive"
    short = classify_primary(0.0045, [VALID_SE] * 3, planned_k=11)
    assert short["magnitude"] == "inconclusive" \
        and short["not_resolved_reason"] == "insufficient_coordinates"
    print("selftest OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", default=None,
                        help="写出机读 JSON(缺省=同目录"
                             " r20_design_calc_v4.json)")
    parser.add_argument("--mc-reps", type=int,
                        default=MC_REPS_DEFAULT)
    parser.add_argument("--selftest-only", action="store_true")
    args = parser.parse_args()
    selftest()
    if args.selftest_only:
        return 0
    document = build_output(args.mc_reps)
    out = args.json_out or str(__file__.replace(".py", ".json"))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=1,
                  sort_keys=True, allow_nan=False)
        handle.write("\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
