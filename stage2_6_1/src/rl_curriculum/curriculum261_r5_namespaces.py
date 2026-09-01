# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:iteration/seed namespace、守卫与 exposure 硬合同。

§12 新 R5 seed 空间(与 R0-R4 的 Stage 2.6.1 namespace 及全部
Stage 2.6.2 official/diagnostic namespace 完全不相交):
- design_r5_tier_a_main / design_r5_tier_a_validation:
  Tier A(D3-only)candidate 开发语料(两份独立,均为参数开发数据,
  不得称为 holdout);
- design_r5_tier_b_main / design_r5_tier_b_validation:
  Tier B(D2+D3 joint)语料;**Tier A 存在合格 candidate 时永久封闭**
  (derive261_seed 守卫:tier B 解锁文件 tier_b_authorized=true 才可访问,
  该文件只在 Tier A 全部 candidate 不满足硬门槛的机械条件下写入);
- preprocess_fit_calibration_r5 / preprocess_fit_holdout_r5 /
  preprocess_fit_qualification_r5(preprocessing fit bank 专用);
- calibration_r5 / calibration_holdout_r5 / qualification_r5 /
  fresh_holdout_r5 / training_r5 / stress_r5 / ppo_smoke_r5。

qualification_r5 解锁守卫(六要素):
1. plan JSON 存在(iteration == r5);
2. plan digest 文件存在;
3. digest 重算与锁定值一致;
4. plan 内 robustness gate 状态为 pass=true;
5. plan 绑定的 parameter-pack digest 与已锁定 pack artifact 一致;
6. sealed final preflight attestation 存在、digest 复算一致且绑定同一
   plan digest(§26B;final runner 启动前必须验证)。

exposure marker 硬合同(§27):
- 原子创建(O_CREAT|O_EXCL;并发 final 只有一个能成功);
- 状态只允许 running -> completed/failed/crashed 单向一次;
- 不存在任何 delete/重置 API;terminal 状态永久阻止同一 iteration 重跑;
- append-only ledger(qualification_exposure_ledger_r5.jsonl)先于 marker
  记录每个事件——marker 被手动删除时 ledger 仍判定已暴露(不可"恢复为
  未暴露")。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CURRICULUM261_ITERATION_ID_R5 = "r5"

#: R5 全部 seed namespace(单一来源定义在 curriculum261_api.py 白名单;
#: 本模块 re-export 供守卫/验证使用)。
from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_R5_NAMESPACES,
)

#: R5 artifacts 目录(WSL 项目侧;发布时映射到 stage2_6_1/artifacts/repair5)。
_REPAIR5_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / (
    "route_c_stage2_6_1_repair5")

#: design plan / parameter pack / qualification plan / exposure 文件名。
R5_DESIGN_PLAN_FILENAME = "r5_design_plan.json"
R5_DESIGN_PLAN_DIGEST_FILENAME = "r5_design_plan_digest.txt"
R5_PARAMETER_PACK_FILENAME = "r5_parameter_pack.json"
R5_DESIGN_DECISION_FILENAME = "r5_design_decision.json"
R5_PLAN_FILENAME = "qualification_plan_r5.json"
R5_PLAN_DIGEST_FILENAME = "qualification_plan_digest_r5.txt"
R5_EXPOSURE_MARKER_NAME = "qualification_exposure_r5.json"
R5_EXPOSURE_LEDGER_NAME = "qualification_exposure_ledger_r5.jsonl"
R5_SEALED_PREFLIGHT_FILENAME = "sealed_final_preflight.json"
R5_SEALED_PREFLIGHT_DIGEST_FILENAME = "sealed_final_preflight_digest.txt"
R5_STATIC_PREFLIGHT_FILENAME = "prelock_static_preflight.json"
R5_FINAL_LOCK_NAME = "qualification_r5.lock"

#: marker 允许状态机:running -> {completed, failed, crashed}(单向一次)。
R5_EXPOSURE_TERMINAL_STATUSES = ("completed", "failed", "crashed")


