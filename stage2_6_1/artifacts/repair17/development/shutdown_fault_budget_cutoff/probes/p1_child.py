#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1 子进程:真实 main() 入口;主循环 crash 后,_terminal_shutdown 循环内
第一次退出观察抛错(升级尚未完成的位置)。验证旧代码放弃仍可执行的保护。"""
import json
import os
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

crash_seen = {"v": False}
real_pump = Supervisor._pump_win_lines


def boom(self2, mono):
    # READY 证明(TERM 忽略已安装)先于异常注入
    ready = os.path.join(base, "biz_ready.marker")
    deadline = time.time() + 30
    while not os.path.exists(ready):
        if time.time() > deadline:
            raise RuntimeError("probe: biz READY 未出现")
        time.sleep(0.1)
    crash_seen["v"] = True
    print("PROBE_INJECT_CRASH", flush=True)
    raise RuntimeError("probe-injected pump failure")


Supervisor._pump_win_lines = boom

obs_state = {"thrown": False}
real_obs = Supervisor._observe_business_exit


def hooked_obs(self2):
    # crash 后第一次退出观察抛错(此时 TERM 已发、KILL 尚未发:
    # 升级前的二次失败位置)
    if crash_seen["v"] and not obs_state["thrown"]:
        obs_state["thrown"] = True
        print("PROBE_INJECT_OBSERVE_FAIL", flush=True)
        raise RuntimeError("probe: observe failure before escalation")
    return real_obs(self2)


Supervisor._observe_business_exit = hooked_obs

sys.argv = ["r17_supervision.py",
            "--run-dir", os.path.join(base, "run"),
            "--task-kind", "fixture", "--max-seconds", "300",
            "--samples-source", "file:" + samples_path,
            "--obs-ready-deadline", "30",
            "--"] + argv
from r17_supervision import main as sup_main  # noqa: E402
rc = sup_main()
print("PROBE_RUN_RC=%d" % rc, flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
