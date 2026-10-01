#!/usr/bin/env bash
DEPLOY=/home/cryptorl/projects/crypto_rl
REPO=/mnt/f/trading/freqai-rl-audit
for dp in src/rl_curriculum/curriculum261_r17_cue_contract.py tests/route_c_stage2_6_1/test_curriculum261_qprod_r6_fixes.py tests/route_c_stage2_6_1/test_curriculum261_qprod_r4_fixes.py; do
  rp="stage2_6_1/$dp"
  a=$(sha256sum "$REPO/$rp" | cut -d' ' -f1); b=$(sha256sum "$DEPLOY/$dp" | cut -d' ' -f1)
  [ "$a" = "$b" ] && echo "SYNC-OK $dp" || echo "MISMATCH $dp repo=$a deploy=$b"
done
