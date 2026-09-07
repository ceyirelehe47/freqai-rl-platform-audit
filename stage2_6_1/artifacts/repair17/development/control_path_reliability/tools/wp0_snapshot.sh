#!/usr/bin/env bash
# WP0 只读快照:正式根现状+存活任务。不写任何部署面文件。
set -uo pipefail
echo "== boot/date =="
date -u +%Y-%m-%dT%H:%M:%SZ
cat /proc/sys/kernel/random/boot_id
echo "== state root listing =="
S=/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17/state
ls -la "$S" 2>&1 | tail -30
echo "== journal tail (read-only) =="
tail -5 "$S"/r17_journal.jsonl 2>/dev/null | cut -c1-400
echo "== aborted marker =="
ls -la "$S"/*aborted* 2>/dev/null || echo "(no aborted marker)"
echo "== requests dir =="
R=/home/cryptorl/projects/crypto_rl/r17_formal_requests
ls -la "$R" 2>&1 | tail -15
echo "== admission/consumed =="
ls -la "$S"/.r17_formal_admission.json "$S"/r17_admission_consumed.jsonl 2>&1
echo "== live r17 processes =="
pgrep -af "r17_supervision|r17_formal|r17_win_sampler|r17_guest" 2>/dev/null || echo "(none)"
echo "== disk =="
df -h /home/cryptorl /mnt/f 2>/dev/null | tail -3
echo "== mem =="
free -g | head -2
