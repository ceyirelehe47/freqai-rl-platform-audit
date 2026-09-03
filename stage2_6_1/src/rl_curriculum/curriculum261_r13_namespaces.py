# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R13:iteration/seed namespace、守卫与 exposure 硬合同。

§15 新 R13 seed 空间(与 R0-R6 的 Stage 2.6.1 namespace 及全部
Stage 2.6.2 official/diagnostic namespace 完全不相交):
- cue_contract_audit_r13:cue 检测合同审计专用(p_contract Monte Carlo;
  不读 candidate ladder、不读任何 R13 design 结果);
- preplan_smoke_r13:plan 锁定前工程 smoke(固定 sentinel ladder;
  不参与任何参数选择);
- design_r13_matched_main / design_r13_matched_validation:
  matched-ladder candidate 开发语料(两份独立,均为开发数据,
  不得称为 holdout);
- design_r13_independent_marginal:选定 ladder 的独立-rung
  marginal guard 语料(§21);
- preprocess_fit_calibration_r13 / preprocess_fit_holdout_r13 /
  preprocess_fit_qualification_r13(preprocessing fit bank 专用);
- calibration_r13 / calibration_holdout_r13 / qualification_r13;
- c2_independent_calibration_r13 / c2_independent_holdout_r13 /
  c2_independent_qualification_r13(C2 独立-rung marginal guard 三阶段);
- stress_r13 / fresh_holdout_r13 / training_r13 / ppo_smoke_r13。

qualification 三 namespace 解锁守卫(六要素,沿用 R5/R6 治理;R13 相对
R6 补强:c2_independent_qualification_r13 一并纳入守卫):
1. plan JSON 存在(iteration == r13);
2. plan digest 文件存在;
3. digest 重算与锁定值一致;
4. plan 内 robustness gate 状态为 pass=true;
5. plan 绑定的 parameter-pack digest 与已锁定 pack artifact 一致;
6. sealed final preflight attestation 存在、digest 复算一致且绑定同一
   plan digest(§25.2;final runner 启动前必须验证)。

§16.2 治理新增(R6 教训:删旧 plan 重锁被禁止):
- design data 生成开始即写 append-only started 事件;
- iteration aborted marker(O_CREAT|O_EXCL)——design data 已生成后
  任何代码/评估器缺陷导致的中止,必须写 aborted 记录并永久结束 R13;
  任何 R13 阶段入口(design/calibration/final)发现 aborted 即拒绝执行;
- 不提供任何 plan/marker/ledger 的删除或重置 API。

exposure marker 硬合同(§28):
- 原子创建(O_CREAT|O_EXCL;并发 final 只有一个能成功);
- 状态只允许 running -> completed/failed/crashed 单向一次;
- 不存在任何 delete/重置 API;terminal 状态永久阻止同一 iteration 重跑;
- append-only ledger(qualification_exposure_ledger_r13.jsonl)先于 marker
  记录每个事件——marker 被手动删除时 ledger 仍判定已暴露。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CURRICULUM261_ITERATION_ID_R13 = "r13"

#: R13 全部 seed namespace(单一来源定义在 curriculum261_api.py 白名单;
#: 本模块 re-export 供守卫/验证使用)。
from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_R13_NAMESPACES,
)

#: R13 artifacts 目录(WSL 项目侧;发布时映射到 stage2_6_1/artifacts/repair13)。
_REPAIR13_ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts" / (
    "route_c_stage2_6_1_repair13")

#: design plan / parameter pack / qualification plan / exposure 文件名。
R13_DESIGN_PLAN_FILENAME = "r13_design_plan.json"
R13_DESIGN_PLAN_DIGEST_FILENAME = "r13_design_plan_digest.txt"
R13_PARAMETER_PACK_FILENAME = "r13_parameter_pack.json"
R13_DESIGN_DECISION_FILENAME = "r13_design_decision.json"
R13_PLAN_FILENAME = "qualification_plan_r13.json"
R13_PLAN_DIGEST_FILENAME = "qualification_plan_digest_r13.txt"
R13_EXPOSURE_MARKER_NAME = "qualification_exposure_r13.json"
R13_EXPOSURE_LEDGER_NAME = "qualification_exposure_ledger_r13.jsonl"
R13_SEALED_PREFLIGHT_FILENAME = "sealed_final_preflight.json"
R13_SEALED_PREFLIGHT_DIGEST_FILENAME = "sealed_final_preflight_digest.txt"
R13_STATIC_PREFLIGHT_FILENAME = "prelock_static_preflight.json"
R13_FINAL_LOCK_NAME = "qualification_r13.lock"

