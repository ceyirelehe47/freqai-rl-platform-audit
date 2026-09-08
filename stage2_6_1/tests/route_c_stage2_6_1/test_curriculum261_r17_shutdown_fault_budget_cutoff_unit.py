# -*- coding: utf-8 -*-
"""R17 收尾二次错误隔离/共享剩余预算/停止决策截止点(任务书 §7 F/B/C/L/I)。

真实模块为主:runner 的 r17_supervision(发布树或 WSL 开发树同步面);
真实短命子进程+事件屏障(挂钩点=实际方法边界);F01 保留真实策略身份
(coop=30s)与真实后代+独立邻居;C 系列以 sys.settrace 行级定位真实
finalize 的临界边界(§6.5:不直接调用替代 handler,不手写字段)。故障
注入仅限测试自己的文件、受控读数与隔离工程状态;外部 watchdog 只做
测试兜底(不计入产品保护行为)。
"""
from __future__ import annotations

import argparse
import datetime as _dt
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
            Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"),
            Path.home() / "projects/crypto_rl/stage2_6_1_runner",
    ):
        if (cand / "r17_supervision.py").is_file():
            return cand
    raise FileNotFoundError("runner 执行面不可达")


RUNNER_DIR = _find_runner_dir()
sys.path.insert(0, str(RUNNER_DIR))

from r17_supervision import Supervisor  # noqa: E402

requires_linux = pytest.mark.skipif(
    os.name == "nt", reason="控制路径执行面只在 Linux/WSL 跑")


def _load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _utc():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _write_samples(path: Path, n: int = 40) -> None:
    win = {"event": "sample", "seq": 1, "utc": _utc(),
           "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                    "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
           "vols": [
               {"vol": "F:", "present": True, "free_gb": 100.0,
                "size_gb": 500.0, "serial": "CFA1",
                "identity_match": True},
               {"vol": "C:", "present": True, "free_gb": 200.0,
                "size_gb": 900.0, "serial": "CCA1",
                "identity_match": True}],
           "telemetry_out_writable": True}
    guest = {"event": "guest_sample", "utc": _utc(),
             "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
             "psi_memory": {"full_avg10": 0.0},
             "vmstat_swap": {"pswpout": 0}}
    with path.open("w", encoding="utf-8") as fh:
        for _ in range(n):
            fh.write(json.dumps({"win": win, "guest": guest}) + "\n")


