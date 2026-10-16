#!/bin/bash
# launch_rootref.sh — root_reference 专用薄 launcher(v2)
# v2(3747 缺口1):official 快照**复制 LOCKED_MANIFEST**(MAN 实际
# 副本,入 manifest),stage1/2 均用快照副本;运行目录含已验
# helper root_integrals.py(运行依赖齐全)。
set -u
ROOT=${1:?attempt_root}
LABEL=${2:?label}
MODE=${3:?mode}
shift 3
HERE=$(cd "$(dirname "$0")" && pwd)
DIR="$ROOT/${LABEL}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
if [ -e "$DIR" ]; then echo "ATTEMPT_DIR_EXISTS $DIR" >&2; exit 96; fi
mkdir "$DIR" 2>/dev/null || { echo "MKDIR_FAIL (no on-disk evidence possible)" >&2; exit 97; }
exec > "$DIR/launcher_stdout.log" 2> "$DIR/launcher_stderr.log"
echo "$$" > "$DIR/pid.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_start.txt"
fail() { echo "LAUNCH_FAIL: $1" >&2; printf '%s\n' "$1" > "$DIR/FAIL_REASON.txt"; exit 94; }
trap 'rc=$?; echo "$rc" > "$DIR/rc.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_end.txt"' EXIT
printf 'mode=%s args=%s\n' "$MODE" "$*" > "$DIR/argv.txt"
sha256sum "$0" > "$DIR/launcher_self.sha256" || fail "launcher hash"
SNAP="$DIR/snapshot"; mkdir "$SNAP" || fail "snapshot mkdir"
for f in launch_rootref.sh inner_rootref.sh root_reference.py root_integrals.py test_root_reference.py CONFIG_rootref.json; do
  cp "$HERE/$f" "$SNAP/$f" || fail "copy $f"
done
case "$MODE" in
  official)
    [ $# -eq 4 ] || fail "official needs PY EVID MANIFEST NEW_OUT"
    PY=$1; EVID=$2; MAN=$3; OUT=$4
    [ -e "$OUT" ] && fail "NEW_OUT_EXISTS $OUT"
    [ -f "$MAN" ] || fail "MANIFEST_MISSING $MAN"
    cp "$MAN" "$SNAP/LOCKED_MANIFEST.json" || fail "copy manifest"
    ( cd "$SNAP" && sha256sum launch_rootref.sh inner_rootref.sh root_reference.py root_integrals.py test_root_reference.py CONFIG_rootref.json LOCKED_MANIFEST.json ) > "$SNAP/sha256.manifest" || fail "manifest"
    S1=("$PY" -m pytest "$SNAP/test_root_reference.py" -p no:cacheprovider -q)
    S2=(/usr/bin/timeout -k 1 10 /usr/bin/time -v "$PY" "$SNAP/root_reference.py" "$EVID" "$SNAP/LOCKED_MANIFEST.json" "$OUT")
    ;;
  stages)
    ( cd "$SNAP" && sha256sum launch_rootref.sh inner_rootref.sh root_reference.py root_integrals.py test_root_reference.py CONFIG_rootref.json ) > "$SNAP/sha256.manifest" || fail "manifest"
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
bash "$SNAP/inner_rootref.sh" "$DIR" "${S1[@]}" -- "${S2[@]}"
exit $?
