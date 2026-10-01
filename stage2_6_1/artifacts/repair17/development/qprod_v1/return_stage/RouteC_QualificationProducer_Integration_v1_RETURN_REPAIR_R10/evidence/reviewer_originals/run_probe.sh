#!/bin/bash
set -u
cd ~/projects/crypto_rl || exit 9
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m py_compile /mnt/f/trading/tmp_r10/reviewer/probe_r10_indep.py || exit 8
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python /mnt/f/trading/tmp_r10/reviewer/probe_r10_indep.py /mnt/f/trading/tmp_r10/reviewer/probe_out 2>&1
echo "PROBE_RC=$?"
