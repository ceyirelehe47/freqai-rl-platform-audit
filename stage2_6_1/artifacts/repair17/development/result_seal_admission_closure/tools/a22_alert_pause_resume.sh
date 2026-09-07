#!/usr/bin/env bash
# A22:真实 Agent 告警接收(WARNING→CRITICAL 升级+停读后恢复回放)
# 模式 B:supervisor stdout 经后台任务输出被 Agent(工具)真实读取;
# Agent 侧停读窗口由调用方控制(不读本脚本管)。本脚本只负责跑
# supervisor 并落盘一切;结束时打印 SUPERVISOR_RC。
set -u
SYNC="$HOME/projects/crypto_rl"
RUNNER_F="/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"
ART="/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/result_seal_admission_closure"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$ART/t22_alert_pause/run_${STAMP}"
mkdir -p "$RUN_DIR"
cd "$SYNC"
source activate-freqtrade.sh >/dev/null 2>&1 || true

python3 - "$RUN_DIR" << 'PYEOF'
import json, sys
from pathlib import Path
import datetime as dt

def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")

def vols(free_f):
    return [{"vol": "F:", "present": True, "free_gb": free_f,
             "size_gb": 1907.3, "serial": "3E141660",
             "identity_match": True},
            {"vol": "C:", "present": True, "free_gb": 104.6,
             "size_gb": 475.8, "serial": "B800FCAC",
             "identity_match": True}]

def win(vol_free, seq):
    return {"event": "sample", "utc": utc(), "seq": seq,
            "run_id": "run",
            "perf": {"phys_avail_gb": 38.0, "phys_total_gb": 63.0,
                     "commit_total_gb": 39.0, "commit_limit_gb": 83.0},
            "vols": vols(vol_free), "telemetry_out_writable": True}

def guest():
    return {"event": "guest_sample", "utc": utc(),
            "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
            "psi_memory": {"full_avg10": 0.0},
            "vmstat_swap": {"pswpout": 0}}

lines = []
seq = 0
def add(vol_free):
    global seq
    seq += 1
    lines.append(json.dumps({"win": win(vol_free, seq),
                             "guest": guest()}))

for _ in range(60):      # 正常段(等待 Agent 进入停读窗)
    add(100.0)
add(10.0)                # keyvol WARNING(20>free>=5)
for _ in range(8):
    add(100.0)
add(3.0)                 # keyvol CRITICAL(free<5)→升级+停止
for _ in range(40):      # 尾部(业务已被 TERM;样本不再影响)
    add(100.0)
p = Path(sys.argv[1]) / "s.jsonl"
p.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("SAMPLES_WRITTEN", len(lines))
PYEOF

python3 "$RUNNER_F/r17_supervision.py" \
  --run-dir "$RUN_DIR/run" --task-kind engineering --max-seconds 120 \
  --samples-source "file:$RUN_DIR/s.jsonl" \
  -- bash -c 'sleep 45'
rc=$?
echo "SUPERVISOR_RC=$rc"
echo "RUN_DIR=$RUN_DIR"
python3 - "$RUN_DIR" << 'PYEOF'
import json, sys
from pathlib import Path
d = Path(sys.argv[1])
s = json.loads((d / "run/summary.json").read_text())
print("BIZ_RC:", s["business"]["rc"], "SIG:", s["business"]["signal"])
print("IO:", json.dumps({k: v for k, v in (s.get("io") or {}).items()
                         if k != "failures"}))
print("STOP_REASONS:", s.get("stop_requested_reasons"))
PYEOF
echo "A22_SCRIPT_DONE"
