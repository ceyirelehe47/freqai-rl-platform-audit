#!/bin/bash
set -u
cd ~/projects/crypto_rl || exit 9
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest tests/route_c_stage2_6_1 -q -k "qprod" 2>&1 | tail -3
echo "QPROD_RC=$?"
