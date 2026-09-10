# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11:policy-visible reference 合同与 reference
equivalence 两层路径闭环(§8/§10/§11 Branch B/§18/§25)。

R9 确认输入:reference_equivalence_all=false 且只保存布尔值(72 episodes
的逐 episode 明细未落盘)。机制(本模块以两层路径严格区分):

Float64 Mathematical Path:
    raw float64 → transform float64 → inverse float64
    —— 检验 preprocessor 数学逆的正确性(应严格容差等价)。

Runtime Policy Path:
    raw float64 → transform float64 → cast float32(env 唯一投影点,
    rl_platform/env.py::_observation)→ cast float64 → inverse
    —— legacy raw 路径读 float32(raw),wrapped 路径读
    inverse(float32(transform(raw))),两者在决策阈值附近可翻转。

Branch B canonicalization(§11):canonical_raw_features =
inverse(float32(transform(raw_features)))。raw-side 与 scaled-side
(wrapped 逆变换)产生 bitwise 相同的 canonical raw,reference 决策
100% 相等;交易价格/reward/ledger 继续用原始市场数据。

合同硬边界:不修改 preprocessor;不修改 reference thresholds;不读取
raw side channel;不引入 latent;绑定 preprocessor bundle。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
)
from rl_curriculum.curriculum261_qualification import build_policy_set
from rl_curriculum.curriculum261_r3_obs import (
    r3_observation_schema,
    scaled_episode,
    wrap_policy_set,
)
from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG, RAW_SCHEMA
from rl_curriculum.curriculum261_r6_param_pack import (
    r6_family_rung_params,
)
from rl_curriculum.evaluator import run_policy_episode

#: 合同语义名(§8/§11/§16/§22 绑定)。
POLICY_VISIBLE_REFERENCE_CONTRACT = "PolicyVisibleReferenceCanonicalization-v1"
#: 监督标签合同语义名(§8)。
SUPERVISED_LABEL_CONTRACT = "PolicyVisibleSupervisedLabel-v1"

#: float32 相对量化上界(2^-24);mismatch 分类用 4 倍安全系数。
_FLOAT32_RELATIVE_QUANTUM = 2.0 ** -24
_FLOAT32_MARGIN_FACTOR = 4.0
#: float64 数学路径的严格绝对容差(MinMax 仿射逆 roundtrip 的 2-3
#: ULP float64 量级;相对界在近零特征值上病态,故用绝对界)。
_FLOAT64_ABS_TOL = 1e-14


# --------------------------------------------------------------- canonical
def canonicalize_feature_matrix(
        raw_features: np.ndarray, preproc: Any) -> np.ndarray:
    """canonical_raw_features = inverse(float32(transform(raw)))。

    输入 (n, 8) float64 raw 特征矩阵;输出 (n, 8) float64 canonical。
    与生产 runtime 投影完全同式:transform float64 → env float32 cast
    → wrapper float64 → inverse_features。
    """
    x = np.asarray(raw_features, dtype=np.float64)
    import pandas as pd

    df = pd.DataFrame(x, columns=list(PRODUCTION_FEATURE_COLUMNS))
    t64 = preproc.transform(df).to_numpy(dtype=np.float64)
    t32 = t64.astype(np.float32)
    return preproc.inverse_features(t32.astype(np.float64))


def canonical_episode(episode: Any, preproc: Any) -> Any:
    """episode 的 8 特征列替换为 canonical 值(价格/隐藏字段不变)。

    价格列保持原始市场数据 —— 交易价格/reward/ledger 语义不变
    (§11 Branch B 的硬边界)。canonical episode 上运行的 raw policy
    与 scaled episode 上的 wrapped policy 决策逐位一致(见
    reference_equivalence_run_r11 的 canonical 路径证明)。
    """
    import dataclasses

    df = episode.df
    raw_x = df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(dtype=np.float64)
    canon = canonicalize_feature_matrix(raw_x, preproc)
    out = df.copy()
    for j, col in enumerate(PRODUCTION_FEATURE_COLUMNS):
        out[col] = canon[:, j]
    return dataclasses.replace(episode, df=out)


