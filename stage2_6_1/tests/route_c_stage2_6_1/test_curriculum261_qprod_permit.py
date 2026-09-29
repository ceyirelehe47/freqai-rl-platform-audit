# -*- coding: utf-8 -*-
"""QProd 许可层测试(A04:验证/一次性消费/重放/错层错根错SHA/零叶调用)。

零原生生成;许可由测试内构造(模拟隔离 test authority 目录)——
被验 src 模块不得含签发函数。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, build_engineering_context,
)
import rl_curriculum.curriculum261_qprod_permit as permit_mod
from rl_curriculum.curriculum261_qprod_permit import (
    LivePermitToken, acquire_live_permit, consume_permit,
    permit_already_consumed, permit_digest, validate_permit,
)

AUTHORITY_ID = "test-authority-001"


def _authority(tmp_path: Path) -> Path:
    adir = tmp_path / "authority"
    adir.mkdir(parents=True, exist_ok=True)
    (adir / "authority_identity.json").write_text(json.dumps({
        "format": "cur261-qprod-authority-identity-v1",
        "authority_id": AUTHORITY_ID}), encoding="utf-8")
    return adir


def _ctx(tmp_path: Path, *, level="level_b", iteration="i1"):
    return build_engineering_context(
        level=level, iteration_id=iteration, base_dir=tmp_path / "base",
        code_freeze_sha="sha-123",
        authority_dir=_authority(tmp_path))


def _write_permit(adir: Path, ctx, **over):
    permit = {
        "format": "cur261-qprod-permit-v1",
        "permit_id": "p-001",
        "task_level": ctx.level,
        "iteration_id": ctx.iteration_id,
        "code_freeze_sha": ctx.code_freeze_sha,
        "artifact_root": str(ctx.artifact_root),
        "state_root": str(ctx.state_root),
        "preregistered_input_scope": {
            "namespaces": ["cue_qprod_v1_c01_model",
                           "cue_qprod_v1_c01_validation"]},
        "quota": {"max_leaf_calls_per_coordinate": 320,
                  "max_successful_episodes_total": 128,
                  "mc_events_per_coordinate": 4096,
                  "max_native_executions": 2},
        "issuer": {"kind": "engineering_test_authority",
                   "authority_id": AUTHORITY_ID},
        "issued_utc": "2026-09-30T00:00:00Z",
    }
    permit.update(over)
    permit["permit_digest"] = permit_digest(permit)
    path = Path(adir) / "permit.json"
    path.write_text(json.dumps(permit, indent=2), encoding="utf-8")
    return path, permit


def test_src_module_has_no_issue_function():
    fns = [n for n in dir(permit_mod)
           if "issue" in n.lower() and callable(getattr(permit_mod, n))]
    assert fns == [], f"被验包不得含签发能力: {fns}"


def test_permit_outside_authority_dir_rejected(tmp_path):
    ctx = _ctx(tmp_path)
    path, _ = _write_permit(tmp_path / "authority", ctx)
    outside = tmp_path / "elsewhere" / "permit.json"
    outside.parent.mkdir()
    outside.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(QProdContextError, match="authority 目录"):
        validate_permit(outside, context=ctx)


@pytest.mark.parametrize("over,match", [
    ({"code_freeze_sha": "sha-OTHER"}, "错 SHA"),
    ({"iteration_id": "other"}, "迭代"),
    ({"state_root": "/tmp/other"}, "错根"),
    ({"task_level": "level_a"}, "错层"),
])
def test_permit_field_mismatches_rejected(tmp_path, over, match):
    ctx = _ctx(tmp_path)
    path, _ = _write_permit(tmp_path / "authority", ctx, **over)
    with pytest.raises(QProdContextError, match=match):
        validate_permit(path, context=ctx)


def test_permit_digest_tamper_rejected(tmp_path):
    ctx = _ctx(tmp_path)
    path, permit = _write_permit(tmp_path / "authority", ctx)
    permit["quota"]["max_leaf_calls_per_coordinate"] = 999999
    (tmp_path / "authority" / "permit.json").write_text(
        json.dumps(permit, indent=2), encoding="utf-8")
    with pytest.raises(QProdContextError, match="digest 失配"):
        validate_permit(path, context=ctx)


def test_permit_unknown_authority_rejected(tmp_path):
    ctx = _ctx(tmp_path)
    path, _ = _write_permit(
        tmp_path / "authority", ctx,
        issuer={"kind": "engineering_test_authority",
                "authority_id": "UNKNOWN"})
    with pytest.raises(QProdContextError, match="authority 身份"):
        validate_permit(path, context=ctx)


def test_permit_scope_namespace_guard(tmp_path):
    ctx = _ctx(tmp_path)
    limited = type(ctx)(**{
        **{f: getattr(ctx, f) for f in (
            "level", "iteration_id", "profile", "artifact_root",
            "state_root", "code_freeze_sha", "plan_identity",
            "permit_path", "authority_dir")},
        "namespaces_scope": ("cue_qprod_v1_c01_model",)})
    path, _ = _write_permit(tmp_path / "authority", limited)
    with pytest.raises(QProdContextError, match="未声明 namespace"):
        validate_permit(path, context=limited)


def test_consume_once_then_replay_rejected(tmp_path):
    ctx = _ctx(tmp_path)
    path, _ = _write_permit(tmp_path / "authority", ctx)
    rec = consume_permit(path, context=ctx)
    assert rec["permit_id"] == "p-001"
    assert permit_already_consumed(ctx, "p-001")
    with pytest.raises(QProdContextError, match="重放拒绝"):
        consume_permit(path, context=ctx)


def test_level_isolated_consumption_records(tmp_path):
    """A/B 各自独立消费记录:B 的消费不写 A 的 state root。"""
    a = _ctx(tmp_path, level="level_a", iteration="ia")
    b = _ctx(tmp_path, level="level_b", iteration="ib")
    pa, _ = _write_permit(tmp_path / "authority", a, permit_id="pa",
                          task_level="level_a", iteration_id="ia")
    consume_permit(pa, context=a)
    assert (a.state_root / "qprod_permit_consumed.jsonl").is_file()
    assert not (b.state_root / "qprod_permit_consumed.jsonl").exists()


def test_live_token_quota_visible(tmp_path):
    ctx = _ctx(tmp_path)
    path, _ = _write_permit(tmp_path / "authority", ctx)
    token = acquire_live_permit(path, context=ctx)
    assert isinstance(token, LivePermitToken)
    assert token.quota["mc_events_per_coordinate"] == 4096
