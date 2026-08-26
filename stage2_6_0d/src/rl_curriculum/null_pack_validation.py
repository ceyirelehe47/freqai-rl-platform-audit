"""阶段 2.6.0d 工作包 B2/B4/C3:实际 Null pack 的 pack-level validity。

family-level 资格(生成器分布层面)不够——正式考试使用的是有限
Episode pack,必须在候选评估开始前验证实际 pack 自身:

- 每族实际 null Episode 数与独立 cluster 数达到冻结要求
  (MIN_PACK_CLUSTERS_PER_FAMILY,与 family-level 门槛分离);
- 实际 pack 的 Oracle / RuleTrend / AlwaysLong 相对 AlwaysFlat
  满足 pack-level margin(同一 qualification spec;pack 内每 seed
  一个 cluster);
- HighTurnover 扣费后无非正优势;
- 没有偶然抽出明显正漂移的 pack(判定由差值上置信界承载;
  episode 累计漂移作为诊断记录);
- pack-level 验证失败 -> EXAM_INVALID(不得把候选判 FAIL 或作弊,
  不得让候选进入评估)。

pack 构建不可候选依赖(B4):构建算法在候选 checkpoint 出现前冻结;
使用固定 master seed derivation(pack_construction namespace);
记录 attempt counter 与被拒 pack 的匿名原因;最大尝试数预注册;
选择标准只依赖 Null 结构/Oracle/规则/trivial baseline(不依赖任何
候选模型成绩);最终 pack hash/pack validity report hash/构建算法
hash 进入 commitment。

隐藏考试隐私(C3):承诺只携带 pack validity 的 hash 与非敏感摘要;
完整 pack-level 报告由执行器对实际物化 pack 现算并对账 hash——
不公开正式隐藏 seed 与逐 Episode 明细。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.evaluator import (
    paired_bootstrap_ci,
    run_policy_episode,
)
from rl_curriculum.null_qualification import (
    HIGH_TURNOVER_TOLERANCE,
    _oracle_for,
)
from rl_curriculum.null_qualification_spec import (
    MIN_PACK_CLUSTERS_PER_FAMILY,
    build_spec_payload,
    null_qualification_spec_hash,
)

PACK_VALIDITY_FORMAT = "null-pack-validity-v1"
#: pack 构建最大尝试数(预注册;超出即拒绝构建)
MAX_PACK_ATTEMPTS = 8


def validate_null_pack(
    episodes_by_family: dict[str, list[Any]],
    *,
    cfg, schema, spec: dict[str, Any],
    pack_hash: str = "",
) -> dict[str, Any]:
    """对实际物化的 null Episode(按族分组)执行 pack-level validity。

    episodes_by_family: {family: [GeneratedEpisode, ...]}(pack 内
    split == null_control 的全部 Episode;同一 seed 的多个 Episode
    先按 per-seed-mean 聚合成一个 cluster)。spec:qualification
    spec payload(margin/统计协议/门槛)。pack_hash:对应 pack 的
    哈希(执行器与构建侧都传入,报告因此完全确定可对账)。

    返回报告 payload;verdict == "PACK_VALID" 才允许候选进入评估,
    否则执行器必须 EXAM_INVALID。
    """
    from rl_curriculum.policies import (
        AlwaysFlatPolicy,
        AlwaysLongPolicy,
        HighTurnoverPolicy,
        RuleTrendPolicy,
    )

    margin = float(spec["margin"])
    flat, long_ = AlwaysFlatPolicy(), AlwaysLongPolicy()
    rule, hft = RuleTrendPolicy(), HighTurnoverPolicy()
    reasons: list[str] = []
    per_family: dict[str, dict[str, Any]] = {}

    for family in sorted(episodes_by_family):
        eps = episodes_by_family[family]
        oracle = _oracle_for(family)
        by_seed: dict[int, dict[str, list[float]]] = {}
        drifts: dict[int, list[float]] = {}
        for ep in eps:
            seed = int(ep.spec.seed)
            slot = by_seed.setdefault(
                seed, {"oracle": [], "rule": [], "long": [], "hft": []})
            f_net = run_policy_episode(flat, ep, cfg, schema).net_return
            slot["oracle"].append(
                run_policy_episode(oracle, ep, cfg, schema).net_return - f_net)
            slot["rule"].append(
                run_policy_episode(rule, ep, cfg, schema).net_return - f_net)
            slot["long"].append(
                run_policy_episode(long_, ep, cfg, schema).net_return - f_net)
            slot["hft"].append(
                run_policy_episode(hft, ep, cfg, schema).net_return - f_net)
            lc = np.log(ep.df["close"].to_numpy(dtype=np.float64))
            drifts.setdefault(seed, []).append(float(
                lc[-1] - np.log(ep.df["open"].iloc[0])))
        seeds = sorted(by_seed)
        n_clusters = len(seeds)
        fam_problems: list[str] = []
        # antithetic 结构校验(D7):每 seed 恰好 (orig, flip) 各一
        # (spec 声明 antithetic_pairing.enabled 时强制)
        if (spec.get("antithetic_pairing") or {}).get("enabled"):
            flip_by_seed: dict[int, set] = {}
            for ep in eps:
                flip_by_seed.setdefault(int(ep.spec.seed), set()).add(
                    bool((ep.spec.params or {}).get("antithetic_flip")))
            bad = [s for s, flags in flip_by_seed.items() if flags != {False, True}]
            if bad:
                fam_problems.append(
                    f"antithetic 结构不完整:{len(bad)} 个 seed 的镜像对"
                    f"不完整(每 seed 必须 orig 与 flip 各恰好一个;"
                    f"首批异常 seed(匿名序号): {bad[:3]}")

        def _agg(key: str) -> list[float]:
            return [float(np.mean(by_seed[s][key])) for s in seeds]

        blocks = {}
        if n_clusters < MIN_PACK_CLUSTERS_PER_FAMILY:
            fam_problems.append(
                f"pack 内独立 cluster 数 {n_clusters} < "
                f"{MIN_PACK_CLUSTERS_PER_FAMILY}(pack-level 冻结要求)")
        for key, tol, mode in (
            ("oracle", margin, "center"),
            ("rule", margin, "center"),
            ("long", margin, "upper_bound"),
            ("hft", HIGH_TURNOVER_TOLERANCE, "upper_bound"),
        ):
            cv = _agg(key)
            boot = paired_bootstrap_ci(cv, stat="mean")
            center = float(np.mean(cv))
            blocks[key] = {
                "n_clusters": n_clusters,
                "mean": center,
                "ci_low": boot["ci_low"], "ci_high": boot["ci_high"],
                "bootstrap_n": boot["n"],
                "test_mode": mode,
            }
            if mode == "upper_bound":
                # AlwaysLong/HFT:中心 + 单侧上置信界都要压进容差
                # (antithetic 镜像使 pair 级优势/漂移精确抵消,该检验
                # 在 pack 级可达;无条件多头优势是唯一直接可交易对象,
                # 采用与 family-level 相同的最强检验)
                ok = (center <= tol and boot["ci_high"] <= tol)
            else:
                # Oracle/Rule:pack 有限样本下其差值 CI 上界不可达
                # (pair 镜像不镜像信息策略的持仓,cluster 波动保留);
                # 信息策略的统计推断已由 family-level(64 cluster x
                # 16 ep)承载,pack-level 用中心统计量拦截"明显可预测
                # pack"(点估计超过 margin 即拒绝)
                ok = center <= tol
            if not ok:
                fam_problems.append(
                    f"{key}: 中心 {center:+.5f} / CI 上界 "
                    f"{boot['ci_high']:+.5f} 未满足 pack-level 容差 "
                    f"{tol:.6f}(模式 {mode};pack 实际样本存在可交易"
                    f"优势)")
        drift_cv = [float(np.mean(drifts[s])) for s in seeds]
        drift_boot = paired_bootstrap_ci(drift_cv, stat="mean")
        blocks["episode_net_drift_diagnostic"] = {
            "mean": float(np.mean(drift_cv)),
            "ci_low": drift_boot["ci_low"],
            "ci_high": drift_boot["ci_high"],
        }
        per_family[family] = {
            "n_episodes": len(eps),
            "n_clusters": n_clusters,
            "seeds": seeds,
            "blocks": blocks,
            "problems": fam_problems,
        }
        reasons.extend(f"{family}: {p}" for p in fam_problems)

    verdict = "PACK_VALID" if not reasons else "PACK_INVALID"
    return {
        "format": PACK_VALIDITY_FORMAT,
        "level": "pack",
        "pack_hash": pack_hash,
        "qualification_spec_hash": null_qualification_spec_hash(spec),
        "margin": margin,
        "min_pack_clusters_per_family": MIN_PACK_CLUSTERS_PER_FAMILY,
        "per_family": per_family,
        "reasons": reasons,
        "verdict": verdict,
        "pass": verdict == "PACK_VALID",
        "builder_code_hash": pack_builder_code_hash(),
    }


def pack_validity_report_hash(report: dict[str, Any]) -> str:
    return "npv-" + hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def pack_builder_code_hash() -> str:
    """pack 构建算法代码哈希(本模块;进入 sealed commitment,实现
    变化即失效——B4:构建规则在候选出现前冻结)。"""
    src = Path(inspect.getsourcefile(validate_null_pack))  # type: ignore[arg-type]
    return "npb-" + hashlib.sha256(src.read_bytes()).hexdigest()


def pack_builder_attempt_log(
    attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """构建尝试记录(匿名拒绝原因;不含 seed 明细——C3 隐私)。"""
    return {
        "format": "null-pack-builder-attempt-log-v1",
        "max_attempts": MAX_PACK_ATTEMPTS,
        "attempts": [
            {"attempt": a["attempt"],
             "verdict": a["verdict"],
             "anonymous_reject_reasons": a.get("reject_reasons", [])}
            for a in attempts],
    }


def build_spec_for_pack(cfg, *, timeframe: str, episode_bars: int,
                        ) -> dict[str, Any]:
    """pack-level 验证使用的 qualification spec(与 family-level 同源)。"""
    spec = build_spec_payload(
        cfg, timeframe=timeframe, episode_bars=episode_bars)
    # pack-level spec 校验(margin 与 EvalConfig 重算一致等)
    from rl_curriculum.null_qualification_spec import verify_spec_payload

    problems = verify_spec_payload(spec)
    if problems:
        raise ValueError(f"qualification spec 自洽失败: {problems}")
    return spec
