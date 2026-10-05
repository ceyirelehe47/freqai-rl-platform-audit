#!/bin/bash
# RCF R2 review: deploy tree state check (read-only)
set -u
D=/home/cryptorl/projects/crypto_rl
echo "=== deploy tree hashes ==="
for f in src/rl_curriculum/curriculum261_qaf_provenance_guard.py \
         src/rl_curriculum/curriculum261_r17_cli.py \
         stage2_6_1_runner/qaf_v2_operator_entry.py \
         tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_reviewclosure.py \
         tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_preissue_guard.py \
         tests/route_c_stage2_6_1/r17_admission_substance_test_support.py; do
  if [ -f "$D/$f" ]; then
    printf '%s  %s\n' "$(sha256sum "$D/$f" | cut -d' ' -f1)" "$f"
  else
    echo "MISSING  $f"
  fi
done
echo "=== python ==="
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -V
echo "=== deploy src crime-scene markers ==="
ls -la "$D/.r17_formal_admission.json" "$D/r17_admission_issued.jsonl" 2>/dev/null
echo "=== recent test artifacts? ==="
ls -dt "$D"/tests/route_c_stage2_6_1/__pycache__ 2>/dev/null
ls "$D" | grep -i "rcf\|review\|tmp" | head
