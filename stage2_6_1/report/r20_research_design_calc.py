#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R20 修订研究设计的可复算计算(design-only;不触碰项目生成器/数据)。

全部输入为 R19 原件的只读数值(cue_contract_audit 重现件)与
正态/二项近似;输出写入 r20_research_design_calc.json 供提案引用。
假设与数值误差随提案一起交付;模拟模型不能代替真实生成器的
经验覆盖验证。

用法:python3 r20_research_design_calc.py [--selftest]
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

#: R19 原件数值(head_reproduction_cue_contract_audit.json;只读锚)
P_ANALYTIC = 0.950431552876822
MODEL_POINT = 0.9492374056385765
MODEL_SE = 0.001861190194595879
VALID_POINT = 0.9459313536444273
VALID_SE = 0.0019410552950364546
N_CLUSTERS = 500
N_BOOT = 20000

#: 冻结规则:analytic 必须落在两个语料 block-cluster bootstrap
#: CI95 内(percentile bootstrap;此处以正态近似刻画其操作特性,
#: 偏差在提案中声明)。
Z95 = 1.959963984540054

#: 历史三代码态的 z 值(归因报告表;只作散布描述输入)
HIST_Z_MODEL = (0.64, 1.18, 1.31)
HIST_Z_VALID = (-0.79, 0.68, 2.32)

SIM_SEED = 20260925
SIM_REPS = 100_000

#: 待审建议的重要偏差幅度(提案正文给出依据;非已冻结合同)
DELTA_STAR_GRID = (0.002, 0.003, 0.004)
K_GRID = (3, 4, 5, 6, 8, 9, 10)
DELTA_TRUE_GRID = (0.0, 0.0005, 0.001, 0.0015, 0.002, 0.003, 0.004)


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def rule_pass_prob(delta: float, se: float) -> float:
    """单次重抽中,单语料 |z|≤z95 的概率(正态近似,SE 视为已知)。"""
    mu = delta / se
    return phi(Z95 - mu) - phi(-Z95 - mu)


def binom_pmf(k: int, n: int, p: float) -> float:
    return math.comb(n, k) * p ** k * (1.0 - p) ** (n - k)


def part_a_rule_operating_characteristics() -> dict:
    """冻结双包含规则在每坐标的通过概率(仅描述,不构成判定)。"""
    rows = []
    for delta_v in DELTA_TRUE_GRID:
        p_valid = rule_pass_prob(delta_v, VALID_SE)
        # model 语料无偏(三态 z 全正是方向性观察,不作为输入)
        p_model = rule_pass_prob(0.0, MODEL_SE)
        rows.append({
            "delta_valid": delta_v,
            "p_pass_valid": round(p_valid, 4),
            "p_pass_joint": round(p_model * p_valid, 4),
        })
    return {
        "assumption": "z ~ N(delta/SE, 1), SE 已知(bootstrap 相对误差"
                      f"≈{1.0 / math.sqrt(2 * N_BOOT):.4f},忽略)",
        "p_pass_model_no_bias": round(rule_pass_prob(0.0, MODEL_SE), 4),
        "rows": rows,
    }


def part_b_old_vote_rule() -> dict:
    """旧 K=5、≥4/5 表决的区分能力(未获批准;定量否决依据)。"""
    out = {"K": 5, "thresholds": {"pass": ">=4/5", "systematic": "<=2/5",
                                  "undecided": "3/5"}}
    rows = []
    for delta_v in DELTA_TRUE_GRID:
        p = rule_pass_prob(delta_v, VALID_SE) * rule_pass_prob(
            0.0, MODEL_SE)
        pg4 = sum(binom_pmf(k, 5, p) for k in (4, 5))
        pl2 = sum(binom_pmf(k, 5, p) for k in (0, 1, 2))
        rows.append({
            "delta_valid": delta_v,
            "p_rule_pass_per_draw": round(p, 4),
            "P_vote_ge4_of_5": round(pg4, 4),
            "P_vote_le2_of_5": round(pl2, 4),
            "P_undecided_3_of_5": round(binom_pmf(3, 5, p), 4),
        })
    out["rows"] = rows
    out["verdict"] = (
        "在 delta=0.003(建议重要偏差)处 P(>=4/5) 仍高,表决规则"
        "不能把重要偏差与零区分;数值见 rows")
    return out


