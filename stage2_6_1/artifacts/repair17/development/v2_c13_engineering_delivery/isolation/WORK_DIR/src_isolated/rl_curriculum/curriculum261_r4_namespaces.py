"""阶段 2.6.1 Repair R4:iteration/seed namespace 与 qualification_r4 守卫。

§17 新 R4 seed 空间(与 R0/R1/R2/R3 的 Stage 2.6.1 namespace 及全部
Stage 2.6.2 official/diagnostic namespace 完全不相交):
- design_r4:D3 功效设计阶段专用(只做 candidate 选择,不得用于
  calibration/holdout/qualification 任何 metric);
- preprocess_fit_design_r4 / preprocess_fit_calibration_r4 /
  preprocess_fit_holdout_r4 / preprocess_fit_qualification_r4
  (preprocessing fit bank 专用;fit bank 不用于任何 qualification
  metric,只用于拟合 preprocessor);
- calibration_r4 / calibration_holdout_r4 / qualification_r4 /
  fresh_holdout_r4 / training_r4 / stress_r4 / ppo_smoke_r4。

qualification_r4 解锁守卫(沿 R3 §32 四要素 + R4 parameter pack 绑定):
1. plan JSON 存在(iteration == r4);
2. plan digest 文件存在;
3. digest 重算与锁定值一致;
4. plan 内 robustness gate 状态为 pass=true;
5. plan 绑定的 parameter-pack digest 与已锁定 pack artifact 一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CURRICULUM261_ITERATION_ID_R4 = "r4"

#: R4 全部 seed namespace(单一来源定义在 curriculum261_api.py 白名单;
#: 本模块 re-export 供守卫/验证使用)。
from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_R4_NAMESPACES,
)

#: R4 artifacts 目录(WSL 项目侧;发布时映射到 stage2_6_1/artifacts/repair4)。
_REPAIR4_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / (
    "route_c_stage2_6_1_repair4")

#: final qualification 一次性暴露 marker(exposure)。
R4_EXPOSURE_MARKER_NAME = "qualification_exposure_r4.json"

#: R4 plan/digest/pack 文件名。
R4_PLAN_FILENAME = "qualification_plan_r4.json"
R4_PLAN_DIGEST_FILENAME = "qualification_plan_digest_r4.txt"
R4_PARAMETER_PACK_FILENAME = "r4_parameter_pack.json"


def _env_dir(env_key: str) -> Path:
    import os

    env_val = os.environ.get(env_key)
    return Path(env_val) if env_val else _REPAIR4_ARTIFACTS


def qualification_r4_lock_dir() -> Path:
    return _env_dir("CURRICULUM261_R4_LOCK_DIR")


def qualification_r4_plan_path() -> Path:
    return qualification_r4_lock_dir() / R4_PLAN_FILENAME


def qualification_r4_digest_path() -> Path:
    return qualification_r4_lock_dir() / R4_PLAN_DIGEST_FILENAME


def r4_parameter_pack_path() -> Path:
    return qualification_r4_lock_dir() / R4_PARAMETER_PACK_FILENAME


def qualification_r4_unlocked() -> bool:
    """完整解锁守卫(四要素 + parameter pack 绑定一致)。

    必须同时成立:
    1. plan JSON 存在且可解析(iteration == r4);
    2. digest 文件存在;
    3. plan digest 重算与锁定值一致;
    4. plan 内 robustness_gate.pass == true(两层 gate 均过才允许 lock);
    5. plan 绑定的 parameter-pack digest 与 pack artifact 重算一致。
    """
    plan_path = qualification_r4_plan_path()
    digest_path = qualification_r4_digest_path()
    if not plan_path.is_file() or not digest_path.is_file():
        return False
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R4:
        return False
    locked = digest_path.read_text(encoding="utf-8").strip()
    from rl_curriculum.curriculum261_r4_plan import plan_digest_r4

    if plan_digest_r4(plan) != locked:
        return False
    gate = plan.get("robustness_gate", {})
    if not (isinstance(gate, dict) and gate.get("pass") is True):
        return False
    pack_digest_in_plan = (
        plan.get("parameter_pack", {}).get("digest"))
    if not pack_digest_in_plan:
        return False
    from rl_curriculum.curriculum261_r4_param_pack import (
        load_selected_pack,
    )

    try:
        pack = load_selected_pack(qualification_r4_lock_dir())
    except RuntimeError:
        return False
    return pack["digest"] == pack_digest_in_plan


def qualification_r4_unlocked_detail() -> dict[str, Any]:
    """守卫细节(诊断/测试用:各项条件各自状态)。"""
    plan_path = qualification_r4_plan_path()
    digest_path = qualification_r4_digest_path()
    detail: dict[str, Any] = {
        "plan_exists": plan_path.is_file(),
        "digest_exists": digest_path.is_file(),
        "digest_matches": False,
        "gate_pass": False,
        "parameter_pack_bound": False,
    }
    if detail["plan_exists"] and detail["digest_exists"]:
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            from rl_curriculum.curriculum261_r4_plan import plan_digest_r4

            detail["digest_matches"] = (
                plan_digest_r4(plan)
                == digest_path.read_text(encoding="utf-8").strip())
            detail["gate_pass"] = bool(
                plan.get("robustness_gate", {}).get("pass") is True)
            pack_digest_in_plan = (
                plan.get("parameter_pack", {}).get("digest"))
            if pack_digest_in_plan:
                from rl_curriculum.curriculum261_r4_param_pack import (
                    load_selected_pack,
                )

                try:
                    pack = load_selected_pack(
                        qualification_r4_lock_dir())
                    detail["parameter_pack_bound"] = bool(
                        pack["digest"] == pack_digest_in_plan)
                except RuntimeError:
                    pass
        except (OSError, json.JSONDecodeError):
            pass
    detail["unlocked"] = bool(
        detail["plan_exists"] and detail["digest_exists"]
        and detail["digest_matches"] and detail["gate_pass"]
        and detail["parameter_pack_bound"])
    return detail


def qualification_r4_exposure_marker() -> Path:
    return qualification_r4_lock_dir() / R4_EXPOSURE_MARKER_NAME


def write_qualification_r4_exposure(plan_digest: str,
                                    status: str = "running") -> None:
    from datetime import datetime, timezone

    path = qualification_r4_exposure_marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "plan_digest": plan_digest,
        "status": status,
        "written_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "contract": "R4 final qualification 一旦开始执行即视为语料暴露;"
                    "无论结果如何(含 crash/checker bug),同一 "
                    "qualification_r4 corpus 不得再次执行;下一次必须"
                    "R4.1/R5 + 全新 seed space。",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def qualification_r4_exposed() -> bool:
    return qualification_r4_exposure_marker().is_file()


def verify_r4_namespace_isolation() -> dict[str, Any]:
    """§17 namespace-integrity:R4 namespace 与全部历史空间不相交。

    枚举 R4 全部 namespace 与 (a) Stage 2.6.1 R0/R1/R2/R3 namespace、
    (b) Stage 2.6.2 official/diagnostic namespace(ppo262 官方、
    diag262r1_*、diag262r2_*)在各 (family, rung, pair, attempt) 上的
    派生 seed,断言两两无交集。
    """
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
        CURRICULUM261_SEED_NAMESPACES,
        _derive261_seed_raw,
    )

    historical = [
        ns for ns in CURRICULUM261_SEED_NAMESPACES
        if not ns.endswith("_r4")
    ]
    ns_262: list[str] = []
    try:
        from rl_curriculum.ppo262_namespaces import (
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
    for ns in list(CURRICULUM261_R4_NAMESPACES) + historical:
        vals = set()
        for fam in CURRICULUM261_FAMILIES:
            for rung in CURRICULUM261_RUNGS:
                for p in pairs:
                    for att in range(5):
                        vals.add(_derive261_seed_raw(
                            ns, fam, rung, p, att))
        seen[ns] = vals
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
    r4_keys = [k for k in keys if k.endswith("_r4")]
    r4_vs_hist_overlap = sorted(
        set().union(*[seen[k] for k in r4_keys]) & set().union(
            *[seen[k] for k in keys if not k.endswith("_r4")])
    ) if r4_keys and len(keys) > len(r4_keys) else []
    name_disjoint = bool(
        not (set(CURRICULUM261_R4_NAMESPACES)
             & (set(historical) | set(ns_262))))
    return {
        "format": "cur261-r4-seed-namespace-integrity-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R4,
        "r4_namespaces": list(CURRICULUM261_R4_NAMESPACES),
        "historical_261_namespaces": sorted(set(historical)),
        "stage262_namespaces": sorted(set(ns_262)),
        "namespaces_checked": len(keys),
        "seeds_per_namespace": 3 * 4 * len(pairs) * 5,
        "pairwise_collisions": collisions,
        "r4_vs_historical_overlap": len(r4_vs_hist_overlap),
        "name_space_disjoint": name_disjoint,
        "qualification_r4_locked_before_use": bool(
            not qualification_r4_unlocked()),
        "pass": bool(
            not collisions and not r4_vs_hist_overlap and name_disjoint),
    }