#: §16.2 iteration 终止记录(design data 已生成后的 crash/代码缺陷)。
R13_ITERATION_LEDGER_NAME = "r13_iteration_events.jsonl"
R13_ABORTED_MARKER_NAME = "r13_iteration_aborted.json"

#: marker 允许状态机:running -> {completed, failed, crashed}(单向一次)。
R13_EXPOSURE_TERMINAL_STATUSES = ("completed", "failed", "crashed")


def _env_dir(env_key: str) -> Path:
    env_val = os.environ.get(env_key)
    return Path(env_val) if env_val else _REPAIR13_ARTIFACTS


def qualification_r13_lock_dir() -> Path:
    return _env_dir("CURRICULUM261_R13_LOCK_DIR")


def r13_design_plan_path() -> Path:
    return qualification_r13_lock_dir() / R13_DESIGN_PLAN_FILENAME


def r13_design_plan_digest_path() -> Path:
    return qualification_r13_lock_dir() / R13_DESIGN_PLAN_DIGEST_FILENAME


def r13_design_decision_path() -> Path:
    return qualification_r13_lock_dir() / R13_DESIGN_DECISION_FILENAME


def r13_parameter_pack_path() -> Path:
    return qualification_r13_lock_dir() / R13_PARAMETER_PACK_FILENAME


def qualification_r13_plan_path() -> Path:
    return qualification_r13_lock_dir() / R13_PLAN_FILENAME


def qualification_r13_digest_path() -> Path:
    return qualification_r13_lock_dir() / R13_PLAN_DIGEST_FILENAME


def qualification_r13_exposure_marker() -> Path:
    return qualification_r13_lock_dir() / R13_EXPOSURE_MARKER_NAME


def qualification_r13_exposure_ledger() -> Path:
    return qualification_r13_lock_dir() / R13_EXPOSURE_LEDGER_NAME


def sealed_preflight_path() -> Path:
    return qualification_r13_lock_dir() / R13_SEALED_PREFLIGHT_FILENAME


def sealed_preflight_digest_path() -> Path:
    return qualification_r13_lock_dir() / R13_SEALED_PREFLIGHT_DIGEST_FILENAME


def r13_iteration_ledger_path() -> Path:
    return qualification_r13_lock_dir() / R13_ITERATION_LEDGER_NAME


def r13_aborted_marker_path() -> Path:
    return qualification_r13_lock_dir() / R13_ABORTED_MARKER_NAME


# ------------------------------------------------- §16.2 iteration 事件账本
def _iteration_ledger_append(event: str, note: str = "") -> None:
    """append-only iteration 事件账本(design-data-started / aborted)。"""
    path = r13_iteration_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "event": event,
        "iteration": CURRICULUM261_ITERATION_ID_R13,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def iteration_ledger_entries() -> list[dict[str, Any]]:
    path = r13_iteration_ledger_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"unparseable_line": line[:200]})
    return out


def mark_design_data_started() -> None:
    """design runner 生成第一条 design episode 前记录(幂等记录多次)。

    该事件一经写入,"design data 已生成"即不可撤销——此后任何代码
    变更/评估器缺陷都只能走 §16.2 的 aborted 路径,不允许删 plan 重锁。
    """
    if r13_iteration_aborted():
        raise RuntimeError(
            "R13 iteration 已 aborted(design data 生成后发生代码/评估器"
            "缺陷);按 §16.2 本 iteration 永久结束,不得继续生成数据")
    _iteration_ledger_append("design_data_started")


def design_data_started() -> bool:
    return any(e.get("event") == "design_data_started"
               and "unparseable_line" not in e
               for e in iteration_ledger_entries())


