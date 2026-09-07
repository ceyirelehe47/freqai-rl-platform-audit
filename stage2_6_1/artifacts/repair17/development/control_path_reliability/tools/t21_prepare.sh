#!/usr/bin/env bash
# T21 场景A准备:样本(WARNING→冷却期内CRITICAL)+运行目录
set -euo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/control_path_reliability
RUNA=$BASE/t21_alert_reception/run_a_$1
mkdir -p "$RUNA"
python3 - "$RUNA/samples.jsonl" <<'PY'
import json, sys
out = open(sys.argv[1], "w")
perf = {"phys_avail_gb": 39.0, "phys_total_gb": 63.0,
        "commit_total_gb": 38.0, "commit_limit_gb": 83.0}
guest = {"event": "guest_sample", "utc": "2026-09-07T02:00:00Z",
         "meminfo": {"MemTotal": 40000000, "MemAvailable": 39000000}}
def win(free):
    return {"event": "sample", "perf": perf, "vols": [
        {"vol": "F:", "present": True, "free_gb": free}]}
n = 0
for free, cnt in ((100.0, 2), (10.0, 3), (3.0, 3), (100.0, 20)):
    for _ in range(cnt):
        n += 1
        out.write(json.dumps({"win": win(free),
                              "guest": dict(guest, utc=f"2026-09-07T02:{n//60:02d}:{n%60:02d}Z")}) + "\n")
out.close()
print("samples:", n)
PY
echo "$RUNA"
