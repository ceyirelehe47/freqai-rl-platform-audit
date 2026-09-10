"""阶段 2.6.2:sealed final evaluation(plan 锁定 → 一次性执行)。

协议(§6/§20,比 R2 更严格):

```
implementation → config dev → probes → core training
→ lock models + manifests + metric thresholds
→ lock final-evaluation plan
→ one-shot final evaluation
```

fail-closed 合同:

- plan 锁定前:ppo_final_eval_262 seed 对任何代码路径封闭
  (ppo262_namespaces.final_eval_unlocked 守卫);
- plan 绑定:R2 plan digest / 2.6.1 source identity / 2.6.2 code
  identity / selected config + digest / staged+mixed training
  manifests / 全部 final model hashes / model seeds / final seed
  schedule / metric 定义 / PASS 阈值 / production observation
  identity / preprocessing boundary / Route C identities / vendor
  SHA / git baseline;
- 执行开始即写 exposure marker(无论 PASS/FAIL/crash/checker bug,
  s262_r0 均视为已暴露;重跑直接拒绝);
- model hash 与 plan 不符 / code identity 漂移 / config 漂移
  -> 拒绝执行;
- final FAIL 不允许覆盖 artifacts(输出目录带 attempt 后缀)。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES, CURRICULUM261_RUNGS,
)
from rl_curriculum.ppo262_namespaces import (
    PPO262_ITERATION_ID, PPO262_MODEL_SEEDS, PPO262_STAGE_ID,
    final_eval_exposure_marker, final_eval_lock_marker,
    write_final_eval_exposure,
)

FINAL_PLAN_FORMAT = "ppo262-final-plan-v1"
FINAL_RESULT_FORMAT = "ppo262-final-result-v1"

#: final PASS 阈值(§23 candidate PASS 条件,plan 内逐字锁定)
FINAL_PASS_THRESHOLDS = {
    "family_core_capture_mean_gt": 0.20,
    "family_seeds_positive_min": 2,        # 至少 2/3 seeds capture > 0
    "aggregate_capture_mean_gt": 0.25,
    "aggregate_ci90_low_gt": 0.0,
    "behavior_gap_gt": {
        "c1_selectivity": 0.15, "c2_gating": 0.15,
        "c3_cost_selectivity": 0.15},
    "staged_retention_min": {"c1": 0.50, "c2": 0.60},
    "non_degenerate": True,
    "baseline_superiority": {
        "c1": ["always_flat", "always_long"],
        "c2": ["always_flat", "always_long", "c2_local_only"],
        "c3": ["always_flat", "always_long", "c3_cost_ignorant"],
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def final_plan_digest(plan: dict[str, Any]) -> str:
    """plan digest(created_utc 豁免;与 2.6.1 plan_digest 同构)。"""
    payload = {k: v for k, v in plan.items() if k != "created_utc"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return "fp-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_final_plan(
    *, r2_plan_digest: str, stage261_code_identity: dict[str, str],
    code_identity_262: dict[str, str], selected_config_name: str,
    selected_config: dict[str, Any], selected_config_digest: str,
    training_manifest_hashes: dict[str, str],
    model_hashes: dict[str, str], model_seeds: list[int],
    final_seed_schedule: dict[str, Any],
    metric_definitions: dict[str, Any],
    pass_thresholds: dict[str, Any],
    observation_identity: dict[str, Any],
    preprocessing_boundary_name: str,
    route_c_identities: dict[str, Any], vendor_sha: str,
    git_baseline: str, schedule_comparison_rule: dict[str, Any],
) -> dict[str, Any]:
    """构建 final plan(锁定前可修改;锁定后 digest 绑定一切)。"""
    return {
        "format": FINAL_PLAN_FORMAT,
        "stage": PPO262_STAGE_ID,
        "iteration": PPO262_ITERATION_ID,
        "created_utc": _utc_now(),
        "r2_plan_digest": r2_plan_digest,
        "stage261_code_identity": stage261_code_identity,
        "code_identity_262": code_identity_262,
        "selected_config": {
            "name": selected_config_name,
            "config": selected_config,
            "digest": selected_config_digest,
        },
        "training_manifest_hashes": training_manifest_hashes,
        "model_hashes": model_hashes,
        "model_seeds": list(model_seeds),
        "final_seed_schedule": final_seed_schedule,
        "metric_definitions": metric_definitions,
        "pass_thresholds": pass_thresholds,
        "observation_identity": observation_identity,
        "preprocessing_boundary": preprocessing_boundary_name,
        "route_c_identities": route_c_identities,
        "vendor_sha": vendor_sha,
        "git_baseline": git_baseline,
        "schedule_comparison_rule": schedule_comparison_rule,
        "exposure_contract": (
            "final evaluation 开始即写 exposure marker;s262_r0 无论 "
            "PASS/FAIL/crash/checker bug 均视为已暴露,同一 corpus "
            "不得再次执行"),
    }


def lock_final_plan(plan: dict[str, Any], out_dir: Path) -> str:
    """锁定 final plan(写盘 + digest);已存在即拒绝重复锁定。"""
    out_dir = Path(out_dir)
    lock_file = out_dir / "final_evaluation_plan.json"
    digest_file = out_dir / "final_evaluation_plan_digest.txt"
    if lock_file.is_file():
        raise RuntimeError(
            f"final plan 已锁定({lock_file});锁定后不得修改/重锁")
    digest = final_plan_digest(plan)
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_file.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8")
    digest_file.write_text(digest + "\n", encoding="utf-8")
    return digest


def load_locked_final_plan(out_dir: Path) -> tuple[dict[str, Any], str]:
    """读取锁定的 final plan(复算 digest 防篡改)。"""
    out_dir = Path(out_dir)
    plan = json.loads(
        (out_dir / "final_evaluation_plan.json").read_text(encoding="utf-8"))
    recorded = (out_dir / "final_evaluation_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    recomputed = final_plan_digest(plan)
    if recomputed != recorded:
        raise RuntimeError(
            f"final plan 被篡改:记录 {recorded} != 重算 {recomputed}")
    return plan, recorded


def verify_final_run_guards(
    plan: dict[str, Any], *, models: dict[str, Path],
    code_identity_262_now: dict[str, str],
) -> list[str]:
    """执行前守卫:model hash / code identity / config 漂移即拒绝。"""
    problems: list[str] = []
    for label, expected in plan["model_hashes"].items():
        path = models.get(label)
        if path is None or not Path(path).is_file():
            problems.append(f"final model 缺失: {label}")
            continue
        actual = _sha256_file(path)
        if actual != expected:
            problems.append(
                f"model hash 不匹配: {label} plan={expected[:16]}.. "
                f"actual={actual[:16]}..")
    for fname, expected in plan["code_identity_262"].items():
        if code_identity_262_now.get(fname) != expected:
            problems.append(f"2.6.2 code identity 漂移: {fname}")
    if final_eval_exposure_marker().is_file():
        problems.append("exposure marker 已存在:final corpus 已消耗")
    return problems


def begin_final_execution(plan_digest: str) -> None:
    """写 exposure marker(此后 s262_r0 final corpus 永久消耗)。"""
    write_final_eval_exposure(plan_digest, status="running")


def write_final_eval_status_completed(plan_digest: str) -> None:
    """final evaluation 结束后单次推进 exposure 状态(running->completed)。"""
    write_final_eval_exposure(plan_digest, status="completed")
