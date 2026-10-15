# -*- coding: utf-8 -*-
"""P0 实验登记(append-only 事件日志 + 课程状态表)。

rev2(审阅 NO-GO 修正版,2026-10-15):

- **损坏即停写**:日志存在 torn(半写/无效 JSON)行时,一切自动
  写入立即拒绝(RegistryError)并保留现场,由人工恢复;绝不
  "补换行自愈后继续接受同 ID"。
- **保留字段不可覆盖**:settled/failed 的 payload 与 intent 的
  extra 中出现 event/experiment_id/plan_digest/utc 等保留键
  即拒绝(防止 payload 伪装成新事件/二次 settle)。
- 全局锁文件 + fcntl.flock 独占:读-查-追加-fsync 同一临界区。
- settled 每实验至多一行,须引用既有 intent(experiment_id +
  plan_digest 双匹配);failed 为终态(不自动重试)。
- plan 哈希 = 规范化 JSON(键排序/紧凑分隔符)SHA-256;不保证
  跨不同路径/日期全面去重。
- 课程状态表:read-SHA→校验→改写→原子 replace 全程持锁;唯一
  临时文件(tempfile.mkstemp 同目录);stage 白名单校验;首版
  仅允许 course="c1";GRADUATED 须人工批准引用;历史追加。
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPES = ("intent", "settled", "failed", "stage_change",
               "backfill")

#: 任何写入 payload/extra 里出现这些键 = 试图覆盖保留字段
RESERVED_EVENT_KEYS = frozenset({
    "event", "experiment_id", "plan_digest", "utc", "_line"})

#: 课程状态白名单
VALID_STAGES = ("NOT_STARTED", "IN_PROGRESS", "NOT_GRADUATED",
                "GRADUATED")

#: 首版状态表只承载 c1
STATUS_COURSES = ("c1",)


class RegistryError(RuntimeError):
    """登记不变量被违反(重复/未知/损坏/保留字段覆盖等)。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True,
                      separators=(",", ":"),
                      ensure_ascii=False)


def plan_digest(plan: dict) -> str:
    return hashlib.sha256(
        canonical_json(plan).encode("utf-8")).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_no_reserved_keys(payload: dict, where: str) -> None:
    hit = sorted(RESERVED_EVENT_KEYS & set(payload or {}))
    if hit:
        raise RegistryError(
            f"{where}: payload must not override reserved "
            f"keys {hit}")


class Registry:
    """append-only 实验事件日志(flock 互斥,一事件一行)。"""

    def __init__(self, root) -> None:
        self.root = Path(root)
        self.jsonl = self.root / "registry.jsonl"
        self.lock_path = self.root / ".registry.lock"
        self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        fd = os.open(str(self.lock_path),
                     os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _append_line(self, line: str) -> None:
        """追加一行;非空文件末字节非 LF 一律拒写(防粘连)。

        已复现边界:合法 intent JSON 仅缺末尾换行时,直接 append
        会把两条 JSON 粘成一条废行。此处拒绝写入并原样保留
        现场,不自动补换行(修复动作必须人工显式进行)。
        """
        if self.jsonl.exists() and (
                self.jsonl.stat().st_size > 0):
            with open(self.jsonl, "rb") as fh:
                fh.seek(-1, 2)
                last = fh.read(1)
            if last != b"\n":
                raise RegistryError(
                    "registry last line unterminated "
                    "(no trailing LF); refusing append "
                    "(would glue JSON lines); file "
                    "preserved as-is")
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

    def corrupt_lines(self) -> list:
        """torn 行清单(空=日志完好)。"""
        return [e for e in self.iter_events()
                if e.get("event") == "torn"]

    def _guard_writable(self):
        """损坏即停:存在 torn 行时拒绝任何自动写入。"""
        torn = self.corrupt_lines()
        if torn:
            raise RegistryError(
                "registry corrupt: torn line(s) "
                f"{[t['torn_line'] for t in torn]}; auto "
                "writes disabled, manual recovery required")

    def find_intent(self, experiment_id, digest):
        for ev in self.iter_events():
            if (ev.get("event") == "intent"
                    and ev.get("experiment_id") == experiment_id
                    and ev.get("plan_digest") == digest):
                return ev
        return None

    # ---- 写入侧(全部持锁 + 完好性守卫) ------------------------
    def register_intent(self, plan: dict, *, mode: str,
                        extra: dict | None = None) -> dict:
        digest = plan_digest(plan)
        experiment_id = plan["experiment_id_hint"]
        _check_no_reserved_keys(extra or {}, "intent extra")
        with self._locked():
            self._guard_writable()
            for ev in self.iter_events():
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
        _check_no_reserved_keys(payload, kind)
        with self._locked():
            self._guard_writable()
            intent = None
            settled_seen = False
            failed_seen = False
            for ev in self.iter_events():
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
        return self._record_terminal(
            "settled", experiment_id, digest, payload)

    def record_failed(self, experiment_id, digest,
                      payload: dict) -> dict:
        return self._record_terminal(
            "failed", experiment_id, digest, payload)


class CurriculumStatus:
    """课程状态表:先表后跑;GRADUATED 须人工批准引用。

    rev2:read-SHA→校验→改写→原子 replace 全程持锁(同一把
    .curriculum.lock);唯一临时文件(tempfile.mkstemp 同目录,
    用后即删);stage/course 白名单;历史追加不删除。
    """

    def __init__(self, registry_root) -> None:
        self.root = Path(registry_root)
        self.path = self.root / "curriculum_status.json"
        self.lock_path = self.root / ".curriculum.lock"

    def _load(self) -> dict:
        if not self.path.exists():
            return {"rows": [], "history": []}
        return json.loads(
            self.path.read_text(encoding="utf-8"))

    @contextmanager
    def _locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_path),
                     os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

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
        if not isinstance(arm, str) or not arm:
            raise RegistryError("arm must be non-empty str")
        if course not in STATUS_COURSES:
            raise RegistryError(
                f"course {course!r} not allowed in status "
                f"table (first version: {STATUS_COURSES})")
        if stage not in VALID_STAGES:
            raise RegistryError(
                f"unknown stage {stage!r}; valid: "
                f"{VALID_STAGES}")
        if stage == "GRADUATED":
            if not (promotion and promotion.get("approved_by")
                    and promotion.get("approval_ref")):
                raise RegistryError(
                    "GRADUATED requires promotion with "
                    "approved_by + approval_ref (manual "
                    "approval; no auto promotion)")
        with self._locked():
            if self.path.exists():
                current = sha256_file(self.path)
                if expected_sha256 != current:
                    raise RegistryError(
                        f"stale status file: expected "
                        f"{expected_sha256!r}, on-disk "
                        f"{current!r}")
            elif expected_sha256 is not None:
                raise RegistryError(
                    "status file does not exist; "
                    "expected_sha256 must be None")
            data = self._load()
            old_row = self.row(arm, course)
            new_row = {"arm": arm, "course": course,
                       "stage": stage,
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
            # 唯一临时文件(同目录,原子 replace)
            tmp_fd, tmp_name = tempfile.mkstemp(
                dir=str(self.path.parent),
                prefix=".curriculum_status.",
                suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w",
                               encoding="utf-8") as fh:
                    fh.write(canonical_json(data))
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, str(self.path))
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            return new_row
