# -*- coding: utf-8 -*-
"""执行前预算预约账本(RouteC_PositionControl R1→R2→R3)。

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

R3 修复(FiniteRepair R3 / FINDINGS R3-01,reviewer F1):
- 预算面真正绑定:_on_bind_record 只核 task_id、异面账本可按代码
  缺省面重新打开的反例(header eval=0 → 重开变 32768 且 snapshot
  matches=false 仍可 reserve)已闭合。TaskLedger 面一律取自
  task_registry()(任务身份 → 预算面/单次上限/派生总项一一对应);
  显式 limits 与注册表面不一致、头部面与代码面不一致、多 bind 行
  面不一致,均在打开(=首资源消费前)拒绝。
- 总预约与叶级消费不双计:新增 draw(rid, ...)——把叶级实际消费从
  已授权预约中划拨入账;commit(rid, actuals) 以**总量**结清
  (已划拨部分不再重复入账,未用额度正常结清释放);abandon 只保留
  未划拨余额。同一动作在任务总量中只占用一次(旧:eval/smoke 总
  预约 + QuotaLedger 逐叶 reserve/commit 双记,9 次生成记 18,
  剩 9 额度反而首叶被拒)。
- 已知实测(draw/commit)与未知实耗(abandon 余额)在事件流中
  分列,不混为一类。
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
    POSCTL_R1_BUDGET, POSCTL_R2_BUDGET, POSCTL_R2_TASK_ID,
    POSCTL_R3_BUDGET, POSCTL_R3_TASK_ID)

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


def r3_limits() -> dict:
    """POSCTL_R3_BUDGET(R3 有限修复面)→ METRICS 键限额映射。"""
    return {
        "ppo_steps": POSCTL_R3_BUDGET["ppo_steps_total"],
        "ppo_learn_attempts": POSCTL_R3_BUDGET["ppo_learn_attempts"],
        "bc_fits": POSCTL_R3_BUDGET["bc_fits"],
        "bc_epochs": POSCTL_R3_BUDGET["bc_epochs"],
        "bc_minibatch_updates":
            POSCTL_R3_BUDGET["bc_minibatch_updates"],
        "eval_steps": POSCTL_R3_BUDGET["eval_steps"],
        "gen_calls": POSCTL_R3_BUDGET["gen_calls"],
        "episodes": POSCTL_R3_BUDGET["episodes"],
    }


def r3_single_caps() -> dict:
    return {"ppo_steps": POSCTL_R3_BUDGET["ppo_steps_single"]}


# R2 派生总项:(总项名, (分项指标元组), 上限) —— 与任务预算面同源。
DERIVED_TOTALS = (("synthetic_total", ("ppo_steps", "eval_steps"),
                   POSCTL_R2_BUDGET["synthetic_total"]),)

# R3 派生总项(同构;上限 = R3 面 ppo+eval 合计 4,224)。
DERIVED_TOTALS_R3 = (("synthetic_total", ("ppo_steps", "eval_steps"),
                      POSCTL_R3_BUDGET["synthetic_total"]),)


def task_registry() -> dict:
    """任务身份 → 预算面注册表(一一对应;TaskLedger 的唯一面来源)。

    key = task_id;value.limits 单一事实来源 = rl_posctl.versions 的
    预算面常量。未知任务身份不在注册表内 ⇒ TaskLedger 拒绝打开。
    """
    return {
        POSCTL_R2_TASK_ID: {
            "limits": r2_limits(),
            "single_caps": r2_single_caps(),
            "derived_totals": DERIVED_TOTALS,
            "budget_source": "rl_posctl.versions.POSCTL_R2_BUDGET",
        },
        POSCTL_R3_TASK_ID: {
            "limits": r3_limits(),
            "single_caps": r3_single_caps(),
            "derived_totals": DERIVED_TOTALS_R3,
            "budget_source": "rl_posctl.versions.POSCTL_R3_BUDGET",
        },
    }


def open_task_ledger(path) -> "TaskLedger":
    """按账本首行 task_bind 的任务身份打开任务账本。

    头部声明哪个任务就按哪个任务的注册表面核对(runner 入口用;
    不再各自硬编码任务 id)。无绑定首行 → 交由 TaskLedger 拒绝。
    """
    p = Path(path)
    header_tid = None
    if p.exists():
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                rec = json.loads(s)
                if rec.get("event") == "task_bind":
                    header_tid = rec.get("task_id")
                break
    if header_tid is None:
        # 无 task_bind 首行:TaskLedger 会给出明确拒绝信息
        return TaskLedger(p, POSCTL_R2_TASK_ID)
    return TaskLedger(p, header_tid)


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
    """预约→划拨/提交/放弃 的执行前计量账本(文件锁 + JSONL 追加)。

    状态机(R3 起三分):
    - reserved(未闭合,保守占用授权额度)
      → draw(叶级实际消费,从预约中划拨,计入 committed)
      → committed(实际用量结清;commit(actuals) 以总量结清,
        已 draw 部分不再重复入账,未用余额正常释放)
      或 abandoned(未划拨余额保守保留,不退还);
    - release 仅限零划拨(未开始任何工作)的预约。

    事件流(append-only JSONL;重放即恢复):
    task_bind / reserve / draw / commit / abandon / release /
    incident_backcharge。R2 旧记录无 draw/余额字段,重放兼容
    (旧 commit = 全额结清;旧 abandon = 全额保留)。
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
        self.drawn: dict[str, dict] = {}
        self._load()
    # 派生总项规格(子类在 super().__init__ 前用任务注册表覆盖;
    # 基类默认 = R2 面,供 R1 旧入口兼容)——类属性,基类构造不覆写。
    _derived_spec = tuple(DERIVED_TOTALS)

    # ------------------------------------------------------------ io
    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(
                encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            self._apply_event(rec)

    def _apply_event(self, rec: dict) -> None:
        """单行事件重放(_load 与 _synced_op 共用;R3 去重)。"""
        ev = rec.get("event")
        if ev == "task_bind":
            self._on_bind_record(rec)
        elif ev == "commit":
            # R3 新记录:per-metric 结清增量在 amounts;R2 旧记录:
            # 顶层全额(无 draw ⇒ 增量=全额,语义一致)。
            if isinstance(rec.get("amounts"), dict):
                for k in METRICS:
                    self.committed[k] += int(
                        rec["amounts"].get(k, 0))
            else:
                for k in METRICS:
                    self.committed[k] += rec.get(k, 0)
            self.reservations.pop(rec["rid"], None)
            self.drawn.pop(rec["rid"], None)
        elif ev == "reserve":
            rid = rec["rid"]
            self.reservations[rid] = {
                k: rec.get(k, 0) for k in METRICS}
            self.drawn.setdefault(rid, {k: 0 for k in METRICS})
        elif ev == "draw":
            rid = rec["rid"]
            if rid not in self.reservations:
                raise RuntimeError(
                    f"账本事件损坏:draw 引用未知预约 {rid!r}"
                    f"({self.path})")
            for k in METRICS:
                self.committed[k] += rec.get(k, 0)
                self.drawn[rid][k] += rec.get(k, 0)
        elif ev == "abandon":
            rid = rec["rid"]
            # abandon:未划拨余额保守保留(不退)。新记录携带余额
            # 明细(amounts);R2 旧记录无该字段 → 保留整笔预约。
            r = self.reservations.pop(rid, None)
            self.drawn.pop(rid, None)
            if r is not None:
                rem = {k: int(rec.get("amounts", {}).get(k, r[k]))
                       for k in METRICS} if isinstance(
                           rec.get("amounts"), dict) else dict(r)
                for k, v in rem.items():
                    self.committed[k] += max(0, v)
        elif ev == "release":
            rid = rec["rid"]
            # release 仅允许未开始任何工作的预约(调用方负责)
            self.reservations.pop(rid, None)
            self.drawn.pop(rid, None)
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
                self.drawn = {}
                for line in content.splitlines():
                    if not line.strip():
                        continue
                    self._apply_event(json.loads(line))
                op(fh)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _append_rec(self, rec: dict, fh) -> None:
        rec["ts"] = time.time()
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------ query
    def reservation_remainder(self, rid: str) -> dict:
        """单笔预约的未划拨余额(authorized − drawn)。"""
        r = self.reservations.get(rid) or {k: 0 for k in METRICS}
        d = self.drawn.get(rid) or {k: 0 for k in METRICS}
        return {k: max(0, r.get(k, 0) - d.get(k, 0))
                for k in METRICS}

    def outstanding(self) -> dict[str, int]:
        """未闭合预约的未划拨余额合计(授权中尚未消费的部分)。"""
        out = {k: 0 for k in METRICS}
        for rid in self.reservations:
            rem = self.reservation_remainder(rid)
            for k, v in rem.items():
                out[k] += v
        return out

    def effective(self) -> dict[str, int]:
        """已提交(含 draw)+ 未闭合余额 + 事故补记(预约检查口径)。

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
        for name, parts, cap in self._derived_spec:
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
            self.drawn[rid] = {k: 0 for k in METRICS}
            holder["rid"] = rid

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]
        return holder["rid"]

    # 单次上限(键 = 指标,值 = 单次最大);子类按预算面覆盖
    single_caps = dict(SINGLE_CAPS)

    def draw(self, rid: str, tag: str = "", **amounts) -> None:
        """叶级实际消费:从已授权预约中划拨(同一动作只记一次)。

        R3-01:总预约给叶级消费提供已授权额度;叶调用 draw 而不是
        再 reserve(旧双计根因)。划拨量 > 预约余额 = 违规
        fail closed(动作未发生即拒绝,不得事后扩约)。
        """
        checked = checked_amounts(amounts, context=f"draw[{tag}]")
        holder = {}

        def op(fh):
            if rid not in self.reservations:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            r = self.reservations[rid]
            d = self.drawn[rid]
            problems = []
            for k, v in checked.items():
                if d.get(k, 0) + v > r.get(k, 0):
                    problems.append(
                        f"{k}: 已划拨 {d.get(k, 0)}+{v}"
                        f">预约 {r.get(k, 0)}"
                        "(叶级消费超授权;不得事后扩约)")
            if problems:
                holder["error"] = BudgetExceeded(
                    f"划拨超预约[{tag}/{rid}]: " + "; ".join(problems))
                return
            rec = {"event": "draw", "rid": rid, "tag": tag}
            rec.update({k: int(checked.get(k, 0)) for k in METRICS
                        if k in checked})
            self._append_rec(rec, fh)
            for k in METRICS:
                self.committed[k] += int(checked.get(k, 0))
                if k in checked:
                    d[k] += int(checked[k])

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]

    def commit(self, rid: str, tag: str = "", **actuals) -> None:
        """以实际总量结清预约;实际>预约 = 违规,fail closed。

        R2:实际计量先过 checked_amounts——负数/NaN/inf/非整数/bool/
        未知指标在结清前拒绝,不得借 commit 释放已消耗额度。
        R3:actuals 为该预约累计**总量**;已 draw 部分不重复入账,
        结清时只补记差额;未用余额随结清释放(正常完成)。
        """
        checked = checked_amounts(actuals, context=f"commit[{tag}]")
        holder = {}

        def op(fh):
            if rid not in self.reservations:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            r = self.reservations[rid]
            d = self.drawn.get(rid) or {k: 0 for k in METRICS}
            problems = []
            for k, v in checked.items():
                if int(v) > r.get(k, 0):
                    problems.append(
                        f"{k}: 实际 {int(v)} > 预约 {r.get(k, 0)}"
                        "(执行超预约;不得事后扩约)")
                if int(v) < d.get(k, 0):
                    problems.append(
                        f"{k}: 实际总量 {int(v)} < 已划拨 "
                        f"{d.get(k, 0)}(实测不可回缩;账实不符)")
            if problems:
                # 不结清,预约保持占用;如实抛出
                holder["error"] = BudgetExceeded(
                    f"实际用量与预约不符[{tag}/{rid}]: "
                    + "; ".join(problems))
                return
            delta = {k: int(checked.get(k, 0)) - d.get(k, 0)
                     for k in METRICS}
            rec = {"event": "commit", "rid": rid, "tag": tag,
                   "amounts": {k: delta[k] for k in METRICS},
                   "actual_total": {k: int(checked.get(k, 0))
                                    for k in METRICS}}
            self._append_rec(rec, fh)
            for k in METRICS:
                self.committed[k] += delta[k]
            self.reservations.pop(rid, None)
            self.drawn.pop(rid, None)

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]

    def abandon(self, rid: str, tag: str = "", note: str = "") -> None:
        """失败/中断:未划拨余额保守保留(不退额度),如实留痕。

        R3:已 draw 部分是实测消费(已入账);abandon 只把**未划拨
        余额**转为保守占用——已知实测与未知实耗分列,不混类。
        """
        holder = {}

        def op(fh):
            if rid not in self.reservations:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            r = self.reservations[rid]
            d = self.drawn.get(rid) or {k: 0 for k in METRICS}
            rem = {k: max(0, r.get(k, 0) - d.get(k, 0))
                   for k in METRICS}
            self._append_rec(
                {"event": "abandon", "rid": rid, "tag": tag,
                 "note": note, "amounts": rem}, fh)
            self.reservations.pop(rid, None)
            self.drawn.pop(rid, None)
            for k, v in rem.items():
                self.committed[k] += v

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]

    def release(self, rid: str, tag: str = "",
                note: str = "未开始任何工作,退还预约") -> None:
        """仅限预约后未执行任何工作(零划拨)的场景。"""
        holder = {}

        def op(fh):
            if rid not in self.reservations:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            d = self.drawn.get(rid) or {k: 0 for k in METRICS}
            if any(d.get(k, 0) > 0 for k in METRICS):
                holder["error"] = RuntimeError(
                    f"预约 {rid} 已有划拨消费,不得 release"
                    "(已发生的工作不得免计;用 commit 结清)")
                return
            self._append_rec(
                {"event": "release", "rid": rid, "tag": tag,
                 "note": note}, fh)
            self.reservations.pop(rid, None)
            self.drawn.pop(rid, None)

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
                "open_rids": sorted(self.reservations),
                "reservations_detail": {
                    rid: {"authorized": dict(self.reservations[rid]),
                          "drawn": dict(self.drawn.get(
                              rid, {k: 0 for k in METRICS})),
                          "remaining": self.reservation_remainder(rid)}
                    for rid in sorted(self.reservations)}}

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
    """任务共享账本(R2 起多个任务身份;R3 面绑定闭合)。

    - 预算面/单次上限/派生总项一律取自 task_registry()[task_id],
      与 rl_posctl.versions 预算面常量一一对应(机械可复算);
    - create() 显式创建(create-only;拒绝覆盖已存在账本);
    - 打开既有账本时校验 task_id **与预算面/派生总项**一致:
      头部面 ≠ 代码面(如 header eval=0 重开变缺省 32768)、
      显式 limits ≠ 注册表面、多 bind 行面不一致,一律拒绝打开
      (=首资源消费前,reviewer F1-a 反例闭合);
    - 无 task_bind 首行的旧式账本(如 R1 耗尽账本)显式拒绝,
      不自动改写或续用;
    - 主 Agent/reviewer/新增测试/全部 runner 共用同一文件
      (fcntl 跨进程一致);
    - 派生总项(synthetic_total)在 reserve 内机械复算。
    """

    def __init__(self, path, task_id: str = POSCTL_R2_TASK_ID,
                 *, limits: dict | None = None) -> None:
        self.task_id = str(task_id)
        reg = task_registry().get(self.task_id)
        if reg is None:
            raise RuntimeError(
                f"未知任务身份 {self.task_id!r}:不在 task_registry"
                f"(已知={sorted(task_registry())});任务账本必须由"
                "已知任务身份显式创建")
        if limits is not None and dict(limits) != reg["limits"]:
            raise RuntimeError(
                f"同任务异预算拒绝打开:{self.task_id} 注册表面 "
                f"{reg['limits']} != 显式 limits {dict(limits)}"
                "(预算面以任务身份绑定,不得按调用方覆写)")
        self._registry_entry = reg
        self._derived_spec = tuple(reg["derived_totals"])
        self._bind_seen: dict | None = None
        super().__init__(Path(path), limits=reg["limits"])
        # 基类构造会把 _derived_spec 重置为 R2 常量;按任务注册表
        # 恢复(打开校验与 reserve 复算必须用本任务面)。
        self._derived_spec = tuple(reg["derived_totals"])
        self.single_caps = dict(reg["single_caps"])
        if self._bind_seen is None:
            raise RuntimeError(
                f"账本无 task_bind 首行,拒绝打开:{self.path}"
                f"(任务 {self.task_id!r};旧式/R1 账本不得自动续用,"
                "任务账本必须由 TaskLedger.create 显式创建)")

    # ------------------------------------------------------------ bind
    @classmethod
    def create(cls, path, task_id: str = POSCTL_R2_TASK_ID,
               *, limits: dict | None = None,
               binding: dict | None = None) -> "TaskLedger":
        """显式创建任务账本(create-only;面 = 注册表面,不可覆写)。"""
        task_id = str(task_id)
        reg = task_registry().get(task_id)
        if reg is None:
            raise RuntimeError(
                f"未知任务身份 {task_id!r}:不在 task_registry"
                f"(已知={sorted(task_registry())})")
        if limits is not None and dict(limits) != reg["limits"]:
            raise RuntimeError(
                f"同任务异预算拒绝创建:{task_id} 注册表面 "
                f"{reg['limits']} != 显式 limits {dict(limits)}"
                "(头部面必须与任务身份一致;测试小额面请用独立"
                "任务身份或以 reserve/commit 预置占用)")
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "event": "task_bind", "task_id": task_id,
            "budget_face": dict(reg["limits"]),
            "budget_source": reg["budget_source"],
            "single_caps": dict(reg["single_caps"]),
            "derived_totals": [
                {"name": n, "parts": list(pp), "cap": c}
                for n, pp, c in reg["derived_totals"]],
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
        return cls(p, task_id)

    def _on_bind_record(self, rec: dict) -> None:
        # 锁内重放全文件:同一 bind 行重复出现视为同一绑定;不同/
        # 多出的 bind 行(任务或面不一致)拒绝。头部面必须与代码
        # 注册表面逐项相等(F1-a:旧实现只核 task_id,缺省重开即
        # 换面继续花)。
        reg = self._registry_entry
        if self._bind_seen is not None:
            same = (
                rec.get("task_id") == self.task_id
                and rec.get("task_id")
                == self._bind_seen.get("task_id")
                and dict(rec.get("budget_face") or {})
                == dict(self._bind_seen.get("budget_face") or {}))
            if not same:
                raise RuntimeError(
                    f"账本含不一致 task_bind 行,拒绝:{self.path}")
            return
        if rec.get("task_id") != self.task_id:
            raise RuntimeError(
                f"task_bind 任务身份不匹配:账本 {rec.get('task_id')!r}"
                f" != 请求 {self.task_id!r};拒绝打开 {self.path}")
        face = dict(rec.get("budget_face") or {})
        if face != dict(self.limits):
            raise RuntimeError(
                f"task_bind 预算面与代码不一致,拒绝打开 "
                f"{self.path}:头部面 {face} != 任务 "
                f"{self.task_id!r} 注册表面 {dict(self.limits)}"
                "(同任务异预算 fail closed;不按代码缺省面扩权)")
        derived_hdr = rec.get("derived_totals")
        if isinstance(derived_hdr, list):
            hdr_spec = tuple(
                (d.get("name"), tuple(d.get("parts") or ()),
                 d.get("cap")) for d in derived_hdr)
            if hdr_spec != tuple(self._derived_spec):
                raise RuntimeError(
                    f"task_bind 派生总项与代码不一致,拒绝打开 "
                    f"{self.path}:头部 {hdr_spec} != 代码 "
                    f"{tuple(self._derived_spec)}")
        self._bind_seen = rec

    def _extra_problems(self, normalized: dict,
                        eff: dict) -> list:
        """派生总项 fail-closed 复算(与预算面一一对应)。"""
        problems = []
        for name, parts, cap in self._derived_spec:
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
