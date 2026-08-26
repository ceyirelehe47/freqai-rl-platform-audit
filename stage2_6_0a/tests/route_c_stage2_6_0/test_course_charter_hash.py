"""工作包 B:课程章程规范化、哈希与不匹配拒绝。"""

from __future__ import annotations

import copy

import pytest

from rl_curriculum.charter import (
    CharterHashMismatchError,
    CharterValidationError,
    canonical_charter,
    charter_hash,
    assert_charter_hash,
    validate_charter,
)
from rl_curriculum.probe_charter import audit_probe_charter


def test_charter_validates_and_hashes():
    c = validate_charter(audit_probe_charter())
    h = charter_hash(c)
    assert h.startswith("c-") and len(h) == 66
    # 规范化确定性:键序无关
    shuffled = dict(reversed(list(c.items())))
    assert canonical_charter(shuffled) == canonical_charter(c)
    assert charter_hash(shuffled) == h


def test_charter_hash_changes_on_modification():
    c = validate_charter(audit_probe_charter())
    h0 = charter_hash(c)
    for mutation in (
        lambda d: d["training_parameter_ranges"].__setitem__(
            "drift_bps_range", [19.0, 30.0]),
        lambda d: d.__setitem__("oracle", "oracle_v2"),
        lambda d: d["anti_cheat_exams"].append("new_exam"),
    ):
        d = copy.deepcopy(c)
        mutation(d)
        assert charter_hash(d) != h0, "修改章程后哈希必须变化"


def test_missing_required_field_rejected():
    c = audit_probe_charter()
    for field in ("oracle", "hard_fail_conditions", "spec_versions"):
        d = dict(c)
        d.pop(field)
        with pytest.raises(CharterValidationError):
            validate_charter(d)
    d = dict(c)
    d["teaches"] = ""  # 空内容同样拒绝
    with pytest.raises(CharterValidationError):
        validate_charter(d)


def test_spec_versions_must_match_frozen():
    d = audit_probe_charter()
    d["spec_versions"] = dict(d["spec_versions"])
    d["spec_versions"]["env_core_version"] = "RouteCEnvCore-v0.9"
    with pytest.raises(CharterValidationError, match="env_core_version"):
        validate_charter(d)


def test_evaluator_rejects_mismatched_charter_hash():
    c = validate_charter(audit_probe_charter())
    with pytest.raises(CharterHashMismatchError):
        assert_charter_hash(c, "c-deadbeef")
    assert_charter_hash(c, charter_hash(c))  # 匹配不抛


def test_example_charter_declares_12_anti_cheat_exams():
    c = audit_probe_charter()
    assert len(c["anti_cheat_exams"]) == 12
    assert "null_control" in c["anti_cheat_exams"]
    assert "common_prefix_future_suffix" in c["anti_cheat_exams"]
