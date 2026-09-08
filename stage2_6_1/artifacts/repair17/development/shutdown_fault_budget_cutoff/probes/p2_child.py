#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 子进程:进程内构造;缩窗工程预算(coop=2s, finalize=5s);停止阶段
消耗大部分预算后进入辅助停止与 drain。记录每次请求的 timeout 与真实耗时,
验证旧代码各层重新获得全额等待。"""
import argparse
import json
import os
import subprocess
import sys
import time

probe_dir, base = sys.argv[1], sys.argv[2]
sys.path.insert(0, probe_dir)
from r17_supervision import Supervisor  # noqa: E402

import datetime as _dt


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


win = {"event": "sample", "seq": 1, "utc": utc_now(),
       "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
       "vols": [
           {"vol": "F:", "present": True, "free_gb": 100.0,
            "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
           {"vol": "C:", "present": True, "free_gb": 200.0,
            "size_gb": 900.0, "serial": "CCA1", "identity_match": True}],
       "telemetry_out_writable": True}
guest = {"event": "guest_sample", "utc": utc_now(),
         "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
         "psi_memory": {"full_avg10": 0.0},
         "vmstat_swap": {"pswpout": 0}}
samples_path = os.path.join(base, "samples.jsonl")
with open(samples_path, "w", encoding="utf-8") as fh:
    for _ in range(40):
        fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

argv = [sys.executable, os.path.join(base, "biz_ignore_term.py"),
        os.path.join(base, "biz_ready.marker")]
args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=argv, task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)
# 运行前收紧工程预算(仅允许收紧;U04b 同款模式)
sup.policy["coop_exit_window_s"] = 2.0
sup.policy["finalize_window_s"] = 5.0

# 受控辅助任务(占用 win sampler 身份):忽略 TERM,使 stop_win_sampler
# 的 wait(timeout=10) 真实全额等待;先证明其忽略已安装再放行 crash。
win_marker = os.path.join(base, "win_ready.marker")
sup.win_proc = subprocess.Popen(
    [sys.executable, os.path.join(base, "win_ignore.py"), win_marker],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    start_new_session=True)

timeline = []
real_ts = Supervisor._terminal_shutdown


def hooked_ts(self2, reason):
    timeline.append({"phase": "terminal_shutdown_enter",
                     "t": time.monotonic(), "reason": reason})
    try:
        return real_ts(self2, reason)
    finally:
        timeline.append({"phase": "terminal_shutdown_exit",
                         "t": time.monotonic()})


Supervisor._terminal_shutdown = hooked_ts

real_sws = Supervisor.stop_win_sampler


def hooked_sws(self2):
    timeline.append({"phase": "stop_win_sampler_enter",
                     "t": time.monotonic()})
    out = real_sws(self2)
    timeline.append({"phase": "stop_win_sampler_exit",
                     "t": time.monotonic()})
    return out


Supervisor.stop_win_sampler = hooked_sws

real_drain = sup.iow.drain


def hooked_drain(timeout):
    timeline.append({"phase": "drain_enter", "t": time.monotonic(),
                     "timeout_requested": timeout})
    out = real_drain(timeout)
    timeline.append({"phase": "drain_exit", "t": time.monotonic()})
    return out


sup.iow.drain = hooked_drain

crash_seen = {"v": False}
real_pump = Supervisor._pump_win_lines


def boom(self2, mono):
    if not crash_seen["v"]:
        ready = os.path.join(base, "biz_ready.marker")
        deadline = time.time() + 30
        while not (os.path.exists(ready) and os.path.exists(win_marker)):
            if time.time() > deadline:
                raise RuntimeError("probe: READY 未出现")
            time.sleep(0.1)
        crash_seen["v"] = True
        print("PROBE_INJECT_CRASH", flush=True)
        raise RuntimeError("probe-injected pump failure")
    return real_pump(self2, mono)


Supervisor._pump_win_lines = boom

rc = sup.run()
# 测试自身清理受控辅助任务(不计产品行为)
try:
    sup.win_proc.kill()
    sup.win_proc.wait(timeout=5)
except Exception:
    pass
print("PROBE_RUN_RC=%d" % rc, flush=True)
print("PROBE_TIMELINE=" + json.dumps(timeline), flush=True)
print("PROBE_BUDGET=%.1f" % sup.policy["finalize_window_s"], flush=True)
sys.exit(0)
