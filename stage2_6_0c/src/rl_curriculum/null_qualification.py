"""阶段 2.6.0b 工作包 H + 阶段 2.6.0c 工作包 D:严格 Null 家族资格审查
与真实资格报告绑定。

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

阶段 2.6.0c 工作包 D(null-qualification-v2):
- 报告 payload 嵌入全部对账材料:族实现指纹(generator
  implementation/manifest hash)、Observation Schema hash、
  EvalConfig manifest(含 fee)、timeframe、qualification 参数、
  资格审查代码哈希——修改任一材料 = 旧报告 hash 失效;
- binding 携带完整 canonical report payload(承诺哈希覆盖报告
  全部内容),不再接受只有 qualification_pass=true 的布尔占位;
- 正式验证重读 binding 内 payload:重算报告 hash、逐项对账
  (family/version/实现/schema/fee/参数/seed/checks/pass),
  任一不符 -> EXAM_INVALID。
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

NULL_QUALIFICATION_FORMAT = "null-qualification-v2"
#: 资格报告的五项必需 checks(键集合精确;D2)
REQUIRED_NULL_CHECKS: tuple[str, ...] = (
    "oracle_no_stable_directional_edge",
    "rule_no_stable_excess",
    "always_flat_strong_baseline",
    "high_frequency_loses_after_fees",
    "multi_seed_coverage",
)
#: 资格审查要求的最小不同 seed 数(multi_seed_coverage 门槛;D2)
MIN_QUALIFICATION_SEEDS = 3
#: 资格报告 payload 的精确键集合(缺失/未识别关键字段均拒绝;D2)
NULL_REPORT_REQUIRED_KEYS: frozenset[str] = frozenset({
    "format", "family", "family_version", "timeframe", "seeds",
    "episodes_per_seed", "n_episodes_tested", "distinct_seeds",
    "generator_implementation_hash", "generator_manifest_hash",
    "observation_schema_hash", "qualification_code_hash",
    "eval_config_manifest", "qualification_params",
    "oracle", "rule_trend", "always_flat_median",
    "always_long_median", "net_drift_per_bar_bootstrap",
    "max_net_drift_per_bar", "high_turnover_median",
    "checks", "reasons", "pass",
})
#: binding 的精确键集合(bool-only 旧结构自动拒绝;D1/D2)
NULL_BINDING_KEYS: frozenset[str] = frozenset({
    "family_version", "qualification_pass", "report_hash",
    "report_payload",
})


class NullQualificationError(RuntimeError):
    """Null 资格审查执行失败/绑定无效(基础设施错误,fail closed)。"""


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
    checks["multi_seed_coverage"] = bool(
        len(set(seeds)) >= MIN_QUALIFICATION_SEEDS)
    if not checks["multi_seed_coverage"]:
        reasons.append(
            f"seed 覆盖不足(>= {MIN_QUALIFICATION_SEEDS} 个不同 seed "
            f"才构成资格审查,实际 {len(set(seeds))})")

    # 工作包 D:嵌入全部对账材料(报告 hash 因此绑定实现/参数/schema/
    # fee/timeframe/seed——任一材料变化,旧报告即失效)
    from rl_curriculum.generator_binding import generator_bindings

    gen_binding = generator_bindings({generator.family: generator})[
        generator.family]
    evidence = {
        "format": NULL_QUALIFICATION_FORMAT,
        "family": generator.family,
        "family_version": generator.family_version,
        "timeframe": timeframe,
        "seeds": [int(s) for s in seeds],
        "episodes_per_seed": int(episodes_per_seed),
        "n_episodes_tested": len(oracle_nets),
        "distinct_seeds": len(set(seeds)),
        "generator_implementation_hash": gen_binding["implementation_hash"],
        "generator_manifest_hash": gen_binding["manifest_hash"],
        "observation_schema_hash": schema.schema_hash(),
        "qualification_code_hash": qualification_code_hash(),
        "eval_config_manifest": cfg.manifest(),
        "qualification_params": {
            "episodes_per_seed": int(episodes_per_seed),
            "max_net_drift_per_bar": max_net_drift_per_bar,
            "min_distinct_qualification_seeds": MIN_QUALIFICATION_SEEDS,
        },
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
    """逐族资格绑定(进入 sealed commitment;工作包 D v2)。

    {family: {family_version, qualification_pass, report_hash,
    report_payload}}——完整 canonical 报告 payload 进入承诺哈希;
    不存在"只写 qualification_pass=true"的占位通道(D1)。
    """
    bindings: dict[str, dict[str, Any]] = {}
    for family, report in sorted(reports_by_family.items()):
        payload = dict(report)
        keys = set(payload)
        if keys != set(NULL_REPORT_REQUIRED_KEYS):
            raise NullQualificationError(
                f"Null 资格报告 {family!r} 键集合与 v2 要求不一致:"
                f"缺失 {sorted(set(NULL_REPORT_REQUIRED_KEYS) - keys)},"
                f"未识别 {sorted(keys - set(NULL_REPORT_REQUIRED_KEYS))}")
        bindings[family] = {
            "family_version": payload["family_version"],
            "qualification_pass": bool(payload["pass"]),
            "report_hash": qualification_report_hash(payload),
            "report_payload": payload,
        }
    return bindings


def verify_null_qualification_bindings(
    expected: dict[str, dict[str, Any]],
    *,
    required_families: list[str],
    generator_bindings: dict[str, dict[str, str]],
    observation_schema_hash: str,
    eval_config_manifest: dict[str, Any],
    timeframe: str,
) -> dict[str, Any]:
    """验证承诺中的 Null 资格绑定(D2:重读真实报告并逐项对账)。

    对每个 required 族:
    - binding 必须存在且键集合精确(缺 report_hash/report_payload 的
      bool-only 旧结构直接拒绝);
    - report_payload 键集合精确等于 v2 要求(缺失/未识别字段拒绝);
    - 重算 qualification_report_hash(payload) == binding.report_hash
      (报告内容被承诺哈希绑定);
    - family / family_version 与 binding 键及当前 generator binding
      对账;generator implementation/manifest hash 与当前密封生成器
      绑定对账(Null 实现改变 = 旧报告失效,D3);
    - qualification_code_hash 与当前资格审查代码哈希一致(代码改变
      = 旧报告失效,D3);
    - Observation Schema hash / EvalConfig manifest(含 fee)/
      timeframe 与本次考试对账;
    - seeds 去重数 >= MIN_QUALIFICATION_SEEDS 且与 distinct_seeds
      字段一致;
    - checks 键集合精确等于五项必需 checks 且全为真;pass 为真且
      与 binding.qualification_pass 一致。

    任一不符 -> problems(EXAM_INVALID)。
    """
    problems: list[str] = []
    checks: dict[str, bool] = {}
    current_code_hash = qualification_code_hash()
    for family in required_families:
        bound = expected.get(family)
        if not isinstance(bound, dict):
            checks[f"null_qualification_bound::{family}"] = False
            problems.append(f"承诺未绑定 Null 族 {family!r} 的资格审查")
            continue
        if set(bound) != set(NULL_BINDING_KEYS):
            checks[f"null_qualification_bound::{family}"] = False
            problems.append(
                f"Null 族 {family!r} 的资格绑定不是 v2 结构(必须为 "
                f"{sorted(NULL_BINDING_KEYS)};bool-only 绑定已被禁止)")
            continue
        checks[f"null_qualification_bound::{family}"] = True
        payload = bound.get("report_payload")
        if not isinstance(payload, dict):
            checks[f"null_qualification_report::{family}"] = False
            problems.append(
                f"Null 族 {family!r} 的绑定缺少真实报告 payload"
                f"(bool-only qualification 绑定不得进入正式考试)")
            continue
        keys = set(payload)
        if keys != set(NULL_REPORT_REQUIRED_KEYS):
            checks[f"null_qualification_report::{family}"] = False
            problems.append(
                f"Null 族 {family!r} 资格报告键集合不符:"
                f"缺失 {sorted(set(NULL_REPORT_REQUIRED_KEYS) - keys)},"
                f"未识别 {sorted(keys - set(NULL_REPORT_REQUIRED_KEYS))}")
            continue
        recomputed = qualification_report_hash(payload)
        if recomputed != bound.get("report_hash"):
            checks[f"null_qualification_report::{family}"] = False
            problems.append(
                f"Null 族 {family!r} 资格报告 hash 与绑定记录不一致"
                f"(报告被篡改或未随材料重新生成)")
            continue
        gb = generator_bindings.get(family) or {}
        report_problems: list[str] = []
        if payload.get("format") != NULL_QUALIFICATION_FORMAT:
            report_problems.append(
                f"报告格式 {payload.get('format')!r} != "
                f"{NULL_QUALIFICATION_FORMAT!r}(旧格式报告不得使用)")
        if payload.get("family") != family:
            report_problems.append("报告 family 与绑定键不一致")
        if payload.get("family_version") != bound.get("family_version"):
            report_problems.append("报告 family_version 与绑定不一致")
        if (gb and payload.get("family_version")
                != gb.get("family_version")):
            report_problems.append(
                "报告 family_version 与当前生成器绑定不一致")
        if (gb and payload.get("generator_implementation_hash")
                != gb.get("implementation_hash")):
            report_problems.append(
                "Null 实现已改变但报告未重新生成"
                "(generator implementation hash 不一致)")
        if (gb and payload.get("generator_manifest_hash")
                != gb.get("manifest_hash")):
            report_problems.append(
                "Null 生成器 manifest hash 与当前绑定不一致")
        if payload.get("qualification_code_hash") != current_code_hash:
            report_problems.append(
                "资格审查代码已改变但报告未重新生成"
                "(qualification code hash 不一致)")
        if payload.get("observation_schema_hash") != observation_schema_hash:
            report_problems.append(
                "报告 Observation Schema hash 与本次考试不一致")
        if payload.get("eval_config_manifest") != eval_config_manifest:
            report_problems.append(
                "报告 EvalConfig(含 fee)与本次考试不一致")
        if payload.get("timeframe") != timeframe:
            report_problems.append("报告 timeframe 与本次考试不一致")
        seeds = payload.get("seeds") or []
        if len(set(int(s) for s in seeds)) < MIN_QUALIFICATION_SEEDS:
            report_problems.append(
                f"报告 seed 数不足(去重 {len(set(int(s) for s in seeds))}"
                f" < {MIN_QUALIFICATION_SEEDS})")
        if payload.get("distinct_seeds") != len(
                set(int(s) for s in seeds)):
            report_problems.append(
                "报告 distinct_seeds 与 seeds 去重数不一致(自相矛盾)")
        rep_checks = payload.get("checks") or {}
        if set(rep_checks) != set(REQUIRED_NULL_CHECKS):
            report_problems.append(
                f"报告 checks 键集合不符(必须为 "
                f"{list(REQUIRED_NULL_CHECKS)};缺失或多余均拒绝)")
        elif not all(bool(v) for v in rep_checks.values()):
            failed = [k for k, v in rep_checks.items() if not v]
            report_problems.append(f"报告存在未通过的检查: {failed}")
        if payload.get("pass") is not True:
            report_problems.append("报告最终 pass 不为真")
        if bool(payload.get("pass")) != bool(
                bound.get("qualification_pass")):
            report_problems.append(
                "binding.qualification_pass 与报告 pass 不一致")
        ok = not report_problems
        checks[f"null_qualification_report::{family}"] = ok
        if not ok:
            problems.append(
                f"Null 族 {family!r} 资格报告对账失败: "
                + "; ".join(report_problems))
    return {"checks": checks, "problems": problems, "pass": not problems}
