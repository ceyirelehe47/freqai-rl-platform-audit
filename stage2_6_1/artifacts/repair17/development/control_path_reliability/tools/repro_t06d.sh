#!/usr/bin/env bash
set -uo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
python3 - <<'PY'
import os, sys, time, argparse
sys.path.insert(0, "stage2_6_1_runner")
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
os.set_blocking(w_fd, True)
e = sys.stderr
print("filled:", filled, file=e)
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
    pg = sup.spawn_business()
    print("pgid:", pg, "leader:", sup.biz_proc.pid,
          "start_ticks:", sup.protector.leader_start, file=e)
    sup.stdout_line("R17ALERT", {"event": "t06"})
    sup.handle_triggers([{"kind": "win_free_phys",
                          "severity": "CRITICAL", "detail": "t06",
                          "metrics": {}}])
    print("term:", sup.protector.term_sent_at,
          "identity_mismatch:", sup.protector.identity_mismatch,
          "biz_alive:", sup.biz_proc.poll() is None, file=e)
    for i in range(10):
        m = sup.protector._member_pids()
        st = sup.protector.poll(time.monotonic())
        print(f"round {i}: members={m} poll_ret={st} "
              f"kill={sup.protector.kill_sent_at} "
              f"terminal={sup.protector.terminal_at} "
              f"pending_logs={len(sup.protector.pending_logs)}",
              file=e)
        if sup.protector.kill_sent_at is not None:
            break
        time.sleep(0.4)
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
