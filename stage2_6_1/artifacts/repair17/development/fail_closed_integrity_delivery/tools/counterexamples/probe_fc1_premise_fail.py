# -*- coding: utf-8 -*-
"""反例FC-1(SPCSC-01/WP1):线程前提失败后仍可普通成功 + 50ms 复核尾部信号。

接手实现事实假设(待证伪/证实):
  A) finalize 临界区前提核验失败(存在未屏蔽辅助线程)时,现行代码
     走"保守复核"分支:sleep(0.05) → 复核消费 → 基线更新——
     **无信号时 run 照常 rc=0**(能力失效成功降级);
  B) 在 sleep(0.05) 窗口内发送真实 TERM,登记归属仍不可证明
     (依赖调度运气),可能被保守消费(rc=4)也可能被当 C 后事件。

用法:
  python probe_fc1_premise_fail.py <snap_dir> <base_dir> [--signal-in-review]
  snap_dir = 接手快照 r17_supervision.py 所在目录
  --signal-in-review = 变体B:settrace 定位 time.sleep(0.05) 行并在
  进入该行时发送真实 SIGTERM。
"""
import argparse
import json
import os
import signal
import sys
import threading

snap = sys.argv[1]
base = sys.argv[2]
SIG_IN_REVIEW = "--signal-in-review" in sys.argv[3:]
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

# ---- 未屏蔽辅助线程(全程存活;不设掩码) ----
aux_hold = threading.Event()
aux = threading.Thread(target=aux_hold.wait, name="fc1-unshielded-aux",
                       daemon=True)
aux.start()
print(f"PROBE_AUX_STARTED={aux.name}", flush=True)

state = {"fired": False}
if SIG_IN_REVIEW:
    # 定位保守复核 sleep 行(接手快照唯一 time.sleep(0.05))
    review_line = None
    with open(os.path.join(snap, "r17_supervision.py"),
              encoding="utf-8") as fh:
        for i, ln in enumerate(fh, 1):
            if "time.sleep(0.05)" in ln:
                review_line = i
                break
    assert review_line, "定位 time.sleep(0.05) 失败"
    print(f"PROBE_REVIEW_LINE={review_line}", flush=True)

    def _local(frame, event, arg):
        if event != "line" or frame.f_code.co_name != "finalize":
            return _local
        if frame.f_lineno == review_line and not state["fired"]:
            state["fired"] = True
            print("PROBE_SIGNAL_SENT_IN_REVIEW=SIGTERM", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
        return _local

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
print(f"PROBE_PREMISE_OK={sup._cutoff_premise_ok!r}", flush=True)
print(f"PROBE_PREMISE_DETAIL={sup._cutoff_premise_detail!r}", flush=True)
print(f"PROBE_SIG={sup._external_stop_sig!r}", flush=True)
print(f"PROBE_SIG_COUNT={sup._external_stop_sig_count}", flush=True)
print(f"PROBE_CONSUMED={sup._external_stop_consumed!r}", flush=True)
print(f"PROBE_COUNT_AT_CUTOFF={sup._external_stop_count_at_cutoff!r}",
      flush=True)
print(f"PROBE_AUX_ALIVE={aux.is_alive()}", flush=True)
# 事件面:cutoff_thread_premise_failed / 保守消费 / mask_unavailable
log_path = os.path.join(base, "run", "events.jsonl")
if os.path.isfile(log_path):
    evs = [json.loads(ln) for ln in
           open(log_path, encoding="utf-8").read().splitlines() if ln.strip()]
    names = [e.get("event") for e in evs]
    print(f"PROBE_PREMISE_FAILED_EVENT={'cutoff_thread_premise_failed' in names}",
          flush=True)
    print(f"PROBE_CONSERVATIVE_EVENT={'cutoff_signal_conservatively_consumed' in names}",
          flush=True)
sm = os.path.join(base, "run", "summary.json")
if os.path.isfile(sm):
    d = json.loads(open(sm, encoding="utf-8").read())
    print(f"PROBE_SUMMARY_PREMISE={d.get('cutoff_premise_ok')!r}",
          flush=True)
rr = os.path.join(base, "run", "run_record.json")
if os.path.isfile(rr):
    d = json.loads(open(rr, encoding="utf-8").read())
    print(f"PROBE_RR_EVIDENCE={d.get('evidence_complete')!r}", flush=True)
    print(f"PROBE_RR_FINALIZED={d.get('finalized')!r}", flush=True)
aux_hold.set()
aux.join(timeout=5)
sys.exit(rc if 0 <= rc < 256 else 0)
