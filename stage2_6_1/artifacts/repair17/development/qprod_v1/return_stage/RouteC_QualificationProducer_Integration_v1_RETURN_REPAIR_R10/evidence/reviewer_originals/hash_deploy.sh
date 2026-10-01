#!/bin/bash
cd ~/projects/crypto_rl || exit 9
for f in stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r10_fixes.py stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round10_notclosed/REPRO_R10_PRE_FIX.py stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round10_notclosed/EVIDENCE_INDEX.md stage2_6_1/runner/qprod_r10_r21_regress.sh; do sha256sum "$f"; done
