# -*- coding: utf-8 -*-
"""执行前预算预约账本(RouteC_PositionControl R1→R2)。

R1 修复上轮计量缺陷(SCOPE_AND_BUDGET/FINDINGS R1-D):
- 上轮 UsageLedger 只在 learn 完成后计账、只查 PPO 总额,分项
  (smoke 次数/步数、BC、生成、评估)无执行前控制,smoke 21,516>
  16,384 且 11>8 次成为既成事实。全部动作**先预约后执行**:
  预约时即对"已提交+未闭合预约+本次"做分项与总额 fail-closed
  检查,超限在动作发生前拒绝。
- 失败/中断/未闭合预约保守保留(abandon 不退还),不清零、不挪用。
- JSONL 追加 + fcntl 文件锁(多进程安全);每次操作原子落盘,
  崩溃后重读恢复(未闭合预约继续占用额度)。
- 单次 PPO 步数上限在预约时校验(SB3 rollout 向上取整必须事前
  控制,不得事后把实际步数写小)。

R2 修复(FiniteRepair R2 / FINDINGS R2-01):
- commit/incident_backcharge 的非法计量(负数/NaN/inf/非整数/bool/
  未知指标)一律拒绝——旧实现只查上界,负值实际计量会**释放**已消耗
  额度(reviewer 反例:commit(actual=-100)、incident(-50) 被接纳)。
  事故补记只能增加消费。
- 新增 TaskLedger:R2 任务共享账本。首行 task_bind 绑定任务身份与
  预算面;读到无绑定的旧式账本(如已耗尽超限的 R1 账本)显式拒绝,
  不自动改写/续用——R2 账本必须由任务身份显式创建。
- 派生总项(ppo_steps+eval_steps 合计上限)在 reserve 内机械复算,
  与任务预算面一一对应,无同名近似字段漏检查。
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import time
import uuid
from pathlib import Path

from rl_posctl.versions import (
    POSCTL_R1_BUDGET, POSCTL_R2_BUDGET, POSCTL_R2_TASK_ID)

METRICS = ("ppo_steps", "ppo_learn_attempts", "bc_fits", "bc_epochs",
           "bc_minibatch_updates", "eval_steps", "gen_calls", "episodes")

# 单次上限(预约时校验;键 = 指标,值 = 单次最大)
SINGLE_CAPS = {"ppo_steps": POSCTL_R1_BUDGET["ppo_steps_single"],
               "bc_epochs": POSCTL_R1_BUDGET["bc_epochs"],
               "bc_minibatch_updates":
                   POSCTL_R1_BUDGET["bc_minibatch_updates"]}


def r2_limits() -> dict:
    """POSCTL_R2_BUDGET(预算面)→ METRICS 键限额映射(一一对应)。"""
    return {
        "ppo_steps": POSCTL_R2_BUDGET["ppo_steps_total"],
        "ppo_learn_attempts": POSCTL_R2_BUDGET["ppo_learn_attempts"],
        "bc_fits": POSCTL_R2_BUDGET["bc_fits"],
        "bc_epochs": POSCTL_R2_BUDGET["bc_epochs"],
        "bc_minibatch_updates":
            POSCTL_R2_BUDGET["bc_minibatch_updates"],
        "eval_steps": POSCTL_R2_BUDGET["eval_steps"],
        "gen_calls": POSCTL_R2_BUDGET["gen_calls"],
        "episodes": POSCTL_R2_BUDGET["episodes"],
    }


def r2_single_caps() -> dict:
    return {"ppo_steps": POSCTL_R2_BUDGET["ppo_steps_single"]}


# R2 派生总项:(总项名, (分项指标元组), 上限) —— 与任务预算面同源。
DERIVED_TOTALS = (("synthetic_total", ("ppo_steps", "eval_steps"),
                   POSCTL_R2_BUDGET["synthetic_total"]),)


def checked_amounts(amounts, *, context: str) -> dict:
    """计量值校验:未知指标/bool/非有限/非整数/负数一律拒绝。

    负数拒绝对所有路径生效(reserve/commit/incident_backcharge):
    负计量会释放已消耗额度,等同伪造预算(R2-01 reviewer 反例)。
    """
    bad_names = [k for k in amounts if k not in METRICS]
    if bad_names:
        raise ValueError(
            f"{context}: 未知计量项 {bad_names};可用={list(METRICS)}")
    out = {}
    for k, v in amounts.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{context}[{k}]: 非数值计量 {v!r} 拒绝")
        fv = float(v)
        if not math.isfinite(fv):
            raise ValueError(f"{context}[{k}]: 非有限计量 {v!r} 拒绝")
        if fv != int(fv):
            raise ValueError(f"{context}[{k}]: 非整数计量 {v!r} 拒绝")
        iv = int(fv)
        if iv < 0:
            raise ValueError(
                f"{context}[{k}]: 负计量 {iv} 拒绝"
                "(计量只能增加消费,不得释放额度)")
        out[k] = iv
    return out


class BudgetExceeded(RuntimeError):
    """执行前预约被拒(动作未发生)。"""


class ReservationLedger:
    """预约→提交/放弃 的执行前计量账本(文件锁 + JSONL 追加)。

    状态机:reserved(未闭合,保守占用)→ committed(实际用量)
    或 abandoned(保守保留全额,不退还)。
    """

    def __init__(self, path: Path, limits: dict | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limits = dict(
            limits or {k: POSCTL_R1_BUDGET[k] for k in METRICS
                       if k in POSCTL_R1_BUDGET})
        self.committed = {k: 0 for k in METRICS}
        self.incidents: dict[str, int] = {k: 0 for k in METRICS}
        self.reservations: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------ io
    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            ev = rec.get("event")
            if ev == "task_bind":
                self._on_bind_record(rec)
            elif ev == "commit":
                for k in METRICS:
                    self.committed[k] += rec.get(k, 0)
                self.reservations.pop(rec["rid"], None)
            elif ev == "reserve":
                rid = rec["rid"]
                self.reservations[rid] = {
                    k: rec.get(k, 0) for k in METRICS}
            elif ev == "abandon":
                rid = rec["rid"]
                # abandon:保守保留 —— 预约转 committed(不退)
                r = self.reservations.pop(rid, None)
                if r is not None:
                    for k, v in r.items():
                        self.committed[k] += v
            elif ev == "release":
                rid = rec["rid"]
                # release 仅允许未开始任何工作的预约(调用方负责)
                self.reservations.pop(rid, None)
            elif ev == "incident_backcharge":
                # 已发生但未经预约的消耗(事故补记;计入占用并使
                # 后续预约对超限 fail closed,超限事实在 snapshot
                # 如实可见,不隐藏不回滚)
                for k in METRICS:
                    self.incidents[k] += rec.get(k, 0)

    def _on_bind_record(self, rec: dict) -> None:
        """task_bind 行处理:基类(无绑定语义)跳过;TaskLedger 校验。"""

    def _synced_op(self, op) -> None:
        """锁内重读全部事件后执行 op(跨进程一致:检查基于最新
        落盘状态,而不是本进程的陈旧内存快照)。a+ 可读可追加。"""
        with self.path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                content = fh.read()
                self.committed = {k: 0 for k in METRICS}
                self.incidents = {k: 0 for k in METRICS}
                self.reservations = {}
                for line in content.splitlines():
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    ev = rec.get("event")
                    if ev == "task_bind":
                        self._on_bind_record(rec)
                    elif ev == "commit":
                        for k in METRICS:
                            self.committed[k] += rec.get(k, 0)
                        self.reservations.pop(rec["rid"], None)
                    elif ev == "reserve":
                        self.reservations[rec["rid"]] = {
                            k: rec.get(k, 0) for k in METRICS}
                    elif ev == "abandon":
                        r = self.reservations.pop(rec["rid"], None)
                        if r is not None:
                            for k, v in r.items():
                                self.committed[k] += v
                    elif ev == "release":
                        self.reservations.pop(rec["rid"], None)
                    elif ev == "incident_backcharge":
                        for k in METRICS:
                            self.incidents[k] += rec.get(k, 0)
                op(fh)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _append_rec(self, rec: dict, fh) -> None:
        rec["ts"] = time.time()
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------ query
    def outstanding(self) -> dict[str, int]:
        out = {k: 0 for k in METRICS}
        for r in self.reservations.values():
            for k, v in r.items():
                out[k] += v
        return out

    def effective(self) -> dict[str, int]:
        """已提交 + 未闭合预约 + 事故补记(预约检查口径)。

        事故补记使已发生的未预算消耗同样占用额度:后续预约对
        超限 fail closed,超限不得被"忘记"。
        """
        out_q = self.outstanding()
        return {k: (self.committed[k] + out_q[k]
                    + self.incidents[k]) for k in METRICS}

    def derived_totals(self) -> dict:
        """派生总项机械复算(总项 = 分项之和;与预算面一一对应)。"""
        eff = self.effective()
        out = {}
        for name, parts, cap in DERIVED_TOTALS:
            total = sum(eff[p] for p in parts)
            out[name] = {"parts": list(parts), "effective": total,
                         "cap": cap, "over": max(0, total - cap)}
        return out

    def _extra_problems(self, normalized: dict,
                        eff: dict) -> list:
        """子类钩子:额外 fail-closed 检查(如派生总项)。"""
        return []

    # ------------------------------------------------------------ ops
    def reserve(self, tag: str, **amounts) -> str:
        """动作前预约;分项/总额/单次上限任一超限即拒绝(动作未发生)。

        检查与追加在同一文件锁内完成(跨进程一致:基于最新落盘
        状态检查,不用本进程陈旧快照)。
        """
        normalized = checked_amounts(amounts, context=f"reserve[{tag}]")
        holder = {}

        def op(fh):
            eff = self.effective()
            problems = []
            for k, v in normalized.items():
                cap = self.single_caps.get(k)
                if cap is not None and v > cap:
                    problems.append(
                        f"{k}: 单次 {v}>{cap}"
                        f"(单次上限,SB3 取整须事前控制)")
                lim = self.limits.get(k)
                if lim is not None and eff[k] + v > lim:
                    problems.append(
                        f"{k}: {eff[k]}+{v}>{lim}"
                        f"(已提交+未闭合+本次;fail closed)")
            problems.extend(self._extra_problems(normalized, eff))
            if problems:
                holder["error"] = BudgetExceeded(
                    f"预算预约被拒[{tag}]: " + "; ".join(problems)
                    + f"; 当前 effective={eff}")
                return
            rid = uuid.uuid4().hex[:12]
            rec = {"event": "reserve", "rid": rid, "tag": tag}
            rec.update({k: int(normalized.get(k, 0))
                        for k in METRICS if k in normalized})
            self._append_rec(rec, fh)
            self.reservations[rid] = {
                k: int(normalized.get(k, 0)) for k in METRICS}
            holder["rid"] = rid

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]
        return holder["rid"]

    # 单次上限(键 = 指标,值 = 单次最大);子类按预算面覆盖
    single_caps = dict(SINGLE_CAPS)

    def commit(self, rid: str, tag: str = "", **actuals) -> None:
        """以实际用量结清预约;实际>预约 = 违规,fail closed。

        R2:实际计量先过 checked_amounts——负数/NaN/inf/非整数/bool/
        未知指标在结清前拒绝,不得借 commit 释放已消耗额度。
        """
        checked = checked_amounts(actuals, context=f"commit[{tag}]")
        holder = {}

        def op(fh):
            r = self.reservations.get(rid)
            if r is None:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            problems = []
            for k, v in checked.items():
                if int(v) > r.get(k, 0):
                    problems.append(
                        f"{k}: 实际 {int(v)} > 预约 {r.get(k, 0)}"
                        "(执行超预约;不得事后扩约)")
            if problems:
                # 不结清,预约保持占用;如实抛出
                holder["error"] = BudgetExceeded(
                    f"实际用量超预约[{tag}/{rid}]: "
                    + "; ".join(problems))
                return
            rec = {"event": "commit", "rid": rid, "tag": tag}
            rec.update({k: int(checked.get(k, 0)) for k in METRICS})
            self._append_rec(rec, fh)
            for k in METRICS:
                self.committed[k] += int(checked.get(k, 0))
            self.reservations.pop(rid, None)

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]

    def abandon(self, rid: str, tag: str = "", note: str = "") -> None:
        """失败/中断:保守保留全额预约(不退额度),如实留痕。"""
        holder = {}

        def op(fh):
            if rid not in self.reservations:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            self._append_rec(
                {"event": "abandon", "rid": rid, "tag": tag,
                 "note": note}, fh)
            r = self.reservations.pop(rid)
            for k, v in r.items():
                self.committed[k] += v

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]

    def release(self, rid: str, tag: str = "",
                note: str = "未开始任何工作,退还预约") -> None:
        """仅限预约后未执行任何工作的场景(如启动前冲突)。"""
        holder = {}

        def op(fh):
            if rid not in self.reservations:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            self._append_rec(
                {"event": "release", "rid": rid, "tag": tag,
                 "note": note}, fh)
            self.reservations.pop(rid)

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]

    def snapshot(self) -> dict:
        return {"committed": dict(self.committed),
                "incident_backcharged": dict(self.incidents),
                "outstanding": self.outstanding(),
                "effective": self.effective(),
                "limits": dict(self.limits),
                "derived_totals": self.derived_totals(),
                "over_limit": {k: max(0, self.effective()[k]
                                       - self.limits.get(k, 10**18))
                               for k in METRICS},
                "open_rids": sorted(self.reservations)}

    def incident_backcharge(self, tag: str, note: str = "",
                            **amounts) -> None:
        """事故补记:已发生但未经预约的消耗(诚实记录,非授权)。

        不走 reserve(那会在超限时拒记,使事故不可见);直接追加
        事故行,计入 effective ⇒ 后续预约 fail closed。调用方必须
        同时在报告中披露事故与超限量。
        R2:计量先过 checked_amounts——负数事故=释放额度,拒绝;
        事故补记只能增加消费。
        """
        checked = checked_amounts(
            amounts, context=f"incident_backcharge[{tag}]")
        rec = {"event": "incident_backcharge", "tag": tag,
               "note": note}
        rec.update({k: int(v) for k, v in checked.items()})
        holder = {}

        def op(fh):
            self._append_rec(rec, fh)
            for k in METRICS:
                self.incidents[k] += int(checked.get(k, 0))

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]


class TaskLedger(ReservationLedger):
    """R2 任务共享账本:首行 task_bind 绑定任务身份与预算面。

    - create() 显式创建(create-only;拒绝覆盖已存在账本);
    - 打开既有账本时校验 task_id 与预算面一致;
    - 无 task_bind 首行的旧式账本(如 R1 耗尽账本)显式拒绝,
      不自动改写或续用——防"读到旧账本默默换个预算面继续花";
    - 主 Agent/reviewer/新增测试/全部 runner 共用同一文件
      (fcntl 跨进程一致);
    - 派生总项(synthetic_total)在 reserve 内机械复算。
    """

    def __init__(self, path, task_id: str = POSCTL_R2_TASK_ID,
                 *, limits: dict | None = None) -> None:
        self.task_id = str(task_id)
        self._bind_seen: dict | None = None
        super().__init__(Path(path), limits=limits or r2_limits())
        self.single_caps = dict(r2_single_caps())
        if self._bind_seen is None:
            raise RuntimeError(
                f"账本无 task_bind 首行,拒绝打开:{self.path}"
                f"(任务 {self.task_id!r};旧式/R1 账本不得自动续用,"
                "R2 账本必须由 TaskLedger.create 显式创建)")

    # ------------------------------------------------------------ bind
    @classmethod
    def create(cls, path, task_id: str = POSCTL_R2_TASK_ID,
               *, limits: dict | None = None,
               binding: dict | None = None) -> "TaskLedger":
        """显式创建 R2 任务账本(create-only;已存在即拒绝)。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "event": "task_bind", "task_id": str(task_id),
            "budget_face": dict(limits or r2_limits()),
            "budget_source": "rl_posctl.versions.POSCTL_R2_BUDGET",
            "derived_totals": [
                {"name": n, "parts": list(pp), "cap": c}
                for n, pp, c in DERIVED_TOTALS],
            "binding": dict(binding or {}),
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime()),
        }
        try:
            fh = p.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise RuntimeError(
                f"任务账本已存在,拒绝覆盖(create-only):{p};"
                "如需新预算面请新任务身份显式建新账本") from exc
        with fh:
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return cls(p, task_id, limits=limits)

    def _on_bind_record(self, rec: dict) -> None:
        # _synced_op 每次锁内重放全文件:同一 bind 行重复出现视为
        # 同一绑定(静默通过);不同/多出的 bind 行才拒绝。
        if self._bind_seen is not None:
            if (rec.get("task_id") != self.task_id
                    or rec.get("task_id")
                    != self._bind_seen.get("task_id")):
                raise RuntimeError(
                    f"账本含不一致 task_bind 行,拒绝:{self.path}")
            return
        if rec.get("task_id") != self.task_id:
            raise RuntimeError(
                f"task_bind 任务身份不匹配:账本 {rec.get('task_id')!r}"
                f" != 请求 {self.task_id!r};拒绝打开 {self.path}")
        self._bind_seen = rec

    def _extra_problems(self, normalized: dict,
                        eff: dict) -> list:
        """派生总项 fail-closed 复算(与预算面一一对应)。"""
        problems = []
        for name, parts, cap in DERIVED_TOTALS:
            asked = sum(eff[p] + normalized.get(p, 0) for p in parts)
            if asked > cap:
                problems.append(
                    f"{name}[{'+'.join(parts)}]: "
                    f"{asked}>{cap}(派生总项;fail closed)")
        return problems

    def snapshot(self) -> dict:
        snap = super().snapshot()
        snap["task_id"] = self.task_id
        snap["budget_face"] = (self._bind_seen or {}).get("budget_face")
        snap["budget_face_matches_code"] = bool(
            self._bind_seen
            and (self._bind_seen.get("budget_face") or {})
            == dict(self.limits))
        return snap


def create_only_dir(path) -> Path:
    """创建唯一运行目录;已存在即拒绝(禁止同名覆盖输出)。"""
    p = Path(path)
    try:
        p.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise RuntimeError(
            f"运行目录已存在,拒绝覆盖输出(create-only):{p}"
            f";请使用新目录名") from exc
    return p
