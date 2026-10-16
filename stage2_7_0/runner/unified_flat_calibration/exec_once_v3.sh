#!/bin/bash
set -u
OUT=/mnt/f/trading/unified_flat_calib_official_attempt2_20261016
RUNNER=$OUT/run_official_v3.py
sha256sum "$RUNNER" > "$OUT/runner_preexec_sha.txt"
cd /mnt/f/trading/freqai-rl-audit/stage2_7_0
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/utc_start.txt"
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python "$RUNNER" "$OUT" > "$OUT/official_stdout.log" 2> "$OUT/official_stderr.log"
rc=$?
echo "$rc" > "$OUT/python_rc.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$OUT/utc_end.txt"
exit "$rc"
