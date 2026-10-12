# -*- coding: utf-8 -*-
"""R1 执行前预算预约账本(RouteC_PositionControl RepairAndCleanup R1)。

修复上轮计量缺陷(SCOPE_AND_BUDGET/FINDINGS R1-D):
- 上轮 UsageLedger 只在 learn 完成后计账、只查 PPO 总额,分项
  (smoke 次数/步数、BC、生成、评估)无执行前控制,smoke 21,516>
  16,384 且 11>8 次成为既成事实。本轮全部动作**先预约后执行**:
  预约时即对"已提交+未闭合预约+本次"做分项与总额 fail-closed
  检查,超限在动作发生前拒绝。
- 失败/中断/未闭合预约保守保留(abandon 不退还),不清零、不挪用。
- JSONL 追加 + fcntl 文件锁(多进程安全);每次操作原子落盘,
  崩溃后重读恢复(未闭合预约继续占用额度)。
- 单次 PPO 步数上限在预约时校验(SB3 rollout 向上取整必须事前
  控制,不得事后把实际步数写小)。

额度(versions.POSCTL_R1_BUDGET,主 Agent/reviewer/新增测试共用
同一账本;旧轮 18 格/容量/时序结果不重跑、旧违规留档不清零)。
"""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from rl_posctl.versions import POSCTL_R1_BUDGET

METRICS = ("ppo_steps", "ppo_learn_attempts", "bc_fits", "bc_epochs",
           "bc_minibatch_updates", "eval_steps", "gen_calls", "episodes")

# 单次上限(预约时校验;键 = 指标,值 = 单次最大)
SINGLE_CAPS = {"ppo_steps": POSCTL_R1_BUDGET["ppo_steps_single"],
               "bc_epochs": POSCTL_R1_BUDGET["bc_epochs"],
               "bc_minibatch_updates":
                   POSCTL_R1_BUDGET["bc_minibatch_updates"]}


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
            if ev == "commit":
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
                    if ev == "commit":
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
        超限 fail closed,超限不得被"忘记"。"""
        out_q = self.outstanding()
        return {k: (self.committed[k] + out_q[k]
                    + self.incidents[k]) for k in METRICS}

    # ------------------------------------------------------------ ops
    def reserve(self, tag: str, **amounts) -> str:
        """动作前预约;分项/总额/单次上限任一超限即拒绝(动作未发生)。

        检查与追加在同一文件锁内完成(跨进程一致:基于最新落盘
        状态检查,不用本进程陈旧快照)。
        """
        bad = [k for k in amounts if k not in METRICS]
        if bad:
            raise ValueError(f"未知计量项 {bad};可用={list(METRICS)}")
        normalized = {k: int(v) for k, v in amounts.items()}
        holder = {}

        def op(fh):
            eff = self.effective()
            problems = []
            for k, v in normalized.items():
                if v < 0:
                    problems.append(f"{k}: 负数 {v}")
                    continue
                cap = SINGLE_CAPS.get(k)
                if cap is not None and v > cap:
                    problems.append(
                        f"{k}: 单次 {v}>{cap}"
                        f"(单次上限,SB3 取整须事前控制)")
                lim = self.limits.get(k)
                if lim is not None and eff[k] + v > lim:
                    problems.append(
                        f"{k}: {eff[k]}+{v}>{lim}"
                        f"(已提交+未闭合+本次;fail closed)")
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

    def commit(self, rid: str, tag: str = "", **actuals) -> None:
        """以实际用量结清预约;实际>预约 = 违规,fail closed。"""
        for k in actuals:
            if k not in METRICS:
                raise ValueError(f"未知计量项 {k}")
        holder = {}

        def op(fh):
            r = self.reservations.get(rid)
            if r is None:
                holder["error"] = RuntimeError(
                    f"未知/已闭合预约 {rid}")
                return
            problems = []
            for k, v in actuals.items():
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
            rec.update({k: int(actuals.get(k, 0)) for k in METRICS})
            self._append_rec(rec, fh)
            for k in METRICS:
                self.committed[k] += int(actuals.get(k, 0))
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
                "over_limit": {k: max(0, self.effective()[k]
                                       - self.limits.get(k, 10**18))
                               for k in METRICS},
                "open_rids": sorted(self.reservations)}

    def incident_backcharge(self, tag: str, note: str = "",
                            **amounts) -> None:
        """事故补记:已发生但未经预约的消耗(诚实记录,非授权)。
        不走 reserve(那会在超限时拒记,使事故不可见);直接追加
        事故行,计入 effective ⇒ 后续预约 fail closed。调用方必须
        同时在报告中披露事故与超限量。"""
        bad = [k for k in amounts if k not in METRICS]
        if bad:
            raise ValueError(f"未知计量项 {bad};可用={list(METRICS)}")
        rec = {"event": "incident_backcharge", "tag": tag,
               "note": note}
        rec.update({k: int(v) for k, v in amounts.items()})
        holder = {}

        def op(fh):
            self._append_rec(rec, fh)
            for k in METRICS:
                self.incidents[k] += int(amounts.get(k, 0))

        self._synced_op(op)
        if "error" in holder:
            raise holder["error"]


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