def _env_dir(env_key: str) -> Path:
    env_val = os.environ.get(env_key)
    return Path(env_val) if env_val else _REPAIR5_ARTIFACTS


def qualification_r5_lock_dir() -> Path:
    return _env_dir("CURRICULUM261_R5_LOCK_DIR")


def r5_design_plan_path() -> Path:
    return qualification_r5_lock_dir() / R5_DESIGN_PLAN_FILENAME


def r5_design_plan_digest_path() -> Path:
    return qualification_r5_lock_dir() / R5_DESIGN_PLAN_DIGEST_FILENAME


def r5_design_decision_path() -> Path:
    return qualification_r5_lock_dir() / R5_DESIGN_DECISION_FILENAME


def r5_parameter_pack_path() -> Path:
    return qualification_r5_lock_dir() / R5_PARAMETER_PACK_FILENAME


def qualification_r5_plan_path() -> Path:
    return qualification_r5_lock_dir() / R5_PLAN_FILENAME


def qualification_r5_digest_path() -> Path:
    return qualification_r5_lock_dir() / R5_PLAN_DIGEST_FILENAME


def qualification_r5_exposure_marker() -> Path:
    return qualification_r5_lock_dir() / R5_EXPOSURE_MARKER_NAME


def qualification_r5_exposure_ledger() -> Path:
    return qualification_r5_lock_dir() / R5_EXPOSURE_LEDGER_NAME


def sealed_preflight_path() -> Path:
    return qualification_r5_lock_dir() / R5_SEALED_PREFLIGHT_FILENAME


def sealed_preflight_digest_path() -> Path:
    return qualification_r5_lock_dir() / R5_SEALED_PREFLIGHT_DIGEST_FILENAME


# ------------------------------------------------- Tier B 机械授权守卫
def tier_b_authorized() -> bool:
    """Tier B namespace 是否已被机械规则授权。

    只有 r5_design_decision.json 显式记录 tier_b_authorized=true(Tier A
    全部 candidate 不满足全部 design 硬门槛,由 design 阶段写入)才允许
    访问 design_r5_tier_b_*。Tier A 存在合格 candidate 时该文件为 false
    (或不存在)——tier B namespace 永久封闭。
    """
    path = r5_design_decision_path()
    if not path.is_file():
        return False
    try:
        decision = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(decision.get("tier_b_authorized") is True
                and decision.get("format")
                == "cur261-r5-design-decision-v1")


