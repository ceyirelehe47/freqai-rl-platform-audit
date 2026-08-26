"""阶段 2.6.0b 工作包 H + 阶段 2.6.0c 工作包 D + 阶段 2.6.0d:严格 Null
家族资格审查、真实资格报告绑定与统计/经济等价闭环。

2.6.0a 的问题:Null 家族只靠"文档声明"进入正式最小集合;若某构造
仍保留可预测方向(如块内趋势、Fourier 相位残存自相关),模型的
Null 考试成绩会被错误解释为作弊或挂科,而真正的原因是 Null 本身
无效。

阶段 2.6.0c 工作包 D(null-qualification-v2):报告 payload 嵌入全部
对账材料(族实现指纹/Observation Schema hash/EvalConfig manifest/
timeframe/qualification 参数/资格审查代码哈希),binding 携带完整
canonical report payload,正式验证重读 binding 内 payload 逐项对账。

阶段 2.6.0d(null-qualification-v3)修复 2.6.0c 独立审查发现的集中
阻塞——资格判定采用了错误的统计单位、过宽的漂移容差,并把"没有
显著发现正收益"错误解释为"已证明不存在经济上可交易的优势":

1. 显式三态结论(QUALIFIED / INVALID_NULL / INSUFFICIENT_EVIDENCE):
   - QUALIFIED:结构、经济等价、统计功效全部成立;
   - INVALID_NULL:发现可交易漂移、Oracle/规则优势、结构性预测
     关系或其他明确反证;
   - INSUFFICIENT_EVIDENCE:样本数或统计功效不足,不能证明等价;
     不得进入正式考试,不得被自动转换为 PASS。
2. 独立统计单位是 seed/Episode cluster:每个 seed 先聚合其全部
   关联 Episode(K 个派生 seed 的 episode 在 cluster 内取均值,
   规则 per-seed-mean-episode-v1),bootstrap 的抽样单位是 cluster
   而非单根 bar(Null 刻意保留波动聚集,bar 不是独立统计单位)。
   报告记录原始 Episode 数、cluster 数、distinct seed 数、cluster
   聚合规则与 bootstrap 实际 n(断言 bootstrap n == distinct
   independent clusters)。
3. 经济等价(代替旧"bar 级平均漂移 CI 落在 ±0.0008/bar"):
   - always_flat_strong_baseline 检查真正比较 Always Long 与
     Always Flat——每 cluster 配对净差(含费,经济直接量)的
     bootstrap CI 上界 <= max_unconditional_long_edge(单侧 TOST:
     证明无可交易的无条件多头优势;2.6.0c 反例 stochvol 3-seed
     Always Long 中位 +2.40% 仍 PASS 的根因是旧检查根本不做该
     比较);
   - episode_net_drift_nonexploitable:每 episode 累计 log drift
     按 cluster 聚合后,CI 上界 <= +max_tradable_drift(正漂移
     才可被 Long/Flat 现货模型利用)且 CI 下界 >= -max_negative_drift
     (负漂移不可利用,仅在巨大到构成结构性非中心证据时拒绝;
     不对称带是预注册的经济语义,不是为通过校准);
   - 旧 per-bar 容差 0.0008 x 96 bar = 7.68% 累计漂移容差废除;
     新带以每 episode 累计量直接定义。
4. 统计功效门槛:MIN_QUALIFICATION_CLUSTERS(预注册 64)。
   3 个 cluster 的资格样本(2.6.0c 现状)必须不再 QUALIFIED——
   功效推导:每 episode Always Long 净收益 std 约 3%(实测),
   K=8 episode/seed 的 cluster std 约 1.1%,n=64 时 bootstrap
   CI 半宽约 0.27%,配合中心噪声覆盖 0.005 带的单侧 TOST
   (探测脚本实测三族 CI 上界 +0.08%/-0.13%/-0.15% 全部带内)。

三态裁决规则(预注册,反证优先):
- INVALID_NULL:Oracle/规则稳定正超额、HFT 扣费不亏,或
  多头优势 CI 下界 > max_unconditional_long_edge(可交易优势
  被证明),或 drift CI 下界 > +max_tradable_drift / CI 上界
  < -max_negative_drift(结构性非中心被证明);
- QUALIFIED:六项 checks 全真;
- INSUFFICIENT_EVIDENCE:其余一切(cluster 不足或带未证明,
  既未证明等价也未发现反证)。
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

NULL_QUALIFICATION_FORMAT = "null-qualification-v3"
#: 已弃用格式(v1 文档声明式 / v2 布尔 + bar 级统计)不得被新执行器接受
_DEPRECATED_NULL_FORMATS: tuple[str, ...] = (
    "null-qualification-v1",
    "null-qualification-v2",
)
#: 资格报告的六项必需 checks(键集合精确;阶段 2.6.0d)
REQUIRED_NULL_CHECKS: tuple[str, ...] = (
    "oracle_no_stable_directional_edge",
    "rule_no_stable_excess",
    "always_flat_strong_baseline",
    "episode_net_drift_nonexploitable",
    "high_frequency_loses_after_fees",
    "multi_seed_coverage",
)
#: 三态结论的合法取值(阶段 2.6.0d;单一布尔 pass 被三态取代,
#: pass 仅作 ==QUALIFIED 的兼容别名保留在报告内)
NULL_VERDICTS: tuple[str, ...] = (
    "QUALIFIED",
    "INVALID_NULL",
    "INSUFFICIENT_EVIDENCE",
)
#: 资格审查要求的最小独立 cluster 数(统计功效门槛,预注册 64)
MIN_QUALIFICATION_CLUSTERS = 64
#: 每 seed 默认生成的关联 Episode 数(cluster 内均值;预注册 8)
DEFAULT_EPISODES_PER_SEED = 8
#: 无条件多头优势的可忽略带上界(每 episode 含费净差;预注册 0.5%)
MAX_UNCONDITIONAL_LONG_EDGE = 0.005
#: 可交易正漂移带(每 episode 累计 log drift 上界;预注册 0.5%)
MAX_TRADABLE_DRIFT = 0.005
#: 负漂移诊断带(Long/Flat 现货下负漂移不可利用,仅结构性非中心
#: 证据;预注册 1.0%)
MAX_NEGATIVE_DRIFT = 0.010
#: cluster 聚合规则名(seed 内关联 Episode 取算术平均)
CLUSTER_AGGREGATION = "per-seed-mean-episode-v1"
#: bootstrap 抽样单位(任务书 A2:bar 不是独立统计单位)
BOOTSTRAP_UNIT = "seed-cluster"
#: 资格报告 payload 的精确键集合(缺失/未识别关键字段均拒绝)
NULL_REPORT_REQUIRED_KEYS: frozenset[str] = frozenset({
    "format", "family", "family_version", "timeframe", "seeds",
    "episodes_per_seed", "n_episodes_tested", "n_clusters",
    "distinct_seeds", "cluster_aggregation", "bootstrap_unit",
    "generator_implementation_hash", "generator_manifest_hash",
    "observation_schema_hash", "qualification_code_hash",
    "eval_config_manifest", "qualification_params",
    "oracle", "rule_trend", "always_long_vs_flat",
    "episode_net_drift", "always_flat_median", "always_long_median",
    "high_turnover_median", "checks", "reasons", "verdict", "pass",
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
    episodes_per_seed: int = DEFAULT_EPISODES_PER_SEED,
) -> dict[str, Any]:
    """对单个 Null 家族执行六项资格审查并给出三态结论。

    统计单位(阶段 2.6.0d):每个 seed 构成一个 cluster;该 seed 的
    K = episodes_per_seed 个关联 Episode(派生 seed = seed + 1000*k)
    先在 cluster 内按算术平均聚合(CLUSTER_AGGREGATION),bootstrap
    的抽样单位是 cluster 值列表(长度 == distinct seeds)。

    返回报告 payload(键集合 == NULL_REPORT_REQUIRED_KEYS);
    verdict == "QUALIFIED" 才具备进入正式考试的资格。
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

    # ---- 逐 seed(cluster)聚合:同一 seed 的关联 Episode 不是独立样本
    n_episodes = 0
    oracle_clusters: list[float] = []   # cluster 级 Oracle-Flat 配对差
    rule_clusters: list[float] = []     # cluster 级 RuleTrend-Flat 配对差
    long_flat_clusters: list[float] = []  # cluster 级 AlwaysLong-Flat 净差
    drift_clusters: list[float] = []    # cluster 级累计 log drift
    flat_nets: list[float] = []         # 诊断:episode 级
    long_nets: list[float] = []         # 诊断:episode 级
    hft_nets: list[float] = []          # HFT 检查:episode 级中位
    for seed in seeds:
        o_vals, r_vals, lf_vals, d_vals = [], [], [], []
        for k in range(episodes_per_seed):
            ep = generator.generate(
                dict(params), int(seed) + 1000 * k, split="null_control",
                timeframe=timeframe)
            o_net = run_policy_episode(oracle, ep, cfg, schema).net_return
            r_net = run_policy_episode(rule, ep, cfg, schema).net_return
            f_net = run_policy_episode(flat, ep, cfg, schema).net_return
            l_net = run_policy_episode(long_, ep, cfg, schema).net_return
            hft_nets.append(
                run_policy_episode(hft, ep, cfg, schema).net_return)
            o_vals.append(o_net - f_net)
            r_vals.append(r_net - f_net)
            lf_vals.append(l_net - f_net)
            log_close = np.log(ep.df["close"].to_numpy(dtype=np.float64))
            d_vals.append(float(
                log_close[-1] - np.log(ep.df["open"].iloc[0])))
            flat_nets.append(f_net)
            long_nets.append(l_net)
            n_episodes += 1
        oracle_clusters.append(float(np.mean(o_vals)))
        rule_clusters.append(float(np.mean(r_vals)))
        long_flat_clusters.append(float(np.mean(lf_vals)))
        drift_clusters.append(float(np.mean(d_vals)))

    n_clusters = len(long_flat_clusters)
    # bootstrap 抽样单位 == cluster(报告内每个 bootstrap 块的 n 都
    # 必须等于 n_clusters;由 verify 层与测试层双重断言)
    oracle_boot = paired_bootstrap_ci(oracle_clusters)
    rule_boot = paired_bootstrap_ci(rule_clusters)
    lf_boot = paired_bootstrap_ci(long_flat_clusters, stat="mean")
    drift_boot = paired_bootstrap_ci(drift_clusters, stat="mean")

    checks: dict[str, bool] = {}
    reasons: list[str] = []
    # 1. Oracle 无稳定方向优势(cluster 级)
    def _stable_positive(boot: dict[str, float],
                         values: list[float]) -> bool:
        return bool(
            boot["n"] > 0
            and float(np.median(values)) > 1e-9
            and boot["ci_low"] > 0.0
        )

    checks["oracle_no_stable_directional_edge"] = not _stable_positive(
        oracle_boot, oracle_clusters)
    if not checks["oracle_no_stable_directional_edge"]:
        reasons.append(
            f"Oracle 在 Null 上保留稳定正超额(cluster 级 median="
            f"{np.median(oracle_clusters):+.5f}, CI low="
            f"{oracle_boot['ci_low']:+.5f}):方向可预测性未切断")
    # 2. 可观察规则无稳定超额(cluster 级)
    checks["rule_no_stable_excess"] = not _stable_positive(
        rule_boot, rule_clusters)
    if not checks["rule_no_stable_excess"]:
        reasons.append(
            f"RuleTrend 在 Null 上保留稳定正超额(cluster 级 median="
            f"{np.median(rule_clusters):+.5f}):历史方向信息未切断")
    # 3. Always Flat 是强基线(经济等价,单侧 TOST):无条件多头优势的
    #    cluster 级 bootstrap CI 上界不超过可忽略带。旧检查(v2)只做
    #    bar 级平均漂移 CI 且从不比较 Always Long vs Always Flat,
    #    导致 stochvol 3-seed 样本 Always Long 中位 +2.40% 仍 PASS。
    checks["always_flat_strong_baseline"] = bool(
        lf_boot["ci_high"] <= MAX_UNCONDITIONAL_LONG_EDGE)
    if not checks["always_flat_strong_baseline"]:
        reasons.append(
            f"无条件多头优势(Always Long - Flat,cluster 级)CI 上界 "
            f"{lf_boot['ci_high']:+.5f} 超过可忽略带 "
            f"+{MAX_UNCONDITIONAL_LONG_EDGE:.4f}:未能证明不存在"
            f"可交易的无条件多头优势")
    # 4. Episode 净漂移不可利用(不对称带):正漂移可被 Long/Flat 现货
    #    模型利用(做多跑赢 Flat),负漂移不可利用(最多保持 Flat 得 0)
    #    ——正侧收紧,负侧仅以结构性非中心证据拒绝。旧 per-bar 容差
    #    0.0008 x 96 bar = 7.68% 累计漂移容差废除。
    checks["episode_net_drift_nonexploitable"] = bool(
        drift_boot["ci_high"] <= MAX_TRADABLE_DRIFT
        and drift_boot["ci_low"] >= -MAX_NEGATIVE_DRIFT)
    if not checks["episode_net_drift_nonexploitable"]:
        reasons.append(
            f"每 episode 累计 log drift(cluster 级)CI "
            f"[{drift_boot['ci_low']:+.5f}, {drift_boot['ci_high']:+.5f}] "
            f"超出不对称带 [+{MAX_TRADABLE_DRIFT:.4f}(可利用正漂移), "
            f"-{MAX_NEGATIVE_DRIFT:.4f}(负侧仅结构性非中心才拒绝)]")
    # 5. 高频策略扣费亏损(episode 级诊断,费用合同有效性)
    checks["high_frequency_loses_after_fees"] = bool(
        float(np.median(hft_nets)) < 0.0)
    if not checks["high_frequency_loses_after_fees"]:
        reasons.append(
            f"HighTurnover 中位净收益 {np.median(hft_nets):+.5f} >= 0:"
            f"费用合同未在高换手下产生亏损(环境异常)")
    # 6. 统计功效门槛:独立 cluster 数(每个 seed 一个 cluster;同 seed
    #    多个关联 Episode 聚合后不增加 cluster 数)
    checks["multi_seed_coverage"] = bool(
        n_clusters >= MIN_QUALIFICATION_CLUSTERS)
    if not checks["multi_seed_coverage"]:
        reasons.append(
            f"独立 cluster 数不足({n_clusters} < "
            f"{MIN_QUALIFICATION_CLUSTERS}):统计功效不足以证明经济"
            f"等价(INSUFFICIENT_EVIDENCE,不得进入正式考试)")

    # ---- 三态裁决(预注册;反证优先)
    economic_disproof = bool(
        lf_boot["ci_low"] > MAX_UNCONDITIONAL_LONG_EDGE
        or drift_boot["ci_low"] > MAX_TRADABLE_DRIFT
        or drift_boot["ci_high"] < -MAX_NEGATIVE_DRIFT)
    if economic_disproof:
        detail = []
        if lf_boot["ci_low"] > MAX_UNCONDITIONAL_LONG_EDGE:
            detail.append(
                f"可交易无条件多头优势被证明(cluster CI 下界 "
                f"{lf_boot['ci_low']:+.5f} > +"
                f"{MAX_UNCONDITIONAL_LONG_EDGE:.4f})")
        if drift_boot["ci_low"] > MAX_TRADABLE_DRIFT:
            detail.append(
                f"可交易正漂移被证明(drift CI 下界 "
                f"{drift_boot['ci_low']:+.5f} > +"
                f"{MAX_TRADABLE_DRIFT:.4f})")
        if drift_boot["ci_high"] < -MAX_NEGATIVE_DRIFT:
            detail.append(
                f"结构性负漂移被证明(drift CI 上界 "
                f"{drift_boot['ci_high']:+.5f} < -"
                f"{MAX_NEGATIVE_DRIFT:.4f})")
        reasons.append("经济反证: " + "; ".join(detail))
    structural_fail = not (
        checks["oracle_no_stable_directional_edge"]
        and checks["rule_no_stable_excess"]
        and checks["high_frequency_loses_after_fees"])
    if structural_fail or economic_disproof:
        verdict = "INVALID_NULL"
    elif all(checks.values()):
        verdict = "QUALIFIED"
    else:
        verdict = "INSUFFICIENT_EVIDENCE"
    if verdict == "INVALID_NULL":
        reasons.insert(
            0, "三态结论 INVALID_NULL:Null 存在明确反证,该族被拒绝")

    # 工作包 D(2.6.0c):嵌入全部对账材料(报告 hash 因此绑定实现/
    # 参数/schema/fee/timeframe/seed——任一材料变化,旧报告即失效)
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
        "n_episodes_tested": n_episodes,
        "n_clusters": n_clusters,
        "distinct_seeds": n_clusters,
        "cluster_aggregation": CLUSTER_AGGREGATION,
        "bootstrap_unit": BOOTSTRAP_UNIT,
        "generator_implementation_hash": gen_binding["implementation_hash"],
        "generator_manifest_hash": gen_binding["manifest_hash"],
        "observation_schema_hash": schema.schema_hash(),
        "qualification_code_hash": qualification_code_hash(),
        "eval_config_manifest": cfg.manifest(),
        "qualification_params": {
            "episodes_per_seed": int(episodes_per_seed),
            "min_qualification_clusters": MIN_QUALIFICATION_CLUSTERS,
            "max_unconditional_long_edge": MAX_UNCONDITIONAL_LONG_EDGE,
            "max_tradable_drift": MAX_TRADABLE_DRIFT,
            "max_negative_drift": MAX_NEGATIVE_DRIFT,
            "cluster_aggregation": CLUSTER_AGGREGATION,
        },
        "oracle": {
            "cluster_values": oracle_clusters,
            "excess_median": float(np.median(oracle_clusters)),
            "excess_bootstrap": oracle_boot,
        },
        "rule_trend": {
            "cluster_values": rule_clusters,
            "excess_median": float(np.median(rule_clusters)),
            "excess_bootstrap": rule_boot,
        },
        "always_long_vs_flat": {
            "cluster_values": long_flat_clusters,
            "excess_median": float(np.median(long_flat_clusters)),
            "excess_bootstrap": lf_boot,
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
    """逐族资格绑定(进入 sealed commitment;v3)。

    {family: {family_version, qualification_pass, report_hash,
    report_payload}}——完整 canonical 报告 payload 进入承诺哈希;
    不存在"只写 qualification_pass=true"的占位通道(D1)。
    binding 构建接受任何三态结论的报告(如实记录);非 QUALIFIED
    报告在 verify_null_qualification_bindings 层被拒绝进入考试。
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
) -> dict[str, Any]:
    """验证承诺中的 Null 资格绑定(v3:重读真实报告并逐项对账)。

    对每个 required 族:
    - binding 必须存在且键集合精确(缺 report_hash/report_payload 的
      bool-only 旧结构直接拒绝);
    - report_payload 键集合精确等于 v3 要求(缺失/未识别字段拒绝);
    - 报告格式必须是 null-qualification-v3(v1/v2 旧格式报告——
      包括 bar 级统计与布尔-only 语义——不得被新执行器接受);
    - 重算 qualification_report_hash(payload) == binding.report_hash
      (报告内容被承诺哈希绑定);
    - family / family_version 与 binding 键及当前 generator binding
      对账;generator implementation/manifest hash 与当前密封生成器
      绑定对账(Null 实现改变 = 旧报告失效);
    - qualification_code_hash 与当前资格审查代码哈希一致;
    - Observation Schema hash / EvalConfig manifest(含 fee)/
      timeframe 与本次考试对账;
    - 统计单位对账:n_clusters == distinct_seeds == seeds 去重数 ==
      各 bootstrap 块的 n(cluster 单位;bootstrap n == distinct
      independent clusters);
    - verdict 必须是合法三态且为 QUALIFIED(INSUFFICIENT_EVIDENCE
      与 INVALID_NULL 均不得进入正式考试,不得被自动转换为 PASS);
      checks 六项全真且与 verdict/pass 自洽;
    - pass 为真且与 binding.qualification_pass 一致。

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
        # ---- 统计单位对账(阶段 2.6.0d):bootstrap 单位必须是
        #      seed cluster,n == distinct independent clusters
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
        if n_clusters != distinct or distinct < MIN_QUALIFICATION_CLUSTERS:
            report_problems.append(
                f"独立 cluster 数不足(去重 {distinct} < "
                f"{MIN_QUALIFICATION_CLUSTERS}:统计功效不足以证明"
                f"经济等价,INSUFFICIENT_EVIDENCE 不得进入正式考试)")
        if payload.get("cluster_aggregation") != CLUSTER_AGGREGATION:
            report_problems.append(
                f"cluster 聚合规则 {payload.get('cluster_aggregation')!r}"
                f" != 预注册 {CLUSTER_AGGREGATION!r}")
        if payload.get("bootstrap_unit") != BOOTSTRAP_UNIT:
            report_problems.append(
                f"bootstrap 单位 {payload.get('bootstrap_unit')!r} != "
                f"预注册 {BOOTSTRAP_UNIT!r}(bar 级 bootstrap 已被禁止)")
        for block_name, block in (
            ("oracle", payload.get("oracle") or {}),
            ("rule_trend", payload.get("rule_trend") or {}),
            ("always_long_vs_flat", payload.get("always_long_vs_flat")
             or {}),
        ):
            boot = block.get("excess_bootstrap") or {}
            cv = block.get("cluster_values")
            if boot.get("n") != distinct or not isinstance(cv, list) \
                    or len(cv) != distinct:
                report_problems.append(
                    f"报告 {block_name} 的 bootstrap n"
                    f"({boot.get('n')!r})/cluster 数({len(cv) if isinstance(cv, list) else None})"
                    f"与独立 cluster 数({distinct})不一致"
                    f"(bootstrap n 必须等于 distinct independent clusters)")
        drift_block = payload.get("episode_net_drift") or {}
        dboot = drift_block.get("bootstrap") or {}
        dcv = drift_block.get("cluster_values")
        if dboot.get("n") != distinct or not isinstance(dcv, list) \
                or len(dcv) != distinct:
            report_problems.append(
                f"报告 episode_net_drift 的 bootstrap n"
                f"({dboot.get('n')!r})/cluster 数"
                f"({len(dcv) if isinstance(dcv, list) else None})"
                f"与独立 cluster 数({distinct})不一致")
        qp = payload.get("qualification_params") or {}
        expected_params = {
            "episodes_per_seed": payload.get("episodes_per_seed"),
            "min_qualification_clusters": MIN_QUALIFICATION_CLUSTERS,
            "max_unconditional_long_edge": MAX_UNCONDITIONAL_LONG_EDGE,
            "max_tradable_drift": MAX_TRADABLE_DRIFT,
            "max_negative_drift": MAX_NEGATIVE_DRIFT,
            "cluster_aggregation": CLUSTER_AGGREGATION,
        }
        if qp != expected_params:
            report_problems.append(
                f"报告 qualification_params {qp!r} 与预注册参数"
                f"{expected_params!r} 不一致")
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
