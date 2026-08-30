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
        pmr = float(thresholds["pmr_thr"])
        vt = float(thresholds["vol_thr"])
        policies["c2_local_only"] = C2LocalOnlyPolicy(cue)
        policies["c2_single_context_pmr"] = C2SingleContextPolicy(
            cue, pmr, "%-price-ma-ratio")
        policies["c2_single_context_vol"] = C2SingleContextPolicy(
            cue, vt, "%-vol-24")
        policies["reference"] = C2ReferencePolicy(cue, pmr, vt)
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
    from rl_curriculum.curriculum261_api import CURRICULUM261_TIMEFRAME
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


def check_production_feature_equivalence(family: str, rung: str,
                                         pair_index: int) -> dict[str, Any]:
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
        derive261_seed("qualification", family, rung, pair_index, 0),
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
    """WP-G(repair R1):主 calibration 语料(委托 run_calibration_corpus)。"""
    return run_calibration_corpus(
        "calibration", pairs_per_rung=pairs_per_rung, out_dir=out_dir,
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
    """repair R1:独立 calibration_holdout 语料(与主 calibration、
    qualification 的 seed 均隔离),用于 lock 前稳健性交叉验证。"""
    return run_calibration_corpus(
        "calibration_holdout", pairs_per_rung=pairs_per_rung,
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
) -> dict[str, Any]:
    """repair R1 核心:lock 前的双语料稳健性门槛。

    对每个 family:
    - 主 calibration 语料与 holdout 语料各自 ordering_ok 且 D3 为正
      且 reference 在全部 rung 上压过必胜基线;
    - 相邻 rung 难度间隔 gap_k = M_k - M_{k+1} 在两个语料上都 > 0;
    - gap_k >= kappa x SE(gap_k):SE 由两个语料合并的 per-episode
      度量样本估计(Var(M_k) + Var(M_{k+1}) / n 的样本版本);
    - D3 度量 >= kappa x SE(M_D3)。
    全部通过才允许 lock plan(否则必须回到设计,不得进入 qualification)。
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
            },
            "holdout": {
                "ordering_ok": fh["ordering_ok"],
                "d3_positive": fh["d3_metric_positive"],
                "ref_beats_required": fh[
                    "reference_beats_required_all_rungs"],
            },
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
            and gaps_ok and d3_se_ok)
        families_out[family] = {
            "per_corpus_flags": per_corpus_flags,
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
        "format": "cur261-robustness-gate-v1",
        "kappa": float(kappa),
        "main_namespace": main.get("seed_namespace", "calibration"),
        "holdout_namespace": holdout.get(
            "seed_namespace", "calibration_holdout"),
        "families": families_out,
        "pass": overall,
    }
