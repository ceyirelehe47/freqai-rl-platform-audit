#!/usr/bin/env bash
# One NEW monitored statistical handoff. No generation, refit, or policy evaluation.
set -euo pipefail
[ "$#" -eq 1 ] || { echo 'usage: run_readonly_handoff.sh <new-log-directory>' >&2; exit 2; }
LOG="$1"
[ -d "$(dirname "$LOG")" ] || { echo 'log parent must already exist' >&2; exit 2; }
mkdir "$LOG" # Never reuse or truncate a prior attempt directory.
LOG=$(cd "$LOG" && pwd)
finish() { local rc=$?; printf '%s\n' "$rc" > "$LOG/outer.rc.txt"; }
trap finish EXIT
source "$HOME/projects/crypto_rl/activate-freqtrade.sh"
REPO=/mnt/f/trading/freqai-rl-audit
RUNNER="$HOME/projects/crypto_rl/stage2_6_1_runner"
SUPERV="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision"
SOURCE="$SUPERV/runs/c3reserve_v1_20260910T050655_93442/c3_finite_reserve"
RID="c3calbridge_$(date -u +%Y%m%dT%H%M%S)_$$"
RD="$SUPERV/runs/$RID"
[ -d "$SUPERV/runs" ] || { echo 'existing supervision root unavailable' >&2; exit 2; }
printf '%s\n' "$RD" > "$LOG/run_path.txt"
cp "${BASH_SOURCE[0]}" "$LOG/launcher.sh"
export R17_RUN_DIR="$RD"
set +e
bash "$RUNNER/r17_monitored_entry.sh" engineering --max-seconds 600 -- \
  python "$RUNNER/r17_c3_calibration_bridge.py" run --batch "$SOURCE" --out "$RD/c3_calibration_bridge" \
  > "$LOG/entry.stdout.log" 2> "$LOG/entry.stderr.log"
ENTRY=$?
printf '%s\n' "$ENTRY" > "$LOG/entry.rc.txt"
unset R17_RUN_DIR
python -B "$RUNNER/r17_c3_calibration_delivery.py" --root "$SUPERV" --record "$RD/run_record.json" \
  > "$LOG/delivery.json" 2> "$LOG/delivery.stderr.log"
DELIVERY=$?
printf '%s\n' "$DELIVERY" > "$LOG/delivery.rc.txt"
set -e
printf 'RUN_DIR=%s ENTRY_RC=%s DELIVERY_RC=%s\n' "$RD" "$ENTRY" "$DELIVERY"
[ "$ENTRY" -eq 0 ] && [ "$DELIVERY" -eq 0 ]
