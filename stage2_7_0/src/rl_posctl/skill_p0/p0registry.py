# -*- coding: utf-8 -*-
"""P0 实验登记(append-only 事件日志 + 课程状态表)。

批准版设计(2026-10-15,route-c-p0-continuation 分支):

- 一事件一行(JSONL)。事件类型:intent / settled / failed /
  stage_change / backfill;torn(半写行)只由读取侧合成,不可写占位。
- 全局锁文件 + fcntl.flock 独占:读-查-追加-fsync 在同一临界区内
  完成,杜绝"先查后 append"竞态(跨进程互斥)。
- settled 每实验至多一行,且必须引用既有 intent(experiment_id +
  plan_digest 双匹配);重复 settle、未知 intent 的 settle、
  failed 之后再 settle(失败即终态,不自动重试)均拒绝。
- intent 后失败写 failed 事件(带真实计数);保留现场、不删除、
  不冒充 settled。半写(torn)行在迭代时显式标记并保留原始片段,
  torn 行不可充当任何有效事件。
- plan 哈希 = 规范化 JSON(键排序/紧凑分隔符/ensure_ascii=False)
  的 SHA-256。显式声明:不保证跨不同路径/日期的全面去重——
  同一实验意图以不同路径或日期写入即视为不同计划记录。
- 课程状态表(curriculum_status.json):GRADUATED 必须携带人工
  批准引用(promotion.approved_by/approval_ref/utc);状态变更
  以旧文件 SHA 证明 + 历史行追加(永不删除历史)。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = ("intent", "settled", "failed", "stage_change",
               "backfill")


class RegistryError(RuntimeError):
    """登记不变量被违反(重复/未知/半写冒充等)。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def canonical_json(obj) -> str:
    """规范化 JSON 文本(排序键/紧凑分隔符)。"""
    return json.dumps(obj, sort_keys=True,
                      separators=(",", ":"),
                      ensure_ascii=False)


