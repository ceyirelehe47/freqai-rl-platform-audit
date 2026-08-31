"""阶段 2.6.2 Repair R1:diagnostic workflow CLI(与 official 完全分离)。

命令族(全部只写 artifacts/route_c_stage2_6_2/repair1/):

- diagnose-namespace-integrity  诊断 namespace 隔离枚举证明
- repair-verify                harness 修复在 s262_r0 数据上的行为验证
- diagnose-feature-scale       特征尺度 profile + 第一层激活分析(不训练)
- diagnose-plan-lock           诊断计划锁定(ablation/BC 运行前冻结)
- diagnose-supervised          静态监督可学习性探针(linear+MLP)
- diagnose-overfit             tiny D0 过拟合诊断(C1/C2/C3 × 3 seeds)
- diagnose-preprocessing       A/B/C preprocessing ablation(严格配对)
- diagnose-bc-warmstart        BC warm-start(条件触发)
- diagnose-decision            决策树分支判定
- diagnose-summary             诊断汇总

诊断命令不得生成 official PASS、不得写 official final plan、
不得消费 ppo_final_eval_262、不得复用 official final namespace。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES, CURRICULUM261_RUNGS,
    qualification_r2_lock_marker,
)
from rl_curriculum.ppo262_namespaces import ppo262_artifacts_dir

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPAIR1_DIR = ppo262_artifacts_dir() / "repair1"
DIAG_MODELS_DIR = PROJECT_ROOT / "models" / "ppo262" / "repair1"

#: 本轮基线(任务书):s262_r0 FAIL 检查点;父提交 = 2.6.1 R2
R1_BASELINE_SHA = "7481b39b3d141a21b845a111b9f48e036c5f98f5"
R2_PASS_SHA = "1927faa647d34e4f45ed9c46d100f500081560b8"
VENDOR_SHA = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"


def _w(name: str, payload: Any) -> Path:
    REPAIR1_DIR.mkdir(parents=True, exist_ok=True)
    p = REPAIR1_DIR / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                            default=_np_default), encoding="utf-8")
    return p


def _np_default(o):
    import numpy as np
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"不可序列化: {type(o)}")


def _locked_rung_params() -> dict[str, Any]:
    from rl_curriculum.curriculum261_plan import load_locked_plan
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["rung_params"] for fam, fp in plan["families"].items()}


def _locked_reference_thresholds() -> dict[str, Any]:
    from rl_curriculum.curriculum261_plan import load_locked_plan
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["reference_thresholds"]
            for fam, fp in plan["families"].items()}


def _r2_plan_digest() -> str:
    from rl_curriculum.ppo262_input_lock import R2_EXPECTED_PLAN_DIGEST
    return R2_EXPECTED_PLAN_DIGEST


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_identity_diag() -> dict[str, str]:
    out = {}
    for f in sorted((PROJECT_ROOT / "src" / "rl_curriculum").glob(
            "ppo262*.py")):
        out[f.name] = _sha256_file(f)
    return out


def _route_c_integrity() -> dict[str, Any]:
    from rl_curriculum.ppo262_input_lock import run_input_lock
    art = run_input_lock()
    return {
        "rl_platform_tree_hash": art["rl_platform_tree_hash"]["now"],
        "route_c_frozen_versions": art["route_c_frozen_versions"],
        "r2_plan_digest": art["r2_plan_digest"],
        "input_lock_pass": art["pass"],
        "vendor_sha": art["vendor"]["sha"],
        "vendor_clean": not art["vendor"]["status_porcelain"],
    }


# ============================================================ bank 构造
def _diag_bank_keys(namespace: str, families, rungs, n_pairs: int,
                    pair_base: int) -> list:
    """诊断 bank keys(staged 顺序:family -> rung -> pair -> variant)。"""
    from rl_curriculum.ppo262_banks import EpisodeKey
    keys = []
    for fam in families:
        for rung in rungs:
            for j in range(n_pairs):
                for v in ("A", "B"):
                    keys.append(EpisodeKey(
                        namespace, fam, rung, pair_base + j, v))
    return keys


def _gen_diag_bank(namespace: str, families, rungs, n_pairs: int,
                   pair_base: int, *, progress: bool = True):
    from rl_curriculum.ppo262_banks import generate262_bank
    from rl_curriculum.ppo262_diag_namespaces import derive262_diag_seed
    keys = _diag_bank_keys(namespace, families, rungs, n_pairs, pair_base)
    return generate262_bank(
        keys, locked_plan_rung_params=_locked_rung_params(),
        progress=progress, derive_seed_fn=derive262_diag_seed)


# ============================================================ 基础 artifacts
def cmd_namespace_integrity(args) -> int:
    from rl_curriculum.ppo262_diag_namespaces import (
        DIAG262_NAMESPACES, verify_diag_namespace_isolation,
    )
    t0 = time.time()
    art = verify_diag_namespace_isolation(
        pair_range=range(0, 1024),
        official_pair_range=range(0, 2048),
        pair_range_261=range(0, 2048))
    art["namespaces_official_262_preserved"] = "s262_r0 11 个 namespace" \
        " 不变(ppo262_namespaces.all_262_namespaces)"
    art["enumeration_note"] = (
        "diag 枚举 range(0,1024) 覆盖全部诊断 pair 区间(3 seed 槽位 "
        "x32 + eval +256 偏移);official/2.6.1 以合并集交集验证"
        "(range(0,2048))")
    _w("diagnostic_namespace_integrity.json", art)
    print(json.dumps({"pass": art["pass"], "problems": art["problems"][:3],
                      "elapsed_s": round(time.time() - t0, 1)},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


def cmd_baseline_integrity(args) -> int:
    """基线/历史绑定 + 只读边界验证(r0 evidence 不覆盖声明)。"""
    r0_files = sorted(p.name for p in ppo262_artifacts_dir().glob("*.json"))
    route_c = _route_c_integrity()
    ok = bool(route_c["input_lock_pass"])
    vendor_pinned = route_c["vendor_sha"] == VENDOR_SHA
    ok = ok and vendor_pinned and route_c["vendor_clean"]
    art = {
        "format": "ppo262-repair1-baseline-integrity-v1",
        "r1_baseline_git_sha": R1_BASELINE_SHA,
        "r1_baseline_parent": R2_PASS_SHA,
        "vendor_sha_expected": VENDOR_SHA,
        "vendor_pinned": vendor_pinned,
        "r2_plan_digest": _r2_plan_digest(),
        "route_c": route_c,
        "code_identity_diag_at_start": _code_identity_diag(),
        "historical_s262_r0_artifacts_present": r0_files,
        "preservation_contract": (
            "s262_r0 的 artifacts/models/report 一律只读;repair1 全部"
            "输出写 repair1/ 子目录;官方同名命令的覆盖写路径已被"
            "本轮冻结(不重跑 config-dev/probe/summarize 于默认目录)"),
        "stage261_readonly": {
            "generators": "frozen(R2 code_identity 绑定)",
            "family_versions": "frozen",
            "rung_params_source": "locked R2 qualification plan",
            "qualification_artifacts": "read-only",
            "r2_exposure_marker": "untouched",
        },
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pass": ok,
    }
    _w("baseline_integrity.json", art)
    print(json.dumps({"input_lock_pass": ok,
                      "r2_plan_digest": art["r2_plan_digest"]},
                     ensure_ascii=False))
    return 0 if ok else 2


# ============================================================ repair verify
def cmd_repair_verify(args) -> int:
    """harness 修复在 s262_r0 历史数据上的行为验证(不重训练)。

    - 用 config_dev_d1_capture 对 r0 的 capture_tables(D1 cells)重算
      三 candidate 分数:必须有限非 null;
    - select_config_from_scores:按 all_fail_semantics 必须判定
      all-fail(selected=None);
    - 在 sandbox artifacts 目录执行 cmd_config_dev_select(修语义后):
      必须返回非零且不生成 selected config;
    - gate 函数在 all-fail 状态下必须拒绝 probe/core/final-lock。
    r0 原始文件零改动。
    """
    import shutil
    import tempfile

    from rl_curriculum.ppo262_cli import (
        cmd_config_dev_select, official_config_gate, select_config_from_scores,
    )
    from rl_curriculum.ppo262_metrics import config_dev_d1_capture

    src = ppo262_artifacts_dir() / "ppo_config_development_result.json"
    r0 = json.loads(src.read_text(encoding="utf-8"))
    rescored: dict[str, Any] = {}
    for name, cand in r0["candidates"].items():
        merged: dict[str, dict[str, Any]] = {}
        for fam, t in cand["capture_tables"].items():
            merged.update(t)
        fams = sorted(cand["capture_tables"])
        rescored[name] = {
            "family_d1_captures": {
                fam: cand["capture_tables"][fam][f"{fam}/D1"]["capture"]
                for fam in fams},
            "config_dev_D1_capture": config_dev_d1_capture(merged, fams),
        }
    scores = {n: r["config_dev_D1_capture"] for n, r in rescored.items()}
    selected, notes, all_fail = select_config_from_scores(
        scores, {n: r["family_d1_captures"] for n, r in rescored.items()})

    # sandbox 重选(r0 result 拷贝;PPO262_ARTIFACTS_DIR 重定向)
    sandbox = Path(tempfile.mkdtemp(prefix="repair1_verify_"))
    shutil.copy(src, sandbox / "ppo_config_development_result.json")
    import os
    old_art = os.environ.get("PPO262_ARTIFACTS_DIR")
    old_lock = os.environ.get("PPO262_FINAL_LOCK_DIR")
    os.environ["PPO262_ARTIFACTS_DIR"] = str(sandbox)
    os.environ["PPO262_FINAL_LOCK_DIR"] = str(sandbox)
    try:
        rc = cmd_config_dev_select(args)
        sandbox_selected = (sandbox / "selected_ppo_config.json").is_file()
        result_reread = json.loads(
            (sandbox / "ppo_config_development_result.json").read_text(
                encoding="utf-8"))
        # gate 在 all-fail sandbox 下的行为
        gate_cfg = official_config_gate()
    finally:
        if old_art is None:
            os.environ.pop("PPO262_ARTIFACTS_DIR", None)
        else:
            os.environ["PPO262_ARTIFACTS_DIR"] = old_art
        if old_lock is None:
            os.environ.pop("PPO262_FINAL_LOCK_DIR", None)
        else:
            os.environ["PPO262_FINAL_LOCK_DIR"] = old_lock

    checks = {
        "rescored_all_finite": all(
            v is not None and _finite(v) for v in scores.values()),
        "r0_null_scores_reproduced": all(
            s is None for s in r0["candidate_scores"].values()),
        "all_fail_detected": bool(all_fail and selected is None),
        "reselect_returned_nonzero": rc != 0,
        "reselect_no_selected_config": not sandbox_selected,
        "reselect_result_all_fail": bool(result_reread.get("all_fail")),
        "gate_closed_after_all_fail": (
            gate_cfg[0] is False),  # sandbox 中 selected 未生成 => 关闭
    }
    art = {
        "format": "ppo262-repair1-config-metric-repair-v1",
        "metric": "config_dev_D1_capture(方案 B:独立 D1-only 指标,"
                  "不调用 family_core_capture)",
        "r0_scores_null": dict(r0["candidate_scores"]),
        "rescored": {n: r["config_dev_D1_capture"]
                     for n, r in rescored.items()},
        "rescored_detail": rescored,
        "selection": {"selected": selected, "all_fail": all_fail,
                      "notes": notes},
        "checks": checks,
        "sandbox_reselect_returncode": rc,
        "pass": all(checks.values()),
        "r0_original_untouched": (
            "repair-verify 只读 ppo_config_development_result.json;"
            "重选在临时 sandbox artifacts 目录执行"),
    }
    _w("config_metric_repair.json", art)

    # gate 行为矩阵(official 目录的真实状态 + sandbox all-fail 状态)
    gate_art = {
        "format": "ppo262-repair1-official-gate-repair-v1",
        "config_gate": {
            "all_fail_scores": "official workflow STOP(无 selected config;"
                               "probe/core/dev-eval/final-lock 全部拒绝)",
            "verified_in_sandbox": checks,
        },
        "probe_gate": {
            "requires": "三族 probe_results 全部存在、schema 完整"
                        "(D0-D3 cells + 非空 episode_curve + env_audit)"
                        "且 pass=true",
            "forgery_resistance": "手工伪造 artifact 缺真实运行痕迹字段"
                                  "即拒绝(_load_probe_result 校验)",
        },
        "final_gate": {
            "requires": ["input lock PASS",
                         "config gate PASS(selected 非空且非 all_fail)",
                         "probe gate PASS(三族)",
                         "6 个 core training_run_summary 全部 pass",
                         "模型/manifest 哈希完整"],
        },
        "diagnostic_workflow_separation": {
            "diagnose_*_commands": "独立 CLI 族,写 repair1/ 目录",
            "cannot_produce_official_pass": True,
            "cannot_consume_final_namespace": (
                "derive262_diag_seed 白名单不含 ppo_final_eval_262;"
                "诊断计划锁不含 final seed schedule"),
        },
        "pass": art["pass"],
    }
    _w("official_gate_repair.json", gate_art)
    print(json.dumps({"pass": art["pass"], "checks": checks,
                      "rescored": {n: r["config_dev_D1_capture"]
                                   for n, r in rescored.items()}},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


def _finite(v) -> bool:
    import math
    return isinstance(v, (int, float)) and math.isfinite(v)


# ============================================================ feature scale
_OBS_GROUPS = {
    "ret_vol": ["%-ret-1", "%-ret-4", "%-vol-24"],
    "price_ma_ratio": ["%-price-ma-ratio"],
    "raw_ohlc": ["%-raw_open", "%-raw_high", "%-raw_low", "%-raw_close"],
    "position_slot": ["position"],
}


def cmd_feature_scale(args) -> int:
    """特征尺度 profile(不训练任何模型)。"""
    from rl_curriculum.ppo262_banks import (
        EpisodeKey, generate262_bank, staged_order,
    )
    from rl_curriculum.ppo262_diag_metrics import _reference_free_obs_sequence
    from rl_curriculum.ppo262_metrics import build_261_policy_set
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
    )

    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    schema = production_observation_schema()

    banks: dict[str, list] = {}
    # official r0 corpus 复现(确定性生成,零覆盖风险)
    banks["config_dev_train"] = generate262_bank(
        _mini_keys("ppo_config_dev_262", 70, pair_base=0),
        locked_plan_rung_params=rung_params)
    banks["config_dev_eval"] = generate262_bank(
        _mini_keys("ppo_config_dev_262", 8, pair_base=100),
        locked_plan_rung_params=rung_params)
    probe_keys = []
    from rl_curriculum.ppo262_config import PPO262_PROBE_BUDGETS
    for fam, layout in PPO262_PROBE_BUDGETS.items():
        ns = f"ppo_probe_train_262_{fam.split('_')[0]}"
        for rung, n in layout.items():
            for j in range(n // 2):
                for v in ("A", "B"):
                    probe_keys.append(EpisodeKey(ns, fam, rung, j, v))
    banks["probe_train"] = generate262_bank(
        staged_order(probe_keys), locked_plan_rung_params=rung_params)
    eval_keys = []
    for fam in CURRICULUM261_FAMILIES:
        for rung in CURRICULUM261_RUNGS:
            for j in range(4):
                for v in ("A", "B"):
                    eval_keys.append(EpisodeKey(
                        "ppo_probe_eval_262", fam, rung, j, v))
    banks["probe_eval"] = generate262_bank(
        eval_keys, locked_plan_rung_params=rung_params)

    obs_names = list(PRODUCTION_FEATURE_COLUMNS) + ["position"]
    profile: dict[str, Any] = {}
    all_obs_by_bank: dict[str, np.ndarray_like] = {}
    for bname, bank in banks.items():
        rows = []
        ref_rows_by_family: dict[str, list] = {}
        for loaded in bank:
            seq = _reference_free_obs_sequence(loaded)
            rows.extend(seq)
            pols = build_261_policy_set(
                loaded.key.family,
                rung_params[loaded.key.family][loaded.key.rung],
                thresholds[loaded.key.family])
            pols["reference"].bind_observation_schema(schema)
            ref_rows_by_family.setdefault(loaded.key.family, []).append(
                (pols["reference"], seq))
        X = np.stack(rows)
        all_obs_by_bank[bname] = X
        stats = {}
        for i, name in enumerate(obs_names):
            col = X[:, i].astype(np.float64)
            qs = np.quantile(col, [0.01, 0.05, 0.5, 0.95, 0.99])
            stats[name] = {
                "min": float(col.min()), "max": float(col.max()),
                "mean": float(col.mean()), "std": float(col.std()),
                "median": float(qs[2]),
                "q01": float(qs[0]), "q05": float(qs[1]),
                "q95": float(qs[3]), "q99": float(qs[4]),
                "missing": int(np.sum(~np.isfinite(col))),
                "inf": int(np.sum(np.isinf(col))),
                "mean_abs_scale": float(np.mean(np.abs(col))),
            }
        corr = np.corrcoef(X.T)
        corr = np.where(np.isfinite(corr), corr, np.nan)
        corr_json = [[(None if not np.isfinite(v) else float(v))
                      for v in row] for row in corr]
        # reference-action conditional(逐族 reference 在 flat 轨迹 obs 上)
        cond: dict[str, Any] = {}
        for fam, items in ref_rows_by_family.items():
            xs_long, xs_flat = [], []
            for pol, seq in items:
                for o in seq:
                    a = pol.act(o)
                    (xs_long if a == 1 else xs_flat).append(o)
            entry: dict[str, Any] = {
                "n_long": len(xs_long), "n_flat": len(xs_flat)}
            if xs_long and xs_flat:
                xl = np.stack(xs_long)
                xf = np.stack(xs_flat)
                entry["per_feature_mean_when_long"] = {
                    n: float(xl[:, i].mean()) for i, n in enumerate(obs_names)}
                entry["per_feature_mean_when_flat"] = {
                    n: float(xf[:, i].mean()) for i, n in enumerate(obs_names)}
            cond[fam] = entry
        profile[bname] = {
            "n_episodes": len(bank), "n_obs_rows": int(X.shape[0]),
            "per_feature": stats,
            "correlation_matrix": {
                "names": obs_names,
                "matrix": corr_json,
                "note": "position slot 在 flat 轨迹口径下恒 0(相关为 "
                        "null);训练期的仓位分布见 episode_curve 的 "
                        "long_fraction",
            },
            "reference_action_conditional": cond,
        }

    # 组间尺度比(config_dev_train 主口径)
    X = all_obs_by_bank["config_dev_train"]
    group_scale = {}
    for gname, cols in _OBS_GROUPS.items():
        idx = [obs_names.index(c) for c in cols]
        group_scale[gname] = float(np.mean(np.abs(X[:, idx])))
    ratios = {
        "raw_vs_retvol": (
            group_scale["raw_ohlc"] / group_scale["ret_vol"]
            if group_scale["ret_vol"] > 0 else None),
        "raw_vs_pmr": (
            group_scale["raw_ohlc"] / group_scale["price_ma_ratio"]
            if group_scale["price_ma_ratio"] > 0 else None),
    }
    art = {
        "format": "ppo262-repair1-feature-scale-profile-v1",
        "observation_layout": obs_names,
        "groups": {g: list(c) for g, c in _OBS_GROUPS.items()},
        "banks": {b: {"namespace_scope": b, **profile[b]}
                  for b in profile},
        "group_mean_abs_scale_config_dev_train": group_scale,
        "scale_ratios": ratios,
        "claim_check": (
            f"实测 raw OHLC 组 mean|scale| = {group_scale['raw_ohlc']:.6g},"
            f" ret/vol 组 = {group_scale['ret_vol']:.6g},"
            f" 比值 {ratios['raw_vs_retvol']:.1f} x(以逐特征分位数"
            f" 表为准,不做口头'约 300 倍'表述)"),
    }
    _w("feature_scale_profile.json", art)

    # ---- 第一层激活分析(随机初始化 MLP,不训练)
    import torch
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES, build_ppo
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

    cfg = PPO262_CANDIDATES["cand_a_center"]
    probe_env = CurriculumMultiEpisodeEnv(banks["config_dev_train"][:2])
    model = build_ppo(cfg, 26201, probe_env)
    first = model.policy.mlp_extractor.policy_net[0]
    W = first.weight.detach().numpy()          # (128, 9)
    b0 = first.bias.detach().numpy()           # (128,)
    Xa = all_obs_by_bank["config_dev_train"].astype(np.float64)
    contrib = np.abs(Xa[:, None, :] * W[None, :, :])   # (n,128,9)
    pre = Xa @ W.T + b0                                  # (n,128)
    per_col = contrib.mean(axis=(0, 1))                  # (9,)
    share = per_col / per_col.sum()
    tanh_out = np.tanh(pre)
    act = {
        "format": "ppo262-repair1-feature-activation-profile-v1",
        "model": "PPO MlpPolicy [128,128] Tanh seed=26201 随机初始化"
                 "(未训练)",
        "bank": "config_dev_train(全部 obs 行)",
        "first_layer_per_input_mean_abs_contribution": {
            n: float(v) for n, v in zip(obs_names, per_col)},
        "first_layer_contribution_share": {
            n: float(v) for n, v in zip(obs_names, share)},
        "group_contribution_share": {
            g: float(sum(share[obs_names.index(c)] for c in cols))
            for g, cols in _OBS_GROUPS.items()},
        "pre_activation_abs_mean": float(np.mean(np.abs(pre))),
        "pre_activation_abs_gt2_rate": float(np.mean(np.abs(pre) > 2.0)),
        "tanh_saturation_rate_gt_0.96": float(
            np.mean(np.abs(tanh_out) > 0.96)),
        "per_feature_tanh_saturation_note": (
            "饱和率在第一层输出(128 单元)上聚合;per-feature 主导性以"
            "contribution share 为准"),
    }
    _w("feature_activation_profile.json", act)
    print(json.dumps({
        "group_scale": group_scale, "ratios": ratios,
        "group_contribution_share": act["group_contribution_share"],
        "tanh_saturation": act["tanh_saturation_rate_gt_0.96"]},
        ensure_ascii=False))
    return 0


def _mini_keys(namespace: str, n_episodes: int, *, rung: str = "D1",
               pair_base: int) -> list:
    from rl_curriculum.ppo262_banks import EpisodeKey
    keys = []
    for fam in CURRICULUM261_FAMILIES:
        for j in range(n_episodes // 2):
            for v in ("A", "B"):
                keys.append(EpisodeKey(
                    namespace, fam, rung, pair_base + j, v))
    return keys


# ============================================================ plan lock
#: Arm B 常数机械规则:scale_i = 10^round(log10(std_i)),center=0;
#: position slot 恒 identity。(规则本身在 plan 中冻结,由代码机械执行,
#: 无手工挑选;依据 = 诊断训练 bank 的特征统计,不读 eval corpus)
ARM_B_SCALE_RULE = "10^round(log10(std_trainbank));center=0;position=identity"


def _arm_b_constants(X_train: np.ndarray) -> dict[str, Any]:
    std = X_train.astype(np.float64).std(axis=0)
    scale = np.power(10.0, np.round(np.log10(np.where(std > 0, std, 1.0))))
    scale[-1] = 1.0  # position slot
    center = np.zeros_like(scale)
    return {"center": [float(v) for v in center],
            "scale": [float(v) for v in scale]}


#: 诊断训练/评估 bank 规格(所有命令共用;冻结进 plan)
DIAG_BANK_SPEC = {
    "supervised": {
        "train": {"namespace": "diag262r1_supervised_train",
                  "families": list(CURRICULUM261_FAMILIES),
                  "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 12,
                  "pair_base": 0},
        "eval": {"namespace": "diag262r1_supervised_eval",
                 "families": list(CURRICULUM261_FAMILIES),
                 "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 12,
                 "pair_base": 0},
    },
    "overfit": {
        "train_per_seed_slot": {
            "namespace": "diag262r1_overfit_{fam_short}",
            "families": "{single}", "rungs": ["D0"], "pairs": 8,
        },
        "dev": {"pair_base_offset": 256, "pairs": 8},
        "episodes_per_bank": 16, "cycles": 16,
        "steps_per_seed": 16 * 287 * 16,   # 73,472
        "checkpoint_episodes": [0, 12, 25, 64, 128, 256],
    },
    "preprocess": {
        "train_per_seed_slot": {
            "namespace": "diag262r1_preprocess_train",
            "families": list(CURRICULUM261_FAMILIES),
            "rungs": ["D0", "D1"], "pairs_per_fr": 4,
        },
        "eval": {"namespace": "diag262r1_preprocess_eval",
                 "families": list(CURRICULUM261_FAMILIES),
                 "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 4,
                 "pair_base": 0},
        "episodes_per_bank": 48, "cycles": 6,
        "steps_per_seed": 48 * 287 * 6,    # 82,656
        "checkpoint_episodes": [0, 14, 29, 72, 144, 288],
    },
    "bc": {
        "train": {"namespace": "diag262r1_bc_train",
                  "families": list(CURRICULUM261_FAMILIES),
                  "rungs": ["D0", "D1"], "pairs_per_fr": 4,
                  "pair_base": 0},
        "eval": {"namespace": "diag262r1_bc_eval",
                 "families": list(CURRICULUM261_FAMILIES),
                 "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 4,
                 "pair_base": 0},
        "bc_epochs": 20, "bc_lr": 3e-4,
        "finetune_cycles": 3, "steps_finetune": 48 * 287 * 3,
        "checkpoint_episodes": [0, 72, 144],
    },
}

#: 诊断判定规则(预注册;diagnose-decision 机械执行)
DIAG_INTERPRETATION_RULES = {
    "supervised_learned": (
        "family x arm 的 held-out(eval bank)balanced_accuracy >= 0.60 "
        "且 behavior_gap_proxy >= 0.20"),
    "ppo_recovered_arm": (
        "训练 bank capture > 0.05 且 probability separation gap > 0.05 "
        "且 deterministic behavior gap > 0.02(3 seeds 中 >= 2 seeds 满足)"),
    "overfit_nondegenerate": (
        "family x seed: 训练 bank D0 capture > 0.05 且该族 probability "
        "gap > 0.05;3 seeds 中 >= 2 满足则该族可过拟合"),
    "bc_retained": (
        "PPO fine-tune 后 held-out reference match rate 相对 BC 结束值"
        "绝对下降 <= 0.15,且 fine-tune 后 match rate 仍 >= 0.55"),
    "branch_decision": {
        "A": "unscaled scratch PPO 满足 ppo_recovered_arm(Arm A)",
        "B": "A 不满足,但 Arm B 或 C 满足 ppo_recovered_arm",
        "C": "supervised 学会 + scratch PPO 全不满足 + BC 能学且 "
             "fine-tune 保留",
        "D": "supervised 学会 + scratch 全不满足 + BC 能学但 "
             "fine-tune 摧毁",
        "E": "scaled(全部 arm)supervised 也学不会",
        "F": "证据互相矛盾或不充分",
    },
}


def cmd_plan_lock(args) -> int:
    """诊断计划锁定(preprocessing ablation / BC 运行前冻结)。"""
    lock = REPAIR1_DIR / "diagnostic_plan.json"
    if lock.is_file():
        print(f"诊断计划已锁定({lock}),拒绝重锁", file=sys.stderr)
        return 2
    from rl_curriculum.ppo262_diag_namespaces import (
        DIAG262_ABLATION_SEEDS, DIAG262_BC_SEEDS, DIAG262_NAMESPACES,
        DIAG262_OVERFIT_SEEDS, DIAG262_PROB_RNG_SEED,
    )

    # Arm B 常数:诊断训练 bank(全部 3 seed 槽位)特征统计的机械规则
    Xs = []
    for slot in (0, 1, 2):
        base = slot * 32
        bank = _gen_diag_bank(
            "diag262r1_preprocess_train", CURRICULUM261_FAMILIES,
            ("D0", "D1"), 4, base, progress=False)
        from rl_curriculum.ppo262_diag_metrics import (
            _reference_free_obs_sequence,
        )
        Xs.extend([o for e in bank for o in
                   _reference_free_obs_sequence(e)])
    arm_b = _arm_b_constants(np.stack(Xs))

    plan = {
        "format": "ppo262-repair1-diagnostic-plan-v1",
        "diagnostic_iteration": "s262_diag_r1",
        "baseline_git_sha": R1_BASELINE_SHA,
        "r2_plan_digest": _r2_plan_digest(),
        "s262_r0_fail_commit": R1_BASELINE_SHA,
        "namespaces": list(DIAG262_NAMESPACES),
        "model_seeds": {
            "overfit": list(DIAG262_OVERFIT_SEEDS),
            "ablation": list(DIAG262_ABLATION_SEEDS),
            "bc": list(DIAG262_BC_SEEDS),
        },
        "prob_rng_seed": DIAG262_PROB_RNG_SEED,
        "ppo_config_source": "s262_r0 selected(cand_a_center,回退产物,"
                             "仅作为诊断对照配置;非有效 official 选择)",
        "bank_spec": DIAG_BANK_SPEC,
        "arms": {
            "A_current_unscaled": {
                "adapter": "identity(bitwise = s262_r0/R2 observation)",
                "must_verify": "Arm A 训练 env 输出与 official unscaled "
                               "逐位一致",
            },
            "B_fixed_causal_scaling": {
                "rule": ARM_B_SCALE_RULE,
                "constants": arm_b,
                "fit_source": "diag262r1_preprocess_train 全部 3 seed "
                              "槽位 bank 特征(训练语料,非 eval)",
            },
            "C_train_bank_fitted_frozen": {
                "rule": "per-seed train bank mean/std z-score;"
                        "fit 后冻结应用于该 seed 的训练与评估;"
                        "position slot identity;dev/eval 不参与 fit",
            },
        },
        "budgets": {
            "overfit_steps_per_family_seed":
                DIAG_BANK_SPEC["overfit"]["steps_per_seed"],
            "ablation_steps_per_arm_seed":
                DIAG_BANK_SPEC["preprocess"]["steps_per_seed"],
            "bc_epochs": DIAG_BANK_SPEC["bc"]["bc_epochs"],
            "bc_finetune_steps": DIAG_BANK_SPEC["bc"]["steps_finetune"],
        },
        "metrics": ["capture(train/dev)", "deterministic behavior gap",
                    "probability behavior(P(Long) per latent label)",
                    "stochastic behavior(fixed RNG)",
                    "value/advantage distribution",
                    "gradient probe(actor/critic/first-layer per-column)",
                    "cost decomposition(fees/liquidation/trades)"],
        "interpretation_rules": DIAG_INTERPRETATION_RULES,
        "code_identity_diag": _code_identity_diag(),
        "route_c_identity": _route_c_integrity(),
        "vendor_sha": VENDOR_SHA,
        "forbidden": [
            "修改 2.6.1 R2 observation contract / qualification artifacts",
            "把 scaled arm 升级为正式合同(仅 diagnostic evidence)",
            "触碰 ppo_final_eval_262 / qualification_r2",
            "声称 scaled diagnostic 通过 Stage 2.6.2",
            "根据结果改 scaling 常数 / 增删 seed / 改预算或判定规则",
        ],
        "locked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    payload = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    digest = "dp-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    plan["plan_digest_self"] = digest
    _w("diagnostic_plan.json", plan)
    (REPAIR1_DIR / "diagnostic_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    print(json.dumps({"locked": True, "digest": digest,
                      "arm_b_scale": arm_b["scale"]}, ensure_ascii=False))
    return 0


def _load_diag_plan() -> dict[str, Any]:
    p = REPAIR1_DIR / "diagnostic_plan.json"
    if not p.is_file():
        raise SystemExit("诊断计划未锁定:先运行 diagnose-plan-lock")
    plan = json.loads(p.read_text(encoding="utf-8"))
    payload = {k: v for k, v in plan.items() if k != "plan_digest_self"}
    expect = "dp-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False).encode(
        "utf-8")).hexdigest()
    if expect != plan.get("plan_digest_self"):
        raise SystemExit("诊断计划 digest 校验失败(计划被改动,fail closed)")
    return plan


# ============================================================ supervised
def cmd_supervised(args) -> int:
    """静态监督可学习性探针(linear + MLP;unscaled/fixed/fitted 三 arm)。"""
    import torch
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.curriculum261_api import curriculum261_eval_config
    from rl_curriculum.ppo262_diag_train import (
        ObsAdapter, collect_bc_dataset,
    )
    from rl_curriculum.ppo262_diag_metrics import (
        calibration_curve_summary, supervised_metrics,
    )
    from rl_curriculum.ppo262_metrics import build_261_policy_set

    plan = _load_diag_plan()
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg = curriculum261_eval_config()
    spec = DIAG_BANK_SPEC["supervised"]

    datasets: dict[str, dict[str, Any]] = {}
    for side in ("train", "eval"):
        s = spec[side]
        bank = _gen_diag_bank(
            s["namespace"], s["families"], s["rungs"],
            s["pairs_per_fr"], s["pair_base"])
        per_fam: dict[str, dict[str, Any]] = {}
        for fam in s["families"]:
            fam_bank = [e for e in bank if e.key.family == fam]
            pols_by_rung = {}
            data = {"X": [], "y": [], "pairs": set()}
            for e in fam_bank:
                pols = pols_by_rung.get(e.key.rung) or build_261_policy_set(
                    fam, rung_params[fam][e.key.rung], thresholds[fam])
                pols_by_rung[e.key.rung] = pols
                ds = collect_bc_dataset([e], pols["reference"], schema, cfg)
                data["X"].append(ds["X"])
                data["y"].append(ds["y"])
                data["pairs"].add((e.key.rung, e.key.pair_index))
            per_fam[fam] = {
                "X": np.concatenate(data["X"]),
                "y": np.concatenate(data["y"]),
                "n_pairs": len(data["pairs"]),
            }
        datasets[side] = per_fam

    # 三 arm adapter:unscaled / fixed(plan B 常数)/ fitted(train fit)
    arm_b = plan["arms"]["B_fixed_causal_scaling"]["constants"]
    results: dict[str, Any] = {}
    for fam in spec["train"]["families"]:
        Xtr, ytr = datasets["train"][fam]["X"], datasets["train"][fam]["y"]
        Xev, yev = datasets["eval"][fam]["X"], datasets["eval"][fam]["y"]
        adapters = {
            "unscaled": ObsAdapter.identity(Xtr.shape[1]),
            "fixed_causal": ObsAdapter.fixed(
                arm_b["center"], arm_b["scale"],
                source="plan-locked Arm B constants"),
            "train_fitted": ObsAdapter.fit_frozen(
                Xtr, source="diag supervised train bank mean/std"),
        }
        fam_res: dict[str, Any] = {
            "n_train": len(ytr), "n_eval": len(yev),
            "n_train_pairs": datasets["train"][fam]["n_pairs"],
            "n_eval_pairs": datasets["eval"][fam]["n_pairs"],
            "class_balance_train": {
                "long": float(np.mean(ytr == 1))},
        }
        for aname, adapter in adapters.items():
            Xt = np.stack([adapter.apply(x) for x in Xtr])
            Xe = np.stack([adapter.apply(x) for x in Xev])
            entry: dict[str, Any] = {"adapter": adapter.describe()}
            # ---- linear probe
            from sklearn.linear_model import LogisticRegression
            lin = LogisticRegression(max_iter=2000, random_state=262)
            lin.fit(Xt, ytr)
            entry["linear"] = {
                "train": supervised_metrics(ytr, lin.predict(Xt)),
                "eval": supervised_metrics(yev, lin.predict(Xe)),
            }
            # ---- MLP classifier(接近 PPO actor:[128,128] Tanh)
            torch.manual_seed(26201)
            net = torch.nn.Sequential(
                torch.nn.Linear(Xt.shape[1], 128), torch.nn.Tanh(),
                torch.nn.Linear(128, 128), torch.nn.Tanh(),
                torch.nn.Linear(128, 2))
            opt = torch.optim.Adam(net.parameters(), lr=3e-4)
            Xt_t = torch.as_tensor(Xt, dtype=torch.float32)
            ytr_t = torch.as_tensor(ytr, dtype=torch.long)
            Xe_t = torch.as_tensor(Xe, dtype=torch.float32)
            for _ in range(20):
                opt.zero_grad()
                loss = torch.nn.functional.cross_entropy(
                    net(Xt_t), ytr_t)
                loss.backward()
                opt.step()
            with torch.no_grad():
                p_eval = torch.softmax(net(Xe_t), dim=-1)[:, 1].numpy()
                p_train = torch.softmax(net(Xt_t), dim=-1)[:, 1].numpy()
            entry["mlp"] = {
                "train": supervised_metrics(
                    ytr, net(Xt_t).argmax(dim=-1).numpy()),
                "eval": supervised_metrics(
                    yev, net(Xe_t).argmax(dim=-1).numpy()),
                "eval_calibration": calibration_curve_summary(yev, p_eval),
            }
            learned = (entry["mlp"]["eval"]["balanced_accuracy"] is not None
                       and entry["mlp"]["eval"]["balanced_accuracy"] >= 0.60
                       and (entry["mlp"]["eval"].get("behavior_gap_proxy")
                            or 0) >= 0.20)
            entry["mlp_learned_rule"] = {
                "learned": bool(learned),
                "rule": plan["interpretation_rules"][
                    "supervised_learned"],
            }
            fam_res[aname] = entry
        results[fam] = fam_res

    art = {
        "format": "ppo262-repair1-supervised-probe-v1",
        "diagnostic_iteration": "s262_diag_r1",
        "diagnostic_only": True,
        "plan_digest": plan["plan_digest_self"],
        "split_contract": "pair 级 train/eval 隔离(train/eval 为不同 "
                          "namespace 不同 pair;同 pair 数据不跨集)",
        "label_source": "causal observation reference policy"
                        "(不读 latent oracle / future / episode id)",
        "input": "policy-visible observation(8 生产特征 + position slot,"
                 "reference 自身轨迹)",
        "results": results,
    }
    _w("supervised_probe_results.json", art)
    _w("supervised_probe_plan.json", {
        "format": "ppo262-repair1-supervised-probe-plan-v1",
        "spec": spec, "models": ["LogisticRegression(max_iter=2000)",
                                 "MLP [128,128] Tanh Adam lr=3e-4 20ep"],
        "arms": ["unscaled", "fixed_causal(plan B)", "train_fitted"],
        "seed": {"linear": 262, "mlp": 26201},
        "plan_digest": plan["plan_digest_self"],
    })
    summary = {fam: {
        a: {
            "linear_eval_bal_acc": results[fam][a]["linear"]["eval"][
                "balanced_accuracy"],
            "mlp_eval_bal_acc": results[fam][a]["mlp"]["eval"][
                "balanced_accuracy"],
            "mlp_learned": results[fam][a]["mlp_learned_rule"]["learned"],
        } for a in ("unscaled", "fixed_causal", "train_fitted")}
        for fam in results}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


# ============================================================ tiny overfit
def _eval_d0_capture(model_or_policy, bank, rung_params, thresholds,
                     adapter=None):
    """诊断口径 capture:bank 上全 cells + 行为指标(不做 core 加权)。"""
    from rl_curriculum.ppo262_diag_train import ScaledEvalPolicy
    from rl_curriculum.ppo262_metrics import (
        behavior_metrics, build_261_policy_set, capture_table,
        evaluate_policy_on_bank,
    )
    if adapter is None:
        if hasattr(model_or_policy, "reset_episode"):
            policy = model_or_policy
        else:
            from rl_curriculum.ppo262_metrics import SB3PPOPolicy
            policy = SB3PPOPolicy(model_or_policy, "diag-ppo")
    else:
        policy = ScaledEvalPolicy(model_or_policy, adapter, "diag")
    rows = evaluate_policy_on_bank(policy, bank)
    fam = bank[0].key.family
    ref_rows, baseline_rows = [], {}
    by_rung: dict[str, list] = {}
    for e in bank:
        by_rung.setdefault(e.key.rung, []).append(e)
    for rung, eps in by_rung.items():
        pols = build_261_policy_set(
            fam, rung_params[fam][rung], thresholds[fam])
        ref_rows.extend(evaluate_policy_on_bank(
            pols["reference"], eps, collect_actions=False))
        for bname, pol in pols.items():
            if bname == "reference":
                continue
            baseline_rows.setdefault(bname, []).extend(
                evaluate_policy_on_bank(pol, eps, collect_actions=False))
    table = capture_table(rows, ref_rows, baseline_rows)
    return {
        "capture_table": table,
        "rows_summary": {
            "mean_net_return": float(np.mean(
                [r["net_return"] for r in rows])),
            "n_trades_total": int(sum(r["n_trades"] for r in rows)),
        },
        "behavior": behavior_metrics(rows, bank),
    }


def _probe_adapter_of(adapter):
    return None if (adapter is None
                    or adapter.identity_equivalent()) else adapter


def cmd_overfit(args) -> int:
    """tiny D0 过拟合诊断(C1/C2/C3 x 3 seeds;重复暴露 bank)。"""
    from rl_curriculum.ppo262_diag_metrics import (
        probability_metrics_on_bank, probability_separation_summary,
    )
    from rl_curriculum.ppo262_diag_namespaces import DIAG262_OVERFIT_SEEDS
    from rl_curriculum.ppo262_diag_train import diag_train_run
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES

    plan = _load_diag_plan()
    spec = DIAG_BANK_SPEC["overfit"]
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    cfg = PPO262_CANDIDATES["cand_a_center"]
    fam_short = {"c1_opportunity": "c1", "c2_context": "c2",
                 "c3_cost": "c3"}

    results: dict[str, Any] = {}
    for fam in CURRICULUM261_FAMILIES:
        ns = f"diag262r1_overfit_{fam_short[fam]}"
        fam_res: dict[str, Any] = {"namespace": ns}
        for slot, seed in enumerate(DIAG262_OVERFIT_SEEDS):
            base = slot * 32
            train_bank = _gen_diag_bank(
                ns, [fam], ["D0"], spec["train_per_seed_slot"]["pairs"],
                base, progress=False)
            dev_bank = _gen_diag_bank(
                ns, [fam], ["D0"], spec["dev"]["pairs"],
                spec["dev"]["pair_base_offset"] + base, progress=False)
            run = diag_train_run(
                train_bank, config=cfg, model_seed=seed,
                total_timesteps=spec["steps_per_seed"],
                run_label=f"diag/overfit/{fam}/seed{seed}",
                checkpoint_episodes=tuple(spec["checkpoint_episodes"]),
                gradient_probe_every=8)
            ckpt_prob = {}
            for tag in run["checkpoints"]:
                ckpt_prob[tag] = probability_separation_summary(
                    probability_metrics_on_bank(
                        run["model"], train_bank[:8]))
            final_eval = _eval_d0_capture(
                run["model"], dev_bank, rung_params, thresholds)
            train_eval = _eval_d0_capture(
                run["model"], train_bank, rung_params, thresholds)
            fam_res[f"seed{seed}"] = {
                "run_audit": {k: run[k] for k in (
                    "cycles", "bank_episodes", "total_timesteps",
                    "elapsed_seconds", "fps", "env_audit",
                    "audit_problems", "pass")},
                "train_bank_capture": train_eval,
                "dev_bank_capture": final_eval,
                "probability_dynamics_checkpoints": ckpt_prob,
                "probability_final": probability_separation_summary(
                    probability_metrics_on_bank(run["model"], dev_bank)),
                "update_records_summary": {
                    "n_updates": len(run["update_records"]),
                    "first_update_has_kl": bool(
                        run["update_records"]
                        and "approx_kl" in run["update_records"][0]),
                    "final_entropy_loss": (
                        run["update_records"][-1].get("entropy_loss")
                        if run["update_records"] else None),
                    "final_approx_kl": (
                        run["update_records"][-1].get("approx_kl")
                        if run["update_records"] else None),
                },
                "rollout_stats_final": (
                    run["rollout_records"][-1]
                    if run["rollout_records"] else None),
                "gradient_probes": run["gradient_probes"][-2:],
                "initial_policy_state_sha256": run[
                    "initial_policy_state_sha256"],
                "cost_decomposition": {
                    "total_fees_train": float(np.sum([
                        r["cost_fees_paid"]
                        for r in run["episode_curve"]])),
                    "total_liquidation_fees": float(np.sum([
                        r["terminal_liquidation_fee"]
                        for r in run["episode_curve"]])),
                    "ledger_trades_total": int(np.sum([
                        r["ledger_trades"]
                        for r in run["episode_curve"]])),
                    "position_changes_total": int(np.sum([
                        r["position_changes"]
                        for r in run["episode_curve"]])),
                },
            }
        flags = []
        for seed in DIAG262_OVERFIT_SEEDS:
            r = fam_res[f"seed{seed}"]
            caps = [v["capture"] for v in
                    r["train_bank_capture"]["capture_table"].values()
                    if v["capture"] is not None]
            cap = max(caps) if caps else None
            gaps = [v for k, v in r["probability_final"].items()
                    if k.endswith("_probability_gap")]
            pgap = max(gaps) if gaps else None
            flags.append(bool(cap is not None and cap > 0.05
                              and pgap is not None and pgap > 0.05))
        fam_res["overfit_nondegenerate"] = {
            "flags_per_seed": flags,
            "n_positive": int(sum(flags)),
            "pass": int(sum(flags)) >= 2,
            "rule": plan["interpretation_rules"]["overfit_nondegenerate"],
        }
        results[fam] = fam_res

    art = {
        "format": "ppo262-repair1-ppo-overfit-v1",
        "diagnostic_iteration": "s262_diag_r1",
        "diagnostic_only": True,
        "plan_digest": plan["plan_digest_self"],
        "budget": spec,
        "config": "cand_a_center(诊断对照配置,非有效 official 选择)",
        "results": results,
    }
    _w("ppo_overfit_plan.json", {
        "format": "ppo262-repair1-ppo-overfit-plan-v1",
        "tests": {"A": "C1 D0 small bank 重复暴露 16 cycles",
                  "B": "C2 D0 small bank", "C": "C3 D0 small bank"},
        "seeds": list(DIAG262_OVERFIT_SEEDS), "budget": spec,
        "plan_digest": plan["plan_digest_self"],
    })
    _w("ppo_overfit_results.json", art)
    print(json.dumps({
        fam: {"nondegenerate_pass": results[fam]["overfit_nondegenerate"][
                  "pass"],
              "flags": results[fam]["overfit_nondegenerate"][
                  "flags_per_seed"]}
        for fam in results}, ensure_ascii=False))
    return 0


# ============================================================ ablation
def cmd_preprocessing(args) -> int:
    """A/B/C preprocessing ablation(严格配对:同 episodes/seed/初始权重)。"""
    from rl_curriculum.ppo262_diag_metrics import (
        _reference_free_obs_sequence, probability_metrics_on_bank,
        probability_separation_summary,
    )
    from rl_curriculum.ppo262_diag_namespaces import DIAG262_ABLATION_SEEDS
    from rl_curriculum.ppo262_diag_train import ObsAdapter, diag_train_run
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES
    from rl_curriculum.ppo262_metrics import (
        aggregate_capture, family_core_capture,
    )

    plan = _load_diag_plan()
    spec = DIAG_BANK_SPEC["preprocess"]
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    cfg = PPO262_CANDIDATES["cand_a_center"]
    arm_b = plan["arms"]["B_fixed_causal_scaling"]["constants"]

    eval_bank = _gen_diag_bank(
        spec["eval"]["namespace"], spec["eval"]["families"],
        spec["eval"]["rungs"], spec["eval"]["pairs_per_fr"],
        spec["eval"]["pair_base"])

    arms_out: dict[str, Any] = {}
    pairing: dict[str, Any] = {"initial_policy_state": {}, "manifests": {}}
    for slot, seed in enumerate(DIAG262_ABLATION_SEEDS):
        base = slot * 32
        train_bank = _gen_diag_bank(
            spec["train_per_seed_slot"]["namespace"],
            spec["train_per_seed_slot"]["families"],
            spec["train_per_seed_slot"]["rungs"],
            spec["train_per_seed_slot"]["pairs_per_fr"], base)
        X_fit = np.stack([o for e in train_bank
                          for o in _reference_free_obs_sequence(e)])
        adapters = {
            "A_unscaled": ObsAdapter.identity(X_fit.shape[1]),
            "B_fixed_causal": ObsAdapter.fixed(
                arm_b["center"], arm_b["scale"],
                source="plan-locked Arm B constants"),
            "C_train_fitted": ObsAdapter.fit_frozen(
                X_fit, source=f"preprocess_train seed 槽位 {slot} bank"),
        }
        pairing["manifests"][f"seed{seed}"] = hashlib.sha256(json.dumps(
            [e.canonical() for e in train_bank]).encode()).hexdigest()
        for arm_name, adapter in adapters.items():
            run = diag_train_run(
                train_bank, config=cfg, model_seed=seed,
                total_timesteps=spec["steps_per_seed"],
                run_label=f"diag/preprocess/{arm_name}/seed{seed}",
                adapter=_probe_adapter_of(adapter),
                checkpoint_episodes=tuple(spec["checkpoint_episodes"]),
                gradient_probe_every=8)
            pairing["initial_policy_state"].setdefault(
                f"seed{seed}", {})[arm_name] = run[
                "initial_policy_state_sha256"]
            ckpt_prob = {}
            for tag in run["checkpoints"]:
                ckpt_prob[tag] = probability_separation_summary(
                    probability_metrics_on_bank(
                        run["model"], train_bank[:12],
                        adapter=_probe_adapter_of(adapter)))
            final_eval = _eval_d0_capture(
                run["model"], eval_bank, rung_params, thresholds,
                adapter=_probe_adapter_of(adapter))
            train_eval = _eval_d0_capture(
                run["model"], train_bank, rung_params, thresholds,
                adapter=_probe_adapter_of(adapter))
            table = final_eval["capture_table"]
            arms_out.setdefault(arm_name, {})[f"seed{seed}"] = {
                "adapter": run["adapter"],
                "run_audit": {k: run[k] for k in (
                    "cycles", "total_timesteps", "elapsed_seconds", "fps",
                    "env_audit", "audit_problems", "pass")},
                "train_bank_capture": {
                    "capture_cells": {k: v["capture"]
                                      for k, v in
                                      train_eval["capture_table"].items()},
                    "behavior": train_eval["behavior"],
                },
                "core_captures": {
                    fam: family_core_capture(table, fam)
                    for fam in CURRICULUM261_FAMILIES},
                "aggregate_capture": aggregate_capture(table),
                "capture_cells": {k: v["capture"]
                                  for k, v in table.items()},
                "behavior": final_eval["behavior"],
                "mean_net_return_eval": final_eval["rows_summary"][
                    "mean_net_return"],
                "probability_dynamics_checkpoints": ckpt_prob,
                "probability_final_eval": probability_separation_summary(
                    probability_metrics_on_bank(
                        run["model"], eval_bank[:24],
                        adapter=_probe_adapter_of(adapter))),
                "update_records_summary": {
                    "n_updates": len(run["update_records"]),
                    "final_entropy_loss": (
                        run["update_records"][-1].get("entropy_loss")
                        if run["update_records"] else None),
                    "final_value_loss": (
                        run["update_records"][-1].get("value_loss")
                        if run["update_records"] else None),
                    "final_explained_variance": (
                        run["update_records"][-1].get("explained_variance")
                        if run["update_records"] else None),
                },
                "rollout_stats_final": (
                    run["rollout_records"][-1]
                    if run["rollout_records"] else None),
                "gradient_probes": run["gradient_probes"][-2:],
                "cost_decomposition": {
                    "total_fees": float(np.sum([
                        r["cost_fees_paid"]
                        for r in run["episode_curve"]])),
                    "position_changes": int(np.sum([
                        r["position_changes"]
                        for r in run["episode_curve"]])),
                    "ledger_trades": int(np.sum([
                        r["ledger_trades"]
                        for r in run["episode_curve"]])),
                },
                "initial_policy_state_sha256": run[
                    "initial_policy_state_sha256"],
            }

    pair_ok = {}
    for seed_tag, per in pairing["initial_policy_state"].items():
        pair_ok[seed_tag] = len(set(per.values())) == 1
    art = {
        "format": "ppo262-repair1-preprocessing-ablation-v1",
        "diagnostic_iteration": "s262_diag_r1",
        "diagnostic_only": True,
        "plan_digest": plan["plan_digest_self"],
        "budget": spec,
        "pairing_contract": {
            "same_episodes": "三 arm 使用同一 train_bank 对象(同 seed "
                             "槽位/同 pair 区间/同 manifest)",
            "same_seed_and_init": {
                "initial_policy_state_sha256": pairing[
                    "initial_policy_state"],
                "all_arms_identical_per_seed": pair_ok},
            "same_config_steps_eval": "cand_a_center / 82,656 steps / "
                                      "同一 eval bank 对象",
            "only_difference": "observation preprocessing adapter",
        },
        "results": arms_out,
        "pass_pairing": all(pair_ok.values()),
    }
    _w("preprocessing_ablation_results.json", art)
    _w("preprocessing_ablation_plan.json", {
        "format": "ppo262-repair1-preprocessing-ablation-plan-v1",
        "arms": ["A_unscaled(=s262_r0 逐位)", "B_fixed_causal(plan 常数)",
                 "C_train_fitted(冻结 z-score)"],
        "seeds": list(DIAG262_ABLATION_SEEDS), "budget": spec,
        "plan_digest": plan["plan_digest_self"],
    })
    _w("paired_initialization_integrity.json", {
        "format": "ppo262-repair1-paired-init-v1",
        "initial_policy_state_sha256": pairing["initial_policy_state"],
        "all_arms_identical_per_seed": pair_ok,
        "pass": all(pair_ok.values()),
    })
    _w("paired_manifest_integrity.json", {
        "format": "ppo262-repair1-paired-manifest-v1",
        "train_bank_manifest_sha256_per_seed": pairing["manifests"],
        "note": "同一 seed 内三 arm 共享同一 bank 对象(构造级配对);"
                "不同 seed 槽位 pair 区间互斥(bank 不重合合同)",
    })
    print(json.dumps({
        arm: {s: v["aggregate_capture"] for s, v in per.items()}
        for arm, per in arms_out.items()} | {
        "pairing_ok": all(pair_ok.values())}, ensure_ascii=False))
    return 0


# ============================================================ BC warm-start
def cmd_bc_warmstart(args) -> int:
    """BC warm-start 诊断(条件:supervised 学会 + scratch PPO 坍塌)。"""
    from rl_curriculum.curriculum261_api import curriculum261_eval_config
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.ppo262_diag_metrics import (
        probability_metrics_on_bank, probability_separation_summary,
    )
    from rl_curriculum.ppo262_diag_namespaces import DIAG262_BC_SEEDS
    from rl_curriculum.ppo262_diag_train import (
        ObsAdapter, actor_state_hash, bc_train_actor, collect_bc_dataset,
        diag_train_run,
    )
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES
    from rl_curriculum.ppo262_metrics import build_261_policy_set

    plan = _load_diag_plan()
    sup = REPAIR1_DIR / "supervised_probe_results.json"
    if not sup.is_file():
        print("supervised 探针未执行,BC warm-start 前置条件未知",
              file=sys.stderr)
        return 2
    sup_data = json.loads(sup.read_text(encoding="utf-8"))
    # 前置条件:哪个 arm 的 MLP 在 held-out 上学会(任一族)
    learned_arms: dict[str, list[str]] = {}
    for fam, fr in sup_data["results"].items():
        for arm in ("unscaled", "fixed_causal", "train_fitted"):
            if fr[arm]["mlp_learned_rule"]["learned"]:
                learned_arms.setdefault(arm, []).append(fam)
    any_learned = bool(learned_arms)
    bc_arm = ("unscaled" if "unscaled" in learned_arms
              else "fixed_causal" if "fixed_causal" in learned_arms
              else "train_fitted" if "train_fitted" in learned_arms
              else None)

    spec = DIAG_BANK_SPEC["bc"]
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg261 = curriculum261_eval_config()
    ppo_cfg = PPO262_CANDIDATES["cand_a_center"]

    if not any_learned:
        art = {
            "format": "ppo262-repair1-bc-warmstart-v1",
            "executed": False,
            "reason": "supervised MLP 在全部 arm 上均未学会 reference "
                      "action(held-out 规则未达):BC 无可克隆的有效策略,"
                      "按任务书不制造空 BC artifact",
            "supervised_learned_arms": learned_arms,
            "branch_implication": "指向 Branch E(scaled supervised 也学"
                                  "不会)或 F",
        }
        _w("bc_warmstart_results.json", art)
        print(json.dumps({"executed": False,
                          "reason": art["reason"]}, ensure_ascii=False))
        return 0

    train_bank = _gen_diag_bank(
        spec["train"]["namespace"], spec["train"]["families"],
        spec["train"]["rungs"], spec["train"]["pairs_per_fr"],
        spec["train"]["pair_base"])
    eval_bank = _gen_diag_bank(
        spec["eval"]["namespace"], spec["eval"]["families"],
        spec["eval"]["rungs"], spec["eval"]["pairs_per_fr"],
        spec["eval"]["pair_base"])
    # 监督数据(reference 轨迹,按族构建 reference)
    datasets = []
    for fam in spec["train"]["families"]:
        fam_bank = [e for e in train_bank if e.key.family == fam]
        pols_by_rung: dict[str, Any] = {}
        for e in fam_bank:
            pols = pols_by_rung.get(e.key.rung) or build_261_policy_set(
                fam, rung_params[fam][e.key.rung], thresholds[fam])
            pols_by_rung[e.key.rung] = pols
            datasets.append(collect_bc_dataset(
                [e], pols["reference"], schema, cfg261))
    X = np.concatenate([d["X"] for d in datasets])
    y = np.concatenate([d["y"] for d in datasets])
    # held-out 数据
    eval_sets = []
    for fam in spec["eval"]["families"]:
        fam_bank = [e for e in eval_bank if e.key.family == fam]
        pols_by_rung = {}
        for e in fam_bank:
            pols = pols_by_rung.get(e.key.rung) or build_261_policy_set(
                fam, rung_params[fam][e.key.rung], thresholds[fam])
            pols_by_rung[e.key.rung] = pols
            eval_sets.append(collect_bc_dataset(
                [e], pols["reference"], schema, cfg261))
    Xe = np.concatenate([d["X"] for d in eval_sets])
    ye = np.concatenate([d["y"] for d in eval_sets])

    arm_b = plan["arms"]["B_fixed_causal_scaling"]["constants"]
    if bc_arm == "unscaled":
        adapter = ObsAdapter.identity(X.shape[1])
    elif bc_arm == "fixed_causal":
        adapter = ObsAdapter.fixed(
            arm_b["center"], arm_b["scale"], source="plan Arm B")
    else:
        adapter = ObsAdapter.fit_frozen(
            X, source="bc train bank(supervised 同款规则)")

    def _match(model) -> dict[str, Any]:
        from rl_curriculum.ppo262_diag_metrics import supervised_metrics
        import torch
        out = {}
        for name, xx, yy in (("train", X, y), ("heldout", Xe, ye)):
            xt = torch.as_tensor(np.stack(
                [adapter.apply(o) for o in xx]), dtype=torch.float32)
            with torch.no_grad():
                logits = model.policy.get_distribution(
                    xt).distribution.logits
            out[name] = supervised_metrics(yy, logits.argmax(dim=-1).numpy())
        return out

    results: dict[str, Any] = {
        "executed": True,
        "bc_arm": bc_arm,
        "supervised_learned_arms": learned_arms,
        "n_train_obs": len(y), "n_heldout_obs": len(ye),
        "train_dev_pair_isolation": "bc_train/bc_eval 独立 namespace"
                                    " + 独立 pair 区间",
        "critic_access": "critic 不读取 latent;BC 只训练 actor 参数",
        "per_seed": {},
    }
    seed = DIAG262_BC_SEEDS[0]
    # BC 载体:构造同 seed PPO -> actor 克隆 reference -> state_dict
    # 交给诊断 runner 做 PPO fine-tune(bc_init_state,训练前载入)
    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    env = CurriculumMultiEpisodeEnv(train_bank)
    model = build_diagnosed_ppo(ppo_cfg, seed, env)
    pre_hash = actor_state_hash(model)
    bc_info = bc_train_actor(
        model, {"X": X, "y": y}, epochs=spec["bc_epochs"],
        lr=spec["bc_lr"], adapter=adapter, rng_seed=seed)
    post_hash = actor_state_hash(model)
    match_bc = _match(model)
    # PPO fine-tune(BC 权重经 bc_init_state 载入 runner 模型)
    bc_state = {k: v.clone() for k, v in model.policy.state_dict().items()}
    actor_import_verified = actor_state_hash(model) == post_hash
    run = diag_train_run(
        train_bank, config=ppo_cfg, model_seed=seed,
        total_timesteps=spec["steps_finetune"],
        run_label=f"diag/bc_finetune/{bc_arm}/seed{seed}",
        adapter=_probe_adapter_of(adapter),
        checkpoint_episodes=tuple(spec["checkpoint_episodes"]),
        gradient_probe_every=8, bc_init_state=bc_state)
    match_ft = _match(run["model"])
    dropped = (match_bc["heldout"]["balanced_accuracy"]
               - match_ft["heldout"]["balanced_accuracy"])
    retained = bool(dropped <= 0.15
                    and match_ft["heldout"]["balanced_accuracy"] >= 0.55)
    results["per_seed"][f"seed{seed}"] = {
        "actor_state_sha256_before_bc": pre_hash,
        "actor_state_sha256_after_bc": post_hash,
        "actor_import_verified": actor_import_verified,
        "bc_training": bc_info,
        "behavior_match_after_bc": match_bc,
        "behavior_match_after_ppo_finetune": match_ft,
        "heldout_balanced_accuracy_drop": float(dropped),
        "bc_retained_rule": {
            "retained": retained,
            "rule": plan["interpretation_rules"]["bc_retained"],
        },
        "finetune_run_audit": {k: run[k] for k in (
            "cycles", "total_timesteps", "env_audit",
            "audit_problems", "pass")},
        "probability_after_finetune": probability_separation_summary(
            probability_metrics_on_bank(
                run["model"], eval_bank[:24],
                adapter=_probe_adapter_of(adapter))),
        "update_records_summary": {
            "n_updates": len(run["update_records"]),
            "final_approx_kl": (
                run["update_records"][-1].get("approx_kl")
                if run["update_records"] else None),
            "final_entropy_loss": (
                run["update_records"][-1].get("entropy_loss")
                if run["update_records"] else None),
        },
        "capture_after_finetune": _eval_d0_capture(
            run["model"], eval_bank, rung_params, thresholds,
            adapter=_probe_adapter_of(adapter)),
    }
    art = {
        "format": "ppo262-repair1-bc-warmstart-v1",
        "diagnostic_iteration": "s262_diag_r1",
        "diagnostic_only": True,
        "plan_digest": plan["plan_digest_self"],
        **results,
        "interpretation": {
            "bc_learned_and_retained": "representation 有效;主要 blocker "
                                       "= scratch exploration/初始化",
            "bc_learned_but_finetune_destroys": "PPO update/value/"
                                                "advantage 或成本局部最"
                                                "优摧毁选择性",
            "bc_cannot_learn": "representation/label boundary/preprocess"
                               " 问题",
        },
    }
    _w("bc_warmstart_results.json", art)
    print(json.dumps({
        "executed": True, "bc_arm": bc_arm,
        "bc_heldout_bal_acc": match_bc["heldout"]["balanced_accuracy"],
        "finetune_heldout_bal_acc": match_ft["heldout"][
            "balanced_accuracy"],
        "retained": retained}, ensure_ascii=False))
    return 0


# ============================================================ decision
def _arm_recovered(arm_results: dict[str, Any]) -> dict[str, Any]:
    """ppo_recovered_arm 规则的机械执行(3 seeds 中 >= 2 满足)。

    单 seed 满足 = 训练 bank 任一 capture cell > 0.05
    且任一族 probability gap > 0.05(eval bank final)
    且该族 deterministic behavior gap > 0.02。
    """
    flags = {}
    detail = {}
    for seed_tag, r in arm_results.items():
        caps = [v for v in r["train_bank_capture"]["capture_cells"].values()
                if v is not None]
        cap_ok = bool(caps) and max(caps) > 0.05
        prob_ok = False
        det_ok = False
        best = None
        for gap_key, gap_val in r["probability_final_eval"].items():
            if (gap_key.endswith("_probability_gap")
                    and gap_val is not None and gap_val > 0.05):
                fam_key = gap_key.split("_")[0]
                det_key = f"{fam_key}_det_gap"
                det_val = r["probability_final_eval"].get(det_key)
                if det_val is not None and det_val > 0.02:
                    prob_ok, det_ok = True, True
                    best = (gap_key, gap_val, det_key, det_val)
                    break
        flags[seed_tag] = bool(cap_ok and prob_ok and det_ok)
        detail[seed_tag] = {"capture_ok": cap_ok, "probability_ok": prob_ok,
                            "det_gap_ok": det_ok, "best_signal": best}
    n_pos = sum(1 for v in flags.values() if v)
    return {"flags": flags, "n_positive": n_pos,
            "recovered": n_pos >= 2, "detail": detail}


def cmd_decision(args) -> int:
    """决策树分支判定(机械执行 plan 预注册规则)。"""
    plan = _load_diag_plan()

    def _load(name: str) -> dict[str, Any] | None:
        p = REPAIR1_DIR / name
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file(
        ) else None

    abl = _load("preprocessing_ablation_results.json")
    sup = _load("supervised_probe_results.json")
    ovf = _load("ppo_overfit_results.json")
    bc = _load("bc_warmstart_results.json")
    missing = [n for n, d in (
        ("preprocessing_ablation_results.json", abl),
        ("supervised_probe_results.json", sup),
        ("ppo_overfit_results.json", ovf)) if d is None]
    if missing:
        print(f"缺少诊断产物,无法判定: {missing}", file=sys.stderr)
        return 2

    arm_flags = {arm: _arm_recovered(per)
                 for arm, per in abl["results"].items()}
    # supervised 分 arm 学习计数(任一族学会即计)
    sup_learned: dict[str, list[str]] = {}
    if sup:
        for fam, fr in sup["results"].items():
            for arm in ("unscaled", "fixed_causal", "train_fitted"):
                if fr[arm]["mlp_learned_rule"]["learned"]:
                    sup_learned.setdefault(arm, []).append(fam)
    # overfit(unscaled D0 重复暴露辅证)
    ovf_pass = {fam: r["overfit_nondegenerate"]["pass"]
                for fam, r in ovf["results"].items()}

    unscaled_rec = arm_flags.get("A_unscaled", {}).get("recovered", False)
    b_rec = arm_flags.get("B_fixed_causal", {}).get("recovered", False)
    c_rec = arm_flags.get("C_train_fitted", {}).get("recovered", False)
    any_scaled_rec = b_rec or c_rec
    unscaled_sup_learned = bool(sup_learned.get("unscaled"))
    any_sup_learned = bool(sup_learned)

    bc_executed = bool(bc and bc.get("executed"))
    bc_retained = bool(
        bc_executed and bc["per_seed"]
        and all(v["bc_retained_rule"]["retained"]
                for v in bc["per_seed"].values()))

    if any_sup_learned and not (unscaled_rec or any_scaled_rec):
        if bc_executed:
            branch = "C" if bc_retained else "D"
        else:
            # supervised 学会但 BC 未执行 => 证据不充分
            branch = "F"
    elif not any_sup_learned:
        branch = "E"
    elif unscaled_rec:
        branch = "A"
    elif any_scaled_rec:
        branch = "B"
    else:
        branch = "F"

    next_stage = {
        "A": "Stage 2.6.2 s262_r1 official rerun(全新 official seeds;"
             "无需先改 2.6.1 contract)",
        "B": "Stage 2.6.1 Repair R3(冻结新 preprocessing contract;"
             "reference/baseline 适配;新 calibration/robustness/"
             "qualification/final qualification;然后 2.6.2 s262_r1)",
        "C": "单独设计并治理 reference-guided warm-start / curriculum "
             "bootstrap / 不改 reward 的初始化方案(不自动纳入正式路线)",
        "D": "PPO optimization repair:advantage normalization / critic "
             "stabilization / smaller updates / KL control / actor-"
             "critic LR 分离 / cost transition dynamics(仍不进 2.6.3)",
        "E": "Stage 2.6.1 Repair R3:重审课程可学习性(observation/"
             "reference boundary/generator),而非继续 PPO 调参",
        "F": "Diagnostics INCONCLUSIVE -> Repair R1 FAIL;"
            "补充对照实验后再判",
    }[branch]

    art = {
        "format": "ppo262-repair1-diagnostic-decision-v1",
        "diagnostic_iteration": "s262_diag_r1",
        "rules_applied": plan["interpretation_rules"],
        "evidence": {
            "arm_recovery": arm_flags,
            "supervised_learned_arms": sup_learned,
            "overfit_nondegenerate_by_family": ovf_pass,
            "bc": {"executed": bc_executed, "retained": bc_retained},
        },
        "branch": branch,
        "branch_meaning": plan["interpretation_rules"][
            "branch_decision"][branch],
        "recommended_next_stage": next_stage,
        "official_stage_status_unchanged": "Stage 2.6.2 = FAIL"
                                           "(Repair R1 不改变)",
        "final_namespace_unconsumed": True,
    }
    _w("diagnostic_decision.json", art)
    print(json.dumps({"branch": branch, "next": next_stage,
                      "arms": {a: f["recovered"]
                               for a, f in arm_flags.items()}},
                     ensure_ascii=False))
    return 0


# ============================================================ summary
def cmd_summary(args) -> int:
    """诊断汇总(机器可读底稿;不产生 official verdict)。"""
    files = [
        "diagnostic_namespace_integrity.json", "baseline_integrity.json",
        "config_metric_repair.json", "official_gate_repair.json",
        "episode_attribution.json", "update_metric_binding.json",
        "feature_scale_profile.json", "feature_activation_profile.json",
        "supervised_probe_results.json", "ppo_overfit_results.json",
        "preprocessing_ablation_results.json",
        "paired_initialization_integrity.json",
        "paired_manifest_integrity.json", "bc_warmstart_results.json",
        "diagnostic_decision.json",
    ]
    checks: dict[str, Any] = {}
    for f in files:
        p = REPAIR1_DIR / f
        if not p.is_file():
            checks[f] = None
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        checks[f] = d.get("pass", "present")
    decision = REPAIR1_DIR / "diagnostic_decision.json"
    branch = (json.loads(decision.read_text(encoding="utf-8"))["branch"]
              if decision.is_file() else None)
    infra_keys = (
        "diagnostic_namespace_integrity.json", "baseline_integrity.json",
        "config_metric_repair.json", "official_gate_repair.json",
        "episode_attribution.json", "update_metric_binding.json",
        "paired_initialization_integrity.json")
    infra_ok = all(checks.get(k) is True for k in infra_keys)
    complete = all(v is not None for v in checks.values())
    branch_ok = branch in ("A", "B", "C", "D", "E")
    art = {
        "format": "ppo262-repair1-regression-summary-v1",
        "checks": checks,
        "branch": branch,
        "repair1_diagnostics_pass": bool(infra_ok and complete
                                         and branch_ok),
        "note": "Repair R1 PASS 仅表示诊断基础设施有效、对照完成、"
                "分支明确;Stage 2.6.2 仍为 FAIL",
    }
    _w("regression_summary.json", art)
    print(json.dumps(art, ensure_ascii=False))
    return 0


def cmd_episode_attribution_artifact(args) -> int:
    """Repair C/D 修复证据 artifact(小规模实跑训练验证)。"""
    from rl_curriculum.ppo262_diag_train import diag_train_run
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES

    bank = _gen_diag_bank("diag262r1_smoke", ("c1_opportunity",), ("D0",),
                          1, 0, progress=False)
    run = diag_train_run(
        bank, config=PPO262_CANDIDATES["cand_a_center"], model_seed=27101,
        total_timesteps=2 * len(bank) * 287,
        run_label="diag/attribution-smoke")
    curve = run["episode_curve"]
    attr_ok = bool(curve) and all(
        r["episode_key"] and r["family"] and r["rung"] is not None
        and r["pair_index"] is not None and r["variant"]
        and r["manifest_index"] is not None for r in curve)
    keys = [r["episode_key"] for r in curve]
    manifest_aligned = keys == [e.key.canonical() for e in bank] * 2
    upd = run["update_records"]
    upd_ok = bool(upd) and all(
        "approx_kl" in u and "update_index" in u and "rollout_index" in u
        for u in upd)
    monotonic = [u["update_index"] for u in upd] == sorted(
        u["update_index"] for u in upd)
    no_missing = all(not u["missing_metrics"] for u in upd)
    art = {
        "format": "ppo262-repair1-attribution-update-binding-v1",
        "episode_attribution": {
            "terminal_info_keeps_identity": attr_ok,
            "curve_manifest_alignment": manifest_aligned,
            "sample_row": curve[0] if curve else None,
            "staged_order_verifiable": True,
        },
        "update_metric_binding": {
            "first_update_has_data": upd_ok,
            "update_index_monotonic": monotonic,
            "rollout_index_bound_1to1": all(
                u["rollout_index"] == u["update_index"] for u in upd),
            "no_silent_missing_metrics": no_missing,
            "sample_record": upd[0] if upd else None,
        },
        "run_audit": {k: run[k] for k in (
            "cycles", "total_timesteps", "env_audit", "audit_problems",
            "pass")},
        "pass": bool(attr_ok and manifest_aligned and upd_ok and monotonic
                     and no_missing and run["pass"]),
    }
    _w("episode_attribution.json", {
        "format": "ppo262-repair1-episode-attribution-v1",
        "terminal_info_keeps_identity": attr_ok,
        "curve_manifest_alignment": manifest_aligned,
        "pass": bool(attr_ok and manifest_aligned),
        "sample": art["episode_attribution"]["sample_row"],
    })
    _w("update_metric_binding.json", {
        "format": "ppo262-repair1-update-metric-binding-v1",
        **art["update_metric_binding"],
        "pass": bool(upd_ok and monotonic and no_missing),
    })
    print(json.dumps({"pass": art["pass"]}, ensure_ascii=False))
    return 0 if art["pass"] else 2


# ============================================================ main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ppo262-diagnose")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("namespace-integrity").set_defaults(
        func=cmd_namespace_integrity)
    sub.add_parser("baseline-integrity").set_defaults(
        func=cmd_baseline_integrity)
    sub.add_parser("repair-verify").set_defaults(func=cmd_repair_verify)
    sub.add_parser("feature-scale").set_defaults(func=cmd_feature_scale)
    sub.add_parser("plan-lock").set_defaults(func=cmd_plan_lock)
    sub.add_parser("supervised").set_defaults(func=cmd_supervised)
    sub.add_parser("overfit").set_defaults(func=cmd_overfit)
    sub.add_parser("preprocessing").set_defaults(func=cmd_preprocessing)
    sub.add_parser("bc-warmstart").set_defaults(func=cmd_bc_warmstart)
    sub.add_parser("decision").set_defaults(func=cmd_decision)
    sub.add_parser("summary").set_defaults(func=cmd_summary)
    sub.add_parser("attribution-smoke").set_defaults(
        func=cmd_episode_attribution_artifact)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
