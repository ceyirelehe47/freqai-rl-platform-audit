#!/usr/bin/env bash
set -u
DEPLOY=/home/cryptorl/projects/crypto_rl
REPO=/mnt/f/trading/freqai-rl-audit
for f in \
  stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py \
  stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r6_fixes.py \
  stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r4_fixes.py \
  stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round6_notclosed/REPRO_R6_PRE_FIX.py ; do
  a=$(sha256sum "$REPO/$f" 2>/dev/null | cut -d' ' -f1)
  b=$(sha256sum "$DEPLOY/$f" 2>/dev/null | cut -d' ' -f1)
  if [ "$a" = "$b" ] && [ -n "$a" ]; then st=SYNC-OK; else st=MISMATCH; fi
  echo "$st $f"
  echo "  repo  : $a"
  echo "  deploy: $b"
done