# ------------------------------------------------- sealed preflight
def sealed_preflight_valid() -> bool:
    """sealed attestation 存在、digest 复算一致且格式正确。"""
    path = sealed_preflight_path()
    digest_path = sealed_preflight_digest_path()
    if not path.is_file() or not digest_path.is_file():
        return False
    try:
        att = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    from rl_curriculum.curriculum261_r5_preflight import (
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


def qualification_r5_unlocked() -> bool:
    """完整解锁守卫(六要素;全部成立才允许派生 final namespace seed)。"""
    plan_path = qualification_r5_plan_path()
    digest_path = qualification_r5_digest_path()
    if not plan_path.is_file() or not digest_path.is_file():
        return False
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R5:
        return False
    locked = digest_path.read_text(encoding="utf-8").strip()
    from rl_curriculum.curriculum261_r5_plan import plan_digest_r5

    if plan_digest_r5(plan) != locked:
        return False
    gate = plan.get("robustness_gate", {})
    if not (isinstance(gate, dict) and gate.get("pass") is True):
        return False
    pack_digest_in_plan = (
        plan.get("parameter_pack", {}).get("digest"))
    if not pack_digest_in_plan:
        return False
    from rl_curriculum.curriculum261_r5_param_pack import load_selected_pack

    try:
        pack = load_selected_pack(qualification_r5_lock_dir())
    except RuntimeError:
        return False
    if pack["digest"] != pack_digest_in_plan:
        return False
    if not sealed_preflight_valid():
        return False
    if not sealed_preflight_binds_plan(plan):
        return False
    return True


def sealed_preflight_binds_plan(plan: dict[str, Any]) -> bool:
    """attestation 绑定的 plan digest 与当前锁定 plan 一致。"""
    path = sealed_preflight_path()
    if not path.is_file():
        return False
    try:
        att = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    from rl_curriculum.curriculum261_r5_plan import plan_digest_r5

    return bool(att.get("plan_digest") == plan_digest_r5(plan))


def qualification_r5_unlocked_detail() -> dict[str, Any]:
    plan_path = qualification_r5_plan_path()
    digest_path = qualification_r5_digest_path()
    detail: dict[str, Any] = {
        "plan_exists": plan_path.is_file(),
        "digest_exists": digest_path.is_file(),
        "digest_matches": False,
        "gate_pass": False,
        "parameter_pack_bound": False,
        "sealed_preflight_valid": False,
        "sealed_preflight_binds_plan": False,
    }
    if detail["plan_exists"] and detail["digest_exists"]:
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            from rl_curriculum.curriculum261_r5_plan import plan_digest_r5

            detail["digest_matches"] = (
                plan_digest_r5(plan)
                == digest_path.read_text(encoding="utf-8").strip())
            detail["gate_pass"] = bool(
                plan.get("robustness_gate", {}).get("pass") is True)
            pack_digest_in_plan = (
                plan.get("parameter_pack", {}).get("digest"))
            if pack_digest_in_plan:
                from rl_curriculum.curriculum261_r5_param_pack import (
                    load_selected_pack,
                )

                try:
                    pack = load_selected_pack(
                        qualification_r5_lock_dir())
                    detail["parameter_pack_bound"] = bool(
                        pack["digest"] == pack_digest_in_plan)
                except RuntimeError:
                    pass
            detail["sealed_preflight_valid"] = sealed_preflight_valid()
            detail["sealed_preflight_binds_plan"] = (
                sealed_preflight_binds_plan(plan))
        except (OSError, json.JSONDecodeError):
            pass
    detail["unlocked"] = bool(
        detail["plan_exists"] and detail["digest_exists"]
        and detail["digest_matches"] and detail["gate_pass"]
        and detail["parameter_pack_bound"]
        and detail["sealed_preflight_valid"]
        and detail["sealed_preflight_binds_plan"])
    return detail


# ------------------------------------------------- exposure 硬合同
def _ledger_append(event: str, plan_digest: str, status: str,
                   note: str = "") -> None:
    """append-only 事件账本(先写 ledger 再动 marker;不提供删除)。"""
    path = qualification_r5_exposure_ledger()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "event": event,
        "iteration": CURRICULUM261_ITERATION_ID_R5,
        "plan_digest": plan_digest,
        "status": status,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ledger_entries() -> list[dict[str, Any]]:
    path = qualification_r5_exposure_ledger()
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"unparseable_line": line[:200]})
    return out


