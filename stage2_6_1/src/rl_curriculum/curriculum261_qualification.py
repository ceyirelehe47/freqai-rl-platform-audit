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
    curriculum261_observation_schema,
    derive261_seed,
    episode_content_hash,
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
from rl_curriculum.evaluator import run_policy_episode
from rl_curriculum.policies import AlwaysFlatPolicy, AlwaysLongPolicy

SCHEMA = curriculum261_observation_schema()
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
        h1 = float(thresholds["htf1_thr"])
        vt = float(thresholds["vol_thr"])
        policies["c2_local_only"] = C2LocalOnlyPolicy(cue)
        policies["c2_single_context_htf_1h_mom"] = C2SingleContextPolicy(
            cue, h1, "htf_1h_mom")
        policies["c2_single_context_vol_24"] = C2SingleContextPolicy(
            cue, vt, "vol_24")
        policies["reference"] = C2ReferencePolicy(cue, h1, vt)
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
def check_observation_causality(family: str, rung: str,
                                pair_index: int) -> dict[str, Any]:
    """未来噪声变异:变异起点前的 observation 必须逐位不变。"""
    spec = family_specs()[family]
    rung_params = dict(spec.rung_params[rung])
    rung_params["cur261_rung"] = rung
    gen = spec.generator
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_TIMEFRAME, attach_curriculum261_features)
    from rl_curriculum.evaluator import select_features_strict

    base_params = gen.base_params(rung_params, "A")
    cut = 150
    ep_base = gen.generate(base_params, derive261_seed(
        "qualification", family, rung, pair_index, 0),
        split="curriculum261_causality", timeframe=CURRICULUM261_TIMEFRAME)
    mut_params = dict(base_params)
    mut_params["noise_mutate_from"] = cut
    mut_params["noise_mutate_salt"] = 20260830
    ep_mut = gen.generate(mut_params, derive261_seed(
        "qualification", family, rung, pair_index, 0),
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


def check_htf_resample_equivalence(family: str, rung: str,
                                   pair_index: int) -> dict[str, Any]:
    """htf_1h_mom 在整点对齐处与 pandas 1h resample 的因果等价性。"""
    from rl_curriculum.curriculum261_api import CURRICULUM261_TIMEFRAME
    spec = family_specs()[family]
    rung_params = dict(spec.rung_params[rung])
    rung_params["cur261_rung"] = rung
    ep = spec.generator.generate(
        spec.generator.base_params(rung_params, "A"),
        derive261_seed("qualification", family, rung, pair_index, 0),
        split="curriculum261_causality", timeframe=CURRICULUM261_TIMEFRAME)
    df = ep.df.set_index("date")
    h1 = df["htf_1h_mom"].to_numpy(dtype=np.float64)
    close_1h = df["close"].resample("1h").last()
    r6 = (np.log(close_1h).diff(6).dropna()).to_numpy()
    # 对齐:15m index t 对应 1h bar j = (t+1)//4 - 1;
    # htf_1h_mom[t] = log(close_t / close_{t-24});当 t+1 是 4 的倍数时,
    # 窗口恰好覆盖 6 根完整 1h bar
    ok, checked = True, 0
    for t in range(24, len(df)):
        if (t + 1) % 4 != 0:
            continue
        j = (t + 1) // 4 - 1  # 最新的完整 1h bar 索引
        if j - 6 < 0 or j >= len(r6) + 6:
            continue
        if j - 6 >= 0 and (j - 6) < len(r6):
            ref = r6[j - 6]
            if not np.isclose(h1[t], ref, rtol=0, atol=1e-12):
                ok = False
            checked += 1
    return {
        "family": family, "rung": rung, "pair": pair_index,
        "aligned_bars_checked": checked,
        "equivalent_to_resample": bool(ok and checked >= 20),
        "pass": bool(ok and checked >= 20),
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
                                namespace="fresh_holdout")
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


# ------------------------------------------------------------- 运行器
def run_calibration(pairs_per_rung: int = 10,
                    out_dir: Path | None = None) -> dict[str, Any]:
    """WP-G:在 calibration namespace 上运行完整评估(可迭代调参)。"""
    specs = family_specs()
    thresholds = {
        "c1_opportunity": dict(specs["c1_opportunity"].reference_defaults),
        "c2_context": dict(specs["c2_context"].reference_defaults),
        "c3_cost": dict(specs["c3_cost"].reference_defaults),
    }
    family_reports: dict[str, Any] = {}
    all_records: dict[str, list[PairRecord]] = {}
    for family in CURRICULUM261_FAMILIES:
        rung_params = {
            r: specs[family].rung_params[r] for r in CURRICULUM261_RUNGS}
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace="calibration"))
        all_records[family] = records
        family_reports[family] = rung_report(
            records, family, rung_params, thresholds)
        family_reports[family]["attempt_stats"] = attempt_statistics(records)
        family_reports[family]["pair_integrity_pass_rate"] = float(
            sum(1 for r in records if r.integrity_ok) / len(records))
    summary = {
        "stage": "calibration",
        "seed_namespace": "calibration",
        "pairs_per_rung": pairs_per_rung,
        "thresholds": thresholds,
        "families": family_reports,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "calibration_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        raw = {fam: [r.canonical() for r in recs]
               for fam, recs in all_records.items()}
        (out_dir / "calibration_raw.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
    return summary
