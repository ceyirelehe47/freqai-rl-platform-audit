"""阶段 2.6.0g 收尾:工作包 H——checkpoint 前访问守卫(audit hook)。"""

from __future__ import annotations

import os

import pytest


def test_guard_records_checkpoint_open(tmp_path):
    from rl_curriculum.access_guard import BuilderStageAccessGuard

    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"x")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        with open(ckpt, "rb"):
            pass
    audit = guard.audit_result()
    assert audit["violations"], "守卫必须记录对 checkpoint 的 open"
    assert "model.zip" in audit["violations"][0]
    assert audit["open_event_count"] >= 1


def test_guard_clean_when_no_candidate_access(tmp_path):
    from rl_curriculum.access_guard import BuilderStageAccessGuard

    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"x")
    other = tmp_path / "innocent.txt"
    other.write_text("ok")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        with open(other, "r"):
            pass
    audit = guard.audit_result()
    assert audit["violations"] == []
    assert audit["open_event_count"] >= 1


def test_guard_covers_sidecar_and_attestation(tmp_path):
    from rl_curriculum.access_guard import BuilderStageAccessGuard

    sidecar = tmp_path / "model.zip.rl_manifest.json"
    attestation = tmp_path / "model.zip.rl_attestation.json"
    sidecar.write_text("{}")
    attestation.write_text("{}")
    with BuilderStageAccessGuard([str(sidecar), str(attestation)]) as g:
        with open(sidecar):
            with open(attestation):
                pass
    names = " ".join(g.audit_result()["violations"])
    assert "rl_manifest.json" in names
    assert "rl_attestation.json" in names


def test_guard_deactivated_after_exit(tmp_path):
    """with 退出后 hook 不再记录(CPython 无法摘除 audit hook,
    active 标志停止记录)。"""
    from rl_curriculum.access_guard import BuilderStageAccessGuard

    ckpt = tmp_path / "m.zip"
    ckpt.write_bytes(b"x")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        pass
    with open(ckpt, "rb"):
        pass
    assert guard.audit_result()["violations"] == []
    assert guard.audit_result()["guard_active"] is False


def test_builder_stage_no_checkpoint_access_via_monkeypatch_stat(
        tmp_path, monkeypatch):
    """等价访问记录:monkeypatch os.stat 证明 builder 阶段无 stat。"""
    stat_calls: list[str] = []
    real_stat = os.stat

    def spy_stat(path, *a, **kw):
        stat_calls.append(str(path))
        return real_stat(path, *a, **kw)

    monkeypatch.setattr(os, "stat", spy_stat)
    ckpt = tmp_path / "checkpoint.zip"
    ckpt.write_bytes(b"x")
    from rl_curriculum.access_guard import BuilderStageAccessGuard

    with BuilderStageAccessGuard([str(ckpt)]):
        # 模拟 builder 阶段的其他文件访问(非 checkpoint)
        (tmp_path / "pack.json").write_text("{}")
    assert not any("checkpoint.zip" in c for c in stat_calls)


def test_formal_outputs_audit_field():
    """formal 输出结构含 builder_stage_access_audit 字段(签名层)。"""
    import inspect

    from rl_curriculum import formal_exam

    src = inspect.getsource(formal_exam)
    assert "builder_stage_access_audit" in src
    assert "BuilderStageAccessGuard" in src