def write_r13_iteration_aborted(reason: str) -> None:
    """§16.2:写 aborted marker(O_CREAT|O_EXCL;已存在即拒绝)。"""
    path = r13_aborted_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "iteration": CURRICULUM261_ITERATION_ID_R13,
        "aborted_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "reason": reason,
        "contract": "design data 已生成后发生代码/评估器/统计缺陷;"
                    "按 §16.2 R13 iteration 永久结束:原 plan 保留不得删除,"
                    "不得复用任何 R13 design namespace,下一轮必须 R13"
                    " + 全新 seed space。",
    }
    data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    _iteration_ledger_append("iteration_aborted", note=reason)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def r13_iteration_aborted() -> bool:
    if r13_aborted_marker_path().is_file():
        return True
    return any(e.get("event") == "iteration_aborted"
               and "unparseable_line" not in e
               for e in iteration_ledger_entries())


def require_r13_iteration_active() -> None:
    """R13 各阶段入口共用守卫:aborted 后拒绝一切继续执行。"""
    if r13_iteration_aborted():
        raise RuntimeError(
            "R13 iteration 已 aborted;按 §16.2 永久结束,任何继续执行"
            "(design/calibration/final)均被拒绝")


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
    from rl_curriculum.curriculum261_r13_preflight import (
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


def qualification_r13_unlocked() -> bool:
    """完整解锁守卫(六要素;全部成立才允许派生 final namespace seed)。"""
    plan_path = qualification_r13_plan_path()
    digest_path = qualification_r13_digest_path()
    if not plan_path.is_file() or not digest_path.is_file():
        return False
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R13:
        return False
    locked = digest_path.read_text(encoding="utf-8").strip()
    from rl_curriculum.curriculum261_r13_plan import plan_digest_r13

    if plan_digest_r13(plan) != locked:
        return False
    gate = plan.get("robustness_gate", {})
    if not (isinstance(gate, dict) and gate.get("pass") is True):
        return False
    pack_digest_in_plan = (
        plan.get("parameter_pack", {}).get("digest"))
    if not pack_digest_in_plan:
        return False
    from rl_curriculum.curriculum261_r13_param_pack import load_selected_pack

    try:
        pack = load_selected_pack(qualification_r13_lock_dir())
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
    from rl_curriculum.curriculum261_r13_plan import plan_digest_r13

    return bool(att.get("plan_digest") == plan_digest_r13(plan))


def qualification_r13_unlocked_detail() -> dict[str, Any]:
    plan_path = qualification_r13_plan_path()
    digest_path = qualification_r13_digest_path()
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
            from rl_curriculum.curriculum261_r13_plan import plan_digest_r13

            detail["digest_matches"] = (
                plan_digest_r13(plan)
                == digest_path.read_text(encoding="utf-8").strip())
            detail["gate_pass"] = bool(
                plan.get("robustness_gate", {}).get("pass") is True)
            pack_digest_in_plan = (
                plan.get("parameter_pack", {}).get("digest"))
            if pack_digest_in_plan:
                from rl_curriculum.curriculum261_r13_param_pack import (
                    load_selected_pack,
                )

                try:
                    pack = load_selected_pack(
                        qualification_r13_lock_dir())
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
    path = qualification_r13_exposure_ledger()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({
        "event": event,
        "iteration": CURRICULUM261_ITERATION_ID_R13,
        "plan_digest": plan_digest,
        "status": status,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": note,
    }, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def ledger_entries() -> list[dict[str, Any]]:
    path = qualification_r13_exposure_ledger()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"unparseable_line": line[:200]})
    return out


