# -*- coding: utf-8 -*-
"""R17 结果判定一致性/在途写入封口/资源准入(任务书 A 矩阵可夹具化项)。

本文件先固定三个最小假成功反例(A01/A09/A14),修复前红、修复后绿;
其余 A 矩阵场景按工作包逐步补全。真实模块为主:发布仓库 runner 与
rl_curriculum 实现 + CONTROL_FIXTURE_TEST worker;故障注入仅限隔离
工程夹具(生产入口不暴露注入通道)。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


def _find_runner_dir() -> Path:
    here = Path(__file__).resolve()
    for cand in (
            here.parents[3] / "stage2_6_1" / "runner",
            here.parents[2].parent / "stage2_6_1_runner",
            Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"),
    ):
        if (cand / "r17_supervision.py").is_file():
            return cand
    raise FileNotFoundError("runner 执行面不可达")


RUNNER_DIR = _find_runner_dir()
sys.path.insert(0, str(RUNNER_DIR))

from r17_supervision import (  # noqa: E402
    BoundedIOWriter, Supervisor, WinSampleReader, validate_win_sample)

requires_linux = pytest.mark.skipif(
    os.name == "nt", reason="控制路径执行面只在 Linux/WSL 跑")


def _perf(free=39.0, ct=38.0, cl=83.0, total=63.0):
    return {"phys_avail_gb": free, "commit_total_gb": ct,
            "commit_limit_gb": cl, "phys_total_gb": total}


def _utc_now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _vols_ok():
    """必需卷完整有效状态(F: required+C: optional;§6.2)。"""
    return [{"vol": "F:", "present": True, "free_gb": 100.0,
             "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
            {"vol": "C:", "present": True, "free_gb": 200.0,
             "size_gb": 900.0, "serial": "CCA1", "identity_match": True}]


def _win(perf=None, run_id=None, vols="default", utc="now", seq=1,
         telemetry_writable=True):
    line = {"event": "sample", "perf": perf if perf is not None else _perf()}
    if vols == "default":
        vols = _vols_ok()
    if vols is not None:
        line["vols"] = vols
    if utc == "now":
        utc = _utc_now()
    if utc is not None:
        line["utc"] = utc
    if seq is not None:
        line["seq"] = seq
    if telemetry_writable is not None:
        line["telemetry_out_writable"] = telemetry_writable
    if run_id is not None:
        line["run_id"] = run_id
    return line


def _guest(avail_kb=39_000_000, total_kb=40_000_000):
    return {"event": "guest_sample", "utc": _utc_now(),
            "meminfo": {"MemTotal": total_kb, "MemAvailable": avail_kb},
            "psi_memory": {"full_avg10": 0.0},
            "vmstat_swap": {"pswpout": 0}}


def _sup(tmp_path, argv=("--", "true"), task_kind="fixture", expect=None,
         samples_source=""):
    argv = list(argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    args = argparse.Namespace(
        run_dir=str(tmp_path / "run"), task_kind=task_kind,
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source=samples_source, win_sampler_ps1="/nonexistent.ps1",
        win_volumes="C:,F:", expect_artifact=expect or [],
        obs_ready_deadline=30.0)
    return Supervisor(args)


# ================================================= 三个最小假成功反例

# ---- A01:worker rc=0 但委派协议失败 → 步骤/链不得成功 ----------
# 复用上轮 CONTROL_FIXTURE_TEST 链路(coordinator 真实 execute_
# workflow_chain_r17 + 独立 worker)。half_line 行为:worker 写半行
# 身份后 exit 0(旧行为:raw rc=0 → step completed → 链继续
# fixture_never → chain ok=true —— 假成功)。
CF_RUNNER_SCRIPT = r'''
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from rl_curriculum.curriculum261_r17_execgov import R17ChainSession
from rl_curriculum.curriculum261_r17_workflow import (
    execute_workflow_chain_r17,
)
import rl_curriculum.curriculum261_r17_workflow as wf

sr = Path(sys.argv[2])
out = Path(sys.argv[3])
behavior = sys.argv[4]
mode = sys.argv[5] if len(sys.argv) > 5 else "normal"
wf.R17_WORKFLOW_CLI_MODULE = "r17_control_fixture_worker"

if mode == "revoke_fail":
    def _revoke(self, grant):
        raise RuntimeError("cf 注入:revoke 持久化失败")
    R17ChainSession.revoke_generation_grant = _revoke
elif mode == "terminal_raise":
    def _commit(self, status, digest, *, note=""):
        raise RuntimeError("cf 注入:terminal 写入失败")
    R17ChainSession.commit_qualification_terminal = _commit
elif mode == "terminal_raise_after_write":
    _orig = R17ChainSession.commit_qualification_terminal
    def _commit2(self, status, digest, *, note=""):
        _orig(self, status, digest, note=note)
        raise RuntimeError("cf 注入:写已落盘但调用报错")
    R17ChainSession.commit_qualification_terminal = _commit2
elif mode == "terminate_unconfirmed":
    def _tw(proc, timeout=10.0):
        return False
    wf._terminate_and_wait = _tw
elif mode in ("cancel_read", "cancel_grant"):
    import signal as _sig
    _real_read = wf._read_pipe_line

    def _read(fd, **kw):
        if mode == "cancel_read":
            os.kill(os.getpid(), _sig.SIGTERM)
        line = _real_read(fd, **kw)
        if mode == "cancel_grant":
            os.kill(os.getpid(), _sig.SIGTERM)
        return line
    wf._read_pipe_line = _read
elif mode == "cancel_after_grant":
    # RSA-03:token 已写完(授权+交付都完成)之后才注入停止请求
    # ——worker 捕获 TERM 优雅 exit 0,验证取消归因不丢失
    import signal as _sig
    _real_write = wf._write_pipe_all

    def _write(fd, data, **kw):
        _real_write(fd, data, **kw)
        os.kill(os.getpid(), _sig.SIGTERM)
    wf._write_pipe_all = _write
elif mode == "fc_timeout":
    import subprocess as _sp
    _real_run = wf.subprocess.run
    def _run(*a, **kw):
        argv = a[0] if a else kw.get("args")
        if argv and any("fail-closure" == str(x) for x in argv):
            raise _sp.TimeoutExpired(cmd=str(argv), timeout=60)
        return _real_run(*a, **kw)
    wf.subprocess.run = _run

binding = {"mode": "rehearsal", "freeze_sha": "f" * 40,
           "state_root": str(sr), "out_dir": str(out),
           "argv": ["cf-fixture"]}
session = R17ChainSession.acquire(binding)
os.environ["R17_CF_BEHAVIOR"] = behavior
os.environ.setdefault("R17_CF_NAMESPACES", "cf_ns_a")
steps = [
    {"name": "qualify", "cli_command": "cfqualify",
     "argv": ["--behavior", behavior],
     "requires_artifacts": [], "output_artifacts": []},
    {"name": "fixture_never", "cli_command": "fixture",
     "argv": ["never"], "requires_artifacts": [],
     "output_artifacts": []},
]
plan = {"profile": "rehearsal", "out_dir": str(out),
        "manifest_path": str(out / "manifest.jsonl"),
        "workflow_graph_digest": "cf-fixture-digest",
        "qualify_grant_namespaces": ["cf_ns_a"],
        "steps": steps}
result = execute_workflow_chain_r17(
    plan, session=session, log_dir=out / "logs")
print("CFQUAL " + json.dumps(
    {"ok": result["ok"], "failed": result["failed_step"],
     "term_status": result.get("qualification_terminal_status")}))
if not result["ok"]:
    session.record_iteration_aborted(result["failure_reason"][:2000])
session.release(summary="cf fixture")
'''


@requires_linux
class TestA01ResultPropagation:
    """RCP-01:协议失败必须真实传到步骤/链/外层(§4.3 判定表)。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    SRC = SYNC / "src"
    RUNNER = SYNC / "stage2_6_1_runner"

    def _run_chain(self, tmp_path, behavior, mode="normal", timeout=120):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = tmp_path / "state"
        out = tmp_path / "out"
        script = tmp_path / "cf_runner.py"
        script.write_text(CF_RUNNER_SCRIPT, encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SRC) + os.pathsep + str(self.RUNNER),
            CURRICULUM261_R17_STATE_ROOT=str(state),
            R17_CF_BEHAVIOR=behavior,
            R17_CF_NAMESPACES="cf_ns_a")
        proc = subprocess.run(
            [sys.executable, str(script), str(self.SRC), str(state),
             str(out), behavior, mode],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=str(self.SYNC))
        journal = state / "r17_execution_journal.jsonl"
        events = [json.loads(l) for l in
                  journal.read_text(encoding="utf-8").splitlines() if l
                  ] if journal.is_file() else []
        mf = out / "manifest.jsonl"
        mlines = [json.loads(l) for l in
                  mf.read_text(encoding="utf-8").splitlines() if l
                  ] if mf.is_file() else []
        return proc, events, mlines, out

    def test_a01_half_line_identity_exit0_blocks_chain(self, tmp_path):
        """worker 写半行身份后 exit 0:raw rc=0 保留,但协议失败必须
        使步骤有效失败、链停止、后续哨兵零启动、外层非零。"""
        proc, events, mlines, _out = self._run_chain(tmp_path, "half_line")
        assert proc.returncode == 0, proc.stderr  # coordinator 自身正常
        assert '"ok": false' in proc.stdout, "链结果必须失败"
        # 后续哨兵零启动:manifest 只有 qualify 一条记录
        assert [r.get("step") for r in mlines] == ["qualify"], \
            "fixture_never 不得启动(旧实现假成功继续执行)"
        rec = mlines[0]
        assert rec["rc"] == 0  # raw worker rc 保留(不改写事实)
        assert rec.get("effective_result") == "failed"
        assert rec.get("effective_failure")
        assert rec["delegation"]["protocol_error"]
        assert rec["delegation"]["grant_issued"] is False
        # journal:步骤失败(不是 completed);无第二步痕迹
        failed = [e for e in events
                  if e["event"] == "chain_step_failed"]
        completed = [e for e in events
                     if e["event"] == "chain_step_completed"]
        assert failed and failed[0].get("step") == "qualify"
        assert not completed, "qualify 不得记 completed"
        assert not any(e.get("step") == "fixture_never"
                       for e in events)
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and term[0].get("status") == "failed"

    def test_a01_silent_exit0_before_identity_blocks_chain(self, tmp_path):
        """A01 第一行精确形态:worker 取得委派 fd 后不写身份、
        exit 0(协调者读到 EOF)→ raw rc=0、协议失败、grant=0、
        步骤失败、链停止、外层非零。"""
        proc, events, mlines, _out = self._run_chain(
            tmp_path, "silent_exit")
        assert proc.returncode == 0, proc.stderr
        assert '"ok": false' in proc.stdout
        assert [r.get("step") for r in mlines] == ["qualify"]
        rec = mlines[0]
        assert rec["rc"] == 0  # raw rc=0 保留
        assert rec.get("effective_result") == "failed"
        assert "identity_pipe_eof" in (
            rec["delegation"]["protocol_error"] or "")
        assert rec["delegation"]["grant_issued"] is False
        failed = [e for e in events
                  if e["event"] == "chain_step_failed"]
        assert failed and failed[0].get("step") == "qualify"
        assert not any(e.get("step") == "fixture_never"
                       for e in events)
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and term[0].get("status") == "failed"

    def test_a01_bad_json_identity_exit0_blocks_chain(self, tmp_path):
        proc, events, mlines, _out = self._run_chain(tmp_path, "bad_json")
        assert '"ok": false' in proc.stdout
        assert [r.get("step") for r in mlines] == ["qualify"]
        # 写完坏行即退的 worker 与协调者 TERM 存在时序竞争:
        # rc=0(先退出)或 -15(先被 TERM)都是真实形态;两种下
        # 有效结果都必须是失败。
        assert mlines[0]["rc"] in (0, -15)
        assert mlines[0].get("effective_result") == "failed"
        assert mlines[0]["delegation"]["protocol_error"]
        assert not any(e.get("step") == "fixture_never"
                       for e in events)


