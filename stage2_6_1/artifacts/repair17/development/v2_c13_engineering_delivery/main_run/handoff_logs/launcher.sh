#!/usr/bin/env bash
# One NEW monitored engineering main experiment for
# R17V2C13EngineeringCalibration-v1. Real generation, real V2 fits,
# real scaled evaluation; one shot only.
set -euo pipefail
[ "$#" -eq 1 ] || { echo 'usage: run_v2c13_main.sh <new-log-directory>' >&2; exit 2; }
LOG="$1"
[ -d "$(dirname "$LOG")" ] || { echo 'log parent must already exist' >&2; exit 2; }
mkdir "$LOG"
LOG=$(cd "$LOG" && pwd)
finish() { local rc=$?; printf '%s\n' "$rc" > "$LOG/outer.rc.txt"; }
trap finish EXIT
source "$HOME/projects/crypto_rl/activate-freqtrade.sh"
REPO=/mnt/f/trading/freqai-rl-audit
RUNNER="$HOME/projects/crypto_rl/stage2_6_1_runner"
SUPERV="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision"
[ -d "$SUPERV/runs" ] || { echo 'existing supervision root unavailable' >&2; exit 2; }
RID="v2c13eng_$(date -u +%Y%m%dT%H%M%S)_$$"
RD="$SUPERV/runs/$RID"
printf '%s\n' "$RD" > "$LOG/run_path.txt"
cp "${BASH_SOURCE[0]}" "$LOG/launcher.sh"
export R17_RUN_DIR="$RD"
set +e
bash "$RUNNER/r17_monitored_entry.sh" engineering --max-seconds 21600 -- \
  python "$RUNNER/r17_v2_c13_pipeline.py" run --out "$RD/v2_c13_engineering" \
  > "$LOG/entry.stdout.log" 2> "$LOG/entry.stderr.log"
ENTRY=$?
printf '%s\n' "$ENTRY" > "$LOG/entry.rc.txt"
unset R17_RUN_DIR
set -e
printf 'RUN_DIR=%s ENTRY_RC=%s\n' "$RD" "$ENTRY"
[ "$ENTRY" -eq 0 ]