def write_qualification_r13_exposure(plan_digest: str,
                                    status: str = "running") -> None:
    """exposure marker 硬合同写入。

    - status == "running":O_CREAT|O_EXCL 原子创建(已存在即拒绝——并发
      final 只有一个成功;terminal 状态后再创 running 也拒绝);
    - status in terminal:仅允许 running -> terminal 一次(同 plan digest);
    - 每次事件先 append ledger(marker 被删时 ledger 仍判定已暴露)。
    """
    path = qualification_r13_exposure_marker()
    path.parent.mkdir(parents=True, exist_ok=True)
    if status == "running":
        _ledger_append("marker_create", plan_digest, status)
        payload = {
            "iteration": CURRICULUM261_ITERATION_ID_R13,
            "plan_digest": plan_digest,
            "status": status,
            "written_utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "contract": "R13 final qualification 一旦开始执行即视为语料"
                        "暴露;无论结果如何(含 crash),同一 "
                        "qualification_r13 corpus 不得再次执行;marker "
                        "不可删除/覆盖/恢复为未暴露(ledger 兜底);下一"
                        "次必须 R13 + 全新 seed space。",
        }
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode(
            "utf-8")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError as exc:
            raise RuntimeError(
                "qualification_r13 exposure marker 已存在(并发 final 或"
                "重复执行);同一 iteration 不得重跑") from exc
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return
    if status not in R13_EXPOSURE_TERMINAL_STATUSES:
        raise RuntimeError(f"非法 marker 状态 {status!r}")
    if not path.is_file():
        raise RuntimeError(
            "exposure marker 缺失(running 从未写入或被删除);禁止在无 "
            "running marker 的情况下写 terminal 状态")
    current = json.loads(path.read_text(encoding="utf-8"))
    if current.get("status") in R13_EXPOSURE_TERMINAL_STATUSES:
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


def qualification_r13_exposed() -> bool:
    """本轮 iteration 是否已暴露(marker 存在 OR ledger 有任何事件)。"""
    if qualification_r13_exposure_marker().is_file():
        return True
    return any(e.get("iteration") == CURRICULUM261_ITERATION_ID_R13
               and "unparseable_line" not in e
               for e in ledger_entries())


class QualificationR13FileLock:
    """final runner 互斥锁(flock;进程存活期间持有,不可重入)。"""

    def __init__(self, blocking: bool = False) -> None:
        self.blocking = blocking
        self._fh = None

    def __enter__(self) -> "QualificationR13FileLock":
        import fcntl

        path = qualification_r13_lock_dir() / R13_FINAL_LOCK_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(path, "a+", encoding="utf-8")
        flags = fcntl.LOCK_EX | (0 if self.blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self._fh.fileno(), flags)
        except BlockingIOError as exc:
            self._fh.close()
            self._fh = None
            raise RuntimeError(
                "另一个 R13 final qualification 进程持有锁(并发 final "
                "被拒绝)") from exc
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._fh is not None:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            self._fh.close()
            self._fh = None


# ------------------------------------------------- namespace 隔离验证
def verify_r13_namespace_isolation() -> dict[str, Any]:
    """§15 namespace-integrity:R13 namespace 与全部历史空间不相交。"""
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
        CURRICULUM261_SEED_NAMESPACES,
        _derive261_seed_raw,
    )

    r13_set = set(CURRICULUM261_R13_NAMESPACES)
    historical = [
        ns for ns in CURRICULUM261_SEED_NAMESPACES
        if ns not in r13_set
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
    for ns in list(CURRICULUM261_R13_NAMESPACES) + historical:
        vals = set()
        for fam in CURRICULUM261_FAMILIES:
            for rung in CURRICULUM261_RUNGS + ("matched_block",):
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
    r13_keys = [k for k in keys if k in r13_set]
    r13_vs_hist_overlap = sorted(
        set().union(*[seen[k] for k in r13_keys]) & set().union(
            *[seen[k] for k in keys if k not in r13_set])
    ) if r13_keys and len(keys) > len(r13_keys) else []
    name_disjoint = bool(
        not (set(CURRICULUM261_R13_NAMESPACES)
             & (set(historical) | set(ns_262))))
    return {
        "format": "cur261-r13-seed-namespace-integrity-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R13,
        "r13_namespaces": list(CURRICULUM261_R13_NAMESPACES),
        "historical_261_namespaces": sorted(set(historical)),
        "stage262_namespaces": sorted(set(ns_262)),
        "namespaces_checked": len(keys),
        "seeds_per_namespace": 3 * 5 * len(pairs) * 5,
        "pairwise_collisions": collisions,
        "r13_vs_historical_overlap": len(r13_vs_hist_overlap),
        "name_space_disjoint": name_disjoint,
        "matched_block_seed_key_checked": True,
        "qualification_r13_locked_before_use": bool(
            not qualification_r13_unlocked()),
        "qualification_r13_exposed": qualification_r13_exposed(),
        "iteration_aborted": r13_iteration_aborted(),
        "design_data_started": design_data_started(),
        "pass": bool(
            not collisions and not r13_vs_hist_overlap and name_disjoint),
    }
