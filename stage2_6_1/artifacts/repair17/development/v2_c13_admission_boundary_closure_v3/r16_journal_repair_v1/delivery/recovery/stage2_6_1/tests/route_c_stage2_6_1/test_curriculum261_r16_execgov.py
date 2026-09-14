# -*- coding: utf-8 -*-
"""R16 执行治理内核测试(§6/§7/§8/§10 矩阵)。

覆盖:会话唯一性与竞争零副作用、exposure 一次性先于数据访问、
静态资格≠动态执行权的授权矩阵、终态持权提交、孤儿接管/封口、
journal 权威与损坏 fail closed、token 复制/环境变量冒用拒绝。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r16_execgov import (
    R16AuthorizationError,
    R16FormalSession,
    R16JournalCorruption,
    R16OwnershipError,
    bootstrap_failure_evidence,
    exposure_state,
    iteration_aborted,
    journal_entries,
    orphan_running_closure,
    require_r16_generation_authorization,
    r16_journal_path,
    verify_executor_token,
)


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    root = tmp_path / "r16_state"
    root.mkdir()
    monkeypatch.setenv("CURRICULUM261_R16_STATE_ROOT", str(root))
    monkeypatch.delenv("CURRICULUM261_R16_EXECUTOR_TOKEN", raising=False)
    return root


BINDING = {"iteration": "r16", "test": "execgov"}


class TestSessionUniqueness:
    def test_acquire_and_release(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        assert s.owns()
        s.release(summary="done")
        assert not s.owns()
        entries = journal_entries()
        events = [e["event"] for e in entries]
        assert events[0] == "session_acquired"
        assert events[-1] == "session_released"

    def test_second_acquire_rejected_zero_side_effects(self, state_root):
        """§6.2:B 抢占失败只记录 session_rejected;对 A 的 exposure/
        abort/manifest 零写入。"""
        a = R16FormalSession.acquire(binding=BINDING)
        with pytest.raises(R16OwnershipError):
            R16FormalSession.acquire(binding={"request": "B"})
        entries = journal_entries()
        # B 的拒绝被记录……
        assert any(e["event"] == "session_rejected"
                   and e.get("reason") == "lock_held_by_active_owner"
                   for e in entries)
        # ……但没有 exposure/abort/terminal 事件
        assert not any(e["event"] in (
            "exposure_started", "iteration_aborted",
            "qualification_terminal", "orphan_closure")
            for e in entries)
        # A 仍持有且可正常推进
        assert a.owns()
        a.release()

    def test_released_session_allows_new_session(self, state_root):
        a = R16FormalSession.acquire(binding=BINDING)
        a.release()
        b = R16FormalSession.acquire(binding={"request": "B"})
        assert b.owns()
        b.release()


class TestExposureOneShot:
    def test_exposure_before_grant_enforced(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        with pytest.raises(R16AuthorizationError):
            s.issue_generation_grant()  # exposure 未发生 ⇒ 拒绝
        s.record_exposure_started("digest-1")
        state = exposure_state()
        assert state["exposed"] and state["status"] == "running"
        grant = s.issue_generation_grant()
        assert grant is not None
        s.revoke_generation_grant()
        s.commit_qualification_terminal("failed", "digest-1")
        s.release()

    def test_double_exposure_rejected(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        with pytest.raises(R16OwnershipError):
            s.record_exposure_started("digest-2")
        s.release()

    def test_exposure_after_release_blocks_new_session(self, state_root):
        """exposure running 的孤儿:不接管重跑,只能显式封口(§6.5)。"""
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.release()  # 模拟 owner 未封口即消失(无终态)
        with pytest.raises(R16OwnershipError, match="孤儿"):
            R16FormalSession.acquire(binding={"request": "B"})
        closure = orphan_running_closure(note="test orphan")
        assert closure["status"] == "crashed"
        assert exposure_state()["terminal"]


class TestTerminalOwnership:
    def test_terminal_requires_ownership(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.release()
        # 释放后不再持有 ⇒ 终态提交被拒(§6.3 持权内提交)
        s2 = R16FormalSession.__new__(R16FormalSession)
        s2._released = True
        s2._lock_fh = None
        with pytest.raises(R16OwnershipError):
            s2.commit_qualification_terminal("crashed", "digest-1")

    def test_terminal_after_terminal_rejected(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.commit_qualification_terminal("failed", "digest-1")
        with pytest.raises(R16OwnershipError):
            s.commit_qualification_terminal("crashed", "digest-1")
        s.release()

    def test_terminal_digest_mismatch_rejected(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        with pytest.raises(R16OwnershipError):
            s.commit_qualification_terminal("failed", "other-digest")
        s.release()


class TestOrphanSupersede:
    def test_no_exposure_orphan_superseded(self, state_root):
        """锁释放且无 exposure/无授权的孤儿会话:新会话可接管
        (session_superseded;正式数据从未被访问)。"""
        s = R16FormalSession.acquire(binding=BINDING)
        # 不 release,直接丢引用(owner 进程死亡 ⇒ 锁 fd 关闭)。
        # 同进程内 flock 于不同 open file description,显式模拟:
        import fcntl

        fcntl.flock(s._lock_fh.fileno(), fcntl.LOCK_UN)
        s._lock_fh.close()
        s._lock_fh = None
        b = R16FormalSession.acquire(binding={"request": "B"})
        events = [e["event"] for e in journal_entries()]
        assert "session_superseded" in events
        assert b.owns()
        b.release()


class TestAuthorizationMatrix:
    """§7.1 强制行为表:各状态下正式 seed 派生是否允许。"""

    NS = "qualification_r16"

    def test_no_grant_no_session_rejected(self, state_root):
        with pytest.raises(R16AuthorizationError):
            require_r16_generation_authorization(self.NS)

    def test_grant_active_allows(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.issue_generation_grant()
        fact = require_r16_generation_authorization(self.NS)
        assert fact["namespace"] == self.NS
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()

    def test_revoked_grant_rejected(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.issue_generation_grant()
        s.revoke_generation_grant()
        with pytest.raises(R16AuthorizationError):
            require_r16_generation_authorization(self.NS)
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()

    def test_terminal_state_rejects_new_grant(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        g = s.issue_generation_grant()
        s.revoke_generation_grant()
        s.commit_qualification_terminal("failed", "digest-1")
        s.release()
        # 终态后:即使持有残留 token 也拒绝(exposure 非 running)
        with pytest.raises(R16AuthorizationError):
            verify_executor_token(g.token, self.NS)

    def test_namespace_scope_enforced(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        grant = s.issue_generation_grant(
            namespaces=("qualification_r16",))
        with pytest.raises(R16AuthorizationError):
            verify_executor_token(grant.token,
                                  "cue_semantic_qualification_r16")
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()

    def test_copied_token_rejected_after_release(self, state_root):
        """§7.1:marker/token 复制到新场景不构成授权。"""
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        grant = s.issue_generation_grant()
        token = grant.token
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()
        # 复制的 token + 会话已释放 ⇒ 拒绝
        with pytest.raises(R16AuthorizationError):
            verify_executor_token(token, self.NS)

    def test_env_token_from_delegated_subprocess(self, state_root):
        """受委派子进程经环境变量取得授权(§6.5);父会话死亡后
        残留 token 因互斥消失被拒。"""
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.issue_generation_grant(delegate_to_env=True)
        env_token = os.environ["CURRICULUM261_R16_EXECUTOR_TOKEN"]
        # 同进程内 require 走 env 分支(先清进程内 grant)
        from rl_curriculum import curriculum261_r16_execgov as eg

        eg._deactivate_grant()
        fact = require_r16_generation_authorization(self.NS)
        assert fact["namespace"] == self.NS
        # 模拟 owner 消失(锁释放且无人继承):互斥探测令 token 失效
        import fcntl

        fh = s._lock_fh
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        with pytest.raises(R16AuthorizationError, match="互斥"):
            require_r16_generation_authorization(self.NS)
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()

    def test_forged_token_rejected(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.issue_generation_grant()
        with pytest.raises(R16AuthorizationError):
            verify_executor_token("0" * 64, self.NS)
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()


class TestJournalAuthority:
    NS = "qualification_r16"

    def test_corrupt_journal_fails_closed(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        s.issue_generation_grant()
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-1")
        s.release()
        # 截断/污染 journal ⇒ 授权判定 fail closed(不得静默认为
        # "从未 exposure")
        path = r16_journal_path()
        raw = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(raw[:-2]) + "\n{broken json\n",
                        encoding="utf-8")
        with pytest.raises(R16JournalCorruption):
            exposure_state()
        assert iteration_aborted(strict=False) is False  # lenient

    def test_unknown_event_rejected(self, state_root):
        R16FormalSession.acquire(binding=BINDING)  # 写 journal
        path = r16_journal_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"seq": 2, "event": "evil_event",
                                 "iteration": "r16"}) + "\n")
        with pytest.raises(R16JournalCorruption):
            journal_entries()

    def test_aborted_blocks_session_and_grant(self, state_root):
        s = R16FormalSession.acquire(binding=BINDING)
        s.record_exposure_started("digest-1")
        g = s.issue_generation_grant()
        from rl_curriculum.curriculum261_r16_execgov import (
            record_iteration_aborted_standalone,
        )

        # 会话持有中:standalone abort 拒绝(不得干扰运行中执行)
        with pytest.raises(R16OwnershipError):
            record_iteration_aborted_standalone("conflict test")
        s.revoke_generation_grant()
        s.commit_qualification_terminal("failed", "digest-1")
        s.release()
        record_iteration_aborted_standalone("smoke 失败(测试)")
        assert iteration_aborted()
        with pytest.raises(R16AuthorizationError):
            verify_executor_token(g.token, self.NS)


class TestBootstrapEvidence:
    def test_bootstrap_failure_shape(self, state_root):
        ev = bootstrap_failure_evidence(
            "bash r16_formal_chain.sh abc123",
            "set: pipefail: invalid option name (CRLF)")
        assert ev["failure_boundary"] == "bootstrap"
        assert ev["workflow_started"] is False
        assert ev["executed_prefix"] == []
        assert ev["first_unexecuted_node"] == "provenance-verify"
        assert ev["qualification_authorized"] is False
        assert ev["exposure"]["exposed"] is False


class TestRealSubprocessCompetition:
    """§10:双进程竞争用真实 subprocess(barrier 精确控制交错)。"""

    COMPETITION_SCRIPT = textwrap.dedent("""
        import json, os, sys
        sys.path.insert(0, {src!r})
        from rl_curriculum.curriculum261_r16_execgov import (
            R16FormalSession, R16OwnershipError, exposure_state)
        role, ready_path, go_path = sys.argv[1], sys.argv[2], sys.argv[3]
        Path_ready = open(ready_path, "w"); Path_ready.close()
        # barrier: 等 go 信号(主进程在 A 已 acquire 后创建 go 文件)
        import time
        while not os.path.exists(go_path):
            time.sleep(0.02)
        try:
            s = R16FormalSession.acquire(binding={{"role": role}})
        except R16OwnershipError as exc:
            print(json.dumps({{"role": role, "acquired": False,
                               "error": str(exc)[:80]}}))
            sys.exit(3)
        s.record_exposure_started("digest-comp")
        g = s.issue_generation_grant()
        # 慢速持权:主进程在此期间观察
        time.sleep(float(sys.argv[4]))
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "digest-comp")
        s.release()
        print(json.dumps({{"role": role, "acquired": True}}))
    """)

    def test_two_processes_one_winner(self, state_root, tmp_path):
        src = str(Path(__file__).resolve().parents[2] / "src")
        script = tmp_path / "compete.py"
        script.write_text(self.COMPETITION_SCRIPT.format(src=src),
                          encoding="utf-8")
        ready_a = tmp_path / "ready_a"
        ready_b = tmp_path / "ready_b"
        go = tmp_path / "go"
        env = dict(os.environ)
        env["CURRICULUM261_R16_STATE_ROOT"] = str(state_root)
        # A 先启动并等待 barrier;B 也启动等待
        pa = subprocess.Popen(
            [sys.executable, str(script), "A", str(ready_a), str(go),
             "1.0"],
            env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(200):
            if ready_a.exists():
                break
            import time

            time.sleep(0.02)
        assert ready_a.exists(), "A 未到达 barrier"
        pb = subprocess.Popen(
            [sys.executable, str(script), "B", str(ready_b), str(go),
             "0.1"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True)
        for _ in range(200):
            if ready_b.exists():
                break
            import time

            time.sleep(0.02)
        assert ready_b.exists(), "B 未到达 barrier"
        # A 已 acquire(在 barrier 前?不——脚本先等 go 再 acquire;
        # 修正:go 之前进程未 acquire。这里用 A 的 ready 后、B 的
        # ready 顺序不能保证 A 先拿锁。改为:主进程先让 A 走,
        # 确认 A 获得锁(exposure running),再放 B。)
        go.write_text("")
        out_a, _ = pa.communicate(timeout=30)
        # A 结束(terminal+release)后 B 才被放行?不——go 已同时
        # 放行。为确保 A 先:等待 exposure 出现。
        # (A 的 acquire 与 B 的 acquire 竞争;确定性由 A 先启动
        #  与 flock 语义保证:A 先到 barrier,go 创建后 A 大概率
        #  先 acquire。若 B 赢,A 的输出会显示 acquired:False;
        #  断言恰好一个 acquired=True 即可,角色不限。)
        out_b, _ = pb.communicate(timeout=30)
        results = []
        for line in (out_a + out_b).splitlines():
            line = line.strip()
            if line.startswith("{"):
                results.append(json.loads(line))
        winners = [r for r in results if r.get("acquired")]
        assert len(winners) == 1, results
        losers = [r for r in results if not r.get("acquired")]
        assert len(losers) == 1
        # 输家的拒绝被记录;journal 恰好一次 exposure
        entries = journal_entries()
        assert len([e for e in entries
                    if e["event"] == "exposure_started"]) == 1
        assert exposure_state()["terminal"]
