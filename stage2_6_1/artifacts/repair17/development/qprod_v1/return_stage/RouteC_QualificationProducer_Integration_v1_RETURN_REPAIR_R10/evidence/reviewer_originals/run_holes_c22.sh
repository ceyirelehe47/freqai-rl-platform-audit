#!/bin/bash
set -u
cd ~/projects/crypto_rl || exit 9
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python /mnt/f/trading/tmp_r10/reviewer/probe_holes_fixture_lf.py /mnt/f/trading/tmp_r10/reviewer/probe_out c22 || exit 8
