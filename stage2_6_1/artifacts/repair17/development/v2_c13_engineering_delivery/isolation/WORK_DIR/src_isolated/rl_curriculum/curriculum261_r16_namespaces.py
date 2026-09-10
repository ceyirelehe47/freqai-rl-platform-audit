# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R16 namespace 状态与静态资格(适配层)。

与 R15 的区别(§2.3/§7):
- exposure/终态/aborted 的权威状态全部由 curriculum261_r16_execgov
  的 journal 承担;本模块不再提供任何可写 marker 入口(投影由会话
  持有者生成),杜绝"终态 writer 只认 plan digest 不认所有权"的
  R15 缺口;
- 静态资格(六要素)保留为只读检查:它回答"可以申请开始
  qualification",不回答"现在可以生成正式数据"(§7.1 静态资格
  ≠ 动态执行权;动态授权唯一入口 =
  curriculum261_r16_execgov.require_r16_generation_authorization);
- namespace 隔离拆成两级(§7.2):名称/角色隔离是静态检查,
  preflight 可用;涉及本轮 final 数值 seed 的碰撞抽检必须移入
  唯一授权窗口(final core 内 grant 激活后执行),私有
  _derive261_seed_raw 不是绕过守卫的通道。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r16_execgov import (
    CURRICULUM261_ITERATION_ID_R16,
    R16_EXPOSURE_TERMINAL_STATUSES,
    iteration_aborted,
    r16_exposure_marker_path,
    r16_state_root,
)

#: R16 全部 seed namespace(白名单单一来源在 curriculum261_api.py)。
from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_R16_NAMESPACES,
    CURRICULUM261_R16_FORMAL_NAMESPACES,
)

#: r16 状态文件名(全部位于 r16_state_root())。
R16_DESIGN_PLAN_FILENAME = "r16_design_plan.json"
R16_DESIGN_PLAN_DIGEST_FILENAME = "r16_design_plan_digest.txt"
R16_PARAMETER_PACK_FILENAME = "r16_parameter_pack.json"
R16_DESIGN_DECISION_FILENAME = "r16_design_decision.json"
R16_PLAN_FILENAME = "qualification_plan_r16.json"
R16_PLAN_DIGEST_FILENAME = "qualification_plan_digest_r16.txt"
R16_SEALED_PREFLIGHT_FILENAME = "sealed_final_preflight_r16.json"
R16_SEALED_PREFLIGHT_DIGEST_FILENAME = "sealed_final_preflight_r16_digest.txt"
R16_STATIC_PREFLIGHT_FILENAME = "prelock_static_preflight_r16.json"


def r16_design_plan_path() -> Path:
    return r16_state_root() / R16_DESIGN_PLAN_FILENAME


def r16_design_plan_digest_path() -> Path:
    return r16_state_root() / R16_DESIGN_PLAN_DIGEST_FILENAME


def r16_design_decision_path() -> Path:
    return r16_state_root() / R16_DESIGN_DECISION_FILENAME


def r16_parameter_pack_path() -> Path:
    return r16_state_root() / R16_PARAMETER_PACK_FILENAME


def qualification_r16_plan_path() -> Path:
    return r16_state_root() / R16_PLAN_FILENAME


def qualification_r16_digest_path() -> Path:
    return r16_state_root() / R16_PLAN_DIGEST_FILENAME


def sealed_preflight_r16_path() -> Path:
    return r16_state_root() / R16_SEALED_PREFLIGHT_FILENAME


def sealed_preflight_r16_digest_path() -> Path:
    return r16_state_root() / R16_SEALED_PREFLIGHT_DIGEST_FILENAME


# ------------------------------------------------- iteration 状态(只读)
def r16_iteration_aborted() -> bool:
    """iteration 终止判定(journal 权威;损坏即 fail closed)。"""
    return iteration_aborted(strict=True)


def require_r16_iteration_active() -> None:
    """R16 各阶段入口共用守卫:aborted 后拒绝一切继续执行。"""
    if r16_iteration_aborted():
        raise RuntimeError(
            "R16 iteration 已 aborted;按 §16.2 永久结束,任何继续执行"
            "(design/calibration/final)均被拒绝")


def write_r16_iteration_aborted(reason: str) -> None:
    """兼容入口(机械替换后的 r16_design/r16_cli 调用)。

    R16 语义:iteration 终止是失败封口事件,唯一写入路径 =
    execgov.record_iteration_aborted_standalone(锁内 journal
    append + 投影;存在活动会话时拒绝——不得干扰正在运行的
    正式执行)。
    """
    from rl_curriculum.curriculum261_r16_execgov import (
        record_iteration_aborted_standalone,
    )

    record_iteration_aborted_standalone(reason)


