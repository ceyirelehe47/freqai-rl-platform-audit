#!/bin/bash
set -u
cd ~/projects/crypto_rl || exit 9
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
"$PY" -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_r10_fixes.py tests/route_c_stage2_6_1/test_curriculum261_qprod_r8_fixes.py tests/route_c_stage2_6_1/test_curriculum261_qprod_r9_fixes.py -q 2>&1 | tail -4
echo "rc1=$?"
ls tests/route_c_stage2_6_1/ | grep -E "r8_cue|r9_cue|r10_cue|r17" | head
