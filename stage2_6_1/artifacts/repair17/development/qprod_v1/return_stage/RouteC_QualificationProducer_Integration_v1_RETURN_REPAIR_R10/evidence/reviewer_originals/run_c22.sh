#!/bin/bash
set -u
cd ~/projects/crypto_rl || exit 9
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
"$PY" -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_r10_fixes.py -q 2>&1 | tail -2
"$PY" -m pytest tests/route_c_stage2_6_1 -q -k "qprod" 2>&1 | tail -2
