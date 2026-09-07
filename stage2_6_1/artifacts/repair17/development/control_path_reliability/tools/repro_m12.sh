#!/usr/bin/env bash
set -uo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
RD=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/repro_m12_$RANDOM
mkdir -p "$RD"
S=$(mktemp /tmp/m12s.XXXX.jsonl)
python3 - <<PY
import json
s = {"win": {"event": "sample", "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0, "commit_limit_gb": 83.0, "phys_total_gb": 63.0}, "vols": []},
     "guest": {"event": "guest_sample", "utc": "2026-09-07T00:00:00Z",
               "meminfo": {"MemTotal": 40000000, "MemAvailable": 39000000},
               "psi_memory": {"full_avg10": 0.0}, "vmstat_swap": {"pswpout": 0}}}
open("$S", "w").write(json.dumps(s) + "\n")
PY
python3 stage2_6_1_runner/r17_supervision.py --run-dir "$RD" --task-kind fixture \
  --max-seconds 120 --samples-source "file:$S" -- bash -c "sleep 120" &
SUP=$!
sleep 5
echo "--- alerts after 5s ---"
cat "$RD/alerts/alerts.jsonl" 2>/dev/null | cut -c1-150
kill -TERM $SUP
wait $SUP; echo "supervisor rc=$?"
sleep 1
echo "--- alerts tail ---"
tail -6 "$RD/alerts/alerts.jsonl" 2>/dev/null | cut -c1-160
echo "--- summary business ---"
python3 -c "import json;s=json.load(open('$RD/summary.json'));print(s['business']);print('stops:',s['stop_requested_reasons'])"
rm -f "$S"