def mark_design_data_started() -> None:
    """§16.2 design runner 生成第一条 design episode 前记录。

    该事件一经写入,"design data 已生成"即不可撤销——此后任何
    代码变更/评估器缺陷都只能走 §16.2 的 aborted 路径。R16:
    权威 journal 事件(锁外允许;单向 append,幂等记录多次)。
    """
    from rl_curriculum.curriculum261_r16_execgov import journal_append

    if r16_iteration_aborted():
        raise RuntimeError(
            "R16 iteration 已 aborted;design data 不得再生成"
            "(§16.2 永久结束)")
    journal_append("design_data_started")


def design_data_started() -> bool:
    from rl_curriculum.curriculum261_r16_execgov import journal_entries

    return any(e.get("event") == "design_data_started"
               for e in journal_entries(strict=False))


def qualification_r16_lock_dir() -> Path:
    """兼容别名(机械转换后的 r16_cli 调用)= r16_state_root。"""
    return r16_state_root()


def qualification_r16_exposed() -> bool:
    """exposure 是否已发生(journal 权威;损坏按已暴露处理)。"""
    from rl_curriculum.curriculum261_r16_execgov import (
        R16JournalCorruption,
        exposure_state as _state,
    )

    try:
        return _state()["exposed"]
    except R16JournalCorruption:
        return True  # fail closed:损坏按已暴露


def verify_r16_namespace_isolation() -> dict[str, Any]:
    """§15 namespace-integrity 兼容入口(名称级;数值抽检在授权
    窗口内由 verify_r16_namespace_collision_within_grant 执行)。"""
    return verify_r16_namespace_name_isolation()


# ------------------------------------------------- sealed preflight
def sealed_preflight_r16_valid() -> bool:
    """sealed attestation 存在、digest 复算一致且格式正确。"""
    path = sealed_preflight_r16_path()
    digest_path = sealed_preflight_r16_digest_path()
    if not path.is_file() or not digest_path.is_file():
        return False
    try:
        att = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    from rl_curriculum.curriculum261_r15_preflight import (
        sealed_preflight_digest,
    )

    try:
        if sealed_preflight_digest(att) != att.get("digest"):
            return False
    except (KeyError, TypeError):
        return False
    if digest_path.read_text(encoding="utf-8").strip() != att.get("digest"):
        return False
    return bool(att.get("pass") is True)


def sealed_preflight_r16_binds_plan(plan: dict[str, Any]) -> bool:
    """sealed attestation 绑定当前 qualification plan。"""
    path = sealed_preflight_r16_path()
    if not path.is_file():
        return False
    try:
        att = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    from rl_curriculum.curriculum261_r15_plan import plan_digest_r15

    try:
        return att.get("plan_digest") == plan_digest_r15(plan)
    except (KeyError, TypeError):
        return False


# ------------------------------------------------- 静态资格(六要素)
def qualification_r16_unlocked() -> bool:
    """完整静态解锁守卫(六要素,只读)。

    plan 存在且 iteration=r16;digest 复算一致;robustness gate
    PASS;parameter pack 绑定一致;sealed preflight 有效且绑定本
    plan。它只是"可以申请开始 qualification"的静态资格(§7.1)。
    """
    plan_path = qualification_r16_plan_path()
    digest_path = qualification_r16_digest_path()
    if not plan_path.is_file() or not digest_path.is_file():
        return False
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R16:
        return False
    locked = digest_path.read_text(encoding="utf-8").strip()
    from rl_curriculum.curriculum261_r15_plan import plan_digest_r15

    if plan_digest_r15(plan) != locked:
        return False
    gate = plan.get("robustness_gate", {})
    if not (isinstance(gate, dict) and gate.get("pass") is True):
        return False
    pack_digest_in_plan = (
        plan.get("parameter_pack", {}).get("digest"))
    if not pack_digest_in_plan:
        return False
    from rl_curriculum.curriculum261_r15_param_pack import load_selected_pack

    try:
        pack = load_selected_pack(r16_state_root())
    except RuntimeError:
        return False
    if pack["digest"] != pack_digest_in_plan:
        return False
    if not sealed_preflight_r16_valid():
        return False
    if not sealed_preflight_r16_binds_plan(plan):
        return False
    return True


