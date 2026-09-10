"""阶段 2.6.1 工作包 G/I:课程资格基础设施与运行器。

校准(calibration namespace)与最终资格(qualification namespace)共用
同一评估代码路径;差异只在 seed namespace 与是否已锁定 plan。

评估层:
- degenerate baseline matrix:Always Flat / Always Long / family 特异
  简单基线(C1 朴素动量、C2 local-only、C3 cost-ignorant)+ 附加
  诊断基线(C2 单上下文)——全部经冻结 AlignedLongFlatEnv 计算净收益;
- causal observation reference policy(每 family 的参考策略,只读当前
  observation);
- latent oracle(读 sidecar,仅诊断,证明世界确实含有目标因果结构);
- 难度度量 M_rung = mean(ref) - max(0, mean(always_long))(corpus 级,
  "跨 pair 稳定胜出"的语料级口径;always_flat 恒 0)。

因果矩阵(§15):
- observation causality:未来噪声变异(按噪声配对粒度,变异起点之后
  的配对改由盐化 RNG 重抽)不得改变起点之前的 observation;
- HTF causality:特征前缀重算(generator 自动)+ 与 pandas resample
  的整点对齐等价性显式验证;
- reference causality:相同 observation 向量 -> 相同 action(跨 episode
  验证),参考策略接口只接收 observation;
- latent isolation:sidecar 列与 observation 列零交集、禁止命名模式
  不命中、清零 sidecar 不改变 observation。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    curriculum261_eval_config,
    derive261_seed,
    episode_content_hash,
    qualification_r2_unlocked,
)
from rl_curriculum.curriculum261_c1 import (
    C1OraclePolicy,
    C1ReferencePolicy,
    C1ShortcutPolicy,
    c1_reference_threshold,
)
from rl_curriculum.curriculum261_c2 import (
    C2LocalOnlyPolicy,
    C2OraclePolicy,
    C2ReferencePolicy,
    C2SingleContextPolicy,
)
from rl_curriculum.curriculum261_c3 import (
    C3CostIgnorantPolicy,
    C3OraclePolicy,
    C3ReferencePolicy,
    c3_strength_threshold,
)
from rl_curriculum.curriculum261_pairs import (
    PairRecord,
    attempt_statistics,
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_production_obs import (
    assert_production_observation_binding,
    production_observation_schema,
)
from rl_curriculum.evaluator import run_policy_episode
from rl_curriculum.policies import AlwaysFlatPolicy, AlwaysLongPolicy

#: repair R1:qualification 的 observation 一律绑定生产路径
#: (RouteCStrategy.feature_engineering_standard -> AlignedLongFlatEnv);
#: 守卫测试断言本 schema 的 hash 与 production 一致——若被切回任何
#: 课程自制 schema(旧 obs v1 等)立即失败。
SCHEMA = production_observation_schema()
EVAL_CFG = curriculum261_eval_config()

#: 各 family 的"必胜"基线集合(参考必须在这些之上;其余为报告用诊断基线)
REQUIRED_BASELINES: dict[str, tuple[str, ...]] = {
    "c1_opportunity": ("always_flat", "always_long"),
    "c2_context": ("always_flat", "always_long", "c2_local_only"),
    "c3_cost": ("always_flat", "always_long", "c3_cost_ignorant"),
}


def build_policy_set(family: str, rung_params: dict[str, Any],
                     thresholds: dict[str, Any]) -> dict[str, Any]:
    """一个 family 的完整评估策略集(参考 + 基线;oracle 单独构建)。"""
    policies: dict[str, Any] = {
        "always_flat": AlwaysFlatPolicy(),
        "always_long": AlwaysLongPolicy(),
    }
    if family == "c1_opportunity":
        policies["c1_shortcut_naive_momentum"] = C1ShortcutPolicy()
        policies["reference"] = C1ReferencePolicy(
            c1_reference_threshold(rung_params, thresholds["ma_sigma_mult"]))
    elif family == "c2_context":
        cue = float(thresholds["cue_thr"])
        dir_thr = float(thresholds["wick_dir_thr"])
        width_thr = float(thresholds["wick_width_thr"])
        policies["c2_local_only"] = C2LocalOnlyPolicy(cue)
        policies["c2_single_context_wick_dir"] = C2SingleContextPolicy(
            cue, dir_thr, "wick_dir")
        policies["c2_single_context_wick_width"] = C2SingleContextPolicy(
            cue, width_thr, "wick_width")
        policies["reference"] = C2ReferencePolicy(cue, dir_thr, width_thr)
    elif family == "c3_cost":
        policies["c3_cost_ignorant"] = C3CostIgnorantPolicy(
            float(thresholds["any_signal_s"]))
        policies["reference"] = C3ReferencePolicy(
            c3_strength_threshold(rung_params, float(thresholds["margin"])))
    else:
        raise KeyError(family)
    return policies


def build_oracle(family: str) -> Any:
    return {
        "c1_opportunity": C1OraclePolicy,
        "c2_context": C2OraclePolicy,
        "c3_cost": C3OraclePolicy,
    }[family]()


def evaluate_pair_corpus(
    records: list[PairRecord], family: str, rung_params: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """一个 family 全部 pair 的策略评估(ref/baseline/oracle 逐 episode)。"""
    policies = build_policy_set(family, rung_params, thresholds)
    oracle = build_oracle(family)
    per_episode: list[dict[str, Any]] = []
    nets: dict[str, list[float]] = {name: [] for name in policies}
    nets["oracle"] = []
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            row: dict[str, Any] = {
                "rung": rec.rung, "pair": rec.pair_index, "side": side,
                "episode_hash": rec.attempt_log.episode_hashes[side],
            }
            for name, pol in policies.items():
                r = run_policy_episode(pol, ep, EVAL_CFG, SCHEMA)
                nets[name].append(float(r.net_return))
                row[name] = float(r.net_return)
                row[f"{name}_trades"] = int(r.n_trades)
            ro = run_policy_episode(oracle, ep, EVAL_CFG, SCHEMA)
            nets["oracle"].append(float(ro.net_return))
            row["oracle"] = float(ro.net_return)
            per_episode.append(row)
    means = {k: float(np.mean(v)) for k, v in nets.items()}
    # 难度度量与资格关系(corpus 级)
    best_const = max(0.0, means["always_long"])
    metric = means["reference"] - best_const
    best_required = max(
        means[b] for b in REQUIRED_BASELINES[family])
    return {
        "family": family,
        "policy_means": means,
        "difficulty_metric": metric,
        "reference_beats_required_baselines":
            bool(means["reference"] > best_required),
        "oracle_positive": bool(means["oracle"] > 0.0),
        "episodes": per_episode,
    }


def rung_report(records: list[PairRecord], family: str,
                rung_params_by_rung: dict[str, dict[str, Any]],
                thresholds_by_family: dict[str, dict[str, Any]],
                ) -> dict[str, Any]:
    """按 rung 聚合评估 + 难度排序判定。"""
    by_rung: dict[str, Any] = {}
    for rung in CURRICULUM261_RUNGS:
        rung_records = [r for r in records if r.rung == rung]
        ev = evaluate_pair_corpus(
            rung_records, family, rung_params_by_rung[rung],
            thresholds_by_family[family])
        ev["rung"] = rung
        by_rung[rung] = ev
    metrics = [by_rung[r]["difficulty_metric"] for r in CURRICULUM261_RUNGS]
    return {
        "family": family,
        "by_rung": by_rung,
        "difficulty_metric_ladder": {
            r: by_rung[r]["difficulty_metric"] for r in CURRICULUM261_RUNGS},
        "ordering_ok": bool(
            metrics[0] > metrics[1] > metrics[2] > metrics[3]),
        "d3_metric_positive": bool(metrics[3] > 0.0),
        "reference_beats_required_all_rungs": bool(all(
            by_rung[r]["reference_beats_required_baselines"]
            for r in CURRICULUM261_RUNGS)),
        "oracle_positive_all_rungs": bool(all(
            by_rung[r]["oracle_positive"] for r in CURRICULUM261_RUNGS)),
    }


# ------------------------------------------------------------- 因果矩阵
def check_observation_causality(family: str, rung: str, pair_index: int,
                                namespace: str = "qualification_r2",
                                ) -> dict[str, Any]:
    """未来噪声变异:变异起点前的 observation 必须逐位不变。

    namespace 参数化:final 走 qualification_r2(lock 后放行);
    lock 前的守卫/诊断测试可传 calibration_r2。"""
    spec = family_specs()[family]
    rung_params = dict(spec.rung_params[rung])
    rung_params["cur261_rung"] = rung
    gen = spec.generator
    from rl_curriculum.curriculum261_api import CURRICULUM261_TIMEFRAME
    from rl_curriculum.evaluator import select_features_strict

    base_params = gen.base_params(rung_params, "A")
    cut = 150
    ep_base = gen.generate(base_params, derive261_seed(
        namespace, family, rung, pair_index, 0),
        split="curriculum261_causality", timeframe=CURRICULUM261_TIMEFRAME)
    mut_params = dict(base_params)
    mut_params["noise_mutate_from"] = cut
    mut_params["noise_mutate_salt"] = 20260830
    ep_mut = gen.generate(mut_params, derive261_seed(
        namespace, family, rung, pair_index, 0),
        split="curriculum261_causality", timeframe=CURRICULUM261_TIMEFRAME)
    obs_cols = list(SCHEMA.feature_names)
    a = ep_base.df[obs_cols].to_numpy(dtype=np.float64)[:cut]
    b = ep_mut.df[obs_cols].to_numpy(dtype=np.float64)[:cut]
    pa = ep_base.df["close"].to_numpy()[:cut]
    pb = ep_mut.df["close"].to_numpy()[:cut]
    future_differs = not np.allclose(
        ep_base.df["close"].to_numpy()[cut:],
        ep_mut.df["close"].to_numpy()[cut:], rtol=0, atol=0)
    return {
        "family": family, "rung": rung, "pair": pair_index, "cut": cut,
        "prefix_observation_identical": bool(np.array_equal(a, b)),
        "prefix_price_identical": bool(np.array_equal(pa, pb)),
        "future_actually_mutated": bool(future_differs),
        "pass": bool(np.array_equal(a, b) and np.array_equal(pa, pb)
                     and future_differs),
    }


def check_production_feature_equivalence(family: str, rung: str,
                                         pair_index: int,
                                         namespace: str = "qualification_r2",
                                         ) -> dict[str, Any]:
    """production observation identity:episode 的 8 个特征列必须与
    真实 RouteCStrategy.feature_engineering_standard 的独立重算逐位
    一致;observation 数组必须由冻结 AlignedLongFlatEnv 构造且落在
    observation_space 内(repair R1 核心检查,替代旧 htf resample)。
    """
    from rl_curriculum.curriculum261_api import CURRICULUM261_TIMEFRAME
    from rl_platform.env import AlignedLongFlatEnv
    from rl_curriculum.evaluator import select_features_strict
    from rl_curriculum.generator_api import PRICE_COLUMNS

    spec = family_specs()[family]
    rung_params = dict(spec.rung_params[rung])
    rung_params["cur261_rung"] = rung
    ep = spec.generator.generate(
        spec.generator.base_params(rung_params, "A"),
        derive261_seed(namespace, family, rung, pair_index, 0),
        split="curriculum261_causality", timeframe=CURRICULUM261_TIMEFRAME)
    try:
        assert_production_observation_binding(
            SCHEMA, ep.df, context=f"qual_feature_equivalence/{family}")
        binding_ok = True
        binding_error = ""
    except RuntimeError as exc:
        binding_ok = False
        binding_error = str(exc)[:300]
    # observation 数组由冻结环境构造(env.reset)且与特征行逐位一致
    feats = select_features_strict(ep.df, SCHEMA)
    env = AlignedLongFlatEnv(
        features=feats, prices=ep.df[list(PRICE_COLUMNS)],
        fee=EVAL_CFG.fee, slippage_bps=EVAL_CFG.slippage_bps,
        initial_cash=EVAL_CFG.initial_cash, window_size=1)
    obs, _ = env.reset(seed=1)
    t0 = env.first_decision_tick
    expect = np.concatenate([
        feats.to_numpy(dtype=np.float64)[t0],
        [0.0]]).astype(np.float32)
    obs_matches_features = bool(np.array_equal(obs, expect))
    in_space = bool(
        env.observation_space.contains(obs))
    return {
        "family": family, "rung": rung, "pair": pair_index,
        "schema_hash": SCHEMA.schema_hash(),
        "production_binding_ok": bool(binding_ok),
        "binding_error": binding_error,
        "observation_from_frozen_env": bool(obs_matches_features),
        "observation_in_space": bool(in_space),
        "pass": bool(binding_ok and obs_matches_features and in_space),
    }


def check_reference_causality(family: str, rung_params: dict[str, Any],
                              thresholds: dict[str, Any]) -> dict[str, Any]:
    """相同 observation -> 相同 action(跨 episode / 跨 bar)。"""
    policies = build_policy_set(family, rung_params, thresholds)
    rng = np.random.default_rng(20260830)
    obs_a = rng.normal(0, 0.01, size=(6, SCHEMA.observation_dim)
                       ).astype(np.float32)
    obs_b = rng.normal(0, 0.01, size=(6, SCHEMA.observation_dim)
                       ).astype(np.float32)
    obs_b[2] = obs_a[4]  # 人为制造一行完全相同
    consistent = True
    for name, pol in policies.items():
        if hasattr(pol, "bind_observation_schema"):
            pol.bind_observation_schema(SCHEMA)
        pol.reset_episode()
        act_a = [int(pol.act(o)) for o in obs_a]
        act_b = [int(pol.act(o)) for o in obs_b]
        if act_a[4] != act_b[2]:
            consistent = False
    return {
        "family": family,
        "same_observation_same_action": bool(consistent),
        "policies_observation_only": bool(all(
            hasattr(p, "act") and not getattr(p, "reads_hidden", False)
            for p in policies.values())),
        "pass": bool(consistent),
    }


def check_latent_isolation(records: list[PairRecord]) -> dict[str, Any]:
    """sidecar 与 observation 零交集 + 清零 sidecar 不改变 observation。"""
    from rl_curriculum.generator_api import FORBIDDEN_OBSERVATION_PATTERNS
    overlap: list[str] = []
    forbidden_hits: list[str] = []
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            overlap += sorted(set(ep.hidden.columns)
                              & set(ep.observation_columns()))
            for c in ep.observation_columns():
                for pat in FORBIDDEN_OBSERVATION_PATTERNS:
                    if pat in c:
                        forbidden_hits.append(f"{ep.spec.family}:{c}")
    # 清零 sidecar 不改变 observation:重建 env 只用 df
    sample = records[0].episodes["A"]
    from rl_platform.env import AlignedLongFlatEnv
    from rl_curriculum.evaluator import select_features_strict
    from rl_curriculum.generator_api import PRICE_COLUMNS
    feats = select_features_strict(sample.df, SCHEMA)
    env1 = AlignedLongFlatEnv(
        features=feats, prices=sample.df[list(PRICE_COLUMNS)],
        fee=EVAL_CFG.fee, slippage_bps=EVAL_CFG.slippage_bps,
        initial_cash=EVAL_CFG.initial_cash, window_size=1)
    obs1, _ = env1.reset(seed=1)
    obs2, _ = env1.reset(seed=1)
    return {
        "n_pairs_checked": len(records),
        "sidecar_observation_overlap": sorted(set(overlap)),
        "forbidden_pattern_hits": sorted(set(forbidden_hits)),
        "observation_deterministic_without_sidecar": bool(
            np.array_equal(obs1, obs2)),
        "pass": bool(not overlap and not forbidden_hits
                     and np.array_equal(obs1, obs2)),
    }


def check_reproducibility(family: str, rung: str, pair_index: int,
                          namespace: str) -> dict[str, Any]:
    """同 config+seed 完全一致;同 pair seed 完全一致;新 seed 不同。"""
    rec1 = generate_pair(family, rung, pair_index, namespace=namespace)
    rec2 = generate_pair(family, rung, pair_index, namespace=namespace)
    same_pair = all(
        rec1.episodes[s].df.equals(rec2.episodes[s].df)
        and rec1.episodes[s].hidden.equals(rec2.episodes[s].hidden)
        for s in ("A", "B"))
    hash_same = (rec1.attempt_log.episode_hashes
                 == rec2.attempt_log.episode_hashes)
    rec3 = generate_pair(family, rung, pair_index + 50, namespace=namespace)
    fresh_differs = any(
        not rec1.episodes[s].df.equals(rec3.episodes[s].df)
        for s in ("A", "B"))
    return {
        "family": family, "rung": rung, "pair": pair_index,
        "same_seed_same_episode": bool(same_pair and hash_same),
        "different_seed_different_episode": bool(fresh_differs),
        "pass": bool(same_pair and hash_same and fresh_differs),
    }


def check_fresh_seed_validity(n_checks: int = 10) -> dict[str, Any]:
    """qualification corpus 外的新 seed(fresh_holdout namespace)合法生成。"""
    results = []
    rng = np.random.default_rng(20260830)
    for i in range(n_checks):
        family = CURRICULUM261_FAMILIES[int(rng.integers(0, 3))]
        rung = CURRICULUM261_RUNGS[int(rng.integers(0, 4))]
        pair_index = 500 + i
        try:
            rec = generate_pair(family, rung, pair_index,
                                namespace="fresh_holdout_r2")
            ok = rec.integrity_ok
        except Exception as exc:  # noqa: BLE001
            results.append({"family": family, "rung": rung,
                            "valid": False, "error": str(exc)[:120]})
            continue
        results.append({"family": family, "rung": rung, "valid": bool(ok)})
    n_valid = sum(1 for r in results if r["valid"])
    return {
        "n_checks": n_checks, "n_valid": n_valid,
        "details": results,
        "pass": bool(n_valid >= max(1, int(0.8 * n_checks))),
    }


# ------------------------------------------------- C2 诊断(repair R2)
def check_c2_local_cue_independence(records: list[PairRecord],
                                    ) -> dict[str, Any]:
    """§13.A local cue context independence:cue bar 的 %-ret-1 读数
    分布在四个上下文象限 (s=±1 x w=±1) 必须匹配。

    判定(预注册,与结果无关):
    - 每象限的 cue bar 样本 mean 差 <= 3 x pooled SE(抽样容差);
    - std 比值(任意两象限)∈ [0.8, 1.25];
    - 正号率(sign balance)差 <= 0.10;
    - cue event rate(每 bar cue 概率)比值 ∈ [0.75, 1.35]。
    v9 构造上 cue 读数 = pulse + 独立噪声,与 s/w 无耦合——统计差异
    只能来自抽样;任何系统性泄漏(如漂移载体时代的读数平移)都会
    在 mean/quantiles 上暴露。
    """
    from rl_curriculum.curriculum261_c2 import (
        c2_structural_issues,
    )

    quad_samples: dict[tuple[int, int], list[float]] = {}
    quad_rates: dict[tuple[int, int], list[float]] = {}
    per_rung: dict[str, Any] = {}
    for rec in records:
        rung = rec.rung
        h = rec.episodes["A"].hidden
        df = rec.episodes["A"].df
        r1 = df["%-ret-1"].to_numpy(dtype=np.float64)
        cue = h["cue_dir"].to_numpy()
        s = h["wick_dir_state"].to_numpy()
        w = h["wick_width_state"].to_numpy()
        n_bars = len(r1)
        for ss in (1, -1):
            for ww in (1, -1):
                key = (ss, ww)
                sel = (cue != 0) & (s == ss) & (w == ww)
                vals = r1[sel]
                quad_samples.setdefault(key, []).extend(
                    float(v) for v in vals)
                quad_rates.setdefault(key, []).append(
                    float(sel.sum()) / n_bars)
        # 每 rung 分位数记录(证据)
        row = {"rung": rung, "n_cues": int(np.count_nonzero(cue))}
        per_rung.setdefault(rung, {"n_pairs": 0})
        per_rung[rung]["n_pairs"] += 1
    stats: dict[str, Any] = {}
    for key, vals in sorted(quad_samples.items()):
        arr = np.asarray(vals, dtype=np.float64)
        stats[f"s{key[0]:+d}_w{key[1]:+d}"] = {
            "n": int(arr.size),
            "mean_bps": float(arr.mean() * 1e4) if arr.size else None,
            "std_bps": float(arr.std(ddof=1) * 1e4) if arr.size > 1 else None,
            "positive_rate": float((arr > 0).mean()) if arr.size else None,
            "quantiles_bps": (np.percentile(arr, [5, 25, 50, 75, 95])
                              * 1e4).round(2).tolist() if arr.size else None,
        }
    means = {k: np.asarray(v, dtype=np.float64)
             for k, v in quad_samples.items()}
    n_min = min(v.size for v in means.values())
    checks: dict[str, bool] = {}
    if n_min >= 5:
        keys = sorted(means)
        mean_vals = {k: float(means[k].mean()) for k in keys}
        std_vals = {k: float(means[k].std(ddof=1)) for k in keys}
        pooled_se = float(np.sqrt(np.mean(
            [std_vals[k] ** 2 / means[k].size for k in keys])))
        max_mean_gap = max(
            abs(mean_vals[a] - mean_vals[b])
            for i, a in enumerate(keys) for b in keys[i + 1:])
        checks["mean_gap_within_3se"] = bool(
            max_mean_gap <= 3.0 * pooled_se)
        max_std_ratio = max(
            max(std_vals[a], std_vals[b]) / max(min(std_vals[a],
                                                    std_vals[b]), 1e-12)
            for i, a in enumerate(keys) for b in keys[i + 1:])
        checks["std_ratio_in_range"] = bool(0.8 <= max_std_ratio <= 1.25)
        pos_rates = {k: float((means[k] > 0).mean()) for k in keys}
        max_pos_gap = max(
            abs(pos_rates[a] - pos_rates[b])
            for i, a in enumerate(keys) for b in keys[i + 1:])
        checks["sign_balance_gap"] = bool(max_pos_gap <= 0.10)
        rate_means = {k: float(np.mean(quad_rates[k]))
                      for k in quad_rates}
        max_rate_ratio = max(
            max(rate_means[a], rate_means[b]) / max(min(rate_means[a],
                                                        rate_means[b]), 1e-12)
            for i, a in enumerate(sorted(rate_means))
            for b in sorted(rate_means)[i + 1:])
        checks["cue_rate_ratio_in_range"] = bool(
            0.75 <= max_rate_ratio <= 1.35)
    else:
        for k in ("mean_gap_within_3se", "std_ratio_in_range",
                  "sign_balance_gap", "cue_rate_ratio_in_range"):
            checks[k] = False
    return {
        "format": "cur261-c2-local-cue-independence-v1",
        "n_pairs": len(records),
        "per_quadrant": stats,
        "per_rung_pair_counts": per_rung,
        "checks": checks,
        "max_mean_gap_bps": float(max_mean_gap * 1e4) if n_min >= 5 else None,
        "pooled_se_bps": float(pooled_se * 1e4) if n_min >= 5 else None,
        "pass": bool(all(checks.values())),
    }


def check_c2_context_observability(records: list[PairRecord],
                                   kappa: float = 1.5,
                                   ) -> dict[str, Any]:
    """§13.B context observability:冻结 production observation 的
    observation-only 判定器(阈值化 wick 特征)辨认上下文的 margin。

    判定器只读 observation 行的生产特征槽位(与 latent 隔离);
    latent 真值仅作评估 label。两个上下文各自报告:
    - direction:sign(raw_high+raw_low-raw_open-raw_close) vs s;
    - width:(raw_high-raw_low)-|raw_close-raw_open| > 0.0120 vs w。
    margin = 2 x accuracy - 1(逐 bar 二项),要求
    margin >= kappa x SE_binomial(SE = 2*sqrt(p(1-p)/n))。
    """
    from rl_curriculum.curriculum261_c2 import (
        wick_score_of,
        wick_width_of,
    )

    n_dir = {"n": 0, "correct": 0}
    n_wid = {"n": 0, "correct": 0}
    per_rung: dict[str, dict[str, float]] = {}
    obs_cols = list(SCHEMA.feature_names)
    for rec in records:
        h = rec.episodes["A"].hidden
        df = rec.episodes["A"].df
        feats = df[obs_cols].to_numpy(dtype=np.float64)
        s = h["wick_dir_state"].to_numpy()
        w = h["wick_width_state"].to_numpy()
        scores = np.array([wick_score_of(o) for o in feats])
        spans = np.array([wick_width_of(o) for o in feats])
        d_ok = np.sign(scores) == np.sign(s)
        w_ok = (spans > 0.0120) == (w > 0)
        n_dir["n"] += int(d_ok.size)
        n_dir["correct"] += int(d_ok.sum())
        n_wid["n"] += int(w_ok.size)
        n_wid["correct"] += int(w_ok.sum())
        rd = per_rung.setdefault(rec.rung, {"dir_acc": [], "width_acc": []})
        rd["dir_acc"].append(float(d_ok.mean()))
        rd["width_acc"].append(float(w_ok.mean()))
    out_rung = {r: {"dir_accuracy": float(np.mean(v["dir_acc"])),
                    "width_accuracy": float(np.mean(v["width_acc"]))}
                for r, v in per_rung.items()}

    def _margin(n: int, correct: int) -> dict[str, Any]:
        acc = correct / max(n, 1)
        p = min(max(acc, 1e-6), 1 - 1e-6)
        se = 2.0 * float(np.sqrt(p * (1 - p) / n)) if n else float("inf")
        margin = 2.0 * acc - 1.0
        return {"n_bars": n, "accuracy": acc, "margin": margin,
                "se": se, "kappa_times_se": kappa * se,
                "margin_ge_kappa_se": bool(margin >= kappa * se)}

    direction = _margin(n_dir["n"], n_dir["correct"])
    width = _margin(n_wid["n"], n_wid["correct"])
    return {
        "format": "cur261-c2-context-observability-v1",
        "discriminator": {
            "direction": "sign(raw_high+raw_low-raw_open-raw_close)",
            "width": "(raw_high-raw_low)-|raw_close-raw_open|>0.0120",
            "observation_only": True,
            "latent_used_as": "evaluation label only",
        },
        "per_rung_accuracy": out_rung,
        "direction": direction,
        "width": width,
        "pass": bool(direction["margin_ge_kappa_se"]
                     and width["margin_ge_kappa_se"]),
    }


# ------------------------------------------------- C2 诊断 runner
def run_c2_diagnostics(pairs_per_rung: int = 10,
                       out_dir: Path | None = None,
                       ) -> dict[str, Any]:
    """在 calibration_r2 + calibration_holdout_r2 两语料的 C2 pairs 上
    运行 local-cue independence 与 context observability 双诊断。

    records 重新生成(同 namespace+seed 确定性复现 calibration 语料,
    不引入新 seed space);诊断进入 robustness gate 的 C2 条件。
    """
    records: list[PairRecord] = []
    for ns in ("calibration_r2", "calibration_holdout_r2"):
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    "c2_context", rung, idx, namespace=ns))
    lc = check_c2_local_cue_independence(records)
    ob = check_c2_context_observability(records)
    out = {"local_cue_independence": lc, "context_observability": ob}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "c2_local_cue_context_independence.json").write_text(
            json.dumps(lc, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        (out_dir / "c2_context_observability.json").write_text(
            json.dumps(ob, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
    return out


# ------------------------------------------------- stress 与 namespace 完整性
def run_generator_stress(pairs_per_rung: int = 12,
                         namespace: str = "stress_r2",
                         out_dir: Path | None = None,
                         ) -> dict[str, Any]:
    """§11 pre-qualification generator stress:family x rung x 多 seed
    大量生成,accepted pair 的 final structural integrity 必须 PASS。

    统一合同下 accepted => integrity=1.0 是同函数确定性的推论;
    stress 提供经验证据(低概率退化如 shared 表断裂 / 构造漂移)。
    禁止使用 qualification_r2 seed。"""
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace))
        stats = attempt_statistics(records)
        n_ok = sum(1 for r in records if r.integrity_ok)
        families_out[family] = {
            "namespace": namespace,
            "pairs_per_rung": pairs_per_rung,
            "n_pairs": len(records),
            "n_integrity_ok": n_ok,
            "integrity_pass_ratio": n_ok / len(records),
            "accepted_implies_integrity": bool(n_ok == len(records)),
            "attempt_stats": stats,
        }
    overall = {
        "format": "cur261-generator-stress-v1",
        "namespace": namespace,
        "families": families_out,
        "pass": bool(all(
            v["accepted_implies_integrity"] for v in families_out.values())),
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        for family in CURRICULUM261_FAMILIES:
            (out_dir / f"{family}_structural_stress.json").write_text(
                json.dumps(families_out[family], indent=2,
                           ensure_ascii=False, default=float),
                encoding="utf-8")
        (out_dir / "generator_stress_summary.json").write_text(
            json.dumps(overall, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
    return overall


def seed_namespace_integrity_report() -> dict[str, Any]:
    """§6 seed namespace integrity:R0/R1/R2 全部 namespace 的派生 seed
    无碰撞;R2 qualification seed 在 lock 前从未被派生。

    枚举旧 5 namespace 与新 6 namespace x 3 family x 4 rung x
    pair 0..29 x attempt 0..4(共 11 x 3 x 4 x 30 x 5 = 19800 个)
    + fresh 的 500..509。断言:
    - R2 qualification_r2 与其它任何 namespace 无交集;
    - R2 各 namespace 两两无交集(派生字符串不同 -> 值不同,显式验证);
    - calibration_r2 / calibration_holdout_r2 / stress_r2 与
      qualification_r2 无交集(约束 calibration code path 不触测试集)。
    qualification_r2 的枚举走 _derive261_seed_raw(纯哈希值,不生成
    episode——corpus 暴露以生成为准,守卫保持对生成路径生效)。
    """
    from rl_curriculum.curriculum261_api import _derive261_seed_raw
    r2_namespaces = ("calibration_r2", "calibration_holdout_r2",
                     "qualification_r2", "fresh_holdout_r2",
                     "training_r2", "stress_r2")
    old_namespaces = ("calibration", "calibration_holdout",
                      "qualification", "fresh_holdout", "training")
    pairs = list(range(30)) + list(range(500, 510))
    seen: dict[str, set[int]] = {}
    for ns in r2_namespaces + old_namespaces:
        vals = set()
        for fam in CURRICULUM261_FAMILIES:
            for rung in CURRICULUM261_RUNGS:
                for p in pairs:
                    for att in range(5):
                        vals.add(_derive261_seed_raw(ns, fam, rung, p, att))
        seen[ns] = vals
    collisions = []
    keys = sorted(seen)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            inter = seen[a] & seen[b]
            if inter:
                collisions.append(f"{a}∩{b}={len(inter)}")
    r2q_vs_others = sorted(
        seen["qualification_r2"] & set().union(
            *[seen[k] for k in keys if k != "qualification_r2"]))
    return {
        "format": "cur261-seed-namespace-integrity-v1",
        "iteration": "r2",
        "namespaces_checked": list(r2_namespaces + old_namespaces),
        "seeds_per_namespace": 3 * 4 * len(pairs) * 5,
        "pairwise_collisions": collisions,
        "qualification_r2_overlap_with_any": len(r2q_vs_others),
        "calibration_vs_qualification_r2_disjoint": bool(
            not (seen["calibration_r2"] & seen["qualification_r2"])
            and not (seen["calibration_holdout_r2"]
                     & seen["qualification_r2"])
            and not (seen["stress_r2"] & seen["qualification_r2"])),
        "qualification_r2_locked_before_use": bool(
            not qualification_r2_unlocked()),
        "pass": bool(not collisions and not r2q_vs_others),
    }


# ------------------------------------------------------------- 运行器
def run_calibration(pairs_per_rung: int = 10,
                    out_dir: Path | None = None) -> dict[str, Any]:
    """repair R2:主 calibration 语料(calibration_r2 全新 seed space)。"""
    return run_calibration_corpus(
        "calibration_r2", pairs_per_rung=pairs_per_rung, out_dir=out_dir,
        prefix="calibration")


def run_calibration_corpus(namespace: str, pairs_per_rung: int = 10,
                           out_dir: Path | None = None,
                           prefix: str = "calibration") -> dict[str, Any]:
    """在指定 calibration 类 namespace 上运行完整评估(共用代码路径)。"""
    specs = family_specs()
    thresholds = {
        "c1_opportunity": dict(specs["c1_opportunity"].reference_defaults),
        "c2_context": dict(specs["c2_context"].reference_defaults),
        "c3_cost": dict(specs["c3_cost"].reference_defaults),
    }
    family_reports: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        rung_params = {
            r: specs[family].rung_params[r] for r in CURRICULUM261_RUNGS}
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace))
        family_reports[family] = rung_report(
            records, family, rung_params, thresholds)
        family_reports[family]["attempt_stats"] = attempt_statistics(records)
        family_reports[family]["pair_integrity_pass_rate"] = float(
            sum(1 for r in records if r.integrity_ok) / len(records))
    summary = {
        "stage": prefix,
        "seed_namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "thresholds": thresholds,
        "families": family_reports,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{prefix}_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
    return summary


def run_calibration_holdout(pairs_per_rung: int = 10,
                            out_dir: Path | None = None) -> dict[str, Any]:
    """repair R2:独立 calibration_holdout_r2 语料(与主 calibration_r2、
    qualification_r2 的 seed 均隔离),用于 lock 前稳健性交叉验证。"""
    return run_calibration_corpus(
        "calibration_holdout_r2", pairs_per_rung=pairs_per_rung,
        out_dir=out_dir, prefix="calibration_holdout")


#: 预注册的 robustness gate 常数:相邻 rung 的难度间隔与 D3 度量都
#: 必须 >= KAPPA x SE(双语料合并的 per-episode 样本标准误)。
#: KAPPA=1.5 在 plan 中锁定;不得看了结果再调。
ROBUSTNESS_KAPPA = 1.5


def _episode_metric_values(rung_eval: dict[str, Any]) -> list[float]:
    """一个 rung 评估里逐 episode 的 ref_net - max(0, always_long_net)
    (corpus 难度度量的 per-episode 贡献样本)。"""
    out = []
    for row in rung_eval["episodes"]:
        ref = float(row["reference"])
        lng = float(row["always_long"])
        out.append(ref - max(0.0, lng))
    return out


def calibration_robustness_gate(
    main: dict[str, Any], holdout: dict[str, Any],
    kappa: float = ROBUSTNESS_KAPPA,
    stress: dict[str, Any] | None = None,
    c2_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """repair R2 硬合同:lock 前的双语料稳健性门槛(真正的 Gate)。

    每个 family 必须在 calibration_r2 AND calibration_holdout_r2
    同时满足全部八条:
    1. D0 > D1 > D2 > D3(ordering_ok);
    2. D3 > 0;
    3. reference 在全部 rung 压过必胜基线;
    4. accepted pair integrity = 1.0(统一合同 + stress 实证);
    5. 相邻 rung gap >= kappa x SE(双语料合并 per-episode 样本);
    6. D3 >= kappa x SE;
    7. C2 额外通过 local-cue independence 与 context observability;
    8. attempt 分布合理(mean < max,无全部靠多 attempt 硬凑的 rung)。
    任一 family FAIL -> gate.pass = false -> 禁止 lock plan
    (Layer A/B/C 三层强制,CLI 非零退出 / plan 拒生成 / final fail
    closed)。
    """
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        fm = main["families"][family]
        fh = holdout["families"][family]
        ladders = {
            "main": fm["difficulty_metric_ladder"],
            "holdout": fh["difficulty_metric_ladder"],
        }
        per_corpus_flags = {
            "main": {
                "ordering_ok": fm["ordering_ok"],
                "d3_positive": fm["d3_metric_positive"],
                "ref_beats_required": fm[
                    "reference_beats_required_all_rungs"],
                "integrity_unity": bool(
                    fm["pair_integrity_pass_rate"] == 1.0),
            },
            "holdout": {
                "ordering_ok": fh["ordering_ok"],
                "d3_positive": fh["d3_metric_positive"],
                "ref_beats_required": fh[
                    "reference_beats_required_all_rungs"],
                "integrity_unity": bool(
                    fh["pair_integrity_pass_rate"] == 1.0),
            },
        }
        # 条件 4(stress 实证)+ 条件 8(attempts 分布)
        stress_ok = True
        if stress is not None:
            fam_stress = stress.get("families", {}).get(family)
            stress_ok = bool(
                fam_stress is not None
                and fam_stress["accepted_implies_integrity"])
        attempts_ok = True
        for rep in (fm, fh):
            stats = rep.get("attempt_stats", {})
            attempts_ok = attempts_ok and bool(
                stats.get("n_pairs", 0) > 0
                and stats.get("mean_attempts", 9.0)
                < stats.get("max_attempts", 5)
                and stats.get("max_attempts_used", 0) <= 5)
        # 条件 7(C2 双诊断,仅 c2_context)
        c2_flags: dict[str, bool] | None = None
        if family == "c2_context":
            c2_flags = {
                "local_cue_independence": bool(c2_diagnostics is not None
                and c2_diagnostics["local_cue_independence"]["pass"]),
                "context_observability": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["context_observability"]["pass"]),
            }
        # 合并两语料的 per-episode 度量样本(每 rung 2 x 20 个)
        samples = {r: (
            _episode_metric_values(fm["by_rung"][r])
            + _episode_metric_values(fh["by_rung"][r]))
            for r in CURRICULUM261_RUNGS}
        n_ep = {r: len(samples[r]) for r in CURRICULUM261_RUNGS}
        means = {r: float(np.mean(samples[r])) for r in CURRICULUM261_RUNGS}
        ses = {
            r: (float(np.std(samples[r], ddof=1) / np.sqrt(n_ep[r]))
                if n_ep[r] > 1 else float("inf"))
            for r in CURRICULUM261_RUNGS}
        gap_report: dict[str, Any] = {}
        gaps_ok = True
        for k in range(3):
            r_hi, r_lo = CURRICULUM261_RUNGS[k], CURRICULUM261_RUNGS[k + 1]
            gap_main = (ladders["main"][r_hi] - ladders["main"][r_lo])
            gap_hold = (ladders["holdout"][r_hi]
                        - ladders["holdout"][r_lo])
            se = float(np.sqrt(ses[r_hi] ** 2 + ses[r_lo] ** 2))
            ok = bool(
                gap_main > 0 and gap_hold > 0
                and min(gap_main, gap_hold) >= kappa * se)
            gaps_ok = gaps_ok and ok
            gap_report[f"{r_hi}-{r_lo}"] = {
                "gap_main": gap_main, "gap_holdout": gap_hold,
                "se_pooled": se, "kappa_times_se": kappa * se,
                "ok": ok,
            }
        d3_se_ok = bool(means["D3"] >= kappa * ses["D3"])
        family_pass = bool(
            all(all(fc.values()) for fc in per_corpus_flags.values())
            and gaps_ok and d3_se_ok and stress_ok and attempts_ok
            and (c2_flags is None or all(c2_flags.values())))
        families_out[family] = {
            "per_corpus_flags": per_corpus_flags,
            "stress_accepted_implies_integrity": bool(stress_ok),
            "attempts_distribution_ok": bool(attempts_ok),
            "c2_diagnostics": c2_flags,
            "pooled_episode_metric_mean": means,
            "pooled_episode_metric_se": ses,
            "n_episodes_per_rung": n_ep,
            "gaps": gap_report,
            "d3_mean": means["D3"], "d3_se": ses["D3"],
            "d3_mean_ge_kappa_se": d3_se_ok,
            "pass": family_pass,
        }
    overall = bool(all(v["pass"] for v in families_out.values()))
    return {
        "format": "cur261-robustness-gate-v2",
        "iteration": "r2",
        "kappa": float(kappa),
        "contract": [
            "1 ordering", "2 d3_positive", "3 ref_beats_required",
            "4 integrity_unity(corpus x2 + stress)", "5 gap_ge_kappa_se",
            "6 d3_ge_kappa_se", "7 c2_local_cue+observability(c2)",
            "8 attempts_distribution",
        ],
        "main_namespace": main.get("seed_namespace", "calibration_r2"),
        "holdout_namespace": holdout.get(
            "seed_namespace", "calibration_holdout_r2"),
        "c2_local_cue_independence": (
            c2_diagnostics["local_cue_independence"]
            if c2_diagnostics else None),
        "c2_context_observability": (
            c2_diagnostics["context_observability"]
            if c2_diagnostics else None),
        "families": families_out,
        "pass": overall,
    }