def tost_power(delta_true: float, delta_star: float, k: int,
               se: float, alpha: float = 0.05) -> float:
    """已知 σ 的 TOST 等效性功效(双侧 90% CI 落入 ±delta_star)。"""
    sigma = se / math.sqrt(k)
    z_a = phi_inv_one_sided(alpha)  # z_{1-alpha} = 1.645
    # P[ CI90 上端 < delta* 且 CI90 下端 > -delta* ]
    return (phi((delta_star - delta_true) / sigma - z_a)
            - phi((-delta_star - delta_true) / sigma + z_a))


def phi_inv_one_sided(alpha: float) -> float:
    # 1.6449 via bisection on phi
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if phi(mid) < 1.0 - alpha:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def part_c_equivalence_design() -> dict:
    """推荐设计:K 个预注册新坐标的 pooled-mean TOST 等效性检验。"""
    z_a = phi_inv_one_sided(0.05)
    tables = {}
    for delta_star in DELTA_STAR_GRID:
        rows = []
        for k in K_GRID:
            sigma = VALID_SE / math.sqrt(k)
            margin_ratio = delta_star / sigma
            row = {
                "K": k,
                "se_pooled_mean": round(sigma, 6),
                "margin_over_se": round(margin_ratio, 3),
                "power": {},
            }
            for delta_true in DELTA_TRUE_GRID:
                row["power"][str(delta_true)] = round(
                    tost_power(delta_true, delta_star, k, VALID_SE), 4)
            rows.append(row)
        # 最小 K:经典等效性样本量判据 power(delta=0) >= 0.90
        # (margin/sigma >= z_{1-alpha} + z_{1-0.90} = 1.645 + 1.282);
        # 半幅度处功效单列(中间偏差判别力如实报告,不作门槛)
        target_ratio = z_a + 1.2815515655446004
        min_k = None
        for row in rows:
            if row["margin_over_se"] >= target_ratio:
                min_k = row["K"]
                break
        half_power = next(
            row["power"][str(round(0.5 * delta_star, 4))]
            for row in rows if row["K"] == (min_k or K_GRID[0]))
        tables[str(delta_star)] = {
            "z_one_sided_alpha": round(z_a, 4),
            "rows": rows,
            "min_K_power90_at_zero": min_k,
            "power_at_half_margin_at_min_K": half_power,
        }
    return tables


def part_d_simulation_check() -> dict:
    """蒙特卡洛复核 TOST 功效与规则通过率(正态世界 + SE 抖动)。"""
    rng = random.Random(SIM_SEED)
    out = {}
    delta_star = 0.003
    for k in (5, 9):
        for delta_true in (0.0, 0.0015, 0.003):
            hits = 0
            for _ in range(SIM_REPS):
                mean_delta = rng.gauss(delta_true, VALID_SE / math.sqrt(k))
                sigma = VALID_SE / math.sqrt(k)
                # SE 估计抖动:bootstrap SE 相对误差 ~ 1/sqrt(2*n_boot)
                sigma_hat = sigma * rng.gauss(
                    1.0, 1.0 / math.sqrt(2 * N_BOOT))
                half = 1.6448536269514722 * sigma_hat
                if mean_delta + half < delta_star \
                        and mean_delta - half > -delta_star:
                    hits += 1
            out[f"K={k},delta={delta_true}"] = round(
                hits / SIM_REPS, 4)
    mc_err = 0.5 / math.sqrt(SIM_REPS)
    return {"seed": SIM_SEED, "reps": SIM_REPS,
            "tost_power_at_delta_star_0.003": out,
            "mc_se": round(mc_err, 5)}