def policy_visible_reference_contract_payload(
        preproc_v2: Any) -> dict[str, Any]:
    """合同身份(进入 design/final plan identity;§16/§22)。"""
    return {
        "contract": POLICY_VISIBLE_REFERENCE_CONTRACT,
        "definition": ("canonical_raw_features = inverse(float32("
                       "transform(raw_features)))"),
        "raw_side": "canonical episode(价格列原始市场数据不变)",
        "scaled_side": ("wrapped policy 逆变换(inverse_features on "
                        "float64(float32(scaled obs)))"),
        "equality_claim": ("canonical raw path 与 wrapped scaled path "
                           "的 observation-aware 决策逐位一致"),
        "does_not_modify": [
            "preprocessor", "reference thresholds", "C2 generator",
            "matched ladder", "Cue Contract v2"],
        "no_raw_side_channel": True,
        "no_latent": True,
        "bound_to_bundle": {
            "fit_namespace": getattr(
                preproc_v2, "namespace",
                "reference_diagnostic_main_r11"),
            "bundle_hash": getattr(preproc_v2, "bundle_hash",
                                      "unbundled-diagnostic"),
            "parameter_state_hash": getattr(
                preproc_v2, "parameter_state_hash",
                "unbundled-diagnostic"),
        },
        "float32_projection_point": "rl_platform/env.py::_observation",
    }


def policy_visible_reference_contract_static_digest() -> str:
    """合同级 digest(不含 bundle 绑定;design plan 锁定阶段用)。

    calibrate/final 阶段的完整 payload(含 bound_to_bundle)另算;
    两级 digest 都以 r11pv- 前缀进入对应 plan identity。
    """
    payload = policy_visible_reference_contract_payload_static()
    return policy_visible_reference_contract_digest(payload)


def policy_visible_reference_contract_payload_static() -> dict[str, Any]:
    """§11 合同的静态身份(canonical 定义与硬边界,零运行态)。"""
    return {
        "contract": POLICY_VISIBLE_REFERENCE_CONTRACT,
        "definition": ("canonical_raw_features = inverse(float32("
                       "transform(raw_features)))"),
        "raw_side": "canonical episode(价格列原始市场数据不变)",
        "scaled_side": ("wrapped policy 逆变换(inverse_features on "
                        "float64(float32(scaled obs)))"),
        "equality_claim": ("canonical raw path 与 wrapped scaled path "
                           "的 observation-aware 决策逐位一致"),
        "does_not_modify": [
            "preprocessor", "reference thresholds", "C2 generator",
            "matched ladder", "Cue Contract v2"],
        "no_raw_side_channel": True,
        "no_latent": True,
        "float32_projection_point": "rl_platform/env.py::_observation",
        "binding_levels": {
            "static": "design plan(pre-bundle)",
            "bundle": "preprocessing robustness / final(bundle hash)",
        },
    }


def policy_visible_reference_contract_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return "r11pv-" + hashlib.sha256(
        canonical.encode("utf-8")).hexdigest()


# ------------------------------------------------------------ 两层数值路径
def float64_math_path_check(
        raw_features: np.ndarray, preproc: Any) -> dict[str, Any]:
    """§10.1 Float64 Mathematical Path:transform→inverse 严格容差。"""
    import pandas as pd

    x = np.asarray(raw_features, dtype=np.float64)
    df = pd.DataFrame(x, columns=list(PRODUCTION_FEATURE_COLUMNS))
    t64 = preproc.transform(df).to_numpy(dtype=np.float64)
    back = preproc.inverse_features(t64)
    err = np.abs(back - x)
    scale = np.maximum(np.abs(x), 1e-300)
    rel = err / scale
    return {
        "path": "float64_mathematical",
        "n_rows": int(x.shape[0]),
        "max_abs_reconstruction_error": float(np.max(err)),
        "max_relative_reconstruction_error": float(np.max(rel)),
        "abs_tol": _FLOAT64_ABS_TOL,
        "pass": bool(np.max(err) <= _FLOAT64_ABS_TOL),
    }