def plan_digest(plan: dict) -> str:
    """计划规范化摘要。见模块 docstring 的去重边界声明。"""
    return hashlib.sha256(
        canonical_json(plan).encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()



class Registry:
    """append-only 实验事件日志(flock 互斥,一事件一行)。"""

    def __init__(self, root) -> None:
        self.root = Path(root)
        self.jsonl = self.root / "registry.jsonl"
        self.lock_path = self.root / ".registry.lock"
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        """全局独占锁:持锁期间完成 读-查-追加-fsync。"""
        fd = os.open(str(self.lock_path),
                     os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _append_line(self, line: str) -> None:
        """追加一行;若文件尾无换行(前次半写)先补边界换行。

        torn 片段因此保持独立行,后续事件不被粘连污染;
        torn 行本身仍由读取侧标记,不冒充任何有效事件。
        """
        if self.jsonl.exists():
            with open(self.jsonl, "r+b") as probe:
                size = probe.seek(0, 2)
                if size > 0:
                    probe.seek(size - 1)
                    if probe.read(1) != b"\n":
                        probe.seek(0, 2)
                        probe.write(b"\n")
        with open(self.jsonl, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # ---- 读取侧 -------------------------------------------------
    def iter_events(self):
        """逐行产出事件;无效 JSON 行产出 torn(保留原始片段)。"""
        if not self.jsonl.exists():
            return
        with open(self.jsonl, "r", encoding="utf-8") as fh:
            for line_no, raw in enumerate(fh, 1):
                text = raw.rstrip("\n")
                if not text.strip():
                    continue
                try:
                    ev = json.loads(text)
                except ValueError:
                    yield {"event": "torn", "torn_line": line_no,
                           "raw": text[:512]}
                    continue
                ev["_line"] = line_no
                yield ev

    def _events_under_lock(self):
        return list(self.iter_events())

    def find_intent(self, experiment_id, digest):
        for ev in self.iter_events():
            if (ev.get("event") == "intent"
                    and ev.get("experiment_id") == experiment_id
                    and ev.get("plan_digest") == digest):
                return ev
        return None

    # ---- 写入侧(全部持锁) --------------------------------------
    def register_intent(self, plan: dict, *, mode: str,
                        extra: dict | None = None) -> dict:
        digest = plan_digest(plan)
        experiment_id = plan["experiment_id_hint"]
        with self._locked():
            events = self._events_under_lock()
            for ev in events:
                if ev.get("event") != "intent":
                    continue
                if ev.get("plan_digest") == digest:
                    raise RegistryError(
                        "duplicate intent: same plan_digest "
                        f"already registered at line "
                        f"{ev.get('_line')}")
                if ev.get("experiment_id") == experiment_id:
                    raise RegistryError(
                        "duplicate intent: experiment_id "
                        f"{experiment_id!r} already used at "
                        f"line {ev.get('_line')}")
            rec = {
                "event": "intent",
                "experiment_id": experiment_id,
                "plan_digest": digest,
                "mode": str(mode),
                "source_checkpoint": plan["source"][
                    "checkpoint"],
                "source_checkpoint_sha256": plan["source"][
                    "checkpoint_sha256"],
                "base_model_seed_in_zip": plan["source"][
                    "base_model_seed_in_zip"],
                "new_random_stream_seed": plan[
                    "random_stream"]["new_seed"],
                "append_steps": plan["steps"]["append_steps"],
                "cumulative_end": plan["steps"]["cumulative_end"],
                "course": plan["course"]["course"],
                "bank_sha256": plan["course"].get(
                    "bank_sha256"),
                "feature_names": plan["course"][
                    "feature_names"],
                "budget": dict(plan["budget"]),
                "eval_scope": dict(plan["eval_scope"]),
                "evidence_root": plan["evidence"]["root"],
                "utc": utc_now(),
            }
            if extra:
                rec.update(extra)
            self._append_line(canonical_json(rec))
            return rec

    def _record_terminal(self, kind: str, experiment_id: str,
                         digest: str, payload: dict) -> dict:
        with self._locked():
            intent = None
            settled_seen = False
            failed_seen = False
            for ev in self._events_under_lock():
                if ev.get("event") == "intent":
                    if (ev.get("experiment_id") == experiment_id
                            and ev.get("plan_digest") == digest):
                        intent = ev
                elif ev.get("event") == "settled":
                    if ev.get("experiment_id") == experiment_id:
                        settled_seen = True
                elif ev.get("event") == "failed":
                    if ev.get("experiment_id") == experiment_id:
                        failed_seen = True
            if intent is None:
                raise RegistryError(
                    f"{kind} rejected: no matching intent for "
                    f"{experiment_id!r}")
            if settled_seen:
                raise RegistryError(
                    f"{kind} rejected: settled already exists "
                    f"for {experiment_id!r}")
            if failed_seen:
                raise RegistryError(
                    f"{kind} rejected: failed is terminal for "
                    f"{experiment_id!r} (no auto retry)")
            rec = {"event": kind,
                   "experiment_id": experiment_id,
                   "plan_digest": digest,
                   "utc": utc_now()}
            rec.update(payload)
            self._append_line(canonical_json(rec))
            return rec

    def record_settled(self, experiment_id, digest,
                       payload: dict) -> dict:
        """唯一成功实结;半写行(解析失败)不构成 settled。"""
        return self._record_terminal(
            "settled", experiment_id, digest, payload)

    def record_failed(self, experiment_id, digest,
                      payload: dict) -> dict:
        """失败实结(终态):真实计数,不删除、不重试。"""
        return self._record_terminal(
            "failed", experiment_id, digest, payload)


class CurriculumStatus:
    """课程状态表:先表后跑;GRADUATED 须人工批准引用。"""

    def __init__(self, registry_root) -> None:
        self.path = Path(registry_root) / "curriculum_status.json"

    def _load(self) -> dict:
        if not self.path.exists():
            return {"rows": [], "history": []}
        return json.loads(
            self.path.read_text(encoding="utf-8"))

    def row(self, arm: str, course: str) -> dict | None:
        for r in self._load()["rows"]:
            if r.get("arm") == arm and r.get("course") == course:
                return r
        return None

    def graduated(self, arm: str, course: str) -> bool:
        r = self.row(arm, course)
        if not r or r.get("stage") != "GRADUATED":
            return False
        promo = r.get("promotion") or {}
        return bool(promo.get("approved_by")
                    and promo.get("approval_ref"))

    def set_stage(self, arm: str, course: str, stage: str,
                  *, promotion: dict | None = None,
                  expected_sha256: str | None = None) -> dict:
        """状态变更:旧文件 SHA 证明 + 历史追加,不删历史。

        expected_sha256 为当前文件 SHA(文件不存在时必须传 None
        且文件确实不存在);防止基于过期读的丢失更新。
        """
        if stage == "GRADUATED":
            if not (promotion and promotion.get("approved_by")
                    and promotion.get("approval_ref")):
                raise RegistryError(
                    "GRADUATED requires promotion with "
                    "approved_by + approval_ref (manual "
                    "approval; no auto promotion)")
        if self.path.exists():
            current = sha256_file(self.path)
            if expected_sha256 != current:
                raise RegistryError(
                    f"stale status file: expected "
                    f"{expected_sha256!r}, on-disk "
                    f"{current!r}")
        elif expected_sha256 is not None:
            raise RegistryError(
                "status file does not exist; expected_sha256 "
                "must be None")
        data = self._load()
        old_row = self.row(arm, course)
        new_row = {"arm": arm, "course": course, "stage": stage,
                   "promotion": promotion,
                   "utc": utc_now()}
        rows = [r for r in data["rows"]
                if not (r.get("arm") == arm
                        and r.get("course") == course)]
        rows.append(new_row)
        data["rows"] = rows
        data["history"].append({
            "arm": arm, "course": course,
            "from": (old_row or {}).get("stage"),
            "to": stage, "utc": utc_now()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(canonical_json(data), encoding="utf-8")
        os.replace(str(tmp), str(self.path))
        return new_row
