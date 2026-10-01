#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
cd /home/cryptorl/projects/crypto_rl
T=tests/route_c_stage2_6_1
for f in test_curriculum261_r9_cue_contract test_curriculum261_r9_cue_eval test_curriculum261_r10_cue_contract test_curriculum261_r10_cue_eval test_curriculum261_r12_global_k; do
  n=$("$PY" -m pytest --collect-only -q "$T/$f.py" 2>/dev/null | grep -c "::")
  echo "$f: $n"
done
