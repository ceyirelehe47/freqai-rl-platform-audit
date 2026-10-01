#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
"$PY" -m pytest "$T/test_curriculum261_r17_execgov.py::TestExecutorIdentity::test_t09_owner_death_rejects_new_requests" "$T/test_curriculum261_r17_execgov.py::TestExecutorIdentity" -q --no-header 2>&1 | tail -2
"$PY" -m pytest "$T/test_curriculum261_r17_execgov.py" -q --no-header 2>&1 | tail -2
