#!/usr/bin/env bash
set -uo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
python3 - <<'PY'
import os, sys, time, json, argparse, tempfile
sys.path.insert(0, "stage2_6_1_runner")
import importlib.util
spec = importlib.util.spec_from_file_location(
    "r17_supervision", "stage2_6_1_runner/r17_supervision.py")
rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)
e = sys.stderr
tmp = tempfile.mkdtemp()
samples = os.path.join(tmp, "s.jsonl")
open(samples, "w").write(json.dumps({
    "win": {"event": "sample",
            "perf": {"phys_avail_gb": 39.0, "phys_total_gb": 63.0,
                     "commit_total_gb": 38.0, "commit_limit_gb": 83.0},
            "vols": []},
    "guest": {"event": "guest_sample", "utc": "2026-09-07T01:00:00Z",
              "meminfo": {"MemTotal": 40000000,
                          "MemAvailable": 39000000}}}) + "\n")
args = argparse.Namespace(
    run_dir=os.path.join(tmp, "run"), task_kind="fixture",
    argv=["bash", "-c", 'trap "" TERM; exec sleep 60'], task_cwd=None,
    max_seconds=0, samples_source=f"file:{samples}",
    win_sampler_ps1="/x.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = rs.Supervisor(args)
sup.policy["coop_exit_window_s"] = 0.5
sup.policy["default_max_seconds"] = 8
rc = sup.run()
print("rc:", rc, "biz_rc:", sup.biz_rc,
      "residual_unconf:", sup.residual_unconfirmed,
      "terminal_at:", sup.protector.terminal_at,
      "requested:", sup.protector.requested_at,
      "kill:", sup.protector.kill_sent_at, file=e)
rec = json.load(open(os.path.join(tmp, "run", "run_record.json")))
print("required:", [(r["role"], r["status"], r.get("live_writers"))
                    for r in rec["required"]], file=e)
if sup.biz_proc and sup.biz_proc.poll() is None:
    os.killpg(os.getpgid(sup.biz_proc.pid), 9)
    sup.biz_proc.wait(timeout=10)
PY
