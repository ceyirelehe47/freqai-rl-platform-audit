# -*- coding: utf-8 -*-
"""R17 执行治理内核测试(链会话/执行者身份/单写者 journal/状态机)。

覆盖任务书验收矩阵 T02-T16 的单元/进程级面(端到端成功链与权限
集成由 chain 集成测试与真实入口 rehearsal 承担):
  T02 同入口并发 A/B;T05 双拒绝并发 journal 不变;
  T06 fork 继承反例;T07 spawn 复制 token 反例;
  T08 合法委派子进程;T09 owner 真实退出;
  T10 静态资格≠执行权;T11 root/marker 漂移;
  T12 非法迁移 strict 拒绝;T13 journal 损坏;
  T16 被接受运行崩溃后不接管。

全部使用隔离临时 state root;零 R17 正式/holdout/final 数据。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

PROJ_SRC = Path(__file__).resolve().parents[2] / "src"
if str(PROJ_SRC) not in sys.path:
    sys.path.insert(0, str(PROJ_SRC))

from rl_curriculum.curriculum261_r17_execgov import (  # noqa: E402
    R17AuthorizationError,
    R17ChainSession,
    R17JournalCorruption,
    R17OwnershipError,
    chain_released,
    executor_identity,
    executor_identity_matches,
    exposure_state,
    iteration_aborted,
    journal_entries,
    post_hoc_closure_allowed,
    process_alive,
    r17_journal_path,
    r17_request_dir,
    verify_executor_token,
    write_rejection_evidence,
)
from rl_curriculum.curriculum261_r17_registry import (  # noqa: E402
    R17_FORMAL_QUALIFICATION_NAMESPACES,
    verify_r17_namespace_name_isolation,
)

PROBE_NS = "qualification_r17_execgov_test"


@pytest.fixture()
def isolated_root(monkeypatch):
    with tempfile.TemporaryDirectory(
            prefix="r17_execgov_test_") as td:
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT", td)
        yield Path(td)


def _acquire(binding=None):
    return R17ChainSession.acquire(
        binding or {"probe": "test", "mode": "probe"})


def _journal_snapshot(root: Path) -> bytes:
    p = root / "r17_execution_journal.jsonl"
    return p.read_bytes() if p.is_file() else b""


# ------------------------------------------------- 基础生命周期 --------
class TestChainSessionLifecycle:

    def test_acquire_owns_and_identity_bound(self, isolated_root):
        s = _acquire()
        assert s.owns()
        assert s.owner_identity["pid"] == os.getpid()
        assert s.owner_identity.get("starttime")
        entries = journal_entries()
        assert entries[0]["event"] == "chain_session_acquired"
        assert entries[0]["owner_identity"]["pid"] == os.getpid()

    def test_full_lifecycle_event_sequence(self, isolated_root):
        s = _acquire()
        s.record_design_data_started(note="t")
        s.record_step_started("provenance-verify")
        s.record_step_completed("provenance-verify", rc=0)
        s.open_qualification_window("digest-1")
        grant = s.issue_generation_grant(
            namespaces=(PROBE_NS,))
        facts = verify_executor_token(grant.token, PROBE_NS)
        assert facts["namespace"] == PROBE_NS
        s.revoke_generation_grant(grant)
        s.commit_qualification_terminal("completed", "digest-1")
        s.record_step_started("smoke")
        s.record_step_completed("smoke", rc=0)
        s.release(summary="done")
        events = [e["event"] for e in journal_entries()]
        assert events == [
            "chain_session_acquired", "design_data_started",
            "chain_step_started", "chain_step_completed",
            "chain_exposure_started", "grant_issued", "grant_revoked",
            "qualification_terminal", "chain_step_started",
            "chain_step_completed", "chain_released"]
        assert exposure_state()["status"] == "completed"
        assert chain_released()

    def test_release_requires_exposure_resolution(self,
                                                  isolated_root):
        s = _acquire()
        s.open_qualification_window("digest-2")
        with pytest.raises(R17OwnershipError, match="running"):
            s.release(summary="premature")
        s.commit_qualification_terminal("crashed", "digest-2")
        s.release(summary="ok")

    def test_one_accepted_run_per_iteration(self, isolated_root):
        s = _acquire()
        s.release(summary="first")
        with pytest.raises(R17OwnershipError, match="一次"):
            _acquire()


# ------------------------------------------------- T02/T05 竞争 --------
class TestCompetingRequests:

    def test_t02_second_acquire_rejected_zero_journal_effect(
            self, isolated_root):
        s = _acquire()
        before = _journal_snapshot(isolated_root)
        with pytest.raises(R17OwnershipError):
            _acquire({"probe": "loser"})
        assert _journal_snapshot(isolated_root) == before
        rejected = list((isolated_root / "rejected_requests").glob(
            "*.json"))
        assert len(rejected) == 1
        doc = json.loads(rejected[0].read_text(encoding="utf-8"))
        assert doc["reason"] == "lock_held_by_active_owner"
        assert doc["requester_identity"]["pid"] == os.getpid()

    def test_t05_concurrent_losers_journal_unchanged(
            self, isolated_root):
        s = _acquire()
        before = _journal_snapshot(isolated_root)
        code = f"""
