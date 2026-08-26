"""阶段 2.6.0d 工作包 A3/A4/A5:Null Qualification Spec(独立资格规范)。

经济 margin 的唯一来源(阶段 2.6.0d 硬要求):

- 旧实现(2.6.0c 及更早)的 `null_qual_max_net_drift_per_bar` 生成器
  参数通道已删除——被审查的生成器不得自行提供资格门槛;
- margin 由本 Spec 按 EvalConfig 精确计算:

      round_trip_friction = 1 - (1 - fee)^2 * (1 - slippage)^2

  即一次完整往返(开仓 + 平仓)的乘法交易摩擦,不写死常数。当前
  fee=0.001、slippage=0 时 friction = 0.001999(不是硬编码的 0.002);
- 任务书硬上限:任一无条件策略相对 Flat 的允许正优势不得大于该
  Episode 在当前 EvalConfig 下的一次完整往返摩擦——本 Spec 取
  margin = round_trip_friction(允许上限本身;更紧 margin 会把
  TOST 功效需求推向数百 cluster,而摩擦上限已足以排除全部已知
  反例:stochvol 3-seed +2.40% / sign +0.75% / 7.68% 每日漂移区
  间,经济解释见 margin_derivation)。

统计协议(考试前冻结,进入 spec 哈希):

- 方法:cluster 级 percentile bootstrap 单侧上置信界(TOST 风格
  非优越性检验)——对 Oracle / ObservableRule / AlwaysLong 相对
  AlwaysFlat 的差值,以及 HighTurnover 相对 Flat 的差值;
- 资格要求(每个差值):中心统计量 <= margin 且单侧置信上界
  (97.5%)<= margin;HighTurnover 的容差为 0(扣费后无非正优势);
  不使用 p-value,不使用"CI 是否包含零";
- 置信水平 / bootstrap 迭代 / 随机种子直接引用 evaluator 的冻结
  常量(单一来源,禁止漂移)。

独立统计单位与 seed namespace(A2/A5/B1):

- 每 seed 构成一个 cluster(K 个关联 Episode 在 cluster 内按
  per-seed-mean-episode-v1 聚合),bootstrap 抽样单位是 cluster;
- family-level 资格 seeds 与 pack 构造 seeds 使用独立推导
  namespace(与训练 seed / dev seed / hidden exam seed 天然隔离,
  防止资格 seed 挑选);verify 层强制 seeds 必须等于 namespace
  推导序列。

统计功效门槛(A5):

- MIN_QUALIFICATION_CLUSTERS = 64:功效分析(确定性 Monte Carlo)
  实证 32 cluster 在 1xmargin 拒绝功效上贴线不达标(约 79% <
  80%),64 cluster 全部目标达标(见 null_power_analysis);
- 不得因执行时间缩小 seed/cluster 数。

margin 按 Episode 真实时间定义(A4):spec payload 记录
episode_duration_hours(由 episode_bars x timeframe 计算),
margin 语义绑定该时长(当前 96 x 15m = 24h);不使用每 bar 固定
阈值。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from rl_curriculum.evaluator import (
    EvalConfig,
    BOOTSTRAP_DEFAULT_ITERS,
    BOOTSTRAP_SEED,
)

SPEC_FORMAT = "null-qualification-spec-v1"

#: 统计协议(冻结;bootstrap 常量单一来源 = evaluator,禁止漂移)
STATISTICAL_PROTOCOL: dict[str, Any] = {
    "method": "cluster-percentile-bootstrap-upper-bound",
    "test_style": "non-inferiority-tost-single-sided",
    "confidence_level": 0.95,
    "bootstrap_iters": int(BOOTSTRAP_DEFAULT_ITERS),
    "bootstrap_seed": int(BOOTSTRAP_SEED),
    "bootstrap_stat": "mean",
    "decision_rule": (
        "每个差值要求中心统计量 <= margin 且单侧置信上界"
        "(97.5%)<= margin;HighTurnover 容差为 0;不使用 p-value"
        "或 CI 包含零"),
}
#: 参与比较的策略(进入 spec 哈希;A4)
COMPARISON_STRATEGIES: tuple[str, ...] = (
    "oracle", "observable_rule", "always_long", "high_turnover",
)

#: cluster 聚合规则(预注册;bootstrap 单位 = seed cluster)
CLUSTER_AGGREGATION = "per-seed-mean-episode-v1"
BOOTSTRAP_UNIT = "seed-cluster"

#: 结构平衡(任务书 B3):antithetic pairing 仅用于 **pack 层**——同一
#: seed/随机流的基准路径收益逐位取负(绝对收益与波动状态路径不变),
#: pair 内镜像使实际 pack 的无条件多头优势与累计漂移精确抵消。
#: 注意:antithetic 镜像同样会抵消任何确定性漂移,因此 family-level
#: 资格判定必须使用原始(非镜像)样本——结构平衡不进入资格统计。
#: pair 标志只在生成器 params,不进入 observation;pair 顺序由构建
#: namespace 随机化
ANTITHETIC_PAIRING: dict[str, Any] = {
    "enabled": True,
    "scope": "pack-level only",
    "mirror_relation": "returns_negated_bitwise",
    "preserves": "absolute returns, volatility-state path, length, timeframe",
    "pair_cluster": "同 base seed 的 (orig, flip) 两 Episode 聚合为"
                    "一个 pack cluster,只算一个独立样本",
    "family_qualification_uses_raw_episodes": (
        "family-level 资格使用原始派生 Episode(方差保留)——镜像"
        "会掩盖真漂移伪 Null,不得进入资格判定"),
    "no_endpoint_constraint": (
        "镜像在生成层施加,不在单个 Episode 内全局 demean/终点约束"
        "(无 Brownian bridge 类位置泄漏)"),
}

#: 每族 family-level 资格的独立 cluster 数(功效分析实证 32 不足,
#: 64 达标;不得因执行时间缩小)
MIN_QUALIFICATION_CLUSTERS = 64
#: 每 seed 关联 Episode 数(cluster 内均值;原始派生 Episode,
#: 无镜像——方差保留是资格判定的前提)
EPISODES_PER_SEED = 16
#: 实际 pack 内每族 null Episode 的最小独立 cluster 数(B2)
MIN_PACK_CLUSTERS_PER_FAMILY = 32

#: 功效目标(A5;进入 spec 哈希,power analysis 必须逐项达成)
POWER_TARGETS: dict[str, float] = {
    "max_false_invalid_rate_at_zero_edge": 0.05,
    "max_false_qualified_rate_at_2x_margin": 0.05,
    "min_rejection_power_at_1x_margin": 0.80,
}

#: seed namespace(独立 salt;与训练/dev/hidden/pack 种子隔离)
FAMILY_QUALIFICATION_SEED_SALT = "null-qualification-family-seeds-v1"
PACK_CONSTRUCTION_SEED_SALT = "null-pack-construction-seeds-v1"
#: pack 内 pair 顺序随机化的稳定推导 salt(镜像关系不可由固定顺序识别)
PACK_ORDER_SALT = "null-pack-pair-order-v1"


def pack_order_seed(family: str, attempt: int) -> int:
    """pair 顺序随机化的确定性种子(sha256 推导,跨进程稳定)。"""
    digest = hashlib.sha256(
        f"{PACK_ORDER_SALT}|{family}|{attempt}".encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16)


def qualification_seeds(n: int) -> list[int]:
    """family-level 资格 seeds 的确定性 namespace 推导。

    推导自独立 salt(与 pack 构造 namespace、训练 seed、dev seed、
    mock pack 内种子全部隔离;百万段与项目既有小数字种子天然不相交)。
    派生冲突检查:任意两 base seed 之差不得为 1000 的(小)倍数,
    否则派生 seed(seed + 1000*j)会跨 cluster 相撞。
    """
    out: list[int] = []
    for i in range(n):
        digest = hashlib.sha256(
            f"{FAMILY_QUALIFICATION_SEED_SALT}|{i}".encode("utf-8")
        ).hexdigest()
        out.append(1_000_000 + int(digest[:8], 16) % 1_000_000)
    assert len(set(out)) == n, "namespace 推导发生碰撞(不应发生)"
    for a in range(n):
        for b in range(a + 1, n):
            diff = abs(out[a] - out[b])
            if diff != 0 and diff <= 7000 and diff % 1000 == 0:
                raise ValueError(
                    f"资格 namespace seeds 存在派生冲突({out[a]} 与 "
                    f"{out[b]} 相差 {diff}):请更换 namespace salt")
    return out


def pack_construction_seeds(family: str, attempt: int, n: int) -> list[int]:
    """pack 构造 seeds 的确定性 namespace 推导(按族 + attempt)。"""
    out: list[int] = []
    for i in range(n):
        digest = hashlib.sha256(
            f"{PACK_CONSTRUCTION_SEED_SALT}|{family}|{attempt}|{i}".encode(
                "utf-8")
        ).hexdigest()
        out.append(1_000_000 + int(digest[:8], 16) % 1_000_000)
    return out


def round_trip_friction(cfg: EvalConfig) -> float:
    """一次完整往返(开仓 + 平仓)的乘法交易摩擦(按 EvalConfig 精确
    计算,不写死常数;当前 fee=0.001/slippage=0 -> 0.001999)。"""
    slip = float(getattr(cfg, "slippage_bps", 0.0)) / 1e4
    return 1.0 - (1.0 - float(cfg.fee)) ** 2 * (1.0 - slip) ** 2


def episode_duration_hours(episode_bars: int, timeframe: str) -> float:
    """Episode 真实时长(小时;A4:margin 按真实时间定义)。"""
    minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60,
               "4h": 240, "1d": 1440}
    if timeframe not in minutes:
        raise ValueError(f"未知 timeframe {timeframe!r}")
    return episode_bars * minutes[timeframe] / 60.0


def build_spec_payload(
    cfg: EvalConfig, *, timeframe: str, episode_bars: int,
) -> dict[str, Any]:
    """构造资格规范 payload(进入 spec 哈希;绑定 EvalConfig 全部
    经济参数 / Episode 真实时长 / 统计协议 / 比较策略 / 聚合方式 /
    功效目标 / seed namespace)。"""
    margin = round_trip_friction(cfg)
    return {
        "format": SPEC_FORMAT,
        "margin": margin,
        "margin_derivation": {
            "formula": "1 - (1 - fee)^2 * (1 - slippage)^2",
            "fee": float(cfg.fee),
            "slippage_bps": float(getattr(cfg, "slippage_bps", 0.0)),
            "price_tick": float(getattr(cfg, "price_tick", 0.0)),
            "semantics": (
                "一次完整往返的乘法交易摩擦;无条件策略相对 Flat 的"
                "允许正优势上限(经济解释:无信息交易者的套利屏障——"
                "优势低于该摩擦时任何单次往返都无法稳定获利)"),
            "hard_cap_satisfied": True,
        },
        "statistical_protocol": dict(STATISTICAL_PROTOCOL),
        "comparison_strategies": list(COMPARISON_STRATEGIES),
        "cluster_aggregation": CLUSTER_AGGREGATION,
        "bootstrap_unit": BOOTSTRAP_UNIT,
        "antithetic_pairing": dict(ANTITHETIC_PAIRING),
        "episodes_per_seed": EPISODES_PER_SEED,
        "min_qualification_clusters": MIN_QUALIFICATION_CLUSTERS,
        "min_pack_clusters_per_family": MIN_PACK_CLUSTERS_PER_FAMILY,
        "power_targets": dict(POWER_TARGETS),
        "seed_namespaces": {
            "family_qualification": FAMILY_QUALIFICATION_SEED_SALT,
            "pack_construction": PACK_CONSTRUCTION_SEED_SALT,
        },
        "eval_config_manifest": cfg.manifest(),
        "timeframe": timeframe,
        "episode_duration_hours": episode_duration_hours(
            int(episode_bars), timeframe),
    }


def null_qualification_spec_hash(payload: dict[str, Any]) -> str:
    """规范哈希(进入 sealed commitment;改变任一内容使旧承诺失效)。"""
    return "nqs-" + hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def verify_spec_payload(payload: dict[str, Any]) -> list[str]:
    """规范 payload 的自洽校验(margin 与 EvalConfig 重算一致等)。"""
    problems: list[str] = []
    if payload.get("format") != SPEC_FORMAT:
        problems.append(f"spec format {payload.get('format')!r} != "
                        f"{SPEC_FORMAT!r}")
    der = payload.get("margin_derivation") or {}
    cfg = EvalConfig(
        fee=float(der.get("fee", -1)),
        slippage_bps=float(der.get("slippage_bps", 0.0)),
        price_tick=float(der.get("price_tick", 0.0)),
    )
    recomputed = round_trip_friction(cfg)
    if abs(float(payload.get("margin", -1)) - recomputed) > 1e-12:
        problems.append(
            f"spec margin {payload.get('margin')!r} 与 EvalConfig 重算"
            f"值 {recomputed:.6f} 不一致(margin 只能来自规范计算)")
    if float(payload.get("margin", 1.0)) > recomputed + 1e-12:
        problems.append("spec margin 超过一次完整往返摩擦硬上限")
    proto = payload.get("statistical_protocol") or {}
    if proto.get("confidence_level") != STATISTICAL_PROTOCOL[
            "confidence_level"]:
        problems.append("置信水平与冻结统计协议不一致")
    if proto.get("bootstrap_iters") != BOOTSTRAP_DEFAULT_ITERS:
        problems.append("bootstrap 迭代数与冻结值不一致")
    if proto.get("bootstrap_seed") != BOOTSTRAP_SEED:
        problems.append("bootstrap 随机种子与冻结值不一致")
    if payload.get("cluster_aggregation") != CLUSTER_AGGREGATION:
        problems.append("cluster 聚合规则与预注册值不一致")
    if payload.get("bootstrap_unit") != BOOTSTRAP_UNIT:
        problems.append("bootstrap 单位与预注册值不一致")
    if int(payload.get("min_qualification_clusters", 0)) < 32:
        problems.append("family-level 独立 cluster 数低于最小 32")
    if int(payload.get("min_pack_clusters_per_family", 0)) < 32:
        problems.append("pack-level 每族独立 cluster 数低于最小 32")
    return problems