def _sup(base, argv=("--", "bash", "-c", "sleep 30"), task_kind="fixture"):
    """进程内构造(主线程;handler 可注册)。"""
    argv = list(argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    base = Path(base)
    base.mkdir(parents=True, exist_ok=True)
    sp = base / "samples.jsonl"
    _write_samples(sp)
    args = argparse.Namespace(
        run_dir=str(base / "run"), task_kind=task_kind,
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source="file:" + str(sp),
        win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
        expect_artifact=[], obs_ready_deadline=30.0)
    return Supervisor(args)


BIZ_IGNORE_SRC = r'''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
pid = os.fork()
if pid == 0:
    time.sleep(600)
with open(sys.argv[1], "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(600)
'''

WIN_IGNORE_SRC = r'''
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(sys.argv[1], "w") as fh:
    fh.write(str(os.getpid()))
time.sleep(600)
'''


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _group_alive(pgid: int) -> list[int]:
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as fh:
                text = fh.read()
            rp = text.rindex(")")
            fields = text[rp + 2:].split()
            if int(fields[2]) == pgid and fields[0] != "Z":
                out.append(int(name))
        except (OSError, ValueError, IndexError):
            continue
    return out


def _alert_events(run_dir) -> list[dict]:
    p = Path(run_dir) / "alerts" / "alerts.jsonl"
    out = []
    if p.is_file():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except json.JSONDecodeError:
                    pass
    return out


def _event_names(run_dir) -> list[str]:
    return [e.get("event") for e in _alert_events(run_dir)]


# 子进程模板:参数化 mode。f01 走真实 main();其余进程内 sup.run();
# c 系列以 sys.settrace 行级定位临界边界(python 3.11 真实模块)。
SFB_CHILD_SRC = r'''
import argparse, json, os, signal, subprocess, sys, threading, time
probe_dir, base, mode = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, probe_dir)
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
    for _ in range(40):
        fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

use_ignore_biz = mode in (
    "f01", "f02a", "f03", "f04", "b01", "b02", "b03")
argv = ["bash", "-c", "sleep 1" if mode.startswith("c") else "sleep 30"]
if use_ignore_biz:
    argv = [sys.executable, os.path.join(base, "biz_ignore_term.py"),
            os.path.join(base, "biz_ready.marker")]

# ---- crash 注入(READY 证明先于注入;忽略 TERM 业务已证明安装) ----
crash_seen = {"v": False}
real_pump = Supervisor._pump_win_lines
def boom(self2, mono):
    if mode == "f02b":
        if crash_seen["v"]:
            return real_pump(self2, mono)
        crash_seen["v"] = True
        raise RuntimeError("probe: pump crash (f02b)")
    if mode.startswith("c0"):
        # C 边界测试:无 crash,业务正常收尾,边界由 settrace 定位
        return real_pump(self2, mono)
    if use_ignore_biz:  # 仅忽略 TERM 业务场景:READY 证明先于注入
        ready = os.path.join(base, "biz_ready.marker")
        dl = time.time() + 30
        while not os.path.exists(ready):
            if time.time() > dl:
                raise RuntimeError("probe: biz READY 未出现")
            time.sleep(0.1)
    crash_seen["v"] = True
    print("PROBE_INJECT_CRASH", flush=True)
    raise RuntimeError("probe-injected pump failure")

# ---- 二次错误注入点(按 mode) ----
if mode == "f01":
    # 升级前第一次 flush_logs 抛错(合作窗未满、KILL 未发)
    real_flush = type(None)
    from r17_supervision import Protector
    real_flush = Protector.flush_logs
    fl_state = {"thrown": False}
    def hooked_flush(self2):
        if crash_seen["v"] and not fl_state["thrown"]:
            fl_state["thrown"] = True
            print("PROBE_INJECT_FLUSH_FAIL", flush=True)
            raise RuntimeError("probe: flush failure before escalation")
        return real_flush(self2)
    Protector.flush_logs = hooked_flush
elif mode == "f02a":
    real_obs = Supervisor._observe_business_exit
    obs_state = {"thrown": False}
    def hooked_obs(self2):
        if crash_seen["v"] and not obs_state["thrown"]:
            obs_state["thrown"] = True
            print("PROBE_INJECT_OBSERVE_FAIL", flush=True)
            raise RuntimeError("probe: observe failure before escalation")
        return real_obs(self2)
    Supervisor._observe_business_exit = hooked_obs
elif mode == "f02b":
    # 实际 rc 已读到 self2.biz_rc 之后、退出日志链(_scan)抛错
    real_scan = Supervisor._scan_business_stderr
    scan_state = {"thrown": False}
    def hooked_scan(self2):
        if crash_seen["v"] and not scan_state["thrown"] \
                and self2.biz_proc is not None \
                and self2.biz_proc.poll() is not None \
                and self2.biz_rc is not None:
            scan_state["thrown"] = True
            print("PROBE_INJECT_SCAN_FAIL", flush=True)
            raise RuntimeError("probe: exit-log failure after rc read")
        return real_scan(self2)
    Supervisor._scan_business_stderr = hooked_scan
elif mode == "f03":
    # 持续:每次 flush_logs 都抛 + R17ALERT 通道持续阻塞
    from r17_supervision import Protector
    def hooked_flush(self2):
        if crash_seen["v"]:
            raise RuntimeError("probe: flush persistent failure")
        return Protector._real_flush_backup(self2)
    Protector._real_flush_backup = Protector.flush_logs
    Protector.flush_logs = hooked_flush
    real_sync = Supervisor._stdout_sync
    gate = threading.Event()
    hit = threading.Event()
    def blocked_sync(self2, tag2, line):
        if tag2 == "R17ALERT" and not hit.is_set():
            hit.set()
            print("PROBE_ALERT_BLOCKED", flush=True)
            gate.wait(60.0)
        return real_sync(self2, tag2, line)
    Supervisor._stdout_sync = blocked_sync
elif mode == "f04":
    from r17_supervision import Protector
    def broken_members(self2):
        if crash_seen["v"]:
            raise RuntimeError("probe: member scan unavailable")
        return Protector._real_members_backup(self2)
    Protector._real_members_backup = Protector._member_pids
    Protector._member_pids = broken_members

# ---- 预算/收尾观察 wrap(b 系列) ----
timeline = []
if mode in ("b01", "b02", "b03"):
    real_ts = Supervisor._terminal_shutdown
    def hooked_ts(self2, reason):
        timeline.append({"phase": "ts_enter", "t": time.monotonic(),
                         "deadline": self2._finalize_deadline,
                         "reason": reason})
        try:
            return real_ts(self2, reason)
        finally:
            timeline.append({"phase": "ts_exit", "t": time.monotonic()})
    Supervisor._terminal_shutdown = hooked_ts
    real_sws = Supervisor.stop_win_sampler
    def hooked_sws(self2):
        timeline.append({"phase": "sws_enter", "t": time.monotonic(),
                         "deadline": self2._finalize_deadline})
        out = real_sws(self2)
        timeline.append({"phase": "sws_exit", "t": time.monotonic()})
        return out
    Supervisor.stop_win_sampler = hooked_sws
    if mode in ("b01", "b03"):
        # win sampler 身份的受控辅助任务(忽略 TERM)
        wm = os.path.join(base, "win_ready.marker")
        subprocess.Popen(
            [sys.executable, os.path.join(base, "win_ignore.py"), wm],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        deadline_t = time.time() + 30
        while not os.path.exists(wm):
            if time.time() > deadline_t:
                raise RuntimeError("probe: win READY 未出现")
            time.sleep(0.1)

# ---- b02:TERM→停止中 crash→重复收尾 ----
if mode == "b02":
    # 正常外部停止先进入主循环消费(停止请求),随后 crash
    real_tsc = Supervisor._terminal_state_confirmed
    stop_done = {"v": False}
    def hooked_tsc_b02(self2):
        return real_tsc(self2)
    # 注入:第 20 轮 pump(主循环内)先自发 TERM(被 handler 登记→
    # 主循环消费→request_stop),第 25 轮 crash(停止进行中转异常)
    calls_b02 = {"n": 0}
    def boom_b02(self2, mono):
        calls_b02["n"] += 1
        if calls_b02["n"] == 10:
            print("PROBE_TERM_SENT", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
        if calls_b02["n"] >= 15:
            crash_seen["v"] = True
            print("PROBE_INJECT_CRASH", flush=True)
            raise RuntimeError("probe: crash during stop")
        return real_pump(self2, mono)
    boom = boom_b02  # 替换默认 boom

# ---- C 系列:settrace 行级定位临界边界 ----
if mode.startswith("c0") or mode.startswith("c1"):
    target_line = None
    with open(os.path.join(probe_dir, "r17_supervision.py"),
              encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            if mode in ("c01_pre", "c02_dual", "c04"):
                if "old_mask = signal.pthread_sigmask(" in ln:
                    target_line = i
            else:
                if "_external_stop_count_at_cutoff" in ln \
                        and ln.rstrip().endswith("\\"):
                    target_line = i
    assert target_line is not None, "C 边界目标行未定位"
    print("PROBE_TARGET_LINE=%d" % target_line, flush=True)
    fired = {"v": False}
    def _local(frame, event, arg):
        if event == "line" and frame.f_code.co_name == "finalize" \
                and not fired["v"] and frame.f_lineno == target_line:
            fired["v"] = True
            print("PROBE_SIGNAL_SENT", flush=True)
            if mode in ("c01_pre", "c02_dual", "c04"):
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(0.05)  # C 前完成登记(确定性)
                if mode == "c02_dual":
                    os.kill(os.getpid(), signal.SIGINT)
                    time.sleep(0.05)
            elif mode == "c02_in_repeat":
                # 两种不同信号在屏蔽中各自挂起(S1:同类标准信号
                # 不保证逐个排队,不以重复同号信号断言计数)
                os.kill(os.getpid(), signal.SIGTERM)
                os.kill(os.getpid(), signal.SIGINT)
            else:  # c01_in
                os.kill(os.getpid(), signal.SIGTERM)
        return _local
    def _global(frame, event, arg):
        if event == "call" and frame.f_code.co_name == "finalize" \
                and frame.f_code.co_filename.endswith("r17_supervision.py"):
            return _local
        return None
    sys.settrace(_global)

# ---- c04:临界区消费决定后的发布失败(第二次 write_summary 抛) ----
if mode == "c04":
    real_ws = Supervisor.write_summary
    ws_calls = {"n": 0}
    def hooked_ws(self2):
        ws_calls["n"] += 1
        if ws_calls["n"] >= 2:
            print("PROBE_REWRITE_FAIL", flush=True)
            raise RuntimeError("probe: publish after cutoff failed")
        return real_ws(self2)
    Supervisor.write_summary = hooked_ws

Supervisor._pump_win_lines = boom

# ---- 执行面 ----
if mode == "f01":
    sys.argv = ["r17_supervision.py",
                "--run-dir", os.path.join(base, "run"),
                "--task-kind", "fixture", "--max-seconds", "300",
                "--samples-source", "file:" + samples_path,
                "--obs-ready-deadline", "30",
                "--"] + argv
    from r17_supervision import main as sup_main
    rc = sup_main()
else:
    args = argparse.Namespace(
        run_dir=os.path.join(base, "run"), task_kind="fixture",
        argv=argv, task_cwd=None, max_seconds=0,
        samples_source="file:" + samples_path,
        win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
        expect_artifact=[], obs_ready_deadline=30.0)
    sup = Supervisor(args)
    if mode in ("f02a", "f03", "b01"):
        sup.policy["coop_exit_window_s"] = 2.0
    if mode == "b03":
        sup.policy["coop_exit_window_s"] = 0.4
        sup.policy["finalize_window_s"] = 1.2
    if mode in ("b01",):
        sup.policy["finalize_window_s"] = 5.0
    if mode == "b02":
        sup.policy["coop_exit_window_s"] = 1.5
        sup.policy["finalize_window_s"] = 8.0
    if mode == "f04":
        sup.policy["coop_exit_window_s"] = 1.0
        sup.policy["finalize_window_s"] = 3.0
    if mode in ("b01", "b03"):
        # 受控辅助任务占用 win sampler 身份(进程内直塞;TERM 忽略)
        sup.win_proc = subprocess.Popen(
            [sys.executable, os.path.join(base, "win_ignore.py"),
             os.path.join(base, "win_ready.marker")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
    rc = sup.run()
    if mode == "b02":
        # 重复收尾入口:deadline 不重开、合作窗不重发、幂等 finalize
        before_deadline = sup._finalize_deadline
        before_term = sup.protector.term_sent_at if sup.protector else None
        try:
            sup._terminal_shutdown("probe: repeated shutdown entry")
        except Exception as exc:
            print("PROBE_REPEAT_TS_RAISED=%r" % exc, flush=True)
        print("PROBE_REPEAT_DEADLINE_SAME=%s"
              % (sup._finalize_deadline == before_deadline), flush=True)
        after_term = sup.protector.term_sent_at if sup.protector else None
        print("PROBE_TERM_AT_UNCHANGED=%s"
              % (before_term == after_term), flush=True)
    try:
        if sup.win_proc is not None:
            sup.win_proc.kill()
            sup.win_proc.wait(timeout=5)
    except Exception:
        pass
    print("PROBE_SIG=%r" % sup._external_stop_sig, flush=True)
    print("PROBE_SIG_COUNT=%d" % sup._external_stop_sig_count, flush=True)
    print("PROBE_CONSUMED=%r" % sup._external_stop_consumed, flush=True)
    print("PROBE_COUNT_AT_CUTOFF=%r"
          % sup._external_stop_count_at_cutoff, flush=True)
    if mode in ("b01", "b02", "b03"):
        print("PROBE_TIMELINE=" + json.dumps(timeline), flush=True)
        print("PROBE_BUDGET=%.1f" % sup.policy["finalize_window_s"],
              flush=True)
        print("PROBE_EST_REASON=%r" % sup._finalize_budget_reason,
              flush=True)
        print("PROBE_BUDGET_NOTES=%d"
              % len([n for n in sup._finalize_budget_notes
                     if n.get("phase") == "budget_established"]), flush=True)
    if mode == "f04":
        m = sup._shutdown_step_failures
        print("PROBE_STEP_FAILURES=%s" % ",".join(sorted(m.keys())),
              flush=True)
    if mode in ("f02a", "f02b", "f03"):
        m = sup._shutdown_step_failures
        print("PROBE_STEP_FAILURES=%s" % ",".join(sorted(m.keys())),
              flush=True)

print("PROBE_RUN_RC=%d" % rc, flush=True)
pc = os.path.join(base, "run", "post_cutoff_signal.json")
print("PROBE_POST_CUTOFF_FILE=%s" % os.path.exists(pc), flush=True)
if mode == "c02_mask_restore":
    cur = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    print("PROBE_SIGMASK_AFTER=%s" % (sorted(cur) or "empty"), flush=True)
    print("PROBE_TERM_HANDLER=%r"
          % (signal.getsignal(signal.SIGTERM) is signal.SIG_DFL),
          flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
'''


def _run_sfb_child(tmp_path, mode, biz_ignore=True, max_wait=60.0):
    base = tmp_path / mode
    base.mkdir(parents=True, exist_ok=True)
    if biz_ignore:
        (base / "biz_ignore_term.py").write_text(
            BIZ_IGNORE_SRC, encoding="utf-8")
    (base / "win_ignore.py").write_text(WIN_IGNORE_SRC, encoding="utf-8")
    child = base / "sfb_child.py"
    child.write_text(SFB_CHILD_SRC, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, str(child), str(RUNNER_DIR), str(base), mode],
        start_new_session=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list[str] = []
    done = threading.Event()

    def _reader():
        for ln in p.stdout:
            lines.append(ln.decode("utf-8", "replace").rstrip())
        done.set()
    threading.Thread(target=_reader, daemon=True).start()
    rc = None
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if p.poll() is not None:
            rc = p.returncode
            break
        time.sleep(0.3)
    if rc is None:
        p.kill()
        rc = p.wait(timeout=10)
        lines.append("PROBE_WATCHDOG_KILLED")
    done.wait(timeout=5)
    (base / "child_stdout.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    kv = {}
    for ln in lines:
        if ln.startswith("PROBE_") and "=" in ln:
            k, v = ln.split("=", 1)
            kv[k] = v
    return rc, lines, kv, base / "run"


def _killpg_safe(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


# ------------------------------------------------ F:二次错误隔离
@requires_linux
class TestSecondaryFailureIsolation:
    """F01-F04:升级前二次失败不放弃仍可执行的保护(§4)。"""

    def test_f01_flush_failure_before_escalation_keeps_kill(
            self, tmp_path):
        """F01(真实 coop=30s,真实 main()):crash 后第一次日志 flush
        抛错——产品继续 poll→合作窗满→KILL→真实 rc→成员核验;独立
        邻居存活;未被测试解除故障或兜底杀进程。"""
        neighbor = subprocess.Popen(
            ["bash", "-c", "sleep 120"], start_new_session=True)
        try:
            rc, lines, kv, run_dir = _run_sfb_child(
                tmp_path, "f01", max_wait=120.0)
            assert rc == 3, f"crash 外层 rc=3,实际 {rc};{lines[-6:]}"
            assert any("PROBE_INJECT_FLUSH_FAIL" in ln for ln in lines)
            biz_pid = None
            marker = tmp_path / "f01" / "biz_ready.marker"
            if marker.is_file():
                biz_pid = int(marker.read_text().strip())
            evs = _event_names(run_dir)
            assert "sigkill_sent" in evs, \
                "升级 KILL 必须仍发生(二次 flush 失败不弃保护)"
            summary = _load(run_dir / "summary.json")
            assert summary["business"]["rc"] == -9, \
                "真实 rc(KILL)必须取得"
            assert summary["business"]["protector"][
                "terminal_confirmed"] is True
            assert "flush_logs" in summary.get(
                "shutdown_step_failures", {}), "二次错误有界登记"
            if biz_pid:
                assert not _group_alive(biz_pid), \
                    "supervisor 返回前业务组已结束"
            assert _alive(neighbor.pid), "独立邻居存活(不扩大打击面)"
        finally:
            _killpg_safe(os.getpgid(neighbor.pid))
            neighbor.wait(timeout=10)

    def test_f02a_observe_failure_before_escalation_keeps_kill(
            self, tmp_path):
        """F02a(缩窗):升级前第一次退出观察抛错——信号控制继续,
        KILL 仍发生,业务组结束,二次错误有界登记(USH-01 复现位)。"""
        rc, lines, kv, run_dir = _run_sfb_child(tmp_path, "f02a")
        assert rc == 3
        assert any("PROBE_INJECT_OBSERVE_FAIL" in ln for ln in lines)
        evs = _event_names(run_dir)
        assert "sigkill_sent" in evs
        summary = _load(run_dir / "summary.json")
        assert summary["business"]["rc"] == -9
        assert "observe_exit" in summary["shutdown_step_failures"]

    def test_f02b_exit_log_failure_keeps_real_rc(self, tmp_path):
        """F02b(缩窗):实际 rc 已读到后退出日志链抛错——真实 rc
        保留,封口继续(supervisor_end 在),恢复后可确认。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "f02b", biz_ignore=False)
        assert rc == 3
        assert any("PROBE_INJECT_SCAN_FAIL" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        assert summary["business"]["rc"] == -15, \
            "已读真实 rc(TERM)不因日志失败丢失"
        assert "observe_exit" in summary["shutdown_step_failures"]
        evs = _event_names(run_dir)
        assert "supervisor_end" in evs, "封口未被放弃"

    def test_f03_persistent_log_failure_keeps_control(self, tmp_path):
        """F03(缩窗):日志/通知持续失败(R17ALERT 阻塞+flush 持续抛)
        ——控制身份仍可靠,KILL/核验仍达,必要证据如实不完整。"""
        rc, lines, kv, run_dir = _run_sfb_child(tmp_path, "f03")
        assert rc == 3
        assert any("PROBE_ALERT_BLOCKED" in ln for ln in lines)
        summary = _load(run_dir / "summary.json")
        # KILL 动作由内存状态证实(protector.status 不依赖日志链);
        # 持续 flush 失败下升级日志无法递交 alerts 是如实呈现
        assert summary["business"]["protector"]["kill_sent"] is True,             "KILL 升级仍发生(日志链失败不弃控制)"
        assert summary["business"]["rc"] == -9
        sf = summary["shutdown_step_failures"]
        assert sf.get("flush_logs", {}).get("count", 0) >= 2, \
            "持续失败有界累计(非无界 traceback)"
        assert summary["residual_unconfirmed"] is False
        rr = _load(run_dir / "run_record.json")
        assert rr["evidence_complete"] is False, \
            "必要证据未完成时准确不完整"

    def test_f04_member_scan_failure_no_blind_kill(self, tmp_path):
        """F04(缩窗):成员核验持续失败——不盲杀、不把错误当空成员;
        到期未确认+非零;watchdog 清理另记(测试兜底)。"""
        rc, lines, kv, run_dir = _run_sfb_child(tmp_path, "f04")
        assert rc == 3
        steps = set(kv.get("PROBE_STEP_FAILURES", "").split(","))
        assert {"poll", "residual_scan"} <= steps, kv
        summary = _load(run_dir / "summary.json")
        assert summary["residual_unconfirmed"] is True, \
            "核验失败≠无残留:未确认保持未确认"
        evs = _event_names(run_dir)
        assert "sigkill_sent" not in evs, "不盲杀"
        biz_pid = None
        marker = tmp_path / "f04" / "biz_ready.marker"
        if marker.is_file():
            biz_pid = int(marker.read_text().strip())
        try:
            if biz_pid:
                assert _group_alive(biz_pid), \
                    "身份不可核验时登记组保持未处置(非空成员集合)"
        finally:
            if biz_pid:
                _killpg_safe(biz_pid)  # 测试兜底清理,另记


# ------------------------------------------------ B:共享收尾预算
@requires_linux
class TestSharedShutdownBudget:
    """B01-B03:整个 run 一份收尾预算(§5)。"""

    def test_b01_all_stages_share_remaining_budget(self, tmp_path):
        """B01(缩窗 5s):停止阶段消耗大部分预算后,辅助停止/drain
        只获剩余时间;总链不叠加各层全额;预算事实可核验。"""
        t0 = time.monotonic()
        rc, lines, kv, run_dir = _run_sfb_child(tmp_path, "b01")
        spend = time.monotonic() - t0
        tl = json.loads(kv["PROBE_TIMELINE"])
        phases = {e["phase"]: e for e in tl}
        budget = float(kv["PROBE_BUDGET"])
        ts_enter = phases["ts_enter"]["t"]
        assert phases["sws_enter"]["deadline"] is not None
        sws_in = phases["sws_enter"]["t"]
        sws_out = phases["sws_exit"]["t"]
        remaining_at_sws = budget - (sws_in - ts_enter)
        sws_spend = sws_out - sws_in
        assert sws_spend <= remaining_at_sws + 0.3, \
            f"辅助停止只能消费剩余({remaining_at_sws:.2f}s)," \
            f"实际 {sws_spend:.2f}s"
        assert (sws_out - ts_enter) <= budget + 0.3, \
            "停止+辅助停止不叠加全额"
        summary = _load(run_dir / "summary.json")
        fb = summary["finalize_budget"]
        assert fb["window_s"] == budget
        est = [n for n in fb["notes"]
               if n["phase"] == "budget_established"]
        assert len(est) == 1, "一次建立、一直复用"
        assert fb["establish_reason"].startswith("terminal_shutdown")
        dr = [n for n in fb["notes"] if n["phase"] == "io_drain"]
        assert dr and dr[0]["requested"] == 15.0 \
            and dr[0]["allowed"] <= remaining_at_sws + 0.3, \
            "drain 请求被钳制到剩余预算"
        evs = _event_names(run_dir)
        assert "win_sampler_stop_timeout" in evs, \
            "辅助任务等待如实超时记录"

    def test_b02_deadline_reused_across_repeated_shutdown(self, tmp_path):
        """B02(缩窗):TERM→停止中 crash→重复调用收尾——deadline
        身份与起点不变,合作窗不重发,finalize 不重入,首因保留。"""
        rc, lines, kv, run_dir = _run_sfb_child(tmp_path, "b02")
        assert rc == 3
        assert kv.get("PROBE_REPEAT_DEADLINE_SAME") == "True"
        assert kv.get("PROBE_TERM_AT_UNCHANGED") == "True"
        assert kv.get("PROBE_BUDGET_NOTES") == "1", \
            "重复收尾不重新建立预算"
        assert kv.get("PROBE_EST_REASON", "").startswith(
            "'terminal_shutdown"), kv.get("PROBE_EST_REASON")
        evs = _event_names(run_dir)
        assert evs.count("supervisor_end") == 1, \
            "finalize 幂等(不递归收尾)"
        assert "supervisor_signal" in evs
        assert "supervisor_crash" in evs, "首因保留"

    def test_b03_exhausted_budget_zero_remaining_no_infinite_wait(
            self, tmp_path):
        """B03(缩窗 1.2s):停止阶段耗尽预算——后续等待零剩余不为
        无期限;未确认如实;外层有界失败。"""
        rc, lines, kv, run_dir = _run_sfb_child(tmp_path, "b03")
        assert rc == 3
        tl = json.loads(kv["PROBE_TIMELINE"])
        phases = {e["phase"]: e for e in tl}
        budget = float(kv["PROBE_BUDGET"])
        ts_enter = phases["ts_enter"]["t"]
        sws_in = phases["sws_enter"]["t"]
        sws_out = phases["sws_exit"]["t"]
        sws_spend = sws_out - sws_in
        remaining = budget - (sws_in - ts_enter)
        assert sws_spend <= remaining + 0.4, \
            f"零/低剩余不得转换成全额等待({remaining:.2f}s " \
            f"vs 实际 {sws_spend:.2f}s)"
        assert (sws_out - ts_enter) <= budget + 0.6
        summary = _load(run_dir / "summary.json")
        fb = summary["finalize_budget"]
        assert fb["remaining_at_write"] <= 0.6
        evs = _event_names(run_dir)
        assert "win_sampler_stop_timeout" in evs


# ------------------------------------------------ C:停止决策边界
@requires_linux
class TestCutoffBoundary:
    """C01/C02/C04:截止点 C 的可证明顺序(§6)。"""

    def test_c01_pre_cutoff_signal_participates_in_result(self, tmp_path):
        """C01(正例):最后检查后、临界区前 handler 已实际登记的真实
        TERM——必须参与本 run 结果(rc=4,消费,summary 重写承载),
        不被伪称 C 后事件。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "c01_pre", biz_ignore=False)
        assert rc == 4, f"C 前登记=本 run 取消,rc=4,实际 {rc};{lines[-6:]}"
        assert kv.get("PROBE_CONSUMED") == "True"
        assert kv.get("PROBE_COUNT_AT_CUTOFF") == "1"
        assert kv.get("PROBE_POST_CUTOFF_FILE") == "False", \
            "已消费信号不得再伪称 C 后事件"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM
        assert summary["external_stop_consumed"] is True

    def test_c01_in_cutoff_signal_is_post_cutoff_receipt(self, tmp_path):
        """C01(反例):临界区内(C 标记赋值行,TERM/INT 已屏蔽)发真实
        TERM——handler 只能在 C 后执行:独立回执,结果/封口件不改。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "c01_in", biz_ignore=False)
        assert rc == 0, "真 C 后事件不改写成功结果"
        assert kv.get("PROBE_CONSUMED") == "False"
        assert kv.get("PROBE_COUNT_AT_CUTOFF") == "0"
        assert kv.get("PROBE_POST_CUTOFF_FILE") == "True"
        receipt = _load(run_dir / "post_cutoff_signal.json")
        assert receipt["sig_count_at_cutoff"] == 0
        assert receipt["sig_count_total"] == 1
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] is None
        assert summary["business"]["rc"] == 0

    def test_c02_dual_signals_before_cutoff_first_wins(self, tmp_path):
        """C02:临界区前 TERM+INT 双登记——首因粘性、计数=2、同一
        决策消费;恢复语义(掩码/handler)完好。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "c02_dual", biz_ignore=False)
        assert rc == 4
        assert kv.get("PROBE_SIG") == str(signal.SIGTERM), \
            "首信号粘性(TERM 先登记)"
        assert kv.get("PROBE_SIG_COUNT") == "2"
        assert kv.get("PROBE_CONSUMED") == "True"
        assert kv.get("PROBE_COUNT_AT_CUTOFF") == "2"
        assert kv.get("PROBE_POST_CUTOFF_FILE") == "False"
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] == signal.SIGTERM

    def test_c02_repeated_signals_inside_cutoff_single_receipt(
            self, tmp_path):
        """C02:临界区内重复信号(屏蔽挂起)——解除后逐个登记,回执
        承载计数;不倒改结果。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "c02_in_repeat", biz_ignore=False)
        assert rc == 0
        receipt = _load(run_dir / "post_cutoff_signal.json")
        assert receipt["sig_count_total"] >= 2
        assert receipt["sig_count_at_cutoff"] == 0
        summary = _load(run_dir / "summary.json")
        assert summary["external_stop_sig"] is None
        assert kv.get("PROBE_RUN_RC") == "0"

    def test_c02_mask_and_handler_restored(self, tmp_path):
        """C02:临界区内信号(C 后回执)处理完成后,信号掩码恢复为空、
        TERM handler 恢复默认——临界区不留残余屏蔽(§5.4)。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "c02_mask_restore", biz_ignore=False)
        assert rc == 0
        assert kv.get("PROBE_SIGMASK_AFTER") == "empty", \
            "临界区解除后掩码必须复原"
        assert kv.get("PROBE_TERM_HANDLER") == "True", \
            "handler 恢复默认(SIG_DFL)"
        assert kv.get("PROBE_POST_CUTOFF_FILE") == "True", \
            "临界区内信号归 C 后回执"

    def test_c04_publish_failure_after_cutoff_keeps_failure(self,
                                                             tmp_path):
        """C04:C 已决定、临界区消费后的重写发布失败——外层仍非
        成功(不因 cutoff 已建立而返回成功);消费决定不被撤销。"""
        rc, lines, kv, run_dir = _run_sfb_child(
            tmp_path, "c04", biz_ignore=False)
        assert rc == 3, f"发布失败外层 rc=3,实际 {rc};{lines[-6:]}"
        assert any("PROBE_REWRITE_FAIL" in ln for ln in lines)
        assert kv.get("PROBE_CONSUMED") == "True", \
            "临界区消费决定已做出(不被发布失败撤销)"
        assert kv.get("PROBE_POST_CUTOFF_FILE") == "False"


