"""阶段 2.6.0a 工作包 H1:隐藏考试 attempt registry(可审计 + 幂等)。

记录每次正式尝试:pack hash、checkpoint hash、attempt id、时间、
状态、是否详细公开、是否退休。相同 (checkpoint, pack) 的重复运行:
- 返回同一结果或标记为幂等重试(不产生新的可探测信息);
- 超过可配置的尝试上限时拒绝(明确策略,所有提交可审计)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

ATTEMPT_REGISTRY_FORMAT = "attempt-registry-v1"


class AttemptLimitExceeded(RuntimeError):
    """相同 (checkpoint, pack) 的尝试次数超过策略上限(fail closed)。"""


class AttemptRegistry:
    """attempt 注册表(JSON 持久化;每次写入即落盘)。"""

    def __init__(self, path, *, max_attempts_per_checkpoint_pack: int | None = None):
        self.path = Path(path)
        self.max_attempts_per_checkpoint_pack = max_attempts_per_checkpoint_pack
        if self.path.is_file():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("format") != ATTEMPT_REGISTRY_FORMAT:
                raise RuntimeError(
                    f"attempt registry 格式 {data.get('format')!r} != "
                    f"{ATTEMPT_REGISTRY_FORMAT!r}:{self.path}")
            self._attempts: list[dict[str, Any]] = list(data.get("attempts") or [])
        else:
            self._attempts = []

    # ------------------------------------------------------------------ 查询
    def attempts_for(self, pack_hash: str, checkpoint_hash: str) -> list[dict[str, Any]]:
        return [
            a for a in self._attempts
            if a.get("pack_hash") == pack_hash
            and a.get("checkpoint_hash") == checkpoint_hash
        ]

    def previous_completed(self, pack_hash: str,
                           checkpoint_hash: str) -> dict[str, Any] | None:
        """最近一次已完成的同 (checkpoint, pack) 尝试(幂等重试依据)。"""
        for a in reversed(self._attempts):
            if (a.get("pack_hash") == pack_hash
                    and a.get("checkpoint_hash") == checkpoint_hash
                    and a.get("completed")):
                return a
        return None

    def entries(self) -> list[dict[str, Any]]:
        return [dict(a) for a in self._attempts]

    # ------------------------------------------------------------------ 写入
    def _new_attempt_id(self, pack_hash: str, checkpoint_hash: str) -> str:
        seq = len(self._attempts)
        digest = hashlib.sha256(
            f"{pack_hash}|{checkpoint_hash}|{seq}".encode("utf-8")
        ).hexdigest()[:12]
        return f"a-{digest}"

    def check_attempt_allowed(self, pack_hash: str, checkpoint_hash: str) -> None:
        if self.max_attempts_per_checkpoint_pack is None:
            return
        n = len(self.attempts_for(pack_hash, checkpoint_hash))
        if n >= self.max_attempts_per_checkpoint_pack:
            raise AttemptLimitExceeded(
                f"相同 (checkpoint, pack) 已提交 {n} 次,超过上限 "
                f"{self.max_attempts_per_checkpoint_pack}"
                f"(attempt policy 明确拒绝,不静默放行)")

    def record_attempt(
        self, *, pack_hash: str, checkpoint_hash: str, status: str,
        completed: bool = True, detailed_disclosed: bool = False,
        pack_retired_after: bool = False, idempotent_retry_of: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.check_attempt_allowed(pack_hash, checkpoint_hash)
        record = {
            "attempt_id": self._new_attempt_id(pack_hash, checkpoint_hash),
            "pack_hash": pack_hash,
            "checkpoint_hash": checkpoint_hash,
            "recorded_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "status": status,
            "completed": bool(completed),
            "detailed_disclosed": bool(detailed_disclosed),
            "pack_retired_after": bool(pack_retired_after),
            "idempotent_retry_of": idempotent_retry_of,
            "extra": dict(extra or {}),
        }
        self._attempts.append(record)
        self._flush()
        return dict(record)

    def _flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"format": ATTEMPT_REGISTRY_FORMAT,
                 "max_attempts_per_checkpoint_pack": self.max_attempts_per_checkpoint_pack,
                 "attempts": self._attempts},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
