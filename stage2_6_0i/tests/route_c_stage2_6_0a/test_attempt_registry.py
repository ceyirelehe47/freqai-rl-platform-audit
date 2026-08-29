"""工作包 H1:attempt registry(可审计 + 幂等 + 上限策略)。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.attempt_registry import (
    AttemptLimitExceeded,
    AttemptRegistry,
)


def test_record_and_query(tmp_path):
    reg = AttemptRegistry(tmp_path / "attempts.json")
    a1 = reg.record_attempt(pack_hash="p-1", checkpoint_hash="c-1",
                            status="FAIL")
    assert a1["attempt_id"].startswith("a-")
    assert a1["status"] == "FAIL"
    assert len(reg.attempts_for("p-1", "c-1")) == 1
    assert reg.previous_completed("p-1", "c-1")["attempt_id"] == \
        a1["attempt_id"]


def test_persistence_roundtrip(tmp_path):
    reg = AttemptRegistry(tmp_path / "attempts.json")
    reg.record_attempt(pack_hash="p", checkpoint_hash="c", status="PASS")
    reg2 = AttemptRegistry(tmp_path / "attempts.json")
    assert len(reg2.entries()) == 1
    assert reg2.entries()[0]["status"] == "PASS"


def test_audit_fields_present(tmp_path):
    reg = AttemptRegistry(tmp_path / "a.json")
    rec = reg.record_attempt(
        pack_hash="p", checkpoint_hash="c", status="PASS",
        detailed_disclosed=True, pack_retired_after=True,
        idempotent_retry_of=None)
    for field in ("attempt_id", "pack_hash", "checkpoint_hash",
                  "recorded_utc", "status", "completed",
                  "detailed_disclosed", "pack_retired_after"):
        assert field in rec


def test_limit_policy_enforced(tmp_path):
    reg = AttemptRegistry(tmp_path / "a.json", max_attempts_per_checkpoint_pack=2)
    reg.record_attempt(pack_hash="p", checkpoint_hash="c", status="FAIL")
    reg.record_attempt(pack_hash="p", checkpoint_hash="c", status="FAIL")
    with pytest.raises(AttemptLimitExceeded, match="上限"):
        reg.record_attempt(pack_hash="p", checkpoint_hash="c", status="FAIL")
    # 其他 checkpoint 不受影响
    reg.record_attempt(pack_hash="p", checkpoint_hash="c2", status="FAIL")


def test_unlimited_by_default(tmp_path):
    reg = AttemptRegistry(tmp_path / "a.json")
    for i in range(5):
        reg.record_attempt(pack_hash="p", checkpoint_hash="c",
                           status="FAIL")
    assert len(reg.entries()) == 5


def test_bad_format_rejected(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps({"format": "other", "attempts": []}))
    with pytest.raises(RuntimeError, match="格式"):
        AttemptRegistry(p)
