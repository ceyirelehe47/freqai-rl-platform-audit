# -*- coding: utf-8 -*-
"""反例A(SFB-01):真实多线程下的截止点 C 与 C 前发布。

事实假设(接手实现):
  1) finalize 顺序为 seal→drain→检查点③→write_summary→finalize_run_record
     →[临界区]——summary 与 finalized=true 的 run_record 在 C 之前已公开;
  2) 临界区 pthread_sigmask 只屏蔽主线程;r17-io-writer 线程(seal/drain
     后仍存活、阻塞于 queue.get)未屏蔽——TERM 发出后由未屏蔽线程接收,
     CPython C handler 置 tripped,Python handler(_sig_external)在主线程
     下一个字节码边界立即执行,与主线程掩码无关;
  3) 若 handler 执行落在"临界区最后判定之后、_external_stop_count_at_cutoff
     赋值之前",信号已被登记(count 已 +1)却不被消费、不触发重写——
     rc 仍为 0,停止被漏接。

本脚本在接手快照副本上用 sys.settrace 行级定位两个观察点:
  观察点1 = "old_mask = signal.pthread_sigmask(" 行(临界区进入前):
            记录 run_record.json 是否已存在且 finalized=true;
  观察点2 = "_external_stop_count_at_cutoff" 赋值语句行(最后判定已过):
            记录真实线程清单,发送真实 SIGTERM,给 0.05s 确定性调度窗口。
"""
import argparse
import json
import os
import signal
import sys
import threading

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

# ---- settrace 定位两个观察点(按快照源码文本匹配) ----
mask_line = cutoff_line = None
with open(os.path.join(snap, "r17_supervision.py"),
          encoding="utf-8") as fh:
    for i, ln in enumerate(fh, 1):
        if "old_mask = signal.pthread_sigmask(" in ln:
            mask_line = i
        if cutoff_line is None and \
                "_external_stop_count_at_cutoff" in ln and \
                ln.rstrip().endswith("\\"):
            cutoff_line = i  # 第一个匹配=C 赋值语句行(保守分支同款
            # 文本在赋值之后出现,且仅在前提失败路径执行)
assert mask_line and cutoff_line, \
    f"观察点定位失败 mask={mask_line} cutoff={cutoff_line}"
print(f"PROBE_MASK_LINE={mask_line}", flush=True)
print(f"PROBE_CUTOFF_LINE={cutoff_line}", flush=True)

state = {"mask_seen": False, "fired": False}


def _local(frame, event, arg):
    if event != "line" or frame.f_code.co_name != "finalize":
        return _local
    ln = frame.f_lineno
    if ln == mask_line and not state["mask_seen"]:
        state["mask_seen"] = True
        rr = os.path.join(base, "run", "run_record.json")
        finalized = None
        if os.path.isfile(rr):
            try:
                finalized = json.loads(
                    open(rr, encoding="utf-8").read()).get("finalized")
            except Exception as exc:  # noqa: BLE001
                finalized = f"read_error:{exc}"
        print(f"PROBE_RR_BEFORE_C={rr_exists_and_finalized(os.path.isfile(rr), finalized)}",
              flush=True)
        threads = [t.name for t in threading.enumerate()]
        print(f"PROBE_THREADS_BEFORE_MASK={threads}", flush=True)
    if ln == cutoff_line and not state["fired"]:
        state["fired"] = True
        threads = [t.name for t in threading.enumerate()]
        print(f"PROBE_THREADS_AT_C={threads}", flush=True)
        cur_mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
        print(f"PROBE_MAIN_MASK_AT_C={sorted(cur_mask) or 'empty'}",
              flush=True)
        print("PROBE_SIGNAL_SENT=SIGTERM", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
        time_sleep(0.05)  # 确定性窗口:接收线程 C handler + 主线程 handler
        print(f"PROBE_AFTER_SEND_COUNT={frame.f_locals.get('_external_stop_sig_count')}",
              flush=True)
    return _local


def rr_exists_and_finalized(exists, finalized):
    return f"exists={exists},finalized={finalized}"


def time_sleep(s):
    import time as _t
    _t.sleep(s)


def _global(frame, event, arg):
    if event == "call" and frame.f_code.co_name == "finalize" \
            and frame.f_code.co_filename.endswith("r17_supervision.py"):
        return _local
    return None


sys.settrace(_global)

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "sleep 1"], task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)
rc = sup.run()

print(f"PROBE_RUN_RC={rc}", flush=True)
print(f"PROBE_SIG={sup._external_stop_sig!r}", flush=True)
print(f"PROBE_SIG_COUNT={sup._external_stop_sig_count}", flush=True)
print(f"PROBE_CONSUMED={sup._external_stop_consumed!r}", flush=True)
print(f"PROBE_COUNT_AT_CUTOFF={sup._external_stop_count_at_cutoff!r}",
      flush=True)
pc = os.path.join(base, "run", "post_cutoff_signal.json")
print(f"PROBE_POST_CUTOFF_FILE={os.path.exists(pc)}", flush=True)
if os.path.isfile(pc):
    print("PROBE_POST_CUTOFF=" + open(pc, encoding="utf-8").read(),
          flush=True)
sm = os.path.join(base, "run", "summary.json")
if os.path.isfile(sm):
    d = json.loads(open(sm, encoding="utf-8").read())
    print(f"PROBE_SUMMARY_SIG={d.get('external_stop_sig')!r}", flush=True)
    print(f"PROBE_SUMMARY_COUNT={d.get('external_stop_sig_count')!r}",
          flush=True)
    fb = d.get("finalize_budget") or {}
    print(f"PROBE_SUMMARY_EST_REASON={fb.get('establish_reason')!r}",
          flush=True)
rr = os.path.join(base, "run", "run_record.json")
if os.path.isfile(rr):
    d = json.loads(open(rr, encoding="utf-8").read())
    print(f"PROBE_RR_FINALIZED={d.get('finalized')!r}", flush=True)
    print(f"PROBE_RR_EVIDENCE={d.get('evidence_complete')!r}", flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
