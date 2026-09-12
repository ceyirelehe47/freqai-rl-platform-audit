#!/usr/bin/env bash
# Verification only. No experiment/preclaim/claim/generation CLI is invoked.
set -euo pipefail
CANDIDATE=${1:?usage: run_bound_regression.sh CANDIDATE_SHA FRESH_WORK_DIR}
OUT=${2:?fresh external work directory required}
REPO=/mnt/f/trading/freqai-rl-audit
DEPLOY=/home/cryptorl/projects/crypto_rl
RUNNER=$DEPLOY/stage2_6_1_runner
source "$DEPLOY/activate-freqtrade.sh"
cd "$DEPLOY"
[[ $CANDIDATE =~ ^[a-f0-9]{40}$ ]] || { echo 'Invalid candidate' >&2; exit 2; }
[[ $(git -C "$REPO" rev-parse HEAD) == "$CANDIDATE" ]] || { echo 'Candidate HEAD drift' >&2; exit 2; }
[[ -z $(git -C "$REPO" status --porcelain=v1 -- stage2_6_1/runner stage2_6_1/src stage2_6_1/tests .gitattributes) ]] || { echo 'Candidate worktree dirty' >&2; exit 2; }
OUT=$(realpath -m "$OUT")
[[ $OUT != "$REPO" && $OUT != "$REPO"/* ]] || { echo 'Use work output outside release repo' >&2; exit 2; }
[[ ! -e $OUT ]] || { echo 'Work output exists; not overwriting' >&2; exit 2; }
mkdir -p "$OUT"
printf '%s\n' "$CANDIDATE" > "$OUT/candidate.txt"
export PYTHONPATH="$RUNNER:$DEPLOY/src${PYTHONPATH:+:$PYTHONPATH}"
python - <<'PY' > "$OUT/source_before.json"
import json, sys
import r17_v2_c13_pipeline as pipe
print(json.dumps({'python':sys.version,'executable':sys.executable,'sources':pipe.source_guard()},indent=2))
PY
mapfile -t R17 < <(find tests/route_c_stage2_6_1 -maxdepth 1 -name 'test_*r17*.py' -type f | LC_ALL=C sort)
mapfile -t OTHER < <(find tests/route_c_stage2_6_1 -maxdepth 1 -name 'test_*.py' ! -name 'test_*r17*.py' -type f | LC_ALL=C sort)
(( ${#R17[@]} > 0 && ${#OTHER[@]} > 0 )) || { echo 'Full test set missing' >&2; exit 2; }
python - "${R17[@]}" "${OTHER[@]}" <<'PY' > "$OUT/test_files.sha256"
import hashlib,pathlib,sys
for name in sorted(sys.argv[1:]):
    print(hashlib.sha256(pathlib.Path(name).read_bytes()).hexdigest()+'  '+name)
PY
python -m pytest --collect-only -q "${R17[@]}" "${OTHER[@]}" > "$OUT/collected_tests.txt" 2> "$OUT/collect.stderr.log"
RUN="$OUT/monitored_run"
printf '%q ' bash "$RUNNER/r17_monitored_entry.sh" pytest --max-seconds 7200 -- python -m pytest -q "${R17[@]}" "${OTHER[@]}" "--junitxml=$RUN/junit.xml" > "$OUT/entry_command.txt"
printf '\n' >> "$OUT/entry_command.txt"
set +e
R17_RUN_DIR="$RUN" bash "$RUNNER/r17_monitored_entry.sh" pytest --max-seconds 7200 -- \
  python -m pytest -q "${R17[@]}" "${OTHER[@]}" "--junitxml=$RUN/junit.xml" \
  > "$OUT/entry.stdout.log" 2> "$OUT/entry.stderr.log"
RC=$?
set -e
printf '%s\n' "$RC" > "$OUT/entry.rc"
[[ $RC -eq 0 ]] || { echo "Full regression failed rc=$RC; preserve all evidence" >&2; exit "$RC"; }
python - <<'PY' > "$OUT/source_after.json"
import json,sys
import r17_v2_c13_pipeline as pipe
print(json.dumps({'python':sys.version,'executable':sys.executable,'sources':pipe.source_guard()},indent=2))
PY
cmp "$OUT/source_before.json" "$OUT/source_after.json"
python - <<'PY' > "$OUT/skips_allowlist.json"
import json
from r17_v2_c13_admission_guard import HISTORICAL_SKIP_IDS
print(json.dumps({'allowed_skips':sorted(HISTORICAL_SKIP_IDS),'policy':'source-owned v3 historical policy; not inferred from this run'},indent=2))
PY
CRITICAL=$(python - <<'PY'
from r17_v2_c13_admission_guard import CRITICAL_TEST_FILES
print(','.join(CRITICAL_TEST_FILES))
PY
)
python "$RUNNER/r17_v2_c13_regression_evidence.py" collect \
  --run-dir "$RUN" --out "$OUT/healthy_package" \
  --entry-stdout "$OUT/entry.stdout.log" --entry-stderr "$OUT/entry.stderr.log" --entry-rc "$OUT/entry.rc" \
  --candidate-commit "$CANDIDATE" --release-repo "$REPO" --deploy-root "$DEPLOY" \
  --collected "$OUT/collected_tests.txt" --test-files "$OUT/test_files.sha256" \
  --skips-allowlist "$OUT/skips_allowlist.json" --critical-tests "$CRITICAL" \
  > "$OUT/collect_package.json" 2> "$OUT/collect_package.stderr.log"
set +e
python "$RUNNER/r17_v2_c13_regression_evidence.py" verify --package "$OUT/healthy_package" \
  > "$OUT/verify_C.json" 2> "$OUT/verify_C.stderr.log"
VRC=$?
set -e
printf '%s\n' "$VRC" > "$OUT/verify_C.rc"
exit "$VRC"
