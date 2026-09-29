#!/usr/bin/env bash
set -u
cd /home/cryptorl/projects/crypto_rl
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python /mnt/f/trading/tmp_reviewer_tb_v1/reviewer_probe.py 2>&1 | tail -30
