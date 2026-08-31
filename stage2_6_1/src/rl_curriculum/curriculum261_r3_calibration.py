"""阶段 2.6.1 Repair R3:预处理 calibration、supervised gate 与双层
robustness gate(WP-E/F/G/H)。

§17 fit bank 与 evaluation bank 完全隔离:
- preprocess_fit_calibration_r3 / preprocess_fit_holdout_r3 /
  preprocess_fit_qualification_r3:每 bank 3 family x 4 rung x
  4 pairs x A/B = 96 episodes,只用于拟合 preprocessor,不进入任何
  qualification metric;
- calibration_r3 / calibration_holdout_r3:正式课程 calibration 语料
  (每 family/rung 10 pairs),评估用(scaled episodes + wrapped
  reference)。

§7 统一 fit/冻结协议:一个训练 run -> 一个完整 training episode
multiset -> 一个统一 preprocessor -> C1/C2/C3 全部共享。fit 于
multiset 的全部 policy-visible feature rows(position slot 不参与),
fit 后冻结;staged/mixed 同 multiset 必得同一 fitted state(row 序
不敏感,回归测试证明)。

§23 pair-cluster statistical contract:一个 A/B pair = 一个 cluster;
mean/SE/bootstrap/adjacent-rung gap/D3 margin 全部 pair-level 聚合,
禁止把 A/B 当独立样本。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
    curriculum261_eval_config,
)
from rl_curriculum.curriculum261_pairs import (
    PairRecord,
    attempt_statistics,
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    production_observation_schema,
)
from rl_curriculum.curriculum261_qualification import (
    REQUIRED_BASELINES,
    build_oracle,
    build_policy_set,
)
from rl_curriculum.curriculum261_r3_namespaces import (
    CURRICULUM261_ITERATION_ID_R3,
)
from rl_curriculum.curriculum261_r3_obs import (
    PreprocessingAwarePolicy,
    reference_equivalence_check,
    r3_observation_schema,
    scaled_episode,
    validate_observation_containment,
    wrap_policy_set,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
)
from rl_curriculum.evaluator import run_policy_episode

EVAL_CFG = curriculum261_eval_config()
RAW_SCHEMA = production_observation_schema()

#: fit bank 规模(§17:3 family x 4 rung x 4 pairs x A/B)。
FIT_BANK_PAIRS_PER_RUNG = 4

#: calibration 语料规模(与 R2 相同:pairs/rung/family)。
CALIBRATION_PAIRS_PER_RUNG = 10

#: 预注册 kappa(与 R2 相同;pair-cluster SE 口径下沿用)。
ROBUSTNESS_KAPPA_R3 = 1.5

#: 预注册 conditioning gate 常数(§19;calibration 前 a priori 锁定,
#: 不得看 final 结果调整)。8 列中 4 列 raw OHLC:均匀贡献下份额 0.5;
#: unscaled(R2 诊断)实测约 98%。阈值取 0.60(允许 20% 相对富余)。
CONDITIONING_GATE = {
    "raw_ohlc_contribution_share_max": 0.60,
    "tanh_saturation_rate_max": 0.05,
    "near_zero_scaled_variance": "forbidden (variance > 1e-12)",
    "eval_out_of_fit_range_rate_max": 0.10,
}

#: 预注册 supervised gate 常数(§20:每 family 至少 2/3 seeds 达标)。
SUPERVISED_GATE = {
    "min_seeds_passing": 2,
    "n_model_seeds": 3,
    "heldout_balanced_accuracy_min": 0.60,
    "behavior_gap_min": 0.20,
    "mlp_arch": [128, 128],
    "gated_controls": ["W", "B"],
    "unweighted_control": "U (diagnostic only, not gated; all families)",
    "imbalance_rationale": "C1/C2/C3 Long rate 4-8%; W/B controls are"
                           " gated for all families (262 R2 family-aware"
                           " supervised precedent)",
}

#: supervised model seeds(预注册)。
SUPERVISED_MODEL_SEEDS = (20260901, 20260902, 20260903)


# ------------------------------------------------------------ fit bank
def generate_fit_bank(namespace: str,
                      pairs_per_rung: int = FIT_BANK_PAIRS_PER_RUNG,
                      ) -> list[PairRecord]:
    """生成一个 preprocessing fit bank(3 family x 4 rung x N pair)。"""
    records: list[PairRecord] = []
    for family in CURRICULUM261_FAMILIES:
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace))
    return records


def fit_matrix_from_records(records: list[PairRecord]) -> pd.DataFrame:
    """fit bank 的全部 policy-visible feature rows(8 列,行序无关)。

    position slot 不参与 fit;每 episode 取全部行(288 bars)。
    """
    frames = []
    for rec in records:
        for side in ("A", "B"):
            df = rec.episodes[side].df
            frames.append(df[list(PRODUCTION_FEATURE_COLUMNS)]
                          .astype(np.float64))
    return pd.concat(frames, ignore_index=True)


def fit_preprocessor_from_bank(
    namespace: str, pairs_per_rung: int = FIT_BANK_PAIRS_PER_RUNG,
) -> tuple[RouteCPreprocessor, dict[str, Any]]:
    """生成 fit bank -> 统一 fit -> 冻结(offline corpus fit 协议)。"""
    records = generate_fit_bank(namespace, pairs_per_rung)
    fit_df = fit_matrix_from_records(records)
    preproc = RouteCPreprocessor.build_and_fit(fit_df)
    manifest = {
        "namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "n_pairs": len(records),
        "n_episodes": 2 * len(records),
        "n_rows": int(len(fit_df)),
        "columns": list(PRODUCTION_FEATURE_COLUMNS),
        "integrity_all_ok": bool(all(r.integrity_ok for r in records)),
        "state_hash": preproc.state_hash(),
    }
    return preproc, manifest


# ------------------------------------------------- R3 课程 corpus 评估
def evaluate_pair_corpus_r3(
    records: list[PairRecord], family: str, rung_params: dict[str, Any],
    thresholds: dict[str, Any], preproc: RouteCPreprocessor,
) -> dict[str, Any]:
    """R3 正式评估:wrapped reference/baseline on scaled episodes。

    与 R2 evaluate_pair_corpus 相同的 policy 集,但:
    - observation-aware 策略经 PreprocessingAwarePolicy 包装(方式 B);
    - env 特征列为 frozen preprocessor transform 输出;
    - oracle 走 sidecar(raw episode,不受 preprocessing 影响);
    - 逐 episode 行保留 side/pair 元数据(pair-cluster 统计输入)。
    """
    raw_set = build_policy_set(family, rung_params, thresholds)
    policies = wrap_policy_set(raw_set, preproc)
    oracle = build_oracle(family)
    schema = r3_observation_schema(preproc)
    per_episode: list[dict[str, Any]] = []
    for rec in records:
        for side in ("A", "B"):
            ep = rec.episodes[side]
            scaled_ep = scaled_episode(ep, preproc)
            row: dict[str, Any] = {
                "rung": rec.rung, "pair": rec.pair_index, "side": side,
                "episode_hash": rec.attempt_log.episode_hashes[side],
            }
            for name, pol in policies.items():
                r = run_policy_episode(pol, scaled_ep, EVAL_CFG, schema)
                row[name] = float(r.net_return)
                row[f"{name}_trades"] = int(r.n_trades)
            ro = run_policy_episode(oracle, ep, EVAL_CFG, RAW_SCHEMA)
            row["oracle"] = float(ro.net_return)
            per_episode.append(row)

    # pair-cluster 聚合(§23:pair = cluster,A/B 均值为 pair 样本)
    names = list(policies.keys()) + ["oracle"]
    pair_values: dict[str, dict[int, list[float]]] = {
        n: {} for n in names}
    for row in per_episode:
        for n in names:
            pair_values[n].setdefault(int(row["pair"]), []).append(
                float(row[n]))
    pair_mean = {
        n: {p: float(np.mean(v)) for p, v in pv.items()}
        for n, pv in pair_values.items()}
    cluster_means = {n: float(np.mean(list(pm.values())))
                     for n, pm in pair_mean.items()}

    def _difficulty(pm: dict[int, float]) -> float:
        best_const = max(0.0, cluster_means["always_long"])
        return float(np.mean([
            pm[p] - best_const for p in pm]))

    difficulty_pair_values = _difficulty_pair_series(
        pair_mean, cluster_means)
    d_values = np.asarray(list(difficulty_pair_values.values()),
                          dtype=np.float64)
    best_required = max(
        cluster_means[b] for b in REQUIRED_BASELINES[family])
    return {
        "family": family,
        "policy_means_pair_cluster": cluster_means,
        "difficulty_metric": float(np.mean(d_values)),
        "difficulty_metric_pair_se": float(
            np.std(d_values, ddof=1) / np.sqrt(len(d_values))
            if len(d_values) > 1 else float("inf")),
        "difficulty_metric_n_pairs": int(len(d_values)),
        "reference_beats_required_baselines": bool(
            cluster_means["reference"] > best_required),
        "oracle_positive": bool(cluster_means["oracle"] > 0.0),
        "episodes": per_episode,
    }


def _difficulty_pair_series(
    pair_mean: dict[str, dict[int, float]],
    cluster_means: dict[str, float],
) -> dict[int, float]:
    best_const = max(0.0, cluster_means["always_long"])
    ref = pair_mean["reference"]
    return {p: v - best_const for p, v in ref.items()}


def rung_report_r3(records: list[PairRecord], family: str,
                   rung_params_by_rung: dict[str, dict[str, Any]],
                   thresholds_by_family: dict[str, dict[str, Any]],
                   preproc: RouteCPreprocessor) -> dict[str, Any]:
    """按 rung 聚合 R3 评估 + 难度排序(pair-cluster 口径)。"""
    by_rung: dict[str, Any] = {}
    for rung in CURRICULUM261_RUNGS:
        rung_records = [r for r in records if r.rung == rung]
        ev = evaluate_pair_corpus_r3(
            rung_records, family, rung_params_by_rung[rung],
            thresholds_by_family[family], preproc)
        ev["rung"] = rung
        by_rung[rung] = ev
    metrics = [by_rung[r]["difficulty_metric"]
               for r in CURRICULUM261_RUNGS]
    ses = [by_rung[r]["difficulty_metric_pair_se"]
           for r in CURRICULUM261_RUNGS]
    return {
        "family": family,
        "by_rung": by_rung,
        "difficulty_metric_ladder": {
            r: by_rung[r]["difficulty_metric"]
            for r in CURRICULUM261_RUNGS},
        "difficulty_metric_pair_se": {
            r: by_rung[r]["difficulty_metric_pair_se"]
            for r in CURRICULUM261_RUNGS},
        "ordering_ok": bool(
            metrics[0] > metrics[1] > metrics[2] > metrics[3]),
        "d3_metric_positive": bool(metrics[3] > 0.0),
        "reference_beats_required_all_rungs": bool(all(
            by_rung[r]["reference_beats_required_baselines"]
            for r in CURRICULUM261_RUNGS)),
        "oracle_positive_all_rungs": bool(all(
            by_rung[r]["oracle_positive"] for r in CURRICULUM261_RUNGS)),
    }


def run_calibration_corpus_r3(
    preproc: RouteCPreprocessor, namespace: str,
    pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG,
    out_dir: Path | None = None, prefix: str = "calibration",
) -> dict[str, Any]:
    """R3 calibration 语料(calibration_r3 / calibration_holdout_r3)。"""
    specs = family_specs()
    thresholds = {
        "c1_opportunity": dict(
            specs["c1_opportunity"].reference_defaults),
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
        family_reports[family] = rung_report_r3(
            records, family, rung_params, thresholds, preproc)
        family_reports[family]["attempt_stats"] = attempt_statistics(
            records)
        family_reports[family]["pair_integrity_pass_rate"] = float(
            sum(1 for r in records if r.integrity_ok) / len(records))
    summary = {
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "stage": prefix,
        "seed_namespace": namespace,
        "pairs_per_rung": pairs_per_rung,
        "preprocessing_state_hash": preproc.state_hash(),
        "thresholds": thresholds,
        "families": family_reports,
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{prefix}_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
    return summary


# ------------------------------------------------ conditioning profile
def conditioning_profile(
    preproc: RouteCPreprocessor,
    fit_records: list[PairRecord],
    eval_records: list[PairRecord],
) -> dict[str, Any]:
    """§19 feature conditioning 量化:分布/越界率/随机第一层贡献/饱和。"""
    state = preproc.fitted_state()
    fit_df = fit_matrix_from_records(fit_records)
    eval_df = fit_matrix_from_records(eval_records)
    fit_t = preproc.transform(fit_df).to_numpy(dtype=np.float64)
    eval_t = preproc.transform(eval_df).to_numpy(dtype=np.float64)
    fit_raw = fit_df.to_numpy(dtype=np.float64)
    eval_raw = eval_df.to_numpy(dtype=np.float64)

    dmin = np.asarray(state["scaler"]["data_min_"])
    dmax = np.asarray(state["scaler"]["data_max_"])
    out_mask = (eval_raw < dmin[None, :]) | (eval_raw > dmax[None, :])
    out_rate = out_mask.mean(axis=0)

    # 随机初始化 MLP 第一层 per-input 贡献(stable seed,双空间对比)
    rng = np.random.default_rng(262626)
    w1 = rng.uniform(-1.0, 1.0, size=(128, 9)) / np.sqrt(9)
    b1 = rng.uniform(-0.5, 0.5, size=128)

    def _contribution(X: np.ndarray) -> np.ndarray:
        # E|w_ij| * std_i(每输入列的期望绝对贡献,position 槽位取
        # 其 0/1 二值 std)
        mean_abs_w = np.mean(np.abs(w1), axis=0)
        std = X.std(axis=0, ddof=1)
        return mean_abs_w * std

    contrib_scaled = _contribution(
        np.concatenate([fit_t, np.zeros((len(fit_t), 1))], axis=1))
    contrib_raw = _contribution(
        np.concatenate([fit_raw, np.zeros((len(fit_raw), 1))], axis=1))

    def _share(c: np.ndarray) -> float:
        return float(c[4:8].sum() / max(c[:8].sum(), 1e-300))

    # Tanh 饱和率:第一层 pre-activation |tanh(z)| > 0.95(抽样子集)
    sub = fit_t[:: max(1, len(fit_t) // 8000)][:8000]
    z = sub @ w1[:, :8].T + b1[None, :]
    sat_rate = float((np.abs(np.tanh(z)) > 0.95).mean())
    z_raw = fit_raw[:: max(1, len(fit_raw) // 8000)][:8000] @ w1[
        :, :8].T + b1[None, :]
    sat_raw = float((np.abs(np.tanh(z_raw)) > 0.95).mean())

    quant = lambda a: (np.percentile(a, [1, 5, 25, 50, 75, 95, 99])
                       ).round(6).tolist()
    per_feature = {}
    for j, col in enumerate(PRODUCTION_FEATURE_COLUMNS):
        per_feature[col] = {
            "fit_min": float(fit_t[:, j].min()),
            "fit_max": float(fit_t[:, j].max()),
            "fit_mean": float(fit_t[:, j].mean()),
            "fit_std": float(fit_t[:, j].std(ddof=1)),
            "fit_quantiles": quant(fit_t[:, j]),
            "eval_min": float(eval_t[:, j].min()),
            "eval_max": float(eval_t[:, j].max()),
            "eval_mean": float(eval_t[:, j].mean()),
            "eval_std": float(eval_t[:, j].std(ddof=1)),
            "eval_quantiles": quant(eval_t[:, j]),
            "eval_out_of_fit_range_rate": float(out_rate[j]),
            "scaled_variance": float(fit_t[:, j].var(ddof=1)),
        }
    corr = np.corrcoef(fit_t.T)
    checks = {
        "raw_ohlc_share_scaled": _share(contrib_scaled),
        "raw_ohlc_share_unscaled": _share(contrib_raw),
        "raw_ohlc_share_ok": bool(
            _share(contrib_scaled)
            <= CONDITIONING_GATE["raw_ohlc_contribution_share_max"]),
        "tanh_saturation_scaled": sat_rate,
        "tanh_saturation_unscaled": sat_raw,
        "tanh_saturation_ok": bool(
            sat_rate <= CONDITIONING_GATE["tanh_saturation_rate_max"]),
        "near_zero_scaled_variance": bool(
            (np.var(fit_t, axis=0, ddof=1) > 1e-12).all()),
        "eval_out_of_range_max": float(out_rate.max()),
        "eval_out_of_range_ok": bool(
            out_rate.max()
            <= CONDITIONING_GATE["eval_out_of_fit_range_rate_max"]),
        "all_finite": bool(np.isfinite(fit_t).all()
                           and np.isfinite(eval_t).all()),
    }
    return {
        "format": "cur261-r3-conditioning-profile-v1",
        "gate_constants": CONDITIONING_GATE,
        "n_fit_rows": int(len(fit_t)),
        "n_eval_rows": int(len(eval_t)),
        "per_feature": per_feature,
        "feature_correlation_fit": corr.round(4).tolist(),
        "random_first_layer": {"seed": 262626, "units": 128},
        "checks": checks,
        "pass": bool(checks["raw_ohlc_share_ok"]
                     and checks["tanh_saturation_ok"]
                     and checks["near_zero_scaled_variance"]
                     and checks["eval_out_of_range_ok"]
                     and checks["all_finite"]),
    }


# --------------------------------------------- preprocessing robustness
def preprocessing_robustness_checks(
    preproc: RouteCPreprocessor,
    fit_manifest: dict[str, Any],
    preproc_holdout: RouteCPreprocessor,
    holdout_manifest: dict[str, Any],
    eval_records: list[PairRecord],
    equivalence_records: list[PairRecord],
) -> dict[str, Any]:
    """§18 多 fit manifest 稳健性 + §10/§11/§12/§13 合同验证。

    检查:8 特征存活、列序一致、无 NaN/Inf、observation containment、
    serialization/reload、staged/mixed(行序)不变、reference 等价、
    双 fit state 的 transform 分布稳定性。
    """
    import tempfile

    from rl_curriculum.generator_api import PRICE_COLUMNS

    checks: dict[str, Any] = {}
    checks["survival_main"] = bool(
        preproc.retained_columns == list(PRODUCTION_FEATURE_COLUMNS))
    checks["survival_holdout"] = bool(
        preproc_holdout.retained_columns
        == list(PRODUCTION_FEATURE_COLUMNS))
    checks["column_order_main"] = list(preproc.retained_columns)
    checks["fit_bank_integrity"] = bool(
        fit_manifest["integrity_all_ok"]
        and holdout_manifest["integrity_all_ok"])

    # serialization/reload(§12)
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "state.json"
        preproc.serialize(p)
        reloaded = RouteCPreprocessor.load(p)
        sample = fit_matrix_from_records(eval_records[:4])
        t1 = preproc.transform(sample)
        t2 = reloaded.transform(sample)
        checks["reload_transform_bitwise_equal"] = bool(
            list(t1.columns) == list(t2.columns) and np.array_equal(
                t1.to_numpy(), t2.to_numpy()))
        checks["reload_state_hash_equal"] = bool(
            reloaded.state_hash() == preproc.state_hash())

    # staged/mixed order invariance(§8):shuffled rows 同 multiset
    rng = np.random.default_rng(31415)
    fit_df = fit_matrix_from_records(generate_fit_bank(
        fit_manifest["namespace"], fit_manifest["pairs_per_rung"]))
    perm = rng.permutation(len(fit_df))
    alt = RouteCPreprocessor.build_and_fit(fit_df.iloc[perm])
    checks["staged_mixed_same_state_hash"] = bool(
        alt.state_hash() == preproc.state_hash())

    # NaN/Inf + containment(§11)
    eval_dfs = [rec.episodes[s].df for rec in eval_records[:8]
                for s in ("A", "B")]
    scaled = [preproc.transform_episode_df(df) for df in eval_dfs]
    finite = all(np.isfinite(
        sdf[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy()).all()
        for sdf in scaled)
    checks["no_nan_inf"] = bool(finite)
    contain = validate_observation_containment(
        scaled,
        [df[list(PRICE_COLUMNS)] for df in eval_dfs],
        EVAL_CFG,
        [int(r.episodes[s].spec.seed) for r in eval_records[:8]
         for s in ("A", "B")],
        context="preprocessing_robustness",
    )
    checks["observation_containment"] = contain

    # reference 等价(§13;每 family/rung 各 episode)
    specs = family_specs()
    thresholds = {
        f: dict(specs[f].reference_defaults) for f in CURRICULUM261_FAMILIES}
    eq_reports = []
    for rec in equivalence_records:
        rung_params = dict(specs[rec.family].rung_params[rec.rung])
        rung_params["cur261_rung"] = rec.rung
        eq_reports.append(reference_equivalence_check(
            rec.episodes["A"], rec.family, rung_params,
            thresholds[rec.family], preproc, EVAL_CFG, RAW_SCHEMA))
    checks["reference_equivalence_all"] = bool(
        all(e["pass"] for e in eq_reports))
    checks["reference_equivalence_n"] = len(eq_reports)

    # 双 fit state 分布稳定性(main vs holdout transform 的列统计差)
    sample_t_main = preproc.transform(sample).to_numpy()
    sample_t_hold = preproc_holdout.transform(sample).to_numpy()
    per_col_max_abs_diff = float(np.max(np.abs(
        sample_t_main - sample_t_hold)))
    checks["dual_fit_transform_max_abs_diff"] = per_col_max_abs_diff
    checks["state_hashes_distinct"] = bool(
        preproc.state_hash() != preproc_holdout.state_hash())

    core_ok = bool(
        checks["survival_main"] and checks["survival_holdout"]
        and checks["reload_transform_bitwise_equal"]
        and checks["reload_state_hash_equal"]
        and checks["staged_mixed_same_state_hash"]
        and checks["no_nan_inf"] and contain["pass"]
        and checks["reference_equivalence_all"]
        and checks["fit_bank_integrity"])
    return {
        "format": "cur261-r3-preprocessing-robustness-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "fit_manifest": fit_manifest,
        "holdout_manifest": holdout_manifest,
        "checks": checks,
        "pass": core_ok,
    }


# ------------------------------------------------ supervised learnability
def _collect_supervised_dataset(
    records: list[PairRecord], family: str, preproc: RouteCPreprocessor,
) -> list[dict[str, Any]]:
    """scaled obs + reference action(等价已证,标签=raw reference)。"""
    specs = family_specs()
    thresholds = dict(specs[family].reference_defaults)
    schema = r3_observation_schema(preproc)
    rows: list[dict[str, Any]] = []
    for rec in records:
        rung_params = dict(specs[family].rung_params[rec.rung])
        raw_set = build_policy_set(family, rung_params, thresholds)
        ref = raw_set["reference"]
        for side in ("A", "B"):
            ep = rec.episodes[side]
            scaled_ep = scaled_episode(ep, preproc)
            r = run_policy_episode(
                ref, scaled_ep, EVAL_CFG, schema,
                return_observations=True)
            obs_list, actions = r[2], r[1]
            for o, a in zip(obs_list, actions):
                rows.append({
                    "family": family, "rung": rec.rung,
                    "pair": rec.pair_index, "side": side,
                    "obs": np.asarray(o, dtype=np.float32),
                    "action": int(a),
                })
    return rows


def _binary_metrics(y_true: np.ndarray, p_long: np.ndarray,
                    ) -> dict[str, Any]:
    """balanced acc / Long recall/precision / PR-AUC / ROC-AUC(自实现,
    无 sklearn 依赖;PR/ROC-AUC 用秩法,与概率单调变换无关)。"""
    y = np.asarray(y_true, dtype=np.int64)
    p = np.asarray(p_long, dtype=np.float64)
    pred = (p >= 0.5).astype(np.int64)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    balanced_acc = 0.5 * (recall + specificity)
    precision = tp / max(tp + fp, 1)

    def _auc(scores: np.ndarray, labels: np.ndarray) -> float:
        order = np.argsort(scores, kind="mergesort")
        ranks = np.empty(len(scores), dtype=np.float64)
        i = 0
        s_sorted = scores[order]
        while i < len(s_sorted):
            j = i
            while j + 1 < len(s_sorted) and s_sorted[j + 1] == s_sorted[i]:
                j += 1
            ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
            i = j + 1
        n_pos = int(labels.sum())
        n_neg = int(len(labels) - n_pos)
        if n_pos == 0 or n_neg == 0:
            return float("nan")
        return float(
            (ranks[labels == 1].sum() - n_pos * (n_pos + 1) / 2.0)
            / (n_pos * n_neg))

    roc_auc = _auc(p, y)
    # PR-AUC(按阈值递减的 precision-recall 阶梯和)
    order = np.argsort(-p, kind="mergesort")
    y_sorted = y[order]
    cum_tp = np.cumsum(y_sorted)
    ks = np.arange(1, len(y_sorted) + 1)
    prec_at_k = cum_tp / ks
    n_pos = int(y.sum())
    with np.errstate(divide="ignore", invalid="ignore"):
        recall_at_k = cum_tp / max(n_pos, 1)
    pr_auc = float(np.sum(
        (recall_at_k[1:] - recall_at_k[:-1]) * prec_at_k[1:])
    ) if n_pos > 0 else float("nan")
    agreement = float((pred == y).mean())
    majority = float(max(y.mean(), 1 - y.mean()))
    # behavior gap(与 Stage 2.6.2 Repair R2 预注册先例
    # extended_binary_metrics.behavior_gap_proxy 完全同口径):
    # TPR - FPR = 2 x balanced_accuracy - 1(Youden's J / informedness)。
    fpr = fp / max(fp + tn, 1)
    return {
        "balanced_accuracy": float(balanced_acc),
        "long_recall": float(recall),
        "long_precision": float(precision),
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "accuracy": agreement,
        "behavior_gap": float(recall - fpr),
        "behavior_gap_definition": "TPR - FPR (= 2*balanced_accuracy - 1;"
                                   " R2 extended_binary_metrics 同口径)",
        "accuracy_minus_majority_diagnostic": float(agreement - majority),
        "class_balance": {"long": int(y.sum()),
                          "flat": int(len(y) - y.sum())},
    }


def supervised_learnability_run(
    preproc: RouteCPreprocessor,
    pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG,
    namespace: str = "calibration_r3",
    train_pair_limit: int = 6,
) -> dict[str, Any]:
    """§20 supervised learnability gate(三族 x 3 seeds x pair-heldout)。

    - 数据:calibration corpus 的 scaled obs + reference action;
    - split:pair-level —— 每 rung 前 train_pair_limit 个 pair 的
      全部 A/B 行训练,其余 pair 为 held-out(无 pair 跨集泄漏);
    - C2:W(class-weighted CE)与 B(balanced minibatch)双控制,
      U(unweighted)仅诊断;
    - gate:每 family 至少 2 个 gated (seed,control) run
      held-out balanced accuracy >= 0.60 且 behavior gap >= 0.20。
    """
    from rl_curriculum.ppo262_r2_supervised import train_supervised_mlp

    specs = family_specs()
    out: dict[str, Any] = {
        "format": "cur261-r3-supervised-learnability-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "namespace": namespace,
        "gate_constants": SUPERVISED_GATE,
        "model_seeds": list(SUPERVISED_MODEL_SEEDS),
        "families": {},
    }
    overall = True
    for family in CURRICULUM261_FAMILIES:
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace))
        rows = _collect_supervised_dataset(records, family, preproc)
        train_rows = [r for r in rows if r["pair"] < train_pair_limit]
        test_rows = [r for r in rows if r["pair"] >= train_pair_limit]
        Xtr = np.stack([r["obs"] for r in train_rows]).astype(np.float32)
        ytr = np.asarray([r["action"] for r in train_rows], dtype=np.int64)
        Xte = np.stack([r["obs"] for r in test_rows]).astype(np.float32)
        yte = np.asarray([r["action"] for r in test_rows], dtype=np.int64)
        test_pairs = sorted({(r["rung"], r["pair"]) for r in test_rows})

        # 三族统一 U/W/B 控制(与 Stage 2.6.2 Repair R2 的 family-aware
        # supervised 先例一致):C1/C3 的 Long 率约 7-8%,unweighted
        # full-batch CE 在该不平衡下结构性偏向 Flat(训练控制问题,
        # 非表示可学性问题);W/B 为正式 gate 控制,U 仅诊断。
        controls = ["U", "W", "B"]
        gated_controls = ["W", "B"]
        seed_reports: list[dict[str, Any]] = []
        n_passing = 0
        for seed in SUPERVISED_MODEL_SEEDS:
            for control in controls:
                trained = train_supervised_mlp(
                    Xtr, ytr, control=control, seed=seed)
                net = trained["net"]
                import torch

                with torch.no_grad():
                    logits = net(torch.as_tensor(Xte))
                    p_long = torch.softmax(logits, dim=-1)[:, 1].numpy()
                metrics = _binary_metrics(yte, p_long)
                # pair-level held-out 分布(逐 pair balanced acc)
                pair_accs = []
                for rung, pid in test_pairs:
                    sel = np.asarray([
                        (r["rung"], r["pair"]) == (rung, pid)
                        for r in test_rows])
                    if sel.sum() > 0 and len(set(yte[sel].tolist())) > 1:
                        pair_accs.append(_binary_metrics(
                            yte[sel], p_long[sel])["balanced_accuracy"])
                metrics["heldout_pair_balanced_accuracy_min"] = (
                    float(np.min(pair_accs)) if pair_accs else None)
                metrics["heldout_pair_balanced_accuracy_mean"] = (
                    float(np.mean(pair_accs)) if pair_accs else None)
                gated = bool(
                    metrics["balanced_accuracy"]
                    >= SUPERVISED_GATE["heldout_balanced_accuracy_min"]
                    and metrics["behavior_gap"]
                    >= SUPERVISED_GATE["behavior_gap_min"])
                if control in gated_controls:
                    n_passing += int(gated)
                seed_reports.append({
                    "seed": int(seed), "control": control,
                    "gated": gated, "metrics": metrics,
                })
        family_pass = bool(
            n_passing >= SUPERVISED_GATE["min_seeds_passing"])
        overall = overall and family_pass
        out["families"][family] = {
            "n_train_rows": int(len(train_rows)),
            "n_test_rows": int(len(test_rows)),
            "train_long_rate": float(ytr.mean()),
            "test_long_rate": float(yte.mean()),
            "controls": controls,
            "gated_controls": gated_controls,
            "n_gated_runs_passing": n_passing,
            "min_seeds_passing": SUPERVISED_GATE["min_seeds_passing"],
            "runs": seed_reports,
            "pass": family_pass,
        }
    out["pass"] = bool(overall)
    return out


# --------------------------------------------------------- 课程 gate
def curriculum_robustness_gate_r3(
    main: dict[str, Any], holdout: dict[str, Any],
    kappa: float = ROBUSTNESS_KAPPA_R3,
    stress: dict[str, Any] | None = None,
    c2_diagnostics: dict[str, Any] | None = None,
    reference_gap_floor: float = 0.0,
) -> dict[str, Any]:
    """§24 R3 课程稳健性 gate(pair-cluster 口径)。

    每 family 在 calibration_r3 AND calibration_holdout_r3 同时满足:
    1. D0>D1>D2>D3;2. D3>0;3. reference>全部必胜基线;
    4. pair integrity=1.0(+stress 实证);5. 相邻 rung gap >=
    kappa x pair-cluster SE;6. D3 >= kappa x pair-cluster SE;
    7. C2 双诊断;8. attempts 分布合理;
    9. reference-vs-required margin >= kappa x pair-cluster SE
       (极窄 gap 不得用 normalized capture 掩盖)。
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
            c: {
                "ordering_ok": rep["ordering_ok"],
                "d3_positive": rep["d3_metric_positive"],
                "ref_beats_required": rep[
                    "reference_beats_required_all_rungs"],
                "integrity_unity": bool(
                    rep["pair_integrity_pass_rate"] == 1.0),
            }
            for c, rep in (("main", fm), ("holdout", fh))
        }
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
        c2_flags: dict[str, bool] | None = None
        if family == "c2_context":
            c2_flags = {
                "local_cue_independence": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["local_cue_independence"]["pass"]),
                "context_observability": bool(
                    c2_diagnostics is not None
                    and c2_diagnostics["context_observability"]["pass"]),
            }

        def _pair_metric_samples(rep: dict[str, Any], rung: str
                                 ) -> list[float]:
            ep_rows = rep["by_rung"][rung]["episodes"]
            by_pair: dict[int, list[float]] = {}
            for row in ep_rows:
                by_pair.setdefault(int(row["pair"]), []).append(
                    float(row["reference"])
                    - max(0.0, float(row["always_long"])))
            return [float(np.mean(v)) for v in by_pair.values()]

        samples = {r: (
            _pair_metric_samples(fm, r) + _pair_metric_samples(fh, r))
            for r in CURRICULUM261_RUNGS}
        n_pairs_per_rung = {r: len(samples[r])
                            for r in CURRICULUM261_RUNGS}
        means = {r: float(np.mean(samples[r]))
                 for r in CURRICULUM261_RUNGS}
        ses = {
            r: (float(np.std(samples[r], ddof=1)
                      / np.sqrt(len(samples[r])))
                if len(samples[r]) > 1 else float("inf"))
            for r in CURRICULUM261_RUNGS}
        gap_report: dict[str, Any] = {}
        gaps_ok = True
        for k in range(3):
            r_hi, r_lo = CURRICULUM261_RUNGS[k], CURRICULUM261_RUNGS[k + 1]
            gap_main = ladders["main"][r_hi] - ladders["main"][r_lo]
            gap_hold = ladders["holdout"][r_hi] - ladders["holdout"][r_lo]
            se = float(np.sqrt(ses[r_hi] ** 2 + ses[r_lo] ** 2))
            ok = bool(gap_main > 0 and gap_hold > 0
                      and min(gap_main, gap_hold) >= kappa * se)
            gaps_ok = gaps_ok and ok
            gap_report[f"{r_hi}-{r_lo}"] = {
                "gap_main": gap_main, "gap_holdout": gap_hold,
                "se_pair_cluster": se, "kappa_times_se": kappa * se,
                "ok": ok,
            }
        d3_se_ok = bool(means["D3"] >= kappa * ses["D3"])

        # 条件 9:reference-vs-required margin(pair-cluster SE 口径)。
        # 统计单元 =(rung, pair):margin 在每个 rung 内独立按 pair 聚合
        # (不同 rung 的同 index pair 是不同 episode,跨 rung 混合会
        # 制造伪 cluster);全部 rung(含 D3)需 margin >= floor 且
        # >= kappa x pair-cluster SE。
        margin_report: dict[str, Any] = {}
        margins_ok = True
        for rep_name, rep in (("main", fm), ("holdout", fh)):
            required = REQUIRED_BASELINES[family]
            rung_margins: dict[str, Any] = {}
            for r in CURRICULUM261_RUNGS:
                by_pair_ref: dict[int, list[float]] = {}
                by_pair_best: dict[int, list[float]] = {}
                for row in rep["by_rung"][r]["episodes"]:
                    pid = int(row["pair"])
                    by_pair_ref.setdefault(pid, []).append(
                        float(row["reference"]))
                    by_pair_best.setdefault(pid, []).append(max(
                        float(row[b]) for b in required))
                pair_margin = {
                    p: float(np.mean(by_pair_ref[p])
                             - np.mean(by_pair_best[p]))
                    for p in by_pair_ref}
                arr = np.asarray(list(pair_margin.values()))
                margin = float(np.mean(arr))
                se = float(np.std(arr, ddof=1) / np.sqrt(len(arr))) \
                    if len(arr) > 1 else float("inf")
                ok = bool(margin >= reference_gap_floor
                          and margin >= kappa * se)
                margins_ok = margins_ok and ok
                rung_margins[r] = {
                    "reference_minus_best_required": margin,
                    "pair_cluster_se": se,
                    "gap_over_se": float(margin / se) if se > 0 else None,
                    "kappa_times_se": kappa * se,
                    "ok": ok,
                }
            margin_report[rep_name] = {
                "per_rung": rung_margins,
                "ok": bool(all(v["ok"] for v in rung_margins.values())),
            }
            margins_ok = margins_ok and margin_report[rep_name]["ok"]

        family_pass = bool(
            all(all(fc.values()) for fc in per_corpus_flags.values())
            and gaps_ok and d3_se_ok and margins_ok and stress_ok
            and attempts_ok
            and (c2_flags is None or all(c2_flags.values())))
        families_out[family] = {
            "per_corpus_flags": per_corpus_flags,
            "stress_accepted_implies_integrity": bool(stress_ok),
            "attempts_distribution_ok": bool(attempts_ok),
            "c2_diagnostics": c2_flags,
            "pair_cluster_metric_mean": means,
            "pair_cluster_metric_se": ses,
            "n_pairs_per_rung": n_pairs_per_rung,
            "gaps": gap_report,
            "reference_margin": margin_report,
            "d3_mean": means["D3"], "d3_se": ses["D3"],
            "d3_mean_ge_kappa_se": d3_se_ok,
            "pass": family_pass,
        }
    overall = bool(all(v["pass"] for v in families_out.values()))
    return {
        "format": "cur261-r3-curriculum-robustness-gate-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "kappa": float(kappa),
        "statistical_unit": "pair cluster(A/B 均值;禁止 episode 假独立)",
        "contract": [
            "1 ordering", "2 d3_positive", "3 ref_beats_required",
            "4 integrity_unity(corpus x2 + stress)",
            "5 gap_ge_kappa_pair_se", "6 d3_ge_kappa_pair_se",
            "7 c2_local_cue+observability(c2)",
            "8 attempts_distribution",
            "9 reference_margin_ge_kappa_pair_se",
        ],
        "main_namespace": main.get("seed_namespace", "calibration_r3"),
        "holdout_namespace": holdout.get(
            "seed_namespace", "calibration_holdout_r3"),
        "c2_local_cue_independence": (
            c2_diagnostics["local_cue_independence"]
            if c2_diagnostics else None),
        "c2_context_observability": (
            c2_diagnostics["context_observability"]
            if c2_diagnostics else None),
        "families": families_out,
        "pass": overall,
    }


