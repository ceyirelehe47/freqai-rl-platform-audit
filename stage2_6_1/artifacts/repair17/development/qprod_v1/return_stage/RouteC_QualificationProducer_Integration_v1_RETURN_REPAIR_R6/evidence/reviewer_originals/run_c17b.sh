#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
cd /home/cryptorl/projects/crypto_rl
echo "=== C17b probes ==="
"$PY" /mnt/f/trading/tmp_r6/reviewer/probe_c17b.py 2>&1
echo "=== qprod face ==="
"$PY" -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_*.py tests/route_c_stage2_6_2/test_ppo262_qprod_export.py -q --no-header 2>&1 | tail -2
