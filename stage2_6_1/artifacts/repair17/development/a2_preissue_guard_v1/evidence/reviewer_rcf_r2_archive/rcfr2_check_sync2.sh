#!/bin/bash
set -u
for D in /home/cryptorl/projects/crypto_rl_qaf_v2 /home/cryptorl/projects/crypto_rl_formal_a_qaf_v2; do
  echo "############ $D"
  for f in src/rl_curriculum/curriculum261_qaf_provenance_guard.py \
           tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_reviewclosure.py; do
    if [ -f "$D/$f" ]; then
      printf '%s  %s  (%s)\n' "$(sha256sum "$D/$f" | cut -d' ' -f1)" "$f" "$(stat -c %y "$D/$f" | cut -d. -f1)"
    else
      echo "MISSING  $f"
    fi
  done
done
