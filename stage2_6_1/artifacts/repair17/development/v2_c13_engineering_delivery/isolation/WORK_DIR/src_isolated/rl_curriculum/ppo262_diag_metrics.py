"""阶段 2.6.2 Repair R1:概率级策略评估与监督探针指标(diagnostic only)。

- probability-level 评估:P(Long)/P(Flat)/logit 差/熵/value prediction,
  按 latent evaluation label 聚合(C1 seg / C2 aligned-anti / C3 above-
  below)——区分"概率已分离但未跨过 0.5"与"网络输出无状态区分";
- deterministic(argmax)/stochastic(固定诊断 RNG)行为;
- supervised 探针指标:balanced accuracy / precision / recall /
  class balance / calibration / held-out pair / train-dev gap;
- 全部只读 observation 与 latent sidecar(事后打标签),
  不进入训练。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rl_curriculum.ppo262_diag_namespaces import DIAG262_PROB_RNG_SEED
from rl_curriculum.ppo262_diag_train import latent_label_series

#: latent label 语义(与 latent_label_series 对齐)
LATENT_LABEL_SEMANTICS = {
    "c1_opportunity": {"2": "positive", "1": "neutral", "0": "negative"},
    "c2_context": {"1": "aligned", "-1": "anti_aligned", "0": "no_cue"},
    "c3_cost": {"1": "above_cost", "0": "below_cost", "2": "no_signal"},
}


# ============================================================ 概率级评估
def probability_metrics_on_bank(
    model, bank: list, *, adapter=None, n_episodes: int | None = None,
) -> dict[str, Any]:
    """逐 episode 收集概率级输出并按 latent label 聚合。

    返回:
    - overall:deterministic/stochastic 一致率、P(Long) 均值、熵均值;
    - per_family:{latent_label -> {n, mean_p_long, mean_logit_diff,
      mean_entropy, mean_value, deterministic_long_rate,
      stochastic_long_rate}};
    - thresholds:P(Long) 跨过 0.5 的 bar 占比。
    stochastic 用固定诊断 RNG(numpy Generator,seed 记录在 artifact)。
    """
    import torch

    rng = np.random.default_rng(DIAG262_PROB_RNG_SEED)
    overall_p_long: list[float] = []
    overall_entropy: list[float] = []
    overall_det_long: list[int] = []
    overall_sto_long: list[int] = []
    det_sto_agree: list[int] = []
    per_family: dict[str, dict[str, dict[str, list]]] = {}
    for idx, loaded in enumerate(bank):
        if n_episodes is not None and idx >= n_episodes:
            break
        obs_seq = _reference_free_obs_sequence(loaded)
        if adapter is not None:
            obs_seq = [adapter.apply(o) for o in obs_seq]
        labels = latent_label_series(loaded, loaded.key.family)
        fam_acc = per_family.setdefault(
            loaded.key.family,
            {name: {"p_long": [], "logit_diff": [], "entropy": [],
                    "value": [], "det": [], "sto": []}
             for name in LATENT_LABEL_SEMANTICS[
                 loaded.key.family].values()})
        for t, obs in enumerate(obs_seq):
            obs_t = torch.as_tensor(
                np.asarray(obs, dtype=np.float32).reshape(1, -1))
            with torch.no_grad():
                dist = model.policy.get_distribution(obs_t)
                logits = dist.distribution.logits[0].numpy()
                probs = np.exp(logits - logits.max())
                probs = probs / probs.sum()
                value = float(model.policy.predict_values(obs_t)[0, 0])
            p_long = float(probs[1])
            logit_diff = float(logits[1] - logits[0])
            entropy = float(-np.sum(probs * np.log(probs + 1e-12)))
            det = int(np.argmax(logits))
            sto = int(rng.choice(2, p=probs))
            overall_p_long.append(p_long)
            overall_entropy.append(entropy)
            overall_det_long.append(det)
            overall_sto_long.append(sto)
            det_sto_agree.append(int(det == sto))
            lab = int(labels[t]) if t < len(labels) else None
            sem = LATENT_LABEL_SEMANTICS[loaded.key.family].get(
                str(lab) if lab is not None else "")
            if sem is None:
                continue
            acc = fam_acc[sem]
            acc["p_long"].append(p_long)
            acc["logit_diff"].append(logit_diff)
            acc["entropy"].append(entropy)
            acc["value"].append(value)
            acc["det"].append(det)
            acc["sto"].append(sto)

    def _agg(entries: dict[str, dict[str, list]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, acc in entries.items():
            if not acc["p_long"]:
                out[name] = {"n": 0}
                continue
            out[name] = {
                "n": len(acc["p_long"]),
                "mean_p_long": float(np.mean(acc["p_long"])),
                "std_p_long": float(np.std(acc["p_long"])),
                "mean_logit_diff": float(np.mean(acc["logit_diff"])),
                "mean_entropy": float(np.mean(acc["entropy"])),
                "mean_value_prediction": float(np.mean(acc["value"])),
                "deterministic_long_rate": float(np.mean(acc["det"])),
                "stochastic_long_rate": float(np.mean(acc["sto"])),
                "p_long_above_0.5_rate": float(
                    np.mean(np.asarray(acc["p_long"]) > 0.5)),
            }
        return out

    return {
        "format": "ppo262-diag-probability-metrics-v1",
        "prob_rng_seed": DIAG262_PROB_RNG_SEED,
        "n_bars_total": len(overall_p_long),
        "overall": {
            "mean_p_long": float(np.mean(overall_p_long)) if (
                overall_p_long) else None,
            "mean_entropy": float(np.mean(overall_entropy)) if (
                overall_entropy) else None,
            "deterministic_long_rate": float(np.mean(overall_det_long)) if (
                overall_det_long) else None,
            "stochastic_long_rate": float(np.mean(overall_sto_long)) if (
                overall_sto_long) else None,
            "det_sto_agreement_rate": float(np.mean(det_sto_agree)) if (
                det_sto_agree) else None,
        },
        "per_family": {fam: _agg(entries)
                       for fam, entries in per_family.items()},
    }


def probability_separation_summary(prob: dict[str, Any]) -> dict[str, Any]:
    """三族概率分离摘要(决策树证据用)。

    - C1: mean_p_long(positive) - max(neutral, negative)
    - C2: mean_p_long(aligned) - mean_p_long(anti_aligned)(per variant
      由 caller 在 bank 拆分后分别评估;此处聚合全部)
    - C3: mean_p_long(above_cost) - mean_p_long(below_cost)
    分离 > 0 且 deterministic gap = 0 => "概率已分离但未跨过 0.5"。
    """
    out: dict[str, Any] = {}
    per = prob.get("per_family", {})
    c1 = per.get("c1_opportunity", {})
    if c1:
        pos = (c1.get("positive") or {}).get("mean_p_long")
        neu = (c1.get("neutral") or {}).get("mean_p_long")
        neg = (c1.get("negative") or {}).get("mean_p_long")
        if pos is not None and neu is not None and neg is not None:
            out["c1_probability_gap"] = pos - max(neu, neg)
            out["c1_det_gap"] = ((c1.get("positive") or {}).get(
                "deterministic_long_rate", 0.0) - max(
                (c1.get("neutral") or {}).get(
                    "deterministic_long_rate", 0.0),
                (c1.get("negative") or {}).get(
                    "deterministic_long_rate", 0.0)))
    c2 = per.get("c2_context", {})
    if c2:
        al = (c2.get("aligned") or {}).get("mean_p_long")
        anti = (c2.get("anti_aligned") or {}).get("mean_p_long")
        if al is not None and anti is not None:
            out["c2_probability_gap"] = al - anti
            out["c2_det_gap"] = ((c2.get("aligned") or {}).get(
                "deterministic_long_rate", 0.0)
                - (c2.get("anti_aligned") or {}).get(
                    "deterministic_long_rate", 0.0))
    c3 = per.get("c3_cost", {})
    if c3:
        ab = (c3.get("above_cost") or {}).get("mean_p_long")
        be = (c3.get("below_cost") or {}).get("mean_p_long")
        if ab is not None and be is not None:
            out["c3_probability_gap"] = ab - be
            out["c3_det_gap"] = ((c3.get("above_cost") or {}).get(
                "deterministic_long_rate", 0.0)
                - (c3.get("below_cost") or {}).get(
                    "deterministic_long_rate", 0.0))
    return out


def _reference_free_obs_sequence(loaded) -> list[np.ndarray]:
    """episode 的初始状态观测序列(position slot 恒为决策前状态)。

    用冻结 AlignedLongFlatEnv 逐步展开:动作用 reference policy
    (因果,只读 obs)驱动,使 position slot 处于策略真实可见的分布;
    不读取 latent/future。
    """
    from rl_curriculum.curriculum261_api import curriculum261_eval_config
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.evaluator import _build_env

    # 概率级评估使用常平仓(position 恒 0)轨迹展开 obs:与坍塌诊断
    # 口径自洽,且不依赖任何 policy/latent——bar 级特征序列唯一。
    cfg = curriculum261_eval_config()
    schema = production_observation_schema()
    env = _build_env(loaded.episode, cfg, schema)
    obs, _ = env.reset(seed=loaded.episode.spec.seed)
    seq: list[np.ndarray] = []
    done = False
    while not done:
        seq.append(np.array(obs))
        obs, _r, term, trunc, _info = env.step(0)
        done = term or trunc
    return seq


# ============================================================ supervised
def supervised_metrics(y_true: np.ndarray, y_pred: np.ndarray,
                       ) -> dict[str, Any]:
    """balanced accuracy / precision / recall / class balance。"""
    y_true = np.asarray(y_true, dtype=int)
    y_pred = np.asarray(y_pred, dtype=int)
    n = len(y_true)
    classes = np.unique(np.concatenate([y_true, y_pred]))
    recalls = {}
    precisions = {}
    supports = {}
    for c in sorted(classes):
        tp = int(np.sum((y_pred == c) & (y_true == c)))
        fp = int(np.sum((y_pred == c) & (y_true != c)))
        fn = int(np.sum((y_pred != c) & (y_true == c)))
        recalls[int(c)] = tp / (tp + fn) if (tp + fn) else None
        precisions[int(c)] = tp / (tp + fp) if (tp + fp) else None
        supports[int(c)] = int(np.sum(y_true == c))
    bal = float(np.mean([v for v in recalls.values() if v is not None])) if (
        any(v is not None for v in recalls.values())) else None
    return {
        "n": int(n),
        "balanced_accuracy": bal,
        "accuracy": float(np.mean(y_true == y_pred)) if n else None,
        "precision_per_class": precisions,
        "recall_per_class": recalls,
        "class_balance": {int(c): v / n for c, v in supports.items()} if n
        else {},
        "predicted_long_rate": float(np.mean(y_pred == 1)) if n else None,
        "true_long_rate": float(np.mean(y_true == 1)) if n else None,
        "behavior_gap_proxy": (
            float(np.mean(y_pred[y_true == 1] == 1)) - float(
                np.mean(y_pred[y_true == 0] == 1)))
        if n and np.any(y_true == 1) and np.any(y_true == 0) else None,
    }


def calibration_curve_summary(y_true: np.ndarray, p_long: np.ndarray,
                              n_bins: int = 10) -> dict[str, Any]:
    """action calibration:预测 P(Long) 分箱 vs 实际 long 频率。"""
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(p_long, dtype=float)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    rows = []
    for i in range(n_bins):
        m = (p >= bins[i]) & (p < bins[i + 1] if i < n_bins - 1
                              else p <= bins[i + 1])
        if m.any():
            rows.append({
                "bin": [float(bins[i]), float(bins[i + 1])],
                "n": int(m.sum()),
                "mean_predicted_p_long": float(np.mean(p[m])),
                "empirical_long_rate": float(np.mean(y[m])),
            })
    return {"bins": rows}
