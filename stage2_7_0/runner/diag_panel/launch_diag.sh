#!/bin/bash
# launch_diag.sh — diag panel 专用薄 launcher(复用已验语义)
# 正式: PY snapshot/diag_panel.py NEW_OUT --config snapshot/CONFIG_diag.json
# 外包 timeout -k 1 60 与 time -v;PILOT_REPO_SRC=快照 repo 根。
set -u
ROOT=${1:?attempt_root}
LABEL=${2:?label}
MODE=${3:?mode}
shift 3
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_SRC_DEFAULT=/mnt/f/trading/freqai-rl-audit/stage2_7_0/src
DIR="$ROOT/${LABEL}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
if [ -e "$DIR" ]; then echo "ATTEMPT_DIR_EXISTS $DIR" >&2; exit 96; fi
mkdir "$DIR" 2>/dev/null || { echo "MKDIR_FAIL" >&2; exit 97; }
exec > "$DIR/launcher_stdout.log" 2> "$DIR/launcher_stderr.log"
echo "$$" > "$DIR/pid.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_start.txt"
fail() { echo "LAUNCH_FAIL: $1" >&2; printf '%s\n' "$1" > "$DIR/FAIL_REASON.txt"; exit 94; }
trap 'rc=$?; echo "$rc" > "$DIR/rc.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_end.txt"' EXIT
printf 'mode=%s args=%s\n' "$MODE" "$*" > "$DIR/argv.txt"
sha256sum "$0" > "$DIR/launcher_self.sha256" || fail "launcher hash"
SNAP="$DIR/snapshot"; mkdir "$SNAP" || fail "snapshot mkdir"
for f in launch_diag.sh inner_diag.sh diag_panel.py test_diag_panel.py CONFIG_diag.json; do
  cp "$HERE/$f" "$SNAP/$f" || fail "copy $f"
done
REPO=${PILOT_REPO_SRC:-$REPO_SRC_DEFAULT}
[ -d "$REPO/rl_posctl" ] || fail "repo src missing $REPO"
mkdir -p "$SNAP/repo/rl_posctl/skill_p0" || fail "repo dirs"
for f in __init__.py ledger.py env.py policy.py versions.py curriculum.py; do
  cp "$REPO/rl_posctl/$f" "$SNAP/repo/rl_posctl/$f" || fail "copy rl_posctl/$f"
done
for f in __init__.py p0policy.py p0spec.py unified_course.py; do
  cp "$REPO/rl_posctl/skill_p0/$f" "$SNAP/repo/rl_posctl/skill_p0/$f" || fail "copy skill_p0/$f"
done
( cd "$SNAP" && sha256sum launch_diag.sh inner_diag.sh diag_panel.py test_diag_panel.py CONFIG_diag.json repo/rl_posctl/*.py repo/rl_posctl/skill_p0/*.py ) > "$SNAP/sha256.manifest" || fail "manifest"
case "$MODE" in
  official)
    [ $# -eq 2 ] || fail "official needs PY NEW_OUT"
    PY=$1; OUT=$2
    [ -e "$OUT" ] && fail "NEW_OUT_EXISTS $OUT"
    { sha256sum /mnt/f/trading/unified_teaching_pilot_a1_20261016_output/initial.zip /mnt/f/trading/unified_teaching_pilot_a1_20261016_output/final.zip /mnt/f/trading/teaching_pilot_prep_20261016/run_spec.json; } > "$DIR/pre_input_hashes.txt" || fail "pre hashes"
    S1=("$PY" -m pytest "$SNAP/test_diag_panel.py" -p no:cacheprovider -q)
    S2=(/usr/bin/timeout -k 1 60 /usr/bin/time -v "$PY" "$SNAP/diag_panel.py" "$OUT" --config "$SNAP/CONFIG_diag.json")
    ;;
  stages)
    S1=(); S2=(); saw=0
    for a in "$@"; do
      if [ "$saw" = 0 ]; then
        [ "$a" = "--" ] && { saw=1; continue; }
        S1+=("$a")
      else S2+=("$a"); fi
    done
    ;;
  *) fail "unknown mode $MODE";;
esac
if [ "$MODE" = official ]; then
  export PILOT_REPO_SRC="$SNAP/repo"
fi
bash "$SNAP/inner_diag.sh" "$DIR" "${S1[@]}" -- "${S2[@]}"
irc=$?
meta_rc=0
if [ "$MODE" = official ] && [ -d "$OUT" ]; then
  if ! find "$OUT" -type f -exec sha256sum {} + > "$DIR/post_output_hashes.txt" 2> "$DIR/post_output_hashes.err"; then
    meta_rc=1
  fi
fi
echo "$meta_rc" > "$DIR/metadata_rc.txt"
[ "$irc" -ne 0 ] && exit "$irc"
[ "$meta_rc" -ne 0 ] && exit 93
exit 0
