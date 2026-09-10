"""Null Qualification Spec v2(阶段 2.6.0e 工作包 A/B)。

经济 margin 的唯一来源(单一实现 = null_friction;阶段 2.6.0e 修复):

- 旧错误公式 ``1 - (1-fee)^2 * (1-slippage)^2``(得 0.001999)与冻结
  账本不一致,已废除——margin 现在精确取自冻结 LongFlatLedger 的真实
  完整往返摩擦:

      friction = 1 - [(1-fee)/(1+fee)] * [(1-slippage)/(1+slippage)]

  fee=0.001、slippage=0 时 = 0.002/1.001 = 0.001998001998...;
- 单位与 EpisodeResult.net_return 相同(simple return);
- 不大于冻结账本真实摩擦(构造上相等;tick>0 时真实摩擦只增,由
  null_friction 的真实执行 parity 网格实证,spec 验证强制其通过);
- 不由生成器参数控制(null_qual_max_net_drift_per_bar 通道保持删除),
  不硬编码常数。

统计协议(冻结,进入 spec 哈希)与 2.6.0d 一致:

- cluster 级 percentile bootstrap 单侧上置信界(TOST 风格非优越性);
- 每 seed 一个 cluster(per-seed-mean-episode-v1 聚合);
- 家族资格 seeds / pack 构造 seeds / pair 顺序使用独立 namespace。

阶段 2.6.0e 新增进入 spec 哈希的冻结项(工作包 B):

- TOLERANCE_BY_BLOCK:四个比较块各自的容差语义
  (AlwaysLong/Oracle/Rule = qualification margin;HighTurnover = 0);
- POWER_SCENARIO_MANIFEST:功效分析预注册场景清单
  (valid_zero_edge / inside_half_tolerance / boundary_diagnostic /
  violation_plus_1x_margin / violation_plus_2x_margin;target 为
  绝对经济优势,注入前经验分布先中心化);
- POWER_MC_CONFIG:Monte Carlo 迭代数/种子与比例置信方法
  (Wilson score 双侧 95% 保守界);
- CLUSTER_CANDIDATE_LADDER:cluster 数预注册候选阶梯
  (32/64/96/128;选择满足全部硬目标的最小值)。

antithetic pairing 继续仅用于 pack 层(family 资格用原始非镜像样本)。
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
from rl_curriculum.null_friction import (
    FRICTION_CONTRACT_FORMAT,
    LEDGER_ROUND_TRIP_FORMULA,
    friction_contract_code_hash,
    friction_parity_problems,
    ledger_round_trip_friction,
)

SPEC_FORMAT = "null-qualification-spec-v2"
#: 已弃用 spec 格式(v1 使用与冻结账本不一致的旧摩擦公式,不得被接受)
_DEPRECATED_SPEC_FORMATS: tuple[str, ...] = (
    "null-qualification-spec-v1",
)

#: 统计协议(冻结;bootstrap 常量单一来源 = evaluator,禁止漂移)
STATISTICAL_PROTOCOL: dict[str, Any] = {
    "method": "cluster-percentile-bootstrap-upper-bound",
    "test_style": "non-inferiority-tost-single-sided",
    "confidence_level": 0.95,
    "bootstrap_iters": int(BOOTSTRAP_DEFAULT_ITERS),
    "bootstrap_seed": int(BOOTSTRAP_SEED),
    "bootstrap_stat": "mean",
    "decision_rule": (
        "每个差值要求中心统计量 <= 容差 且 单侧置信上界(97.5%)<= 容差;"
        "HighTurnover 容差为 0;不使用 p-value 或 CI 包含零"),
}
#: 参与比较的策略(进入 spec 哈希;A4)
COMPARISON_STRATEGIES: tuple[str, ...] = (
    "oracle", "observable_rule", "always_long", "high_turnover",
)

#: 四个比较块的容差语义(阶段 2.6.0e 工作包 B2:功效硬门覆盖全部四块)
#: "qualification_margin" -> 容差 = 本 spec 的 margin;"zero" -> 容差 = 0
TOLERANCE_BY_BLOCK: dict[str, str] = {
    "always_long_vs_flat": "qualification_margin",
    "oracle": "qualification_margin",
    "rule_trend": "qualification_margin",
    "high_turnover_vs_flat": "zero",
}

#: 功效分析预注册场景清单(阶段 2.6.0e 工作包 B2/B4):
#: - valid_zero_edge:target_absolute_edge = 0(真正无优势,不得高频误判
#:   INVALID_NULL);
#: - inside_half_tolerance:target = 0.5 x 容差(经济等价区间内部;仅
#:   tolerance>0 的块定义);
#: - boundary_diagnostic:target = 容差(边界诊断,不解释为"必须拒绝";
#:   仅 tolerance>0 的块定义);
#: - violation_plus_1x_margin:target = 容差 + 1 x qualification_margin
#:   (超过允许容差一个完整 margin 的违规优势;拒绝功效 >= 80%);
#: - violation_plus_2x_margin:target = 容差 + 2 x qualification_margin
#:   (错误获得 QUALIFIED 的概率 <= 5%)。
POWER_SCENARIO_MANIFEST: dict[str, Any] = {
    "target_edge_rule": (
        "resample(empirical_centered_residuals) + target_absolute_edge;"
        "target 为绝对经济优势(经验分布先按 mean 中心化,不受原始经验"
        "均值污染)"),
    "center_statistic": "mean",
    "violation_margin_multiples": {"plus_1x": 1.0, "plus_2x": 2.0},
    "cluster_selection_rule": (
        "对预注册阶梯(32/64/96/128)升序评估并选择同时满足以下两项的"
        "最小 n:(a)该 n 下全部功效硬目标(Wilson 保守置信界,非点估计);"
        "(b)该 n 的资格 namespace 前缀上三族全部四个比较块的经济等价"
        "检验通过(中心与单侧上界均压进容差且无反证)——只满足功效但"
        "实际前缀资格不充分(INSUFFICIENT_EVIDENCE)的档位不得选用。"
        "经验分布基座固定为 64-cluster 资格报告(确定性 namespace 前缀;"
        "n>64 的候选需先扩展生成对应报告,本阶段不可达)。选定值必须等于"
        "冻结的 MIN_QUALIFICATION_CLUSTERS,不得按某次实际资格结果"
        "临时重选 seed"),
    "blocks": {
        "always_long_vs_flat": {
            "tolerance": "qualification_margin",
            "scenarios": [
                "valid_zero_edge", "inside_half_tolerance",
                "boundary_diagnostic", "violation_plus_1x_margin",
                "violation_plus_2x_margin",
            ],
        },
        "oracle": {
            "tolerance": "qualification_margin",
            "scenarios": [
                "valid_zero_edge", "inside_half_tolerance",
                "boundary_diagnostic", "violation_plus_1x_margin",
                "violation_plus_2x_margin",
            ],
        },
        "rule_trend": {
            "tolerance": "qualification_margin",
            "scenarios": [
                "valid_zero_edge", "inside_half_tolerance",
                "boundary_diagnostic", "violation_plus_1x_margin",
                "violation_plus_2x_margin",
            ],
        },
        # HighTurnover 容差为 0:零优势即合法对照,任何正优势都是违规
        "high_turnover_vs_flat": {
            "tolerance": "zero",
            "scenarios": [
                "valid_zero_edge", "violation_plus_1x_margin",
                "violation_plus_2x_margin",
            ],
        },
    },
}

#: 功效 Monte Carlo 配置(进入 spec 哈希;比例判定用保守置信界,
#: 不使用点估计——工作包 B5)。mc_iters=1600 由精度需求决定:容差为 0
#: 的 HighTurnover 块在零优势场景的名义误判率约 2.5%(单侧 97.5% 检验
#: 的边界固有率),400 次 MC 的 Wilson 上界噪声会越过 5% 硬目标;
#: 1600 次使上界稳定低于目标(不得因运行时间降低精度)。
POWER_MC_CONFIG: dict[str, Any] = {
    "mc_iters": 1600,
    "mc_seed": 20260827,
    "confidence_method": "wilson-score-95-two-sided-conservative",
}

#: 功效硬目标(进入 spec 哈希;对每个 family x required block 逐项达成)
POWER_TARGETS: dict[str, float] = {
    "max_false_invalid_rate_at_zero_edge": 0.05,
    "max_false_qualified_rate_at_2x_margin": 0.05,
    "min_rejection_power_at_1x_margin": 0.80,
}

#: cluster 数预注册候选阶梯(工作包 B6:重新校准,选择满足全部硬目标的
#: 最小值;选定后进入 spec 哈希,不得按某次实际资格结果临时重选)
CLUSTER_CANDIDATE_LADDER: tuple[int, ...] = (32, 64, 96, 128)

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
    "nuisance_slot_policy": (
        "antithetic_flip 不进入 nuisance counter-hash 派生(与 "
        "derive_seed 对称):同一 pair 的 nuisance 槽位逐位一致,"
        "候选无法经 nuisance 区分 pair side"),
}

#: 每族 family-level 资格的独立 cluster 数(功效分析按阶梯重选后的
#: 冻结值;不得因执行时间缩小)
MIN_QUALIFICATION_CLUSTERS = 64
#: 每 seed 关联 Episode 数(cluster 内均值;原始派生 Episode,
#: 无镜像——方差保留是资格判定的前提)
EPISODES_PER_SEED = 16
#: 实际 pack 内每族 null Episode 的最小独立 cluster 数(B2)
MIN_PACK_CLUSTERS_PER_FAMILY = 32

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
    """一次完整往返(开仓 + 平仓)的真实摩擦(冻结账本语义;阶段
    2.6.0e:精确 closed form,fee=0.001/slippage=0 ->
    0.002/1.001 = 0.001998001998...,不是旧公式的 0.001999)。"""
    slip = float(getattr(cfg, "slippage_bps", 0.0)) / 1e4
    return ledger_round_trip_friction(float(cfg.fee), slip)


def scenario_manifest_hash() -> str:
    """预注册场景清单哈希(npss-;进入 spec 与 power report)。"""
    return "npss-" + hashlib.sha256(
        json.dumps(POWER_SCENARIO_MANIFEST, sort_keys=True,
                   separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


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
    经济参数 / 冻结账本摩擦合同 / Episode 真实时长 / 统计协议 /
    比较策略与分块容差 / 聚合方式 / 功效场景清单与 MC 配置 / cluster
    候选阶梯 / seed namespace)。"""
    margin = round_trip_friction(cfg)
    return {
        "format": SPEC_FORMAT,
        "margin": margin,
        "margin_derivation": {
            "formula": LEDGER_ROUND_TRIP_FORMULA,
            "fee": float(cfg.fee),
            "slippage_bps": float(getattr(cfg, "slippage_bps", 0.0)),
            "price_tick": float(getattr(cfg, "price_tick", 0.0)),
            "units": "simple_return",
            "units_note": (
                "与 EpisodeResult.net_return 相同(final_cash/"
                "initial_cash - 1 的差值尺度;retention 即该比值)"),
            "ledger_semantics": {
                "buy": "qty = cash / (buy_exec_price * (1 + fee))",
                "sell": "final_cash = qty * sell_exec_price * (1 - fee)",
                "slippage": "buy P*(1+s) / sell P*(1-s)",
                "tick": "buy ceil_to_tick / sell floor_to_tick(方向不利)",
                "source_modules": [
                    "rl_platform.ledger", "rl_platform.market_execution"],
            },
            "tick_treatment": (
                "price_tick=0 精确 closed-form;tick>0 的方向不利取整只增"
                "摩擦,真实执行 parity 网格实证其为保守下界与 margin 硬"
                "上限(null_friction.friction_parity_problems)"),
            "friction_contract_format": FRICTION_CONTRACT_FORMAT,
            "friction_contract_hash": friction_contract_code_hash(),
            "semantics": (
                "一次完整往返的真实乘法交易摩擦(冻结账本语义);无条件"
                "策略相对 Flat 的允许正优势上限(经济解释:无信息交易者"
                "的套利屏障——优势低于该摩擦时任何单次往返都无法稳定"
                "获利)"),
            "hard_cap_satisfied": True,
        },
        "statistical_protocol": dict(STATISTICAL_PROTOCOL),
        "comparison_strategies": list(COMPARISON_STRATEGIES),
        "tolerance_by_block": dict(TOLERANCE_BY_BLOCK),
        "power_scenario_manifest": json.loads(json.dumps(
            POWER_SCENARIO_MANIFEST)),
        "power_scenario_manifest_hash": scenario_manifest_hash(),
        "power_mc_config": dict(POWER_MC_CONFIG),
        "power_targets": dict(POWER_TARGETS),
        "cluster_candidate_ladder": [int(n) for n in CLUSTER_CANDIDATE_LADDER],
        "cluster_aggregation": CLUSTER_AGGREGATION,
        "bootstrap_unit": BOOTSTRAP_UNIT,
        "antithetic_pairing": dict(ANTITHETIC_PAIRING),
        "episodes_per_seed": EPISODES_PER_SEED,
        "min_qualification_clusters": MIN_QUALIFICATION_CLUSTERS,
        "min_pack_clusters_per_family": MIN_PACK_CLUSTERS_PER_FAMILY,
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
    """规范 payload 的自洽校验(v2:margin 与冻结账本重算一致、真实执行
    parity 必须通过、单位/公式/摩擦合同/分块容差/场景清单/MC 配置全部
    对账)。"""
    import copy as _copy

    problems: list[str] = []
    fmt = payload.get("format")
    if fmt != SPEC_FORMAT:
        if fmt in _DEPRECATED_SPEC_FORMATS:
            problems.append(
                f"spec format {fmt!r} 已弃用(旧摩擦公式 1-(1-fee)^2*"
                f"(1-slippage)^2 与冻结账本不一致;必须以 "
                f"{SPEC_FORMAT!r} 重新生成)")
        else:
            problems.append(f"spec format {fmt!r} != {SPEC_FORMAT!r}")
    der = payload.get("margin_derivation") or {}
    cfg = EvalConfig(
        fee=float(der.get("fee", -1)),
        slippage_bps=float(der.get("slippage_bps", 0.0)),
        price_tick=float(der.get("price_tick", 0.0)),
    )
    recomputed = round_trip_friction(cfg)
    if abs(float(payload.get("margin", -1)) - recomputed) > 1e-12:
        problems.append(
            f"spec margin {payload.get('margin')!r} 与冻结账本摩擦重算值 "
            f"{recomputed:.12f} 不一致(margin 只能来自冻结账本公式)")
    if float(payload.get("margin", 1.0)) > recomputed + 1e-12:
        problems.append("spec margin 超过一次完整往返摩擦硬上限")
    if der.get("formula") != LEDGER_ROUND_TRIP_FORMULA:
        problems.append(
            f"margin 推导公式 {der.get('formula')!r} != 冻结账本公式"
            f"(旧错误公式 1-(1-fee)^2*(1-slippage)^2 已被废除)")
    if der.get("units") != "simple_return":
        problems.append("margin 单位必须为 simple_return(net_return 尺度)")
    if not str(der.get("friction_contract_hash") or "").startswith("nfc-"):
        problems.append("margin 推导缺少摩擦合同哈希(nfc-)")
    if der.get("friction_contract_hash") != friction_contract_code_hash():
        problems.append(
            "摩擦合同实现已变化但 spec 未重新生成"
            "(friction contract hash 不一致)")
    # A3:price_tick 保守下界性质必须由真实执行函数实证(不只写注释)
    parity_problems = friction_parity_problems()
    if parity_problems:
        problems.append(
            "冻结账本摩擦 parity 失败(tick 下界性质被违反;qualification"
            f" spec 不得构建): {parity_problems[:3]}")
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
    if payload.get("tolerance_by_block") != TOLERANCE_BY_BLOCK:
        problems.append("分块容差语义与预注册值不一致(四块硬门)")
    if payload.get("power_mc_config") != POWER_MC_CONFIG:
        problems.append("功效 MC 配置与预注册值不一致")
    if payload.get("power_scenario_manifest_hash") != scenario_manifest_hash():
        problems.append("功效场景清单哈希与预注册值不一致")
    manifest = _copy.deepcopy(payload.get("power_scenario_manifest") or {})
    if manifest != POWER_SCENARIO_MANIFEST:
        problems.append("功效场景清单与预注册清单不一致")
    if payload.get("cluster_candidate_ladder") != [
            int(n) for n in CLUSTER_CANDIDATE_LADDER]:
        problems.append("cluster 候选阶梯与预注册值不一致")
    if int(payload.get("min_qualification_clusters", 0)) < 32:
        problems.append("family-level 独立 cluster 数低于最小 32")
    if int(payload.get("min_pack_clusters_per_family", 0)) < 32:
        problems.append("pack-level 每族独立 cluster 数低于最小 32")
    return problems