def runtime_projection_path_stats(
        raw_features: np.ndarray, preproc: Any) -> dict[str, Any]:
    """§10.1 Runtime Policy Path 的量化效应统计(非 gate,诊断)。"""
    x = np.asarray(raw_features, dtype=np.float64)
    canon = canonicalize_feature_matrix(x, preproc)
    diff = np.abs(canon - x)
    # bound 基于特征量级下限 0.1(bps 量级特征域;MinMax range ~O(0.1))
    scale = np.maximum(np.abs(x), 1e-300)
    bound = (_FLOAT32_MARGIN_FACTOR * _FLOAT32_RELATIVE_QUANTUM
             * np.maximum(np.abs(x), np.maximum(np.abs(canon), 0.1)))
    return {
        "path": "runtime_float32_projection",
        "n_rows": int(x.shape[0]),
        "max_abs_projection_deviation": float(np.max(diff)),
        "max_relative_projection_deviation": float(
            np.max(diff / scale)),
        "float32_relative_quantum": _FLOAT32_RELATIVE_QUANTUM,
        "float32_bound_scale_floor": 0.1,
        "all_within_float32_bound": bool(np.all(diff <= bound)),
    }


# ------------------------------------------------- equivalence(正式/诊断)
def _policy_thresholds(policy: Any) -> dict[str, float]:
    """policy 决策条件的 float 参数(诊断用;只读属性不改行为)。"""
    out: dict[str, float] = {}
    for k, v in vars(policy).items():
        if isinstance(v, float):
            out[k] = float(v)
    return out


def _obs_margin_to_thresholds(obs: np.ndarray,
                              thresholds: dict[str, float]) -> float:
    """observation 各维与各 threshold 的最小 |margin|(近似决策距离)。"""
    margins: list[float] = []
    for thr in thresholds.values():
        margins.extend(float(abs(float(x) - thr)) for x in obs[:8])
    return min(margins) if margins else float("inf")


def _float32_explainable(obs_a: np.ndarray, obs_b: np.ndarray,
                         thresholds: dict[str, float]) -> tuple[bool, float]:
    """两路径 obs 差是否全部在 float32 量化界内(边界解释判定)。"""
    diff = np.abs(np.asarray(obs_a, dtype=np.float64)
                  - np.asarray(obs_b, dtype=np.float64))[:8]
    bound = (_FLOAT32_MARGIN_FACTOR * _FLOAT32_RELATIVE_QUANTUM
             * np.maximum(
                 np.maximum(np.abs(np.asarray(obs_a, dtype=np.float64)[:8]),
                            np.abs(np.asarray(obs_b, dtype=np.float64)[:8])),
                 0.1))
    margin = _obs_margin_to_thresholds(obs_a, thresholds)
    return bool(np.all(diff <= bound)), float(margin)