# ---- A09:唯一写动作 in-flight、队列空 → drain 不得声称完成 ------
@requires_linux
class TestA09InFlightDrain:
    """RCP-02:drain 不得以 queue.empty 判完成;in-flight 必须等待,
    超时返回未确认(>0)。barrier 确认写线程已 get 并进入动作。"""

    def test_a09_single_inflight_action_blocks_drain(self):
        iow = BoundedIOWriter()
        started = threading.Event()
        release = threading.Event()

        def blocking_fn():
            started.set()          # barrier:动作已开始执行
            release.wait(10)

        assert iow.submit(blocking_fn) is True
        assert started.wait(5.0), "写线程未进入动作"
        # 此刻:queue 为空(动作已被 get),但写入仍在途
        n = iow.drain(0.5)
        assert n > 0, "in-flight 未完成时 drain 必须返回未确认(旧实现 queue.empty 误报 0)"
        release.set()
        assert iow.drain(5.0) == 0

    def test_a09_failed_action_not_counted_done(self):
        iow = BoundedIOWriter()

        def failing_fn():
            raise OSError("disk full (cf)")

        assert iow.submit(failing_fn) is True
        n = iow.drain(5.0)
        assert n > 0, "失败动作不得计为完成(旧实现吞错计 executed)"
        st = iow.stats()
        assert st.get("failed", 0) == 1
        assert st.get("ok", 0) == 0


