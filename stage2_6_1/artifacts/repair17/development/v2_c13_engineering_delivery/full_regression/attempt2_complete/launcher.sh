#!/usr/bin/env bash
# One regular R17-first full regression including the new v2c13 tests.
set -euo pipefail
[ "$#" -eq 1 ] || { echo 'usage: run_full_regression.sh <new-log-directory>' >&2; exit 2; }
LOG="$1"
[ -d "$(dirname "$LOG")" ] || { echo 'log parent must already exist' >&2; exit 2; }
mkdir "$LOG"
LOG=$(cd "$LOG" && pwd)
finish() { local rc=$?; printf '%s\n' "$rc" > "$LOG/outer.rc.txt"; }
trap finish EXIT
source "$HOME/projects/crypto_rl/activate-freqtrade.sh"
cd "$HOME/projects/crypto_rl"
R=tests/route_c_stage2_6_1
mapfile -t R17_FIRST < <(find "$R" -maxdepth 1 -name 'test_curriculum261_r17_*.py' -type f | LC_ALL=C sort)
mapfile -t REST < <(find "$R" -maxdepth 1 -name 'test_*.py' ! -name 'test_curriculum261_r17_*.py' -type f | LC_ALL=C sort)
printf '%s\n' "${R17_FIRST[@]}" "${REST[@]}" > "$LOG/test_files.txt"
grep -Fxq "$R/test_curriculum261_r17_c3_reserve_batch.py" "$LOG/test_files.txt" || { echo 'reserve tests missing' >&2; exit 2; }
grep -Fxq "$R/test_curriculum261_r17_c3_calibration_bridge.py" "$LOG/test_files.txt" || { echo 'bridge tests missing' >&2; exit 2; }
grep -Fxq "$R/test_curriculum261_r17_v2_c13_pipeline.py" "$LOG/test_files.txt" || { echo 'v2c13 tests missing' >&2; exit 2; }
REPO=/mnt/f/trading/freqai-rl-audit
SUPERV="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision"
RID="v2c13full_$(date -u +%Y%m%dT%H%M%S)_$$"
RD="$SUPERV/runs/$RID"
printf '%s\n' "$RD" > "$LOG/run_path.txt"
cp "${BASH_SOURCE[0]}" "$LOG/launcher.sh"
export R17_RUN_DIR="$RD"
set +e
bash stage2_6_1_runner/r17_monitored_entry.sh pytest --max-seconds 5400 -- \
  python -m pytest "${R17_FIRST[@]}" "${REST[@]}" -q --junitxml="$RD/junit.xml" \
  > "$LOG/entry.stdout.log" 2> "$LOG/entry.stderr.log"
RC=$?
printf '%s\n' "$RC" > "$LOG/entry.rc.txt"
unset R17_RUN_DIR
set -e
printf 'RUN_DIR=%s ENTRY_RC=%s N_FILES=%s\n' "$RD" "$RC" "$(wc -l < "$LOG/test_files.txt")"
exit "$RC"
