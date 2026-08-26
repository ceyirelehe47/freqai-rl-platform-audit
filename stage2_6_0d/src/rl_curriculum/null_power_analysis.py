"""阶段 2.6.0d 工作包 A5:Null 资格的确定性 Monte Carlo 功效分析。

目的:在预注册的经济 margin(一次完整往返摩擦)与统计协议(cluster
percentile bootstrap 单侧上置信界)下,实证最小独立 cluster 数的
判定特性,防止"功效不足却 PASS"或"零优势被误判 INVALID"。

场景覆盖(任务书 A5 全部六类):
1. 真正零优势 Null(delta = 0);
2. 正优势 0.5 x margin 的伪 Null;
3. 正优势 1 x margin 的伪 Null;
4. 正优势 2 x margin 的伪 Null;
5. 重尾与波动聚集场景(直接采用 stochvol(t 分布重尾 + 粘性波动
   聚集)与 volstate(状态条件化)的经验 cluster 分布);
6. 可预测方向但净漂移近零的伪 Null(Oracle 差值分布平移 delta:
   方向可读、AlwaysLong 无优势)。

预注册功效目标(POWER_TARGETS):
- 零优势 Null 的误判 INVALID 率 <= 5%;
- 优势 >= 2 x margin 的伪 Null 错误获得 QUALIFIED 的概率 <= 5%;
- 优势 = 1 x margin 的伪 Null 拒绝(未获得 QUALIFIED)功效 >= 80%。

方法:非参数 Monte Carlo——以真实 family-level 资格报告的经验
cluster 值分布为基底(有放回重抽样 n 个 cluster 值并平移 delta),
用与 qualify_null_family 完全相同的判定逻辑(单侧上置信界非优越
性检验 + 反证优先三态裁决)给出判定,统计各判定率。全部随机源
固定(MC_SEED),结果确定可复现;报告哈希(npa-)与代码哈希(npac-)
进入 sealed commitment。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.evaluator import paired_bootstrap_ci
from rl_curriculum.null_qualification import (
    HIGH_TURNOVER_TOLERANCE,
    _evaluate_check,
)
from rl_curriculum.null_qualification_spec import (
    MIN_QUALIFICATION_CLUSTERS,
    POWER_TARGETS,
)

POWER_ANALYSIS_FORMAT = "null-power-analysis-v1"
#: 每场景 Monte Carlo 次数(确定性;结果进 artifact)
MC_ITERS = 400
MC_SEED = 20260827


def _verdict_on_cluster_values(
    cluster_values: list[float], margin: float,
) -> str:
    """与 qualify_null_family 相同的判定逻辑(单策略视角):
    反证(置信下界 > margin)-> INVALID_NULL;上界与中心压进
    margin -> QUALIFIED;其余 -> INSUFFICIENT_EVIDENCE。"""
    _boot, passed, disproven = _evaluate_check(cluster_values, margin)
    if disproven:
        return "INVALID_NULL"
    if passed:
        return "QUALIFIED"
    return "INSUFFICIENT_EVIDENCE"


def _simulate_rate(
    base_values: list[float], delta: float, n: int, *, margin: float,
    scenario_index: int,
) -> dict[str, Any]:
    """非参数 MC:重抽样 n 个 cluster 值 + 平移 delta -> 判定率。"""
    rng = np.random.default_rng(MC_SEED + scenario_index * 7919)
    arr = np.asarray(base_values, dtype=np.float64)
    counts = {"QUALIFIED": 0, "INVALID_NULL": 0, "INSUFFICIENT_EVIDENCE": 0}
    for _ in range(MC_ITERS):
        sample = rng.choice(arr, size=n, replace=True) + delta
        counts[_verdict_on_cluster_values(
            [float(v) for v in sample], margin)] += 1
    total = sum(counts.values())
    return {
        "n": n,
        "delta": float(delta),
        "mc_iters": MC_ITERS,
        "rates": {k: v / total for k, v in counts.items()},
    }


def run_power_analysis(
    family_reports: dict[str, dict[str, Any]],
    *,
    margin: float,
) -> dict[str, Any]:
    """执行确定性功效分析。

    family_reports:真实 family-level 资格报告(提供经验 cluster
    分布);margin:来自 qualification spec 的经济 margin。
    返回报告 payload(targets_met 必须为真,否则资格链路 fail closed)。
    """
    scenarios: list[dict[str, Any]] = []
    idx = 0

    def _add(name: str, family: str, block: str, delta: float,
             n_list: tuple[int, ...]) -> None:
        nonlocal idx
        base = family_reports[family][block]["cluster_values"]
        for n in n_list:
            r = _simulate_rate(
                base, delta, n, margin=margin, scenario_index=idx)
            scenarios.append({
                "scenario": name, "family": family, "block": block,
                **r,
            })
            idx += 1

    fams = sorted(family_reports)
    # 1-4. 无条件多头优势场景(delta = 0 / 0.5m / 1m / 2m)
    for fam in fams:
        for label, mult in (("zero_edge", 0.0), ("half_margin", 0.5),
                            ("one_margin", 1.0), ("two_margin", 2.0)):
            _add(f"always_long_{label}", fam, "always_long_vs_flat",
                 mult * margin, (MIN_QUALIFICATION_CLUSTERS,))
    # 32-cluster 不足证据(任务书 A5:功效不足必须增加)
    _add("always_long_zero_edge_n32", fams[0], "always_long_vs_flat",
         0.0, (32,))
    _add("always_long_one_margin_n32", fams[0], "always_long_vs_flat",
         margin, (32,))
    _add("always_long_two_margin_n32", fams[0], "always_long_vs_flat",
         2 * margin, (32,))
    # 5. 重尾(stochvol 的 long 分布,t(4) 重尾)与波动聚集(volstate)
    #    场景已由各族真实分布承载;显式标注
    for fam in fams:
        _add("heavy_tail_check" if "stochvol" in fam
             else "volatility_clustering_check", fam,
             "always_long_vs_flat", 0.0, (MIN_QUALIFICATION_CLUSTERS,))
    # 6. 可预测方向但净漂移近零(Oracle 差值平移;AlwaysLong 无优势)。
    #    零方差分布(如 stochvol 的 Oracle 恒 flat -> cluster 值恒 0)
    #    平移后为常数序列,bootstrap 退化,跳过并记录。
    oracle_skipped = []
    for fam in fams:
        base = family_reports[fam]["oracle"]["cluster_values"]
        if float(np.std(base)) == 0.0:
            oracle_skipped.append(
                {"family": fam,
                 "reason": "Oracle cluster 分布零方差(恒 flat),"
                           "平移场景退化为常数序列,无统计意义"})
            continue
        _add("oracle_edge_one_margin", fam, "oracle",
             margin, (MIN_QUALIFICATION_CLUSTERS,))
        _add("oracle_edge_two_margin", fam, "oracle",
             2 * margin, (MIN_QUALIFICATION_CLUSTERS,))

    # ---- 目标核验(n = MIN_QUALIFICATION_CLUSTERS)
    def _rate(name: str, family: str, key: str) -> float | None:
        for s in scenarios:
            if (s["scenario"] == name and s["family"] == family
                    and s["n"] == MIN_QUALIFICATION_CLUSTERS):
                return s["rates"][key]
        return None

    zero_invalid = {
        fam: _rate(f"always_long_zero_edge", fam, "INVALID_NULL")
        for fam in fams}
    two_margin_qualified = {
        fam: _rate(f"always_long_two_margin", fam, "QUALIFIED")
        for fam in fams}
    one_margin_rejection = {
        fam: 1.0 - _rate(f"always_long_one_margin", fam, "QUALIFIED")
        for fam in fams}
    oracle_rejection = {
        fam: 1.0 - _rate("oracle_edge_one_margin", fam, "QUALIFIED")
        for fam in fams
        if _rate("oracle_edge_one_margin", fam, "QUALIFIED") is not None}
    max_false_invalid = max(zero_invalid.values())
    max_false_qualified = max(two_margin_qualified.values())
    min_power = min(one_margin_rejection.values())
    targets = {
        "zero_edge_false_invalid_rate_by_family": zero_invalid,
        "two_margin_false_qualified_rate_by_family": two_margin_qualified,
        "one_margin_rejection_power_by_family": one_margin_rejection,
        "oracle_edge_rejection_power_by_family": oracle_rejection,
        "max_false_invalid_at_zero": max_false_invalid,
        "max_false_qualified_at_2x_margin": max_false_qualified,
        "min_rejection_power_at_1x_margin": min_power,
        "targets_met": bool(
            max_false_invalid
            <= POWER_TARGETS["max_false_invalid_rate_at_zero_edge"]
            and max_false_qualified
            <= POWER_TARGETS["max_false_qualified_rate_at_2x_margin"]
            and min_power
            >= POWER_TARGETS["min_rejection_power_at_1x_margin"]),
    }
    # 32-cluster 充分性证据(决策依据:除 1xmargin 拒绝功效外,还看
    # 零优势样本获得 QUALIFIED 的成功率——固定预注册 seeds 不允许
    # 重选,单次实现落在失败区间即永久 INSUFFICIENT)
    n32_one = next(
        (s for s in scenarios
         if s["scenario"] == "always_long_one_margin_n32"), None)
    n32_note = None
    if n32_one is not None:
        n32_rejection = 1.0 - n32_one["rates"]["QUALIFIED"]
        n32_zero = next(
            (s for s in scenarios
             if s["scenario"] == "always_long_zero_edge_n32"
             and s["family"] == fams[0]), None)
        n32_zero_qualified = (n32_zero["rates"]["QUALIFIED"]
                              if n32_zero else None)
        n32_ok = bool(
            n32_rejection >= 0.80
            and (n32_zero_qualified is None or n32_zero_qualified >= 0.95))
        n32_note = {
            "n": 32,
            "one_margin_rejection_power": n32_rejection,
            "zero_edge_qualified_rate": n32_zero_qualified,
            "meets_targets_with_margin": n32_ok,
            "decision": (
                "32 cluster 达标且零优势 QUALIFIED 率 >=95% -> 可用 32"
                if n32_ok else
                "32 cluster 未同时满足拒绝功效与零优势可得率 -> "
                "采用 64(留余量;固定预注册 seeds 不允许重选)"),
        }
    return {
        "format": POWER_ANALYSIS_FORMAT,
        "margin": float(margin),
        "power_targets": dict(POWER_TARGETS),
        "min_qualification_clusters": MIN_QUALIFICATION_CLUSTERS,
        "mc_iters": MC_ITERS,
        "mc_seed": MC_SEED,
        "scenarios": scenarios,
        "oracle_scenarios_skipped": oracle_skipped,
        "targets": targets,
        "n32_sufficiency": n32_note,
        "code_hash": power_analysis_code_hash(),
    }


def power_analysis_report_hash(report: dict[str, Any]) -> str:
    return "npa-" + hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def power_analysis_code_hash() -> str:
    """功效分析代码哈希(进入 sealed commitment;实现变化即失效)。"""
    src = Path(inspect.getsourcefile(run_power_analysis))  # type: ignore[arg-type]
    return "npac-" + hashlib.sha256(src.read_bytes()).hexdigest()
