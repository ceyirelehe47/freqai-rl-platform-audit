#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src
DEPLOY=/home/cryptorl/projects/crypto_rl
WORK=/mnt/f/trading/tmp_r6/reviewer
cd "$DEPLOY"
echo "=== C16(deploy bytes) probe ==="
"$PY" "$WORK/probe_r6_indep.py" 2>&1
echo "=== C15(pre-fix) probe ==="
rm -rf /tmp/r6_c15_src && cp -r "$DEPLOY/src" /tmp/r6_c15_src
cp "$WORK/cue_contract_C15.py" /tmp/r6_c15_src/rl_curriculum/curriculum261_r17_cue_contract.py
cd /tmp/r6_c15_src/.. 
PYTHONPATH=/tmp/r6_c15_src "$PY" "$WORK/probe_r6_indep.py" 2>&1
