#!/usr/bin/env bash
# 回归进度检查(只读)
set -uo pipefail
D=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/supervision_closure/full_regression/runs/final_20260906T183450
echo "=== 遥测行数:"
wc -l "$D"/telemetry/guest_samples.jsonl "$D"/telemetry/win_samples.jsonl "$D"/alerts/alerts.jsonl 2>&1
echo "=== 业务 stdout 尾部:"
tail -c 400 "$D"/business/stdout.log 2>/dev/null | tail -3
echo "=== alerts 尾部事件:"
tail -3 "$D"/alerts/alerts.jsonl 2>/dev/null | cut -c1-180
echo "=== junit 是否已生成:"
ls -la "$D"/junit.xml 2>/dev/null || echo "尚未生成(运行中)"