# ---- A14:必需依赖缺测不得跳过准入 --------------------------------
@requires_linux
class TestA14RequiredDepsAdmission:
    """RCP-03:必需卷缺记录/vols 空/present=false/存储查询失败
    均不得默默通过(旧实现只遍历 present、None 跳过)。"""

    @pytest.mark.parametrize("vols", [
        None,          # 无 vols 字段
        [],            # 空列表
        [{"vol": "C:", "present": True, "free_gb": 100.0}],  # 缺 F:
    ], ids=["no_field", "empty_list", "only_optional_C"])
    def test_a14_required_vol_missing_rejected(self, tmp_path, vols):
        sup = _sup(tmp_path)
        win = _win(vols=vols)
        ok, detail = sup.admission_check(win, _guest())
        assert not ok, "必需依赖缺测不得准入(旧实现跳过 keyvol)"
        assert "required_vol_missing" in detail
        assert sup.admission["ok"] is False

    def test_a14_storage_unknown_rejected(self, tmp_path, monkeypatch):
        sup = _sup(tmp_path)
        monkeypatch.setattr(sup, "_storage_used_gib", lambda: None)
        ok, detail = sup.admission_check(
            _win(vols=[{"vol": "F:", "present": True,
                        "free_gb": 100.0}]), _guest())
        assert not ok, "存储用量查询失败(unknown)不得跳过"
        assert "storage_unknown" in detail