def part_e_cluster_sensitivity() -> dict:
    """若 bootstrap SE 低估真实重抽离散度 ρ 倍,所需 K 的变化。"""
    z_a = phi_inv_one_sided(0.05)
    target_ratio = z_a + 1.2815515655446004  # power 0.90 at delta=0
    rows = []
    for rho in (1.0, 1.25, 1.5):
        se_eff = VALID_SE * rho
        for delta_star in (0.002, 0.003):
            k_min = math.ceil((target_ratio * se_eff / delta_star) ** 2)
            rows.append({"rho_se_underestimate": rho,
                         "delta_star": delta_star,
                         "min_K_power90_at_zero": k_min})
    return {"criterion": "delta_star / (SE*rho/sqrt(K)) >= 1.645+1.282",
            "rows": rows}


def hist_dispersion() -> dict:
    def stats(values):
        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / (n - 1)
        return {"mean_z": round(mean, 3),
                "sd_z": round(math.sqrt(var), 3)}

    return {"model": stats(HIST_Z_MODEL),
            "validation": stats(HIST_Z_VALID),
            "note": "三代码态散布(实现散布量级);n=3 仅描述性"}


def selftest() -> None:
    assert abs(phi(1.959963984540054) - 0.975) < 1e-9
    assert abs(rule_pass_prob(0.0, VALID_SE) - 0.95) < 1e-9
    p = tost_power(0.0, 0.003, 5, VALID_SE)
    assert 0.90 < p < 1.0, p
    # 边界处功效 ≈ alpha(单侧)
    p_edge = tost_power(0.003, 0.003, 5, VALID_SE)
    assert p_edge < 0.10, p_edge
    # binom 归一
    assert abs(sum(binom_pmf(k, 5, 0.6) for k in range(6)) - 1.0) < 1e-9
    print("selftest OK")


def main() -> int:
    if "--selftest" in sys.argv:
        selftest()
        return 0
    result = {
        "format": "r20-research-design-calc-v1",
        "inputs": {
            "p_analytic": P_ANALYTIC,
            "model_point": MODEL_POINT, "model_se": MODEL_SE,
            "valid_point": VALID_POINT, "valid_se": VALID_SE,
            "n_clusters": N_CLUSTERS, "n_boot": N_BOOT,
            "z95": Z95,
            "observed_gap_valid": round(P_ANALYTIC - VALID_POINT, 6),
            "observed_z_valid": round(
                (P_ANALYTIC - VALID_POINT) / VALID_SE, 3),
        },
        "A_rule_operating_characteristics":
            part_a_rule_operating_characteristics(),
        "B_old_vote_rule_rejected": part_b_old_vote_rule(),
        "C_equivalence_design": part_c_equivalence_design(),
        "D_simulation_check": part_d_simulation_check(),
        "E_cluster_se_sensitivity": part_e_cluster_sensitivity(),
        "F_historical_dispersion": hist_dispersion(),
        "assumptions": [
            "每坐标语料 = 独立重抽(新 namespace/attempt 坐标);"
            "z_k = (p_analytic - recall_k)/SE_k 近似 N(delta/SE, 1)",
            "bootstrap SE 视为已知(相对误差≈0.5%,模拟中已含抖动)",
            "percentile bootstrap CI 以正态近似刻画;真实簇结构下的"
            "覆盖偏差未建模,需以真实生成器经验验证(见提案 §限制)",
            "model 语料按无偏处理;其三态 z 全正仅作方向性观察",
        ],
        "generated_by": "report/r20_research_design_calc.py (design-only)",
    }
    out = Path(__file__).resolve().parent / "r20_research_design_calc.json"
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(result["C_equivalence_design"]["0.003"]["rows"][2:6],
                     ensure_ascii=False, indent=1))
    print("B:", json.dumps(result["B_old_vote_rule_rejected"]["rows"][2:5],
                           ensure_ascii=False))
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
