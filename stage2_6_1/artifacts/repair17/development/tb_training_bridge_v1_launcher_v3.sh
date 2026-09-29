#!/bin/bash
set -u
export R17_PROJECT_ROOT=$HOME/projects/crypto_rl
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1
OUT=$BASE/full_regression_v3
rc=0
bash $HOME/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh engineering --max-seconds 3600 -- \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r21_full_collection_regression.py \
  --repo /mnt/f/trading/freqai-rl-audit \
  --commit-a 611966b28bc0d2baeff396e8f42e91ddb1729e4e \
  --deploy-root /home/cryptorl/projects/crypto_rl \
  --out-dir "$OUT" || rc=$?
printf "%s\n" "$rc" > "$BASE/full_regression_v3.launcher_rc.txt"

cd $HOME/projects/crypto_rl
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1
mkdir -p "$BASE/regression_262_v3"
rc2=0
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest \
  tests/route_c_stage2_6_2 -q \
  --junitxml="$BASE/regression_262_v3/junit.xml" \
  > "$BASE/regression_262_v3/stdout.txt" 2> "$BASE/regression_262_v3/stderr.txt" || rc2=$?
printf "%s\n" "$rc2" > "$BASE/regression_262_v3/rc.txt"
printf '261_rc=%s 262_rc=%s\n' "$rc" "$rc2" > "$BASE/ALL_RC_V3.txt"
exit 0
