#!/bin/bash
set -u
export R17_PROJECT_ROOT=$HOME/projects/crypto_rl
OUT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/r25_final_closure_20260928T160624/full_regression_v1
rc=0
bash $HOME/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh engineering --max-seconds 3600 -- \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r21_full_collection_regression.py \
  --repo /mnt/f/trading/freqai-rl-audit \
  --commit-a 7e9e5470889884bad296a2dbb4b3e55ca38bc151 \
  --deploy-root /home/cryptorl/projects/crypto_rl \
  --out-dir "$OUT" || rc=$?
printf "%s\n" "$rc" > "$OUT.launcher_rc.txt"
exit "$rc"
