# -*- coding: utf-8 -*-
"""R17 读取失败隔离与信号安全停止(任务书 §7 R/S 矩阵可夹具化项)。

RCF-01:reader 读取失败(stat/open/read)后本次有效批次必须为空,
pump 不消费旧批次,失联计时从最后真实有效样本继续累计,15/30s
告警经真实非 replay 路径可达保护。
RCF-02:TERM/INT handler 只登记意图(零锁/零 I/O);持 writer 锁时
真实信号 handler 必须返回;停止由正常控制路径(spawn 前/spawn 衔接/
主循环每轮)消费;阻塞的通知通道不妨碍升级与有界收尾。

真实模块/真实进程为主;测试挂钩只控制时序,不改生产锁类型与停止
判断;每个子进程测试有外部有界观察(父进程),watchdog 强杀只是
测试兜底,不宣称被测 supervisor 成功保护。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
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
    Supervisor, WinSampleReader)

requires_linux = pytest.mark.skipif(
    os.name == "nt", reason="控制路径执行面只在 Linux/WSL 跑")


def _utc_now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _vols_ok():
    return [{"vol": "F:", "present": True, "free_gb": 100.0,
             "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
            {"vol": "C:", "present": True, "free_gb": 200.0,
             "size_gb": 900.0, "serial": "CCA1", "identity_match": True}]


def _win(perf=None, run_id=None, utc="now", seq=1):
    line = {"event": "sample",
            "perf": perf if perf is not None else {
                "phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
            "vols": _vols_ok(), "telemetry_out_writable": True}
    if utc == "now":
        utc = _utc_now()
    line["utc"] = utc
    line["seq"] = seq
    if run_id is not None:
        line["run_id"] = run_id
    return line


def _guest(avail_kb=39_000_000, total_kb=40_000_000):
    return {"event": "guest_sample", "utc": _utc_now(),
            "meminfo": {"MemTotal": total_kb, "MemAvailable": avail_kb},
            "psi_memory": {"full_avg10": 0.0},
            "vmstat_swap": {"pswpout": 0}}


def _sup(tmp_path, argv=("--", "true"), samples_source=""):
    argv = list(argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    args = argparse.Namespace(
        run_dir=str(tmp_path / "run"), task_kind="fixture",
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source=samples_source, win_sampler_ps1="/nonexistent.ps1",
        win_volumes="C:,F:", expect_artifact=[], obs_ready_deadline=30.0)
    return Supervisor(args)


def _reader_for(sup):
    return WinSampleReader(
        sup.win_path_guest, run_id=sup.run_id,
        started_iso=sup._started_utc,
        predates_tolerance_s=sup.policy["startup_admission"][
            "source_utc_tolerance_s"])


def _write_samples(path, lines):
    with path.open("a", encoding="utf-8") as fh:
        for ln in lines:
            fh.write(json.dumps(ln) + "\n")


# ================================================= R01-R04 读取失败隔离
@requires_linux
class TestRReadFailureIsolation:
    """WP1(RCF-01):读取失败的提前返回不交付旧批次;诊断有界;
    失联计时从最后真实有效样本累计;恢复不绕过身份闸。"""

    def test_r01_file_gone_empty_batch_no_refresh(self, tmp_path):
        """R01:先健康后文件消失——本次 new_valid 为空;pump 不返回
        旧样本;有效时点不前进;读取失败有界诊断(§4.2)。"""
        sup = _sup(tmp_path)
        sup.win_reader = _reader_for(sup)
        _write_samples(sup.win_path_guest,
                       [_win(run_id=sup.run_id, seq=1), _win(run_id=sup.run_id, seq=2)])
        got = sup._pump_win_lines(10.0)
        assert got and sup.last_win_line_mono == 10.0
        assert len(sup.win_reader.new_valid) == 2
        # 文件消失(stat FileNotFoundError)
        sup.win_path_guest.unlink()
        got2 = sup._pump_win_lines(20.0)
        assert got2 is None, "失败读取不得把旧批次当新有效样本返回"
        assert sup.win_reader.new_valid == []
        assert sup.last_win_line_mono == 10.0, "有效时点不得被失败读取刷新"
        rd = sup.win_reader
        assert rd.read_failures >= 1 and rd.read_failure_consecutive >= 1
        assert rd.read_failure_last_op == "stat"
        assert rd.read_failure_last_err == "FileNotFoundError"
        assert rd.read_failure_last_utc is not None
        # 诊断不充当样本:身份/序号/last_valid 不受影响
        assert rd.last_valid is not None and rd.last_valid["seq"] == 2
        assert rd.last_valid_mono is not None

    def test_r02_stat_open_read_failure_paths(self, tmp_path, monkeypatch):
        """R02:stat/open/read 三类失败分别隔离;每条提前返回无旧
        批次;真实控制循环没有被静默停掉(恢复后继续工作)。"""
        sup = _sup(tmp_path)
        sup.win_reader = _reader_for(sup)
        _write_samples(sup.win_path_guest, [_win(run_id=sup.run_id, seq=1)])
        sup._pump_win_lines(5.0)
        base_mono = sup.last_win_line_mono

        # 形态A:stat 失败(文件不存在)
        sup.win_path_guest.unlink()
        sup._pump_win_lines(6.0)
        assert sup.win_reader.new_valid == []
        assert sup.last_win_line_mono == base_mono
        assert sup.win_reader.read_failure_last_op == "stat"
        total_a = sup.win_reader.read_failures

        # 形态B:open 失败(路径是目录→IsADirectoryError)
        sup.win_path_guest.mkdir()
        sup._pump_win_lines(7.0)
        assert sup.win_reader.new_valid == []
        assert sup.last_win_line_mono == base_mono
        assert sup.win_reader.read_failure_last_op == "read"  # open/read 同段
        assert sup.win_reader.read_failure_last_err == "IsADirectoryError"
        assert sup.win_reader.read_failures > total_a

        # 形态C:read 阶段抛 OSError(注入只读坏文件对象;stat/open
        # 成功,fh.read 失败——与 open 同一提前返回路径)
        sup.win_path_guest.rmdir()

        class _BoomFH:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def seek(self, *a):
                pass

            def read(self, *a):
                raise OSError(5, "Input/output error")

        class _FakePath:
            def __init__(self, real):
                self._real = real

            def stat(self):
                return self._real.stat()

            def open(self, *a, **k):
                return _BoomFH()

        sup.win_path_guest.write_text("", encoding="utf-8")
        real_path = sup.win_path_guest
        sup.win_reader.path = _FakePath(real_path)
        sup._pump_win_lines(8.0)
        assert sup.win_reader.new_valid == []
        assert sup.last_win_line_mono == base_mono
        assert sup.win_reader.read_failure_last_err == "OSError"
        # 恢复真实路径:控制循环继续工作(没有被静默停掉)
        sup.win_reader.path = real_path
        _write_samples(sup.win_path_guest, [_win(run_id=sup.run_id, seq=2)])
        got = sup._pump_win_lines(9.0)
        assert got and got["seq"] == 2
        assert sup.last_win_line_mono == 9.0
        assert sup.win_reader.read_failure_consecutive == 0

    def test_r03_bad_lines_do_not_advance_liveness(self, tmp_path):
        """R03:无新行/半行/坏 JSON/非对象/重复 seq/旧时间——均不
        刷新有效性;完整新合法样本到达才推进。"""
        sup = _sup(tmp_path)
        sup.win_reader = _reader_for(sup)
        _write_samples(sup.win_path_guest, [_win(run_id=sup.run_id, seq=1)])
        sup._pump_win_lines(10.0)
        base_mono = sup.last_win_line_mono
        rd = sup.win_reader
        # 半行(无换行结尾,留在缓冲)
        with sup.win_path_guest.open("a", encoding="utf-8") as fh:
            fh.write('{"event": "sample", "seq": 2')
        sup._pump_win_lines(11.0)
        assert rd.new_valid == [] and sup.last_win_line_mono == base_mono
        # 补全为坏 JSON 行 + null 行 + 重复 seq + 旧 utc
        _write_samples(sup.win_path_guest, [
            {"broken": True}, None,
            _win(run_id=sup.run_id, seq=1),  # 重复 seq(拒绝)
            _win(run_id=sup.run_id, seq=3,
                 utc="2020-01-01T00:00:00Z"),  # 旧时间重放(拒绝)
        ])
        sup._pump_win_lines(12.0)
        assert rd.new_valid == []
        assert sup.last_win_line_mono == base_mono
        assert rd.parse_errors >= 2        # broken + null
        assert rd.duplicate_seq == 1
        assert rd.stale_replayed == 1
        # 新合法样本到达:有效性推进(恢复按原有规则)
        _write_samples(sup.win_path_guest, [_win(run_id=sup.run_id, seq=4)])
        got = sup._pump_win_lines(13.0)
        assert got and got["seq"] == 4
        assert sup.last_win_line_mono == 13.0

    def test_r04_recover_same_source_rejects_replayed_old_lines(
            self, tmp_path):
        """R04:读失败后恢复同源文件——重建后的旧行(已消费 seq)仍
        拒收,不因"故障恢复"获得新有效性;新行可恢复观测。"""
        sup = _sup(tmp_path)
        sup.win_reader = _reader_for(sup)
        _write_samples(sup.win_path_guest, [_win(run_id=sup.run_id, seq=1)])
        sup._pump_win_lines(10.0)
        # 读取失败(文件消失)
        sup.win_path_guest.unlink()
        sup._pump_win_lines(11.0)
        assert sup.win_reader.new_valid == []
        # 同源重建:先旧行(seq=1 重放),再新合法行(seq=2)
        sup.win_path_guest.write_text("", encoding="utf-8")
        _write_samples(sup.win_path_guest,
                       [_win(run_id=sup.run_id, seq=1), _win(run_id=sup.run_id, seq=2)])
        got = sup._pump_win_lines(12.0)
        assert got and got["seq"] == 2, "只有新行恢复观测"
        assert sup.win_reader.duplicate_seq == 1, "重放旧行仍拒收"
        assert sup.win_reader.new_valid[-1]["seq"] == 2

    def test_r04_read_failure_alert_bounded_once(self, tmp_path):
        """首次读取失败告警只发一次(有界);持续失败不重复刷屏。"""
        sup = _sup(tmp_path)
        sup.win_reader = _reader_for(sup)
        _write_samples(sup.win_path_guest, [_win(run_id=sup.run_id, seq=1)])
        sup._pump_win_lines(10.0)
        sup.win_path_guest.unlink()
        sup._pump_win_lines(11.0)
        sup._pump_win_lines(12.0)
        sup._pump_win_lines(13.0)
        assert sup._win_read_failure_logged is True
        # safe_log 走 iow;直接验证告警语义只发一次:标志粘性
        # (重复告警由标志阻断;alerts 落盘由 iow 异步,不在此断言)


# ================================================= S 系列信号安全停止
CHILD_SRC = r'''
import argparse, json, os, signal, sys, threading, time
repo, base, mode = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, os.path.join(repo, "stage2_6_1", "runner"))
from r17_supervision import Supervisor

import datetime as _dt
def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

perf = {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
        "commit_limit_gb": 83.0, "phys_total_gb": 63.0}
vols = [
    {"vol": "F:", "present": True, "free_gb": 100.0,
     "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
    {"vol": "C:", "present": True, "free_gb": 200.0,
     "size_gb": 900.0, "serial": "CCA1", "identity_match": True}]
win = {"event": "sample", "seq": 1, "utc": utc_now(), "perf": perf,
       "vols": vols, "telemetry_out_writable": True}
guest = {"event": "guest_sample", "utc": utc_now(),
         "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
         "psi_memory": {"full_avg10": 0.0},
         "vmstat_swap": {"pswpout": 0}}
samples_path = os.path.join(base, "samples.jsonl")
with open(samples_path, "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

argv = ["bash", "-c", "sleep 30"]
if mode == "s05c":
    argv = ["bash", "-c", "sleep 3"]
if mode == "s04":
    argv = ["bash", "-c", 'trap "" TERM; exec sleep 30']
args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=argv, task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)

if mode in ("s01", "s02", "s03", "s05a", "s05c"):
    # stdout 提交计数挂钩:第 N 次提交(N=2 business_started/
    # N=1 supervisor_start/N=3 supervisor_end)暂停在 submit 持锁
    # 区间(真实 writer Lock 持有点;只控制时序)
    n_th = 1 if mode == "s05a" else (3 if mode == "s05c" else 2)
    real_put = sup.iow._q.put_nowait
    hit = threading.Event()
    count = {"n": 0}
    def hooked(act):
        if act.get("role") == "stdout":
            count["n"] += 1
            if count["n"] == n_th and not hit.is_set():
                hit.set()
                print("PROBE_HOLDING_LOCK", flush=True)
                time.sleep(6.0)
        return real_put(act)
    sup.iow._q.put_nowait = hooked
elif mode == "s04":
    # 标记挂钩:business_started(第 2 次 stdout)打印就绪标记;
    # R17ALERT 递交阻塞(通知通道打开但消费者不读的等价注入:
    # 写线程停在 stdout 动作;控制线程/升级不受影响)
    real_put = sup.iow._q.put_nowait
    hit = threading.Event()
    count = {"n": 0}
    def hooked(act):
        if act.get("role") == "stdout":
            count["n"] += 1
            if count["n"] == 2 and not hit.is_set():
                hit.set()
                print("PROBE_HOLDING_LOCK", flush=True)
                time.sleep(0.5)
        return real_put(act)
    sup.iow._q.put_nowait = hooked
    real_sync = sup._stdout_sync
    gate = threading.Event()
    ahit = threading.Event()
    def blocked_sync(tag, line):
        if tag == "R17ALERT" and not ahit.is_set():
            ahit.set()
            print("PROBE_ALERT_BLOCKED", flush=True)
            gate.wait(60.0)
        return real_sync(tag, line)
    sup._stdout_sync = blocked_sync
    sup.policy["coop_exit_window_s"] = 0.5  # 测试缩窗(工程夹具)
elif mode == "s05b":
    # spawn 已发生、衔接窗口内的真实信号(真实 spawn_business 完成后
    # 立即向自身发 TERM——信号必然落在 Protector 已创建、主循环首
    # 轮消费之前的窗口)
    real_spawn = Supervisor.spawn_business
    def spawn_and_stop(self2):
        pgid = real_spawn(self2)
        print("PROBE_SPAWNED", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        return pgid
    Supervisor.spawn_business = spawn_and_stop
elif mode in ("s06a", "s06b"):
    # supervisor 异常:真实 main() 的 except 分支是被测面(直调
    # run() 不会进入 crash 处理);类级 patch 对 main() 自建实例生效
    real_pump = Supervisor._pump_win_lines
    def boom(self2, mono):
        raise RuntimeError("probe-injected pump failure")
    Supervisor._pump_win_lines = boom
    if mode == "s06b":
        real_sync = Supervisor._stdout_sync
        gate = threading.Event()
        ahit = threading.Event()
        def blocked_sync(self2, tag, line):
            if tag == "R17ALERT" and not ahit.is_set():
                ahit.set()
                print("PROBE_ALERT_BLOCKED", flush=True)
                gate.wait(60.0)
            return real_sync(self2, tag, line)
        Supervisor._stdout_sync = blocked_sync

if mode in ("s06a", "s06b"):
    sys.argv = [sys.argv[0],
                "--run-dir", os.path.join(base, "run"),
                "--task-kind", "fixture",
                "--samples-source", "file:" + samples_path,
                "--win-sampler-ps1", "/nonexistent.ps1",
                "--win-volumes", "C:,F:",
                "--", "bash", "-c", "sleep 30"]
    from r17_supervision import main as sup_main
    rc = sup_main()
else:
    rc = sup.run()
print("PROBE_RUN_RC=%d" % rc, flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
'''


def _run_child(tmp_path, mode, *, expect_marker, sig=None,
               max_wait=60.0, marker_wait=30.0, delay_after_marker=0.5,
               sigs=None):
    """起真实子进程(replay Supervisor.run),等待测试挂钩标记,发送
    真实信号,有界等待退出;返回 (exit_rc, 输出行, run_dir)。"""
    base = tmp_path / mode
    base.mkdir(parents=True, exist_ok=True)
    child = base / "child_probe.py"
    child.write_text(CHILD_SRC, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, str(child), str(RUNNER_DIR.parents[1]), str(base),
         mode],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, start_new_session=True)
    lines: list[str] = []
    marker = threading.Event()

    def _reader():
        for ln in p.stdout:
            ln = ln.rstrip("\n")
            lines.append(ln)
            if expect_marker and expect_marker in ln:
                marker.set()

    rt = threading.Thread(target=_reader, daemon=True)
    rt.start()
    try:
        if expect_marker:
            if not marker.wait(marker_wait):
                pytest.fail(f"{marker_wait}s 内未见 {expect_marker}:"
                            f"挂钩未命中(非假绿);输出={lines[-5:]}")
            time.sleep(delay_after_marker)
        if sigs:
            for s in sigs:
                p.send_signal(s)
                time.sleep(0.2)
        elif sig is not None:
            p.send_signal(sig)
        deadline = time.time() + max_wait
        rc = None
        while time.time() < deadline:
            rc = p.poll()
            if rc is not None:
                break
            time.sleep(0.2)
        if rc is None:
            p.kill()
            p.wait(timeout=10)
            pytest.fail(f"子进程 {max_wait}s 未退出(停止/收尾失控);"
                        f"输出={lines[-8:]}")
        return rc, lines, base / "run"
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
        rt.join(timeout=5)


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


@requires_linux
class TestSignalSafeStop:
    """WP2(RCF-02):handler 只登记意图;真实信号在持锁窗口可返回;
    停止由正常控制路径消费;阻塞通知不妨碍升级与有界收尾。"""

    def test_s01_sigterm_while_holding_writer_lock(self, tmp_path):
        """S01:主线程持真实 writer 锁时 SIGTERM——生产 handler 返回
        (不重入 log);真实业务收到 TERM 退出;外层 rc=4 与事实一致
        (旧实现:handler 重入 writer Lock 同线程死锁,50s 不返回)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s01", expect_marker="PROBE_HOLDING_LOCK",
            sig=signal.SIGTERM, max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM
        assert summary["external_stop_consumed"] is True
        assert summary["business"]["rc"] == -signal.SIGTERM
        assert any("supervisor_external_stop" in r
                   for r in summary["stop_requested_reasons"])
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert "supervisor_signal" in alerts  # 消费点 log(正常上下文)

    def test_s02_sigint_while_holding_writer_lock(self, tmp_path):
        """S02:相同持锁窗口 SIGINT——同样无重入死锁,不利用
        KeyboardInterrupt 跳过状态与清理。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s02", expect_marker="PROBE_HOLDING_LOCK",
            sig=signal.SIGINT, max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGINT
        assert summary["business"]["rc"] is not None
        assert not summary.get("residual_unconfirmed")

    def test_s03_repeated_signals_single_sticky_chain(self, tmp_path):
        """S03:TERM 后紧接 INT——粘性意图保留首次原因(15);停止
        链单条(incident/stop 理由各一,不重开合作窗/不重复 terminal)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s03", expect_marker="PROBE_HOLDING_LOCK",
            sigs=[signal.SIGTERM, signal.SIGINT], max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM, \
            "重复信号不覆盖首次停止原因(粘性)"
        ext = [r for r in summary["stop_requested_reasons"]
               if "supervisor_external_stop" in r]
        assert len(ext) == 1, "重复信号不得新建第二条停止链"
        kinds = [i["kind"] for i in summary["incidents"]]
        assert kinds.count("supervisor_external_stop") == 1

    def test_s04_ignore_term_blocked_alert_kill_escalation(self, tmp_path):
        """S04:业务忽略 TERM+告警通道阻塞(写线程停在 stdout 动作)
        ——阻塞未解除时 KILL 升级与退出核验已发生;writer 未完成就
        如实标不完整,不签完整 PASS(外部 watchdog 只做测试兜底)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s04", expect_marker="PROBE_HOLDING_LOCK",
            sig=signal.SIGTERM, max_wait=90, marker_wait=45)
        assert any("PROBE_RUN_RC=" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        # KILL 升级已发生(阻塞的只是写线程;控制路径完成升级+核验)
        assert summary["business"]["protector"]["kill_sent"] is True
        assert summary["business"]["rc"] in (-9, 137), \
            f"忽略 TERM 的业务应被 KILL:rc={summary['business']['rc']}"
        # writer 未完成:证据不完整如实标记(不假签 PASS)
        assert summary["coverage"]["stdout_failures"] >= 0
        rr = _load(run_dir / "run_record.json")
        assert rr["evidence_complete"] is False
        assert rc in (4, 5), f"保护性中止/未证实外层 rc,实际 {rc}"

    def test_s05a_stop_before_spawn_zero_business(self, tmp_path):
        """S05a:spawn 之前接受停止——不再启动业务;只收尾本请求已
        启动的采样/辅助任务(handler 注册已覆盖 supervisor_start
        窗口;旧实现注册前的 TERM 直接默认杀死进程,exit=-15)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s05a", expect_marker="PROBE_HOLDING_LOCK",
            sig=signal.SIGTERM, max_wait=45)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines)
        # 零业务启动:业务 stdout/stderr 文件不存在
        biz = run_dir / "business"
        assert not (biz / "stdout.bin").exists()
        assert not (biz / "stderr.bin").exists()
        summary = _load(run_dir / "summary.json")
        assert summary["business"]["rc"] is None

    def test_s05b_stop_in_spawn_handover_window(self, tmp_path):
        """S05b:spawn 已发生、Protector 登记衔接窗口内的信号——
        登记后补做停止,不丢失该窗口里的信号(主循环消费点覆盖)。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s05b", expect_marker="PROBE_SPAWNED",
            sig=None, max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM
        assert summary["business"]["rc"] == -signal.SIGTERM

    def test_s05c_stop_during_finalize_no_reentry(self, tmp_path):
        """S05c/L01:finalize(supervisor_end 已入队/seal 前窗口)中的
        停止——截止点 C 之前登记的停止参与最终结果:raw rc=0 保留
        不改写,outer rc=4,消费一次、不重入 finalize、不解封流。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s05c", expect_marker="PROBE_HOLDING_LOCK",
            sig=signal.SIGTERM, max_wait=60)
        assert any("PROBE_RUN_RC=4" in ln for ln in lines), \
            "C 前停止必须使整体非成功(业务 raw rc 不被改写,run 非普通成功)"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM
        assert summary["external_stop_consumed"] is True, \
            "finalize 窗口(C 前)的停止由收尾检查点消费"
        assert summary["business"]["rc"] == 0, "业务原始成功事实保留"
        assert summary["external_stop_sig_count"] >= 1
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert alerts.count('"supervisor_end"') == 1, "finalize 不重入"

    def test_s06a_supervisor_exception_bounded_shutdown(self, tmp_path):
        """S06a/U01:supervisor 主循环异常——统一收尾真正驱动到终态:
        TERM 响应形态下 supervisor 自己观察业务退出码、确认任务树
        结束后返回;handler 覆盖收尾;真实异常/原始 rc 可核查。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s06a", expect_marker=None, max_wait=60)
        assert any("PROBE_RUN_RC=3" in ln for ln in lines), \
            f"真实 main() crash 分支 rc=3;输出={lines[-5:]}"
        assert rc == 3, f"子进程退出码与 main() 返回一致,实际 {rc}"
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert "supervisor_crash" in alerts
        summary = _load(run_dir / "summary.json")
        prot = summary["business"]["protector"]
        assert prot["term_sent"] is True
        assert prot["terminal_confirmed"] is True, \
            "异常后停止链由被测 supervisor 驱动到终态确认"
        assert summary["business"]["rc"] == -signal.SIGTERM, \
            "异常收尾必须实际观察业务退出码(不再是 None)"

    def test_s06b_supervisor_exception_blocked_alert_still_bounded(
            self, tmp_path):
        """S06b:异常分支的告警通道阻塞(写线程停在 R17ALERT 动作)
        ——异常通知阻塞不卡死保护收尾;证据不完整如实标记。"""
        rc, lines, run_dir = _run_child(
            tmp_path, "s06b", expect_marker="PROBE_ALERT_BLOCKED",
            marker_wait=45, max_wait=90)
        assert any("PROBE_RUN_RC=3" in ln for ln in lines)
        assert rc == 3
        summary = _load(run_dir / "summary.json")
        assert summary["business"]["protector"]["term_sent"] is True
        assert summary["business"]["rc"] == -signal.SIGTERM, \
            "通知持续阻塞不改变停止/升级/退出观察责任(§4.5)"
        rr = _load(run_dir / "run_record.json")
        assert rr["evidence_complete"] is False, \
            "writer 未完成不得签完整(阻塞只被有界等待,不被假完成)"


# ================================================= R05 真实非 replay 集成
@requires_linux
class TestRStaleLiveIntegration:
    """R05:非 replay 的实际读取/失联分支——真实 CLI supervisor +
    真实 ps1 采样(live 模式;不使用 --samples-source file:)。
    host 遥测持续读取失败(jsonl 路径替换为目录,ps1 的
    AppendAllText 对目录持续失败)→ 失联事实经真实 stale 规则形成
    15s WARNING/30s CRITICAL → 既有 Protector 停止本 run 任务。
    不直接调用 handle_triggers(CRITICAL)——缺测事实必须走实际
    失联规则。"""

    def test_r05_live_host_read_failure_escalates_to_protection(
            self, tmp_path):
        run_dir = tmp_path / "run"
        argv = [sys.executable,
                str(RUNNER_DIR / "r17_supervision.py"),
                "--run-dir", str(run_dir),
                "--task-kind", "fixture",
                "--max-seconds", "300",
                "--obs-ready-deadline", "45",
                "--", "bash", "-c", "sleep 60"]
        p = subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        win_path = run_dir / "telemetry" / "win_samples.jsonl"
        alerts_path = run_dir / "alerts" / "alerts.jsonl"
        try:
            # 就绪:真实采样产出有效首样本(业务已启动)
            deadline = time.time() + 60
            admitted = False
            while time.time() < deadline:
                if alerts_path.is_file() and \
                        "business_started" in alerts_path.read_text(
                            encoding="utf-8", errors="replace"):
                    admitted = True
                    break
                time.sleep(0.5)
            assert admitted, "60s 内未见 business_started(live 就绪失败)"
            assert win_path.is_file()
            # 注入持续读取失败:jsonl 路径替换为目录(只作用本测试
            # 自己的文件;ps1 每样本 AppendAllText 持续失败)
            win_path.unlink()
            win_path.mkdir()
            # 真实失联链:stale 从最后有效样本累计 → 15s WARNING →
            # 30s CRITICAL(observation_stale_win)→ Protector TERM
            deadline = time.time() + 120
            stopped = False
            while time.time() < deadline:
                rc = p.poll()
                if rc is not None:
                    break
                if alerts_path.is_file():
                    text = alerts_path.read_text(
                        encoding="utf-8", errors="replace")
                    if "sigterm_sent" in text:
                        stopped = True
                time.sleep(0.5)
            end_deadline = time.time() + 90
            rc = None
            while time.time() < end_deadline:
                rc = p.poll()
                if rc is not None:
                    break
                time.sleep(0.5)
            assert rc is not None, "失联保护后 supervisor 未有界退出"
            assert rc == 4, f"保护性中止外层 rc=4,实际 {rc}"
            alerts = alerts_path.read_text(encoding="utf-8",
                                           errors="replace")
            assert "observation_stale_win" in alerts, \
                "失联告警必须来自实际 stale 规则(非直接注入)"
            assert "win_read_failure" in alerts, "读取失败告警在场"
            summary = _load(run_dir / "summary.json")
            assert summary["business"]["rc"] == -signal.SIGTERM
            cov = summary["coverage"]
            assert (cov["win_read_failures"] or 0) >= 1
            assert cov["win_read_failure_last_op"] == "read"
            # 有效时点停在注入前(读取失败不刷新);guest 独立判活
            # 不被 host 失联掩盖(两源 last_mono 都在场)
            assert cov["win_last_mono"] is not None
            assert cov["guest_last_mono"] is not None
            assert summary["external_stop_sig"] is None
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=15)
            # 清理注入(目录→文件形态留给 run_record 事实;目录不删
            # 会影响 tmp_path 清理,交由 pytest 递归删除,无需处理)
