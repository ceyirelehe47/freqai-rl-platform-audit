#!/usr/bin/env bash
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src
cd /mnt/f/trading/tmp_r12/reviewer
$PY probe_r12_c25.py
echo "rc=$?"
