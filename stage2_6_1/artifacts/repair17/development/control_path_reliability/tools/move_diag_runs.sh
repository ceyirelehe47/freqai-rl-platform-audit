#!/usr/bin/env bash
set -uo pipefail
SRC=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs
DST=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/control_path_reliability/diagnostics
mkdir -p "$DST"
for d in repro_m12 repro_t06; do
  for p in "$SRC"/${d}_*; do
    [ -d "$p" ] && mv "$p" "$DST/" || true
  done
done
ls "$DST" 2>/dev/null | head -8
