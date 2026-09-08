# -*- coding: utf-8 -*-
"""反例B(SFB-02):第一次接受外部 TERM 时不建立总 deadline。

事实假设(接手实现):外部 TERM 的消费链为
  _consume_external_stop → handle_triggers → protector.request_stop,
该链不调用 _ensure_finalize_budget;deadline 只在随后异常收尾
(_terminal_shutdown)或正常 finalize 才建立。TERM 被接受后业务
合作退出所消耗的时间不计入 finalize_window_s 窗口。

本脚本:业务捕获 TERM 后 sleep 2 再退出(真实合作退出),主循环第 10
轮 pump 发真实 SIGTERM(进程内自发,与外部等价:handler 登记→主循环
消费)。记录第一次消费时刻与第一次预算建立时刻。
"""
import argparse
import json
import os
import signal
import sys

snap = sys.argv[1]
base = sys.argv[2]
sys.path.insert(0, snap)
from r17_supervision import Supervisor  # noqa: E402

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

# 合作退出业务:捕获 TERM → 2s 后退出(真实合作窗消耗)
biz_src = '''import signal, sys, time
def _h(s, f):
    print("BIZ_TERM_RECEIVED", flush=True)
    time.sleep(2.0)
    sys.exit(0)
signal.signal(signal.SIGTERM, _h)
print("BIZ_READY", flush=True)
time.sleep(120)
'''
biz_path = os.path.join(base, "biz_coop.py")
with open(biz_path, "w", encoding="utf-8") as fh:
    fh.write(biz_src)

# hook:第一次消费外部停止 / 第一次建立预算 的时刻
import time as _time
first = {"consume": None, "est": None, "est_reason": None}
real_consume = Supervisor._consume_external_stop


def hooked_consume(self):
    if first["consume"] is None:
        first["consume"] = _time.monotonic()
        print("PROBE_TERM_CONSUMED_AT=%.3f" % first["consume"], flush=True)
    return real_consume(self)


Supervisor._consume_external_stop = hooked_consume
real_ensure = Supervisor._ensure_finalize_budget


def hooked_ensure(self, reason):
    if first["est"] is None:
        first["est"] = _time.monotonic()
        first["est_reason"] = reason
        print("PROBE_BUDGET_EST_AT=%.3f" % first["est"], flush=True)
        print("PROBE_BUDGET_EST_REASON=%r" % reason, flush=True)
    return real_ensure(self, reason)


Supervisor._ensure_finalize_budget = hooked_ensure

# 第 10 轮 pump:主循环内发真实 TERM(handler 登记→主循环消费)
real_pump = Supervisor._pump_win_lines
calls = {"n": 0}


def boom(self, mono):
    calls["n"] += 1
    if calls["n"] == 10:
        print("PROBE_TERM_SENT", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
    return real_pump(self, mono)


Supervisor._pump_win_lines = boom

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=[sys.executable, biz_path], task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)
sup.policy["coop_exit_window_s"] = 6.0
sup.policy["finalize_window_s"] = 5.0
rc = sup.run()

print(f"PROBE_RUN_RC={rc}", flush=True)
if first["consume"] is not None and first["est"] is not None:
    delta = first["est"] - first["consume"]
    print(f"PROBE_DELTA_EST_MINUS_CONSUME={delta:.3f}", flush=True)
    print(f"PROBE_WINDOW=5.0", flush=True)
    print(f"PROBE_REMAINING_IF_EARLY={max(0.0, 5.0 - delta):.3f}",
          flush=True)
sm = os.path.join(base, "run", "summary.json")
if os.path.isfile(sm):
    d = json.loads(open(sm, encoding="utf-8").read())
    fb = d.get("finalize_budget") or {}
    print(f"PROBE_SUMMARY_EST_REASON={fb.get('establish_reason')!r}",
          flush=True)
    print(f"PROBE_SUMMARY_EST_AT={fb.get('established_at_mono')!r}",
          flush=True)
    print(f"PROBE_SUMMARY_REMAIN_AT_WRITE="
          f"{fb.get('remaining_at_write')!r}", flush=True)
rr = os.path.join(base, "run", "run_record.json")
if os.path.isfile(rr):
    d = json.loads(open(rr, encoding="utf-8").read())
    print(f"PROBE_RR_FINALIZED={d.get('finalized')!r}", flush=True)
    print(f"PROBE_RR_EVIDENCE={d.get('evidence_complete')!r}", flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
