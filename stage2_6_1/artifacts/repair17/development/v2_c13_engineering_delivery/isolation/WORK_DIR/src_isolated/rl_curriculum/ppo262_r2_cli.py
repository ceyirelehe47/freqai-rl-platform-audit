"""阶段 2.6.2 Repair R2:diagnostic workflow CLI(s262_diag_r2)。

命令族(全部只写 artifacts/route_c_stage2_6_2/repair2/ 与
models/ppo262/repair2/;与 official、s262_diag_r1 完全分离):

- r2-namespace-integrity   R2 诊断 namespace 隔离枚举证明
- r2-baseline-integrity    基线/历史绑定 + Route C/2.6.1 只读边界
- r2-plan-lock             诊断计划锁定(任何 r2 train/eval bank 前)
- r2-evaluator-validation  family-aware evaluator sentinel 回归
- r2-gradient-verify       PPO surrogate 梯度单 minibatch 等价验证
- r2-supervised            family 分开监督对照(U/W/B × 3 seeds)
- r2-scratch               family 分开 scratch PPO(3 arms × 3 seeds)
- r2-bc                    family 分开 BC(3 seeds 全部执行)
- r2-family-decision       按 family 的 branch 判定 + global 路线
- r2-semantic-validation   语义 validator(计划执行/评估器/梯度/BC/branch)
- r2-summary               汇总

诊断命令不得生成 official PASS、不得写 official final plan、不得消费
ppo_final_eval_262、不得复用 official final namespace。
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
)
from rl_curriculum.ppo262_namespaces import ppo262_artifacts_dir
from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_SMOKE_NS,
    DIAG262R2_INTEGRITY_NS, bc_eval_namespace, bc_train_namespace,
    scratch_eval_namespace, scratch_train_namespace,
    supervised_eval_namespace, supervised_train_namespace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPAIR2_DIR = ppo262_artifacts_dir() / "repair2"
REPAIR1_DIR = ppo262_artifacts_dir() / "repair1"
MODELS_REPAIR2_DIR = PROJECT_ROOT / "models" / "ppo262" / "repair2"

#: 基线绑定(任务书):本轮启动基线 = R1 检查点(独立审查判 FAIL);
#: s262_r0 FAIL 检查点;2.6.1 R2 PASS 基线
R2_START_SHA = "af871ee9c9e449c541dfdb5c8412d4c69f85c55e"
S262_DIAG_R1_FAIL_SHA = "af871ee9c9e449c541dfdb5c8412d4c69f85c55e"
S262_R0_FAIL_SHA = "7481b39b3d141a21b845a111b9f48e036c5f98f5"
R261_R2_PASS_SHA = "1927faa647d34e4f45ed9c46d100f500081560b8"
VENDOR_SHA = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"

#: 独立审查对 R1 的判定(历史证据,不得改写)
R1_INDEPENDENT_REVIEW = {
    "verdict": "FAIL",
    "branch": "F / INCONCLUSIVE",
    "findings": [
        "mixed-family evaluator 以 bank[0].family 的 reference 评估整个"
        " bank(C2/C3 capture 无效)",
        "BC 计划锁定 3 seeds,实际只执行 1 个",
        "Arm B 实际读取 train-bank 标准差(coarse_train_fitted),不是"
        " data-independent fixed scaling",
        "预注册的 probability checkpoints 实际为空",
        "gradient probe 用行为模仿式 -log_prob(action),不是 PPO "
        "clipped surrogate gradient",
        "C2 supervised MLP 无 2.4% Long label 的类别不平衡控制",
        "diagnostics PASS validator 大量只检查文件存在,没有语义验证",
    ],
}

# ============================================================ 预算/规格
#: R2 诊断 bank 规格(冻结进 plan;所有命令共用)
R2_BANK_SPEC: dict[str, Any] = {
    "supervised": {
        "train": {"namespace": supervised_train_namespace(),
                  "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 6,
                  "pair_base": 0},
        "eval": {"namespace": supervised_eval_namespace(),
                 "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 6,
                 "pair_base": 256},
    },
    "scratch": {
        "train_per_family_slot": {
            "rungs": ["D0", "D1"], "pairs_per_rung": 4,
            "pair_base_rule": "slot*32"},
        "eval_per_family": {
            "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 4,
            "pair_base": 256},
        "episodes_per_bank": 16, "cycles": 18,
        "steps_per_seed": 16 * 287 * 18,           # 82,656
        "episodes_total": 288,
        # checkpoint 边界 = ceil(fraction × 288) 向上取整到 bank 边界
        # (16 的倍数):5%->16,10%->32,25%->80,50%->144,100%->288
        "checkpoint_episodes": [0, 16, 32, 80, 144, 288],
    },
    "bc": {
        "train_per_family_slot": {
            "rungs": ["D0", "D1"], "pairs_per_rung": 2,
            "pair_base_rule": "slot*32"},
        "eval_per_family_slot": {
            "rungs": ["D0", "D1", "D2"], "pairs_per_fr": 4,
            "pair_base_rule": "256 + slot*32"},
        "episodes_per_bank": 8,
        "bc_epochs": 30, "bc_lr": 3e-4, "class_weighted": True,
        "finetune_cycles": 12, "steps_finetune": 8 * 287 * 12,  # 27,552
        "episodes_total": 96,
        # checkpoint 边界 = ceil(fraction × 96) 到 bank 边界(8 的倍数):
        # 5%->8,10%->16,25%->24,50%->48,100%->96
        "checkpoint_episodes": [0, 8, 16, 24, 48, 96],
        "checkpoint_tags": ["after_bc_before_ppo", "ep8", "ep16",
                            "ep24", "ep48", "ep96"],
    },
}

#: branch 阈值(预注册)
R2_BRANCH_THRESHOLDS = {
    "recovery_eval_capture": 0.0,
    "recovery_probability_gap": 0.05,
    "recovery_det_behavior_gap": 0.02,
    "recovery_min_seeds": 2,
    "supervised_balanced_accuracy": 0.60,
    "supervised_behavior_gap_proxy": 0.20,
    "supervised_min_seeds": 2,
    "bc_retained_max_drop": 0.15,
    "bc_retained_min_final_bal_acc": 0.55,
    "bc_learned_min_bal_acc": 0.55,
    "bc_min_seeds": 2,
}

#: 预注册解读规则(与阈值一致的自然语言合同)
R2_INTERPRETATION_RULES = {
    "ppo_recovered_arm_family": (
        "同族 >= 2/3 seeds:family eval capture > 0(该族 valid "
        "reference gap)且该族 probability gap > 0.05 且该族 "
        "deterministic behavior gap > 0.02"),
    "supervised_learned": (
        "held-out balanced_accuracy >= 0.60 且 behavior_gap_proxy "
        ">= 0.20(>= 2/3 supervised seeds;C2 判 E 需要 W/B 类平衡"
        "对照也失败)"),
    "bc_arm_selection": (
        "按 A unscaled -> B fixed -> C train_fitted 顺序取第一个"
        " supervised learned 的 arm(基于 supervised 诊断结果,规则"
        "预注册;全部 arm 未学会则该族不执行 BC)"),
    "bc_retained": (
        "fine-tune 后 held-out balanced accuracy 相对 BC 结束值绝对"
        "下降 <= 0.15 且仍 >= 0.55"),
    "bc_destroyed": (
        "BC 结束 held-out >= 0.55(学会)且 fine-tune 后下降 > 0.15 "
        "或低于 0.55"),
    "family_branches": {
        "A": "Arm A(unscaled)scratch PPO 该族恢复(>=2/3 seeds)",
        "B": "Arm A 不满足,Arm B 或 C 该族恢复(>=2/3 seeds)",
        "C": "scratch 全不满足;supervised/BC 可学;fine-tune 保留"
             "(>=2/3 seeds)",
        "D": "scratch 全不满足;BC held-out 可学;fine-tune 摧毁"
             "(>=2/3 seeds)",
        "E": "linear 与 class-balanced MLP 在所有 arms 上都学不会"
             " reference action",
        "F": "证据分裂/冲突/不充分(checkpoint 缺失、denominator "
             "无效、evaluator 语义不确定、未执行全部计划)",
    },
}


def _w(name: str, payload: Any) -> Path:
    REPAIR2_DIR.mkdir(parents=True, exist_ok=True)
    p = REPAIR2_DIR / name
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
    from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
    from rl_curriculum.curriculum261_plan import load_locked_plan
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["rung_params"] for fam, fp in plan["families"].items()}


def _locked_reference_thresholds() -> dict[str, Any]:
    from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
    from rl_curriculum.curriculum261_plan import load_locked_plan
    plan, _ = load_locked_plan(qualification_r2_lock_marker().parent)
    return {fam: fp["reference_thresholds"]
            for fam, fp in plan["families"].items()}


def _r2_plan_digest() -> str:
    from rl_curriculum.ppo262_input_lock import R2_EXPECTED_PLAN_DIGEST
    return R2_EXPECTED_PLAN_DIGEST


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_identity_r2() -> dict[str, str]:
    out = {}
    for f in sorted((PROJECT_ROOT / "src" / "rl_curriculum").glob(
            "ppo262_r2*.py")):
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
def _r2_bank_keys(namespace: str, families, rungs, n_pairs: int,
                  pair_base: int) -> list:
    from rl_curriculum.ppo262_banks import EpisodeKey
    keys = []
    for fam in families:
        for rung in rungs:
            for j in range(n_pairs):
                for v in ("A", "B"):
                    keys.append(EpisodeKey(
                        namespace, fam, rung, pair_base + j, v))
    return keys


def _gen_r2_bank(namespace: str, families, rungs, n_pairs: int,
                 pair_base: int, *, progress: bool = False):
    from rl_curriculum.ppo262_banks import generate262_bank
    from rl_curriculum.ppo262_r2_namespaces import derive262r2_seed
    keys = _r2_bank_keys(namespace, families, rungs, n_pairs, pair_base)
    return generate262_bank(
        keys, locked_plan_rung_params=_locked_rung_params(),
        progress=progress, derive_seed_fn=derive262r2_seed)


def _bank_manifest_hash(bank) -> str:
    payload = json.dumps([e.key.canonical() for e in bank],
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ============================================================ namespace
def cmd_namespace_integrity(args) -> int:
    from rl_curriculum.ppo262_r2_namespaces import (
        verify_r2_namespace_isolation,
    )
    t0 = time.time()
    art = verify_r2_namespace_isolation(
        pair_range=range(0, 1024),
        official_pair_range=range(0, 2048),
        r1_pair_range=range(0, 1024),
        pair_range_261=range(0, 2048))
    art["namespaces_official_262_preserved"] = (
        "s262_r0 11 个 namespace 不变(ppo262_namespaces."
        "all_262_namespaces)")
    art["namespaces_diag_r1_preserved"] = (
        "s262_diag_r1 11 个 diag262r1_* namespace 不变(只读)")
    _w("diagnostic_namespace_integrity.json", art)
    print(json.dumps({"pass": art["pass"],
                      "problems": art["problems"][:3],
                      "elapsed_s": round(time.time() - t0, 1)},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


# ============================================================ baseline
def cmd_baseline_integrity(args) -> int:
    """基线/历史绑定 + 只读边界 + R1 evidence 保留哈希。"""
    route_c = _route_c_integrity()
    ok = bool(route_c["input_lock_pass"])
    vendor_pinned = route_c["vendor_sha"] == VENDOR_SHA
    ok = ok and vendor_pinned and route_c["vendor_clean"]

    r0_files = sorted(p.name for p in ppo262_artifacts_dir().glob(
        "*.json"))
    r1_files = sorted(p.name for p in REPAIR1_DIR.glob("*")
                      if p.is_file()) if REPAIR1_DIR.is_dir() else []
    r1_hashes = {p.name: _sha256_file(p) for p in
                 sorted(REPAIR1_DIR.glob("*")) if p.is_file()} \
        if REPAIR1_DIR.is_dir() else {}
    r1_report = PROJECT_ROOT / "reports" / (
        "route_c_stage2_6_2_repair1_diagnostics.md")
    r0_report = PROJECT_ROOT / "reports" / (
        "route_c_stage2_6_2_small_ppo_teaching.md")

    art = {
        "format": "ppo262-repair2-baseline-integrity-v1",
        "iteration": "s262_diag_r2",
        "r2_start_git_sha": R2_START_SHA,
        "s262_diag_r1_fail_commit": S262_DIAG_R1_FAIL_SHA,
        "s262_r0_fail_commit": S262_R0_FAIL_SHA,
        "r261_r2_pass_sha": R261_R2_PASS_SHA,
        "vendor_sha_expected": VENDOR_SHA,
        "vendor_pinned": vendor_pinned,
        "r2_qualification_plan_digest": _r2_plan_digest(),
        "route_c": route_c,
        "code_identity_r2_at_start": _code_identity_r2(),
        "historical_s262_r0_artifacts_present": r0_files,
        "historical_s262_r0_report_present": r0_report.is_file(),
        "historical_r1_report_present": r1_report.is_file(),
        "preservation_contract": (
            "s262_r0 与 s262_diag_r1 的 artifacts/models/report 一律"
            "只读(历史证据不得覆盖/删除/重写);R2 全部输出写 "
            "repair2/;不修改旧 artifact 让旧报告变正确"),
        "stage261_readonly": {
            "generators": "frozen(R2 code_identity 绑定,input lock)",
            "family_versions": "frozen",
            "rung_params_source": "locked R2 qualification plan",
            "qualification_artifacts": "read-only",
            "r2_exposure_marker": "untouched",
        },
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pass": ok,
    }
    _w("baseline_integrity.json", art)

    _w("route_c_integrity.json", {
        "format": "ppo262-repair2-route-c-integrity-v1",
        **route_c,
        "frozen_contracts": [
            "RouteCEnvCore-v1.0.0", "ObservationSpec-v1",
            "BinaryLongFlatAction-v1", "NetLogEquityReward-v1",
            "MarketOpenCausalExecution-v1", "TerminalLiquidation-v1",
        ],
        "unchanged_fields": ["fee", "slippage", "price_tick", "ledger",
                             "reward", "action", "execution timing",
                             "terminal liquidation",
                             "observation feature", "position slot"],
        "pass": bool(route_c["input_lock_pass"]
                     and route_c["vendor_sha"] == VENDOR_SHA),
    })
    _w("stage261_readonly.json", {
        "format": "ppo262-repair2-stage261-readonly-v1",
        "r2_plan_digest": _r2_plan_digest(),
        "readonly": ["C1/C2/C3 generators", "family versions",
                     "rung params", "pair construction",
                     "reference policies", "required baselines",
                     "R2 calibration/qualification artifacts",
                     "R2 qualification plan", "R2 exposure marker"],
        "input_lock_pass": route_c["input_lock_pass"],
        "pass": bool(route_c["input_lock_pass"]),
    })
    _w("historical_diagnostic_binding.json", {
        "format": "ppo262-repair2-historical-binding-v1",
        "iterations": {
            "s262_r0": {"status": "official experiment FAIL",
                        "commit": S262_R0_FAIL_SHA,
                        "artifacts_root_files": r0_files},
            "s262_diag_r1": {
                "agent_claim": "Repair R1 Diagnostics: PASS / Branch D",
                "independent_review": R1_INDEPENDENT_REVIEW,
                "binding": "独立审查结论为准:FAIL / Branch F;R1 报告"
                           "与 artifacts 原样保留作为诚实的诊断失败"
                           "历史",
                "commit": S262_DIAG_R1_FAIL_SHA,
                "artifact_files": r1_files,
                "artifact_sha256": r1_hashes,
            },
            "s262_diag_r2": {"status": "当前诊断 iteration(本目录)"},
        },
        "pass": bool(r0_files and r1_files and r1_report.is_file()
                     and r0_report.is_file()),
    })
    print(json.dumps({"input_lock_pass": ok,
                      "r1_artifacts_hashed": len(r1_hashes)},
                     ensure_ascii=False))
    return 0 if ok else 2


# ============================================================ plan lock
#: Arm B 常数机械规则:R1 已暴露的 feature_scale_profile.json
#: (s262_r0 official corpus 统计,历史 artifact;零读取任何
#: diag262r2 bank)逐特征 std -> 10^round(log10(std));center=0;
#: position slot identity
ARM_B_RULE = ("scale_i = 10^round(log10(std_i of "
              "repair1/feature_scale_profile.json:config_dev_train "
              "per_feature));center=0;position=identity;"
              "来源 artifact sha256 记录于 fixed_scaling_contract")


def _arm_b_constants_from_r1_profile() -> dict[str, Any]:
    """从 R1 历史 artifact 机械推导 Arm B 常数(不生成/读取任何 r2 bank)。"""
    prof_path = REPAIR1_DIR / "feature_scale_profile.json"
    if not prof_path.is_file():
        raise SystemExit(
            f"缺少 R1 历史 artifact {prof_path}(Arm B 常数依据)")
    prof = json.loads(prof_path.read_text(encoding="utf-8"))
    per_feature = prof["banks"]["config_dev_train"]["per_feature"]
    names = list(prof["observation_layout"])
    stds = np.array([per_feature[n]["std"] for n in names], dtype=np.float64)
    with np.errstate(divide="ignore"):
        logs = np.where(stds > 0, np.log10(np.where(stds > 0, stds, 1.0)),
                        0.0)
    scale = np.power(10.0, np.round(logs))
    scale[-1] = 1.0  # position slot identity
    center = np.zeros_like(scale)
    return {
        "feature_names": names,
        "center": [float(v) for v in center],
        "scale": [float(v) for v in scale],
        "source_artifact": "repair1/feature_scale_profile.json"
                           "(s262_r0 official corpus config_dev_train)",
        "source_artifact_sha256": _sha256_file(prof_path),
        "rule": ARM_B_RULE,
        "no_r2_data_access": (
            "常数推导只读取 R1 历史 artifact(已提交于 af871ee);"
            "不读取任何 diag262r2 train/eval bank(此时尚未生成);"
            "不在每 episode 拟合;不根据结果调整"),
    }


def cmd_plan_lock(args) -> int:
    """R2 诊断计划锁定(在任何正式 diag262r2 train/eval bank 之前)。"""
    lock = REPAIR2_DIR / "diagnostic_plan.json"
    if lock.is_file():
        print(f"诊断计划已锁定({lock}),拒绝重锁", file=sys.stderr)
        return 2
    from rl_curriculum.ppo262_r2_namespaces import (
        DIAG262R2_BC_SEEDS, DIAG262R2_NAMESPACES,
        DIAG262R2_PROB_RNG_SEED, DIAG262R2_SCRATCH_SEEDS,
        DIAG262R2_SUPERVISED_SEEDS, DIAG262R2_EVAL_PAIR_BASE,
        DIAG262R2_SEED_PAIR_STRIDE,
    )

    arm_b = _arm_b_constants_from_r1_profile()

    plan = {
        "format": "ppo262-repair2-diagnostic-plan-v1",
        "diagnostic_iteration": "s262_diag_r2_1",
        "supersedes": {
            "s262_diag_r2_lock_dp-0551c1a1": (
                "gradient-verify clipping 单调检查浮点容差缺陷;在任何"
                "正式 bank 生成前发现,repair2 清空重锁,零证据"),
            "s262_diag_r2_lock_dp-0a0c2e2c": (
                "_checkpoint_diagnostics 缺 evaluate_family_cells 导入,"
                "首个 scratch run 的 checkpoint 评估即 NameError 崩溃"
                "(scratch/BC 零模型证据);按任务书 §13 迭代结束,重启"
                "为 s262_diag_r2_1 + 新 namespace/seed 空间;该锁下"
                "生成过的 supervised 证据随迭代作废并重新执行"),
        },
        "baseline_git_sha": R2_START_SHA,
        "s262_r0_fail_commit": S262_R0_FAIL_SHA,
        "s262_diag_r1_fail_commit": S262_DIAG_R1_FAIL_SHA,
        "r261_r2_pass_sha": R261_R2_PASS_SHA,
        "r2_qualification_plan_digest": _r2_plan_digest(),
        "vendor_sha": VENDOR_SHA,
        "namespaces": list(DIAG262R2_NAMESPACES),
        "model_seeds": {
            "supervised": list(DIAG262R2_SUPERVISED_SEEDS),
            "scratch": list(DIAG262R2_SCRATCH_SEEDS),
            "bc": list(DIAG262R2_BC_SEEDS),
        },
        "prob_rng_seed": DIAG262R2_PROB_RNG_SEED,
        "pair_isolation": {
            "seed_slot_stride": DIAG262R2_SEED_PAIR_STRIDE,
            "eval_pair_base": DIAG262R2_EVAL_PAIR_BASE,
            "bc_eval_pair_base_rule": "256 + slot*32",
        },
        "ppo_config_source": "cand_a_center(s262_r0 中心候选,诊断对照"
                             "配置;非有效 official 选择)",
        "bank_spec": R2_BANK_SPEC,
        "arms": {
            "A_unscaled": {
                "adapter": "identity(bitwise = s262_r0/R2 observation)",
            },
            "B_fixed_precommitted": {
                "rule": ARM_B_RULE,
                "constants": arm_b,
                "constructor_contract": (
                    "ObsAdapter.fixed(center, scale) 构造器不接受任何"
                    "训练数据;常数在本计划锁定时冻结(先于任何 "
                    "diag262r2 bank 生成)"),
            },
            "C_train_bank_fitted_frozen": {
                "rule": "per family/seed train bank mean/std z-score;"
                        "fit 后冻结应用于该 family/seed 的训练与评估;"
                        "position slot identity;eval 不参与 fit",
            },
            "legacy_r1_arm_b_reclassified": (
                "s262_diag_r1 的 Arm B(10^round(log10(std_trainbank)) "
                "读 diag 训练 bank)重新命名为 coarse_train_fitted,"
                "仅历史对照,不得再称为 fixed scaling"),
        },
        "supervised_controls": {
            "controls": ["U(unweighted,历史对照)", "W(class-weighted CE,"
                         "权重只来自 train labels)",
                         "B(balanced minibatches,不改 eval 分布)"],
            "seeds": list(DIAG262R2_SUPERVISED_SEEDS),
            "models": ["LogisticRegression(control U)",
                       "MLP [128,128] Tanh Adam lr=3e-4 20ep(全控制)"],
            "c2_note": "C2 判 Branch E 需要 W 与 B 类平衡对照在全部 "
                       "arms 上都失败;单一 unweighted seed 不得认定 "
                       "C2 representation 不可学",
        },
        "branch_thresholds": R2_BRANCH_THRESHOLDS,
        "interpretation_rules": R2_INTERPRETATION_RULES,
        "evaluator_identity": {
            "module": "ppo262_r2_evaluator",
            "contract": [
                "evaluate_single_family_bank 拒绝 mixed bank",
                "evaluate_mixed_family_bank 显式 family × rung 分组",
                "每 cell 记录 reference identity(threshold 解析值)",
                "denominator R<=B -> invalid_reference_gap,capture=None",
                "probability 评估禁止 first-N 切片(全族分层)",
            ],
        },
        "gradient_instrumentation_identity": {
            "module": "ppo262_r2_train.DiagnosedPPO2",
            "contract": [
                "train() 为 SB3 2.9.0 PPO.train() 忠实副本",
                "真实 loss.backward() 后、clip/step 前记录 .grad",
                "pre/post clipping norm 都记录",
                "首个 minibatch 张量克隆保存供单 minibatch 等价测试",
                "记录绑定 {update_index, minibatch_index}",
            ],
        },
        "checkpoint_schedule": {
            "scratch_tags_per_run": ["ep0", "ep16", "ep32", "ep80",
                                     "ep144", "ep288"],
            "bc_tags_per_run": R2_BANK_SPEC["bc"]["checkpoint_tags"],
            "persistence": "policy state dict 落盘(.pt)+ policy/actor/"
                           "critic/optimizer 哈希;可重新加载评估;"
                           "缺失即 FAIL",
        },
        "code_identity_r2": _code_identity_r2(),
        "route_c_identity": _route_c_integrity(),
        "forbidden": [
            "修改 2.6.1 R2 observation contract / qualification artifacts",
            "把 scaled arm 升级为正式合同(仅 diagnostic evidence)",
            "触碰 ppo_final_eval_262 / qualification_r2",
            "声称 scaled diagnostic 通过 Stage 2.6.2",
            "根据结果改 Arm B 常数 / 增删 seed / 改预算 / 改 checkpoint "
            "/ 改 branch 阈值 / 改 family evaluator",
        ],
        "locked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    payload = json.dumps(plan, sort_keys=True, ensure_ascii=False)
    digest = "dp-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    plan["plan_digest_self"] = digest
    _w("diagnostic_plan.json", plan)
    (REPAIR2_DIR / "diagnostic_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    _w("fixed_scaling_contract.json", {
        "format": "ppo262-repair2-fixed-scaling-contract-v1",
        "arm": "B_fixed_precommitted",
        **arm_b,
        "constructor_signature": "ObsAdapter.fixed(center, scale, *, "
                                 "source)——不接受 X_train",
        "locked_before_any_r2_bank": True,
        "pass": bool(all(s > 0 for s in arm_b["scale"])
                     and arm_b["scale"][-1] == 1.0),
    })
    print(json.dumps({"locked": True, "digest": digest,
                      "arm_b_scale": arm_b["scale"]},
                     ensure_ascii=False))
    return 0


def _load_r2_plan() -> dict[str, Any]:
    p = REPAIR2_DIR / "diagnostic_plan.json"
    if not p.is_file():
        raise SystemExit("R2 诊断计划未锁定:先运行 r2-plan-lock")
    plan = json.loads(p.read_text(encoding="utf-8"))
    payload = {k: v for k, v in plan.items() if k != "plan_digest_self"}
    expect = "dp-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False).encode(
        "utf-8")).hexdigest()
    if expect != plan.get("plan_digest_self"):
        raise SystemExit("R2 诊断计划 digest 校验失败(fail closed)")
    return plan


# ============================================================ evaluator
def cmd_evaluator_validation(args) -> int:
    """family-aware evaluator sentinel 回归(真实三族 bank)。"""
    from rl_curriculum.ppo262_diag_metrics import (
        probability_metrics_on_bank,
    )
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    from rl_curriculum.ppo262_metrics import (
        evaluate_policy_on_bank, build_261_policy_set,
    )
    from rl_curriculum.ppo262_r2_evaluator import (
        MixedFamilyBankError, evaluate_mixed_family_bank,
        evaluate_single_family_bank, EXPECTED_REFERENCE_CLASS,
    )

    plan = _load_r2_plan()
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()

    bank = _gen_r2_bank(DIAG262R2_INTEGRITY_NS, CURRICULUM261_FAMILIES,
                        ("D0", "D1"), 2, 0)
    pol = build_261_policy_set(
        "c1_opportunity", rung_params["c1_opportunity"]["D1"],
        thresholds["c1_opportunity"])["reference"]

    mixed = evaluate_mixed_family_bank(
        pol, bank, rung_params, thresholds)
    singles = {}
    for fam in CURRICULUM261_FAMILIES:
        fam_bank = [e for e in bank if e.key.family == fam]
        singles[fam] = evaluate_single_family_bank(
            pol, fam_bank, rung_params, thresholds)

    # 1) mixed 与逐族 single 的 cell 数值一致(同一 episodes/reference)
    cell_match = True
    for fam in CURRICULUM261_FAMILIES:
        for rung, cell in mixed["cells"][fam].items():
            scell = singles[fam]["cells"][fam][rung]
            for k in ("reference_mean", "baseline_means", "denominator",
                      "capture", "status"):
                if cell[k] != scell[k]:
                    cell_match = False

    # 2) reference identity 正确(逐族逐 rung)
    identity_ok = True
    for fam in CURRICULUM261_FAMILIES:
        for rung, cell in mixed["cells"][fam].items():
            ident = cell["reference_identity"]
            if ident["reference_class"] != EXPECTED_REFERENCE_CLASS[fam]:
                identity_ok = False
            if not ident["reference_class_matches_family_contract"]:
                identity_ok = False

    # 3) bank[0].family bug 复现:用 C1 的 policy set 评估全 bank
    #    (R1 错误路径)——C2/C3 cells 的 reference_mean 必须与正确
    #    评估不同,证明该 shortcut 会被检测
    from rl_curriculum.ppo262_metrics import PPO262_REQUIRED_BASELINES
    buggy_divergence: dict[str, Any] = {}
    by_rung: dict[tuple, list] = {}
    for e in bank:
        by_rung.setdefault((e.key.family, e.key.rung), []).append(e)
    for (fam, rung), eps in sorted(by_rung.items()):
        pols = build_261_policy_set(
            "c1_opportunity",
            rung_params["c1_opportunity"][rung],
            thresholds["c1_opportunity"])
        ref_rows = evaluate_policy_on_bank(
            pols["reference"], eps, collect_actions=False)
        buggy_ref_mean = float(np.mean(
            [r["net_return"] for r in ref_rows]))
        correct = mixed["cells"][fam][rung]["reference_mean"]
        buggy_divergence[f"{fam}/{rung}"] = {
            "buggy_bank0_reference_mean": buggy_ref_mean,
            "correct_reference_mean": correct,
            "divergent": buggy_ref_mean != correct,
        }
    bug_detectable = all(
        v["divergent"] for k, v in buggy_divergence.items()
        if not k.startswith("c1_opportunity/"))

    # 4) 单族评估器拒绝 mixed bank
    rejected_mixed = False
    try:
        evaluate_single_family_bank(pol, bank, rung_params, thresholds)
    except MixedFamilyBankError:
        rejected_mixed = True

    # 5) probability 分层合同(全族,非 first-N):由 scratch/bc 命令
    #    的 per-family 全量调用保证(逐族 eval bank,无 [:N] 切片)
    fam_counts = mixed["family_episode_counts"]

    art = {
        "format": "ppo262-repair2-family-evaluator-validation-v1",
        "plan_digest": plan["plan_digest_self"],
        "namespace": f"{DIAG262R2_INTEGRITY_NS}(非训练语料)",
        "family_episode_counts": fam_counts,
        "mixed_vs_single_family_cells_identical": cell_match,
        "reference_identity_per_family": {
            fam: {
                rung: cell["reference_identity"]["reference_class"]
                for rung, cell in mixed["cells"][fam].items()}
            for fam in CURRICULUM261_FAMILIES},
        "reference_identity_matches_contract": identity_ok,
        "required_baselines_per_family": {
            fam: sorted({
                b for cell in mixed["cells"][fam].values()
                for b in cell["reference_identity"]["required_baselines"]})
            for fam in CURRICULUM261_FAMILIES},
        "expected_required_baselines": {
            fam: sorted(PPO262_REQUIRED_BASELINES[fam])
            for fam in CURRICULUM261_FAMILIES},
        "bank0_shortcut_detection": {
            "replica": "以 C1 policy set 评估整个 mixed bank(R1 "
                       "错误路径复现)",
            "per_cell_divergence": buggy_divergence,
            "bug_would_be_detected": bug_detectable,
        },
        "single_family_evaluator_rejects_mixed_bank": rejected_mixed,
        "reference_gap_validity": {
            f"{fam}/{rung}": {
                "denominator": cell["denominator"],
                "status": cell["status"],
                "valid": cell["reference_gap_valid"]}
            for fam in CURRICULUM261_FAMILIES
            for rung, cell in mixed["cells"][fam].items()},
        "probability_stratification_contract": (
            "scratch/bc 命令对每族 eval bank 全量运行 "
            "probability_metrics_on_bank(无 [:N] 切片);每族类样本"
            "计数在 policy_probability_dynamics.json 验证非零"),
        "identity_matrix": mixed["identity_matrix"],
        "pass": bool(cell_match and identity_ok and bug_detectable
                     and rejected_mixed),
    }
    _w("family_evaluator_validation.json", art)
    _w("reference_identity_matrix.json", {
        "format": "ppo262-repair2-reference-identity-matrix-v1",
        "identity_matrix": mixed["identity_matrix"],
        "source": f"{DIAG262R2_INTEGRITY_NS} sentinel bank(family × D0/D1)",
        "pass": identity_ok,
    })
    print(json.dumps({"pass": art["pass"],
                      "cell_match": cell_match,
                      "identity_ok": identity_ok,
                      "bug_detectable": bug_detectable,
                      "rejected_mixed": rejected_mixed},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


# ============================================================ gradient
def cmd_gradient_verify(args) -> int:
    """单 minibatch 等价性:插桩梯度 vs 手工 PPO surrogate 复算。"""
    import torch
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES
    from rl_curriculum.ppo262_r2_train import (
        actor_state_hash, build_diagnosed_ppo2, r2_diag_train_run,
    )
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

    plan = _load_r2_plan()
    bank = _gen_r2_bank(DIAG262R2_SMOKE_NS, ("c1_opportunity",), ("D0",),
                        2, 0)
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    steps = 2 * len(bank) * 287
    run = r2_diag_train_run(
        bank, config=cfg, model_seed=28501, total_timesteps=steps,
        run_label="diag-r2/gradient-verify")
    model = run["model"]
    cap = model.diag2_first_minibatch
    if cap is None:
        art = {"pass": False, "reason": "无 minibatch 捕获"}
        _w("ppo_surrogate_gradient_validation.json", art)
        return 2
    rec = next(r for r in model.diag2_minibatch_records
               if r["minibatch_index"] == cap["minibatch_index"])

    # 手工复算:同 seed 重建模型(初始权重逐位一致)→ 载入捕获的
    # pre-update 权重 → 按 SB3 语义重建 loss → backward → 对比
    env = CurriculumMultiEpisodeEnv(bank)
    manual = build_diagnosed_ppo2(cfg, 28501, env)
    manual.policy.load_state_dict(cap["policy_state_before"])
    policy = manual.policy
    obs = torch.as_tensor(cap["observations"])
    actions = torch.as_tensor(cap["actions"]).long().flatten()
    old_log_prob = torch.as_tensor(cap["old_log_prob"])
    returns = torch.as_tensor(cap["returns"])
    adv = torch.as_tensor(cap["advantages_raw"]).clone()
    if cap["normalize_advantage"] and len(adv) > 1:
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    values, log_prob, entropy = policy.evaluate_actions(obs, actions)
    values = values.flatten()
    ratio = torch.exp(log_prob - old_log_prob)
    eps = cap["clip_range"]
    pl1 = adv * ratio
    pl2 = adv * torch.clamp(ratio, 1 - eps, 1 + eps)
    policy_loss = -torch.min(pl1, pl2).mean()
    value_loss = torch.nn.functional.mse_loss(returns, values)
    entropy_loss = -torch.mean(entropy)
    loss = (policy_loss + cap["ent_coef"] * entropy_loss
            + cap["vf_coef"] * value_loss)
    policy.set_training_mode(True)
    policy.optimizer.zero_grad()
    loss.backward()

    def _norm(params):
        gs = [p.grad for p in params if p.grad is not None]
        return float(torch.sqrt(sum((g.detach() ** 2).sum()
                                    for g in gs)))

    actor_params = (list(policy.mlp_extractor.policy_net.parameters())
                    + list(policy.action_net.parameters()))
    critic_params = (list(policy.mlp_extractor.value_net.parameters())
                     + list(policy.value_net.parameters()))
    manual_actor_norm = _norm(actor_params)
    manual_critic_norm = _norm(critic_params)
    fp = policy.mlp_extractor.policy_net[0]
    manual_first = [float(x) for x in
                    fp.weight.grad.detach().abs().mean(dim=0)]

    def _close(a, b, *, rtol=1e-4, atol=1e-6):
        return a is not None and b is not None and abs(a - b) <= (
            atol + rtol * abs(b))

    checks = {
        "policy_loss_close": _close(
            float(policy_loss.item()), rec["policy_loss"]),
        "value_loss_close": _close(
            float(value_loss.item()), rec["value_loss"]),
        "entropy_loss_close": _close(
            float(entropy_loss.item()), rec["entropy_loss"]),
        "total_loss_close": _close(
            float(loss.item()), rec["total_loss"]),
        "actor_grad_norm_close": _close(
            manual_actor_norm, rec["actor_total_grad_norm"]),
        "critic_grad_norm_close": _close(
            manual_critic_norm, rec["critic_total_grad_norm"]),
        "first_layer_per_input_close": (
            len(manual_first) == len(
                rec.get("policy_first_layer_per_input_abs_grad", []))
            and all(_close(a, b, rtol=1e-3, atol=1e-9) for a, b in zip(
                manual_first,
                rec["policy_first_layer_per_input_abs_grad"]))),
        "pre_clip_norm_recorded": rec.get(
            "pre_clip_total_grad_norm") is not None,
        "post_clip_norm_recorded": rec.get(
            "post_clip_total_grad_norm") is not None,
        "clipping_semantics_ok": rec.get(
            "post_clip_total_grad_norm", 0.0) <= rec.get(
            "pre_clip_total_grad_norm", 0.0) * (1 + 1e-6) + 1e-9,
        "update_minibatch_identity_present": (
            "update_index" in rec and "minibatch_index" in rec
            and "epoch" in rec),
        "n_minibatch_records_matches_budget": (
            len(model.diag2_minibatch_records)
            == (steps // cfg["n_steps"]) * cfg["n_epochs"] * (
                cfg["n_steps"] // cfg["batch_size"])),
    }
    art = {
        "format": "ppo262-repair2-surrogate-gradient-validation-v1",
        "plan_digest": plan["plan_digest_self"],
        "method": (
            "真实 train() 中捕获首个 minibatch 的张量与 pre-update "
            "权重;同 seed 重建模型后按 SB3 2.9.0 语义(per-minibatch "
            "advantage 归一化 / ratio / clipped surrogate / entropy / "
            "vf 系数)手工重建 loss 并 backward,数值对比插桩记录"),
        "captured_minibatch_identity": {
            "update_index": cap["update_index"],
            "minibatch_index": cap["minibatch_index"],
            "n_samples": int(obs.shape[0])},
        "numbers": {
            "instrumented": {k: rec.get(k) for k in (
                "policy_loss", "value_loss", "entropy_loss",
                "total_loss", "actor_total_grad_norm",
                "critic_total_grad_norm",
                "pre_clip_total_grad_norm",
                "post_clip_total_grad_norm")},
            "manual_reference": {
                "policy_loss": float(policy_loss.item()),
                "value_loss": float(value_loss.item()),
                "entropy_loss": float(entropy_loss.item()),
                "total_loss": float(loss.item()),
                "actor_grad_norm": manual_actor_norm,
                "critic_grad_norm": manual_critic_norm},
        },
        "checks": checks,
        "run_audit": {k: run[k] for k in (
            "cycles", "total_timesteps", "env_audit", "audit_problems",
            "pass")},
        "pass": all(checks.values()) and run["pass"],
    }
    _w("ppo_surrogate_gradient_validation.json", art)
    print(json.dumps({"pass": art["pass"], "checks": checks},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


# ============================================================ supervised
def cmd_supervised(args) -> int:
    """family 分开的监督对照(U/W/B × 3 arms × 3 seeds)。"""
    from rl_curriculum.curriculum261_api import curriculum261_eval_config
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    from rl_curriculum.ppo262_r2_namespaces import (
        DIAG262R2_SUPERVISED_SEEDS,
    )
    from rl_curriculum.ppo262_r2_supervised import (
        CONTROL_KINDS, extended_binary_metrics,
        heldout_pair_performance, mlp_predict_long,
        train_linear_probe, train_supervised_mlp,
    )
    from rl_curriculum.ppo262_r2_train import collect_family_bc_dataset

    plan = _load_r2_plan()
    spec = R2_BANK_SPEC["supervised"]
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg = curriculum261_eval_config()
    thr = plan["branch_thresholds"]

    datasets: dict[str, dict[str, dict[str, Any]]] = {}
    for side in ("train", "eval"):
        s = spec[side]
        bank = _gen_r2_bank(s["namespace"], CURRICULUM261_FAMILIES,
                            s["rungs"], s["pairs_per_fr"],
                            s["pair_base"])
        datasets[side] = {
            fam: collect_family_bc_dataset(
                [e for e in bank if e.key.family == fam], fam,
                rung_params, thresholds, schema, cfg)
            for fam in CURRICULUM261_FAMILIES}

    arm_b = plan["arms"]["B_fixed_precommitted"]["constants"]
    results: dict[str, Any] = {}
    for fam in CURRICULUM261_FAMILIES:
        dtr, dev = datasets["train"][fam], datasets["eval"][fam]
        adapters = {
            "unscaled": ObsAdapter.identity(dtr["X"].shape[1]),
            "fixed_precommitted": ObsAdapter.fixed(
                arm_b["center"], arm_b["scale"],
                source="plan-locked Arm B constants"),
            "train_fitted": ObsAdapter.fit_frozen(
                dtr["X"], source=f"supervised train bank({fam})"),
        }
        fam_res: dict[str, Any] = {
            "n_train": len(dtr["y"]), "n_eval": len(dev["y"]),
            "class_balance_train_long": float(np.mean(dtr["y"] == 1)),
            "class_balance_eval_long": float(np.mean(dev["y"] == 1)),
            "train_eval_pair_isolation": (
                "train/eval 不同 namespace 不同 pair 区间;held-out "
                "pairs 未进入训练"),
            "arms": {},
        }
        for aname, adapter in adapters.items():
            Xt = np.stack([adapter.apply(x) for x in dtr["X"]])
            Xe = np.stack([adapter.apply(x) for x in dev["X"]])
            arm_res: dict[str, Any] = {"adapter": adapter.describe()}
            # linear probe(control U 口径)
            lin = train_linear_probe(Xt, dtr["y"], seed=262)
            arm_res["linear_U"] = {
                "train": extended_binary_metrics(
                    dtr["y"], lin.predict_proba(Xt)[:, 1]),
                "eval": extended_binary_metrics(
                    dev["y"], lin.predict_proba(Xe)[:, 1]),
                "heldout_pair_performance": heldout_pair_performance(
                    dev["y"], lin.predict_proba(Xe)[:, 1],
                    dev["row_pairs"]),
            }
            for control in CONTROL_KINDS:
                c_res: dict[str, Any] = {}
                learned_flags = []
                for seed in DIAG262R2_SUPERVISED_SEEDS:
                    trained = train_supervised_mlp(
                        Xt, dtr["y"], control=control, seed=seed)
                    p_eval = mlp_predict_long(trained, Xe)
                    p_train = mlp_predict_long(trained, Xt)
                    m = extended_binary_metrics(dev["y"], p_eval)
                    learned = bool(
                        m["balanced_accuracy"] is not None
                        and m["balanced_accuracy"] >= thr[
                            "supervised_balanced_accuracy"]
                        and (m["behavior_gap_proxy"] or 0) >= thr[
                            "supervised_behavior_gap_proxy"])
                    learned_flags.append(learned)
                    c_res[f"seed{seed}"] = {
                        "train": extended_binary_metrics(
                            dtr["y"], p_train),
                        "eval": m,
                        "heldout_pair_performance": (
                            heldout_pair_performance(
                                dev["y"], p_eval, dev["row_pairs"])),
                        "learned": learned,
                        "final_loss": trained["history"][-1]["loss"],
                    }
                n_learned = int(sum(learned_flags))
                c_res["learned_rule"] = {
                    "n_learned_seeds": n_learned,
                    "learned_2of3": n_learned >= thr[
                        "supervised_min_seeds"],
                    "rule": plan["interpretation_rules"][
                        "supervised_learned"],
                }
                arm_res[f"mlp_{control}"] = c_res
            # arm 级 learned = 任一 control >= 2/3 seeds(C2 判 E 需要
            # W 与 B 都失败,见 c2_imbalance artifact)
            arm_res["arm_learned"] = bool(any(
                arm_res[f"mlp_{c}"]["learned_rule"]["learned_2of3"]
                for c in CONTROL_KINDS))
            arm_res["class_balanced_learned"] = bool(any(
                arm_res[f"mlp_{c}"]["learned_rule"]["learned_2of3"]
                for c in ("W", "B")))
            fam_res["arms"][aname] = arm_res
        # bc arm 选择规则(A -> B -> C 第一个 learned)
        order = ["unscaled", "fixed_precommitted", "train_fitted"]
        fam_res["bc_arm_selection"] = next(
            (a for a in order
             if fam_res["arms"][a]["arm_learned"]), None)
        results[fam] = fam_res

    _w("supervised_control_plan.json", {
        "format": "ppo262-repair2-supervised-control-plan-v1",
        "spec": spec,
        "controls": list(CONTROL_KINDS),
        "seeds": list(DIAG262R2_SUPERVISED_SEEDS),
        "models": ["LogisticRegression(U)", "MLP [128,128] Tanh "
                   "Adam lr=3e-4 20ep"],
        "label_source": "causal observation reference policy(逐族逐 "
                        "rung 正确 reference;不读 latent/future/meta)",
        "plan_digest": plan["plan_digest_self"],
    })
    _w("supervised_control_results.json", {
        "format": "ppo262-repair2-supervised-control-results-v1",
        "diagnostic_iteration": "s262_diag_r2_1",
        "plan_digest": plan["plan_digest_self"],
        "results": results,
    })
    # C2 类别不平衡专题 extract
    c2 = results["c2_context"]
    _w("c2_class_imbalance_results.json", {
        "format": "ppo262-repair2-c2-imbalance-v1",
        "long_label_rate_train": c2["class_balance_train_long"],
        "long_label_rate_eval": c2["class_balance_eval_long"],
        "controls": {
            arm: {
                c: {
                    "per_seed_eval": {
                        s: {
                            "balanced_accuracy": v["eval"][
                                "balanced_accuracy"],
                            "long_recall": v["eval"]["long_recall"],
                            "long_precision": v["eval"]["long_precision"],
                            "pr_auc": v["eval"]["pr_auc"],
                            "roc_auc": v["eval"]["roc_auc"],
                            "false_positive_rate": v["eval"][
                                "false_positive_rate"],
                            "predicted_long_rate": v["eval"][
                                "predicted_long_rate"],
                            "behavior_gap_proxy": v["eval"][
                                "behavior_gap_proxy"],
                            "learned": v["learned"],
                        } for s, v in c2["arms"][arm][
                            f"mlp_{c}"].items()
                        if s.startswith("seed")},
                    "learned_2of3": c2["arms"][arm][f"mlp_{c}"][
                        "learned_rule"]["learned_2of3"],
                } for c in CONTROL_KINDS
            } for arm in ("unscaled", "fixed_precommitted",
                          "train_fitted")},
        "class_balanced_learned_by_arm": {
            arm: c2["arms"][arm]["class_balanced_learned"]
            for arm in ("unscaled", "fixed_precommitted",
                        "train_fitted")},
        "branch_E_would_require": (
            "linear 与 class-balanced(W/B)MLP 在所有 arms 上都 "
            "无法学(>= 2/3 supervised seeds 口径)"),
        "plan_digest": plan["plan_digest_self"],
    })
    summary = {fam: {
        "bc_arm": results[fam]["bc_arm_selection"],
        **{a: {
            "arm_learned": results[fam]["arms"][a]["arm_learned"],
            "class_balanced_learned": results[fam]["arms"][a][
                "class_balanced_learned"],
            "linear_eval_bal_acc": results[fam]["arms"][a][
                "linear_U"]["eval"]["balanced_accuracy"]}
            for a in ("unscaled", "fixed_precommitted",
                      "train_fitted")}} for fam in results}
    print(json.dumps(summary, ensure_ascii=False))
    return 0


# ============================================================ scratch PPO
def _arm_adapter(plan: dict[str, Any], arm: str, X_fit=None, *,
                 fit_source: str = ""):
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    if arm == "A_unscaled":
        return ObsAdapter.identity(9)
    if arm == "B_fixed_precommitted":
        const = plan["arms"]["B_fixed_precommitted"]["constants"]
        return ObsAdapter.fixed(
            const["center"], const["scale"],
            source="plan-locked Arm B constants(precommitted)")
    if arm == "C_train_fitted":
        if X_fit is None:
            raise ValueError("Arm C 需要 train bank obs 拟合")
        return ObsAdapter.fit_frozen(X_fit, source=fit_source)
    raise ValueError(f"未知 arm {arm!r}")


def _checkpoint_diagnostics(store, run, *, cfg, eval_env_bank,
                            adapter_probe, plan, rung_params=None,
                            thresholds=None, ref_cache=None) -> dict:
    """逐 checkpoint:重载 + probability + family behavior + capture。"""
    from rl_curriculum.ppo262_diag_metrics import (
        probability_metrics_on_bank,
    )
    from rl_curriculum.ppo262_r2_evaluator import (
        evaluate_family_cells, family_behavior_gap,
        family_eval_capture, family_probability_summary,
    )
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.ppo262_r2_train import load_r2_checkpoint

    out: dict[str, Any] = {}
    env = CurriculumMultiEpisodeEnv(eval_env_bank)
    for tag, rec in sorted(store.records.items(),
                           key=lambda kv: kv[1]["episode_index"]):
        model = load_r2_checkpoint(
            rec["path"], config=cfg, model_seed=run["model_seed"],
            env=env, expect_policy_sha256=rec["policy_state_sha256"])
        prob = probability_metrics_on_bank(
            model, eval_env_bank, adapter=adapter_probe)
        fam = eval_env_bank[0].key.family
        summary = family_probability_summary(prob, fam)
        cap_eval = evaluate_family_cells(
            model, eval_env_bank, rung_params, thresholds,
            adapter=adapter_probe, reference_cache=ref_cache)
        out[tag] = {
            "episode_index": rec["episode_index"],
            "policy_state_sha256": rec["policy_state_sha256"],
            "reload_verified": True,
            "probability": prob,
            "family_probability_summary": summary,
            "family_eval_capture": family_eval_capture(
                fam, cap_eval["cells"]),
            "family_behavior_gap": family_behavior_gap(
                cap_eval["behavior"], fam),
            "family_capture_cells": cap_eval["cells"],
        }
    return out


def _compact_ckpt_diag(ckpt_diag: dict[str, Any], fam: str) -> dict:
    """§9.3 要求的 checkpoint 诊断紧凑结构(进 artifact)。"""
    out = {}
    for tag, d in ckpt_diag.items():
        prob = d["probability"]
        per = prob.get("per_family", {}).get(fam, {})
        out[tag] = {
            "episode_index": d["episode_index"],
            "policy_state_sha256": d["policy_state_sha256"],
            "reload_verified": d["reload_verified"],
            "overall": prob.get("overall"),
            "per_latent_class": {
                name: {k: v for k, v in stats.items()
                       if k in ("n", "mean_p_long", "mean_logit_diff",
                                "mean_entropy",
                                "mean_value_prediction",
                                "deterministic_long_rate",
                                "stochastic_long_rate")}
                for name, stats in per.items()},
            "family_probability_summary": d[
                "family_probability_summary"],
            "family_eval_capture": d["family_eval_capture"],
        }
    return out


def cmd_scratch(args) -> int:
    """family 分开 scratch PPO(A/B/C × 3 seeds;真实 checkpoints)。"""
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES
    from rl_curriculum.ppo262_diag_metrics import (
        _reference_free_obs_sequence, probability_metrics_on_bank,
    )
    from rl_curriculum.ppo262_r2_evaluator import (
        family_behavior_gap, family_eval_capture,
        family_probability_summary,
    )
    from rl_curriculum.ppo262_r2_namespaces import (
        DIAG262R2_SCRATCH_SEEDS, scratch_eval_namespace,
        scratch_train_namespace,
    )
    from rl_curriculum.ppo262_r2_train import (
        R2CheckpointStore, policy_state_hash, r2_diag_train_run,
    )

    plan = _load_r2_plan()
    spec = R2_BANK_SPEC["scratch"]
    thr = plan["branch_thresholds"]
    cfg = PPO262_CANDIDATES["cand_a_center"]
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    ckpt_tags = plan["checkpoint_schedule"]["scratch_tags_per_run"]

    results: dict[str, Any] = {}
    pairing: dict[str, Any] = {"init_hash": {}, "train_manifest": {},
                               "eval_manifest": {}}
    ref_validity: dict[str, Any] = {}
    cost: dict[str, Any] = {}
    prob_dyn: dict[str, Any] = {}
    upd_diag: dict[str, Any] = {}
    val_adv: dict[str, Any] = {}
    ckpt_integrity: dict[str, Any] = {}
    t_start = time.time()

    for fam in CURRICULUM261_FAMILIES:
        eval_bank = _gen_r2_bank(
            scratch_eval_namespace(fam), [fam], spec["eval_per_family"][
                "rungs"], spec["eval_per_family"]["pairs_per_fr"],
            spec["eval_per_family"]["pair_base"])
        pairing["eval_manifest"][fam] = _bank_manifest_hash(eval_bank)
        # reference/baseline rows 每族 eval bank 只算一次(共享 cache)
        ref_cache: dict = {}

        def _cells(model_or_policy, adapter):
            from rl_curriculum.ppo262_r2_evaluator import (
                evaluate_family_cells,
            )
            return evaluate_family_cells(
                model_or_policy, eval_bank, rung_params, thresholds,
                adapter=adapter, reference_cache=ref_cache)

        # 用 reference-only 评估填充 cache 并记录 validity
        from rl_curriculum.policies import AlwaysFlatPolicy
        _cells(AlwaysFlatPolicy(), None)
        ref_validity[fam] = {
            rung: {
                "denominator": _denominator_of(ref_cache, fam, rung),
                "reference_mean": _refmean_of(ref_cache, fam, rung),
                "status": "valid" if _denominator_of(
                    ref_cache, fam, rung) > 0 else
                "invalid_reference_gap",
            } for rung in spec["eval_per_family"]["rungs"]}

        fam_res: dict[str, Any] = {}
        for slot, seed in enumerate(DIAG262R2_SCRATCH_SEEDS):
            base = slot * 32
            train_bank = _gen_r2_bank(
                scratch_train_namespace(fam),
                [fam], spec["train_per_family_slot"]["rungs"],
                spec["train_per_family_slot"]["pairs_per_rung"], base)
            pairing["train_manifest"][f"{fam}/seed{seed}"] = (
                _bank_manifest_hash(train_bank))
            X_fit = np.stack([o for e in train_bank
                              for o in _reference_free_obs_sequence(e)])
            adapters = {
                "A_unscaled": _arm_adapter(plan, "A_unscaled"),
                "B_fixed_precommitted": _arm_adapter(
                    plan, "B_fixed_precommitted"),
                "C_train_fitted": _arm_adapter(
                    plan, "C_train_fitted", X_fit,
                    fit_source=f"{scratch_train_namespace(fam)} "
                               f"seed 槽位 {slot} train bank(仅训练 "
                               f"bank;eval 不参与 fit)"),
            }
            for arm_name, adapter in adapters.items():
                run_id = f"scratch_{fam.split('_')[0]}_{arm_name[0]}_" \
                         f"seed{seed}"
                store = R2CheckpointStore(
                    MODELS_REPAIR2_DIR, run_id, family=fam, arm=arm_name,
                    seed=seed, expected_tags=tuple(ckpt_tags))
                run = r2_diag_train_run(
                    train_bank, config=cfg, model_seed=seed,
                    total_timesteps=spec["steps_per_seed"],
                    run_label=f"diag-r2/scratch/{fam}/{arm_name}/"
                              f"seed{seed}",
                    adapter=None if adapter.identity_equivalent()
                    else adapter,
                    checkpoint_store=store,
                    checkpoint_episodes=tuple(
                        spec["checkpoint_episodes"]),
                    gradient_detail_every=8)
                pairing["init_hash"].setdefault(
                    f"{fam}/seed{seed}", {})[arm_name] = run[
                    "initial_policy_state_sha256"]
                adapter_probe = None if adapter.identity_equivalent() \
                    else adapter
                final_cells = _cells(run["model"], adapter_probe)
                fam_cap = family_eval_capture(fam, final_cells["cells"])
                prob = probability_metrics_on_bank(
                    run["model"], eval_bank, adapter=adapter_probe)
                prob_sum = family_probability_summary(
                    prob, fam)
                beh = family_behavior_gap(final_cells["behavior"], fam)
                ckpt_diag = _checkpoint_diagnostics(
                    store, run, cfg=cfg, eval_env_bank=eval_bank,
                    adapter_probe=adapter_probe, plan=plan,
                    rung_params=rung_params, thresholds=thresholds,
                    ref_cache=ref_cache)
                key = f"seed{seed}"
                fam_res.setdefault(arm_name, {})[key] = {
                    "family": fam,
                    "run_audit": {k: run[k] for k in (
                        "cycles", "bank_episodes", "total_timesteps",
                        "elapsed_seconds", "fps", "env_audit",
                        "audit_problems", "pass")},
                    "adapter": run["adapter"],
                    "initial_policy_state_sha256": run[
                        "initial_policy_state_sha256"],
                    "final_capture_cells": final_cells["cells"],
                    "family_eval_capture": fam_cap,
                    "probability_final": prob_sum,
                    "behavior_final": beh,
                    "recovery_check": _recovery_check(
                        fam_cap, prob_sum, beh, thr, family=fam),
                    "update_records": run["update_records"],
                    "minibatch_grad_summary": _minibatch_grad_summary(
                        run["minibatch_records"]),
                    "rollout_records_final": run["rollout_records"][-1],
                    "cost_decomposition": {
                        "total_fees": float(np.sum([
                            r["cost_fees_paid"]
                            for r in run["episode_curve"]])),
                        "total_liquidation_fees": float(np.sum([
                            r["terminal_liquidation_fee"]
                            for r in run["episode_curve"]])),
                        "ledger_trades": int(np.sum([
                            r["ledger_trades"]
                            for r in run["episode_curve"]])),
                        "position_changes": int(np.sum([
                            r["position_changes"]
                            for r in run["episode_curve"]])),
                    },
                    "checkpoint_verification": run[
                        "checkpoint_verification"],
                }
                ckpt_integrity[run_id] = run["checkpoint_verification"]
                prob_dyn[run_id] = _compact_ckpt_diag(ckpt_diag, fam)
                upd_diag[run_id] = {
                    "n_updates": len(run["update_records"]),
                    "n_minibatches": len(run["minibatch_records"]),
                    "final_update": run["update_records"][-1]
                    if run["update_records"] else None,
                    "minibatch_grad_summary": fam_res[arm_name][key][
                        "minibatch_grad_summary"],
                }
                val_adv[run_id] = {
                    "n_rollouts": len(run["rollout_records"]),
                    "final_rollout": run["rollout_records"][-1]
                    if run["rollout_records"] else None,
                }
                cost[run_id] = fam_res[arm_name][key][
                    "cost_decomposition"]
        results[fam] = fam_res

    # arm 级 recovery(>= 2/3 seeds)
    for fam in CURRICULUM261_FAMILIES:
        for arm in results[fam]:
            flags = [v["recovery_check"]["recovered"]
                     for v in results[fam][arm].values()]
            results[fam][arm]["arm_recovery"] = {
                "flags_per_seed": flags,
                "n_positive": int(sum(flags)),
                "recovered_2of3": int(sum(flags)) >= thr[
                    "recovery_min_seeds"],
            }

    pair_ok = {}
    for k, per in pairing["init_hash"].items():
        pair_ok[k] = len(set(per.values())) == 1

    _w("scratch_ppo_plan.json", {
        "format": "ppo262-repair2-scratch-ppo-plan-v1",
        "spec": spec,
        "arms": ["A_unscaled", "B_fixed_precommitted",
                 "C_train_fitted"],
        "seeds": list(DIAG262R2_SCRATCH_SEEDS),
        "checkpoint_tags": ckpt_tags,
        "pairing_contract": "同 family/seed 三 arms 共享同一 train_bank "
                            "对象/同 seed 初始权重/同 config/同 steps/"
                            "同 eval bank/同 checkpoint schedule;"
                            "唯一差异 = observation preprocessing",
        "plan_digest": plan["plan_digest_self"],
    })
    _w("scratch_ppo_results.json", {
        "format": "ppo262-repair2-scratch-ppo-results-v1",
        "diagnostic_iteration": "s262_diag_r2_1",
        "plan_digest": plan["plan_digest_self"],
        "budget": spec,
        "results": results,
        "elapsed_total_s": round(time.time() - t_start, 1),
    })
    _w("reference_gap_validity.json", {
        "format": "ppo262-repair2-reference-gap-validity-v1",
        "per_family_eval_bank": ref_validity,
        "rule": "R <= B 的 cell 标记 invalid_reference_gap,capture="
                "None,从 branch 判定排除;不得当普通数值解释",
        "plan_digest": plan["plan_digest_self"],
    })
    _w("preprocessing_pairing_integrity.json", {
        "format": "ppo262-repair2-pairing-integrity-v1",
        "initial_policy_state_sha256": pairing["init_hash"],
        "all_arms_identical_per_family_seed": pair_ok,
        "train_bank_manifest_sha256": pairing["train_manifest"],
        "eval_bank_manifest_sha256": pairing["eval_manifest"],
        "arm_b_constants_source": "plan(不读取任何 r2 bank)",
        "arm_c_fit_source": "仅该 family/seed 的 train bank",
        "pass": all(pair_ok.values()),
    })
    _w("checkpoint_integrity.json", {
        "format": "ppo262-repair2-checkpoint-integrity-v1",
        "runs": ckpt_integrity,
        "expected_tags_per_scratch_run": ckpt_tags,
        "pass": all(v["pass"] for v in ckpt_integrity.values()),
    })
    _w("policy_probability_dynamics.json", {
        "format": "ppo262-repair2-probability-dynamics-v1",
        "runs": prob_dyn,
        "non_empty_contract": "每个 run 的每个 checkpoint 都有非空 "
                              "probability 摘要(缺失即 FAIL)",
        "pass": all(
            v and all(d["family_probability_summary"] for d in v.values())
            for v in prob_dyn.values()),
    })
    _w("ppo_update_diagnostics.json", {
        "format": "ppo262-repair2-update-diagnostics-v1",
        "runs": upd_diag,
        "gradient_source": "真实 PPO surrogate(DiagnosedPPO2.train "
                           "插桩;详见 ppo_surrogate_gradient_"
                           "validation.json)",
    })
    _w("value_advantage_diagnostics.json", {
        "format": "ppo262-repair2-value-advantage-v1",
        "runs": val_adv,
    })
    _w("cost_decomposition.json", {
        "format": "ppo262-repair2-cost-decomposition-v1",
        "runs": cost,
    })
    summary = {fam: {
        arm: {
            "recovered_2of3": results[fam][arm]["arm_recovery"][
                "recovered_2of3"],
            "captures": {s: v["family_eval_capture"]["capture"]
                         for s, v in results[fam][arm].items()
                         if s.startswith("seed")},
        } for arm in results[fam]} for fam in results}
    print(json.dumps({"summary": summary,
                      "pairing_ok": all(pair_ok.values()),
                      "checkpoints_ok": all(
                          v["pass"] for v in ckpt_integrity.values()),
                      "elapsed_total_s": round(time.time() - t_start, 1)},
                     ensure_ascii=False))
    return 0


def _denominator_of(ref_cache, fam, rung):
    _, ref_rows, baseline_rows, _ = ref_cache[(fam, rung)]
    import numpy as np
    ref_mean = float(np.mean([r["net_return"] for r in ref_rows]))
    base_means = {
        name: float(np.mean([r["net_return"] for r in rows]))
        for name, rows in baseline_rows.items()}
    return ref_mean - max(base_means.values())


def _refmean_of(ref_cache, fam, rung):
    _, ref_rows, _, _ = ref_cache[(fam, rung)]
    import numpy as np
    return float(np.mean([r["net_return"] for r in ref_rows]))


def _recovery_check(fam_cap, prob_sum, beh, thr,
                    family: str | None = None) -> dict[str, Any]:
    """单 seed 的 family recovery(全部证据同族;跨族拼接被拒)。"""
    from rl_curriculum.ppo262_r2_evaluator import family_recovery_evidence
    if family is not None:
        family_recovery_evidence(family, fam_cap, prob_sum, beh)
    capture_ok = bool(
        fam_cap["valid"] and fam_cap["capture"] is not None
        and fam_cap["capture"] > thr["recovery_eval_capture"])
    prob_ok = bool(
        prob_sum.get("sampling_sufficient")
        and prob_sum.get("probability_gap") is not None
        and prob_sum["probability_gap"] > thr[
            "recovery_probability_gap"])
    det_ok = bool(
        beh.get("det_behavior_gap") is not None
        and beh["det_behavior_gap"] > thr["recovery_det_behavior_gap"])
    return {
        "capture_ok": capture_ok,
        "probability_ok": prob_ok,
        "det_behavior_gap_ok": det_ok,
        "recovered": bool(capture_ok and prob_ok and det_ok),
        "evidence_family_consistent": True,
    }


def _minibatch_grad_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"n": 0}
    actor = [r["actor_total_grad_norm"] for r in records
             if r.get("actor_total_grad_norm") is not None]
    critic = [r["critic_total_grad_norm"] for r in records
              if r.get("critic_total_grad_norm") is not None]
    pre = [r["pre_clip_total_grad_norm"] for r in records
           if r.get("pre_clip_total_grad_norm") is not None]
    post = [r["post_clip_total_grad_norm"] for r in records
            if r.get("post_clip_total_grad_norm") is not None]
    per_col = [r["policy_first_layer_per_input_abs_grad"] for r in records
               if r.get("policy_first_layer_per_input_abs_grad")]
    return {
        "n": len(records),
        "first_minibatch_index": records[0]["minibatch_index"],
        "last_minibatch_index": records[-1]["minibatch_index"],
        "update_index_range": [records[0]["update_index"],
                               records[-1]["update_index"]],
        "identity_fields_complete": all(
            {"update_index", "minibatch_index", "epoch",
             "minibatch_of_update"} <= set(r) for r in records),
        "actor_grad_norm": {
            "mean": float(np.mean(actor)) if actor else None,
            "max": float(np.max(actor)) if actor else None,
            "min": float(np.min(actor)) if actor else None},
        "critic_grad_norm": {
            "mean": float(np.mean(critic)) if critic else None,
            "max": float(np.max(critic)) if critic else None},
        "pre_clip_total_norm_max": float(np.max(pre)) if pre else None,
        "post_clip_total_norm_max": float(np.max(post)) if post else None,
        "per_column_detail_samples": len(per_col),
        "last_per_column_detail": per_col[-1] if per_col else None,
    }


# ============================================================ BC
def cmd_bc(args) -> int:
    """family 分开 BC(全部 3 seeds;after_bc checkpoint;retention)。"""
    from rl_curriculum.curriculum261_api import curriculum261_eval_config
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.ppo262_config import PPO262_CANDIDATES
    from rl_curriculum.ppo262_diag_metrics import (
        probability_metrics_on_bank,
    )
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    from rl_curriculum.ppo262_r2_evaluator import (
        family_behavior_gap, family_eval_capture,
        family_probability_summary,
    )
    from rl_curriculum.ppo262_r2_namespaces import (
        DIAG262R2_BC_SEEDS, bc_eval_namespace, bc_train_namespace,
    )
    from rl_curriculum.ppo262_r2_supervised import (
        extended_binary_metrics, heldout_pair_performance,
    )
    from rl_curriculum.ppo262_r2_train import (
        R2CheckpointStore, actor_state_hash, bc_train_actor_weighted,
        build_diagnosed_ppo2, collect_family_bc_dataset,
        critic_state_hash, r2_diag_train_run,
    )
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv

    plan = _load_r2_plan()
    spec = R2_BANK_SPEC["bc"]
    thr = plan["branch_thresholds"]
    ppo_cfg = PPO262_CANDIDATES["cand_a_center"]
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg261 = curriculum261_eval_config()
    ckpt_tags = spec["checkpoint_tags"]

    # bc arm 选择(预注册规则:读 supervised results)
    sup_path = REPAIR2_DIR / "supervised_control_results.json"
    if not sup_path.is_file():
        print("supervised 结果缺失(先运行 r2-supervised)",
              file=sys.stderr)
        return 2
    sup = json.loads(sup_path.read_text(encoding="utf-8"))
    bc_arms = {fam: sup["results"][fam]["bc_arm_selection"]
               for fam in CURRICULUM261_FAMILIES}
    arm_b = plan["arms"]["B_fixed_precommitted"]["constants"]

    results: dict[str, Any] = {}
    integrity: dict[str, Any] = {}
    for fam in CURRICULUM261_FAMILIES:
        bc_arm = bc_arms[fam]
        if bc_arm is None:
            results[fam] = {
                "executed": False,
                "reason": "该 family 在全部 arms 的 supervised 对照均未"
                          "学会(branch 规则指向 E/F);按任务书不执行 "
                          "BC、不制造空 BC artifact",
                "bc_arm": None,
            }
            continue
        fam_res: dict[str, Any] = {"executed": True, "bc_arm": bc_arm,
                                   "per_seed": {}}
        for slot, seed in enumerate(DIAG262R2_BC_SEEDS):
            base = slot * 32
            train_bank = _gen_r2_bank(
                bc_train_namespace(fam), [fam],
                spec["train_per_family_slot"]["rungs"],
                spec["train_per_family_slot"]["pairs_per_rung"], base)
            eval_bank = _gen_r2_bank(
                bc_eval_namespace(fam), [fam],
                spec["eval_per_family_slot"]["rungs"],
                spec["eval_per_family_slot"]["pairs_per_fr"],
                256 + slot * 32)
            dtr = collect_family_bc_dataset(
                train_bank, fam, rung_params, thresholds, schema, cfg261)
            dev = collect_family_bc_dataset(
                eval_bank, fam, rung_params, thresholds, schema, cfg261)
            if bc_arm == "unscaled":
                adapter = ObsAdapter.identity(dtr["X"].shape[1])
            elif bc_arm == "fixed_precommitted":
                adapter = ObsAdapter.fixed(
                    arm_b["center"], arm_b["scale"],
                    source="plan-locked Arm B constants")
            else:
                adapter = ObsAdapter.fit_frozen(
                    dtr["X"], source=f"{bc_train_namespace(fam)} seed "
                                     f"槽位 {slot} train bank")
            adapter_probe = None if adapter.identity_equivalent() \
                else adapter

            def _match(model):
                import torch
                xt = torch.as_tensor(np.stack(
                    [adapter.apply(o) for o in dev["X"]]),
                    dtype=torch.float32)
                with torch.no_grad():
                    logits = model.policy.get_distribution(
                        xt).distribution.logits
                p = torch.softmax(logits, dim=-1)[:, 1].numpy()
                return {
                    "metrics": extended_binary_metrics(dev["y"], p),
                    "heldout_pair_performance": (
                        heldout_pair_performance(dev["y"], p,
                                                  dev["row_pairs"])),
                }

            env = CurriculumMultiEpisodeEnv(train_bank)
            model = build_diagnosed_ppo2(ppo_cfg, seed, env)
            actor_before = actor_state_hash(model)
            critic_before = critic_state_hash(model)
            bc_info = bc_train_actor_weighted(
                model, dtr, epochs=spec["bc_epochs"], lr=spec["bc_lr"],
                adapter=adapter, rng_seed=seed,
                class_weighted=spec["class_weighted"])
            actor_after = actor_state_hash(model)
            critic_after = critic_state_hash(model)
            match_bc = _match(model)
            bc_state = {k: v.clone() for k, v in
                        model.policy.state_dict().items()}
            run_id = f"bc_{fam.split('_')[0]}_seed{seed}"
            store = R2CheckpointStore(
                MODELS_REPAIR2_DIR, run_id, family=fam,
                arm=f"bc:{bc_arm}", seed=seed,
                expected_tags=tuple(ckpt_tags))
            run = r2_diag_train_run(
                train_bank, config=ppo_cfg, model_seed=seed,
                total_timesteps=spec["steps_finetune"],
                run_label=f"diag-r2/bc/{fam}/seed{seed}",
                adapter=adapter_probe, checkpoint_store=store,
                checkpoint_episodes=tuple(
                    spec["checkpoint_episodes"]),
                gradient_detail_every=8, bc_init_state=bc_state)
            match_ft = _match(run["model"])
            bc_bal = match_bc["metrics"]["balanced_accuracy"]
            ft_bal = match_ft["metrics"]["balanced_accuracy"]
            from rl_curriculum.ppo262_r2_train import bc_retention
            ret = bc_retention(bc_bal, ft_bal, thr)
            bc_learned = ret["bc_learned"]
            retained = ret["retained"]
            destroyed = ret["destroyed"]
            drop = ret["drop"]
            # bank 级诊断(概率 + capture;reference cache 每族共享)
            ref_cache: dict = {}

            def _bc_cells(model):
                from rl_curriculum.ppo262_r2_evaluator import (
                    evaluate_family_cells,
                )
                return evaluate_family_cells(
                    model, eval_bank, rung_params, thresholds,
                    adapter=adapter_probe, reference_cache=ref_cache)

            _bc_cells(model)  # 填充 reference cache(BC 后模型)
            prob_bc = family_probability_summary(
                probability_metrics_on_bank(
                    model, eval_bank, adapter=adapter_probe), fam)
            prob_ft = family_probability_summary(
                probability_metrics_on_bank(
                    run["model"], eval_bank, adapter=adapter_probe), fam)
            ft_cells = _bc_cells(run["model"])
            cap_ft = family_eval_capture(fam, ft_cells["cells"])
            beh_ft = family_behavior_gap(ft_cells["behavior"], fam)
            ckpt_diag = _checkpoint_diagnostics(
                store, run, cfg=ppo_cfg, eval_env_bank=eval_bank,
                adapter_probe=adapter_probe, plan=plan,
                rung_params=rung_params, thresholds=thresholds,
                ref_cache=ref_cache)
            fam_res["per_seed"][f"seed{seed}"] = {
                "bc_arm": bc_arm,
                "actor_state_sha256_before_bc": actor_before,
                "actor_state_sha256_after_bc": actor_after,
                "critic_state_sha256_before_bc": critic_before,
                "critic_state_sha256_after_bc": critic_after,
                "critic_untouched_by_bc": critic_before == critic_after,
                "actor_changed_by_bc": actor_before != actor_after,
                "bc_training": bc_info,
                "behavior_match_after_bc": match_bc,
                "behavior_match_after_ppo_finetune": match_ft,
                "bc_learned": bc_learned,
                "heldout_balanced_accuracy_drop": drop,
                "retention_rule": {
                    "retained": retained, "destroyed": destroyed,
                    "rule": plan["interpretation_rules"]["bc_retained"],
                },
                "probability_after_bc": prob_bc,
                "probability_after_finetune": prob_ft,
                "capture_after_finetune": cap_ft,
                "behavior_after_finetune": beh_ft,
                "finetune_run_audit": {k: run[k] for k in (
                    "cycles", "total_timesteps", "env_audit",
                    "audit_problems", "pass")},
                "bc_init_actor_state_sha256": run[
                    "bc_init_actor_state_sha256"],
                "actor_import_verified": run[
                    "bc_init_actor_state_sha256"] == actor_after,
                "checkpoint_verification": run["checkpoint_verification"],
                "checkpoint_probability_dynamics": _compact_ckpt_diag(
                    ckpt_diag, fam),
                "update_records_summary": {
                    "n_updates": len(run["update_records"]),
                    "final_approx_kl": (
                        run["update_records"][-1].get("mean_approx_kl")
                        if run["update_records"] else None),
                    "final_entropy_loss": (
                        run["update_records"][-1].get(
                            "mean_entropy_loss")
                        if run["update_records"] else None),
                },
            }
            integrity[run_id] = {
                **run["checkpoint_verification"],
                "critic_untouched_by_bc": critic_before == critic_after,
                "actor_import_verified": run[
                    "bc_init_actor_state_sha256"] == actor_after,
                "train_eval_pair_isolation": (
                    f"train {bc_train_namespace(fam)} pair[{base},"
                    f"{base + 4}) vs eval {bc_eval_namespace(fam)} "
                    f"pair[{256 + slot * 32},"
                    f"{256 + slot * 32 + 4})(namespace+pair 双隔离)"),
            }
        seeds = fam_res["per_seed"]
        n_retained = sum(1 for v in seeds.values()
                         if v["retention_rule"]["retained"])
        n_destroyed = sum(1 for v in seeds.values()
                          if v["retention_rule"]["destroyed"])
        n_learned = sum(1 for v in seeds.values() if v["bc_learned"])
        fam_res["aggregation"] = {
            "n_seeds_executed": len(seeds),
            "n_bc_learned": n_learned,
            "n_retained": n_retained,
            "n_destroyed": n_destroyed,
            "bc_retained_2of3": n_retained >= thr["bc_min_seeds"],
            "bc_destroyed_2of3": n_destroyed >= thr["bc_min_seeds"],
            "seeds_planned": list(DIAG262R2_BC_SEEDS),
            "seeds_exactly_planned": sorted(
                int(v.replace("seed", ""))
                for v in seeds) == sorted(DIAG262R2_BC_SEEDS),
        }
        results[fam] = fam_res

    for fam in CURRICULUM261_FAMILIES:
        short = fam.split("_")[0]
        _w(f"bc_results_{short}.json", {
            "format": f"ppo262-repair2-bc-results-{short}-v1",
            "diagnostic_iteration": "s262_diag_r2_1",
            "plan_digest": plan["plan_digest_self"],
            **results[fam],
        })
    _w("bc_plan.json", {
        "format": "ppo262-repair2-bc-plan-v1",
        "spec": spec,
        "seeds": list(DIAG262R2_BC_SEEDS),
        "checkpoint_tags": ckpt_tags,
        "arm_selection_rule": plan["interpretation_rules"]["bc_arm_" \
                                                             "selection"],
        "selected_arms": bc_arms,
        "label_source": "causal observation reference policy(逐族逐 "
                        "rung;不读 latent oracle/future/episode id/"
                        "hidden metadata)",
        "plan_digest": plan["plan_digest_self"],
    })
    _w("bc_execution_integrity.json", {
        "format": "ppo262-repair2-bc-execution-integrity-v1",
        "runs": integrity,
        "pass": all(
            v["pass"] and v["critic_untouched_by_bc"]
            and v["actor_import_verified"] for v in integrity.values())
        if integrity else False,
    })
    print(json.dumps({
        fam: {
            "executed": results[fam]["executed"],
            **({"n_retained": results[fam]["aggregation"][
                "n_retained"],
                "n_destroyed": results[fam]["aggregation"][
                    "n_destroyed"],
                "seeds_exactly_planned": results[fam][
                    "aggregation"]["seeds_exactly_planned"]}
               if results[fam]["executed"] else {})}
        for fam in results}, ensure_ascii=False))
    return 0


# ============================================================ decision
def cmd_family_decision(args) -> int:
    """按 family 判定 branch(A-E;F = FAIL)并给出 global 路线。"""
    plan = _load_r2_plan()

    def _load(name):
        p = REPAIR2_DIR / name
        return json.loads(p.read_text(encoding="utf-8")) if (
            p.is_file()) else None

    scratch = _load("scratch_ppo_results.json")
    sup = _load("supervised_control_results.json")
    bc = {fam: _load(f"bc_results_{fam.split('_')[0]}.json")
          for fam in CURRICULUM261_FAMILIES}
    missing = [n for n, d in (("scratch_ppo_results.json", scratch),
                              ("supervised_control_results.json", sup))
               if d is None]
    missing += [f"bc_results_{fam.split('_')[0]}.json"
                for fam in CURRICULUM261_FAMILIES if bc[fam] is None]
    if missing:
        print(f"缺少诊断产物: {missing}", file=sys.stderr)
        return 2

    decisions: dict[str, Any] = {}
    for fam in CURRICULUM261_FAMILIES:
        arm_rec = {arm: scratch["results"][fam][arm]["arm_recovery"][
            "recovered_2of3"] for arm in scratch["results"][fam]}
        a_rec = scratch["results"][fam].get(
            "A_unscaled", {}).get("arm_recovery", {}).get(
            "recovered_2of3", False)
        scaled_rec = any(rec for name, rec in arm_rec.items()
                         if name != "A_unscaled")
        # supervised:该族在任一 arm 上学会(arm_learned);
        # class-balanced 口径单独记录(C2 判 E 用)
        sup_fam = sup["results"][fam]
        any_arm_learned = any(
            sup_fam["arms"][a]["arm_learned"]
            for a in sup_fam["arms"])
        class_balanced_all_fail = not any(
            sup_fam["arms"][a]["class_balanced_learned"]
            for a in sup_fam["arms"])
        linear_all_fail = all(
            (sup_fam["arms"][a]["linear_U"]["eval"][
                 "balanced_accuracy"] is None
             or sup_fam["arms"][a]["linear_U"]["eval"][
                 "balanced_accuracy"] < plan["branch_thresholds"][
                 "supervised_balanced_accuracy"])
            for a in sup_fam["arms"])
        bc_fam = bc[fam]
        bc_executed = bool(bc_fam.get("executed"))
        agg = bc_fam.get("aggregation", {}) if bc_executed else {}

        from rl_curriculum.ppo262_r2_evaluator import decide_family_branch
        branch = decide_family_branch(
            unscaled_recovered=a_rec,
            scaled_recovered=scaled_rec,
            linear_all_fail=linear_all_fail,
            class_balanced_all_fail=class_balanced_all_fail,
            bc_executed=bc_executed,
            bc_retained_2of3=bool(agg.get("bc_retained_2of3")),
            bc_destroyed_2of3=bool(agg.get("bc_destroyed_2of3")))

        decisions[fam] = {
            "arm_recovery": arm_rec,
            "unscaled_recovered": a_rec,
            "scaled_recovered": scaled_rec,
            "supervised_any_arm_learned": any_arm_learned,
            "supervised_linear_all_fail": linear_all_fail,
            "supervised_class_balanced_all_fail": class_balanced_all_fail,
            "bc_executed": bc_executed,
            "bc_aggregation": agg if bc_executed else None,
            "branch": branch,
            "branch_meaning": plan["interpretation_rules"][
                "family_branches"][branch],
            "evidence_family": fam,
        }

    any_f = any(d["branch"] == "F" for d in decisions.values())
    if any_f:
        route = "Repair R2 Diagnostics = FAIL(存在 F:证据不充分/" \
                "分裂;继续诊断,不得进入 official experiment)"
    elif all(d["branch"] == "A" for d in decisions.values()):
        route = "Stage 2.6.2 s262_r1 official rerun(全新 official " \
                "seeds;完整 probes/core/final)"
    elif any(d["branch"] == "B" for d in decisions.values()):
        route = "Stage 2.6.1 Repair R3(重新冻结 preprocessing 并重新 " \
                "qualification;不得直接 official 2.6.2)"
    elif any(d["branch"] == "D" for d in decisions.values()):
        route = "PPO Optimization Repair(该 family 的 PPO update/" \
                "critic/advantage 问题;advantage normalization/critic " \
                "stabilization/smaller updates/KL control/LR 分离/" \
                "cost transition dynamics)"
    elif any(d["branch"] == "C" for d in decisions.values()):
        route = "Warm-start Governance(BC bootstrap/reference-guided " \
                "initialization 治理;不自动纳入 official 路线)"
    elif any(d["branch"] == "E" for d in decisions.values()):
        route = "Stage 2.6.1 Repair R3(重审 observation/reference/" \
                "generator)"
    else:
        route = "unexpected"

    _w("family_branch_decision.json", {
        "format": "ppo262-repair2-family-branch-decision-v1",
        "diagnostic_iteration": "s262_diag_r2_1",
        "plan_digest": plan["plan_digest_self"],
        "decisions": decisions,
        "cross_family_evidence_forbidden": (
            "单族 recovery/branch 的全部证据(capture/probability/"
            "behavior gap/reference gap)来自同一 family;C1 capture "
            "不得与 C3 probability gap 组合(构造性保证 + semantic "
            "validator 复核)"),
        "pass": not any_f,
    })
    _w("global_route_decision.json", {
        "format": "ppo262-repair2-global-route-v1",
        "family_branches": {fam: d["branch"]
                            for fam, d in decisions.items()},
        "recommended_route": route,
        "stage_status_unchanged": "Stage 2.6.2 = FAIL(Repair R2 为诊断"
                                  "轮,不改变 official 状态)",
        "official_final_namespace_unconsumed": True,
        "any_family_F": any_f,
    })
    print(json.dumps({"branches": {fam: d["branch"]
                                   for fam, d in decisions.items()},
                      "route": route}, ensure_ascii=False))
    return 0


# ============================================================ validation
def cmd_semantic_validation(args) -> int:
    """语义 validator(不是文件存在性检查)。"""
    plan = _load_r2_plan()

    def _load(name):
        p = REPAIR2_DIR / name
        return json.loads(p.read_text(encoding="utf-8")) if (
            p.is_file()) else None

    ns = _load("diagnostic_namespace_integrity.json")
    base = _load("baseline_integrity.json")
    hist = _load("historical_diagnostic_binding.json")
    ev = _load("family_evaluator_validation.json")
    gv = _load("ppo_surrogate_gradient_validation.json")
    sup = _load("supervised_control_results.json")
    c2 = _load("c2_class_imbalance_results.json")
    sc = _load("scratch_ppo_results.json")
    ck = _load("checkpoint_integrity.json")
    pd = _load("policy_probability_dynamics.json")
    pair = _load("preprocessing_pairing_integrity.json")
    fsc = _load("fixed_scaling_contract.json")
    bc_int = _load("bc_execution_integrity.json")
    branch = _load("family_branch_decision.json")
    rgv = _load("reference_gap_validity.json")

    checks: dict[str, Any] = {}
    problems: list[str] = []

    def _req(cond, name, detail=""):
        checks[name] = bool(cond)
        if not cond:
            problems.append(f"{name}{(': ' + detail) if detail else ''}")

    # ---- 计划执行矩阵
    seeds_plan = plan["model_seeds"]
    matrix: dict[str, Any] = {"scratch": {}, "bc": {}, "supervised": {}}
    if sc:
        for fam, arms in sc["results"].items():
            for arm, per in arms.items():
                got = sorted(int(k.replace("seed", "")) for k in per
                             if k.startswith("seed"))
                matrix["scratch"][f"{fam}/{arm}"] = {
                    "planned_seeds": seeds_plan["scratch"],
                    "executed_seeds": got,
                    "match": got == sorted(seeds_plan["scratch"]),
                    "steps": per.get("seed" + str(
                        seeds_plan["scratch"][0]), {}).get(
                        "run_audit", {}).get("total_timesteps"),
                }
    if bc_int:
        for fam in CURRICULUM261_FAMILIES:
            d = _load(f"bc_results_{fam.split('_')[0]}.json")
            if d and d.get("executed"):
                got = sorted(int(k.replace("seed", ""))
                             for k in d["per_seed"])
                matrix["bc"][fam] = {
                    "planned_seeds": seeds_plan["bc"],
                    "executed_seeds": got,
                    "match": got == sorted(seeds_plan["bc"]),
                }
            elif d:
                matrix["bc"][fam] = {
                    "planned_seeds": seeds_plan["bc"],
                    "executed_seeds": [],
                    "match": None,
                    "not_executed_reason": d.get("reason"),
                }
    if sup:
        for fam, fr in sup["results"].items():
            arm0 = next(iter(fr["arms"]))
            got = sorted(int(k.replace("seed", ""))
                         for k in fr["arms"][arm0]["mlp_U"]
                         if k.startswith("seed"))
            matrix["supervised"][fam] = {
                "planned_seeds": seeds_plan["supervised"],
                "executed_seeds": got,
                "match": got == sorted(seeds_plan["supervised"]),
            }

    _req(ns and ns.get("pass"), "namespace_isolation_pass")
    _req(base and base.get("pass"), "baseline_integrity_pass")
    _req(hist and hist.get("pass"), "historical_binding_pass")
    _req(ev and ev.get("pass"), "family_evaluator_validation_pass")
    _req(gv and gv.get("pass"), "surrogate_gradient_validation_pass")
    _req(pair and pair.get("pass"), "pairing_integrity_pass")
    _req(fsc and fsc.get("pass"), "fixed_scaling_contract_pass")
    _req(bc_int and bc_int.get("pass"), "bc_execution_integrity_pass")

    # R1 evidence 保留(哈希重算)
    if hist:
        r1_ok = True
        for name, expect in hist["iterations"]["s262_diag_r1"][
                "artifact_sha256"].items():
            p = REPAIR1_DIR / name
            if not p.is_file() or _sha256_file(p) != expect:
                r1_ok = False
        _req(r1_ok, "r1_artifacts_unmodified")

    # seeds 精确执行(不多不少)
    _req(all(v["match"] for v in matrix["scratch"].values()),
         "scratch_seeds_exact")
    _req(all(v["match"] for v in matrix["supervised"].values()),
         "supervised_seeds_exact")
    bc_matches = [v["match"] for v in matrix["bc"].values()]
    _req(all(m is True or m is None for m in bc_matches),
         "bc_seeds_exact_or_not_executed")
    _req(sum(1 for m in bc_matches if m is True) >= 1,
         "bc_executed_for_learnable_families")

    # 预算一致
    _req(all(v["steps"] == R2_BANK_SPEC["scratch"]["steps_per_seed"]
             for v in matrix["scratch"].values()),
         "scratch_budget_matches_plan")

    # checkpoints
    _req(ck and ck.get("pass"), "checkpoints_all_present_hashed")
    _req(pd and pd.get("pass"), "probability_dynamics_non_empty")
    if ck:
        for run_id, v in ck["runs"].items():
            _req(v["n_expected"] == v["n_produced"]
                 and not v["extra_tags"],
                 f"checkpoint_count_{run_id}")

    # evaluator 语义(scratch results 内逐 cell identity)
    if sc:
        ident_ok = True
        denom_ok = True
        for fam, arms in sc["results"].items():
            for arm, per in arms.items():
                for s, v in per.items():
                    if not s.startswith("seed"):
                        continue
                    for rung, cell in v[
                            "final_capture_cells"][fam].items():
                        if cell["reference_identity"][
                                "reference_class"] != {
                            "c1_opportunity": "C1ReferencePolicy",
                            "c2_context": "C2ReferencePolicy",
                            "c3_cost": "C3ReferencePolicy"}[fam]:
                            ident_ok = False
                        if not cell["reference_gap_valid"] and cell[
                                "capture"] is not None:
                            denom_ok = False
        _req(ident_ok, "scratch_reference_identity_correct")
        _req(denom_ok, "invalid_denominator_never_has_capture")

    # Arm 语义
    if sc and pair:
        armb_ok = True
        for fam, arms in sc["results"].items():
            for s, v in arms.get("B_fixed_precommitted", {}).items():
                if not s.startswith("seed"):
                    continue
                if v["adapter"]["kind"] != "fixed":
                    armb_ok = False
        _req(armb_ok, "arm_B_recorded_as_fixed_kind")
        _req(pair["arm_b_constants_source"] == "plan(不读取任何 r2 "
                                              "bank)",
             "arm_B_constants_from_plan")
        c_ok = True
        for fam, arms in sc["results"].items():
            for s, v in arms.get("C_train_fitted", {}).items():
                if not s.startswith("seed"):
                    continue
                if v["adapter"]["kind"] != "fitted":
                    c_ok = False
                if v["adapter"]["scale"][-1] != 1.0:
                    c_ok = False
        _req(c_ok, "arm_C_fitted_only_position_identity")
        _req(fsc["scale"][-1] == 1.0, "arm_B_position_identity")

    # 概率分族样本
    if sc:
        samp_ok = True
        for fam, arms in sc["results"].items():
            for arm, per in arms.items():
                for s, v in per.items():
                    if not s.startswith("seed"):
                        continue
                    if not v["probability_final"].get(
                            "sampling_sufficient"):
                        samp_ok = False
        _req(samp_ok, "probability_sampling_sufficient_per_family")

    # BC 语义
    if bc_int:
        _req(all(v["critic_untouched_by_bc"]
                 for v in bc_int["runs"].values()),
             "bc_critic_untouched")
        _req(all(v["actor_import_verified"]
                 for v in bc_int["runs"].values()),
             "bc_actor_import_verified")

    # 梯度语义
    if gv:
        _req(gv["checks"].get("actor_grad_norm_close")
             and gv["checks"].get("critic_grad_norm_close"),
             "gradient_minibatch_equivalence")
        _req(gv["checks"].get("update_minibatch_identity_present"),
             "gradient_identity_complete")
    if sc:
        gsum_ok = True
        for fam, arms in sc["results"].items():
            for arm, per in arms.items():
                for s, v in per.items():
                    if not s.startswith("seed"):
                        continue
                    gs = v["minibatch_grad_summary"]
                    if not gs.get("identity_fields_complete"):
                        gsum_ok = False
        _req(gsum_ok, "gradient_records_identity_complete")

    # C2 不平衡专题
    _req(c2 is not None and "controls" in c2, "c2_imbalance_results_" \
                                              "present")
    if c2:
        has_metrics = all(
            v.get("pr_auc") is not None or v.get("roc_auc") is not None
            for arm in c2["controls"].values()
            for ctl in arm.values()
            for v in ctl["per_seed_eval"].values())
        _req(has_metrics, "c2_pr_roc_auc_present")

    # branch
    _req(branch is not None and branch.get("pass"),
         "no_family_branch_F")
    _req(branch is not None and all(
        d["evidence_family"] == fam
        for fam, d in branch["decisions"].items()),
         "branch_evidence_single_family")

    # official final 未消费
    _req(not (ppo262_artifacts_dir() / "final_evaluation_plan.json"
              ).is_file(), "official_final_plan_not_generated")

    art = {
        "format": "ppo262-repair2-semantic-validation-v1",
        "plan_digest": plan["plan_digest_self"],
        "checks": checks,
        "problems": problems,
        "plan_execution_matrix": matrix,
        "validator_note": "逐项语义验证(非文件存在性检查);任何 "
                          "checks False 即 Repair R2 Diagnostics FAIL",
        "pass": not problems,
    }
    _w("plan_execution_matrix.json", {
        "format": "ppo262-repair2-plan-execution-matrix-v1",
        **matrix,
    })
    _w("diagnostic_semantic_validation.json", art)
    print(json.dumps({"pass": art["pass"],
                      "n_checks": len(checks),
                      "problems": problems[:10]}, ensure_ascii=False))
    return 0 if art["pass"] else 2


# ============================================================ summary
def cmd_summary(args) -> int:
    """R2 诊断汇总(机器可读;verdict 由语义 validator 决定)。"""
    def _load(name):
        p = REPAIR2_DIR / name
        return json.loads(p.read_text(encoding="utf-8")) if (
            p.is_file()) else None

    sem = _load("diagnostic_semantic_validation.json")
    branch = _load("family_branch_decision.json")
    route = _load("global_route_decision.json")
    files = [
        "diagnostic_namespace_integrity.json", "baseline_integrity.json",
        "historical_diagnostic_binding.json", "route_c_integrity.json",
        "stage261_readonly.json", "diagnostic_plan.json",
        "fixed_scaling_contract.json", "family_evaluator_validation.json",
        "reference_identity_matrix.json",
        "ppo_surrogate_gradient_validation.json",
        "supervised_control_plan.json",
        "supervised_control_results.json",
        "c2_class_imbalance_results.json", "scratch_ppo_plan.json",
        "scratch_ppo_results.json", "reference_gap_validity.json",
        "preprocessing_pairing_integrity.json",
        "checkpoint_integrity.json",
        "policy_probability_dynamics.json",
        "ppo_update_diagnostics.json",
        "value_advantage_diagnostics.json", "cost_decomposition.json",
        "bc_plan.json", "bc_results_c1.json", "bc_results_c2.json",
        "bc_results_c3.json", "bc_execution_integrity.json",
        "family_branch_decision.json", "global_route_decision.json",
        "plan_execution_matrix.json",
        "diagnostic_semantic_validation.json",
    ]
    present = {f: (REPAIR2_DIR / f).is_file() for f in files}
    branches = (branch["decisions"] if branch else {})
    art = {
        "format": "ppo262-repair2-regression-summary-v1",
        "iteration": "s262_diag_r2",
        "artifacts_present": present,
        "all_artifacts_present": all(present.values()),
        "family_branches": {fam: d.get("branch")
                            for fam, d in branches.items()},
        "semantic_validation_pass": bool(
            sem and sem.get("pass")),
        "repair2_diagnostics_pass": bool(
            sem and sem.get("pass") and all(present.values())),
        "recommended_route": route.get("recommended_route")
        if route else None,
        "note": "Repair R2 PASS 仅表示诊断基础设施闭合、全部预注册"
                "对照真实执行、每族得到可信分支;Stage 2.6.2 仍为 FAIL",
        "official_final_namespace_unconsumed": True,
    }
    _w("regression_summary.json", art)
    print(json.dumps({"repair2_diagnostics_pass":
                          art["repair2_diagnostics_pass"],
                      "family_branches": art["family_branches"]},
                     ensure_ascii=False))
    return 0


# ============================================================ main
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ppo262-r2-diagnose")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("namespace-integrity").set_defaults(
        func=cmd_namespace_integrity)
    sub.add_parser("baseline-integrity").set_defaults(
        func=cmd_baseline_integrity)
    sub.add_parser("plan-lock").set_defaults(func=cmd_plan_lock)
    sub.add_parser("evaluator-validation").set_defaults(
        func=cmd_evaluator_validation)
    sub.add_parser("gradient-verify").set_defaults(func=cmd_gradient_verify)
    sub.add_parser("supervised").set_defaults(func=cmd_supervised)
    sub.add_parser("scratch").set_defaults(func=cmd_scratch)
    sub.add_parser("bc").set_defaults(func=cmd_bc)
    sub.add_parser("family-decision").set_defaults(func=cmd_family_decision)
    sub.add_parser("semantic-validation").set_defaults(
        func=cmd_semantic_validation)
    sub.add_parser("summary").set_defaults(func=cmd_summary)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
