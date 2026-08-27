"""实际 Null pack 的 pack-level validity v2(阶段 2.6.0e 工作包 D)。

family-level 资格(生成器分布层面)不够——正式考试使用的是有限
Episode pack,必须在候选评估开始前验证实际 pack 自身。v2 在 2.6.0d
基础上修复四个降级缺口:

- D1 每 seed 恰好两条 Episode(一个 antithetic_flip=false + 一个
  true):不再用 set(flags) 去重——缺 original / 缺 flip / 两个
  original / 两个 flip / 一 orig + 两 flip / >=3 条 / 重复 spec
  全部 PACK_INVALID;
- D2 pair 参数一致性:family / family_version / base seed / timeframe
  / resolved duration / 行数 / 除 flip 外的原始 params / 生成器实现
  指纹,任一不同即 PACK_INVALID;
- D3 物化路径镜像验证:对实际被 commitment 绑定的每一对,逐步 log
  return 互为相反数、绝对收益一致、pair 累计 drift 精确抵消、volume
  逐位一致、隐藏 volatility/regime 状态逐位一致、长度与时间戳间隔
  一致、特征可由价格因果重算(预注册容差进入报告哈希);
- D4 nuisance 槽位逐位一致(生成器侧已排除 antithetic_flip;此处
  对实际物化 Episode 强制验证);
- D5 Oracle / Rule / AlwaysLong / HFT 四块全部使用
  "中心 <= tolerance 且 单侧置信上界 <= tolerance" 硬门——不再把
  Oracle/Rule 降级为只看点估计;样本不足以证明等价时 PACK_INVALID;
- D6 pack builder manifest(npb-)绑定真实 builder(assemble 函数 /
  seed namespace 推导 / pair 顺序 / attempt 循环 / 匿名拒绝日志 /
  validator / 参数规范 / family 列表),不再只哈希 validator 所在
  文件;builder 函数签名不得包含 candidate/checkpoint/model/policy。

pack 构建不可候选依赖(B4):构建算法在候选 checkpoint 出现前冻结;
固定 master seed derivation(pack_construction namespace);记录
attempt counter 与被拒 pack 的匿名原因;最大尝试数预注册。

隐藏考试隐私(C3):承诺只携带 pack validity 的 hash 与非敏感摘要;
完整 pack-level 报告由执行器对实际物化 pack 现算并对账 hash。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable

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

PACK_VALIDITY_FORMAT = "null-pack-validity-v2"
#: 已弃用格式(v1:只检查 flags 集合 + Oracle/Rule 仅点估计)
_DEPRECATED_PACK_FORMATS: tuple[str, ...] = (
    "null-pack-validity-v1",
)
#: pack 构建最大尝试数(预注册;超出即拒绝构建)
MAX_PACK_ATTEMPTS = 8

#: builder manifest 协议(D6)
PACK_BUILDER_MANIFEST_FORMAT = "null-pack-builder-manifest-v1"
#: builder 签名禁止参数(候选相关性 fail closed)
PACK_BUILDER_FORBIDDEN_PARAMS: tuple[str, ...] = (
    "candidate", "checkpoint", "model", "policy",
)

#: 预注册数值容差(进入 pack validity spec/report hash;D3)
MIRROR_TOLERANCES: dict[str, float] = {
    # 逐步 log return 反对称:|lr_orig[t] + lr_flip[t]| 逐位相反数
    "step_log_return_antisymmetry": 1e-12,
    # 逐步绝对收益一致:||lr_orig[t]| - |lr_flip[t]||(由反对称蕴含,
    # 仍显式校验)
    "abs_return_gap": 1e-12,
    # pair 累计 drift 精确抵消:|drift_orig + drift_flip|
    "pair_cumulative_drift_cancellation": 1e-9,
    # 特征由价格列因果重算的逐位一致性
    "feature_recompute_atol": 1e-12,
}
#: nuisance 槽位镜像模式(D4:逐位一致,无容差)
NUISANCE_MIRROR_MODE = "bitwise_equal"


def _fn_binding(fn: Callable) -> dict[str, Any]:
    """函数身份绑定(模块 + 限定名 + 源码哈希;实现变化 -> npb- 变)。"""
    return {
        "module": fn.__module__,
        "qualname": fn.__qualname__,
        "source_sha256": hashlib.sha256(
            inspect.getsource(fn).encode("utf-8")).hexdigest(),
    }


def _check_builder_signature(fn: Callable) -> None:
    """D6:builder 函数签名不得包含 candidate/checkpoint/model/policy。"""
    params = set(inspect.signature(fn).parameters)
    bad = sorted(params & set(PACK_BUILDER_FORBIDDEN_PARAMS))
    if bad:
        raise ValueError(
            f"builder 函数 {fn.__qualname__} 的签名包含禁止参数 {bad}"
            f"(pack 构建不得依赖任何候选/checkpoint/model/policy)")


def pack_builder_manifest(
    *, builder_fn: Callable | None = None,
    attempt_fn: Callable | None = None,
) -> dict[str, Any]:
    """构建真实 builder manifest(D6;默认绑定 mock builder)。

    绑定内容:真正构造 EpisodeSpec 的 builder(assemble)函数、seed
    namespace 推导、pair 顺序推导、antithetic pair 构造、attempt 循环、
    max attempts、匿名拒绝日志生成、pack validator、builder 协议版本、
    参数规范与 family 列表。修改任一项都会改变 npb- 哈希。

    正式私有 builder:评估方运行环境以实际私有 builder 函数调用本函数
    重新计算 manifest;公开 commitment 只发布 npb- 哈希与非敏感摘要。
    """
    from rl_curriculum import mock_sealed_exam
    from rl_curriculum.null_qualification_spec import (
        MIN_PACK_CLUSTERS_PER_FAMILY,
        pack_construction_seeds,
        pack_order_seed,
        qualification_seeds,
    )

    assemble = builder_fn or mock_sealed_exam.assemble_mock_hidden_pack
    attempt_loop = attempt_fn or mock_sealed_exam.build_mock_hidden_pack
    _check_builder_signature(assemble)
    _check_builder_signature(attempt_loop)
    _check_builder_signature(pack_builder_attempt_log)
    _check_builder_signature(validate_null_pack)
    return {
        "format": PACK_BUILDER_MANIFEST_FORMAT,
        "protocol": "null-pack-builder-protocol-v1",
        "builder_function": _fn_binding(assemble),
        "seed_namespace_derivation": [
            _fn_binding(qualification_seeds),
            _fn_binding(pack_construction_seeds),
        ],
        "pair_order_derivation": _fn_binding(pack_order_seed),
        "antithetic_pair_construction": (
            "同 base seed 的 (flip, orig) 两条 EpisodeSpec;flip 仅在 "
            "params['antithetic_flip']=True;pair 顺序由 pair_order_seed "
            "seeded 随机化(绑定于 builder_function 源码)"),
        "attempt_loop": _fn_binding(attempt_loop),
        "max_attempts": MAX_PACK_ATTEMPTS,
        "anonymous_reject_log_generator": _fn_binding(pack_builder_attempt_log),
        "pack_validator": _fn_binding(validate_null_pack),
        "params_spec": {
            "base_params": dict(mock_sealed_exam.BASE_PARAMS),
            "flip_flag_key": "antithetic_flip",
            "episode_bars": int(mock_sealed_exam.BASE_PARAMS[
                "episode_bars"]),
        },
        "pair_count_per_family": int(MIN_PACK_CLUSTERS_PER_FAMILY),
        "families": [
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"],
        "signature_policy": {
            "forbidden_params": list(PACK_BUILDER_FORBIDDEN_PARAMS),
            "enforced": True,
        },
    }


def pack_builder_manifest_hash(
    *, builder_fn: Callable | None = None,
    attempt_fn: Callable | None = None,
) -> str:
    """builder manifest 哈希(npb-;进入 sealed commitment)。"""
    manifest = pack_builder_manifest(
        builder_fn=builder_fn, attempt_fn=attempt_fn)
    return "npb-" + hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _verify_pair_structure(
    eps: list[Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """D1/D2:每 seed 恰好 (orig, flip) 各一;参数除 flip 外一致。

    返回 (pairs, problems);pairs 为 [{orig, flip, seed}]。
    """
    problems: list[str] = []
    by_seed: dict[int, list[Any]] = {}
    for ep in eps:
        by_seed.setdefault(int(ep.spec.seed), []).append(ep)
    # 重复 spec 检测(同族内同一 canonical spec 出现两次)
    canons: dict[str, int] = {}
    for ep in eps:
        canons[ep.spec.canonical()] = canons.get(ep.spec.canonical(), 0) + 1
    dup = [c for c, n in canons.items() if n > 1]
    if dup:
        problems.append(
            f"pack 存在重复 EpisodeSpec({len(dup)} 个 canonical 条目"
            f"出现多次;重复路径/重复 spec 均不合法)")
    pairs: list[dict[str, Any]] = []
    bad_seeds: list[int] = []
    for seed in sorted(by_seed):
        seed_eps = by_seed[seed]
        if len(seed_eps) != 2:
            problems.append(
                f"seed(匿名序号内)Episode 数 {len(seed_eps)} != 2:"
                f"每个 antithetic cluster 必须恰好一个 original + 一个 "
                f"flip(缺一/多一/三条及以上均 PACK_INVALID)")
            bad_seeds.append(seed)
            continue
        flips = sorted(
            bool((ep.spec.params or {}).get("antithetic_flip"))
            for ep in seed_eps)
        if flips != [False, True]:
            problems.append(
                "antithetic 结构不完整:存在 flip 标志组合非 "
                "{False, True} 的 seed(两个 original / 两个 flip 均"
                "PACK_INVALID)")
            bad_seeds.append(seed)
            continue
        orig = seed_eps[0] if not bool(
            seed_eps[0].spec.params.get("antithetic_flip")) else seed_eps[1]
        flip = seed_eps[1] if orig is seed_eps[0] else seed_eps[0]
        # ---- D2 参数一致性(除 antithetic_flip 外完全相同)
        po = {k: v for k, v in dict(orig.spec.params).items()
              if k != "antithetic_flip"}
        pf = {k: v for k, v in dict(flip.spec.params).items()
              if k != "antithetic_flip"}
        pair_problems: list[str] = []
        if po != pf:
            pair_problems.append("pair 原始 params 除 flip 外不一致")
        if orig.spec.timeframe != flip.spec.timeframe:
            pair_problems.append("pair timeframe 不一致")
        if orig.spec.resolved_duration() != flip.spec.resolved_duration():
            pair_problems.append("pair resolved duration 不一致")
        if orig.family_version != flip.family_version:
            pair_problems.append("pair family_version 不一致")
        if orig.generator_fingerprint != flip.generator_fingerprint:
            pair_problems.append("pair 生成器实现指纹不一致")
        if len(orig.df) != len(flip.df):
            pair_problems.append("pair 行数不一致")
        if orig.spec.split != flip.spec.split:
            pair_problems.append("pair split 不一致")
        problems.extend(
            f"pair(seed={seed})参数一致性失败: {p}" for p in pair_problems)
        if not pair_problems:
            pairs.append({"orig": orig, "flip": flip, "seed": seed})
    return pairs, problems


def _verify_pair_mirror(pair: dict[str, Any]) -> list[str]:
    """D3/D4:单个物化 (orig, flip) 对的镜像完整性验证。"""
    from rl_curriculum.generators import (
        PROBE_NUISANCE_SLOTS,
        recompute_probe_features,
    )

    orig, flip = pair["orig"], pair["flip"]
    o, f = orig.df, flip.df
    problems: list[str] = []
    lr_o = np.diff(np.log(o["close"].to_numpy(dtype=np.float64)))
    lr_f = np.diff(np.log(f["close"].to_numpy(dtype=np.float64)))
    if lr_o.shape != lr_f.shape:
        return ["pair 收益序列长度不一致(镜像不可验证)"]
    gap = float(np.max(np.abs(lr_o + lr_f))) if lr_o.size else 0.0
    if gap > MIRROR_TOLERANCES["step_log_return_antisymmetry"]:
        problems.append(
            f"逐步 log return 非相反数(max |lr_o+lr_f| = {gap:.3e} > "
            f"{MIRROR_TOLERANCES['step_log_return_antisymmetry']:.0e})")
    agap = float(np.max(np.abs(np.abs(lr_o) - np.abs(lr_f)))) \
        if lr_o.size else 0.0
    if agap > MIRROR_TOLERANCES["abs_return_gap"]:
        problems.append(
            f"逐步绝对收益不一致(max gap = {agap:.3e} > "
            f"{MIRROR_TOLERANCES['abs_return_gap']:.0e})")
    drift_pair = float(
        (np.log(o["close"].iloc[-1]) - np.log(o["open"].iloc[0]))
        + (np.log(f["close"].iloc[-1]) - np.log(f["open"].iloc[0])))
    if abs(drift_pair) > MIRROR_TOLERANCES[
            "pair_cumulative_drift_cancellation"]:
        problems.append(
            f"pair 累计 drift 未精确抵消(sum = {drift_pair:.3e} > "
            f"{MIRROR_TOLERANCES['pair_cumulative_drift_cancellation']:.0e})")
    if not np.array_equal(
            o["volume"].to_numpy(dtype=np.float64),
            f["volume"].to_numpy(dtype=np.float64)):
        problems.append("volume 路径不一致(必须逐位一致)")
    if list(o["date"]) != list(f["date"]):
        problems.append("时间戳序列不一致(长度或间隔)")
    if not orig.hidden.equals(flip.hidden):
        problems.append(
            "隐藏 volatility/regime 状态路径不一致(必须逐位一致)")
    # ---- D4:nuisance 槽位逐位一致(flip 不得改变 nuisance 派生)
    for slot in PROBE_NUISANCE_SLOTS:
        if slot in o.columns and slot in f.columns:
            if not np.array_equal(
                    o[slot].to_numpy(dtype=np.float64),
                    f[slot].to_numpy(dtype=np.float64)):
                problems.append(
                    f"nuisance 槽位 {slot} 因 antithetic_flip 改变"
                    f"(pair side 不得编码进 observation)")
    # ---- 特征可由价格列因果重算(两 Episode 分别校验)
    for label, ep in (("orig", orig), ("flip", flip)):
        rebuilt = recompute_probe_features(
            ep.df, family=ep.spec.family, family_version=ep.family_version,
            params=dict(ep.spec.params), seed=ep.spec.seed,
            timeframe=ep.spec.timeframe)
        for col in ep.observation_columns():
            if col not in rebuilt.columns:
                problems.append(
                    f"[{label}] 特征 {col} 无法由价格列因果重算")
                continue
            a = ep.df[col].to_numpy(dtype=np.float64)
            b = rebuilt[col].to_numpy(dtype=np.float64)
            if a.shape != b.shape or not np.allclose(
                    a, b, rtol=0.0,
                    atol=MIRROR_TOLERANCES["feature_recompute_atol"]):
                problems.append(
                    f"[{label}] 特征 {col} 因果重算不一致"
                    f"(特征依赖未来行或重建非确定)")
    return problems


def validate_null_pack(
    episodes_by_family: dict[str, list[Any]],
    *,
    cfg, schema, spec: dict[str, Any],
    pack_hash: str = "",
) -> dict[str, Any]:
    """对实际物化的 null Episode(按族分组)执行 pack-level validity v2。

    episodes_by_family: {family: [GeneratedEpisode, ...]}(pack 内
    split == null_control 的全部 Episode)。spec:qualification spec
    payload(margin/分块容差/统计协议/门槛)。pack_hash:对应 pack 的
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

        # ---- D1/D2:每 seed 恰好 (orig, flip) 各一,参数仅 flip 可不同
        # ---- D3/D4:每个物化 pair 的镜像/nuisance 完整性
        # (必须对实际被 commitment 绑定的每一对执行,不得只抽样)
        pairs: list[dict[str, Any]] = []
        if (spec.get("antithetic_pairing") or {}).get("enabled"):
            pairs, struct_problems = _verify_pair_structure(eps)
            fam_problems.extend(struct_problems)
            mirror_details: list[dict[str, Any]] = []
            n_mirror_bad = 0
            for pair in pairs:
                mirror_problems = _verify_pair_mirror(pair)
                if mirror_problems:
                    n_mirror_bad += 1
                    fam_problems.extend(
                        f"pair(seed={pair['seed']})镜像验证失败: {p}"
                        for p in mirror_problems)
                mirror_details.append({
                    "seed": pair["seed"],
                    "mirror_ok": not mirror_problems,
                    "problems": mirror_problems,
                })
            pair_summary = {
                "n_pairs_expected": n_clusters,
                "n_pairs_verified": len(pairs),
                "n_pairs_mirror_ok": len(pairs) - n_mirror_bad,
                "mirror_tolerances": dict(MIRROR_TOLERANCES),
                "nuisance_mirror_mode": NUISANCE_MIRROR_MODE,
                "every_pair_verified": True,
            }
        else:
            mirror_details = []
            pair_summary = {
                "n_pairs_expected": 0, "n_pairs_verified": 0,
                "n_pairs_mirror_ok": 0, "every_pair_verified": False,
                "note": "spec 未启用 antithetic pairing",
            }

        def _agg(key: str) -> list[float]:
            return [float(np.mean(by_seed[s][key])) for s in seeds]

        blocks = {}
        if n_clusters < MIN_PACK_CLUSTERS_PER_FAMILY:
            fam_problems.append(
                f"pack 内独立 cluster 数 {n_clusters} < "
                f"{MIN_PACK_CLUSTERS_PER_FAMILY}(pack-level 冻结要求)")
        # ---- D5:四块全部使用 中心 <= tol 且 CI 上界 <= tol 硬门
        # (Oracle/Rule 不再降级为只看点估计;样本不足以证明等价 ->
        # PACK_INVALID)
        for key, tol in (
            ("oracle", margin),
            ("rule", margin),
            ("long", margin),
            ("hft", HIGH_TURNOVER_TOLERANCE),
        ):
            cv = _agg(key)
            boot = paired_bootstrap_ci(cv, stat="mean")
            center = float(np.mean(cv))
            blocks[key] = {
                "n_clusters": n_clusters,
                "mean": center,
                "ci_low": boot["ci_low"],
                "ci_high": boot["ci_high"],
                "bootstrap_n": boot["n"],
                "test_mode": "center_and_upper_bound",
                "tolerance": float(tol),
            }
            ok = bool(center <= tol and boot["ci_high"] <= tol)
            if not ok:
                fam_problems.append(
                    f"{key}: 中心 {center:+.6f} / CI 上界 "
                    f"{boot['ci_high']:+.6f} 未满足 pack-level 容差 "
                    f"{tol:.6f}(中心与单侧置信上界双门;pack 实际样本"
                    f"存在可交易优势或不足以证明等价)")
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
            "pairs": pair_summary,
            "pair_details": mirror_details,
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
        "mirror_tolerances": dict(MIRROR_TOLERANCES),
        "nuisance_mirror_mode": NUISANCE_MIRROR_MODE,
        "per_family": per_family,
        "reasons": reasons,
        "verdict": verdict,
        "pass": verdict == "PACK_VALID",
        "builder_manifest_hash": pack_builder_manifest_hash(),
    }


def pack_validity_report_hash(report: dict[str, Any]) -> str:
    return "npv-" + hashlib.sha256(
        json.dumps(report, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def pack_builder_code_hash() -> str:
    """pack 构建算法绑定哈希(D6:真实 builder manifest,不再只哈希
    validator 所在文件;进入 sealed commitment)。"""
    return pack_builder_manifest_hash()


def pack_builder_attempt_log(
    attempts: list[dict[str, Any]],
) -> dict[str, Any]:
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
    # pack-level spec 校验(margin 与冻结账本重算一致等)
    from rl_curriculum.null_qualification_spec import verify_spec_payload

    problems = verify_spec_payload(spec)
    if problems:
        raise ValueError(f"qualification spec 自洽失败: {problems}")
    return spec