def reference_equivalence_run_r11(
        records: list[Any], preproc_v2: Any, pack: dict[str, Any], *,
        eval_namespace: str, rung_params_fn: Any = None,
        ledger: Any = None, expected_bundle_hash: str | None = None,
        detailed: bool = True, mismatch_limit: int = 20,
) -> dict[str, Any]:
    """§18/§25 正式 reference equivalence(canonical 口径)+ legacy 差异。

    对每 record/side/observation-aware policy:
    - canonical 路径:raw policy on canonical episode;
    - scaled 路径:wrapped policy on scaled episode(生产语义);
    - legacy 路径(诊断输出):raw policy on raw episode —— 与 canonical
      的差异必须全部可由 float32 投影边界解释,任何 unexplained 即 fail。

    等价判定(gate):canonical vs scaled 的 action 与 net_return 逐位
    相等;unexplained_mismatches == 0。
    """
    rung_params_fn = rung_params_fn or (
        lambda family, pk: r6_family_rung_params(family, pk))
    specs = family_specs()
    preproc = (preproc_v2.inner if hasattr(preproc_v2, "inner")
                else preproc_v2)
    inner = preproc
    schema = (r4_observation_schema(preproc_v2)
               if hasattr(preproc_v2, "bundle_hash")
               else r3_observation_schema(preproc))
    per_episode: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    unexplained = 0
    legacy_action_diffs = 0
    canonical_ok = True
    float64_path = None
    # §10.1:两层路径(全部 episodes 的 raw 特征矩阵聚合)
    raw_all = np.concatenate([
        rec.episodes[s].df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(
            dtype=np.float64)
        for rec in records for s in ("A", "B")], axis=0)
    float64_path = float64_math_path_check(raw_all, inner)
    runtime_stats = runtime_projection_path_stats(raw_all, inner)

    for rec in records:
        family = rec.family
        thresholds = dict(specs[family].reference_defaults)
        rung_params = dict(rung_params_fn(family, pack)[rec.rung])
        rung_params["cur261_rung"] = rec.rung
        raw_set = build_policy_set(family, rung_params, thresholds)
        wrapped_set = wrap_policy_set(raw_set, inner)
        for side in ("A", "B"):
            ep = rec.episodes[side]
            canon_ep = canonical_episode(ep, inner)
            scaled_ep = scaled_episode(ep, inner)
            raw_x64 = ep.df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(
                dtype=np.float64)
            t64 = inner.transform(ep.df[list(
                PRODUCTION_FEATURE_COLUMNS)]).to_numpy(dtype=np.float64)
            ep_report: dict[str, Any] = {
                "family": family, "rung": rec.rung,
                "pair": rec.pair_index, "side": side,
                "episode_seed": int(ep.spec.seed),
                "bundle_hash": getattr(preproc_v2, "bundle_hash",
                                      "unbundled-diagnostic"),
                "fit_namespace": getattr(
                preproc_v2, "namespace",
                "reference_diagnostic_main_r11"),
                "policies": {},
            }
            ep_ok = True
            for name, raw_pol in raw_set.items():
                if name in ("always_flat", "always_long"):
                    continue  # 无输入基线:不经 observation,天然等价
                # policy state 排查记录(§10.3):全新 policy 对象、
                # 每 episode episode_instance/reset_episode、无复用。
                r_canon = run_policy_episode(
                    raw_pol, canon_ep, EVAL_CFG, RAW_SCHEMA,
                    return_actions=True, return_observations=True)
                r_scl = run_policy_episode(
                    wrapped_set[name], scaled_ep, EVAL_CFG, schema,
                    return_actions=True, return_observations=True)
                r_legacy = run_policy_episode(
                    raw_pol, ep, EVAL_CFG, RAW_SCHEMA,
                    return_actions=True, return_observations=True)
                a_canon, a_scl, a_legacy = (
                    list(r_canon[1]), list(r_scl[1]), list(r_legacy[1]))
                ret_canon, ret_scl = (
                    float(r_canon[0].net_return), float(r_scl[0].net_return))
                actions_equal = a_canon == a_scl
                return_equal = ret_canon == ret_scl
                legacy_diff_t = [i for i, (x, y) in enumerate(
                    zip(a_legacy, a_scl)) if x != y]
                legacy_action_diffs += len(legacy_diff_t)
                pol_thr = _policy_thresholds(raw_pol)
                for t in legacy_diff_t[:max(1, mismatch_limit)]:
                    obs_legacy = np.asarray(r_legacy[2][t])
                    obs_scl = np.asarray(r_scl[2][t])
                    canon64 = inner.inverse_features(
                        obs_scl[:8].astype(np.float64).reshape(1, -1))[0]
                    explainable, margin = _float32_explainable(
                        obs_legacy[:8].astype(np.float64), canon64, pol_thr)
                    if not explainable:
                        unexplained += 1
                    if detailed and len(mismatches) < mismatch_limit:
                        mismatches.append({
                            "family": family, "rung": rec.rung,
                            "pair": rec.pair_index, "side": side,
                            "policy": name, "timestep": int(t),
                            "raw_action": int(a_legacy[t]),
                            "wrapped_action": int(a_scl[t]),
                            "canonical_action": int(a_canon[t]),
                            "raw_net_return": float(
                                r_legacy[0].net_return),
                            "wrapped_net_return": ret_scl,
                            "raw_obs_float32": obs_legacy.tolist(),
                            "scaled_float64_obs_row": (
                                t64[t].tolist() if t < len(t64) else None),
                            "scaled_float32_obs_row": (
                                np.float32(t64[t]).tolist()
                                if t < len(t64) else None),
                            "inverse_obs_float64": canon64.tolist(),
                            "per_feature_reconstruction_error": (
                                np.abs(canon64 - raw_x64[t]).tolist()
                                if t < len(raw_x64) else None),
                            "position": float(obs_legacy[-1]),
                            "policy_conditions": pol_thr,
                            "decision_margin_to_threshold": margin,
                            "float32_relative_quantum":
                                _FLOAT32_RELATIVE_QUANTUM,
                            "explainable_by_float32_boundary": explainable,
                            "bundle_hash": getattr(preproc_v2, "bundle_hash",
                                      "unbundled-diagnostic"),
                            "policy_state": {
                                "fresh_policy_objects": True,
                                "per_episode_instance_reset": True,
                                "n_decisions": len(a_scl),
                                "action_length_equal": bool(
                                    len(a_legacy) == len(a_scl)
                                    == len(a_canon)),
                            },
                        })
                ok = actions_equal and return_equal
                ep_ok = ep_ok and ok
                ep_report["policies"][name] = {
                    "canonical_vs_scaled_actions_equal": actions_equal,
                    "canonical_vs_scaled_net_return_equal": return_equal,
                    "canonical_net_return": ret_canon,
                    "scaled_net_return": ret_scl,
                    "legacy_vs_scaled_action_diffs": len(legacy_diff_t),
                    "n_decisions": len(a_scl),
                }
            ep_report["pass"] = bool(ep_ok)
            canonical_ok = canonical_ok and ep_ok
            per_episode.append(ep_report)
    result = {
        "format": "cur261-r11-reference-equivalence-v1",
        "iteration": "r11",
        "eval_namespace": eval_namespace,
        "contract": POLICY_VISIBLE_REFERENCE_CONTRACT,
        "contract_digest": policy_visible_reference_contract_digest(
            policy_visible_reference_contract_payload(preproc_v2)),
        "float64_math_path": float64_path,
        "runtime_projection_stats": runtime_stats,
        "n_episodes": len(per_episode),
        "canonical_scaled_full_equality": bool(canonical_ok),
        "legacy_action_diffs_total": int(legacy_action_diffs),
        "unexplained_mismatches": int(unexplained),
        "mismatches": mismatches,
        "n_mismatches_recorded": len(mismatches),
        "n_episodes_canonical_gate_failed": int(
            sum(1 for e in per_episode if not e["pass"])),
        "per_episode": per_episode,
        "pass": bool(canonical_ok and unexplained == 0
                     and float64_path["pass"]),
    }
    return result


def write_reference_equivalence_artifacts_r11(
        out_dir: Path, report: dict[str, Any], *,
        stem: str) -> None:
    """落盘 equivalence 报告 + mismatch artifact(§18:即使为空也必须存在)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    mism = {
        "format": "cur261-r11-reference-mismatches-v1",
        "eval_namespace": report["eval_namespace"],
        "n_mismatches": int(report.get("unexplained_mismatches", 0)),
        "legacy_action_diffs_total": int(
            report.get("legacy_action_diffs_total", 0)),
        "mismatches": report.get("mismatches", []),
        "explicit": ("n_mismatches 为 unexplained 口径;legacy 差异"
                     "全部记录于 mismatches 列表(float32 边界解释)"
                     "——不再只保存一个布尔值"),
    }
    (out_dir / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / f"{stem}_mismatches.json").write_text(
        json.dumps(mism, ensure_ascii=False, indent=1), encoding="utf-8")
