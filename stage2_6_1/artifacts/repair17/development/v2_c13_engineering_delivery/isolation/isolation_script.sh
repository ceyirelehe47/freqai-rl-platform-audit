#!/usr/bin/env bash
# Isolated cold-read verification of the FAILED v2c13 main run (v2).
set -uo pipefail
RD=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/v2c13eng_20260910T140213_115963
SRC=$RD/v2_c13_engineering
RUNNER=$HOME/projects/crypto_rl/stage2_6_1_runner
WORK=/tmp/v2c13_isolation_v2_$$
mkdir -p "$WORK/stage2_6_1_runner_isolated" "$WORK/src_isolated"
for f in r17_v2_c13_profile.py r17_v2_c13_batch.py r17_v2_c13_pipeline.py r17_v2_c13_source_lock.py; do
  cp "$RUNNER/$f" "$WORK/stage2_6_1_runner_isolated/"
done
cp -r "$HOME/projects/crypto_rl/src/rl_curriculum" "$WORK/src_isolated/" 2>/dev/null

PROBE_MNT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_v2_c13_pipeline.py
PROBE_PRJ=$HOME/projects/crypto_rl/stage2_6_1_runner/r17_v2_c13_pipeline.py
[ -f "$PROBE_MNT" ] && echo "probe_mnt_exists_before=true" || echo "probe_mnt_exists_before=false"
[ -f "$PROBE_PRJ" ] && echo "probe_prj_exists_before=true" || echo "probe_prj_exists_before=false"

# inner runner script (executed inside unshare via env vars)
cat > "$WORK/inner_verify.sh" <<'INNER'
set -u
for p in /mnt /home/cryptorl/projects; do
  if [ -d "$p" ]; then mount -t tmpfs none "$p" 2>/dev/null; fi
done
if [ -n "${CASE_SHADOW:-}" ]; then
  [ -e /mnt/f/trading ] && echo "SHADOW_FAIL_MNT" || echo "mnt_shadow_ok"
  [ -e /home/cryptorl/projects/crypto_rl ] && echo "SHADOW_FAIL_PRJ" || echo "projects_shadow_ok"
fi
cd "$WORK_DIR" || exit 99
PYTHONPATH="$WORK_DIR/src_isolated" python3 stage2_6_1_runner_isolated/r17_v2_c13_pipeline.py verify --root "$TARGET_ROOT"
INNER

run_iso() { # $1 name, $2 target, $3 shadow(0/1)
  local name=$1 target=$2 shadow=$3
  WORK_DIR="$WORK" TARGET_ROOT="$target" CASE_SHADOW=$([ "$shadow" = 1 ] && echo 1 || echo "") \
    unshare --user --map-root-user --mount --propagation private bash "$WORK/inner_verify.sh" \
    >"$WORK/$name.out" 2>"$WORK/$name.err"
  echo "${name}_rc=$?"
}

case1="$WORK/case1_healthy_fail"; cp -r "$SRC" "$case1"
echo "=== case1: healthy-fail copy (shadow check; expect nonzero) ==="
run_iso case1 "$case1" 1
grep -o 'mnt_unreadable_ok\|projects_unreadable_ok\|SHADOW_FAIL_MNT\|SHADOW_FAIL_PRJ' "$WORK/case1.out" | sort -u
tail -c 350 "$WORK/case1.out"; echo; tail -c 200 "$WORK/case1.err"

echo "=== case2: append tamper on request proof ==="
case2="$WORK/case2_append_tamper"; cp -r "$SRC" "$case2"
printf '\n' >> "$case2/stages/fit_main/requests/fit_main_c1_opportunity_D0_p0.json"
run_iso case2 "$case2" 0
tail -c 250 "$WORK/case2.out"; echo; tail -c 200 "$WORK/case2.err"

echo "=== case3: greenwash result.json ==="
case3="$WORK/case3_greenwash"; cp -r "$SRC" "$case3"
python3 - "$case3" <<'PYEOF'
import json, sys
p = sys.argv[1] + "/result.json"
r = json.load(open(p))
r["status"] = "complete"; r["rc"] = 0
r["engineering_path_complete"] = True; r["error"] = None
json.dump(r, open(p, "w"), sort_keys=True)
PYEOF
run_iso case3 "$case3" 0
tail -c 350 "$WORK/case3.out"; echo; tail -c 200 "$WORK/case3.err"

echo "=== original untouched ==="
sha256sum "$SRC/manifest.json" | cut -c1-16
python3 - "$SRC" <<'PYEOF'
import json, sys
r = json.load(open(sys.argv[1] + "/result.json"))
print("original_status", r["status"], "rc", r["rc"])
PYEOF
[ -f "$PROBE_MNT" ] && echo "probe_mnt_exists_after=true"
[ -f "$PROBE_PRJ" ] && echo "probe_prj_exists_after=true"
echo "WORK=$WORK"
echo ISOLATION_DONE
