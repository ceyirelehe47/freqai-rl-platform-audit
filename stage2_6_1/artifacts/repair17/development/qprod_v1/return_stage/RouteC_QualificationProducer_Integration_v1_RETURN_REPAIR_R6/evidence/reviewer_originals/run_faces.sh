#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
echo "=== probe digest ==="
"$PY" /mnt/f/trading/tmp_r6/reviewer/probe_digest_fix.py 2>&1
echo "=== R6 pinned ==="
"$PY" -m pytest "$T/test_curriculum261_qprod_r6_fixes.py" -q --no-header 2>&1 | tail -3
echo "=== qprod face ==="
"$PY" -m pytest $T/test_curriculum261_qprod_*.py -q --no-header 2>&1 | tail -3
echo "=== r8/r9/r10/r17 cue-contract face ==="
"$PY" -m pytest "$T/test_curriculum261_r10_cue_contract.py" "$T/test_curriculum261_r9_cue_contract.py" -q --no-header 2>&1 | tail -3
ls "$T" | grep -E "r17.*cue|cue.*r17" || true