# ================================================= A02-A08 判定表(CF 链)
@requires_linux
class TestJudgmentTableCF:
    """§4.3 判定表:raw rc 与有效结果/资格状态/链结果一致传播。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    SRC = SYNC / "src"
    RUNNER = SYNC / "stage2_6_1_runner"

    def _run_chain(self, tmp_path, behavior, mode="normal", timeout=120):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = tmp_path / "state"
        out = tmp_path / "out"
        script = tmp_path / "cf_runner.py"
        script.write_text(CF_RUNNER_SCRIPT, encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SRC) + os.pathsep + str(self.RUNNER),
            CURRICULUM261_R17_STATE_ROOT=str(state),
            R17_CF_BEHAVIOR=behavior,
            R17_CF_NAMESPACES="cf_ns_a")
        proc = subprocess.run(
            [sys.executable, str(script), str(self.SRC), str(state),
             str(out), behavior, mode],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=str(self.SYNC))
        journal = state / "r17_execution_journal.jsonl"
        events = [json.loads(l) for l in
                  journal.read_text(encoding="utf-8").splitlines() if l
                  ] if journal.is_file() else []
        mf = out / "manifest.jsonl"
        mlines = [json.loads(l) for l in
                  mf.read_text(encoding="utf-8").splitlines() if l
                  ] if mf.is_file() else []
        return proc, events, mlines, out

    @staticmethod
    def _terms(events):
        return [e for e in events
                if e["event"] == "qualification_terminal"]

    def test_a02_normal_worker_full_success_path(self, tmp_path):
        """A02:正常控制 worker 完整完成→全部必需条件成立→成功。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "verify_grant")
        assert '"ok": true' in proc.stdout, proc.stdout + proc.stderr
        rec = mlines[0]
        assert rec["rc"] == 0
        assert rec["effective_result"] == "completed"
        assert rec["effective_failure"] is None
        d = rec["delegation"]
        assert d["terminal_state"] == "committed"
        assert d["terminal_status"] == "completed"
        assert d["revoke_error"] is None and d["cancelled"] is False
        term = self._terms(events)
        assert len(term) == 1 and term[0]["status"] == "completed"
        # 零数值 seed 访问(CONTROL_FIXTURE_TEST 工程命名空间)
        assert all(ns.startswith("cf_ns_") or "cf" in ns
                   for ns in d["allowed_namespaces"])

    def test_a03_revoke_write_failure_blocks_success(self, tmp_path):
        """A03:worker rc=0 但撤权写入失败→保留错误,不走成功
        completed,后续零启动。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "normal", mode="revoke_fail")
        assert '"ok": false' in proc.stdout
        assert [r.get("step") for r in mlines] == ["qualify"]
        rec = mlines[0]
        assert rec["rc"] == 0  # raw 保留
        assert rec["effective_result"] == "failed"
        assert rec["effective_failure"] == "grant_revoke_failed"
        assert "revoke 持久化失败" in (rec["delegation"]["revoke_error"]
                                       or "")
        # RSA-03:资格终态内容与链结果一致——撤权失败不得写 completed
        term = self._terms(events)
        assert term and term[0]["status"] == "failed", \
            "revoke_error 未闭合时 qualification 不得是 completed"
        assert "grant_revoke_failed" in term[0].get("note", "")
        assert rec["delegation"]["terminal_status"] == "failed"
        assert not any(e.get("step") == "fixture_never"
                       for e in events)

    def test_a04_terminal_write_unknown_blocks_success(self, tmp_path):
        """A04a:terminal 写失败(结果未知)→未确认不能成功。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "normal", mode="terminal_raise")
        assert '"ok": false' in proc.stdout
        rec = mlines[0]
        assert rec["rc"] == 0
        assert rec["effective_result"] == "failed"
        assert rec["effective_failure"] == \
            "qualification_terminal_unconfirmed"
        d = rec["delegation"]
        assert d["terminal_state"] == "unknown"
        assert d["terminal_error"]
        assert not self._terms(events), "journal 不得有 terminal"

    def test_a04_terminal_written_but_raised_readonly_verify(
            self, tmp_path):
        """A04b:写已落盘但调用报错→按权威 journal 只读核对为
        committed(不重复提交、不强判失败/成功)。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "normal", mode="terminal_raise_after_write")
        assert '"ok": true' in proc.stdout, proc.stdout + proc.stderr
        rec = mlines[0]
        assert rec["effective_result"] == "completed"
        d = rec["delegation"]
        assert d["terminal_state"] == "committed"
        assert d["terminal_status"] == "completed"
        assert d["terminal_note"]
        # 唯一 terminal(无重复提交)
        assert len(self._terms(events)) == 1

    def test_a05_cancel_propagates_even_if_worker_exits0(
            self, tmp_path):
        """A05:取消先被接受、worker 捕获 TERM 后 exit 0→取消结果
        保持,新 grant 禁止,链有效失败。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "sleep_cancel", mode="cancel_grant")
        assert '"ok": false' in proc.stdout
        rec = mlines[0]
        assert rec["delegation"]["cancelled"] is True
        assert rec["effective_result"] == "failed"
        assert rec["effective_failure"] == "delegation_cancelled"
        assert not any(e.get("step") == "fixture_never"
                       for e in events)
        term = self._terms(events)
        assert term and term[0]["status"] == "failed"
        assert "cancelled" in term[0].get("note", "")

    def test_a07_unconfirmed_termination_not_success(self, tmp_path):
        """A07:清理不能确认 worker 退出(KILL 后仍存活形态)→
        rc=92 哨兵+worker_unconfirmed,不以未知充 0,有效失败。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "wrong_identity",
            mode="terminate_unconfirmed")
        assert '"ok": false' in proc.stdout
        rec = mlines[0]
        assert rec["rc"] == 92  # 未知退出状态哨兵(非 0 非 98/7/-15)
        assert rec["delegation"]["worker_unconfirmed"] is True
        assert rec["effective_result"] == "failed"
        # 第一失败原因=实际时间先后:身份不匹配先于终止失败;
        # worker_unconfirmed 作为事实保留在 summary(§4.5)
        assert rec["effective_failure"] == "delegation_protocol_error"
        term = self._terms(events)
        assert term and "identity_mismatch" in term[0].get("note", "")

    def test_a07_fail_closure_timeout_bounded(self, tmp_path):
        """A07b:fail-closure 子进程挂起→共享预算到期后有界未确认,
        协调者不无限等待、不外抛。"""
        t0 = time.monotonic()
        proc, events, mlines, out = self._run_chain(
            tmp_path, "half_line", mode="fc_timeout")
        assert time.monotonic() - t0 < 60, "收尾不得无期等待"
        assert '"ok": false' in proc.stdout
        fc_log = out / "logs" / "fail_closure.log"
        assert fc_log.is_file()
        assert "fail_closure_timeout" in fc_log.read_text(
            encoding="utf-8")


# ================================================= A10/A11/A13 封口完整性
@requires_linux
class TestSealCompleteness:
    """WP2 §5.4/§5.5:写失败/封口后迟写/live_writers 与验证器。"""

    def _build_verify(self, tmp_path, rr_dir, monkeypatch=None):
        root = rr_dir.parent.parent
        rr_path = rr_dir / "run_record.json"
        manifest = rr_dir / "manifest.jsonl"
        anchor = rr_dir.parent / "anchor.json"
        v = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "build", "--run-record", str(rr_path),
             "--manifest-out", str(manifest),
             "--anchor-out", str(anchor), "--root", str(root)],
            capture_output=True, text=True)
        assert v.returncode == 0, v.stderr
        v2 = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "verify", "--root", str(root), "--manifest", str(manifest),
             "--anchor-file", str(anchor), "--run-record", str(rr_path),
             "--receipt-dir", str(tmp_path / "receipts")],
            capture_output=True, text=True)
        return v2

    def test_a10_write_failure_evidence_incomplete(self, tmp_path):
        """A10:必需写动作抛错→failed 计数→evidence_complete=False
        →verify FAIL(不完整交付)。"""
        sup = _sup(tmp_path)
        sup.expected = [{"role": "alerts",
                         "path": str(sup.alerts_path)}]
        (sup.run_dir / "alerts").mkdir(parents=True, exist_ok=True)
        sup.alerts_path.write_text("", encoding="utf-8")

        def failing():
            raise OSError("disk full (cf A10)")
        assert sup.iow.submit(failing, critical=True, role="alerts")
        assert sup.iow.drain(5.0) > 0, "失败动作不得计完成"
        sup.finalize()
        rr = json.loads(
            (sup.run_dir / "run_record.json").read_text(
                encoding="utf-8"))
        assert rr["evidence_complete"] is False
        assert rr["io"]["failed"] == 1
        v2 = self._build_verify(tmp_path, sup.run_dir)
        assert v2.returncode == 1
        assert "evidence_incomplete" in v2.stderr

    def test_a11_seal_rejects_late_submit(self, tmp_path):
        """A11:封口边界后新提交被拒+计数;边界内成功动作后文件
        不再变化(成功发布不可变)。"""
        import hashlib
        iow = BoundedIOWriter()
        target = tmp_path / "sealed.txt"
        assert iow.submit(
            lambda: target.write_text("v1", encoding="utf-8"),
            role="file") is True
        assert iow.drain(5.0) == 0
        h1 = hashlib.sha256(target.read_bytes()).hexdigest()
        iow.seal()
        assert iow.submit(
            lambda: target.write_text("late", encoding="utf-8"),
            role="file") is False
        assert iow.submit(lambda: None) is False
        st = iow.stats()
        assert st["rejected_after_seal"] == 2
        assert st["accepted"] == 1
        time.sleep(0.1)
        assert hashlib.sha256(
            target.read_bytes()).hexdigest() == h1, \
            "封口后迟到写入不得改动已发布文件"

    def test_a13_live_writers_verify_fail(self, tmp_path):
        """A13:live_writers=true 的角色→verify 拒绝完整 PASS
        (写者未确认关闭,最终哈希不确定)。"""
        sup = _sup(tmp_path)
        # live_writers 标记只作用于业务流角色(stdout/stderr)
        sup.expected = [{"role": "business_stdout",
                         "path": str(sup.biz_stdout)}]
        sup.biz_stdout.parent.mkdir(parents=True, exist_ok=True)
        sup.biz_stdout.write_text("x\n", encoding="utf-8")
        sup.residual_unconfirmed = True  # 写者未证实关闭形态
        sup.finalize()
        rr = json.loads(
            (sup.run_dir / "run_record.json").read_text(
                encoding="utf-8"))
        assert rr["evidence_complete"] is False
        assert any(i.get("live_writers") for i in rr["required"])
        v2 = self._build_verify(tmp_path, sup.run_dir)
        assert v2.returncode == 1
        assert "live_writers" in v2.stderr


# ================================================= A15/A16/A17 样本身份
@requires_linux
class TestSampleIdentityAndAdmission:
    """WP3 §6.3:样本身份/重复/失联与准入矩阵。"""

    def test_a15_vol_identity_conflict_rejected(self, tmp_path):
        sup = _sup(tmp_path)
        ok, detail = sup.admission_check(_win(vols=[
            {"vol": "F:", "present": True, "free_gb": 100.0,
             "serial": "CFA1", "identity_match": False}]), _guest())
        assert not ok
        assert "required_vol_identity_unverified" in detail

    def test_a15_duplicate_vol_records_rejected(self, tmp_path):
        sup = _sup(tmp_path)
        ok, detail = sup.admission_check(_win(vols=[
            {"vol": "F:", "present": True, "free_gb": 100.0,
             "serial": "A", "identity_match": True},
            {"vol": "F:", "present": True, "free_gb": 50.0,
             "serial": "B", "identity_match": True}]), _guest())
        assert not ok
        assert "vol_duplicate:F:" in detail

    def test_a15_optional_C_missing_degrades_not_blocks(self, tmp_path):
        """C(应急备用)缺失:如实降级记录,不阻断 F 上的任务。"""
        sup = _sup(tmp_path)
        ok, detail = sup.admission_check(_win(vols=[
            {"vol": "F:", "present": True, "free_gb": 100.0,
             "serial": "CFA1", "identity_match": True}]), _guest())
        assert ok, detail
        assert sup.admission["optional_degraded"] == ["C:"]

    def test_a16_legacy_lines_not_valid(self, tmp_path):
        """旧格式(无 utc/seq)可解析但不进有效状态(live 准入
        无兼容后门;历史解释只在只读 reader)。"""
        p = tmp_path / "win.jsonl"
        legacy = {"event": "sample", "run_id": "r1",
                  "perf": _perf(), "vols": _vols_ok()}
        p.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        rd = WinSampleReader(p, run_id="r1")
        out = rd.read_new()
        assert out and rd.saw_any is True
        assert rd.saw_valid is False
        assert rd.invalid_samples == 1

    def test_a16_duplicate_seq_no_refresh(self, tmp_path):
        p = tmp_path / "win.jsonl"
        p.write_text(
            json.dumps(_win(seq=5)) + "\n" +
            json.dumps(_win(seq=5, perf=_perf(free=1.0))) + "\n",
            encoding="utf-8")
        rd = WinSampleReader(p, run_id=None)
        rd.read_new()
        assert rd.saw_valid is True
        assert rd.duplicate_seq == 1
        assert rd.last_valid["perf"]["phys_avail_gb"] == 39.0, \
            "重复 seq 不得刷新 last_valid"

    def test_a16_seq_regression_no_refresh(self, tmp_path):
        p = tmp_path / "win.jsonl"
        p.write_text(
            json.dumps(_win(seq=9)) + "\n" +
            json.dumps(_win(seq=4, perf=_perf(free=1.0))) + "\n",
            encoding="utf-8")
        rd = WinSampleReader(p, run_id=None)
        rd.read_new()
        assert rd.seq_regressions == 1
        assert rd.last_valid["seq"] == 9, "序号回退不刷新有效状态"

    def test_a16_old_timestamp_replay_rejected(self, tmp_path):
        """很久以前但数值正常的日志重放到新 run:不得进入有效
        状态(生成时间早于 run 启动-容差)。"""
        p = tmp_path / "win.jsonl"
        p.write_text(
            json.dumps(_win(utc="2020-01-01T00:00:00Z", seq=1))
            + "\n", encoding="utf-8")
        rd = WinSampleReader(
            p, run_id=None, started_iso=_utc_now(),
            predates_tolerance_s=300.0)
        rd.read_new()
        assert rd.stale_replayed == 1
        assert rd.saw_valid is False

    def test_a17_reader_restart_reestablishes_baseline(self, tmp_path):
        """来源重启(seq 归零)→回退计数,不沿用旧连续状态。"""
        p = tmp_path / "win.jsonl"
        rd = WinSampleReader(p, run_id=None)
        p.write_text(json.dumps(_win(seq=3)) + "\n", encoding="utf-8")
        rd.read_new()
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_win(seq=1)) + "\n")
        rd.read_new()
        assert rd.seq_regressions == 1
        assert rd.last_valid["seq"] == 3

    def test_a19_terminal_verify_readonly_fails_closed(self, tmp_path):
        """A19 支撑:journal 读取异常→只读核对 fail-closed(None),
        不产生假 committed;无会话身份同样 fail-closed。"""
        import rl_curriculum.curriculum261_r17_execgov as eg
        import rl_curriculum.curriculum261_r17_workflow as wf

        class _BrokenSession:
            session_hash = "s1"
        real = eg.journal_entries

        def broken(*a, **kw):
            raise RuntimeError("reader down (cf)")
        eg.journal_entries = broken
        try:
            assert wf._journal_terminal_lookup(
                _BrokenSession(), "d1") is None
        finally:
            eg.journal_entries = real
        # 无会话身份=无法核对归属:宁可 unknown,不匹配他人 terminal
        class _NoIdentitySession:
            pass
        assert wf._journal_terminal_lookup(
            _NoIdentitySession(), "d1") is None



# ================================================= RSA-01 writer 原子边界
@requires_linux
class TestRSA01WriterAtomicBoundary:
    """独立审查 §3:队列交接/计数/seal 的并发边界确定性回归。"""

    def test_rsa01_get_handoff_gap_drain_waits(self, tmp_path,
                                               monkeypatch):
        """queue.get 完成→in_flight 计数之间存在真实调度空窗:
        drain 的完整性证明不得依赖 qsize+in_flight 相加(旧实现
        在空窗内 drain=0 假完成,文件此后仍被写)。

        T01(§6 确定性交错):真实写线程是业务动作的**唯一消费者**——
        经标准库 queue.Queue 属性注入(BoundedIOWriter.__init__ 内
        局部 `import queue` 解析到同一模块对象,生效;生产入口不暴
        露注入通道)在写线程**已取走动作、尚未执行/计数交接**的确
        定点暂停。测试线程只观察 drain 并释放屏障,不与写线程竞争
        队列所有权(旧版:测试线程直接 get 抢同一动作,交错不受控)。
        补丁窗口内本进程只有 BoundedIOWriter 构造队列。"""
        import queue as _qmod
        taken = threading.Event()
        gate = threading.Event()

        class _PausingQueue(_qmod.Queue):
            def get(self, *a, **kw):
                act = super().get(*a, **kw)
                if not taken.is_set():
                    taken.set()
                    gate.wait(10.0)  # 有界:断言失败也不永久停泊写线程
                return act

        monkeypatch.setattr(_qmod, "Queue", _PausingQueue)
        iow = BoundedIOWriter()
        target = tmp_path / "handoff.txt"
        done = threading.Event()

        def _write_and_signal():
            target.write_text("v1", encoding="utf-8")
            done.set()

        assert iow.submit(_write_and_signal, role="probe") is True
        # 交接空窗:真实写线程已取走动作(queued=0),尚未执行/计数
        assert taken.wait(5.0), "写线程未取走动作(测试交错未建立)"
        st = iow.stats()
        assert st["queued"] == 0 and st["in_flight"] == 0
        assert st["accepted"] == 1  # 已接受(旧实现两计数都不含它)
        assert st["ok"] == 0 and st["failed"] == 0
        # drain 在交接空窗内必须等待已接受动作(单一计数口径),
        # 不依赖队列内部状态;等待经观测线程,不阻塞断言路径
        result: list[int] = []
        dt = threading.Thread(
            target=lambda: result.append(iow.drain(5.0)))
        dt.start()
        time.sleep(0.3)
        assert not result, "交接空窗内 drain 不得宣称完成"
        gate.set()
        dt.join(10)
        assert result and result[0] == 0, "释放后动作完成,drain 真实清零"
        assert done.wait(5.0)
        assert target.read_text(encoding="utf-8") == "v1"

    def test_rsa01_submit_seal_race_counts_pending(self, tmp_path):
        """submit 已通过 sealed 检查、尚未入队计数时并发 seal+drain:
        该动作必须已计入待完成集合(旧实现 drain=0 假完成后文件
        仍被迟写,封口方既未纳入也未拒绝)。"""
        iow = BoundedIOWriter()
        target = tmp_path / "late.txt"
        barrier = threading.Barrier(2, timeout=10)
        late_gate = threading.Event()
        real_put = iow._q.put_nowait

        def hooked_put(act):
            # submit 持 writer 锁、已通过 sealed 检查、put 之前
            barrier.wait()               # 与主线程的 seal 交错
            late_gate.wait(10)           # 保持暂停直到主线程观测完
            return real_put(act)
        iow._q.put_nowait = hooked_put

        def producer():
            iow.submit(lambda: target.write_text("v1", encoding="utf-8"),
                       role="file")
        t = threading.Thread(target=producer)
        t.start()
        barrier.wait()                   # producer 在锁内暂停
        # seal 与 drain 各起线程(新实现二者阻塞等 writer 锁,排在
        # submit 临界区之后;主线程只做观测,不调用阻塞 API——
        # 否则主线程先卡在锁上,观测窗口丢失)
        st_thread = threading.Thread(target=iow.seal)
        st_thread.start()
        result: list[int] = []

        def _drain():
            result.append(iow.drain(5.0))
        dt = threading.Thread(target=_drain)
        dt.start()
        time.sleep(0.3)
        # 新实现:动作已计入 pending(即使尚未入队),seal/drain 排在
        # submit 之后,drain 必须仍在等待;
        # 旧实现:qsize+in_flight=0,drain 已返回 0(假完成)
        assert not result, \
            "通过 sealed 检查的 submit 未计入待完成集合前,drain 不得宣称完成"
        late_gate.set()
        dt.join(10)
        t.join(10)
        st_thread.join(10)
        assert result and result[0] == 0, "释放后动作完成,drain 真实清零"
        assert target.read_text(encoding="utf-8") == "v1"
        st = iow.stats()
        assert st["accepted"] == 1
        assert st["rejected_after_seal"] == 0  # 属于封口前批次,未被拒

    def test_rsa01_run_record_io_is_final_state(self, tmp_path):
        """§5.3 事前封口:seal→drain→哈希/summary/run_record——
        run_record 内嵌 io 即最终封口态(修复"写入时点态"勘误);
        封口后应急写入同步直走,不产生 rejected_after_seal 假象。"""
        sup = _sup(tmp_path)
        sup.expected = [{"role": "alerts",
                         "path": str(sup.alerts_path)}]
        (sup.run_dir / "alerts").mkdir(parents=True, exist_ok=True)
        sup.alerts_path.write_text("", encoding="utf-8")
        sup.log({"event": "pre_finalize"})
        sup.finalize()
        rr = json.loads(
            (sup.run_dir / "run_record.json").read_text(
                encoding="utf-8"))
        final = sup.iow.stats()
        assert rr["io"]["accepted"] == final["accepted"]
        assert rr["io"]["ok"] == final["ok"]
        assert rr["io"]["failed"] == final["failed"]
        assert rr["io"]["rejected_after_seal"] == \
            final["rejected_after_seal"]
        assert rr["evidence_complete"] is True
        assert sup.iow.is_sealed() is True
        # 封口后应急:submit 被 sealed 拒绝(如实计数)后同步直写
        # ——不伪装入队,run_record 封口快照不被迟事件污染
        before = sup.iow.stats()["rejected_after_seal"]
        sup.emergency_write({"event": "post_seal_emergency"})
        st = sup.iow.stats()
        assert st["rejected_after_seal"] == before + 1, \
            "封口后提交被拒必须如实计数(不静默)"
        assert st["accepted"] == final["accepted"], \
            "同步兜底不得伪装成入队成功"


# ================================================= RSA-02 有效样本输出边界
@requires_linux
class TestRSA02SampleBoundary:
    """独立审查 §4:reader 拒绝结果贯穿真实消费者(pump/失联判定)。"""

    def test_rsa02_pump_rejected_lines_do_not_refresh_liveness(
            self, tmp_path):
        """reader 拒绝(重复 seq/旧 utc)的样本不得经 pump 重新成为
        "刚收到的有效数据"刷新失联计时(旧实现 pump 对返回值重做
        弱校验后放行,掩盖真实断流)。"""
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(
            sup.win_path_guest, run_id=sup.run_id,
            started_iso=_utc_now(), predates_tolerance_s=300.0)
        sup.win_path_guest.write_text(
            json.dumps(_win(run_id=sup.run_id, seq=5)) + "\n",
            encoding="utf-8")
        first = sup._pump_win_lines(10.0)
        assert first is not None and first["seq"] == 5
        assert sup.last_win_line_mono == 10.0
        # 追加同 seq 重复 + 早于 run 的重放:reader 拒绝
        with sup.win_path_guest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_win(run_id=sup.run_id, seq=5,
                                     perf=_perf(free=1.0))) + "\n")
            fh.write(json.dumps(_win(
                run_id=sup.run_id, seq=6,
                utc="2020-01-01T00:00:00Z")) + "\n")
        second = sup._pump_win_lines(20.0)
        assert second is None, "被拒样本不得成为判定输入"
        assert sup.last_win_line_mono == 10.0, \
            "被拒样本不得刷新失联计时(旧实现刷新到 20)"
        assert sup.win_reader.duplicate_seq == 1
        assert sup.win_reader.stale_replayed == 1
        assert sup.win_reader.new_valid == []
        # 新有效样本(seq=7)到达:正常刷新(拒绝不误伤真实数据)
        with sup.win_path_guest.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_win(run_id=sup.run_id, seq=7)) + "\n")
        third = sup._pump_win_lines(30.0)
        assert third is not None and third["seq"] == 7
        assert sup.last_win_line_mono == 30.0

    def test_rsa02_non_object_json_no_crash(self, tmp_path):
        """合法 JSON null/标量行:解析成功但非对象——计解析错误、
        不入返回(旧实现 reader 的 obj.get 抛 AttributeError)。"""
        p = tmp_path / "win.jsonl"
        p.write_text("null\n" + "[1,2]\n" +
                     json.dumps(_win(seq=1)) + "\n", encoding="utf-8")
        rd = WinSampleReader(p, run_id=None)
        out = rd.read_new()           # 不得抛
        assert len(out) == 1 and out[0]["event"] == "sample"
        assert rd.parse_errors == 2
        assert rd.saw_valid is True
        # pump 消费同样不炸(事件循环 isinstance 纵深防御)
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(sup.win_path_guest,
                                         run_id=sup.run_id)
        sup.win_path_guest.write_text("null\n", encoding="utf-8")
        assert sup._pump_win_lines(1.0) is None

    def test_rsa02_live_reader_requires_run_id(self):
        """live reader 绑定 run 身份后,缺失 run_id 的旧格式拒绝
        (历史解释只在只读 reader run_id=None)。"""
        ok, reason = validate_win_sample(_win(), run_id="THIS")
        assert not ok and reason == "run_id_missing"

    def test_rsa02_guest_identity_and_seq_gate(self, tmp_path):
        """guest 生产侧闭合:_emit_guest 只让通过 run_id+seq+新鲜
        utc 全部闸门的样本刷新有效快照与失联计时。"""
        sup = _sup(tmp_path)

        def rec(seq, run_id="run", utc="now"):
            g = _guest()
            g["run_id"] = run_id
            g["seq"] = seq
            if utc != "now":
                g["utc"] = utc
            return g
        sup._emit_guest(rec(1))
        snap1 = sup._guest_snapshot()
        assert snap1 and snap1["seq"] == 1
        t1 = sup.last_guest_mono
        assert t1 is not None
        # 同 seq 重复:不刷新(重复消费不增加有效样本)
        sup._emit_guest(dict(snap1, utc=_utc_now()))
        assert sup._guest_snapshot() is snap1
        assert sup.guest_duplicate_seq == 1
        assert sup.last_guest_mono == t1
        # 序号回退:不刷新
        sup._emit_guest(rec(0))
        assert sup._guest_snapshot() is snap1
        assert sup.guest_seq_regressions == 1
        # 早于 run 启动的旧 utc:不刷新(重放)
        sup._emit_guest(rec(3, utc="2020-01-01T00:00:00Z"))
        assert sup._guest_snapshot() is snap1
        assert sup.guest_stale_replayed == 1
        # 缺失 run_id(live 旧格式后门):无效样本计数
        sup._emit_guest(rec(4, run_id=None))
        assert sup._guest_snapshot() is snap1
        assert sup.invalid_guest_samples == 1
        # 新有效样本:正常刷新
        sup._emit_guest(rec(5))
        snap2 = sup._guest_snapshot()
        assert snap2 and snap2["seq"] == 5
        assert sup.last_guest_mono >= t1


# ================================================= RSA-03 终态内容一致
@requires_linux
class TestRSA03TerminalContent:
    """独立审查 §5:终态内容/撤权/授权后取消与有效结果一致。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    SRC = SYNC / "src"
    RUNNER = SYNC / "stage2_6_1_runner"

    def _run_chain(self, tmp_path, behavior, mode="normal", timeout=120):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = tmp_path / "state"
        out = tmp_path / "out"
        script = tmp_path / "cf_runner.py"
        script.write_text(CF_RUNNER_SCRIPT, encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SRC) + os.pathsep + str(self.RUNNER),
            CURRICULUM261_R17_STATE_ROOT=str(state),
            R17_CF_BEHAVIOR=behavior,
            R17_CF_NAMESPACES="cf_ns_a")
        proc = subprocess.run(
            [sys.executable, str(script), str(self.SRC), str(state),
             str(out), behavior, mode],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=str(self.SYNC))
        journal = state / "r17_execution_journal.jsonl"
        events = [json.loads(l) for l in
                  journal.read_text(encoding="utf-8").splitlines() if l
                  ] if journal.is_file() else []
        mf = out / "manifest.jsonl"
        mlines = [json.loads(l) for l in
                  mf.read_text(encoding="utf-8").splitlines() if l
                  ] if mf.is_file() else []
        return proc, events, mlines, out

    @staticmethod
    def _terms(events):
        return [e for e in events
                if e["event"] == "qualification_terminal"]

    def test_rsa03_cancel_after_grant_worker_exit0_not_completed(
            self, tmp_path):
        """授权+token 交付完成后停止请求到达,worker 捕获 TERM 优雅
        exit 0:取消归因不丢失——raw rc=0 保留,资格终态 failed,
        步骤有效失败(旧实现正常 wait 路径不消费 stop_state→写
        completed)。"""
        proc, events, mlines, _out = self._run_chain(
            tmp_path, "term_exit0", mode="cancel_after_grant")
        assert '"ok": false' in proc.stdout, proc.stdout + proc.stderr
        rec = mlines[0]
        assert rec["rc"] == 0, "worker 优雅退出的 raw rc 保留(不改写)"
        d = rec["delegation"]
        assert d["cancelled"] is True
        assert "supervision_stop_after_grant" in (d.get("cancel_detail")
                                                  or "")
        assert rec["effective_result"] == "failed"
        assert rec["effective_failure"] == "delegation_cancelled"
        term = self._terms(events)
        assert term and term[0]["status"] == "failed", \
            "授权后取消不得写 completed"
        assert "cancelled" in term[0].get("note", "")
        assert not any(e.get("step") == "fixture_never"
                       for e in events)

    def test_rsa03_lookup_verifies_content_and_owner(self, monkeypatch):
        """只读核对返回事件内容并核对会话身份:他人 terminal 不匹配
        (存在性布尔不区分 failed/completed,不能替代内容核对)。"""
        import rl_curriculum.curriculum261_r17_execgov as eg
        import rl_curriculum.curriculum261_r17_workflow as wf

        class _S1:
            session_hash = "s1"

        class _S2:
            session_hash = "s2"
        fake = [{"event": "qualification_terminal",
                 "plan_digest": "d1", "status": "failed",
                 "owner": "s1", "note": "cf"}]
        monkeypatch.setattr(eg, "journal_entries",
                            lambda **kw: list(fake))
        e = wf._journal_terminal_lookup(_S1(), "d1")
        assert e is not None and e["status"] == "failed"
        assert wf._journal_terminal_lookup(_S2(), "d1") is None, \
            "他人会话的 terminal 不得被本会话恢复"

    def test_rsa03_step_failure_content_mismatch_rc0_only(self):
        """终态内容不符判定限定 rc=0 假成功窗口:crashed 记录的第一
        失败原因仍是进程事实,不贴内容不符标签。"""
        import rl_curriculum.curriculum261_r17_workflow as wf
        base = {"cancelled": False, "spawn_failed": None,
                "protocol_error": None, "worker_unconfirmed": False,
                "revoke_error": None, "terminal_state": "committed"}
        # rc=0+journal 恢复出 failed:假成功窗口→内容不符
        s = dict(base, terminal_status="failed", worker_rc=0)
        assert wf._delegation_step_failure(s) == \
            "qualification_terminal_content_mismatch"
        # rc=-15(crashed):进程事实已是第一失败原因,不贴 mismatch
        s2 = dict(base, terminal_status="crashed", worker_rc=-15)
        assert wf._delegation_step_failure(s2) is None
        # 旧 summary 无 terminal_status 字段:宽容不判(增量兼容)
        s3 = dict(base, worker_rc=0)
        assert wf._delegation_step_failure(s3) is None
