#!/bin/bash
# launch_fivepoint.sh — five_point 专用薄 launcher(复用已验捕获语义)
set -u
ROOT=${1:?attempt_root}
LABEL=${2:?label}
MODE=${3:?mode}
shift 3
HERE=$(cd "$(dirname "$0")" && pwd)
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
for f in launch_fivepoint.sh inner_fivepoint.sh five_point.py root_integrals.py test_five_point.py CONFIG_fivepoint.json LOCK_FIVEPOINT.json; do
  cp "$HERE/$f" "$SNAP/$f" || fail "copy $f"
done
case "$MODE" in
  official)
    [ $# -eq 4 ] || fail "official needs PY EVID LOCK NEW_OUT"
    PY=$1; EVID=$2; LK=$3; OUT=$4
    [ -e "$OUT" ] && fail "NEW_OUT_EXISTS $OUT"
    S1=("$PY" -m pytest "$SNAP/test_five_point.py" -p no:cacheprovider -q)
    S2=(/usr/bin/timeout -k 1 10 /usr/bin/time -v "$PY" "$SNAP/five_point.py" "$EVID" "$SNAP/LOCK_FIVEPOINT.json" "$OUT")
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
( cd "$SNAP" && sha256sum launch_fivepoint.sh inner_fivepoint.sh five_point.py root_integrals.py test_five_point.py CONFIG_fivepoint.json LOCK_FIVEPOINT.json ) > "$SNAP/sha256.manifest" || fail "manifest"
# 执行前哈希:绑定实际 snapshot/LOCK 原件并核 cmp 一致
# (防记录 A 运行 B)
if [ "$MODE" = official ]; then
  { sha256sum "$SNAP/LOCK_FIVEPOINT.json" "$EVID/tier_L2.json" "$EVID/V_L2.npy"; } > "$DIR/pre_input_hashes.txt" || fail "pre hashes"
  cmp -s "$LK" "$SNAP/LOCK_FIVEPOINT.json" || fail "lock snapshot drift"
fi
bash "$SNAP/inner_fivepoint.sh" "$DIR" "${S1[@]}" -- "${S2[@]}"
irc=$?
meta_rc=0
if [ "$MODE" = official ] && [ -d "$OUT" ]; then
  if ! find "$OUT" -type f -exec sha256sum {} + > "$DIR/post_output_hashes.txt" 2> "$DIR/post_output_hashes.err"; then
    meta_rc=1
  fi
fi
echo "$meta_rc" > "$DIR/metadata_rc.txt"
# inner 失败保首错;inner 成功而必要归档失败→最终非零
if [ "$irc" -ne 0 ]; then exit "$irc"; fi
if [ "$meta_rc" -ne 0 ]; then exit 93; fi
exit 0
