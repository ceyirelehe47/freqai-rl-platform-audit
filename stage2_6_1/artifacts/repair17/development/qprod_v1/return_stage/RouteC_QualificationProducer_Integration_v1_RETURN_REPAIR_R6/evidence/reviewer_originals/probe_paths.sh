#!/usr/bin/env bash
DEPLOY=/home/cryptorl/projects/crypto_rl
echo "--- root ---"; ls "$DEPLOY" 2>&1 | head
echo "--- find cue_contract ---"
find "$DEPLOY" -name "curriculum261_r17_cue_contract.py" -not -path "*/node_modules/*" 2>/dev/null
echo "--- find r6 test ---"
find "$DEPLOY" -name "test_curriculum261_qprod_r6_fixes.py" 2>/dev/null
echo "--- artifacts round6 ---"
ls "$DEPLOY/stage2_6_1/artifacts/repair17/development/qprod_v1/" 2>&1 | head
