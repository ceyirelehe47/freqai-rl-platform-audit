#!/bin/bash
set -u
export R17_PROJECT_ROOT=/home/cryptorl/projects/crypto_rl
cd /home/cryptorl/projects/crypto_rl || exit 96
bash stage2_6_1_runner/qprod_sync.sh >/dev/null 2>&1
OUT=/home/cryptorl/regress_cue_identity_v1
mkdir -p "$OUT"
exec bash "$R17_PROJECT_ROOT/stage2_6_1_runner/r17_monitored_entry.sh" engineering \
  --max-seconds 7200 -- \
  python stage2_6_1_runner/r21_full_collection_regression.py \
  --repo /mnt/f/trading/freqai-rl-audit \
  --commit-a 33407fd4278731e14f988944d1086de729ee7a9b \
  --deploy-root /home/cryptorl/projects/crypto_rl \
  --out-dir "$OUT" \
  > "$OUT/r21_launch.stdout.log" 2> "$OUT/r21_launch.stderr.log"
