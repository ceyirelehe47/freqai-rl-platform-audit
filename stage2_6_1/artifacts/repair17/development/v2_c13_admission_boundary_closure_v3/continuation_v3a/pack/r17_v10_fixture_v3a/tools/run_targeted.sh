#!/usr/bin/env bash
# Verification only. No production experiment or claim writer is launched.
set -euo pipefail
PACK=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT=${1:?usage: run_targeted.sh FRESH_EXTERNAL_OUT}
REPO=/mnt/f/trading/freqai-rl-audit
DEPLOY=/home/cryptorl/projects/crypto_rl
RUNNER=$DEPLOY/stage2_6_1_runner
BASELINE=1ea193c0f1eb710e37aa23aa89f261617eb93c43
source "$DEPLOY/activate-freqtrade.sh"
cd "$DEPLOY"
[[ $(git -C "$REPO" rev-parse HEAD) == "$BASELINE" ]] || { echo 'wrong HEAD before candidate' >&2; exit 2; }
OUT=$(realpath -m "$OUT")
[[ $OUT != "$REPO" && $OUT != "$REPO"/* && ! -e $OUT && ! -L $OUT ]] || { echo 'fresh external directory required' >&2; exit 2; }
mkdir -p "$OUT"
export PYTHONPATH="$RUNNER:$DEPLOY/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY' > "$OUT/source_before.json"
import json, sys
import r17_v2_c13_pipeline as pipe
print(json.dumps({'python':sys.version,'executable':sys.executable,'sources':pipe.source_guard()},indent=2))
PY
FILES=(
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_admission_guard.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_claim_protocol.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_regression_evidence.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_reader_binding.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_synthetic_chain.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_source_provenance.py
 tests/route_c_stage2_6_1/test_curriculum261_r17_c2_launch_prep.py
)
python - "${FILES[@]}" <<'PY' > "$OUT/test_files.sha256"
import pathlib,sys,hashlib
for path in sys.argv[1:]:
    print(hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()+'  '+path)
PY
RUN=$OUT/monitored_run
printf '%q ' bash "$RUNNER/r17_monitored_entry.sh" pytest --max-seconds 3600 -- python -m pytest -q "${FILES[@]}" "--junitxml=$RUN/junit.xml" > "$OUT/command.txt"
printf '\n' >> "$OUT/command.txt"
set +e
R17_RUN_DIR="$RUN" bash "$RUNNER/r17_monitored_entry.sh" pytest --max-seconds 3600 -- \
 python -m pytest -q "${FILES[@]}" "--junitxml=$RUN/junit.xml" \
 > "$OUT/entry.stdout.log" 2> "$OUT/entry.stderr.log"
RC=$?
set -e
printf '%s\n' "$RC" > "$OUT/entry.rc"
if [[ -f "$RUN/junit.xml" ]]; then
 set +e
 python "$PACK/tools/check_targeted_junit.py" --runner "$RUNNER" --junit "$RUN/junit.xml" \
   > "$OUT/junit_check.json" 2> "$OUT/junit_check.stderr.log"
 JRC=$?
 set -e
 printf '%s\n' "$JRC" > "$OUT/junit_check.rc"
else
 JRC=2
 printf '2\n' > "$OUT/junit_check.rc"
 printf 'JUnit missing\n' > "$OUT/junit_check.stderr.log"
fi
python - <<'PY' > "$OUT/source_after.json"
import json, sys
import r17_v2_c13_pipeline as pipe
print(json.dumps({'python':sys.version,'executable':sys.executable,'sources':pipe.source_guard()},indent=2))
PY
cmp "$OUT/source_before.json" "$OUT/source_after.json"
[[ $RC -eq 0 ]] || exit "$RC"
[[ $JRC -eq 0 ]] || exit "$JRC"
