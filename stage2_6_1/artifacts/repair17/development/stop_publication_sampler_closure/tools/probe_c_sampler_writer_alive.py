# -*- coding: utf-8 -*-
"""反例C(SFB-03):guest 采样线程在途写入时 join 超时——句柄被置 None、
evidence_complete 仍为 true,释放屏障后文件继续增长。

事实假设(接手实现):finalize 中 guest join 超时后直接
  self.guest_sampler = None(句柄丢弃,无未确认状态);
_evidence_ok 的输入不含 guest 采样线程存活状态;run_record 的
writers_live 不含采样器。采样线程在 emit(真实文件写入路径)内阻塞
时,run 仍可给出 evidence_complete=true 的完成件,且随后文件继续变化。

本脚本:非 replay 真实运行(真实 win sampler + 真实 guest 采样线程),
业务为快速成功命令。emit 屏障:业务退出被观测到(_observe_business_exit
首次看到 poll 完成)后,guest 线程的下一次 emit(含必然发生的
guest_sampler_end)阻塞在受控屏障;join(15s) 必然超时。
"""
import argparse
import json
import os
import sys
import threading

snap = sys.argv[1]
base = sys.argv[2]
ps1 = sys.argv[3]  # 真实 ps1 路径(Windows 侧发布仓库)
sys.path.insert(0, snap)
from r17_supervision import Supervisor  # noqa: E402

block_flag = threading.Event()
release_gate = threading.Event()
guest_thread_ref = {"t": None}
emit_count = {"n": 0}

real_emit = Supervisor._emit_guest


def hooked_emit(self, rec):
    if threading.current_thread().name == "r17-guest-sampler":
        guest_thread_ref["t"] = threading.current_thread()
    emit_count["n"] += 1
    if block_flag.is_set():
        print(f"PROBE_EMIT_BLOCKED seq={rec.get('seq')}",
              flush=True)
        release_gate.wait(60.0)
        print("PROBE_EMIT_RELEASED", flush=True)
    return real_emit(self, rec)


Supervisor._emit_guest = hooked_emit

real_obs = Supervisor._observe_business_exit
obs_done = {"v": False}


def hooked_obs(self):
    if not obs_done["v"] and self.biz_proc is not None \
            and self.biz_proc.poll() is not None:
        obs_done["v"] = True
        print("PROBE_BIZ_EXIT_SEEN", flush=True)
        block_flag.set()
    return real_obs(self)


Supervisor._observe_business_exit = hooked_obs

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "echo probe_c_ok"], task_cwd=None,
    max_seconds=0, samples_source="",
    win_sampler_ps1=ps1, win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)
rc = sup.run()

print(f"PROBE_RUN_RC={rc}", flush=True)
print(f"PROBE_GUEST_REF={sup.guest_sampler!r}", flush=True)
t = guest_thread_ref["t"]
print(f"PROBE_GUEST_THREAD_IDENTIFIED={t is not None}", flush=True)
if t is not None:
    print(f"PROBE_GUEST_THREAD_ALIVE_AFTER_RUN={t.is_alive()}",
          flush=True)
    # 释放屏障前记录 guest 遥测文件大小;释放后再对比
    gp = sup.guest_path
    size_before = None
    try:
        size_before = os.path.getsize(gp)
    except OSError:
        pass
    print(f"PROBE_GUEST_FILE_SIZE_BEFORE_RELEASE={size_before}",
          flush=True)
    release_gate.set()
    import time as _t
    _t.sleep(3.0)
    try:
        size_after = os.path.getsize(gp)
    except OSError:
        size_after = None
    print(f"PROBE_GUEST_FILE_SIZE_AFTER_RELEASE={size_after}", flush=True)
    print(f"PROBE_GUEST_FILE_GREW="
          f"{size_before is not None and size_after is not None and size_after > size_before}",
          flush=True)
    print(f"PROBE_GUEST_THREAD_ALIVE_FINAL={t.is_alive()}", flush=True)
rr = os.path.join(base, "run", "run_record.json")
if os.path.isfile(rr):
    d = json.loads(open(rr, encoding="utf-8").read())
    print(f"PROBE_RR_FINALIZED={d.get('finalized')!r}", flush=True)
    print(f"PROBE_RR_EVIDENCE={d.get('evidence_complete')!r}", flush=True)
sm = os.path.join(base, "run", "summary.json")
if os.path.isfile(sm):
    d = json.loads(open(sm, encoding="utf-8").read())
    print(f"PROBE_SUMMARY_EMITS={emit_count['n']}", flush=True)
# alerts 事件序列(证明 join 超时被记录但 stopped 仍写)
al = os.path.join(base, "run", "alerts", "alerts.jsonl")
if os.path.isfile(al):
    names = []
    for ln in open(al, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            try:
                names.append(json.loads(ln).get("event"))
            except json.JSONDecodeError:
                pass
    print(f"PROBE_ALERT_EVENTS={names}", flush=True)
# 采样进程兜底清理(测试父进程职责,不计产品行为)
try:
    if sup.win_proc is not None and sup.win_proc.poll() is None:
        sup.win_proc.kill()
        sup.win_proc.wait(timeout=5)
except Exception:
    pass
sys.exit(rc if 0 <= rc < 256 else 0)
