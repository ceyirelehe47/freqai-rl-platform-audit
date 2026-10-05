#!/bin/bash
set -u
for D in /home/cryptorl/projects/crypto_rl_qaf_v2 /home/cryptorl/projects/crypto_rl_formal_a_qaf_v2; do
  echo "############ $D"
  stat -c '%y %n' "$D" 2>/dev/null
  for f in src/rl_curriculum/curriculum261_qaf_provenance_guard.py \
           src/rl_curriculum/curriculum261_r17_cli.py \
           stage2_6_1_runner/qaf_v2_operator_entry.py \
           tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_reviewclosure.py \
           tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_preissue_guard.py; do
    if [ -f "$D/$f" ]; then
      printf '%s  %s  (%s)\n' "$(sha256sum "$D/$f" | cut -d' ' -f1)" "$f" "$(stat -c %y "$D/$f" | cut -d. -f1)"
    else
      echo "MISSING  $f"
    fi
  done
  echo "-- one-shot markers in tree root:"
  ls -la "$D/.r17_formal_admission.json" "$D/r17_admission_issued.jsonl" 2>/dev/null | sed "s|$D|.|"
  echo "-- recent dirs:"
  ls -dt "$D"/*/ 2>/dev/null | head -6
  echo
done
