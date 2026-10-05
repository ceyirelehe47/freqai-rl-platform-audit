#!/bin/bash
set -u
for D in /home/cryptorl/projects/crypto_rl_qaf_v2 /home/cryptorl/projects/crypto_rl_formal_a_qaf_v2; do
  echo "############ $D  (dir mtime: $(stat -c %y $D | cut -d. -f1))"
  echo "-- top level:"; ls -la "$D" | head -12
  echo "-- tests dir:"; ls "$D/tests/route_c_stage2_6_1/" 2>/dev/null | head -5; echo "  count: $(ls "$D/tests/route_c_stage2_6_1/" 2>/dev/null | wc -l)"
  echo "-- src dir count: $(ls "$D/src/rl_curriculum/" 2>/dev/null | wc -l)"
  echo "-- stage2_6_1_runner count: $(ls "$D/stage2_6_1_runner/" 2>/dev/null | wc -l)"
done
echo "=== running deploy-ish processes (one-shot check, not polling) ==="
ps -eo pid,etime,cmd | grep -E "rsync|tar |cp -|r21_full_collection|qprod|python" | grep -v grep | head -20
