#!/usr/bin/env bash
set -uo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
python3 - <<'PY'
import os, sys, time, json, subprocess, argparse
sys.path.insert(0, "stage2_6_1_runner")
sys.path.insert(0, "tests/route_c_stage2_6_1")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "r17_supervision", "stage2_6_1_runner/r17_supervision.py")
rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)

import tempfile
tmp = tempfile.mkdtemp()
r_fd, w_fd = os.pipe()
os.set_blocking(w_fd, False)
filler = b"x" * 4096; filled = 0
while True:
    try: filled += os.write(w_fd, filler)
    except BlockingIOError: break
print("pipe filled:", filled)
os.set_blocking(w_fd, True)
args = argparse.Namespace(
    run_dir=os.path.join(tmp, "run"), task_kind="fixture",
    argv=["bash", "-c", 'trap "" TERM; sleep 60'], task_cwd=None,
    max_seconds=0, samples_source="", win_sampler_ps1="/x.ps1",
    win_volumes="C:,F:", expect_artifact=[], obs_ready_deadline=30.0)
sup = rs.Supervisor(args)
sup.policy["coop_exit_window_s"] = 1.0
old = sys.stdout
sys.stdout = os.fdopen(w_fd, "w", buffering=1)
try:
    sup.spawn_business()
    print("spawned, protector:", sup.protector is not None,
          "pgid:", sup.protector.pgid, file=sys.stderr)
    t0 = time.monotonic()
    sup.stdout_line("R17ALERT", {"event": "t06"})
    print("submit dt:", round(time.monotonic()-t0, 3), file=sys.stderr)
    sup.handle_triggers([{"kind": "win_free_phys",
                          "severity": "CRITICAL",
                          "detail": "t06", "metrics": {}}])
    print("term_sent_at:", sup.protector.term_sent_at,
          "requested:", sup.protector.requested_at,
          "biz alive:", sup.biz_proc.poll() is None, file=sys.stderr)
    t0 = time.monotonic(); deadline = t0 + 8
    while time.monotonic() < deadline:
        st = sup.protector.poll(time.monotonic())
        if sup.protector.kill_sent_at is not None:
            break
        time.sleep(0.2)
    print("kill_sent_at:", sup.protector.kill_sent_at,
          "after", round(time.monotonic()-t0, 1), "s",
          "members:", sup.protector._member_pids(),
          "io stats:", sup.iow.stats(), file=sys.stderr)
finally:
    sys.stdout = old
    try: os.close(w_fd)
    except OSError: pass
    try:
        os.set_blocking(r_fd, False)
        while True:
            if not os.read(r_fd, 65536): break
    except BlockingIOError: pass
    finally: os.close(r_fd)
    if sup.biz_proc and sup.biz_proc.poll() is None:
        os.killpg(os.getpgid(sup.biz_proc.pid), 9)
        sup.biz_proc.wait(timeout=10)
PY
