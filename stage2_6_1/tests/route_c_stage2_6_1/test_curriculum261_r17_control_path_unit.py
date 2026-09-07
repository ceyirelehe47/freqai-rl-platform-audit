# -*- coding: utf-8 -*-
"""R17 控制路径可靠性测试矩阵(任务书 §10 T01-T24 可夹具化项)。

真实模块/真实进程为主:WinSampleReader/就绪屏障/Supervisor 主循环/
Protector/启动准入全部 import 发布仓库 runner 实现;I/O 故障、时钟
与样本由隔离依赖注入(生产入口不暴露注入通道)。T08-T15(真实资格
委派)在 TestDelegationLifecycle;T21(真实 Agent 接收)证据在
control_path_reliability/receipts/,不在 pytest 内。
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
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
    BoundedIOWriter, POLICY, Protector, Supervisor, WinSampleReader,
    validate_guest_sample, validate_win_sample)

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
    """必需卷完整有效状态(F: required+C: optional;WP3 §6.2)。"""
    return [{"vol": "F:", "present": True, "free_gb": 100.0,
             "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
            {"vol": "C:", "present": True, "free_gb": 200.0,
             "size_gb": 900.0, "serial": "CCA1", "identity_match": True}]


_SEQ = itertools.count(1)


def _win(perf=None, run_id=None, vols="default", utc="now", seq="auto",
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
    if seq == "auto":
        seq = next(_SEQ)
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
    if argv and argv[0] == "--":  # main() 同款剥离;直构路径不剥会
        argv = argv[1:]            # 把 '--' 当可执行文件
    args = argparse.Namespace(
        run_dir=str(tmp_path / "run"), task_kind=task_kind,
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source=samples_source, win_sampler_ps1="/nonexistent.ps1",
        win_volumes="C:,F:", expect_artifact=expect or [],
        obs_ready_deadline=30.0)
    return Supervisor(args)


# ================================================= T01-T04 有效就绪
@requires_linux
class TestValidReadiness:
    """B1:就绪只认有效资源样本;解析成功/来源启动/有效三层分开;
    启动资源准入独立判定。"""

    def test_t01_start_only_and_empty_not_ready(self, tmp_path):
        """host 只有 sampler_start/空 perf sample:实际就绪路径到期
        拒绝(旧行为:saw_any 置位→放行)。"""
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(sup.win_path_guest,
                                         run_id=sup.run_id)
        sup.win_path_guest.write_text(
            json.dumps({"event": "sampler_start", "run_id": sup.run_id,
                        "pid": 111}) + "\n" +
            json.dumps({"event": "sample", "run_id": sup.run_id,
                        "perf": {}}) + "\n",
            encoding="utf-8")
        with sup._guest_lock:
            sup._guest_latest = _guest()
        t0 = time.monotonic()
        ok, detail = sup._wait_observation_ready(
            replay=False, win_started=True, deadline_s=0.8)
        assert not ok
        assert "win_no_valid_sample" in detail
        assert time.monotonic() - t0 >= 0.7  # 到期拒绝(不是即刻误判)
        # 就绪失败→零业务 spawn
        assert sup.biz_proc is None
        # reader 层事实:saw_any(诊断)与 saw_valid(就绪)分层
        assert sup.win_reader.saw_any is True
        assert sup.win_reader.saw_valid is False
        assert sup.win_reader.invalid_samples == 1

    def test_t01_no_resource_lines_at_all(self, tmp_path):
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(sup.win_path_guest,
                                         run_id=sup.run_id)
        sup.win_path_guest.write_text(
            json.dumps({"event": "sampler_start", "run_id": sup.run_id,
                        "pid": 1}) + "\n", encoding="utf-8")
        ok, detail = sup._wait_observation_ready(
            replay=False, win_started=True, deadline_s=0.5)
        assert not ok and "win_no_valid_sample" in detail

    @pytest.mark.parametrize("perf,frag", [
        ({"phys_avail_gb": float("nan"), "phys_total_gb": 63.0,
          "commit_total_gb": 38.0, "commit_limit_gb": 83.0}, "phys_avail"),
        ({"phys_avail_gb": -5.0, "phys_total_gb": 63.0,
          "commit_total_gb": 38.0, "commit_limit_gb": 83.0}, "negative"),
        ({"phys_avail_gb": 500.0, "phys_total_gb": 63.0,
          "commit_total_gb": 38.0, "commit_limit_gb": 83.0}, "avail_gt"),
        ({"phys_total_gb": 0.0, "phys_avail_gb": 1.0,
          "commit_total_gb": 38.0, "commit_limit_gb": 83.0}, "denominator"),
        ({"phys_avail_gb": 39.0, "commit_total_gb": 90.0,
          "commit_limit_gb": 83.0}, "commit_gt"),
        ({"phys_avail_gb": 39.0}, "missing"),
    ])
    def test_t02_invalid_win_samples_rejected(self, tmp_path, perf, frag):
        ok, reason = validate_win_sample(_win(perf))
        assert not ok and reason.startswith("perf_invalid")
        # reader 层:不成为有效首样本
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(sup.win_path_guest,
                                         run_id=sup.run_id)
        sup.win_path_guest.write_text(
            json.dumps(_win(perf)) + "\n", encoding="utf-8")
        sup.win_reader.read_new()
        assert sup.win_reader.saw_valid is False
        assert sup.win_reader.invalid_samples == 1

    def test_t02_wrong_run_id_rejected(self):
        ok, reason = validate_win_sample(_win(_perf(), run_id="OTHER"),
                                         run_id="THIS")
        assert not ok and reason == "run_id_mismatch"

    def test_t02_dangerous_zero_is_valid_but_admitted_no(self, tmp_path):
        """零可用内存=有效但危险:不误记缺测后放行;启动准入拒绝。"""
        ok, _ = validate_win_sample(_win(_perf(free=0.0)))
        assert ok, "危险零值是有效数据,不得记为缺测"
        sup = _sup(tmp_path)
        admitted, detail = sup.admission_check(
            _win(_perf(free=0.0)), _guest())
        assert not admitted and "win_free" in detail

    @pytest.mark.parametrize("guest", [
        {"event": "guest_sample", "utc": "t",
         "meminfo": {"MemAvailable": 1000}},                # 缺 MemTotal
        {"event": "guest_sample", "utc": "t",
         "meminfo": {"MemTotal": 1000, "MemAvailable": float("nan")}},
        {"event": "guest_sample", "utc": "t",
         "meminfo": {"MemTotal": 1000, "MemAvailable": 5000}},  # avail>total
        {"event": "guest_sample",  # 缺 utc 身份
         "meminfo": {"MemTotal": 1000, "MemAvailable": 500}},
        {"event": "other", "utc": "t",
         "meminfo": {"MemTotal": 1, "MemAvailable": 1}},
    ])
    def test_t02_invalid_guest_forms(self, guest):
        ok, reason = validate_guest_sample(guest)
        assert not ok
        # 无效 guest 不刷新有效快照(_emit_guest 路径)
        # (直接调 validate;emit 落盘在 t04 验证)

    def test_t03_admission_gate_values(self, tmp_path):
        sup = _sup(tmp_path)
        # 足够:通过
        ok, detail = sup.admission_check(_win(_perf()), _guest())
        assert ok and detail == "ok"
        # win 内存不足
        ok, d = sup.admission_check(_win(_perf(free=7.9)), _guest())
        assert not ok and "win_free" in d
        # commit ≥90%
        ok, d = sup.admission_check(
            _win(_perf(ct=75.0, cl=83.0)), _guest())
        assert not ok and "win_commit" in d
        # guest 不足
        ok, d = sup.admission_check(_win(_perf()),
                                    _guest(avail_kb=3_000_000))
        assert not ok and "guest_avail" in d
        # 关键输出卷余量不足
        ok, d = sup.admission_check(
            _win(_perf(), vols=[{"vol": "F:", "present": True,
                                 "free_gb": 10.0}]), _guest())
        assert not ok and "keyvol_free" in d
        # 缺某侧有效数据:按不可判定拒绝
        ok, d = sup.admission_check(None, _guest())
        assert not ok
        ok, d = sup.admission_check(_win(_perf()), None)
        assert not ok

    def test_t03_replay_run_denied_without_spawn(self, tmp_path):
        """有效但初始资源不足:run() 级按既定准入结束(rc=94),
        business spawn=0,不自动重开已结束 run。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf(free=7.5)),
                        "guest": _guest(avail_kb=3_000_000)}) + "\n",
            encoding="utf-8")
        sup = _sup(tmp_path, argv=["--", "bash", "-c",
                                   "echo should-not-run"],
                   samples_source=f"file:{samples}")
        rc = sup.run()
        assert rc == 94
        assert not (tmp_path / "run" / "business" / "stdout.log").exists()
        assert (tmp_path / "run" / "run_record.json").is_file()
        sup.iow.drain(5)
        alerts = (tmp_path / "run" / "alerts" /
                  "alerts.jsonl").read_text(encoding="utf-8")
        assert "startup_admission_denied" in alerts

    def test_t04_partial_line_and_no_refresh(self, tmp_path):
        """半行留缓冲;无效行/重复读不刷新有效性时间。"""
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(sup.win_path_guest,
                                         run_id=sup.run_id)
        # 有效行 + NaN 坏数值行(json.loads 接受 NaN 字面量)+
        # 末尾半行(留缓冲)
        sup.win_path_guest.write_bytes(
            json.dumps(_win(_perf())).encode() + b"\n" +
            json.dumps(_win(_perf(free=float("nan")))).encode() + b"\n" +
            b'{"event":"sam')
        lines = sup.win_reader.read_new()
        assert len(lines) == 2
        assert sup.win_reader.saw_valid is True
        assert sup.win_reader.invalid_samples == 1
        first_valid_mono = sup.win_reader.last_valid_mono
        # 无新内容重复读:状态不变(半行不成行、不计数)
        sup.win_reader.read_new()
        assert sup.win_reader.parse_errors == 0
        assert sup.win_reader.last_valid_mono == first_valid_mono
        # 追加无效样本行(先终结缓冲中的半行成坏行):解析成功但
        # 无效,不刷新有效时间
        time.sleep(0.02)
        with sup.win_path_guest.open("ab") as fh:
            fh.write(b"\n" +
                     json.dumps(_win(_perf(free=-1.0))).encode() + b"\n")
        lines = sup.win_reader.read_new()
        assert len(lines) == 1 and sup.win_reader.invalid_samples == 2
        assert sup.win_reader.parse_errors == 1  # 半行终结成坏行
        assert sup.win_reader.last_valid_mono == first_valid_mono, \
            "无效行不得刷新有效样本时间(§4.3)"

    def test_t04_invalid_guest_not_snapshot(self, tmp_path):
        sup = _sup(tmp_path)
        bad = {"event": "guest_sample", "utc": "t",
               "meminfo": {"MemAvailable": 1000}}  # 缺 MemTotal
        sup._emit_guest(bad)  # 落盘保留诊断
        assert sup._guest_snapshot() is None, "无效样本不得进有效快照"
        assert sup.invalid_guest_samples == 1
        assert sup.guest_path.read_text(encoding="utf-8").strip(), \
            "无效样本仍落盘(诊断保留;不算有效)"

    def test_t04_sampler_restart_recorded(self, tmp_path):
        """来源重启(同流新 sampler_start 不同 pid):如实记录事件。"""
        sup = _sup(tmp_path)
        sup.win_reader = WinSampleReader(sup.win_path_guest,
                                         run_id=sup.run_id)
        sup.win_path_guest.write_text(
            json.dumps({"event": "sampler_start", "pid": 11}) + "\n" +
            json.dumps(_win(_perf())) + "\n" +
            json.dumps({"event": "sampler_start", "pid": 22}) + "\n",
            encoding="utf-8")
        sup._pump_win_lines(1.0)
        sup.iow.drain(5)
        alerts = sup.alerts_path.read_text(encoding="utf-8")
        assert "win_sampler_restarted" in alerts


