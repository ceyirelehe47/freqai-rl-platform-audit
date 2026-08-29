"""Null 资格的确定性 Monte Carlo 功效分析 v2(阶段 2.6.0e 工作包 B)。

2.6.0e 修复的三个 2.6.0d 缺陷:

1. 经验分布必须先中心化(B1):旧实现 ``resample(empirical) + delta``
   使 target 掺入原始经验均值(delta 不代表声明的绝对优势)。v2 为
   ``resample(empirical - mean(empirical)) + target_absolute_edge``,
   target 因此具有真实、可审计的经济含义(绝对经济优势);
2. 四类比较全部进入硬门(B3):required blocks =
   always_long_vs_flat / oracle / rule_trend / high_turnover_vs_flat,
   不再只看 Always Long;
3. 比例判定用保守置信界(B5):Wilson score 双侧 95%(坏率取上界、
   好率取下界),不使用 Monte Carlo 点估计。

预注册场景(POWER_SCENARIO_MANIFEST,见 null_qualification_spec):
- valid_zero_edge(真无优势,误判 INVALID 率上界 <= 5%);
- inside_half_tolerance / boundary_diagnostic(诊断,不作门);
- violation_plus_1x_margin(容差 + 1 x margin 的违规优势,未获
  QUALIFIED 的功效下界 >= 80%);
- violation_plus_2x_margin(容差 + 2 x margin,错误 QUALIFIED 率
  上界 <= 5%)。

零方差 required scenario(B4):经验 residual 全为零时走解析确定性
分支(平移后为常数序列,判定完全确定),不得标记 skipped,仍计入
required-scenario coverage。

cluster 数重新校准(B6):对预注册阶梯(32/64/96/128)逐档评估全部
硬目标,选择满足所有 family x block x scenario 目标的最小档;选定值
必须与冻结的 MIN_QUALIFICATION_CLUSTERS 一致(否则 fail closed)。

判定逻辑与 qualify_null_family 完全相同(_evaluate_check);bootstrap
以向量化实现,索引流与 evaluator.paired_bootstrap_ci 逐位一致(测试
power_centering_parity 强制对账)。全部随机源固定,报告哈希(npa-)
与代码哈希(npac-)进入 sealed commitment;正式执行器按
null_power_reverification 确定性重跑并对账。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.evaluator import (
    BOOTSTRAP_DEFAULT_ITERS,
    BOOTSTRAP_SEED,
    paired_bootstrap_ci,
)
from rl_curriculum.null_qualification import _evaluate_check
from rl_curriculum.null_qualification_spec import (
    CLUSTER_CANDIDATE_LADDER,
    MIN_QUALIFICATION_CLUSTERS,
    POWER_MC_CONFIG,
    POWER_SCENARIO_MANIFEST,
    POWER_TARGETS,
    TOLERANCE_BY_BLOCK,
    scenario_manifest_hash,
)

POWER_ANALYSIS_FORMAT = "null-power-analysis-v2"
#: 已弃用格式(v1:未中心化 + 只覆盖 Always Long + 点估计判定)
_DEPRECATED_POWER_FORMATS: tuple[str, ...] = (
    "null-power-analysis-v1",
)

MC_ITERS = int(POWER_MC_CONFIG["mc_iters"])
MC_SEED = int(POWER_MC_CONFIG["mc_seed"])
CONFIDENCE_METHOD = str(POWER_MC_CONFIG["confidence_method"])
_WILSON_Z = 1.959963984540054  # 双侧 95%(单侧 97.5%;保守取界)

#: required 比较块(顺序稳定;全部进入硬门)
REQUIRED_BLOCKS: tuple[str, ...] = (
    "always_long_vs_flat", "oracle", "rule_trend", "high_turnover_vs_flat",
)

_VERDICTS = ("QUALIFIED", "INVALID_NULL", "INSUFFICIENT_EVIDENCE")

#: 向量化 bootstrap 的固定索引流缓存(与 paired_bootstrap_ci 逐位一致)
_INDEX_CACHE: dict[int, np.ndarray] = {}


def _bootstrap_index_matrix(n: int) -> np.ndarray:
    """paired_bootstrap_ci 的固定种子索引流,一次性按行主序生成。

    该 Generator 逐次调用 integers(0, n, size=n) n_boot 次与一次
    integers(0, n, size=(n_boot, n)) 消费同一比特流,输出逐位一致;
    缓存后对整批 MC 样本按行复用(判定语义不变,速度向量化)。
    """
    if n not in _INDEX_CACHE:
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        _INDEX_CACHE[n] = rng.integers(
            0, n, size=(BOOTSTRAP_DEFAULT_ITERS, n))
    return _INDEX_CACHE[n]


def _verdict_matrix(samples: np.ndarray, bound: float) -> np.ndarray:
    """对每行 cluster 样本执行与 _evaluate_check 相同的判定。

    返回 verdict 字符串数组;bootstrap 索引/均值/分位与
    paired_bootstrap_ci + _evaluate_check 逐位一致(测试强制对账)。
    """
    idx = _bootstrap_index_matrix(samples.shape[1])
    means = np.empty((samples.shape[0], idx.shape[0]), dtype=np.float64)
    for b in range(idx.shape[0]):
        means[:, b] = samples[:, idx[b]].mean(axis=1)
    lo = np.quantile(means, 0.025, axis=1)
    hi = np.quantile(means, 0.975, axis=1)
    center = samples.mean(axis=1)
    passed = (center <= bound) & (hi <= bound)
    disproven = lo > bound
    out = np.where(
        disproven, "INVALID_NULL",
        np.where(passed, "QUALIFIED", "INSUFFICIENT_EVIDENCE"))
    return out


def _wilson(k: int, n: int) -> tuple[float, float]:
    """Wilson score 双侧 95% 区间(比例置信界;n=0 时无信息)。"""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    z2 = _WILSON_Z * _WILSON_Z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    half = (_WILSON_Z * np.sqrt(
        p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom)
    return (float(center - half), float(center + half))


def _scenario_target(name: str, tolerance: float, margin: float) -> float:
    if name == "valid_zero_edge":
        return 0.0
    if name == "inside_half_tolerance":
        return 0.5 * tolerance
    if name == "boundary_diagnostic":
        return tolerance
    if name == "violation_plus_1x_margin":
        return tolerance + 1.0 * margin
    if name == "violation_plus_2x_margin":
        return tolerance + 2.0 * margin
    raise ValueError(f"未知预注册场景 {name!r}")


def _simulate_rates(
    base_values: list[float], target_absolute_edge: float, n: int, *,
    bound: float, tolerance: float, scenario_index: int,
) -> dict[str, Any]:
    """中心化非参数 MC(或零方差解析分支)。

    residuals = empirical - mean(empirical);
    sample = resample(residuals) + target_absolute_edge。
    记录原始经验中心 / 残差中心 / target / tolerance / 超出量 /
    实际模拟样本中心,供审计 target 的绝对经济含义。
    """
    arr = np.asarray(base_values, dtype=np.float64)
    empirical_center = float(arr.mean())
    residuals = arr - empirical_center
    residual_center = float(residuals.mean())
    zero_variance = bool(np.all(residuals == 0.0))
    if zero_variance:
        # B4:零方差 required scenario 走解析确定性分支(平移后常数
        # 序列,bootstrap 退化但判定完全确定);不得标记 skipped
        constant = [float(target_absolute_edge)] * int(n)
        boot, passed, disproven = _evaluate_check(constant, bound)
        verdict = ("INVALID_NULL" if disproven
                   else "QUALIFIED" if passed else "INSUFFICIENT_EVIDENCE")
        counts = {v: (1 if v == verdict else 0) for v in _VERDICTS}
        return {
            "n": int(n),
            "mode": "analytic_zero_variance",
            "deterministic": True,
            "target_absolute_edge": float(target_absolute_edge),
            "tolerance": float(tolerance),
            "target_excess_over_tolerance": float(
                target_absolute_edge - tolerance),
            "empirical_center": empirical_center,
            "residual_center": residual_center,
            "simulated_center": float(target_absolute_edge),
            "mc_iters": 0,
            "counts": counts,
            "total": 1,
            "rates": {v: (1.0 if v == verdict else 0.0) for v in _VERDICTS},
            "bootstrap": boot,
        }
    rng = np.random.default_rng(MC_SEED + scenario_index * 7919)
    draws = residuals[rng.integers(
        0, len(residuals), size=(MC_ITERS, n))] + float(target_absolute_edge)
    verdicts = _verdict_matrix(draws, bound)
    counts = {v: int((verdicts == v).sum()) for v in _VERDICTS}
    total = int(verdicts.size)
    return {
        "n": int(n),
        "mode": "centered_residual_resample",
        "deterministic": False,
        "target_absolute_edge": float(target_absolute_edge),
        "tolerance": float(tolerance),
        "target_excess_over_tolerance": float(
            target_absolute_edge - tolerance),
        "empirical_center": empirical_center,
        "residual_center": residual_center,
        "simulated_center": float(draws.mean()),
        "mc_iters": MC_ITERS,
        "counts": counts,
        "total": total,
        "rates": {v: counts[v] / total for v in _VERDICTS},
    }


def _block_tolerance(block: str, margin: float) -> float:
    sem = TOLERANCE_BY_BLOCK[block]
    return float(margin) if sem == "qualification_margin" else 0.0


def run_power_analysis(
    family_reports: dict[str, dict[str, Any]],
    *,
    margin: float,
) -> dict[str, Any]:
    """执行确定性功效分析 v2。

    family_reports:真实 family-level 资格报告(本函数只读取
    reports[family][block]["cluster_values"]——正式执行器以同一契约从
    承诺绑定的报告 payload 确定性重跑并复现 npa- 哈希);
    margin:来自 qualification spec 的经济 margin。

    返回报告 payload;targets_met 覆盖全部 family x required block x
    required scenario,否则资格链路 fail closed。
    """
    margin = float(margin)
    fams = sorted(family_reports)
    scenarios: list[dict[str, Any]] = []
    idx = 0

    for fam in fams:
        for block in REQUIRED_BLOCKS:
            tol = _block_tolerance(block, margin)
            base = family_reports[fam][block]["cluster_values"]
            manifest_block = POWER_SCENARIO_MANIFEST["blocks"][block]
            for scen in manifest_block["scenarios"]:
                target = _scenario_target(scen, tol, margin)
                for n in CLUSTER_CANDIDATE_LADDER:
                    entry = _simulate_rates(
                        base, target, n, bound=tol, tolerance=tol,
                        scenario_index=idx)
                    scenarios.append({
                        "scenario": scen, "family": fam, "block": block,
                        **entry,
                    })
                    idx += 1

    def _entry(fam: str, block: str, scen: str, n: int):
        for s in scenarios:
            if (s["scenario"] == scen and s["family"] == fam
                    and s["block"] == block and s["n"] == n):
                return s
        return None

    # ---- 逐候选 cluster 数评估(B6 预注册两层规则:(a)全部功效硬目标
    #      (Wilson 保守界);(b)该 n 的 namespace 前缀上三族四块经济
    #      等价检验全部通过——只满足功效但前缀资格不充分的档位不得
    #      选用;选择同时满足两项的最小档)
    base_clusters = min(
        (len(family_reports[f][b]["cluster_values"])
         for f in fams for b in REQUIRED_BLOCKS), default=0)
    ladder_eval: list[dict[str, Any]] = []
    for n in CLUSTER_CANDIDATE_LADDER:
        detail: dict[str, Any] = {}
        all_met = True
        for fam in fams:
            for block in REQUIRED_BLOCKS:
                zero = _entry(fam, block, "valid_zero_edge", n)
                v1 = _entry(fam, block, "violation_plus_1x_margin", n)
                v2 = _entry(fam, block, "violation_plus_2x_margin", n)
                fi_up = (
                    zero["rates"]["INVALID_NULL"]
                    if zero.get("deterministic")
                    else _wilson(zero["counts"]["INVALID_NULL"],
                                 zero["total"])[1])
                fq_up = (
                    v2["rates"]["QUALIFIED"]
                    if v2.get("deterministic")
                    else _wilson(v2["counts"]["QUALIFIED"], v2["total"])[1])
                rej_rate = 1.0 - v1["rates"]["QUALIFIED"]
                rej_low = (
                    rej_rate if v1.get("deterministic")
                    else _wilson(v1["total"] - v1["counts"]["QUALIFIED"],
                                 v1["total"])[0])
                ok = (fi_up <= POWER_TARGETS[
                          "max_false_invalid_rate_at_zero_edge"]
                      and fq_up <= POWER_TARGETS[
                          "max_false_qualified_rate_at_2x_margin"]
                      and rej_low >= POWER_TARGETS[
                          "min_rejection_power_at_1x_margin"])
                detail[f"{fam}::{block}"] = {
                    "false_invalid_wilson_upper": fi_up,
                    "false_qualified_2x_wilson_upper": fq_up,
                    "rejection_1x_point": rej_rate,
                    "rejection_1x_wilson_lower": rej_low,
                    "met": bool(ok),
                }
                all_met = all_met and ok
        # (b) 前缀资格经济充分性(n 超过经验基座时不可评估 -> 不可选)
        prefix_evaluable = bool(n <= base_clusters)
        econ_sufficient = False
        econ_detail: dict[str, Any] = {}
        if prefix_evaluable:
            econ_sufficient = True
            for fam in fams:
                for block in REQUIRED_BLOCKS:
                    tol = _block_tolerance(block, margin)
                    prefix = list(
                        family_reports[fam][block]["cluster_values"][:n])
                    boot, passed, disproven = _evaluate_check(prefix, tol)
                    ok_econ = bool(passed and not disproven)
                    econ_detail[f"{fam}::{block}"] = {
                        "center": float(np.mean(prefix)),
                        "ci_high": boot["ci_high"],
                        "passed": bool(passed),
                        "disproven": bool(disproven),
                        "met": ok_econ,
                    }
                    econ_sufficient = econ_sufficient and ok_econ
        ladder_eval.append({
            "n": int(n),
            "by_family_block": detail,
            "targets_met": bool(all_met),
            "prefix_evaluable": prefix_evaluable,
            "qualification_economics_sufficient": bool(econ_sufficient),
            "qualification_economics": econ_detail,
            "selectable": bool(all_met and prefix_evaluable
                               and econ_sufficient),
        })

    selected_n = next(
        (e["n"] for e in ladder_eval if e["selectable"]), None)
    if selected_n is None:
        raise RuntimeError(
            f"cluster 候选阶梯 {list(CLUSTER_CANDIDATE_LADDER)} 内没有任何"
            f"档位同时满足功效硬目标与前缀资格经济充分性(fail closed;"
            f"不得降低目标,也不得选用实际前缀资格 INSUFFICIENT 的档位)")
    if selected_n != MIN_QUALIFICATION_CLUSTERS:
        raise RuntimeError(
            f"功效分析选定的最小 cluster 数 {selected_n} 与冻结的 "
            f"MIN_QUALIFICATION_CLUSTERS={MIN_QUALIFICATION_CLUSTERS} 不一致"
            f"(选定值必须进入 spec hash;请先冻结常量再生成报告)")

    # ---- required scenario coverage(B4:零方差场景已由解析分支覆盖,
    #      不得出现 skipped)
    expected: list[str] = []
    for fam in fams:
        for block in REQUIRED_BLOCKS:
            for scen in POWER_SCENARIO_MANIFEST["blocks"][block][
                    "scenarios"]:
                expected.append(f"{fam}::{block}::{scen}")
    present = {
        f"{s['family']}::{s['block']}::{s['scenario']}"
        for s in scenarios if s["n"] == selected_n}
    skipped = sorted(set(expected) - present)
    unexpected = sorted(present - set(expected))
    required_complete = not skipped and not unexpected

    # ---- 最终 targets(selected n;Wilson 保守界)
    targets_detail: dict[str, Any] = {}
    max_fi, max_fq, min_rej = 0.0, 0.0, 1.0
    all_met = True
    for fam in fams:
        for block in REQUIRED_BLOCKS:
            zero = _entry(fam, block, "valid_zero_edge", selected_n)
            v1 = _entry(fam, block, "violation_plus_1x_margin", selected_n)
            v2 = _entry(fam, block, "violation_plus_2x_margin", selected_n)
            fi_up = (zero["rates"]["INVALID_NULL"]
                     if zero.get("deterministic")
                     else _wilson(zero["counts"]["INVALID_NULL"],
                                  zero["total"])[1])
            fq_up = (v2["rates"]["QUALIFIED"]
                     if v2.get("deterministic")
                     else _wilson(v2["counts"]["QUALIFIED"], v2["total"])[1])
            rej_rate = 1.0 - v1["rates"]["QUALIFIED"]
            rej_low = (rej_rate if v1.get("deterministic")
                       else _wilson(v1["total"] - v1["counts"]["QUALIFIED"],
                                    v1["total"])[0])
            met = (fi_up <= POWER_TARGETS[
                       "max_false_invalid_rate_at_zero_edge"]
                   and fq_up <= POWER_TARGETS[
                       "max_false_qualified_rate_at_2x_margin"]
                   and rej_low >= POWER_TARGETS[
                       "min_rejection_power_at_1x_margin"])
            targets_detail[f"{fam}::{block}"] = {
                "zero_edge": {
                    "rate_point": zero["rates"]["INVALID_NULL"],
                    "wilson_upper": fi_up,
                    "target": POWER_TARGETS[
                        "max_false_invalid_rate_at_zero_edge"],
                    "met": bool(fi_up <= POWER_TARGETS[
                        "max_false_invalid_rate_at_zero_edge"]),
                },
                "violation_plus_1x": {
                    "rejection_point": rej_rate,
                    "wilson_lower": rej_low,
                    "target": POWER_TARGETS[
                        "min_rejection_power_at_1x_margin"],
                    "met": bool(rej_low >= POWER_TARGETS[
                        "min_rejection_power_at_1x_margin"]),
                },
                "violation_plus_2x": {
                    "false_qualified_point": v2["rates"]["QUALIFIED"],
                    "wilson_upper": fq_up,
                    "target": POWER_TARGETS[
                        "max_false_qualified_rate_at_2x_margin"],
                    "met": bool(fq_up <= POWER_TARGETS[
                        "max_false_qualified_rate_at_2x_margin"]),
                },
                "met": bool(met),
            }
            max_fi = max(max_fi, zero["rates"]["INVALID_NULL"])
            max_fq = max(max_fq, v2["rates"]["QUALIFIED"])
            min_rej = min(min_rej, rej_rate)
            all_met = all_met and met

    report = {
        "format": POWER_ANALYSIS_FORMAT,
        "margin": margin,
        "power_targets": dict(POWER_TARGETS),
        "tolerance_by_block": {
            block: _block_tolerance(block, margin)
            for block in REQUIRED_BLOCKS},
        "centering": {
            "method": "residuals-plus-absolute-edge",
            "center_statistic": "mean",
            "note": (
                "residuals = empirical - mean(empirical);sample = "
                "resample(residuals) + target_absolute_edge(target 为真实"
                "绝对经济优势,不受原始经验均值污染)"),
        },
        "min_qualification_clusters": int(selected_n),
        "cluster_candidate_ladder": [int(n) for n in CLUSTER_CANDIDATE_LADDER],
        "cluster_selection": {
            "rule": (
                "预注册两层规则的最小档:(a)全部 family x block 功效硬目标"
                "(Wilson 保守界);(b)该 n 的 namespace 前缀上三族四块"
                "经济等价检验通过(前缀资格不充分的档位不得选用)"),
            "empirical_base_clusters": int(base_clusters),
            "selected": int(selected_n),
            "ladder": ladder_eval,
        },
        "mc_iters": MC_ITERS,
        "mc_seed": MC_SEED,
        "confidence_method": CONFIDENCE_METHOD,
        "scenario_manifest": json.loads(json.dumps(
            POWER_SCENARIO_MANIFEST)),
        "scenario_manifest_hash": scenario_manifest_hash(),
        "required_blocks": list(REQUIRED_BLOCKS),
        "required_scenario_count": len(expected),
        "required_scenarios_complete": bool(required_complete),
        "skipped_required_scenarios": skipped,
        "scenarios": scenarios,
        "targets": {
            "by_family_block": targets_detail,
            "max_false_invalid_at_zero": max_fi,
            "max_false_qualified_at_2x_margin": max_fq,
            "min_rejection_power_at_1x_margin": min_rej,
            "confidence_method": CONFIDENCE_METHOD,
            "targets_met": bool(
                all_met and required_complete and selected_n
                == MIN_QUALIFICATION_CLUSTERS),
        },
        "code_hash": power_analysis_code_hash(),
    }
    return report


def power_analysis_report_hash(report: dict[str, Any]) -> str:
    return "npa-" + hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def power_analysis_code_hash() -> str:
    """功效分析代码哈希(进入 sealed commitment;实现变化即失效)。"""
    src = Path(inspect.getsourcefile(run_power_analysis))  # type: ignore[arg-type]
    return "npac-" + hashlib.sha256(src.read_bytes()).hexdigest()


def power_centering_parity(
    base_values: list[float], delta: float, n: int, *, bound: float,
    scenario_index: int = 0,
) -> dict[str, Any]:
    """中心化语义 parity 证据(工作包 B1 测试/artifacts 用):

    - 注入 target 后样本中心期望 == target(残差重抽样期望中心为 0);
    - 大数定律意义下 simulated_center -> target(MC 批量均值)。
    """
    arr = np.asarray(base_values, dtype=np.float64)
    empirical_center = float(arr.mean())
    residuals = arr - empirical_center
    rng = np.random.default_rng(MC_SEED + scenario_index * 7919)
    draws = residuals[rng.integers(
        0, len(residuals), size=(MC_ITERS, n))] + float(delta)
    return {
        "empirical_center": empirical_center,
        "residual_center": float(residuals.mean()),
        "target_absolute_edge": float(delta),
        "simulated_center": float(draws.mean()),
        "simulated_center_gap": float(abs(draws.mean() - delta)),
        "mc_iters": MC_ITERS,
        "n": int(n),
    }


def bootstrap_matrix_parity(cluster_values: list[float]) -> dict[str, Any]:
    """向量化 bootstrap 与 paired_bootstrap_ci 的逐位一致性证据。"""
    arr = np.asarray(cluster_values, dtype=np.float64)
    idx = _bootstrap_index_matrix(len(arr))
    batch = arr[None, :]
    verdict = _verdict_matrix(batch, 0.0)[0]
    boot = paired_bootstrap_ci(list(cluster_values), stat="mean")
    _, passed, disproven = _evaluate_check(list(cluster_values), 0.0)
    expected_verdict = ("INVALID_NULL" if disproven
                        else "QUALIFIED" if passed else "INSUFFICIENT_EVIDENCE")
    return {
        "vectorized_verdict": str(verdict),
        "reference_verdict": expected_verdict,
        "reference_bootstrap": boot,
        "bitwise_match": bool(verdict == expected_verdict),
    }
