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
args = argparse.Namespace(
    run_dir=os.path.join(tmp, "run"), task_kind="fixture",
    argv=["bash", "-c", 'trap "" TERM; sleep 60'], task_cwd=None,
    max_seconds=0, samples_source="", win_sampler_ps1="/x.ps1",
    win_volumes="C:,F:", expect_artifact=[], obs_ready_deadline=30.0)
sup = rs.Supervisor(args)
sup.policy["coop_exit_window_s"] = 1.0
pg = sup.spawn_business()
e = sys.stderr
print("pgid:", pg, "leader:", sup.biz_proc.pid, file=e)
time.sleep(0.3)
print("before stop members:", sup.protector._member_pids(), file=e)
sup.protector.request_stop("diag")
print("term_sent_at:", sup.protector.term_sent_at,
      "mono():", sup.protector.mono(), file=e)
print("after TERM members:", sup.protector._member_pids(), file=e)
for i in range(6):
    time.sleep(0.5)
    alive = sup.protector._alive()
    print(f"poll {i}: members={sup.protector._member_pids()} "
          f"alive={alive} kill={sup.protector.kill_sent_at} "
          f"term={sup.protector.term_sent_at}", file=e)
    sup.protector.poll(time.monotonic())
if sup.biz_proc.poll() is None:
    os.killpg(os.getpgid(sup.biz_proc.pid), 9)
    sup.biz_proc.wait(timeout=10)
PY
