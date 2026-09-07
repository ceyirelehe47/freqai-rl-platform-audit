#!/usr/bin/env bash
set -uo pipefail
S=/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17/state
echo "== execution journal (full, cut 300) =="
cut -c1-300 "$S"/r17_execution_journal.jsonl
echo "== pid 402 =="
ps -o pid,ppid,etime,stat,cmd -p 402 2>/dev/null || echo "(402 gone)"
echo "== any win sampler under /init =="
pgrep -af "r17_win_sampler" 2>/dev/null || echo "(none)"
