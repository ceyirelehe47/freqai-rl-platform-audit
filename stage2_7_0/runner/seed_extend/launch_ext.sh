#!/bin/bash
# launch_ext.sh — seed extend 专用薄 launcher(复用已验语义;900s)
# 快照=本任务源码/测试/spec+已验 repo 依赖(结构保持);
# 正式命令: PY snapshot/seed_extend.py NEW_OUT --spec snapshot/RUNSPEC_EXT.json --mode official
# 外包 timeout -k 1 900 与 time -v;PILOT_REPO_SRC=快照 repo 根(导入与 SHA 同根)。
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
# 本任务件
for f in launch_ext.sh inner_ext.sh seed_extend.py test_seed_extend.py RUNSPEC_EXT.json; do
  cp "$HERE/$f" "$SNAP/$f" || fail "copy $f"
done
# 本任务依赖:pilot 五件 + diag_panel.py(结构镜像)
PILOT_SRC=${SEED_CONTRAST_PILOT:-/mnt/f/trading/teaching_pilot_prep_20261016}
DIAG_SRC=${SEED_CONTRAST_DIAG:-/mnt/f/trading/diag_panel_prep_20261016}
mkdir -p "$SNAP/pilot" "$SNAP/diag" || fail "dep dirs"
for f in runner.py teach_env.py policy.py eval_pilot.py run_spec.json; do
  cp "$PILOT_SRC/$f" "$SNAP/pilot/$f" || fail "copy pilot/$f"
done
cp "$DIAG_SRC/diag_panel.py" "$SNAP/diag/diag_panel.py" || fail "copy diag/diag_panel.py"
SC_SRC=${SEED_CONTRAST_DIR:-/mnt/f/trading/seed_contrast_prep_20261016}
mkdir -p "$SNAP/sc" || fail "sc dirs"
cp "$SC_SRC/seed_contrast.py" "$SNAP/sc/seed_contrast.py" || fail "copy sc/seed_contrast.py"
echo "803c9a64b683b7fe87a9c10827ee651716e1dc6e924860b41c9b07acb42a7271  $SNAP/sc/seed_contrast.py" | sha256sum -c - || fail "SC frozen SHA"
echo "5ebd5fa6a39b6d9a56e0d0500c27a60d3e82530e04f7eda4d8b1edf6da1ddfd2  $SNAP/diag/diag_panel.py" | sha256sum -c - || fail "diag copy SHA"
echo "d21e8d991347f372de07d293520313e86e68d33155348ca5c25354036d72a92b  $SNAP/RUNSPEC_EXT.json" | sha256sum -c - || fail "RUNSPEC SHA"
# repo 依赖(结构保持;导入与 SHA 同一根)
REPO=${PILOT_REPO_SRC:-$REPO_SRC_DEFAULT}
[ -d "$REPO/rl_posctl" ] || fail "repo src missing $REPO"
mkdir -p "$SNAP/repo/rl_posctl/skill_p0" || fail "repo dirs"
for f in __init__.py ledger.py env.py policy.py versions.py curriculum.py; do
  cp "$REPO/rl_posctl/$f" "$SNAP/repo/rl_posctl/$f" || fail "copy rl_posctl/$f"
done
for f in __init__.py p0policy.py p0spec.py unified_course.py; do
  cp "$REPO/rl_posctl/skill_p0/$f" "$SNAP/repo/rl_posctl/skill_p0/$f" || fail "copy skill_p0/$f"
done
( cd "$SNAP" && sha256sum launch_ext.sh inner_ext.sh seed_extend.py test_seed_extend.py RUNSPEC_EXT.json sc/seed_contrast.py pilot/*.py pilot/run_spec.json diag/diag_panel.py repo/rl_posctl/*.py repo/rl_posctl/skill_p0/*.py ) > "$SNAP/sha256.manifest" || fail "manifest"
case "$MODE" in
  official)
    [ $# -eq 2 ] || fail "official needs PY NEW_OUT"
    PY=$1; OUT=$2
    [ -e "$OUT" ] && fail "NEW_OUT_EXISTS $OUT"
    S1=("$PY" -m pytest "$SNAP/test_seed_extend.py" -p no:cacheprovider -q)
    S2=(/usr/bin/timeout -k 1 900 /usr/bin/time -v "$PY" "$SNAP/seed_extend.py" "$OUT" --spec "$SNAP/RUNSPEC_EXT.json" --mode official)
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
  export SEED_CONTRAST_PILOT="$SNAP/pilot"
  export SEED_CONTRAST_DIAG="$SNAP/diag"
  export SEED_CONTRAST_DIR="$SNAP/sc"
fi
bash "$SNAP/inner_ext.sh" "$DIR" "${S1[@]}" -- "${S2[@]}"
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
