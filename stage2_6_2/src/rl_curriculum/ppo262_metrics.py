"""阶段 2.6.2:评估、normalized reference-gap capture、行为能力指标、
retention 与 pair-cluster 不确定度。

评估口径与 2.6.1 qualification 完全一致:

- 每 policy × episode 用 evaluator.run_observation_episode(obs-only
  路径,冻结 AlignedLongFlatEnv + market_open_causal + 终端清算);
- reference 与 required baselines 在**同一 evaluation bank 上重新
  运行**(不得复用 R2 qualification 的收益数字,§11);
- capture(f,r) = (P - B) / (R - B),不 clip(<0 / >1 都是真实诊断);
- family core capture = 0.20*D0 + 0.30*D1 + 0.50*D2(D3 stretch 不入
  核心权重);aggregate = mean(三族 core);
- 统计单位是 pair(A/B 共享噪声与事件表,§12):pair-level mean、
  pair-cluster bootstrap、training-seed 分布、staged/mixed 配对差。

行为能力指标(latent sidecar 仅在评估后打标签;不进入
observation/reward/训练,§14):决策 bar 对齐——actions[i] 是 policy
在 close[i] 观察后的动作,与 hidden 行 i 一一对应。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import curriculum261_eval_config
from rl_curriculum.curriculum261_production_obs import (
    production_observation_schema,
)
from rl_curriculum.evaluator import run_observation_episode
from rl_curriculum.policy_api import CandidatePolicy
from rl_curriculum.ppo262_banks import LoadedEpisode

#: core capture 的 rung 权重(D3 = stretch,不入核心权重)
PPO262_CORE_RUNG_WEIGHTS = {"D0": 0.20, "D1": 0.30, "D2": 0.50}
#: required baselines(2.6.1 qualification 同款合同)
PPO262_REQUIRED_BASELINES = {
    "c1_opportunity": ("always_flat", "always_long"),
    "c2_context": ("always_flat", "always_long", "c2_local_only"),
    "c3_cost": ("always_flat", "always_long", "c3_cost_ignorant"),
}


# ---------------------------------------------------------------- SB3 适配
class SB3PPOPolicy(CandidatePolicy):
    """SB3 PPO 模型的 obs-only 确定性评估适配器。

    act 与 model.predict(deterministic=True) 等价(Discrete = argmax
    logits),但绕过 predict 的逐次检查开销;reset_episode 无参数
    (前馈 PPO 无跨 episode 状态)。
    """

    def __init__(self, model, name: str):
        self.model = model
        self.name = name

    def reset_episode(self) -> None:
        return None

    def act(self, observation) -> int:
        import torch
        obs = np.asarray(observation, dtype=np.float32).reshape(1, -1)
        with torch.no_grad():
            dist = self.model.policy.get_distribution(
                torch.as_tensor(obs))
            action = torch.argmax(
                dist.distribution.logits, dim=-1)
        return int(action.item())


def load_sb3_policy(zip_path, name: str) -> SB3PPOPolicy:
    from stable_baselines3 import PPO
    model = PPO.load(str(zip_path), device="cpu")
    return SB3PPOPolicy(model, name)


# ---------------------------------------------------------------- 评估
def evaluate_policy_on_bank(policy, bank: list[LoadedEpisode],
                            *, collect_actions: bool = True,
                            ) -> list[dict[str, Any]]:
    """一个 policy 在 bank 上的逐 episode 评估行(net return + actions)。

    返回行:{family, rung, pair_index, variant, net_return, n_trades,
    actions(list[int]|None), result 摘要}。
    """
    cfg = curriculum261_eval_config()
    schema = production_observation_schema()
    rows: list[dict[str, Any]] = []
    for loaded in bank:
        if collect_actions:
            result, actions, _ = run_observation_episode(
                policy, loaded.episode, cfg, schema, return_actions=True)
        else:
            result = run_observation_episode(
                policy, loaded.episode, cfg, schema)
            actions = None
        k = loaded.key
        rows.append({
            "family": k.family, "rung": k.rung,
            "pair_index": int(k.pair_index), "variant": k.variant,
            "net_return": float(result.net_return),
            "n_trades": int(result.n_trades),
            "total_fees": float(result.total_fees),
            "max_drawdown": float(result.max_drawdown),
            "reward_consistency_ok": bool(result.reward_consistency_ok),
            "actions": actions,
        })
    return rows


def build_261_policy_set(family: str, rung_params: dict[str, Any],
                         reference_thresholds: dict[str, Any],
                         ) -> dict[str, Any]:
    """2.6.1 reference + required baselines(rung 参数来自锁定 plan)。"""
    from rl_curriculum.curriculum261_c1 import C1ReferencePolicy
    from rl_curriculum.curriculum261_c2 import C2LocalOnlyPolicy, C2ReferencePolicy
    from rl_curriculum.curriculum261_c3 import (
        C3CostIgnorantPolicy, C3ReferencePolicy,
    )
    from rl_curriculum.curriculum261_c1 import c1_reference_threshold
    from rl_curriculum.curriculum261_c3 import c3_strength_threshold
    from rl_curriculum.policies import (
        AlwaysFlatPolicy, AlwaysLongPolicy,
    )

    pols: dict[str, Any] = {
        "always_flat": AlwaysFlatPolicy(),
        "always_long": AlwaysLongPolicy(),
    }
    if family == "c1_opportunity":
        thr = c1_reference_threshold(
            rung_params, reference_thresholds["ma_sigma_mult"])
        pols["reference"] = C1ReferencePolicy(thr)
    elif family == "c2_context":
        pols["reference"] = C2ReferencePolicy(
            cue_thr=reference_thresholds["cue_thr"],
            wick_dir_thr=reference_thresholds["wick_dir_thr"],
            wick_width_thr=reference_thresholds["wick_width_thr"],
        )
        pols["c2_local_only"] = C2LocalOnlyPolicy(
            cue_thr=reference_thresholds["cue_thr"])
    elif family == "c3_cost":
        thr = c3_strength_threshold(
            rung_params, reference_thresholds["margin"])
        pols["reference"] = C3ReferencePolicy(thr)
        pols["c3_cost_ignorant"] = C3CostIgnorantPolicy(
            any_signal_s=reference_thresholds["any_signal_s"])
    else:
        raise ValueError(f"未知 family {family!r}")
    return pols


# ---------------------------------------------------------------- capture
def policy_mean_net_return(rows: list[dict[str, Any]]) -> float:
    return float(np.mean([r["net_return"] for r in rows]))


def pair_level_values(rows: list[dict[str, Any]]) -> dict[tuple, float]:
    """pair 为统计单位:A/B 双端 net return 的均值(pair cluster 值)。"""
    by_pair: dict[tuple, list[float]] = {}
    for r in rows:
        pk = (r["family"], r["rung"], r["pair_index"])
        by_pair.setdefault(pk, []).append(r["net_return"])
    return {k: float(np.mean(v)) for k, v in by_pair.items()}


def capture_table(
    ppo_rows: list[dict[str, Any]],
    reference_rows: list[dict[str, Any]],
    baseline_rows: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """normalized reference-gap capture(逐 family/rung;不 clip)。

    baseline_rows: {policy_name: rows};B(f,r) = required baselines 中
    mean net return 最高者(§11)。
    """
    def _by_rung(rows: list[dict[str, Any]]) -> dict[tuple, list[float]]:
        out: dict[tuple, list[float]] = {}
        for r in rows:
            out.setdefault((r["family"], r["rung"]), []).append(
                r["net_return"])
        return out

    ppo_by = _by_rung(ppo_rows)
    ref_by = _by_rung(reference_rows)
    base_by = {
        name: _by_rung(rows) for name, rows in baseline_rows.items()}
    frs = sorted({k for d in (ppo_by, ref_by, *base_by.values())
                  for k in d})
    table: dict[str, dict[str, Any]] = {}
    for fam, rung in frs:
        required = PPO262_REQUIRED_BASELINES.get(fam, ("always_flat",))
        base_means = {
            name: float(np.mean(base_by[name][(fam, rung)]))
            for name in required if (fam, rung) in base_by.get(name, {})}
        if not base_means:
            continue
        best_name = max(base_means, key=base_means.get)
        b = base_means[best_name]
        r = float(np.mean(ref_by[(fam, rung)]))
        p = float(np.mean(ppo_by[(fam, rung)]))
        denom = r - b
        table[f"{fam}/{rung}"] = {
            "ppo_mean": p, "reference_mean": r, "baseline_mean": b,
            "best_baseline": best_name,
            "baseline_means": base_means,
            "denominator": denom,
            "capture": (p - b) / denom if denom != 0 else None,
        }
    return table


def family_core_capture(table: dict[str, dict[str, Any]],
                        family: str) -> float | None:
    """family core capture = 0.20*D0 + 0.30*D1 + 0.50*D2。"""
    parts = []
    for rung, w in PPO262_CORE_RUNG_WEIGHTS.items():
        cell = table.get(f"{family}/{rung}")
        if cell is None or cell["capture"] is None:
            return None
        parts.append(w * cell["capture"])
    return float(sum(parts))


# ------------------------------------------------- config dev 专用指标(R1)
#: config-development 的候选评分指标名(Repair A 方案 B,独立于
#: family_core_capture:config-dev 评估集只含 D1 cells,与 D0/D1/D2
#: 加权公式的输入要求不兼容——s262_r0 的 null-score fallback 根因)
CONFIG_DEV_D1_METRIC_NAME = "config_dev_D1_capture"


def config_dev_d1_capture(
    table: dict[str, dict[str, Any]],
    families: tuple[str, ...] | list[str],
) -> float:
    """config-development 专用 D1-only capture(Repair A 方案 B)。

    - 只读 {family}/D1 cells 的 capture,取三族均值;
    - 不得调用 family_core_capture(D0/D1/D2 公式):评估 scope 与指标
      定义必须一致;
    - 输入不足(缺 cell / capture=None)时 raise ValueError,
      绝不返回 None——candidate score 必须是有限可比数值,
      all-fail gate 依据真实数值工作,不允许静默降级或 fallback。
    """
    vals: list[float] = []
    missing: list[str] = []
    for fam in families:
        cell = table.get(f"{fam}/D1")
        if cell is None:
            missing.append(f"{fam}/D1 cell 缺失(评估集与 D1-only 指标不匹配)")
            continue
        cap = cell["capture"]
        if cap is None:
            missing.append(
                f"{fam}/D1 capture 为 None(denominator=0:reference 与 "
                f"best baseline 净收益相同,该评估集无区分度)")
            continue
        vals.append(float(cap))
    if missing:
        raise ValueError(
            f"{CONFIG_DEV_D1_METRIC_NAME} 输入不足,fail closed: "
            + "; ".join(missing))
    result = float(np.mean(vals))
    if not np.isfinite(result):
        raise ValueError(
            f"{CONFIG_DEV_D1_METRIC_NAME} 计算结果非有限值: {result}")
    return result


def aggregate_capture(table: dict[str, dict[str, Any]]) -> float | None:
    fams = []
    for fam in PPO262_REQUIRED_BASELINES:
        c = family_core_capture(table, fam)
        if c is None:
            return None
        fams.append(c)
    return float(np.mean(fams))


# ---------------------------------------------------------------- 行为指标
def behavior_metrics(rows: list[dict[str, Any]],
                     bank: list[LoadedEpisode]) -> dict[str, Any]:
    """C1/C2/C3 行为能力指标(latent sidecar 事后打标签)。

    决策 bar 对齐:actions[i] 与 hidden.iloc[i](bar i)一一对应
    (policy 在 close[i] 观察后决策)。
    """
    out: dict[str, Any] = {}
    by_family: dict[str, list[tuple[LoadedEpisode, dict[str, Any]]]] = {}
    for loaded, row in zip(bank, rows):
        by_family.setdefault(loaded.key.family, []).append((loaded, row))
    for fam, items in by_family.items():
        if fam == "c1_opportunity":
            out[fam] = _c1_behavior(items)
        elif fam == "c2_context":
            out[fam] = _c2_behavior(items)
        elif fam == "c3_cost":
            out[fam] = _c3_behavior(items)
    return out


def _c1_behavior(items) -> dict[str, Any]:
    """C1 selectivity:seg_state 2=positive opp / 1=neutral / 0=negative。"""
    buckets = {"positive": [], "neutral": [], "negative": []}
    for loaded, row in items:
        if row["actions"] is None:
            continue
        acts = np.asarray(row["actions"], dtype=int)
        seg = loaded.episode.hidden["seg_state"].to_numpy()[:len(acts)]
        for st, key in ((2, "positive"), (1, "neutral"), (0, "negative")):
            m = seg == st
            if m.any():
                buckets[key].append(acts[m])
    res: dict[str, Any] = {}
    for key, arrs in buckets.items():
        if arrs:
            all_acts = np.concatenate(arrs)
            res[f"long_rate_on_{key}"] = float(np.mean(all_acts == 1))
            res[f"n_{key}"] = int(len(all_acts))
        else:
            res[f"long_rate_on_{key}"] = None
            res[f"n_{key}"] = 0
    lr = res
    if (lr["long_rate_on_positive"] is not None
            and lr["long_rate_on_neutral"] is not None
            and lr["long_rate_on_negative"] is not None):
        res["selectivity_gap"] = lr["long_rate_on_positive"] - max(
            lr["long_rate_on_neutral"], lr["long_rate_on_negative"])
    else:
        res["selectivity_gap"] = None
    return res


def _c2_behavior(items) -> dict[str, Any]:
    """C2 gating:cue bar 上 aligned(门控同向) vs anti-aligned。

    active context:variant A = wick_dir_state,B = wick_width_state
    (hidden.active_gate_is_dir 记录绑定);按 variant 分开报告。
    """
    per_variant: dict[str, dict[str, list[np.ndarray]]] = {}
    for loaded, row in items:
        if row["actions"] is None:
            continue
        variant = loaded.key.variant
        acts = np.asarray(row["actions"], dtype=int)
        h = loaded.episode.hidden
        cue = h["cue_dir"].to_numpy()[:len(acts)]
        gate_dir = h["active_gate_is_dir"].to_numpy()[:len(acts)]
        ctx = np.where(
            gate_dir == 1,
            h["wick_dir_state"].to_numpy()[:len(acts)],
            h["wick_width_state"].to_numpy()[:len(acts)])
        cue_mask = cue != 0
        aligned = cue_mask & (cue * ctx > 0)
        anti = cue_mask & (cue * ctx < 0)
        acc = per_variant.setdefault(
            variant, {"aligned": [], "anti_aligned": []})
        if aligned.any():
            acc["aligned"].append(acts[aligned])
        if anti.any():
            acc["anti_aligned"].append(acts[anti])
    res: dict[str, Any] = {"per_variant": {}}
    all_al, all_anti = [], []
    for variant, acc in sorted(per_variant.items()):
        v = {}
        for key in ("aligned", "anti_aligned"):
            if acc[key]:
                cat = np.concatenate(acc[key])
                v[f"long_rate_{key}"] = float(np.mean(cat == 1))
                v[f"n_{key}"] = int(len(cat))
            else:
                v[f"long_rate_{key}"] = None
                v[f"n_{key}"] = 0
        if v["long_rate_aligned"] is not None and v[
                "long_rate_anti_aligned"] is not None:
            v["gating_gap"] = (
                v["long_rate_aligned"] - v["long_rate_anti_aligned"])
        else:
            v["gating_gap"] = None
        res["per_variant"][variant] = v
        all_al.extend(acc["aligned"])
        all_anti.extend(acc["anti_aligned"])
    if all_al and all_anti:
        la = float(np.mean(np.concatenate(all_al) == 1))
        lanti = float(np.mean(np.concatenate(all_anti) == 1))
        res["long_rate_aligned"] = la
        res["long_rate_anti_aligned"] = lanti
        res["gating_gap"] = la - lanti
        res["n_aligned"] = int(sum(len(a) for a in all_al))
        res["n_anti_aligned"] = int(sum(len(a) for a in all_anti))
    else:
        res["long_rate_aligned"] = None
        res["long_rate_anti_aligned"] = None
        res["gating_gap"] = None
        res["n_aligned"] = int(sum(len(a) for a in all_al))
        res["n_anti_aligned"] = int(sum(len(a) for a in all_anti))
    return res


def _c3_behavior(items) -> dict[str, Any]:
    """C3 cost selectivity:above_cost vs below/marginal 信号 bar + churn。"""
    above, below = [], []
    changes_total = 0
    steps_total = 0
    cost_total = 0.0
    for loaded, row in items:
        if row["actions"] is None:
            continue
        acts = np.asarray(row["actions"], dtype=int)
        h = loaded.episode.hidden
        strength = h["sig_strength"].to_numpy()[:len(acts)]
        above_cost = h["above_cost"].to_numpy()[:len(acts)]
        sig_mask = strength != 0.0
        m_above = sig_mask & (above_cost == 1)
        m_below = sig_mask & (above_cost == 0)
        if m_above.any():
            above.append(acts[m_above])
        if m_below.any():
            below.append(acts[m_below])
        changes_total += int(np.sum(np.diff(acts) != 0))
        steps_total += len(acts)
        cost_total += float(row["total_fees"])
    res: dict[str, Any] = {}
    for key, arrs in (("above_cost", above), ("below_cost", below)):
        if arrs:
            cat = np.concatenate(arrs)
            res[f"long_rate_{key}"] = float(np.mean(cat == 1))
            res[f"n_{key}"] = int(len(cat))
        else:
            res[f"long_rate_{key}"] = None
            res[f"n_{key}"] = 0
    if (res["long_rate_above_cost"] is not None
            and res["long_rate_below_cost"] is not None):
        res["cost_selectivity_gap"] = (
            res["long_rate_above_cost"] - res["long_rate_below_cost"])
    else:
        res["cost_selectivity_gap"] = None
    res["position_changes_per_100_steps"] = (
        100.0 * changes_total / steps_total) if steps_total else None
    res["transaction_cost_paid"] = cost_total
    res["n_trades_total"] = int(sum(
        row["n_trades"] for _, row in items))
    return res


# ---------------------------------------------------------------- 统计
def pair_cluster_bootstrap_ci(
    rows: list[dict[str, Any]], *, stat: str = "capture_pairs",
    n_boot: int = 2000, alpha: float = 0.10, seed: int = 26262626,
    capture_fn=None,
) -> dict[str, Any]:
    """pair-cluster bootstrap 90% pilot interval(§12)。

    rows 为逐 episode 行;capture_fn(pair_rows) -> float 计算 pair 集
    上的统计量(默认 mean net return);cluster = pair(A/B 不作独立
    样本)。
    """
    if capture_fn is None:
        def capture_fn(pair_rows):
            return float(np.mean([r["net_return"] for r in pair_rows]))
    pairs: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        pk = (r["family"], r["rung"], r["pair_index"])
        pairs.setdefault(pk, []).append(r)
    pair_keys = sorted(pairs)
    pair_values = np.array([capture_fn(pairs[k]) for k in pair_keys])
    point = float(np.mean(pair_values))
    rng = np.random.default_rng(seed)
    boots = np.array([
        np.mean(pair_values[rng.integers(0, len(pair_values),
                                          len(pair_values))])
        for _ in range(n_boot)])
    lo = float(np.percentile(boots, 100 * alpha / 2))
    hi = float(np.percentile(boots, 100 * (1 - alpha / 2)))
    return {
        "stat": stat,
        "n_pairs": len(pair_keys),
        "point": point,
        "ci90_low": lo,
        "ci90_high": hi,
        "median": float(np.median(pair_values)),
        "min": float(np.min(pair_values)),
        "max": float(np.max(pair_values)),
        "n_boot": n_boot,
        "seed": seed,
        "cluster": "pair(A/B 双端聚合为单一 cluster 单位)",
    }


# ---------------------------------------------------------------- retention
def retention_ratio(final_capture: float | None,
                    phase_capture: float | None) -> dict[str, Any]:
    """staged retention = final / phase(分母 <= 0 视为从未学会,§22)。"""
    if final_capture is None or phase_capture is None:
        return {"ratio": None, "phase_capture": phase_capture,
                "final_capture": final_capture,
                "status": "unavailable"}
    if phase_capture <= 0:
        return {"ratio": None, "phase_capture": phase_capture,
                "final_capture": final_capture,
                "status": "never_learned(denominator<=0)"}
    return {"ratio": final_capture / phase_capture,
            "phase_capture": phase_capture,
            "final_capture": final_capture, "status": "ok"}