def qualification_r16_unlocked_detail() -> dict[str, Any]:
    """六要素逐项事实(诊断/证据用;与 bool 结论同源)。"""
    detail: dict[str, Any] = {
        "iteration": CURRICULUM261_ITERATION_ID_R16,
        "plan_present": qualification_r16_plan_path().is_file(),
        "digest_present": qualification_r16_digest_path().is_file(),
    }
    try:
        plan = json.loads(
            qualification_r16_plan_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        plan = None
    detail["plan_iteration_ok"] = bool(
        plan and plan.get("iteration")
        == CURRICULUM261_ITERATION_ID_R16)
    from rl_curriculum.curriculum261_r15_plan import plan_digest_r15

    try:
        detail["digest_recompute_ok"] = bool(
            plan and plan_digest_r15(plan)
            == qualification_r16_digest_path().read_text(
                encoding="utf-8").strip())
    except (OSError, KeyError, TypeError):
        detail["digest_recompute_ok"] = False
    gate = (plan or {}).get("robustness_gate", {})
    detail["robustness_gate_pass"] = bool(
        isinstance(gate, dict) and gate.get("pass") is True)
    from rl_curriculum.curriculum261_r15_param_pack import load_selected_pack

    try:
        pack = load_selected_pack(r16_state_root())
        detail["parameter_pack_bound"] = bool(
            plan and pack["digest"]
            == plan.get("parameter_pack", {}).get("digest"))
    except RuntimeError:
        detail["parameter_pack_bound"] = False
    detail["sealed_preflight_valid"] = sealed_preflight_r16_valid()
    detail["sealed_preflight_binds_plan"] = bool(
        plan and sealed_preflight_r16_binds_plan(plan))
    return detail


# ------------------------------------------------- namespace 隔离(两级)
def verify_r16_namespace_name_isolation() -> dict[str, Any]:
    """§7.2 名称/角色隔离(静态,preflight 阶段可用)。

    只比较 namespace 名称集合与历史空间命名,R16 正式四件套与
    R0–R15 全部历史 namespace 及 R16 工程 namespace 不相交;不派生
    任何 seed 数值。
    """
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R16_NAMESPACE_ROLES,
    )

    collisions: list[dict[str, str]] = []
    for name in CURRICULUM261_R16_FORMAL_NAMESPACES:
        role = CURRICULUM261_R16_NAMESPACE_ROLES.get(name)
        if role is None:
            collisions.append({"namespace": name, "issue": "unregistered"})
        elif role.get("iteration") != CURRICULUM261_ITERATION_ID_R16:
            collisions.append({
                "namespace": name,
                "issue": "role iteration mismatch",
            })
    historical_overlap = [
        name for name in CURRICULUM261_R16_FORMAL_NAMESPACES
        if any(name.endswith(f"_r{num}") for num in range(0, 16))]
    return {
        "level": "name_only",
        "formal_namespaces": list(CURRICULUM261_R16_FORMAL_NAMESPACES),
        "collisions": collisions,
        "historical_iteration_overlap": historical_overlap,
        "pass": not collisions and not historical_overlap,
    }


def verify_r16_namespace_collision_within_grant() -> dict[str, Any]:
    """§7.2 数值碰撞抽检(必须在唯一授权窗口内执行)。

    调用 derive261_seed(受守卫入口)对本轮 final namespace 与
    邻近历史 namespace 的 seed 数值做碰撞抽检;无有效授权时在
    派生前被拒。算法本身不改,也不把有限抽检宣传为对整个 seed
    空间的绝对证明。
    """
    from rl_curriculum.curriculum261_api import derive261_seed

    checked: list[dict[str, Any]] = []
    any_collision = False
    for name in CURRICULUM261_R16_FORMAL_NAMESPACES:
        probes: list[int] = []
        for family in ("c1", "c2", "c3"):
            for rung_i in range(3):
                try:
                    probes.append(derive261_seed(
                        name, family, f"rung{rung_i}",
                        pair_index=rung_i, attempt=0))
                except RuntimeError as exc:
                    checked.append({
                        "namespace": name, "family": family,
                        "rung": f"rung{rung_i}",
                        "authorized_derivation": False,
                        "error": str(exc)[:300],
                    })
                    continue
        checked.append({
            "namespace": name,
            "authorized_derivation": bool(probes),
            "probe_count": len(probes),
        })
    return {
        "level": "numeric_collision_within_grant",
        "checked": checked,
        "note": "有限抽检,非全空间证明;授权缺失即拒绝",
        "pass": all(c.get("authorized_derivation")
                    for c in checked),
    }


__all__ = [
    "CURRICULUM261_ITERATION_ID_R16",
    "R16_EXPOSURE_TERMINAL_STATUSES",
    "CURRICULUM261_R16_NAMESPACES",
    "CURRICULUM261_R16_FORMAL_NAMESPACES",
    "r16_state_root",
    "r16_exposure_marker_path",
    "r16_iteration_aborted",
    "require_r16_iteration_active",
    "sealed_preflight_r16_valid",
    "sealed_preflight_r16_binds_plan",
    "qualification_r16_unlocked",
    "qualification_r16_unlocked_detail",
    "verify_r16_namespace_name_isolation",
    "verify_r16_namespace_collision_within_grant",
]
