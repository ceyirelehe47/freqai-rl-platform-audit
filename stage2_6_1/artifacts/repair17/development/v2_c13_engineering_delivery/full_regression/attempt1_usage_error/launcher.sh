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
REPO=/mnt/f/trading/freqai-rl-audit
RUNNER="$HOME/projects/crypto_rl/stage2_6_1_runner"
SUPERV="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision"
TESTS="$HOME/projects/crypto_rl/tests/route_c_stage2_6_1"
RID="v2c13full_$(date -u +%Y%m%dT%H%M%S)_$$"
RD="$SUPERV/runs/$RID"
printf '%s\n' "$RD" > "$LOG/run_path.txt"
cp "${BASH_SOURCE[0]}" "$LOG/launcher.sh"
mapfile -t R17_FIRST < <(cd "$TESTS" && LC_ALL=C find . -maxdepth 1 -name 'test_curriculum261_r17_*.py' | LC_ALL=C sort)
mapfile -t REST < <(cd "$TESTS" && LC_ALL=C find . -maxdepth 1 -name 'test_*.py' ! -name 'test_curriculum261_r17_*.py' | LC_ALL=C sort)
mapfile -t ALL_TESTS < <(printf '%s\n' "${R17_FIRST[@]}" "${REST[@]}" | sed 's|^\./||')
grep -Fxq 'test_curriculum261_r17_c3_reserve_batch.py' <(printf '%s\n' "${ALL_TESTS[@]}") || { echo 'reserve tests missing' >&2; exit 2; }
grep -Fxq 'test_curriculum261_r17_c3_calibration_bridge.py' <(printf '%s\n' "${ALL_TESTS[@]}") || { echo 'bridge tests missing' >&2; exit 2; }
grep -Fxq 'test_curriculum261_r17_v2_c13_pipeline.py' <(printf '%s\n' "${ALL_TESTS[@]}") || { echo 'v2c13 tests missing' >&2; exit 2; }
printf '%s\n' "${ALL_TESTS[@]}" > "$LOG/test_files.txt"
export R17_RUN_DIR="$RD"
set +e
bash "$RUNNER/r17_monitored_entry.sh" pytest --max-seconds 5400 -- \
  python -m pytest "${ALL_TESTS[@]}" --junitxml="$RD/junit.xml" \
  > "$LOG/entry.stdout.log" 2> "$LOG/entry.stderr.log"
ENTRY=$?
printf '%s\n' "$ENTRY" > "$LOG/entry.rc.txt"
unset R17_RUN_DIR
set -e
printf 'RUN_DIR=%s ENTRY_RC=%s N_TESTS_FILES=%s\n' "$RD" "$ENTRY" "${#ALL_TESTS[@]}"
[ "$ENTRY" -eq 0 ]
