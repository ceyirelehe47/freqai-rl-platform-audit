#!/usr/bin/env bash
DEPLOY=/home/cryptorl/projects/crypto_rl
REPO=/mnt/f/trading/freqai-rl-audit
pairs="
stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py|src/rl_curriculum/curriculum261_r17_cue_contract.py
stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r6_fixes.py|tests/route_c_stage2_6_1/test_curriculum261_qprod_r6_fixes.py
stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r4_fixes.py|tests/route_c_stage2_6_1/test_curriculum261_qprod_r4_fixes.py
stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r5_fixes.py|tests/route_c_stage2_6_1/test_curriculum261_qprod_r5_fixes.py
stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_levela.py|tests/route_c_stage2_6_1/test_curriculum261_qprod_levela.py
"
echo "$pairs" | while IFS='|' read -r rp dp; do
  [ -z "$rp" ] && continue
  a=$(sha256sum "$REPO/$rp" 2>/dev/null | cut -d' ' -f1)
  b=$(sha256sum "$DEPLOY/$dp" 2>/dev/null | cut -d' ' -f1)
  if [ -n "$a" ] && [ "$a" = "$b" ]; then st=SYNC-OK; else st=MISMATCH; fi
  echo "$st repo:$rp deploy:$dp"
done