import subprocess, sys
sys.path.insert(0, {str(PROJ_SRC)!r})
import os
os.environ["CURRICULUM261_R17_STATE_ROOT"] = \
{str(isolated_root)!r}
from rl_curriculum.curriculum261_r17_execgov import (
    R17ChainSession, R17OwnershipError)
try:
    R17ChainSession.acquire({{"probe": "concurrent-loser"}})
    print("acquired(bug)")
except R17OwnershipError:
    print("rejected")
"""
        procs = [subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE,
            text=True) for _ in range(6)]
        outs = [p.communicate()[0].strip() for p in procs]
        assert all(o == "rejected" for o in outs), outs
        assert _journal_snapshot(isolated_root) == before
        assert len(list((isolated_root / "rejected_requests")
                        .glob("*.json"))) == 6
        s.release(summary="owner done")

    def test_rejection_evidence_writer_isolated(self,
                                                isolated_root):
        p = write_rejection_evidence("unit-probe", {"k": 1})
        assert p.is_file()
        assert not r17_journal_path().exists()


# ------------------------------------------------- T06/T07/T08 身份 ----
class TestExecutorIdentity:

    def test_t06_fork_inheritance_rejected(self, isolated_root):
        s = _acquire()
        s.open_qualification_window("digest-fork")
        grant = s.issue_generation_grant(namespaces=(PROBE_NS,))
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            out: dict[str, object] = {}
            out["owns"] = s.owns()
            try:
                verify_executor_token(grant.token, PROBE_NS)
                out["verify"] = "PASSED(bug)"
            except R17AuthorizationError as exc:
                out["verify"] = f"rejected:{str(exc)[:40]}"
            try:
                s.release(summary="hijack")
                out["release"] = "SUCCEEDED(bug)"
            except Exception as exc:  # noqa: BLE001
                out["release"] = f"rejected:{type(exc).__name__}"
            os.write(w, json.dumps(out).encode())
            os._exit(0)
        os.close(w)
        with os.fdopen(r, "rb") as fh:
            child = json.loads(fh.read())
        os.waitpid(pid, 0)
        assert child["owns"] is False
        assert child["verify"].startswith("rejected")
        assert child["release"].startswith("rejected")
        assert s.owns()
        s.commit_qualification_terminal("crashed", "digest-fork")
        s.release(summary="cleanup")

    def test_t07_spawn_copied_token_rejected(self, isolated_root):
        s = _acquire()
        s.open_qualification_window("digest-spawn")
        grant = s.issue_generation_grant(namespaces=(PROBE_NS,))
        env = dict(os.environ,
                   CURRICULUM261_R17_EXECUTOR_TOKEN_ENV=grant.token)
        code = f"""
import sys
sys.path.insert(0, {str(PROJ_SRC)!r})
from rl_curriculum.curriculum261_r17_execgov import (
    verify_executor_token, R17AuthorizationError)
try:
    verify_executor_token({grant.token!r}, {PROBE_NS!r})
    print("PASSED(bug)")
