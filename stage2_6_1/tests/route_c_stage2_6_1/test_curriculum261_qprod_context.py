# -*- coding: utf-8 -*-
"""QProd 上下文层测试(A02:根加固/A-B 隔离/旧根零写/会话治理)。

零原生生成:全部用隔离 tmp 目录与手工配置;不触碰部署历史根。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_qprod_context import (
    QPROD_DEPLOY_CONFIG_NAME, QProdContextError, QProdOwnershipError,
    QProdRunSession, build_engineering_context, harden_root,
    load_deploy_config, protected_old_roots, resolve_formal_roots,
)


def test_harden_root_rejects_relative_and_dotdot(tmp_path):
    with pytest.raises(QProdContextError, match="绝对路径"):
        harden_root("relative/dir", label="t")
    with pytest.raises(QProdContextError, match=r"\.\."):
        harden_root(str(tmp_path / "a" / ".." / "b"), label="t")


def test_harden_root_rejects_protected_old_roots():
    for prot in protected_old_roots():
        with pytest.raises(QProdContextError, match="受保护历史根"):
            harden_root(prot / "new_subdir", label="t", create=False)
        # 别名:symlink 指向保护根同样拒绝(realpath 归一)
        with pytest.raises((QProdContextError, OSError)):
            harden_root(prot, label="t", create=False)


def test_harden_root_symlink_escape(tmp_path):
    import os as _os

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    _os.symlink(real, link)
    # symlink 本身解析到 tmp 内合法目录——通过,但返回真实路径
    out = harden_root(link / "sub", label="t")
    assert str(out).startswith(str(real))


def test_formal_roots_reject_env_redirect(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_QPROD_STATE_ROOT", "/tmp/evil")
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / QPROD_DEPLOY_CONFIG_NAME).write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1", "mode":
        "formal_ready",
        "formal_roots": {"it1": {
            "artifact_root": str(tmp_path / "art"),
            "state_root": str(tmp_path / "state")}}}), encoding="utf-8")
    with pytest.raises(QProdContextError, match="环境重定向"):
        resolve_formal_roots(deploy, level="level_a", iteration_id="it1")


def test_formal_roots_fail_closed_without_config(tmp_path):
    with pytest.raises(QProdContextError, match="受信任部署配置缺失"):
        resolve_formal_roots(tmp_path, level="level_a", iteration_id="it1")
    cfg_dir = tmp_path / "d"
    cfg_dir.mkdir()
    (cfg_dir / QPROD_DEPLOY_CONFIG_NAME).write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1",
        "mode": "sandbox", "formal_roots": {}}), encoding="utf-8")
    with pytest.raises(QProdContextError, match="未批准正式运行"):
        resolve_formal_roots(cfg_dir, level="level_b",
                             iteration_id="it1")


def test_engineering_context_rejected_in_formal_ready_deploy(tmp_path):
    deploy = tmp_path / "deploy"
    deploy.mkdir()
    (deploy / QPROD_DEPLOY_CONFIG_NAME).write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1",
        "mode": "formal_ready", "formal_roots": {}}), encoding="utf-8")
    authority = tmp_path / "authority"
    authority.mkdir()
    (authority / "authority_identity.json").write_text("{}", encoding="utf-8")
    with pytest.raises(QProdContextError,
                       match="工程/test root 注入入口在正式部署拒绝"):
        build_engineering_context(
            level="level_a", iteration_id="i1",
            base_dir=tmp_path / "base",
            code_freeze_sha="sha", authority_dir=authority,
            deploy_root_for_guard=deploy)


def test_level_a_b_roots_and_authority_isolation(tmp_path):
    authority = tmp_path / "authority"
    authority.mkdir()
    (authority / "authority_identity.json").write_text("{}", encoding="utf-8")
    a = build_engineering_context(
        level="level_a", iteration_id="i1", base_dir=tmp_path / "b",
        code_freeze_sha="sha", authority_dir=authority)
    b = build_engineering_context(
        level="level_b", iteration_id="i1", base_dir=tmp_path / "b",
        code_freeze_sha="sha", authority_dir=authority)
    # A/B 状态根/产物根完全分离;共享的只是代码
    assert a.state_root != b.state_root
    assert a.artifact_root != b.artifact_root
    assert "level_a" in str(a.state_root)
    assert "level_b" in str(b.state_root)
    # authority 不得在自身 state/artifact 内(自授权拒绝)
    with pytest.raises(QProdContextError, match="自授权拒绝"):
        build_engineering_context(
            level="level_a", iteration_id="i2",
            base_dir=tmp_path / "b2", code_freeze_sha="sha",
            authority_dir=(tmp_path / "b2" / "qprod_level_a_i2" /
                           "state"))


def test_context_payload_same_check(tmp_path):
    authority = tmp_path / "authority"
    authority.mkdir()
    (authority / "authority_identity.json").write_text("{}", encoding="utf-8")
    a = build_engineering_context(
        level="level_b", iteration_id="i1", base_dir=tmp_path / "b",
        code_freeze_sha="sha", authority_dir=authority)
    b = build_engineering_context(
        level="level_b", iteration_id="i1", base_dir=tmp_path / "b",
        code_freeze_sha="sha", authority_dir=authority)
    a.ensure_same(b, what="test")
    c = build_engineering_context(
        level="level_b", iteration_id="other", base_dir=tmp_path / "b",
        code_freeze_sha="sha", authority_dir=authority)
    with pytest.raises(QProdContextError, match="上下文漂移"):
        a.ensure_same(c, what="test")


class TestQProdRunSession:
    def test_acquire_release_and_no_reentry_after_terminal(self, tmp_path):
        state = tmp_path / "state"
        s1 = QProdRunSession(state, level="level_a", iteration_id="i")
        s1.acquire({"entry": "t"})
        s1.record_terminal(status="completed", verdict="PASS",
                           plan_digest="d")
        s1.release()
        s2 = QProdRunSession(state, level="level_a", iteration_id="i")
        with pytest.raises(QProdOwnershipError, match="终态不可重入"):
            s2.acquire({})
        rej = list((state / "rejected_requests").glob(
            "*terminal_state_no_reentry*"))
        assert rej, "拒绝必须留独立 request 证据"

    def test_no_takeover_after_owner_death(self, tmp_path):
        state = tmp_path / "state"
        s1 = QProdRunSession(state, level="level_a", iteration_id="i")
        s1.acquire({"entry": "t"})
        # 不 release(模拟 owner 消失;锁随进程对象关闭释放)
        s1._fh.close()
        s1._fh = None
        s2 = QProdRunSession(state, level="level_a", iteration_id="i")
        with pytest.raises(QProdOwnershipError, match="不可接管"):
            s2.acquire({})

    def test_interruption_record_is_attributable(self, tmp_path):
        state = tmp_path / "state"
        s = QProdRunSession(state, level="level_b", iteration_id="i")
        s.acquire({})
        s.record_interruption("simulated crash", {
            "coordinate": "c01", "leaf_calls": {"once": 3}})
        entries = s.entries()
        ev = [e["event"] for e in entries]
        assert "interruption_recorded" in ev
        rec = next(e for e in entries
                   if e["event"] == "interruption_recorded")
        assert rec["attribution"]["leaf_calls"] == {"once": 3}

    def test_journal_rejects_unknown_event_and_protected_fields(
            self, tmp_path):
        state = tmp_path / "state"
        s = QProdRunSession(state, level="level_a", iteration_id="i")
        s.acquire({})
        with pytest.raises(QProdContextError, match="未知 journal 事件"):
            s._append("made_up_event")
        with pytest.raises(QProdOwnershipError, match="受保护"):
            s._append("permit_consumed", {"seq": 99})
        s.release()

    def test_append_requires_ownership(self, tmp_path):
        s = QProdRunSession(tmp_path / "state", level="level_a",
                            iteration_id="i")
        with pytest.raises(QProdOwnershipError, match="所有权"):
            s._append("session_released")