def run_generator_stress_r3(pairs_per_rung: int = 12,
                            namespace: str = "stress_r3",
                            ) -> dict[str, Any]:
    """R3 generator stress(stress_r3 全新 seed space)。"""
    families_out: dict[str, Any] = {}
    for family in CURRICULUM261_FAMILIES:
        records = []
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    family, rung, idx, namespace=namespace))
        n_ok = sum(1 for r in records if r.integrity_ok)
        families_out[family] = {
            "namespace": namespace,
            "pairs_per_rung": pairs_per_rung,
            "n_pairs": len(records),
            "n_integrity_ok": n_ok,
            "integrity_pass_ratio": n_ok / len(records),
            "accepted_implies_integrity": bool(n_ok == len(records)),
        }
    return {
        "format": "cur261-r3-generator-stress-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "namespace": namespace,
        "families": families_out,
        "pass": bool(all(
            v["accepted_implies_integrity"] for v in families_out.values())),
    }


def run_c2_diagnostics_r3(pairs_per_rung: int = CALIBRATION_PAIRS_PER_RUNG,
                          ) -> dict[str, Any]:
    """R3 C2 双诊断(calibration_r3 + calibration_holdout_r3 语料)。

    C2 诊断读 raw 特征语义(wick 代数组合),与 preprocessing 无关
    (生成器与特征构造不变),复用 R2 检查函数、换用 R3 namespaces。
    """
    from rl_curriculum.curriculum261_qualification import (
        check_c2_context_observability,
        check_c2_local_cue_independence,
    )

    records: list[PairRecord] = []
    for ns in ("calibration_r3", "calibration_holdout_r3"):
        for rung in CURRICULUM261_RUNGS:
            for idx in range(pairs_per_rung):
                records.append(generate_pair(
                    "c2_context", rung, idx, namespace=ns))
    lc = check_c2_local_cue_independence(records)
    ob = check_c2_context_observability(records)
    return {"local_cue_independence": lc, "context_observability": ob}
