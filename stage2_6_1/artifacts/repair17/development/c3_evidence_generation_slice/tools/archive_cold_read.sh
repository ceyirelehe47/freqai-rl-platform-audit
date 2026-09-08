#!/usr/bin/env bash
# 归档冷读回执与全量运行材料到交付目录。
set -uo pipefail
DELIV=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_evidence_generation_slice
mkdir -p "$DELIV/cold_read" "$DELIV/full_run"
cp -r /home/cryptorl/r17c3eg_cold/cold_read_20260908T171557Z "$DELIV/cold_read/isolated_20260908T171557Z"
cp /home/cryptorl/r17c3eg_cold/pipeline_stdout.log "$DELIV/cold_read/"
# 第一次尝试(/mnt 下副本被隔离遮蔽)的过程事实保留
mkdir -p "$DELIV/cold_read/first_attempt_20260908T171531Z"
cp /mnt/f/trading/r17c3eg_dev/cold_read_20260908T171531Z/*.log "$DELIV/cold_read/first_attempt_20260908T171531Z/" 2>/dev/null || true
cp -r /mnt/f/trading/r17c3eg_dev/cold_read_20260908T171531Z "$DELIV/cold_read/first_attempt_20260908T171531Z/work" 2>/dev/null || true
cp /mnt/f/trading/r17c3eg_dev/full_run/entry_stdout.log /mnt/f/trading/r17c3eg_dev/full_run/outer_rc.txt "$DELIV/full_run/"
echo "== cold_read =="; ls "$DELIV/cold_read/"
echo "== full_run =="; ls "$DELIV/full_run/"
echo "== 复核 ls(防 cp 静默失败) =="
find "$DELIV/cold_read" -name 'summary_receipt*' -o -name '*.json' | head -8
