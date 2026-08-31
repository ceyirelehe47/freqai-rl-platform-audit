"""阶段 2.6.1 Repair R3:iteration/seed namespace 与 qualification_r3 守卫。

§16 新 R3 seed 空间(与 R0/R1/R2 Stage 2.6.1 namespace 及全部
Stage 2.6.2 official/diagnostic namespace 完全不相交):
- preprocess_fit_calibration_r3 / preprocess_fit_holdout_r3 /
  preprocess_fit_qualification_r3(preprocessing fit bank 专用;
  fit bank 不用于任何 qualification metric,只用于拟合 preprocessor);
- calibration_r3 / calibration_holdout_r3 / qualification_r3 /
  fresh_holdout_r3 / training_r3 / stress_r3 / ppo_smoke_r3。

§32 技术债修复:qualification_r3 的解锁守卫不再"只检查 plan 文件
存在",必须同时验证:
1. plan JSON 存在;
2. plan digest 文件存在;
3. digest 重算与锁定值一致;
4. plan 内 robustness gate 状态为 pass=true。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CURRICULUM261_ITERATION_ID_R3 = "r3"

#: R3 全部 seed namespace(进入 curriculum261_api 白名单)。
CURRICULUM261_R3_NAMESPACES: tuple[str, ...] = (
    "preprocess_fit_calibration_r3",
    "preprocess_fit_holdout_r3",
    "preprocess_fit_qualification_r3",
    "calibration_r3",
    "calibration_holdout_r3",
    "qualification_r3",
    "fresh_holdout_r3",
    "training_r3",
    "stress_r3",
    "ppo_smoke_r3",
)

#: R3 artifacts 目录(WSL 项目侧;发布时映射到 stage2_6_1/artifacts/repair3)。
_REPAIR3_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / (
    "route_c_stage2_6_1_repair3")

#: final qualification 一次性暴露 marker(exposure)。
R3_EXPOSURE_MARKER_NAME = "qualification_exposure_r3.json"

#: R3 plan/digest 文件名。
R3_PLAN_FILENAME = "qualification_plan_r3.json"
R3_PLAN_DIGEST_FILENAME = "qualification_plan_digest_r3.txt"


def _env_dir(env_key: str) -> Path:
    import os

    env_val = os.environ.get(env_key)
    return Path(env_val) if env_val else _REPAIR3_ARTIFACTS


def qualification_r3_lock_dir() -> Path:
    return _env_dir("CURRICULUM261_R3_LOCK_DIR")


def qualification_r3_plan_path() -> Path:
    return qualification_r3_lock_dir() / R3_PLAN_FILENAME


def qualification_r3_digest_path() -> Path:
    return qualification_r3_lock_dir() / R3_PLAN_DIGEST_FILENAME


def qualification_r3_unlocked() -> bool:
    """完整解锁守卫(§32 修复:不止检查 plan 文件存在)。

    必须同时成立:
    1. plan JSON 存在且可解析(iteration == r3);
    2. digest 文件存在;
    3. plan digest 重算与锁定值一致;
    4. plan 内 robustness_gate.pass == true(两层 gate 均过才允许 lock)。
    """
    plan_path = qualification_r3_plan_path()
    digest_path = qualification_r3_digest_path()
    if not plan_path.is_file() or not digest_path.is_file():
        return False
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R3:
        return False
    locked = digest_path.read_text(encoding="utf-8").strip()
    from rl_curriculum.curriculum261_r3_plan import plan_digest_r3

    recomputed = plan_digest_r3(plan)
    if recomputed != locked:
        return False
    gate = plan.get("robustness_gate", {})
    if not (isinstance(gate, dict) and gate.get("pass") is True):
        return False
    return True


def qualification_r3_unlocked_detail() -> dict[str, Any]:
    """守卫细节(诊断/测试用:四项条件各自状态)。"""
    plan_path = qualification_r3_plan_path()
    digest_path = qualification_r3_digest_path()
    detail: dict[str, Any] = {
        "plan_exists": plan_path.is_file(),
        "digest_exists": digest_path.is_file(),
        "digest_matches": False,
        "gate_pass": False,
    }
    if detail["plan_exists"] and detail["digest_exists"]:
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            from rl_curriculum.curriculum261_r3_plan import plan_digest_r3

            detail["digest_matches"] = (
                plan_digest_r3(plan)
                == digest_path.read_text(encoding="utf-8").strip())
            detail["gate_pass"] = bool(
                plan.get("robustness_gate", {}).get("pass") is True)
        except (OSError, json.JSONDecodeError):
            pass
    detail["unlocked"] = bool(
        detail["plan_exists"] and detail["digest_exists"]
        and detail["digest_matches"] and detail["gate_pass"])
    return detail


def qualification_r3_exposure_marker() -> Path:
    return qualification_r3_lock_dir() / R3_EXPOSURE_MARKER_NAME


def write_qualification_r3_exposure(plan_digest: str,
                                    status: str = "running") -> None:
    from datetime import datetime, timezone

    path = qualification_r3_exposure_marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "plan_digest": plan_digest,
        "status": status,
        "written_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "contract": "R3 final qualification 一旦开始执行即视为语料暴露;"
                    "无论结果如何(含 crash/checker bug),同一 "
                    "qualification_r3 corpus 不得再次执行;下一次必须 "
                    "R3.1/R4 + 全新 seed space。",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def qualification_r3_exposed() -> bool:
    return qualification_r3_exposure_marker().is_file()


def verify_r3_namespace_isolation() -> dict[str, Any]:
    """§16 namespace-integrity:R3 namespace 与全部历史空间不相交。

    枚举 R3 全部 namespace 与 (a) Stage 2.6.1 R0/R1/R2 namespace、
    (b) Stage 2.6.2 official/diagnostic namespace(ppo262 官方、
    diag262r1_*、diag262r2_*)在各 (family, rung, pair, attempt) 上的
    派生 seed,断言两两无交集;尤其 qualification_r3 不与
    qualification_r2 / diag262r2_1_* / ppo_final_eval_262 重叠。
    """
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
        CURRICULUM261_SEED_NAMESPACES,
        _derive261_seed_raw,
    )

    historical = [
        ns for ns in CURRICULUM261_SEED_NAMESPACES
        if not ns.endswith("_r3")
    ]
    ns_262: list[str] = []
    try:
        from rl_curriculum.ppo262_namespaces import (
            PPO262_PROBE_NAMESPACES,
            PPO262_BASE_NAMESPACES,
        )
        ns_262 = list(PPO262_BASE_NAMESPACES)
    except ImportError:
        pass
    try:
        from rl_curriculum.ppo262_diag_namespaces import DIAG262_NAMESPACES
        ns_262 = ns_262 + list(DIAG262_NAMESPACES)
    except ImportError:
        pass
    try:
        from rl_curriculum.ppo262_r2_namespaces import DIAG262R2_NAMESPACES
        ns_262 = ns_262 + list(DIAG262R2_NAMESPACES)
    except ImportError:
        pass

    pairs = list(range(40)) + list(range(500, 510))
    seen: dict[str, set[int]] = {}
    for ns in list(CURRICULUM261_R3_NAMESPACES) + historical:
        vals = set()
        for fam in CURRICULUM261_FAMILIES:
            for rung in CURRICULUM261_RUNGS:
                for p in pairs:
                    for att in range(5):
                        vals.add(_derive261_seed_raw(
                            ns, fam, rung, p, att))
        seen[ns] = vals
    # 262 侧 seed 用其自身派生函数枚举(payload 的 stage id 不同,
    # 结构上为独立哈希空间;数值层面仍显式求交)。
    try:
        from rl_curriculum.ppo262_namespaces import _derive262_seed_raw
        from rl_curriculum.ppo262_diag_namespaces import (
            DIAG262_NAMESPACES, _derive_diag_raw,
        )
        from rl_curriculum.ppo262_r2_namespaces import (
            DIAG262R2_NAMESPACES, _derive_r2_raw,
        )

        vals_262: set[int] = set()
        for ns in set(ns_262):
            if ns in DIAG262_NAMESPACES:
                derive = _derive_diag_raw
            elif ns in DIAG262R2_NAMESPACES:
                derive = _derive_r2_raw
            else:
                derive = _derive262_seed_raw
            for fam in CURRICULUM261_FAMILIES:
                for rung in CURRICULUM261_RUNGS:
                    for p in pairs:
                        for att in range(5):
                            vals_262.add(derive(
                                ns, fam, rung, p, att))
        seen["__all_262__"] = vals_262
    except ImportError:
        ns_262 = []
    collisions: list[str] = []
    keys = sorted(seen)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            inter = seen[a] & seen[b]
            if inter:
                collisions.append(f"{a}∩{b}={len(inter)}")
    r3_keys = [k for k in keys if k.endswith("_r3")]
    r3_vs_hist_overlap = sorted(
        set().union(*[seen[k] for k in r3_keys]) & set().union(
            *[seen[k] for k in keys if not k.endswith("_r3")])
    ) if r3_keys and len(keys) > len(r3_keys) else []
    name_disjoint = bool(
        not (set(CURRICULUM261_R3_NAMESPACES)
             & (set(historical) | set(ns_262))))
    return {
        "format": "cur261-r3-seed-namespace-integrity-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R3,
        "r3_namespaces": list(CURRICULUM261_R3_NAMESPACES),
        "historical_261_namespaces": sorted(set(historical)),
        "stage262_namespaces": sorted(set(ns_262)),
        "namespaces_checked": len(keys),
        "seeds_per_namespace": 3 * 4 * len(pairs) * 5,
        "pairwise_collisions": collisions,
        "r3_vs_historical_overlap": len(r3_vs_hist_overlap),
        "name_space_disjoint": name_disjoint,
        "qualification_r3_locked_before_use": bool(
            not qualification_r3_unlocked()),
        "pass": bool(
            not collisions and not r3_vs_hist_overlap and name_disjoint),
    }
