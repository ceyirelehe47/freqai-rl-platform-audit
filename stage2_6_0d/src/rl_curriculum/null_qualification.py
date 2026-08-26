"""阶段 2.6.0b 工作包 H + 2.6.0c 工作包 D + 2.6.0d 完整语义:严格 Null
家族资格审查(family-level)、三态结论、cluster 统计单位与经济等价。

阶段 2.6.0d(按完整任务书)的资格语义——

三态结论(A1):
- QUALIFIED:结构、经济等价、统计功效与实际 pack 全部成立;
- INVALID_NULL:发现可交易漂移、Oracle/规则优势、结构性预测关系
  或其他明确反证;
- INSUFFICIENT_EVIDENCE:样本数或统计功效不足,不能证明等价;
  不得进入正式考试,不得被自动转换为 PASS。

统计单位(A2):每 seed 一个 cluster(派生 seed = seed + 1000*k 的
K 个关联 Episode 按 per-seed-mean-episode-v1 聚合),bootstrap 的
抽样单位是 cluster 值列表;报告记录原始 Episode 数/cluster 数/
distinct seed 数/聚合规则/bootstrap 实际 n。

非优越性检验(A3):对四个差值——Oracle/RuleTrend/AlwaysLong/
HighTurnover 相对 AlwaysFlat——分别要求:

    中心统计量 <= margin 且 单侧置信上界(97.5%) <= margin

其中 AlwaysLong/Oracle/RuleTrend 的 margin 来自 Null Qualification
Spec(= 一次完整往返摩擦),HighTurnover 的容差为 0(扣费后无非正
优势)。"CI 不显著大于零"不再构成任何 PASS 依据;反证
(INVALID_NULL)定义为某个差值的置信下界超过对应容差(可交易优势
被证明)。

margin 来源(A4):只来自 null_qualification_spec(按 EvalConfig
精确计算 1-(1-fee)^2*(1-slippage)^2 = 0.001999);生成器参数通道
(null_qual_max_net_drift_per_bar)已删除;旧 per-bar 容差
(0.0008 x 96 bar = 7.68% 累计)与 bar 级 bootstrap(n=288 假样本)
全部废除;episode 累计漂移降级为纯诊断字段(不参与判定——经济
语义统一由策略差值承载)。

统计功效(A5):MIN_QUALIFICATION_CLUSTERS=64(功效分析实证 32 在
1xmargin 拒绝功效上不足,见 null_power_analysis);报告引用
qualification spec hash 与 power analysis hash(由承诺链对账)。
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
from rl_curriculum.null_qualification_spec import (
    BOOTSTRAP_UNIT,
    CLUSTER_AGGREGATION,
    EPISODES_PER_SEED,
    MIN_PACK_CLUSTERS_PER_FAMILY,
    MIN_QUALIFICATION_CLUSTERS,
    build_spec_payload,
    null_qualification_spec_hash,
    qualification_seeds,
    verify_spec_payload,
)
from rl_curriculum.observation_schema import ObservationSchema

NULL_QUALIFICATION_FORMAT = "null-qualification-v3"
#: 已弃用格式(v1 文档声明式 / v2 布尔 + bar 级统计)不得被新执行器接受
_DEPRECATED_NULL_FORMATS: tuple[str, ...] = (
    "null-qualification-v1",
    "null-qualification-v2",
)
#: 资格报告的五项必需 checks(键集合精确;A3 语义)
REQUIRED_NULL_CHECKS: tuple[str, ...] = (
    "oracle_no_tradable_edge",
    "rule_no_tradable_edge",
    "always_flat_strong_baseline",
    "high_frequency_loses_after_fees",
    "multi_seed_coverage",
)
#: 三态结论的合法取值(pass 仅作 ==QUALIFIED 的别名保留在报告内)
NULL_VERDICTS: tuple[str, ...] = (
    "QUALIFIED",
    "INVALID_NULL",
    "INSUFFICIENT_EVIDENCE",
)
#: HighTurnover 的非正容差(扣费后上置信界 <= 0)
HIGH_TURNOVER_TOLERANCE = 0.0

#: 报告 payload 的精确键集合(缺失/未识别关键字段均拒绝)
NULL_REPORT_REQUIRED_KEYS: frozenset[str] = frozenset({
    "format", "level", "family", "family_version", "timeframe",
    "episode_duration_hours", "seeds", "episodes_per_seed",
    "n_episodes_tested", "n_clusters", "distinct_seeds",
    "cluster_aggregation", "bootstrap_unit", "seeds_namespace_conform",
    "generator_implementation_hash", "generator_manifest_hash",
    "observation_schema_hash", "qualification_code_hash",
    "qualification_spec_hash", "power_analysis_ref",
    "eval_config_manifest", "margin", "statistical_protocol",
    "oracle", "rule_trend", "always_long_vs_flat",
    "high_turnover_vs_flat", "episode_net_drift",
    "always_flat_median", "always_long_median",
    "high_turnover_median", "checks", "reasons", "verdict", "pass",
})
#: binding 的精确键集合(bool-only 旧结构自动拒绝)
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


def _evaluate_check(
    cluster_values: list[float], margin: float,
) -> tuple[dict[str, float], bool, bool]:
    """单侧非优越性检验(A3):中心 <= margin 且 CI 上界 <= margin。

    返回 (bootstrap 块, 检查通过, 反证成立)。反证 = 置信下界 >
    margin(该策略的可交易优势被证明)。
    """
    boot = paired_bootstrap_ci(cluster_values, stat="mean")
    center = float(np.mean(cluster_values))
    passed = bool(center <= margin and boot["ci_high"] <= margin)
    disproven = bool(boot["ci_low"] > margin)
    return boot, passed, disproven


def qualify_null_family(
    generator: BaseMarketGenerator,
    *,
    params: dict[str, Any],
    timeframe: str,
    seeds: list[int],
    cfg: EvalConfig,
    schema: ObservationSchema,
    episodes_per_seed: int = EPISODES_PER_SEED,
    power_analysis_ref: str | None = None,
) -> dict[str, Any]:
    """对单个 Null 家族执行 family-level 资格审查并给出三态结论。

    统计单位:每个 seed 构成一个 cluster;K = episodes_per_seed 个
    关联 Episode(派生 seed = seed + 1000*k)在 cluster 内取算术
    平均;bootstrap 的抽样单位是 cluster 值列表。

    经济 margin 来自按 cfg/episode_bars 构建的 qualification spec
    (任务书 A4:margin 只来自规范,不来自生成器参数)。

    返回报告 payload(键集合 == NULL_REPORT_REQUIRED_KEYS);
    verdict == "QUALIFIED" 才具备进入正式考试的 family-level 资格。
    """
    from rl_curriculum.policies import (
        AlwaysFlatPolicy,
        AlwaysLongPolicy,
        HighTurnoverPolicy,
        RuleTrendPolicy,
    )

    if episodes_per_seed < 1:
        raise NullQualificationError("episodes_per_seed 必须 >= 1")
    episode_bars = int(params.get("episode_bars", 96))
    spec_payload = build_spec_payload(
        cfg, timeframe=timeframe, episode_bars=episode_bars)
    margin = float(spec_payload["margin"])

    oracle = _oracle_for(generator.family)
    rule = RuleTrendPolicy()
    flat = AlwaysFlatPolicy()
    long_ = AlwaysLongPolicy()
    hft = HighTurnoverPolicy()

    # ---- 逐 seed(cluster)聚合:同一 seed 的关联 Episode 不是独立
    #      样本;family-level 资格使用原始(非镜像)派生 Episode——
    #      antithetic 镜像会精确抵消任何确定性漂移,若用于资格判定
    #      将掩盖真漂移伪 Null;结构平衡只应用于 pack 层(任务书 B3)
    n_episodes = 0
    oracle_clusters: list[float] = []
    rule_clusters: list[float] = []
    long_flat_clusters: list[float] = []
    hft_clusters: list[float] = []
    drift_clusters: list[float] = []   # 诊断(不参与判定)
    flat_nets: list[float] = []
    long_nets: list[float] = []
    hft_nets: list[float] = []

    def _accumulate(ep) -> None:
        nonlocal n_episodes
        f_net = run_policy_episode(flat, ep, cfg, schema).net_return
        o_vals.append(
            run_policy_episode(oracle, ep, cfg, schema).net_return - f_net)
        r_vals.append(
            run_policy_episode(rule, ep, cfg, schema).net_return - f_net)
        l_net = run_policy_episode(long_, ep, cfg, schema).net_return
        lf_vals.append(l_net - f_net)
        h_vals.append(
            run_policy_episode(hft, ep, cfg, schema).net_return - f_net)
        log_close = np.log(ep.df["close"].to_numpy(dtype=np.float64))
        d_vals.append(float(
            log_close[-1] - np.log(ep.df["open"].iloc[0])))
        flat_nets.append(f_net)
        long_nets.append(l_net)
        hft_nets.append(f_net + h_vals[-1])
        n_episodes += 1

    for seed in seeds:
        o_vals, r_vals, lf_vals, h_vals, d_vals = [], [], [], [], []
        for j in range(episodes_per_seed):
            _accumulate(generator.generate(
                dict(params), int(seed) + 1000 * j, split="null_control",
                timeframe=timeframe))
        oracle_clusters.append(float(np.mean(o_vals)))
        rule_clusters.append(float(np.mean(r_vals)))
        long_flat_clusters.append(float(np.mean(lf_vals)))
        hft_clusters.append(float(np.mean(h_vals)))
        drift_clusters.append(float(np.mean(d_vals)))

    n_clusters = len(long_flat_clusters)
    oracle_boot, oracle_ok, oracle_disproof = _evaluate_check(
        oracle_clusters, margin)
    rule_boot, rule_ok, rule_disproof = _evaluate_check(
        rule_clusters, margin)
    lf_boot, lf_ok, lf_disproof = _evaluate_check(
        long_flat_clusters, margin)
    hft_boot, hft_ok, hft_disproof = _evaluate_check(
        hft_clusters, HIGH_TURNOVER_TOLERANCE)
    drift_boot = paired_bootstrap_ci(drift_clusters, stat="mean")

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    # 1-3. 三个无条件/信息策略差值的单侧非优越性检验(A3)
    for name, ok, disproof, boot, cv, m in (
        ("oracle_no_tradable_edge", oracle_ok, oracle_disproof,
         oracle_boot, oracle_clusters, margin),
        ("rule_no_tradable_edge", rule_ok, rule_disproof,
         rule_boot, rule_clusters, margin),
        ("always_flat_strong_baseline", lf_ok, lf_disproof,
         lf_boot, long_flat_clusters, margin),
    ):
        checks[name] = ok
        if not ok:
            reasons.append(
                f"{name}:中心 {float(np.mean(cv)):+.5f} / CI 上界 "
                f"{boot['ci_high']:+.5f} 未压进 margin {m:.6f}"
                f"(未能证明无可交易优势)")
    # 4. HighTurnover 扣费后无非正优势(容差 0)
    checks["high_frequency_loses_after_fees"] = hft_ok
    if not hft_ok:
        reasons.append(
            f"HighTurnover 相对 Flat:中心 {float(np.mean(hft_clusters)):+.5f}"
            f" / CI 上界 {hft_boot['ci_high']:+.5f} 未压进非正容差 0"
            f"(费用合同未证明有效)")
    # 5. 统计功效门槛(独立 cluster 数)
    checks["multi_seed_coverage"] = bool(
        n_clusters >= MIN_QUALIFICATION_CLUSTERS)
    if not checks["multi_seed_coverage"]:
        reasons.append(
            f"独立 cluster 数不足({n_clusters} < "
            f"{MIN_QUALIFICATION_CLUSTERS}:统计功效不足以证明经济等价,"
            f"INSUFFICIENT_EVIDENCE 不得进入正式考试)")

    # ---- 三态裁决(预注册;反证优先)
    if oracle_disproof or rule_disproof or lf_disproof or hft_disproof:
        verdict = "INVALID_NULL"
        detail = []
        for name, disproven, boot, m in (
            ("Oracle", oracle_disproof, oracle_boot, margin),
            ("RuleTrend", rule_disproof, rule_boot, margin),
            ("AlwaysLong", lf_disproof, lf_boot, margin),
            ("HighTurnover", hft_disproof, hft_boot,
             HIGH_TURNOVER_TOLERANCE),
        ):
            if disproven:
                detail.append(
                    f"{name} 可交易优势被证明(CI 下界 "
                    f"{boot['ci_low']:+.5f} > 容差 {m:.6f})")
        reasons.append("经济反证: " + "; ".join(detail))
    elif all(checks.values()):
        verdict = "QUALIFIED"
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
    if verdict == "INVALID_NULL":
        reasons.insert(
            0, "三态结论 INVALID_NULL:Null 存在明确反证,该族被拒绝")

    from rl_curriculum.generator_binding import generator_bindings

    gen_binding = generator_bindings({generator.family: generator})[
        generator.family]
    expected_seeds = qualification_seeds(n_clusters) if n_clusters else []
    evidence = {
        "format": NULL_QUALIFICATION_FORMAT,
        "level": "family",
        "family": generator.family,
        "family_version": generator.family_version,
        "timeframe": timeframe,
        "episode_duration_hours": spec_payload[
            "episode_duration_hours"],
        "seeds": [int(s) for s in seeds],
        "episodes_per_seed": int(episodes_per_seed),
        "n_episodes_tested": n_episodes,
        "n_clusters": n_clusters,
        "distinct_seeds": n_clusters,
        "cluster_aggregation": CLUSTER_AGGREGATION,
        "bootstrap_unit": BOOTSTRAP_UNIT,
        "seeds_namespace_conform": seeds == expected_seeds,
        "generator_implementation_hash": gen_binding["implementation_hash"],
        "generator_manifest_hash": gen_binding["manifest_hash"],
        "observation_schema_hash": schema.schema_hash(),
        "qualification_code_hash": qualification_code_hash(),
        "qualification_spec_hash": null_qualification_spec_hash(
            spec_payload),
        "power_analysis_ref": power_analysis_ref,
        "eval_config_manifest": cfg.manifest(),
        "margin": {
            "value": margin,
            "derivation": spec_payload["margin_derivation"],
        },
        "statistical_protocol": dict(
            spec_payload["statistical_protocol"]),
        "oracle": {
            "cluster_values": oracle_clusters,
            "mean": float(np.mean(oracle_clusters)),
            "bootstrap": oracle_boot,
        },
        "rule_trend": {
            "cluster_values": rule_clusters,
            "mean": float(np.mean(rule_clusters)),
            "bootstrap": rule_boot,
        },
        "always_long_vs_flat": {
            "cluster_values": long_flat_clusters,
            "mean": float(np.mean(long_flat_clusters)),
            "bootstrap": lf_boot,
        },
        "high_turnover_vs_flat": {
            "cluster_values": hft_clusters,
            "mean": float(np.mean(hft_clusters)),
            "bootstrap": hft_boot,
        },
        "episode_net_drift": {
            "cluster_values": drift_clusters,
            "mean": float(np.mean(drift_clusters)),
            "bootstrap": drift_boot,
        },
        "always_flat_median": float(np.median(flat_nets)),
        "always_long_median": float(np.median(long_nets)),
        "high_turnover_median": float(np.median(hft_nets)),
        "checks": checks,
        "reasons": reasons,
        "verdict": verdict,
        "pass": verdict == "QUALIFIED",
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
    """逐族资格绑定(进入 sealed commitment)。

    {family: {family_version, qualification_pass, report_hash,
    report_payload}}——完整 canonical 报告 payload 进入承诺哈希;
    不存在"只写 qualification_pass=true"的占位通道。
    """
    bindings: dict[str, dict[str, Any]] = {}
    for family, report in sorted(reports_by_family.items()):
        payload = dict(report)
        keys = set(payload)
        if keys != set(NULL_REPORT_REQUIRED_KEYS):
            raise NullQualificationError(
                f"Null 资格报告 {family!r} 键集合与 v3 要求不一致:"
                f"缺失 {sorted(set(NULL_REPORT_REQUIRED_KEYS) - keys)},"
                f"未识别 {sorted(keys - set(NULL_REPORT_REQUIRED_KEYS))}")
        if payload.get("verdict") not in NULL_VERDICTS:
            raise NullQualificationError(
                f"Null 资格报告 {family!r} 的 verdict "
                f"{payload.get('verdict')!r} 不是合法三态结论")
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
    qualification_spec_hash: str | None = None,
    power_analysis_ref: str | None = None,
) -> dict[str, Any]:
    """验证承诺中的 Null 资格绑定(v3 完整语义:重读真实报告并逐项对账)。

    对每个 required 族(除 2.6.0c 的全材料对账外,新增):
    - 报告 qualification_spec_hash 必须与承诺的 spec hash 一致
      (margin/统计协议/聚合规则/功效目标全部经 spec 哈希绑定);
    - power_analysis_ref 必须与承诺的 power analysis hash 一致;
    - seeds 必须等于 spec namespace 推导序列(防资格 seed 挑选),
      且独立 cluster 数 >= MIN_QUALIFICATION_CLUSTERS;
    - 四个差值块的 bootstrap n == distinct clusters(统计单位对账);
    - margin 与当前 spec 重算值一致(margin 只能来自规范);
    - verdict 必须为 QUALIFIED(INSUFFICIENT/INVALID 均拒绝)。

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
                f"Null 族 {family!r} 的资格绑定不是 v3 结构(必须为 "
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
        fmt = payload.get("format")
        if fmt != NULL_QUALIFICATION_FORMAT:
            if fmt in _DEPRECATED_NULL_FORMATS:
                report_problems.append(
                    f"报告格式 {fmt!r} 已弃用(bar 级统计单位/布尔-only "
                    f"语义不得使用;必须重新以 "
                    f"{NULL_QUALIFICATION_FORMAT!r} 生成)")
            else:
                report_problems.append(
                    f"报告格式 {fmt!r} != {NULL_QUALIFICATION_FORMAT!r}"
                    f"(未知格式报告不得使用)")
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
        # ---- spec / power 对账(A3/A4/A5)
        if qualification_spec_hash is not None:
            if payload.get("qualification_spec_hash") != (
                    qualification_spec_hash):
                report_problems.append(
                    "报告 qualification spec hash 与承诺不一致"
                    "(margin/统计协议/聚合规则/功效目标已被改写)")
        elif not str(payload.get("qualification_spec_hash") or "").startswith(
                "nqs-"):
            report_problems.append("报告缺少 qualification spec hash")
        if power_analysis_ref is not None:
            if payload.get("power_analysis_ref") != power_analysis_ref:
                report_problems.append(
                    "报告 power_analysis_ref 与承诺的 power analysis "
                    "不一致(功效分析未绑定或被替换)")
        elif not str(payload.get("power_analysis_ref") or "").startswith(
                "npa-"):
            report_problems.append("报告缺少 power analysis 引用")
        # ---- 统计单位对账(bootstrap 单位 = seed cluster)
        seeds = payload.get("seeds") or []
        distinct = len(set(int(s) for s in seeds))
        n_clusters = payload.get("n_clusters")
        if not isinstance(n_clusters, int) or n_clusters != distinct:
            report_problems.append(
                f"报告 n_clusters({n_clusters!r})与 seeds 去重数"
                f"({distinct})不一致(bootstrap 单位必须是 seed cluster)")
        if payload.get("distinct_seeds") != distinct:
            report_problems.append(
                "报告 distinct_seeds 与 seeds 去重数不一致(自相矛盾)")
        if distinct < MIN_QUALIFICATION_CLUSTERS:
            report_problems.append(
                f"独立 cluster 数不足(去重 {distinct} < "
                f"{MIN_QUALIFICATION_CLUSTERS}:统计功效不足以证明"
                f"经济等价,INSUFFICIENT_EVIDENCE 不得进入正式考试)")
        if payload.get("seeds_namespace_conform") is not True:
            report_problems.append(
                "报告 seeds 不符合资格 namespace 推导序列"
                "(资格 seed 不得挑选)")
        elif distinct >= 1 and [int(s) for s in seeds] != (
                qualification_seeds(distinct)):
            # 重算对账(不信任自声明标志):资格 seed 必须严格等于
            # namespace 推导序列,防止挑选 seeds 后伪造 conform 标志
            report_problems.append(
                "报告 seeds 与资格 namespace 推导序列重算不一致"
                "(资格 seed 不得挑选;自声明 conform 标志不可信)")
        if payload.get("cluster_aggregation") != CLUSTER_AGGREGATION:
            report_problems.append(
                f"cluster 聚合规则 {payload.get('cluster_aggregation')!r}"
                f" != 预注册 {CLUSTER_AGGREGATION!r}")
        if payload.get("bootstrap_unit") != BOOTSTRAP_UNIT:
            report_problems.append(
                f"bootstrap 单位 {payload.get('bootstrap_unit')!r} != "
                f"预注册 {BOOTSTRAP_UNIT!r}(bar 级 bootstrap 已被禁止)")
        for block_name in ("oracle", "rule_trend", "always_long_vs_flat",
                           "high_turnover_vs_flat", "episode_net_drift"):
            block = payload.get(block_name) or {}
            boot = block.get("bootstrap") or block.get("excess_bootstrap") \
                or {}
            cv = block.get("cluster_values")
            if boot.get("n") != distinct or not isinstance(cv, list) \
                    or len(cv) != distinct:
                report_problems.append(
                    f"报告 {block_name} 的 bootstrap n"
                    f"({boot.get('n')!r})/cluster 数"
                    f"({len(cv) if isinstance(cv, list) else None})"
                    f"与独立 cluster 数({distinct})不一致")
        # ---- margin 只能来自规范(A4)
        margin_block = payload.get("margin") or {}
        margin_value = margin_block.get("value") if isinstance(
            margin_block, dict) else None
        if margin_block.get("derivation", {}).get("formula") != \
                "1 - (1 - fee)^2 * (1 - slippage)^2":
            report_problems.append(
                "报告 margin 推导公式与规范不一致(margin 只能来自"
                "qualification spec)")
        # ---- 三态结论对账
        verdict = payload.get("verdict")
        if verdict not in NULL_VERDICTS:
            report_problems.append(
                f"报告 verdict {verdict!r} 不是合法三态结论"
                f"({list(NULL_VERDICTS)})")
        elif verdict != "QUALIFIED":
            report_problems.append(
                f"报告三态结论为 {verdict}(只有 QUALIFIED 才能进入"
                f"正式考试;INSUFFICIENT_EVIDENCE 不得被自动转换为"
                f"PASS,INVALID_NULL 为明确反证)")
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
        if bool(payload.get("pass")) != (
                payload.get("verdict") == "QUALIFIED"):
            report_problems.append(
                "报告 pass 与三态 verdict 不一致(pass 必须等于"
                "(verdict == QUALIFIED))")
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