# ================================================= T05-T07 阻塞 I/O 保护
@requires_linux
class TestBlockingProtection:
    """B2:控制链不同步等待日志/stdout/应急写;阻塞保持期间真实
    TERM/KILL/收尾仍推进。"""

    @staticmethod
    def _proc_start_ticks(pid):
        with open(f"/proc/{pid}/stat") as fh:
            text = fh.read()
        return int(text[text.rindex(")") + 2:].split()[19])

    def test_t05_request_stop_not_blocked_by_log(self):
        """阻塞日志回调(挂起 30s 不返回不抛异常):停止请求必须
        先发信号(旧行为:先 _safe_log 同步写→卡 30s)。"""
        leader = subprocess.Popen(
            ["bash", "-c", "sleep 30"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            time.sleep(0.3)
            pgid = os.getpgid(leader.pid)

            def stuck_log(rec):
                time.sleep(30)  # 磁盘写挂起形态:不返回也不抛异常
            prot = Protector(
                pgid, 1.5, stuck_log,
                leader_pid=leader.pid,
                leader_start_ticks=self._proc_start_ticks(leader.pid),
                mono_fn=time.monotonic)
            t0 = time.monotonic()
            prot.request_stop("t05")
            dt = time.monotonic() - t0
            assert dt < 2.0, f"停止请求被日志 I/O 拖住 {dt:.1f}s"
            assert prot.term_sent_at is not None, "信号必须已发送"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and leader.poll() is None:
                time.sleep(0.1)
            assert leader.poll() is not None, "TERM 必须真实作用业务"
        finally:
            if leader.poll() is None:
                leader.kill()
                leader.wait(timeout=10)

    def test_t06_stdout_full_pipe_does_not_block_control(self, tmp_path):
        """stdout 管道写满+消费者不读:递交投递即刻返回;真实业务
        (忽略 TERM)仍按时 TERM→KILL 升级(阻塞持续存在)。"""
        r_fd, w_fd = os.pipe()  # 64KiB 缓冲
        # 填满管道(消费者保持打开但不读取)
        os.set_blocking(w_fd, False)
        filler = b"x" * 4096
        filled = 0
        while True:
            try:
                filled += os.write(w_fd, filler)
            except BlockingIOError:
                break
        assert filled >= 32 * 1024, "管道必须已被填满"
        os.set_blocking(w_fd, True)
        sup = _sup(tmp_path, argv=["--", "bash", "-c",
                                   'trap "" TERM; sleep 60'])
        sup.policy["coop_exit_window_s"] = 1.0
        old_stdout = sys.stdout
        sys.stdout = os.fdopen(w_fd, "w", buffering=1)
        try:
            sup.spawn_business()
            # 等业务的 trap 忽略处置就位(否则 TERM 在 bash 完成
            # trap 设置前到达=竞态杀死业务,测不到升级路径)
            time.sleep(0.6)
            assert sup.biz_proc.poll() is None, "业务应活着(trap 就位)"
            # 递交面写满管道:投递必须即刻返回(io 线程承接阻塞)
            t0 = time.monotonic()
            sup.stdout_line("R17ALERT", {"event": "t06", "n": 1})
            assert time.monotonic() - t0 < 1.0
            # 保护控制路径完全不等 stdout
            sup.handle_triggers([{
                "kind": "win_free_phys", "severity": "CRITICAL",
                "detail": "t06 注入", "metrics": {}}])
            assert sup.protector.term_sent_at is not None
            # 阻塞保持期间升级 KILL 仍推进(io 线程卡在满管道上)
            clock = time.monotonic
            deadline = clock() + 8
            while clock() < deadline:
                sup.protector.poll(clock())
                if sup.protector.kill_sent_at is not None:
                    break
                time.sleep(0.2)
            assert sup.protector.kill_sent_at is not None, \
                "stdout 阻塞不得饿死升级"
            deadline = clock() + 8
            while clock() < deadline and sup.biz_proc.poll() is None:
                sup.protector.poll(clock())
                time.sleep(0.2)
            assert sup.biz_proc.poll() is not None, "忽略 TERM 也必须被 KILL"
            assert not sup.protector._member_pids()
        finally:
            sys.stdout = old_stdout
            try:
                os.close(w_fd)
            except OSError:
                pass
            # 排空读端防止写线程永久卡死(测试清理自身资源)
            try:
                os.set_blocking(r_fd, False)
                while True:
                    if not os.read(r_fd, 65536):
                        break
            except BlockingIOError:
                pass
            finally:
                os.close(r_fd)
            if sup.biz_proc and sup.biz_proc.poll() is None:
                os.killpg(os.getpgid(sup.biz_proc.pid), 9)

    def test_t07_broken_streams_and_emergency_failure(self, tmp_path):
        """BrokenPipe/关闭流/应急写失败:先保护后尽力证据;失败计数;
        handle_triggers 不抛出。"""
        import io as _io
        sup = _sup(tmp_path)
        # 应急目录不可写(文件占位目录路径)
        (tmp_path / "notdir").write_text("x", encoding="utf-8")
        sup.emergency_win_dir = str(tmp_path / "notdir" / "sub")
        sup.emergency_write({"event": "t07_emerg"})
        closed = _io.TextIOWrapper(_io.BytesIO(), encoding="utf-8")
        closed.close()
        old_stdout = sys.stdout
        sys.stdout = closed
        try:
            sup.handle_triggers([{
                "kind": "win_commit", "severity": "CRITICAL",
                "detail": "t07(测试)", "metrics": {}}])
            # 在闭流窗口内执行递交(print 必须在 closed 流上失败)
            sup.iow.drain(5)
        finally:
            sys.stdout = old_stdout
        assert sup.stop_requested_reasons, "流断裂不得阻止停止意图"
        assert sup.stdout_failures > 0, "关闭流的递交失败必须计数"

    def test_t07_summary_write_failure_emergency(self, tmp_path):
        """summary 落盘失败:应急兜底尝试,不抛出,run_record 照常
        封口(summary 缺件如实 missing)。"""
        sup = _sup(tmp_path)
        sum_dir = tmp_path / "run" / "summary.json"
        sum_dir.parent.mkdir(parents=True, exist_ok=True)
        sum_dir.mkdir()  # 占位:write_text 将抛 IsADirectoryError
        summary = sup.write_summary()  # 不得抛出
        assert summary["run_id"] == "run"
        rr = sup.finalize_run_record()
        rec = json.loads(rr.read_text(encoding="utf-8"))
        roles = {r["role"]: r for r in rec["required"]}
        assert roles["summary"]["status"] == "missing"
        assert rec["evidence_complete"] is False


# ================================================= T16-T18 残留收尾
@requires_linux
class TestResidualClosure:
    """B4:正常 leader 退出核验后代;residual 有界收尾;外层 rc 维度。"""

    def test_t16_leader_rc0_with_children_not_overall_success(
            self, tmp_path):
        """leader rc=0 但子进程仍在:不整体 PASS;识别+受控清理;
        邻近无关进程存活。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        sup = _sup(tmp_path, argv=["--", "bash", "-c",
                                   "sleep 60 & exit 0"],
                   samples_source=f"file:{samples}")
        sup.policy["coop_exit_window_s"] = 1.0
        sup.policy["default_max_seconds"] = 60
        neighbor = subprocess.Popen(
            ["sleep", "60"], start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            rc = sup.run()
            assert sup.biz_rc == 0, "前提:业务 leader 本身 rc=0"
            assert rc != 0, "leader rc=0+残留清理后不得整体 rc=0"
            assert rc == 4, f"保护性清理(residual)→rc=4,实际 {rc}"
            sup.iow.drain(5)
            alerts = sup.alerts_path.read_text(encoding="utf-8")
            assert "residual_task_after_leader_exit" in alerts
            assert "residual_task" in alerts  # CRITICAL 事件
            assert '"event":"sigterm_sent"' in alerts
            # 残留子进程被登记组信号清理
            assert not sup.protector._member_pids()
            # 邻近无关进程不受波及
            assert neighbor.poll() is None
        finally:
            if neighbor.poll() is None:
                neighbor.kill()
                neighbor.wait(timeout=10)

    def test_t17_kill_denied_residual_unconfirmed_bounded(self, tmp_path):
        """KILL 权限不足(注入)→完成未证实:有界退出诊断控制流,
        residual_unconfirmed 如实记录+rc=5,不无限 continue。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        # run_timeout(5s)触发停止→TERM 被忽略→KILL 被注入拒绝→
        # 保护未证实:诊断控制流在硬上界内退出(§7.2)
        sup = _sup(tmp_path, argv=["--", "bash", "-c",
                                   'trap "" TERM; sleep 120'],
                   samples_source=f"file:{samples}")
        sup.policy["coop_exit_window_s"] = 1.0
        sup.policy["default_max_seconds"] = 5
        _sig = Protector._signal

        def denied(self, sig):
            if sig == 9:
                raise PermissionError("t17 注入:KILL 被拒")
            _sig(self, sig)
        Protector._signal = denied
        try:
            t0 = time.monotonic()
            rc = sup.run()
            dt = time.monotonic() - t0
            # 有界:max_s(5)+硬上界(coop1+10+25)之内退出
            assert dt < 50, f"收尾必须有限(实际 {dt:.1f}s)"
            assert sup.residual_unconfirmed is True
            assert rc == 5, f"完成未证实→rc=5,实际 {rc}"
            sup.iow.drain(5)
            alerts = sup.alerts_path.read_text(encoding="utf-8")
            assert "signal_denied" in alerts or "kill_ineffective" \
                in alerts
        finally:
            Protector._signal = _sig
            if sup.biz_proc and sup.biz_proc.poll() is None:
                os.killpg(os.getpgid(sup.biz_proc.pid), 9)
                sup.biz_proc.wait(timeout=10)

    def test_t18_finalize_and_outcome_idempotent(self, tmp_path):
        """重复 finalize/重复 control_outcome 幂等:不产生第二个
        run_record/重复释放形态。"""
        # replay 形态:必需集合不含双采样流(回放输入替代,§8.2)
        sup = _sup(tmp_path, samples_source="file:test")
        sup.biz_rc = 0
        for p in (sup.alerts_path, sup.biz_stdout, sup.biz_stderr):
            p.write_text("x\n", encoding="utf-8")
        (tmp_path / "run" / "summary.json").write_text(
            "{}", encoding="utf-8")
        sup.finalize()
        rr1 = (tmp_path / "run" / "run_record.json").read_bytes()
        sup.finalize()
        rr2 = (tmp_path / "run" / "run_record.json").read_bytes()
        assert rr1 == rr2
        assert sup.control_outcome() == sup.control_outcome() == 0

    def test_t18_live_writers_mark_uncertain_hash(self, tmp_path):
        """写入者未证实退出:业务流哈希标记 live_writers,不宣称
        原始流固定(§7.2)。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        sup = _sup(tmp_path, argv=["--", "bash", "-c",
                                   'trap "" TERM; exec sleep 60'],
                   samples_source=f"file:{samples}")
        sup.policy["coop_exit_window_s"] = 0.5
        sup.policy["default_max_seconds"] = 60
        try:
            rc = sup.run()
            # 忽略 TERM 的业务:KILL 后确认;若实现机器上即时 reap
            # 则无 live 标记——两种都接受,但证据字段必须在
            rec = json.loads((tmp_path / "run" / "run_record.json")
                             .read_text(encoding="utf-8"))
            roles = {r["role"]: r for r in rec["required"]}
            for role in ("business_stdout", "business_stderr"):
                if sup.residual_unconfirmed or (
                        sup.protector.terminal_at is None):
                    assert roles[role].get("live_writers") is True
        finally:
            if sup.biz_proc and sup.biz_proc.poll() is None:
                os.killpg(os.getpgid(sup.biz_proc.pid), 9)
                sup.biz_proc.wait(timeout=10)


# ================================================= T19-T20 角色与交付
@requires_linux
class TestRoleRequirement:
    """B5:task_kind=pytest 的 JUnit 必需角色由类型决定,不靠字符串
    运气;登记/产生/封口/验证分层。"""

    def test_t19_element_split_form_with_spaces(self, tmp_path):
        jp = tmp_path / "re sult dir" / "j.xml"
        sup = _sup(tmp_path, argv=["--", "python", "-m", "pytest",
                                   "--junitxml", str(jp), "-q"])
        roles = {e["role"]: e for e in sup.expected}
        assert roles["junit_xml"]["path"] == jp.resolve()

    def test_t19_pytest_missing_junit_rejected_before_spawn(self, tmp_path):
        sup = _sup(tmp_path, argv=["--", "python", "-m", "pytest", "-q"],
                   task_kind="pytest")
        assert sup._startup_reject and "junit_missing" in \
            sup._startup_reject
        rc = sup.run()
        assert rc == 2
        assert not (tmp_path / "run" / "business" / "stdout.log").exists()

    def test_t19_bash_c_split_form_requires_explicit(self, tmp_path):
        sup = _sup(tmp_path, argv=["--", "bash", "-c",
                                   "python -m pytest tests "
                                   "--junitxml out.xml -q"],
                   task_kind="pytest")
        assert sup._startup_reject and "ambiguous" in sup._startup_reject
        rc = sup.run()
        assert rc == 2

    def test_t19_conflict_rejected(self, tmp_path):
        sup = _sup(tmp_path, argv=["--", "python", "-m", "pytest",
                                   "--junitxml", str(tmp_path / "a.xml"),
                                   "-q"],
                   task_kind="pytest",
                   expect=[f"junit_xml={tmp_path / 'b.xml'}"])
        assert sup._startup_reject and "junit_conflict" in \
            sup._startup_reject

    def test_t19_explicit_registration_maps_to_canonical_role(
            self, tmp_path):
        jp = tmp_path / "declared.xml"
        sup = _sup(tmp_path, argv=["--", "python", "-m", "pytest", "-q"],
                   task_kind="pytest", expect=[f"junit_xml={jp}"])
        assert sup._startup_reject is None
        roles = [e["role"] for e in sup.expected]
        assert "junit_xml" in roles
        assert "declared:junit_xml" not in roles, \
            "junit 显式登记必须映射规范必需角色(§8.1)"
        j = next(e for e in sup.expected if e["role"] == "junit_xml")
        assert j["path"] == jp.resolve()

    def test_t20_required_set_not_shrunk_by_absence(self, tmp_path):
        """缺件保留为缺件:必需集合不随现实缩小;verify FAIL。"""
        sup = _sup(tmp_path, argv=["--", "python", "-m", "pytest",
                                   "--junitxml=" + str(tmp_path / "j.xml"),
                                   "-q"])
        sup.alerts_path.write_text('{"event":"e"}\n', encoding="utf-8")
        sup.biz_stdout.write_text("o\n", encoding="utf-8")
        sup.biz_stderr.write_bytes(b"")
        # summary/junit/双遥测缺失
        sup.finalize_run_record()
        rec = json.loads((tmp_path / "run" / "run_record.json")
                         .read_text(encoding="utf-8"))
        roles = {r["role"] for r in rec["required"]}
        assert {"telemetry_guest", "telemetry_win", "alerts",
                "business_stdout", "business_stderr", "summary",
                "junit_xml"} <= roles, "必需集合不得缩小"
        assert rec["evidence_complete"] is False
        # build 可组包(清单反映现实),verify FAIL
        root = sup.run_dir.parent.parent
        manifest = sup.run_dir / "manifest.jsonl"
        anchor = tmp_path / "anchor.json"
        rr_path = tmp_path / "run" / "run_record.json"
        b = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "build", "--run-record", str(rr_path),
             "--manifest-out", str(manifest),
             "--anchor-out", str(anchor), "--root", str(root)],
            capture_output=True, text=True)
        assert b.returncode == 0, b.stderr
        v = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "verify", "--root", str(root), "--manifest", str(manifest),
             "--anchor-file", str(anchor), "--run-record", str(rr_path),
             "--receipt-dir", str(tmp_path / "receipts")],
            capture_output=True, text=True)
        assert v.returncode == 1
        assert "evidence_incomplete" in v.stderr


# ================================================= T08-T15 真实资格委派
CF_RUNNER_SCRIPT = r'''
import json
import os
import signal
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
behavior, mode = sys.argv[4], sys.argv[5]
wf.R17_WORKFLOW_CLI_MODULE = "r17_control_fixture_worker"
wf.QUALIFY_HANDSHAKE_DEADLINE_S = float(
    os.environ.get("R17_CF_DEADLINE", "30"))

if mode == "spawn_fail":
    _real_popen = wf.subprocess.Popen

    def _popen(argv, **kw):
        if any("--await-delegation" in str(a) for a in argv):
            raise OSError("cf 注入:qualify spawn 失败")
        return _real_popen(argv, **kw)
    wf.subprocess.Popen = _popen
elif mode in ("cancel_read", "cancel_grant"):
    _real_read = wf._read_pipe_line

    def _read(fd, **kw):
        if mode == "cancel_read":
            os.kill(os.getpid(), signal.SIGTERM)
        line = _real_read(fd, **kw)
        if mode == "cancel_grant":
            os.kill(os.getpid(), signal.SIGTERM)
        return line
    wf._read_pipe_line = _read

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
    {"ok": result["ok"], "failed": result["failed_step"]}))
if not result["ok"]:
    session.record_iteration_aborted(result["failure_reason"][:2000])
session.release(summary="cf fixture")
'''


@requires_linux
class TestDelegationLifecycle:
    """B3:真实 qualify 委派(真实协调者/session/journal/grant 机制+
    独立 worker 进程;CONTROL_FIXTURE_TEST,无业务数据/seed/正式 ns)。

    路径:真实 execute_workflow_chain_r17 → _qualify_delegation_
    open/spawn/handshake/close → 真实 R17ChainSession.issue/revoke/
    terminal → 唯一 journal writer 的关闭记录(§6.5)。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    SRC = SYNC / "src"
    RUNNER = SYNC / "stage2_6_1_runner"

    @staticmethod
    def _events(journal):
        return [json.loads(l) for l in
                journal.read_text(encoding="utf-8").splitlines() if l]

    def _run_chain(self, tmp_path, behavior, mode="normal",
                   deadline="30", timeout=120):
        import tempfile
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = tmp_path / "state"
        out = tmp_path / "out"
        script = tmp_path / "cf_runner.py"
        script.write_text(CF_RUNNER_SCRIPT, encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SRC) + os.pathsep +
            str(self.RUNNER),
            CURRICULUM261_R17_STATE_ROOT=str(state),
            R17_CF_DEADLINE=deadline,
            R17_CF_BEHAVIOR=behavior,
            R17_CF_NAMESPACES="cf_ns_a")
        proc = subprocess.run(
            [sys.executable, str(script), str(self.SRC), str(state),
             str(out), behavior, mode],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=str(self.SYNC))
        journal = state / "r17_execution_journal.jsonl"
        events = self._events(journal) if journal.is_file() else []
        manifest_lines = []
        mf = out / "manifest.jsonl"
        if mf.is_file():
            manifest_lines = [json.loads(l) for l in
                              mf.read_text(encoding="utf-8").splitlines()
                              if l]
        return proc, events, manifest_lines, out

    @staticmethod
    def _qualify_rec(manifest_lines):
        for rec in manifest_lines:
            if rec.get("step") == "qualify":
                return rec
        return None

    def test_t08_normal_handshake_grant_and_closure(self, tmp_path):
        proc, events, mlines, out = self._run_chain(tmp_path, "normal")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "CFQUAL" in proc.stdout and '"ok": true' in proc.stdout
        seq = [e["event"] for e in events]
        # 真实工程授权:exposure→grant→revoke→terminal(completed)
        assert "chain_exposure_started" in seq
        assert seq.count("grant_issued") == 1
        assert seq.count("grant_revoked") == 1
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert len(term) == 1 and \
            term[0].get("status") == "completed"
        rec = self._qualify_rec(mlines)
        d = rec["delegation"]
        assert d["identity_verified"] is True
        assert d["grant_issued"] is True and d["cancelled"] is False
        assert d["protocol_error"] is None and \
            d["revoke_error"] is None
        # 唯一 journal writer
        writers = {e.get("writer") for e in events if "writer" in e}
        assert writers <= {"chain_session_owner"}, writers
        assert '"token"' not in json.dumps(d), "不得记录明文 token"

    def test_t09_worker_exit_before_identity(self, tmp_path):
        proc, events, mlines, out = self._run_chain(
            tmp_path, "early_exit")
        seq = [e["event"] for e in events]
        assert seq.count("grant_issued") == 0, "未发 grant"
        rec = self._qualify_rec(mlines)
        assert rec["rc"] == 7  # 真实 worker rc 透传
        assert "identity_pipe_eof" in (rec["delegation"]
                                       ["protocol_error"] or "")
        assert not any(e.get("step") == "fixture_never" and
                       e["event"].startswith("chain_step")
                       for e in events)
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and term[0].get("status") == "failed"

    def test_t09_spawn_failure_keeps_exposure(self, tmp_path):
        """spawn 失败:exposure 已持久化不退回;失败阶段记录;
        有界报错(不悬挂)。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "normal", mode="spawn_fail", timeout=90)
        seq = [e["event"] for e in events]
        assert "chain_exposure_started" in seq, "exposure 不退回"
        rec = self._qualify_rec(mlines)
        assert rec["rc"] == 98
        assert rec["delegation"]["spawn_failed"]
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and "spawn_failed" in term[0].get("note", "")

    @pytest.mark.parametrize("behavior,frag", [
        ("half_line", "identity_pipe_eof"),
        ("no_msg", "handshake_deadline_exceeded"),
        ("bad_json", "identity_bad_json"),
        ("oversized", "identity_message_oversized"),
    ])
    def test_t10_malformed_identity_bounded(self, tmp_path, behavior,
                                            frag):
        """半行/不发/坏 JSON/超长:统一 deadline/长度限制;无无限
        读取;第一失败原因与 cleanup 分开(旧行为=readline 永悬挂)。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, behavior, deadline="2", timeout=90)
        rec = self._qualify_rec(mlines)
        d = rec["delegation"]
        assert frag in (d["protocol_error"] or ""), d
        assert d["identity_verified"] is not True
        assert [e for e in events
                if e["event"] == "grant_issued"] == []
        if behavior == "no_msg":
            assert rec["signal"] == 15, "长睡眠 worker 被 terminate"

    @pytest.mark.parametrize("behavior,frag", [
        ("wrong_identity", "identity_mismatch"),
        ("extra_ns", "namespaces_out_of_scope"),
    ])
    def test_t11_fake_identity_and_extra_namespaces(self, tmp_path,
                                                    behavior, frag):
        proc, events, mlines, out = self._run_chain(
            tmp_path, behavior, deadline="5", timeout=120)
        rec = self._qualify_rec(mlines)
        d = rec["delegation"]
        assert frag in (d["protocol_error"] or "")
        assert d["grant_issued"] is False
        assert [e for e in events
                if e["event"] == "grant_issued"] == []

    @pytest.mark.parametrize("mode", ["cancel_read", "cancel_grant"])
    def test_t12_cancel_before_grant_no_new_grant(self, tmp_path, mode):
        """注册前/完整身份消息后、发 grant 前收到取消:取消先被
        接受→不创建/发送 grant;后续步骤为零(真实 SIGTERM 路径,
        barrier=读管道包装注入点)。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "normal", mode=mode, timeout=120)
        seq = [e["event"] for e in events]
        assert seq.count("grant_issued") == 0, "取消后不得新建 grant"
        rec = self._qualify_rec(mlines)
        assert rec["delegation"]["cancelled"] is True
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and term[0].get("status") == "failed"
        assert "cancelled" in term[0].get("note", "")
        assert not any(e.get("step") == "fixture_never" and
                       e["event"].startswith("chain_step")
                       for e in events), "后续步骤必须为零"

    def test_t13_token_delivery_failure_revokes_grant(self, tmp_path):
        """grant 已建、token 写入 BrokenPipe(worker 关读端退出):
        有界写;已有 grant 撤销;不遗留有效权限或二次下发。"""
        proc, events, mlines, out = self._run_chain(
            tmp_path, "close_token_read", timeout=120)
        seq = [e["event"] for e in events]
        assert seq.count("grant_issued") == 1
        assert seq.count("grant_revoked") == 1, "未确认交付必须撤销"
        rec = self._qualify_rec(mlines)
        d = rec["delegation"]
        assert d["token_delivery_failed"], "BrokenPipe 必须记录"
        assert d["identity_verified"] is True
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and term[0].get("status") == "failed"

    def test_t14_real_supervisor_stops_coordinator_after_grant(
            self, tmp_path):
        """实际授权后由真实 supervisor 检测 CRITICAL:协调者接受
        取消、原 writer 撤销/终态/收尾、二次准入拒(不是直接
        proc.terminate 替代 supervisor 路径)。

        supervisor 从头监护协调者(唯一实例);回放样本先给足
        正常样本(60×0.05s≈3s)让握手+grant 完成,再注入 keyvol
        CRITICAL(单样本瞬时)→supervisor 对登记组发 TERM。"""
        state = tmp_path / "state"
        out = tmp_path / "out"
        script = tmp_path / "cf_runner.py"
        script.write_text(CF_RUNNER_SCRIPT, encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SRC) + os.pathsep + str(self.RUNNER),
            CURRICULUM261_R17_STATE_ROOT=str(state),
            R17_CF_DEADLINE="30", R17_CF_BEHAVIOR="sleep_cancel",
            R17_CF_NAMESPACES="cf_ns_a")
        samples = tmp_path / "s.jsonl"
        lines = [json.dumps({"win": _win(_perf()), "guest": _guest()})
                 for _ in range(60)]
        lines.append(json.dumps({"win": _win(_perf(), vols=[
            {"vol": "F:", "present": True, "free_gb": 3.0,
             "serial": "CFA1", "identity_match": True},
            {"vol": "C:", "present": True, "free_gb": 200.0,
             "serial": "CCA1", "identity_match": True}]),
            "guest": _guest()}))
        lines += [json.dumps({"win": _win(_perf()),
                              "guest": _guest()}) for _ in range(5)]
        samples.write_text("\n".join(lines) + "\n", encoding="utf-8")
        journal = state / "r17_execution_journal.jsonl"
        sup_dir = tmp_path / "sup_run"
        sup = subprocess.run(
            [sys.executable,
             str(self.RUNNER / "r17_supervision.py"),
             "--run-dir", str(sup_dir), "--task-kind", "engineering",
             "--max-seconds", "120",
             "--samples-source", f"file:{samples}",
             "--", sys.executable, str(script), str(self.SRC),
             str(state), str(out), "sleep_cancel", "normal"],
            capture_output=True, text=True, timeout=150, env=env,
            cwd=str(self.SYNC))
        assert sup.returncode == 4, \
            f"保护性中止 rc=4,实际 {sup.returncode} " \
            f"{sup.stdout[-500:]} {sup.stderr[-300:]}"
        events = self._events(journal)
        seq = [e["event"] for e in events]
        # 取消路径:grant 发放+撤销+cancelled 终态;唯一 writer 封口
        assert seq.count("grant_issued") >= 1, \
            "样本时序应保证停止前授权已完成"
        assert seq.count("grant_revoked") >= 1
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        # worker 持 token 睡眠中被停止:crashed(signal)或
        # failed(cancelled)都是真实取消收口形态;不得 completed
        assert term and term[0].get("status") in ("failed", "crashed")
        note = term[0].get("note", "")
        assert "cancelled" in note or "signal" in note
        aborted = [e for e in events
                   if e["event"] == "chain_iteration_aborted"]
        assert aborted
        assert seq[-1] == "chain_released"
        writers = {e.get("writer") for e in events if "writer" in e}
        assert writers <= {"chain_session_owner"}
        # terminal 后新授权请求被拒+同 state 二次准入拒
        rc2 = subprocess.run(
            [sys.executable, str(script), str(self.SRC), str(state),
             str(tmp_path / "out2"), "normal", "normal"],
            capture_output=True, text=True, timeout=60, env=env)
        assert rc2.returncode != 0, "已终结 iteration 不得重新准入"
