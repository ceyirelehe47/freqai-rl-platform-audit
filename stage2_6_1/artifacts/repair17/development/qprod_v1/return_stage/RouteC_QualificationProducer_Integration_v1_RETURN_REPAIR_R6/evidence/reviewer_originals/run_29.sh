#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
"$PY" -m pytest "$T/test_curriculum261_r9_cue_contract.py" "$T/test_curriculum261_r10_cue_contract.py" -q --no-header 2>&1 | tail -2
