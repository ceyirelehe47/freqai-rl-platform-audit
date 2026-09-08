#!/usr/bin/env bash
# 归档三监护运行的原始启动日志(含 c3diag 第二次目录碰撞拒绝 rc=96)。
set -uo pipefail
DELIV=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_evidence_generation_slice
mkdir -p "$DELIV/monitored_runs"
cp /tmp/c3_evidence_runs/runA.log /tmp/c3_evidence_runs/runB.log /tmp/c3_evidence_runs/runC.log "$DELIV/monitored_runs/"
ls -la "$DELIV/monitored_runs/"
echo "== runA 第二次碰撞拒绝证据 =="
tail -1 "$DELIV/monitored_runs/runA.log"
