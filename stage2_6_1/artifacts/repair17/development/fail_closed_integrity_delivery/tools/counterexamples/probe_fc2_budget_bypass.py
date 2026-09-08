# -*- coding: utf-8 -*-
"""反例FC-2(SPSC-02A/WP2-A):budget_check 停止后活写者被 None 掩盖。

接手实现事实假设(待证实):
  1) guest 线程在 _emit_guest 真实文件写入中被事件屏障挂住(在途
     采样写者);
  2) 遥测预算保护经真实 budget_check() 路径触发(主循环首轮调用;
     预算值在构造后注入为受控小值,telemetry_bytes 真实统计);
  3) budget_check 内 stop 后立即 guest_sampler=None;
  4) 保护停止→正常收尾 finalize:guest join 段因句柄 None 被跳过,
     _guest_close_state 保持 None(未知被掩盖);
  5) run_record.writers.guest=None、telemetry_guest 无 live_writers,
     evidence_complete 不受活写者影响;实际 verifier 接受该包。

观察:句柄/关闭状态/线程真实存活/文件增长/run_record/verify rc。
"""
import argparse
import json
import os
import subprocess
import sys
import threading

snap = sys.argv[1]
base = sys.argv[2]
sys.path.insert(0, snap)
from r17_supervision import Supervisor  # noqa: E402

RUNNER = os.path.dirname(os.path.abspath(
    os.path.join(snap, "r17_supervision.py")))

# ---- 屏障:emit1 正常(供就绪判定),emit2 真实文件写完成后在途挂住 ----
# 时序:emit2 写边界完成后(真实 open+write+close 已发生),由本线程
# 调用真实 budget_check()(受控预算已注入)触发遥测预算保护停止,
# 随后挂屏障=收尾 finalize 发生时 guest 恰为在途采样写者。
hold = threading.Event()
emit_count = {"n": 0}
orig_emit = Supervisor._emit_guest
guest_thread_ref = {}


def emit_patched(self, rec):
    emit_count["n"] += 1
    if emit_count["n"] == 2:
        orig_emit(self, rec)  # 真实文件写入(open+write+close)
        guest_thread_ref["t"] = threading.current_thread()
        print("PROBE_EMIT_IN_FLIGHT=True", flush=True)
        self.policy["telemetry_budget_bytes"] = 1
        self.budget_check()  # 真实方法+真实 telemetry_bytes 统计
        print("PROBE_BUDGET_CHECK_CALLED=True", flush=True)
        hold.wait(timeout=300.0)  # 在途采样写者屏障(测试 finally 释放)
        print("PROBE_EMIT_RELEASED=True", flush=True)
        return
    return orig_emit(self, rec)


Supervisor._emit_guest = emit_patched

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "sleep 8"], task_cwd=None, max_seconds=0,
    samples_source="",
    win_sampler_ps1=os.path.join(RUNNER, "r17_win_sampler.ps1"),
    win_volumes="C:,F:", expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)
rc = sup.run()

print(f"PROBE_RUN_RC={rc}", flush=True)
print(f"PROBE_GUEST_HANDLE={sup.guest_sampler!r}", flush=True)
print(f"PROBE_GUEST_CLOSE_STATE={sup._guest_close_state!r}", flush=True)
t = guest_thread_ref.get("t")
print(f"PROBE_GUEST_THREAD_ALIVE_AFTER_RUN={t.is_alive() if t else None}",
      flush=True)
gp = sup.guest_path
b1 = gp.stat().st_size if os.path.exists(gp) else -1
print(f"PROBE_GUEST_BYTES_HELD={b1}", flush=True)
print(f"PROBE_TELEMETRY_CAPPED={sup.telemetry_capped!r}", flush=True)
print(f"PROBE_BUDGET_INCIDENTS={[getattr(e, 'kind', repr(e)) for e in sup.incidents][:4]}",
      flush=True)
print(f"PROBE_STOP_REASONS={list(sup.stop_requested_reasons)[:4]!r}",
      flush=True)
rr_p = os.path.join(base, "run", "run_record.json")
if os.path.isfile(rr_p):
    d = json.loads(open(rr_p, encoding="utf-8").read())
    w = d.get("writers") or {}
    g = w.get("guest")
    tg = [r for r in d.get("required", [])
          if r.get("role") == "telemetry_guest"]
    print(f"PROBE_RR_WRITERS_GUEST={g!r}", flush=True)
    print(f"PROBE_RR_TG_ENTRY={tg[0] if tg else None}", flush=True)
    print(f"PROBE_RR_EVIDENCE={d.get('evidence_complete')!r}", flush=True)
    print(f"PROBE_RR_FINALIZED={d.get('finalized')!r}", flush=True)

# ---- 释放屏障前:实际 build/verify 是否接受该活写者包 ----
# (此时 guest 线程仍挂住、telemetry_guest 仍在可写状态)
# root=run_supervision 根(run_record 内 path 的相对基准,显式传入
# 避免 build 默认 root=run_record.parent.parent 差一层)
SUP_ROOT = os.path.dirname(base) if os.path.basename(base).startswith(
    "run_") else base
man = os.path.join(base, "fc2_manifest.jsonl")
anchor = os.path.join(base, "fc2_anchor.json")
vrun = subprocess.run(
    [sys.executable, os.path.join(RUNNER, "r17_verify_delivery.py"),
     "build", "--run-record", rr_p, "--manifest-out", man,
     "--anchor-out", anchor, "--root", SUP_ROOT],
    capture_output=True, text=True, timeout=120)
print(f"PROBE_BUILD_RC={vrun.returncode}", flush=True)
if vrun.returncode != 0:
    print("PROBE_BUILD_ERR=" + vrun.stderr.strip()[:300], flush=True)
else:
    vrun2 = subprocess.run(
        [sys.executable, os.path.join(RUNNER, "r17_verify_delivery.py"),
         "verify", "--root", SUP_ROOT,
         "--manifest", man, "--anchor-file", anchor,
         "--run-record", rr_p],
        capture_output=True, text=True, timeout=120)
    print(f"PROBE_VERIFY_RC_HELD={vrun2.returncode}", flush=True)
    print("PROBE_VERIFY_STDOUT=" + vrun2.stdout.strip()[:300], flush=True)

# ---- 释放屏障:写者退出,文件继续增长(证明流未冻结) ----
hold.set()
if t:
    t.join(timeout=10.0)
b2 = gp.stat().st_size if os.path.exists(gp) else -1
print(f"PROBE_GUEST_THREAD_ALIVE_AFTER_RELEASE={t.is_alive() if t else None}",
      flush=True)
print(f"PROBE_GUEST_BYTES_FINAL={b2}", flush=True)
print(f"PROBE_BYTES_GREW={b2 > b1}", flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
