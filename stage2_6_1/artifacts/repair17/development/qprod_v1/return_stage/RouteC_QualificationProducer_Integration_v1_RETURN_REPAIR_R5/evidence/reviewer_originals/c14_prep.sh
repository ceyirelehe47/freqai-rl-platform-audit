#!/usr/bin/env bash
set -u
SRC=/home/cryptorl/projects/crypto_rl/src
DST=/mnt/f/trading/tmp_r5/reviewer/c14_snap/stage2_6_1/src
for item in "$SRC"/*; do
  b=$(basename "$item")
  if [ ! -e "$DST/$b" ]; then
    cp -r "$item" "$DST/$b"
    echo "copied: $b"
  fi
done
n=0
for f in "$SRC"/rl_curriculum/*.py; do
  b=$(basename "$f")
  if [ ! -f "$DST/rl_curriculum/$b" ]; then
    cp "$f" "$DST/rl_curriculum/$b"
    n=$((n+1))
  fi
done
echo "copied_missing_rl_curriculum_modules=$n"
cd /mnt/f/trading/tmp_r5/reviewer/c14_snap/stage2_6_1
PYTHONDONTWRITEBYTECODE=1 /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python REPRO_Q123_ROUND5_PRE_FIX.py
echo "c14_repro_rc=$?"