# ------------------------------------------------ L:出口一致性
@requires_linux
class TestUnifiedOutletsBudget:
    """L01:CLI/直调/准入拒绝/正常/异常出口共享同一收尾事实与预算。"""

    def test_l01_outlets_share_single_budget_fact(self, tmp_path):
        """L01:正常成功/crash/93 早拒绝三出口——每 run 预算恰一条
        建立记录,summary.finalize_budget 事实一致。"""
        # 出口1:正常成功
        sup = _sup(tmp_path / "ok", argv=("--", "bash", "-c", "sleep 1"))
        rc1 = sup.run()
        assert rc1 == 0
        s1 = _load(tmp_path / "ok" / "run" / "summary.json")
        # 出口2:crash(收尾)
        rc2, lines, kv, run_dir = _run_sfb_child(
            tmp_path / "crashdir", "f02a")
        assert rc2 == 3
        s2 = _load(run_dir / "summary.json")
        # 出口3:93 早拒绝(真实 run,采样器不可用)
        base3 = tmp_path / "notready"
        args = argparse.Namespace(
            run_dir=str(base3 / "run"), task_kind="fixture",
            argv=["bash", "-c", "echo should-not-run"],
            task_cwd=None, max_seconds=0, samples_source="",
            win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
            expect_artifact=[], obs_ready_deadline=2.0)
        sup3 = Supervisor(args)
        rc3 = sup3.run()
        assert rc3 == 93
        s3 = _load(base3 / "run" / "summary.json")
        for tag, s in (("ok", s1), ("crash", s2), ("notready", s3)):
            fb = s["finalize_budget"]
            est = [n for n in fb["notes"]
                   if n["phase"] == "budget_established"]
            assert len(est) == 1, f"{tag}: 预算恰一次建立"
            assert fb["establish_reason"], f"{tag}: 建立原因在"
        assert s2["finalize_budget"]["establish_reason"].startswith(
            "terminal_shutdown")
        assert s3["finalize_budget"]["establish_reason"] == \
            "stop_win_sampler", "早拒绝出口经同一预算面"


