"""阶段 2.6.0b 工作包 H:严格 Null 家族资格审查(H3/H4)。

2.6.0a 的问题:Null 家族只靠"文档声明"进入正式最小集合;若某构造
仍保留可预测方向(如块内趋势、Fourier 相位残存自相关),模型的
Null 考试成绩会被错误解释为作弊或挂科,而真正的原因是 Null 本身
无效。

资格审查(每个严格 Null 家族进入 sealed exam 前必须通过):

1. Oracle 没有稳定方向优势(读隐藏状态也无法盈利);
2. 可观察规则基线没有稳定超额(RuleTrend vs Always Flat);
3. Always Flat 是强基线(Always Long 中位不优于 Always Flat);
4. 高频策略扣费亏损(HighTurnover 中位净收益 < 0);
5. 多 seed bootstrap 不支持任何稳定正超额。

任何一条不成立 -> INVALID_NULL(该族被拒绝,不得进入正式硬门;
不得把模型判作弊)。资格审查报告哈希 + Null 实现哈希 + 本模块代码
哈希进入 sealed commitment(H4):没有资格证明的 Null 不得进入
正式考试;修改 Null 实现 = 资格证明失效。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.evaluator import (
    EvalConfig,
    paired_bootstrap_ci,
    run_policy_episode,
)
from rl_curriculum.generator_api import BaseMarketGenerator
from rl_curriculum.observation_schema import ObservationSchema

NULL_QUALIFICATION_FORMAT = "null-qualification-v1"


class NullQualificationError(RuntimeError):
    """Null 资格审查执行失败(基础设施错误,fail closed)。"""


def _oracle_for(family: str):
    """按族选择 Oracle(探针系隐藏列)。"""
    from rl_curriculum.policies import (
        OracleSegmentedDriftPolicy,
        OracleSmoothLatentDriftPolicy,
    )

    if "latent" in family:
        return OracleSmoothLatentDriftPolicy()
    return OracleSegmentedDriftPolicy()


def qualify_null_family(
    generator: BaseMarketGenerator,
    *,
    params: dict[str, Any],
    timeframe: str,
    seeds: list[int],
    cfg: EvalConfig,
    schema: ObservationSchema,
    episodes_per_seed: int = 1,
) -> dict[str, Any]:
    """对单个 Null 家族执行五项资格审查(H3)。

    返回 {pass, checks, evidence};pass=False 即 INVALID_NULL。
    """
    from rl_curriculum.policies import (
        AlwaysFlatPolicy,
        AlwaysLongPolicy,
        HighTurnoverPolicy,
        RuleTrendPolicy,
    )

    if episodes_per_seed < 1:
        raise NullQualificationError("episodes_per_seed 必须 >= 1")
    oracle = _oracle_for(generator.family)
    rule = RuleTrendPolicy()
    flat = AlwaysFlatPolicy()
    long_ = AlwaysLongPolicy()
    hft = HighTurnoverPolicy()

    oracle_nets, rule_nets, flat_nets, long_nets, hft_nets = \
        [], [], [], [], []
    all_bar_returns: list[float] = []
    for seed in seeds:
        for k in range(episodes_per_seed):
            ep = generator.generate(
                dict(params), int(seed) + 1000 * k, split="null_control",
                timeframe=timeframe)
            oracle_nets.append(
                run_policy_episode(oracle, ep, cfg, schema).net_return)
            rule_nets.append(
                run_policy_episode(rule, ep, cfg, schema).net_return)
            flat_nets.append(
                run_policy_episode(flat, ep, cfg, schema).net_return)
            long_nets.append(
                run_policy_episode(long_, ep, cfg, schema).net_return)
            hft_nets.append(
                run_policy_episode(hft, ep, cfg, schema).net_return)
            log_close = np.log(
                ep.df["close"].to_numpy(dtype=np.float64))
            first_r = float(np.log(ep.df["open"].iloc[0]))
            all_bar_returns.extend(
                np.diff(log_close, prepend=first_r).tolist())

    oracle_excess = [a - b for a, b in zip(oracle_nets, flat_nets)]
    rule_excess = [a - b for a, b in zip(rule_nets, flat_nets)]
    oracle_boot = paired_bootstrap_ci(oracle_excess)
    rule_boot = paired_bootstrap_ci(rule_excess)

    def _stable_positive(boot: dict[str, float], values: list[float]) -> bool:
        return bool(
            boot["n"] > 0
            and float(np.median(values)) > 1e-9
            and boot["ci_low"] > 0.0
        )

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    # 1. Oracle 无稳定方向优势
    checks["oracle_no_stable_directional_edge"] = not _stable_positive(
        oracle_boot, oracle_excess)
    if not checks["oracle_no_stable_directional_edge"]:
        reasons.append(
            f"Oracle 在 Null 上保留稳定正超额(median="
            f"{np.median(oracle_excess):+.5f}, CI low="
            f"{oracle_boot['ci_low']:+.5f}):方向可预测性未切断")
    # 2. 可观察规则无稳定超额
    checks["rule_no_stable_excess"] = not _stable_positive(
        rule_boot, rule_excess)
    if not checks["rule_no_stable_excess"]:
        reasons.append(
            f"RuleTrend 在 Null 上保留稳定正超额(median="
            f"{np.median(rule_excess):+.5f}):历史方向信息未切断")
    # 3. Always Flat 是强基线:净漂移接近零(汇集全部 bar 的每 bar 平均
    #    对数收益 bootstrap CI 落在 ±max_net_drift_per_bar 内)。
    #    说明:策略级 Always Long vs Flat 的每 Episode 比较统计功效不足
    #    (费用差 ~0.2% 对 Episode 波动 ~3%);bar 级汇集检验以 SE ~1bp
    #    区分零漂移(严格 Null 按构造为零)与漂移伪 Null。
    max_net_drift_per_bar = float(
        params.get("null_qual_max_net_drift_per_bar", 8e-4))
    drift_boot = paired_bootstrap_ci(
        all_bar_returns, stat="mean")
    checks["always_flat_strong_baseline"] = bool(
        drift_boot["ci_low"] >= -max_net_drift_per_bar
        and drift_boot["ci_high"] <= max_net_drift_per_bar)
    if not checks["always_flat_strong_baseline"]:
        reasons.append(
            f"每 bar 平均对数收益 bootstrap CI "
            f"[{drift_boot['ci_low']:+.6f}, {drift_boot['ci_high']:+.6f}] "
            f"超出 ±{max_net_drift_per_bar:.6f}:Null 存在系统性净漂移"
            f"(Always Flat 不再是强基线)")
    # 4. 高频策略扣费亏损
    checks["high_frequency_loses_after_fees"] = bool(
        float(np.median(hft_nets)) < 0.0)
    if not checks["high_frequency_loses_after_fees"]:
        reasons.append(
            f"HighTurnover 中位净收益 {np.median(hft_nets):+.5f} >= 0:"
            f"费用合同未在高换手下产生亏损(环境异常)")
    # 5. 多 seed 覆盖(每个 seed 独立重算,样本量真实)
    checks["multi_seed_coverage"] = bool(len(set(seeds)) >= 3)

    evidence = {
        "format": NULL_QUALIFICATION_FORMAT,
        "family": generator.family,
        "family_version": generator.family_version,
        "timeframe": timeframe,
        "seeds": [int(s) for s in seeds],
        "episodes_per_seed": int(episodes_per_seed),
        "n_episodes_tested": len(oracle_nets),
        "distinct_seeds": len(set(seeds)),
        "oracle": {
            "net_returns": oracle_nets,
            "excess_median": float(np.median(oracle_excess)),
            "excess_bootstrap": oracle_boot,
        },
        "rule_trend": {
            "net_returns": rule_nets,
            "excess_median": float(np.median(rule_excess)),
            "excess_bootstrap": rule_boot,
        },
        "always_flat_median": float(np.median(flat_nets)),
        "always_long_median": float(np.median(long_nets)),
        "net_drift_per_bar_bootstrap": drift_boot,
        "max_net_drift_per_bar": max_net_drift_per_bar,
        "high_turnover_median": float(np.median(hft_nets)),
        "checks": checks,
        "reasons": reasons,
        "pass": all(checks.values()),
    }
    if not checks["multi_seed_coverage"]:
        reasons.append("seed 覆盖不足(>= 3 个不同 seed 才构成资格审查)")
    return evidence


def qualification_report_hash(report: dict[str, Any]) -> str:
    return "nq-" + hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def qualification_code_hash() -> str:
    """资格审查代码哈希(进入 sealed commitment;H4)。"""
    src = Path(inspect.getsourcefile(  # type: ignore[arg-type]
        qualify_null_family))
    return "nqc-" + hashlib.sha256(src.read_bytes()).hexdigest()


def build_null_qualification_bindings(
    reports_by_family: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """逐族资格绑定(进入 sealed commitment;H4)。

    {family: {family_version, qualification_pass, report_hash}}。
    """
    bindings: dict[str, dict[str, Any]] = {}
    for family, report in sorted(reports_by_family.items()):
        bindings[family] = {
            "family_version": report["family_version"],
            "qualification_pass": bool(report["pass"]),
            "report_hash": qualification_report_hash(report),
        }
    return bindings


def verify_null_qualification_bindings(
    expected: dict[str, dict[str, Any]],
    *,
    required_families: list[str],
) -> dict[str, Any]:
    """验证承诺中的 Null 资格绑定完整且全部通过(H4)。

    - required_families 中每个族必须有绑定且 qualification_pass=true;
    - 缺绑定/未通过 -> EXAM_INVALID(未通过资格审查的 Null 不得进入
      正式考试)。
    """
    problems: list[str] = []
    checks: dict[str, bool] = {}
    for family in required_families:
        bound = expected.get(family)
        if bound is None:
            checks[f"null_qualification_bound::{family}"] = False
            problems.append(f"承诺未绑定 Null 族 {family!r} 的资格审查")
            continue
        ok = bool(bound.get("qualification_pass"))
        checks[f"null_qualification_pass::{family}"] = ok
        if not ok:
            problems.append(
                f"Null 族 {family!r} 未通过资格审查(INVALID_NULL),"
                f"不得进入正式考试硬门")
    return {"checks": checks, "problems": problems, "pass": not problems}
