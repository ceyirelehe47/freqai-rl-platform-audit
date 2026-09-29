#!/usr/bin/env bash
set -u
cd /home/cryptorl/projects/crypto_rl
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest \
  tests/route_c_stage2_6_2/test_ppo262e_qualified_input.py \
  tests/route_c_stage2_6_2/test_ppo262e_env_bank.py -q --no-header 2>&1 | tail -5
