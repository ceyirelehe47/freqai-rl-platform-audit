#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 子进程:真实 Python 3.11 模块 + sys.settrace 行级定位,验证修改后
的停止决策边界 C(sigmask 临界区)。

mode=pre :在临界区进入行(pthread_sigmask BLOCK 调用)执行前发真实
          SIGTERM 并等待 handler 完成登记——C 前登记必须被临界区内
          最后判定看到并消费:rc=4、consumed=True、summary 重写承载。
mode=in  :在 C 标记赋值行(临界区内、TERM/INT 已屏蔽)发真实 SIGTERM
          ——信号挂起待决,C 建立后解除屏蔽才执行 handler:必然归为
          C 后事件(独立回执),rc 不改、封口件不被改写。
"""
import argparse
import json
import os
import signal
import sys
import time

probe_dir, base, mode = sys.argv[1], sys.argv[2], sys.argv[3]
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

argv = ["bash", "-c", "sleep 1"]
args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=argv, task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)

# 行定位:pre=临界区进入行(pthread_sigmask BLOCK 赋值);in=C 标记
# 赋值行(_external_stop_count_at_cutoff 带续行符;取最后匹配)。
target_line = None
with open(os.path.join(probe_dir, "r17_supervision.py"),
          encoding="utf-8") as fh:
    for i, ln in enumerate(fh, 1):
        if mode == "pre":
            if "old_mask = signal.pthread_sigmask(" in ln:
                target_line = i
        else:
            if "_external_stop_count_at_cutoff" in ln \
                    and ln.rstrip().endswith("\\"):
                target_line = i
assert target_line is not None, "目标行未定位"
print("PROBE_TARGET_LINE=%d" % target_line, flush=True)

fired = {"v": False}


def _local(frame, event, arg):
    if event == "line" and frame.f_code.co_name == "finalize" \
            and not fired["v"] and frame.f_lineno == target_line:
        # line 事件在该行首个字节码执行前触发。
        fired["v"] = True
        print("PROBE_SIGNAL_SENT", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        if mode == "pre":
            # 等待主线程 handler 完成登记(信号中断 sleep 执行 handler
            # 是 CPython 主线程标准行为)——确定"C 前已登记"形态。
            time.sleep(0.05)
            print("PROBE_HANDLER_DONE=%r" % sup._external_stop_sig,
                  flush=True)
        # mode=in:不等待——信号在屏蔽临界区内挂起,handler 只能在
        # C 建立并解除屏蔽后执行(必然归为 C 后事件)。
    return _local


def _global(frame, event, arg):
    if event == "call" and frame.f_code.co_name == "finalize" \
            and frame.f_code.co_filename.endswith("r17_supervision.py"):
        return _local
    return None


sys.settrace(_global)
rc = sup.run()
sys.settrace(None)
print("PROBE_RUN_RC=%d" % rc, flush=True)
print("PROBE_SIG=%r" % sup._external_stop_sig, flush=True)
print("PROBE_SIG_COUNT=%d" % sup._external_stop_sig_count, flush=True)
print("PROBE_CONSUMED=%r" % sup._external_stop_consumed, flush=True)
print("PROBE_CUTOFF_REACHED=%r" % sup._stop_cutoff_reached, flush=True)
print("PROBE_COUNT_AT_CUTOFF=%r"
      % sup._external_stop_count_at_cutoff, flush=True)
pc = os.path.join(base, "run", "post_cutoff_signal.json")
print("PROBE_POST_CUTOFF_FILE=%s" % os.path.exists(pc), flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
