"""阶段 2.6.2 Repair R2:family-aware 评估器(R1 mixed-family 缺陷修复)。

R1 根因:`_eval_d0_capture()` 以 `bank[0].key.family` 的 reference /
baselines 评估整个 mixed-family bank —— C2/C3 cells 的 capture 全部
以 C1 reference(在 C2/C3 episode 上运行)计算,数字无效。

R2 合同:

- evaluate_single_family_bank:单族 bank 专用;收到 mixed bank 必须
  报错(MixedFamilyBankError);
- evaluate_mixed_family_bank:显式按 family × rung 分组,每个 cell 用
  该 family/rung 的正确 reference policy 与 required baselines;
- 每个 evaluation cell 记录 reference identity(class / module /
  threshold 解析值 / required baseline names / manifest hash),可
  追溯证明 C2/D1 用的是 C2ReferencePolicy、C3/D1 用的是
  C3ReferencePolicy;
- denominator sanity:R <= B 的 cell 标记 invalid_reference_gap,
  capture = None,从 branch 判定中排除,绝不当作普通数值解释;
- probability 评估禁止 first-N 切片:probability family 摘要必须
  逐族给出样本计数,并验证非零。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np


class MixedFamilyBankError(ValueError):
    """单族评估器收到 mixed-family bank(合同违规,fail closed)。"""


# ---------------------------------------------------------------- 分组
def bank_family_counts(bank) -> dict[str, int]:
    counts: dict[str, int] = {}
    for e in bank:
        counts[e.key.family] = counts.get(e.key.family, 0) + 1
    return counts


def assert_single_family(bank) -> str:
    counts = bank_family_counts(bank)
    if len(counts) != 1:
        raise MixedFamilyBankError(
            f"evaluate_single_family_bank 收到 mixed-family bank:"
            f"{counts};单族评估器拒绝 mixed bank(必须先按 family 分组)")
    if not counts:
        raise MixedFamilyBankError("bank 为空")
    return next(iter(counts))


def _group_by_family_rung(bank) -> dict[tuple[str, str], list]:
    out: dict[tuple[str, str], list] = {}
    for e in bank:
        out.setdefault((e.key.family, e.key.rung), []).append(e)
    return out


def _cell_manifest_hash(episodes) -> str:
    payload = json.dumps([e.key.canonical() for e in episodes],
                         sort_keys=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- identity
#: family -> reference policy 类名(构建后校验;防 reference 挂错)
EXPECTED_REFERENCE_CLASS = {
    "c1_opportunity": "C1ReferencePolicy",
    "c2_context": "C2ReferencePolicy",
    "c3_cost": "C3ReferencePolicy",
}


def reference_identity(family: str, rung_params_entry: dict[str, Any],
                       thresholds_entry: dict[str, Any],
                       policy_set: dict[str, Any]) -> dict[str, Any]:
    """一个 (family, rung) cell 的 reference 身份记录。"""
    ref = policy_set["reference"]
    cls = type(ref).__name__
    expected = EXPECTED_REFERENCE_CLASS.get(family)
    return {
        "family": family,
        "reference_class": cls,
        "reference_module": type(ref).__module__,
        "reference_class_matches_family_contract": (
            expected is None or cls == expected),
        "threshold_identity": {
            "rung_params_keys": sorted(rung_params_entry.keys()),
            "rung_params": {k: v for k, v in
                            sorted(rung_params_entry.items())},
            "reference_thresholds": dict(thresholds_entry),
        },
        "required_baselines": sorted(
            k for k in policy_set if k != "reference"),
    }


# ---------------------------------------------------------------- 评估
def evaluate_family_cells(
    model_or_policy, bank, rung_params: dict[str, Any],
    thresholds: dict[str, Any], *, adapter=None,
    reference_cache: dict | None = None,
) -> dict[str, Any]:
    """family-aware 评估:bank(单族或 mixed)按 family × rung 分 cell。

    每个 cell 在**该 family/rung 的 episode slice** 上运行 PPO /
    reference / required baselines,reference/baseline 构建自该 family
    的 rung 参数与阈值。禁止任何 bank[0].family / first-N shortcut。
    """
    from rl_curriculum.ppo262_diag_train import ScaledEvalPolicy
    from rl_curriculum.ppo262_metrics import (
        PPO262_REQUIRED_BASELINES, behavior_metrics, build_261_policy_set,
        evaluate_policy_on_bank, SB3PPOPolicy,
    )

    if adapter is None:
        if hasattr(model_or_policy, "reset_episode"):
            policy = model_or_policy
        else:
            policy = SB3PPOPolicy(model_or_policy, "diag-ppo-r2")
    else:
        policy = ScaledEvalPolicy(model_or_policy, adapter, "diag-r2")

    families = sorted(bank_family_counts(bank))
    out: dict[str, Any] = {
        "format": "ppo262-repair2-family-eval-v1",
        "n_episodes_total": len(bank),
        "family_episode_counts": bank_family_counts(bank),
        "grouping": "family × rung(显式分组;无 bank[0].family 推断)",
        "cells": {},
        "identity_matrix": {},
    }
    for fam in families:
        fam_bank = [e for e in bank if e.key.family == fam]
        fam_ppo_rows: list[dict[str, Any]] = []
        out["cells"][fam] = {}
        for (f, rung), eps in sorted(_group_by_family_rung(fam_bank).items()):
            assert f == fam
            if reference_cache is not None and (fam, rung) in reference_cache:
                cached = reference_cache[(fam, rung)]
                pols, ref_rows, baseline_rows, ident = cached
            else:
                pols = build_261_policy_set(
                    fam, rung_params[fam][rung], thresholds[fam])
                ref_rows = evaluate_policy_on_bank(
                    pols["reference"], eps, collect_actions=False)
                baseline_rows = {}
                for bname in PPO262_REQUIRED_BASELINES[fam]:
                    baseline_rows[bname] = evaluate_policy_on_bank(
                        pols[bname], eps, collect_actions=False)
                ident = reference_identity(
                    fam, rung_params[fam][rung], thresholds[fam], pols)
                if reference_cache is not None:
                    reference_cache[(fam, rung)] = (
                        pols, ref_rows, baseline_rows, ident)
            ppo_rows = evaluate_policy_on_bank(policy, eps)
            fam_ppo_rows.extend(ppo_rows)
            ref_mean = float(np.mean([r["net_return"] for r in ref_rows]))
            base_means = {
                name: float(np.mean([r["net_return"] for r in rows]))
                for name, rows in baseline_rows.items()}
            best_name = max(base_means, key=base_means.get)
            b = base_means[best_name]
            p = float(np.mean([r["net_return"] for r in ppo_rows]))
            denom = ref_mean - b
            valid = bool(denom > 0.0)
            cell = {
                "family": fam,
                "rung": rung,
                "n_episodes": len(eps),
                "reference_identity": ident,
                "episode_manifest_sha256": _cell_manifest_hash(eps),
                "ppo_mean": p,
                "reference_mean": ref_mean,
                "baseline_means": base_means,
                "best_baseline": best_name,
                "denominator": denom,
                "reference_gap_valid": valid,
                "status": "ok" if valid else "invalid_reference_gap",
                "capture": (p - b) / denom if valid else None,
            }
            out["cells"][fam][rung] = cell
            out["identity_matrix"][f"{fam}/{rung}"] = {
                "reference_class": ident["reference_class"],
                "reference_class_matches_family_contract": ident[
                    "reference_class_matches_family_contract"],
                "required_baselines": ident["required_baselines"],
                "episode_manifest_sha256": cell["episode_manifest_sha256"],
            }
        # behavior 由同一批 ppo_rows(含 actions)计算,不重跑 env
        out.setdefault("behavior", {})[fam] = behavior_metrics(
            fam_ppo_rows, fam_bank).get(fam)
    return out


def evaluate_single_family_bank(
    model_or_policy, bank, rung_params, thresholds, *, adapter=None,
    reference_cache: dict | None = None,
) -> dict[str, Any]:
    """单族 bank 评估(mixed bank -> MixedFamilyBankError)。"""
    fam = assert_single_family(bank)
    result = evaluate_family_cells(
        model_or_policy, bank, rung_params, thresholds, adapter=adapter,
        reference_cache=reference_cache)
    result["evaluator"] = "evaluate_single_family_bank"
    result["single_family"] = fam
    return result


def evaluate_mixed_family_bank(
    model_or_policy, bank, rung_params, thresholds, *, adapter=None,
) -> dict[str, Any]:
    """mixed bank 评估:显式 family × rung 分组(等价于逐族调用)。"""
    result = evaluate_family_cells(
        model_or_policy, bank, rung_params, thresholds, adapter=adapter)
    result["evaluator"] = "evaluate_mixed_family_bank"
    result["grouped_families"] = sorted(result["family_episode_counts"])
    return result


#: family core capture 权重(与 official PPO262_CORE_RUNG_WEIGHTS 同款)
_CORE_WEIGHTS = {"D0": 0.20, "D1": 0.30, "D2": 0.50}


def family_eval_capture(family: str, cells: dict[str, Any]) -> dict[str, Any]:
    """family 的 eval capture:valid cells 的 core 加权(权重按 valid 集
    重归一;要求 D1 valid 且 >= 2 个 valid cell,否则 evidence 无效)。

    invalid_reference_gap cell 一律排除(§5.4)。
    """
    fam_cells = cells.get(family, {})
    valid = {r: c for r, c in fam_cells.items()
             if c.get("reference_gap_valid")}
    invalid = sorted(r for r, c in fam_cells.items()
                     if not c.get("reference_gap_valid"))
    if "D1" not in valid or len(valid) < 2:
        return {
            "family": family, "valid": False,
            "reason": "insufficient_valid_cells(D1 必须 valid 且 >=2 个"
                      " valid cell)",
            "valid_cells": sorted(valid), "invalid_cells": invalid,
            "capture": None,
        }
    wsum = sum(_CORE_WEIGHTS[r] for r in valid)
    cap = sum(_CORE_WEIGHTS[r] * valid[r]["capture"]
              for r in valid) / wsum
    return {
        "family": family, "valid": True,
        "valid_cells": sorted(valid), "invalid_cells": invalid,
        "weights_renormalized": {r: _CORE_WEIGHTS[r] / wsum
                                 for r in valid},
        "capture": float(cap),
    }


# ------------------------------------------------------- probability 分族
def family_probability_summary(prob: dict[str, Any], family: str) -> dict:
    """单族 probability 摘要(probability_metrics_on_bank 的输出)。

    输出该族自身的 probability gap / deterministic gap / latent 类样本
    计数;类计数为 0 视为采样不足(不得用于 branch 证据)。
    """
    per = prob.get("per_family", {}).get(family, {})
    key_gap = {
        "c1_opportunity": ("positive", "neutral", "negative"),
        "c2_context": ("aligned", "anti_aligned", None),
        "c3_cost": ("above_cost", "below_cost", None),
    }[family]
    out: dict[str, Any] = {
        "family": family,
        "class_sample_counts": {
            name: (per.get(name) or {}).get("n", 0)
            for name in [k for k in key_gap if k]},
    }
    if family == "c1_opportunity":
        pos = (per.get("positive") or {}).get("mean_p_long")
        neu = (per.get("neutral") or {}).get("mean_p_long")
        neg = (per.get("negative") or {}).get("mean_p_long")
        if None not in (pos, neu, neg):
            out["probability_gap"] = pos - max(neu, neg)
            out["det_gap"] = ((per.get("positive") or {}).get(
                "deterministic_long_rate", 0.0) - max(
                (per.get("neutral") or {}).get(
                    "deterministic_long_rate", 0.0),
                (per.get("negative") or {}).get(
                    "deterministic_long_rate", 0.0)))
    elif family == "c2_context":
        al = (per.get("aligned") or {}).get("mean_p_long")
        anti = (per.get("anti_aligned") or {}).get("mean_p_long")
        if None not in (al, anti):
            out["probability_gap"] = al - anti
            out["det_gap"] = ((per.get("aligned") or {}).get(
                "deterministic_long_rate", 0.0)
                - (per.get("anti_aligned") or {}).get(
                    "deterministic_long_rate", 0.0))
    else:
        ab = (per.get("above_cost") or {}).get("mean_p_long")
        be = (per.get("below_cost") or {}).get("mean_p_long")
        if None not in (ab, be):
            out["probability_gap"] = ab - be
            out["det_gap"] = ((per.get("above_cost") or {}).get(
                "deterministic_long_rate", 0.0)
                - (per.get("below_cost") or {}).get(
                    "deterministic_long_rate", 0.0))
    out["sampling_sufficient"] = all(
        v > 0 for v in out["class_sample_counts"].values())
    return out


def family_behavior_gap(behavior: dict[str, Any], family: str) -> dict:
    """单族 deterministic behavior gap(evaluate_family_cells.behavior)。"""
    fam = behavior.get(family) or {}
    key = {
        "c1_opportunity": "selectivity_gap",
        "c2_context": "gating_gap",
        "c3_cost": "cost_selectivity_gap",
    }[family]
    return {"family": family, "det_behavior_gap": fam.get(key),
            "detail": fam}


class CrossFamilyEvidenceError(ValueError):
    """recovery 证据跨 family 拼接(禁止;fail closed)。"""


def family_recovery_evidence(family: str, fam_cap: dict[str, Any],
                             prob_sum: dict[str, Any],
                             beh: dict[str, Any]) -> dict[str, Any]:
    """单族 recovery 证据组装(四类证据必须全部来自同一 family)。

    任何输入的 family 字段与 family 不一致 -> CrossFamilyEvidenceError
    (禁止 C1 capture 与 C3 probability gap 组合)。
    """
    for name, d in (("capture", fam_cap), ("probability", prob_sum),
                    ("behavior", beh)):
        got = d.get("family")
        if got is not None and got != family:
            raise CrossFamilyEvidenceError(
                f"recovery 证据跨 family 拼接:{name} 证据来自 {got!r},"
                f"判定目标为 {family!r}")
    return {"family": family, "capture": fam_cap,
            "probability": prob_sum, "behavior": beh}


def decide_family_branch(*, unscaled_recovered: bool,
                         scaled_recovered: bool,
                         linear_all_fail: bool,
                         class_balanced_all_fail: bool,
                         bc_executed: bool,
                         bc_retained_2of3: bool,
                         bc_destroyed_2of3: bool) -> str:
    """family branch 判定(预注册顺序;cmd_family_decision 与测试共用)。

    A: unscaled scratch 恢复;B: 仅 scaled 恢复;E: linear 与
    class-balanced MLP 全 arms 失败;C: BC 学会且保留;D: BC 学会但
    被摧毁;F: 其余(分裂/不充分)。
    """
    if unscaled_recovered:
        return "A"
    if scaled_recovered:
        return "B"
    if linear_all_fail and class_balanced_all_fail:
        return "E"
    if bc_executed and bc_retained_2of3:
        return "C"
    if bc_executed and bc_destroyed_2of3:
        return "D"
    return "F"