# ------------------------------------------------ I:工程链联动
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
behavior, mode = sys.argv[4], sys.argv[5]
wf.R17_WORKFLOW_CLI_MODULE = "r17_control_fixture_worker"
wf.QUALIFY_HANDSHAKE_DEADLINE_S = float(
    os.environ.get("R17_CF_DEADLINE", "30"))

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
     "argv": ["never"], "requires_artifacts": [], "output_artifacts": []},
]
plan = {"profile": "rehearsal", "out_dir": str(out),
        "manifest_path": str(out / "manifest.jsonl"),
        "workflow_graph_digest": "cf-fixture-digest",
        "qualify_grant_namespaces": ["cf_ns_a"],
        "steps": steps}
result = execute_workflow_chain_r17(
    plan, session=session, log_dir=out / "logs")
print("CFQUAL " + json.dumps(
    {"ok": result["ok"], "failed_step": result["failed_step"]}))
if not result["ok"]:
    session.record_iteration_aborted(result["failure_reason"][:2000])
session.release(summary="cf fixture")
'''


@requires_linux
class TestEngineeringChainWithShutdownFault:
    """I01:supervisor→工程 coordinator→已授权无数据 worker 单一
    run,叠加一次收尾诊断错误(§7 I01;不拆成两个独立映射)。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    SRC = SYNC / "src"
    RUNNER = SYNC / "stage2_6_1_runner"

    @staticmethod
    def _events(journal):
        return [json.loads(l) for l in
                journal.read_text(encoding="utf-8").splitlines() if l]

    def test_i01_crash_plus_flush_fault_full_chain(self, tmp_path):
        state = tmp_path / "state"
        out = tmp_path / "out"
        script = tmp_path / "cf_runner.py"
        script.write_text(CF_RUNNER_SCRIPT, encoding="utf-8")
        # wrapper:授权完成后 crash + 收尾循环内第一次 flush_logs 抛错
        wrapper = tmp_path / "sup_fault_wrapper.py"
        wrapper.write_text(
            "import os, sys\n"
            "sys.path.insert(0, os.environ['R17U_RUNNER_DIR'])\n"
            "import r17_supervision as rs\n"
            "real_pump = rs.Supervisor._pump_win_lines\n"
            "calls = {'n': 0}\n"
            "def boom(self, mono):\n"
            "    calls['n'] += 1\n"
            "    if calls['n'] >= 120:\n"
            "        raise RuntimeError('i01 注入:supervisor crash')\n"
            "    return real_pump(self, mono)\n"
            "rs.Supervisor._pump_win_lines = boom\n"
            "real_flush = rs.Protector.flush_logs\n"
            "fl = {'thrown': False}\n"
            "def hooked_flush(self):\n"
            "    if calls['n'] >= 120 and not fl['thrown']:\n"
            "        fl['thrown'] = True\n"
            "        raise RuntimeError('i01 注入:收尾 flush 二次失败')\n"
            "    return real_flush(self)\n"
            "rs.Protector.flush_logs = hooked_flush\n"
            "sys.argv = ['r17_supervision.py'] + sys.argv[1:]\n"
            "sys.exit(rs.main())\n", encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SRC) + os.pathsep + str(self.RUNNER),
            CURRICULUM261_R17_STATE_ROOT=str(state),
            R17_CF_DEADLINE="30", R17_CF_BEHAVIOR="sleep_cancel",
            R17_CF_NAMESPACES="cf_ns_a",
            R17U_RUNNER_DIR=str(self.RUNNER))
        samples = tmp_path / "s.jsonl"
        _write_samples(samples, n=80)
        journal = state / "r17_execution_journal.jsonl"
        sup_dir = tmp_path / "sup_run"
        sup = subprocess.run(
            [sys.executable, str(wrapper),
             "--run-dir", str(sup_dir), "--task-kind", "engineering",
             "--max-seconds", "120",
             "--samples-source", f"file:{samples}",
             "--", sys.executable, str(script), str(self.SRC),
             str(state), str(out), "sleep_cancel", "normal"],
            capture_output=True, text=True, timeout=150, env=env,
            cwd=str(self.SYNC))
        assert sup.returncode == 3, \
            f"crash+二次失败外层 rc=3,实际 {sup.returncode} " \
            f"{sup.stdout[-400:]}"
        events = self._events(journal)
        seq = [e["event"] for e in events]
        assert seq.count("grant_issued") >= 1, "停止前授权已完成"
        assert seq.count("grant_revoked") >= 1, "真实取消/撤权"
        term = [e for e in events
                if e["event"] == "qualification_terminal"]
        assert term and term[0].get("status") in (
            "failed", "crashed"), "未确认终止不伪造成 completed"
        assert "chain_iteration_aborted" in seq
        assert seq[-1] == "chain_released"
        assert not [e for e in events
                    if e["event"] == "chain_step_started"
                    and e.get("step") == "fixture_never"], \
            "取消后哨兵零启动"
        # 收尾二次错误有界登记,同一 run 的任务范围处理不受影响
        summary = _load(sup_dir / "summary.json")
        assert "flush_logs" in summary.get(
            "shutdown_step_failures", {}), "二次失败同一 run 记录"
        assert summary["finalize_budget"]["establish_reason"].startswith(
            "terminal_shutdown")
