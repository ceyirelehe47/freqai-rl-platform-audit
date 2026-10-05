#!/bin/bash
set -u
for D in /home/cryptorl/projects/crypto_rl_qaf_v2 /home/cryptorl/projects/crypto_rl_formal_a_qaf_v2; do
  echo "############ $D  (dir mtime: $(stat -c %y $D 2>/dev/null | cut -d. -f1))"
  for f in src/rl_curriculum/curriculum261_qaf_provenance_guard.py \
           tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_reviewclosure.py \
           tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_preissue_guard.py \
           stage2_6_1_runner/qaf_v2_operator_entry.py; do
    if [ -f "$D/$f" ]; then
      printf '  %s  %s\n' "$(sha256sum "$D/$f" | cut -d' ' -f1)" "$f"
    else
      echo "  MISSING  $f"
    fi
  done
  echo "  tests count: $(ls "$D/tests/route_c_stage2_6_1/" 2>/dev/null | wc -l)  src count: $(ls "$D/src/rl_curriculum/" 2>/dev/null | wc -l)"
done
echo "=== processes ==="
ps -eo pid,etime,cmd | grep -iE "r21_full|pytest|qprod|qaf|rsync|cp " | grep -v grep | head -15
