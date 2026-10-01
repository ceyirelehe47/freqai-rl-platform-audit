#!/usr/bin/env bash
set -u
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
export PYTHONDONTWRITEBYTECODE=1
P=/mnt/f/trading/tmp_r6/reviewer
REPO=/mnt/f/trading/freqai-rl-audit
PROBE="$REPO/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round6_notclosed/REPRO_R6_PRE_FIX.py"
echo "=== committed probe on C16 (deploy tree) ==="
cd /home/cryptorl/projects/crypto_rl
PYTHONPATH=src "$PY" "$PROBE" 2>&1 | grep -E "^(c[0-9]|ctl|---)"
echo "=== committed probe on C15 (extracted) ==="
rm -rf /tmp/r6_c15b && cp -r /home/cryptorl/projects/crypto_rl/src /tmp/r6_c15b
cp "$P/cue_contract_C15.py" /tmp/r6_c15b/rl_curriculum/curriculum261_r17_cue_contract.py
cd /tmp && PYTHONPATH=/tmp/r6_c15b "$PY" "$PROBE" 2>&1 | grep -E "^(c[0-9]|ctl|---)"
