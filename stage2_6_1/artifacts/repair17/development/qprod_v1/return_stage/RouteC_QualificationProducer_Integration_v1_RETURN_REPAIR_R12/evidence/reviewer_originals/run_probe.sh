#!/usr/bin/env bash
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
DEPLOY=/home/cryptorl/projects/crypto_rl
export PYTHONPATH="$DEPLOY/src"
cd /mnt/f/trading/tmp_r12/reviewer
echo "interpreter: $($PY -c 'import sys;print(sys.version)')"
echo "PYTHONPATH=$PYTHONPATH"
$PY probe_r12_reviewer.py
echo "rc=$?"