except R17AuthorizationError:
    print("rejected")
"""
        p = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True,
                           timeout=120)
        assert p.stdout.strip() == "rejected", p.stdout + p.stderr
        s.commit_qualification_terminal("crashed", "digest-spawn")
        s.release(summary="cleanup")

    def test_t08_legitimate_delegated_subprocess(self,
                                                 isolated_root):
        """协调者把授权委派给真实子进程:身份匹配 → 通过;越界
        namespace 拒绝(不同 PID 的真实委派,非模拟)。"""
        s = _acquire()
        s.open_qualification_window("digest-delegate")
        r_id, w_id = os.pipe()
        r_tok, w_tok = os.pipe()
        code = f"""
import json, os, sys
sys.path.insert(0, {str(PROJ_SRC)!r})
from rl_curriculum.curriculum261_r17_execgov import (
    executor_identity, verify_executor_token, R17AuthorizationError)
with open({w_id}, "w") as fh:
    fh.write(json.dumps(executor_identity()) + chr(10))
with open({r_tok}) as fh:
    token = json.loads(fh.readline())["token"]
facts = verify_executor_token(token, {PROBE_NS!r})
try:
    verify_executor_token(token, "unrelated_namespace_r17")
    oob = "PASSED(bug)"
except R17AuthorizationError:
    oob = "rejected"