def write_qualification_r5_exposure(plan_digest: str,
                                    status: str = "running") -> None:
    """exposure marker 硬合同写入。

    - status == "running":O_CREAT|O_EXCL 原子创建(已存在即拒绝——并发
      final 只有一个成功;terminal 状态后再创 running 也拒绝);
    - status in terminal:仅允许 running -> terminal 一次(同 plan digest);
    - 每次事件先 append ledger(marker 被删时 ledger 仍判定已暴露)。
    """
    path = qualification_r5_exposure_marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    if status == "running":
        _ledger_append("marker_create", plan_digest, status)
        payload = {
            "iteration": CURRICULUM261_ITERATION_ID_R5,
            "plan_digest": plan_digest,
            "status": status,
            "written_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "contract": "R5 final qualification 一旦开始执行即视为语料"
                        "暴露;无论结果如何(含 crash),同一 "
                        "qualification_r5 corpus 不得再次执行;marker "
                        "不可删除/覆盖/恢复为未暴露(ledger 兜底);下一"
                        "次必须 R5.1/R6 + 全新 seed space。",
        }
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode(
            "utf-8")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            raise RuntimeError(
                "qualification_r5 exposure marker 已存在(并发 final 或"
                "重复执行);同一 iteration 不得重跑") from exc
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return
    if status not in R5_EXPOSURE_TERMINAL_STATUSES:
        raise RuntimeError(f"非法 marker 状态 {status!r}")
    if not path.is_file():
        raise RuntimeError(
            "exposure marker 缺失(running 从未写入或被删除);禁止在无 "
            "running marker 的情况下写 terminal 状态")
    current = json.loads(path.read_text(encoding="utf-8"))
    if current.get("status") in R5_EXPOSURE_TERMINAL_STATUSES:
        raise RuntimeError(
            f"exposure marker 已处于 terminal 状态 "
            f"{current.get('status')!r};任何状态更新被永久拒绝")
    if current.get("status") != "running":
        raise RuntimeError(
            f"非法状态迁移 {current.get('status')!r} -> {status!r}")
    if current.get("plan_digest") != plan_digest:
        raise RuntimeError("terminal 状态更新的 plan digest 与 marker 不符")
    _ledger_append("status_update", plan_digest, status)
    current["status"] = status
    current["updated_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)


def qualification_r5_exposed() -> bool:
    """本轮 iteration 是否已暴露(marker 存在 OR ledger 有任何事件)。"""
    if qualification_r5_exposure_marker().is_file():
        return True
    return any(e.get("iteration") == CURRICULUM261_ITERATION_ID_R5
               and "unparseable_line" not in e
               for e in ledger_entries())


class QualificationR5FileLock:
    """final runner 互斥锁(flock;进程存活期间持有,不可重入)。"""

    def __init__(self, blocking: bool = False) -> None:
        self.blocking = blocking
        self._fh = None

    def __enter__(self) -> "QualificationR5FileLock":
        import fcntl

        path = qualification_r5_lock_dir() / R5_FINAL_LOCK_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "a+", encoding="utf-8")
        flags = fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self._fh.fileno(), flags)
        except BlockingIOError as exc:
            self._fh.close()
            self._fh = None
            raise RuntimeError(
                "另一个 R5 final qualification 进程持有锁(并发 final "
                "被拒绝)") from exc
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._fh is not None:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


# ------------------------------------------------- namespace 隔离验证
def verify_r5_namespace_isolation() -> dict[str, Any]:
    """§12 namespace-integrity:R5 namespace 与全部历史空间不相交。"""
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
        CURRICULUM261_SEED_NAMESPACES,
        _derive261_seed_raw,
    )

    r5_set = set(CURRICULUM261_R5_NAMESPACES)
    historical = [
        ns for ns in CURRICULUM261_SEED_NAMESPACES
        if ns not in r5_set
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
    for ns in list(CURRICULUM261_R5_NAMESPACES) + historical:
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
    r5_keys = [k for k in keys if k in r5_set]
    r5_vs_hist_overlap = sorted(
        set().union(*[seen[k] for k in r5_keys]) & set().union(
            *[seen[k] for k in keys if k not in r5_set])
    ) if r5_keys and len(keys) > len(r5_keys) else []
    name_disjoint = bool(
        not (set(CURRICULUM261_R5_NAMESPACES)
             & (set(historical) | set(ns_262))))
    return {
        "format": "cur261-r5-seed-namespace-integrity-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R5,
        "r5_namespaces": list(CURRICULUM261_R5_NAMESPACES),
        "historical_261_namespaces": sorted(set(historical)),
        "stage262_namespaces": sorted(set(ns_262)),
        "namespaces_checked": len(keys),
        "seeds_per_namespace": 3 * 4 * len(pairs) * 5,
        "pairwise_collisions": collisions,
        "r5_vs_historical_overlap": len(r5_vs_hist_overlap),
        "name_space_disjoint": name_disjoint,
        "tier_b_authorized": tier_b_authorized(),
        "tier_b_namespaces": [
            ns for ns in CURRICULUM261_R5_NAMESPACES
            if "_tier_b_" in ns],
        "qualification_r5_locked_before_use": bool(
            not qualification_r5_unlocked()),
        "qualification_r5_exposed": qualification_r5_exposed(),
        "pass": bool(
            not collisions and not r5_vs_hist_overlap and name_disjoint),
    }
