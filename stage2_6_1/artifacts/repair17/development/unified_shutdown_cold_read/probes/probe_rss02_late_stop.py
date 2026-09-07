# -*- coding: utf-8 -*-
"""RSS-02 反例:late-stop 在收尾窗口只留字段、未被消费、outer rc=0。

三个明确事件边界(不靠 stdout 次数):
  A finalize_begin —— finalize() 进入时向自己发 TERM(生产 handler 已
    由 run() 注册,登记意图),然后正常 finalize;
  B drain —— 原始 writer seal 后、drain 执行时发 TERM;
  C pre_summary —— write_summary() 调用紧前发 TERM(结果提交边界)。

业务 sleep 1 自然成功退出(raw rc=0)。缺陷形态(接手版预期):
三边界 run() 均返回 0(external_stop_sig 已登记但未消费、
stop_requested_reasons 空、control_outcome 走到 biz_rc==0)。

用法(WSL):
  R17U_SNAP=$HOME/r17u_snap_handover \
  python3 probe_rss02_late_stop.py <输出json路径>
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SNAP = Path(os.environ["R17U_SNAP"])
OUT = Path(sys.argv[1])
BOUNDARIES = ("finalize_begin", "drain", "pre_summary")

CHILD_SRC = r'''
import argparse, json, os, signal, sys, time
snap, base, boundary = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, snap)
from r17_supervision import Supervisor

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
         "psi_memory": {"full_avg10": 0.0}, "vmstat_swap": {"pswpout": 0}}
samples = os.path.join(base, "samples.jsonl")
with open(samples, "w") as fh:
    fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "sleep 1"], task_cwd=None, max_seconds=0,
    samples_source="file:" + samples,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)

fired = {"v": False}
def fire(tag):
    if not fired["v"]:
        fired["v"] = True
        print("PROBE_FIRED_AT=" + tag, flush=True)
        os.kill(os.getpid(), signal.SIGTERM)  # 生产 handler 只登记

if boundary == "finalize_begin":
    real_finalize = Supervisor.finalize
    def hooked_finalize(self2):
        fire("finalize_begin")
        return real_finalize(self2)
    Supervisor.finalize = hooked_finalize
elif boundary == "drain":
    real_drain = sup.iow.drain
    def hooked_drain(timeout):
        fire("drain")
        return real_drain(timeout)
    sup.iow.drain = hooked_drain
elif boundary == "pre_summary":
    real_ws = Supervisor.write_summary
    def hooked_ws(self2):
        fire("pre_summary")
        return real_ws(self2)
    Supervisor.write_summary = hooked_ws

rc = sup.run()
summary = json.load(open(os.path.join(base, "run", "summary.json"),
                         encoding="utf-8"))
print("PROBE_RESULT=" + json.dumps({
    "boundary": boundary, "run_rc": rc,
    "external_stop_sig": summary.get("external_stop_sig"),
    "external_stop_consumed": summary.get("external_stop_consumed"),
    "stop_requested_reasons": summary.get("stop_requested_reasons"),
    "biz_rc": (summary.get("business") or {}).get("rc")}, ensure_ascii=False),
    flush=True)
'''


def main() -> None:
    results = []
    for b in BOUNDARIES:
        base = Path.home() / f"r17u_probe_rss02_{b}_{int(time.time())}"
        base.mkdir(parents=True, exist_ok=True)
        (base / "runner_child.py").write_text(CHILD_SRC, encoding="utf-8")
        child = subprocess.Popen(
            [sys.executable, str(base / "runner_child.py"),
             str(SNAP), str(base), b], start_new_session=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + 90
        rc = None
        while time.time() < deadline:
            if child.poll() is not None:
                rc = child.returncode
                break
            time.sleep(0.5)
        if rc is None:
            child.kill()
            rc = child.wait()
        out = child.communicate()[0].decode("utf-8", "replace")
        rec = None
        for ln in out.splitlines():
            if ln.startswith("PROBE_RESULT="):
                rec = json.loads(ln[len("PROBE_RESULT="):])
        if rec is None:
            rec = {"boundary": b, "error": "no PROBE_RESULT",
                   "child_rc": rc, "tail": out[-500:]}
            results.append(rec)
            continue
        rec["fired"] = f"PROBE_FIRED_AT={b}" in out
        # 缺陷判定:信号已登记(非 null)+raw rc=0+run 返回 0(普通成功)
        rec["reproduced"] = bool(
            rec.get("fired")
            and rec.get("external_stop_sig") is not None
            and rec.get("biz_rc") == 0
            and rec.get("run_rc") == 0)
        results.append(rec)
    payload = {"probe": "rss02_late_stop", "boundaries": results,
               "reproduced_any": any(r.get("reproduced")
                                     for r in results)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