print(json.dumps({{"facts": facts, "out_of_scope": oob}}))
"""
        env = dict(os.environ)
        proc = subprocess.Popen(
            [sys.executable, "-c", code], env=env,
            pass_fds=(w_id, r_tok), stdout=subprocess.PIPE,
            text=True)
        with os.fdopen(r_id, "r") as fh:
            worker_ident = json.loads(fh.readline())
        grant = s.issue_generation_grant(
            namespaces=(PROBE_NS,),
            delegate_executor_identity=worker_ident,
            channel="controlled_pipe_test")
        with os.fdopen(w_tok, "w") as fh:
            fh.write(json.dumps(
                {"kind": "grant_token", "token": grant.token})
                + "\n")
        out = json.loads(proc.communicate(timeout=120)[0]
                         .strip().splitlines()[-1])
        assert out["facts"]["namespace"] == PROBE_NS
        assert out["facts"]["grant"] == grant.grant_hash
        assert worker_ident["pid"] != os.getpid()
        assert out["out_of_scope"] == "rejected"
        s.revoke_generation_grant(grant)
        s.commit_qualification_terminal("completed", "digest-delegate")
        s.release(summary="delegate ok")

    def test_t09_owner_death_rejects_new_requests(self,
                                                  isolated_root):
        """owner 真实退出后:身份完全合法的被委派 worker 的新
        受保护请求被拒(owner 存活性独立判定;锁 fd 继承不算
        owner 存活);且被接受运行不允许接管重跑(T16 面)。"""
        coord = isolated_root / "coord"
        coord.mkdir()
        worker_script = coord / "worker.py"
        worker_script.write_text(
            "import json, sys, time\n"
            "sys.path.insert(0, " + repr(str(PROJ_SRC)) + ")\n"
            "from rl_curriculum.curriculum261_r17_execgov import (\n"
            "    executor_identity, verify_executor_token,\n"
            "    R17AuthorizationError)\n"
            "open(" + repr(str(coord / "identity.json")) +
            ", \"w\").write(json.dumps(executor_identity()))\n"
            "from pathlib import Path\n"
            "token_file = Path(" +
            repr(str(coord / "token.json")) + ")\n"
            "for _ in range(600):\n"
            "    if token_file.is_file():\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            "token_doc = json.loads(token_file.read_text())\n"
            "token = token_doc[\"token\"]\n"
            "owner_pid = token_doc[\"owner_pid\"]\n"
            "# 等 owner 进程真实消失(/proc/<pid> 不再存在)\n"
            "for _ in range(600):\n"
            "    if not Path(f\"/proc/{owner_pid}\").exists():\n"
            "        break\n"
            "    time.sleep(0.05)\n"
            "try:\n"
            "    verify_executor_token(token, " +
            repr(PROBE_NS) + ")\n"
            "    result = \"PASSED(bug)\"\n"
            "except R17AuthorizationError as e:\n"
            "    result = \"rejected:\" + str(e)[:80]\n"
            "except BaseException as e:\n"
            "    result = (\"worker-error:\" + type(e).__name__ + "
            "\":\" + str(e)[:120])\n"
            "open(" + repr(str(coord / "worker_result.txt")) +
            ", \"w\").write(result)\n", encoding="utf-8")
        worker = subprocess.Popen(
            [sys.executable, "-u", str(worker_script)])
        identity_path = coord / "identity.json"
        for _ in range(600):
            if identity_path.is_file():
                break
            time.sleep(0.05)
        worker_ident = json.loads(
            identity_path.read_text(encoding="utf-8"))
        owner_script = coord / "owner.py"
        owner_script.write_text(
            "import json, os, sys\n"
            "sys.path.insert(0, " + repr(str(PROJ_SRC)) + ")\n"
            "os.environ[\"CURRICULUM261_R17_STATE_ROOT\"] = " +
            repr(str(isolated_root)) + "\n"
            "from rl_curriculum.curriculum261_r17_execgov import (\n"
            "    R17ChainSession)\n"
            "s = R17ChainSession.acquire({\"probe\": \"death-owner\"})\n"
            "s.open_qualification_window(\"digest-death-owner\")\n"
            "ident = json.loads(open(" +
            repr(str(identity_path)) + ").read())\n"
            "g = s.issue_generation_grant(\n"
            "    namespaces=(" + repr(PROBE_NS) + ",),\n"
            "    delegate_executor_identity=ident)\n"
            "open(" + repr(str(coord / "token.json")) +
            ", \"w\").write(\n"
            "    json.dumps({\"token\": g.token,\n"
            "                \"owner_pid\": os.getpid()}))\n"
            "os._exit(0)  # owner 崩溃(不 release;worker 在途)\n",
            encoding="utf-8")
        owner = subprocess.run(
            [sys.executable, "-u", str(owner_script)],
            timeout=120)
        assert owner.returncode == 0
        result_path = coord / "worker_result.txt"
        for _ in range(600):
            if result_path.is_file():
                break
            time.sleep(0.05)
        result = result_path.read_text(encoding="utf-8")
        assert result.startswith("rejected"), result
        assert "owner" in result or "实例" in result, result
        with pytest.raises(R17OwnershipError):
            _acquire({"probe": "takeover-after-owner-death"})
        worker.kill()
        worker.wait()


# ------------------------------------------------- T10/T11 资格与漂移 --
class TestAuthorizationGates:

    def test_t10_static_unqualified_no_seed(self, isolated_root):
        """六要素未解锁(无 plan):正式四件套 seed 派生被拒。"""
        from rl_curriculum.curriculum261_api import derive261_seed
        for ns in R17_FORMAL_QUALIFICATION_NAMESPACES:
            with pytest.raises(RuntimeError) as ei:
                derive261_seed(ns, "c1_opportunity", "D0", 0, 0)
            assert "R17 qualification plan 完整锁定" in str(ei.value)

    def test_t10_grant_absent_formal_face_gate(self, isolated_root):
        """动态执行权入口的正式面白名单:probe 名被拒(白名单
        本身是被测对象;无 token 的动态层拒绝由 seed 守卫测试
        覆盖)。"""
        from rl_curriculum.curriculum261_r17_execgov import (
            require_r17_generation_authorization,
        )
        os.environ.pop("CURRICULUM261_R17_EXECUTOR_TOKEN_ENV",
                       None)
        with pytest.raises(RuntimeError, match="正式资格面"):
            require_r17_generation_authorization(PROBE_NS)

    def test_t11_marker_token_copy_cannot_restart(
            self, isolated_root):
        s = _acquire()
        s.open_qualification_window("digest-copy")
        s.commit_qualification_terminal("failed", "digest-copy")
        s.release(summary="done")
        # 复制 marker/token 到新 root:journal 缺失 → 一切默认
        # 无会话;但一旦把 journal 一并复制,状态机仍拒绝新会话
        other = isolated_root.parent / (
            isolated_root.name + "_copy")
        other.mkdir()
        for f in isolated_root.iterdir():
            if f.is_file():
                (other / f.name).write_bytes(f.read_bytes())
        os.environ["CURRICULUM261_R17_STATE_ROOT"] = str(other)
        with pytest.raises(R17OwnershipError):
            _acquire({"probe": "copied-root"})
        os.environ["CURRICULUM261_R17_STATE_ROOT"] = str(
            isolated_root)


# ------------------------------------------------- T12/T13 状态机 -----
class TestStateMachine:

    def _raw_append(self, root: Path, rec: dict) -> None:
        with open(root / "r17_execution_journal.jsonl", "a",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")

    def test_t12_orphan_grant_rejected(self, isolated_root):
        self._raw_append(isolated_root, {
            "seq": 1, "utc": "t", "event": "grant_issued",
            "iteration": "r17", "pid": 1, "owner": "x",
            "writer": "y", "grant": "g" * 64,
            "namespaces": [PROBE_NS]})
        with pytest.raises(R17JournalCorruption,
                           match="非法迁移"):
            journal_entries()

    def test_t12_terminal_before_exposure_rejected(self,
                                                   isolated_root):
        self._raw_append(isolated_root, {
            "seq": 1, "utc": "t", "event": "qualification_terminal",
            "iteration": "r17", "pid": 1, "owner": "x",
            "writer": "y", "status": "completed",
            "plan_digest": "d"})
        with pytest.raises(R17JournalCorruption):
            journal_entries()

    def test_t12_wrong_iteration_rejected(self, isolated_root):
        self._raw_append(isolated_root, {
            "seq": 1, "utc": "t", "event": "chain_session_acquired",
            "iteration": "r16", "pid": 1, "owner": "x",
            "writer": "y", "binding": {}})
        with pytest.raises(R17JournalCorruption):
            journal_entries()

    def test_t12_duplicate_step_started_rejected(self,
                                                 isolated_root):
        s = _acquire()
        s.record_step_started("x")
        s.release(summary="t")
        raw = (isolated_root / "r17_execution_journal.jsonl"
               ).read_text(encoding="utf-8").splitlines()
        rec = json.loads(raw[-1])
        rec = dict(rec, event="chain_step_started", step="x",
                   seq=3)
        with open(isolated_root / "r17_execution_journal.jsonl",
                  "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
        with pytest.raises(R17JournalCorruption):
            journal_entries()

    def test_t13_truncated_and_corrupt_journal(self,
                                               isolated_root):
        s = _acquire()
        s.record_step_started("a")
        path = isolated_root / "r17_execution_journal.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:1]) + "\n{broken",
                       encoding="utf-8")
        with pytest.raises(R17JournalCorruption):
            journal_entries()
        assert exposure_state()["corrupt"] is True
        assert exposure_state()["exposed"] is True  # fail closed
        assert iteration_aborted()  # fail closed


# ------------------------------------------------- T14 exposure 崩溃 --
class TestExposureCrashSemantics:

    def test_t14_exposure_persisted_crash_preserved(
            self, isolated_root):
        s = _acquire()
        s.open_qualification_window("digest-crash")
        state = exposure_state()
        assert state["exposed"] and state["status"] == "running"
        # 模拟崩溃:不写终态直接失去对象(锁 fd 由 GC 关闭)
        del s
        state2 = exposure_state()
        assert state2["exposed"]
        assert state2["status"] == "running"
        with pytest.raises(R17OwnershipError, match="接管"):
            _acquire({"probe": "post-crash"})


# ------------------------------------------------- 隔离静态 ------------
class TestRegistry:

    def test_namespace_isolation(self):
        doc = verify_r17_namespace_name_isolation()
        assert doc["pass"], doc["problems"]

    def test_identity_helpers(self):
        a = executor_identity()
        assert executor_identity_matches(a, executor_identity())
        assert not executor_identity_matches(
            a, {"pid": 999999, "starttime": "1",
                "boot_id": a["boot_id"]})
