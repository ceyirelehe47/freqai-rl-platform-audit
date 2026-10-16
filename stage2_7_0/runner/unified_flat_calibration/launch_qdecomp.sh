#!/bin/bash
# launch_qdecomp.sh — q_error_decomposition 专用薄 wrapper
# (独立最小适配;**不改已验发布件** launch_official/inner_official)。
# 复用已验模式:独占 attempt 目录最先→exec 捕获+EXIT trap→
# snapshot(本 wrapper+inner+新脚本+测试 完整副本+SHA+argv)→
# 启动保存的 inner 快照;stage1 仅手写测试、stage2 仅新脚本一次
# (timeout -k 1 10 + time -v);10wall/5CPU/128MiB;-k1 仅清理宽限。
set -u
ROOT=${1:?attempt_root}
LABEL=${2:?label}
shift 2
HERE=$(cd "$(dirname "$0")" && pwd)
DIR="$ROOT/${LABEL}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
if [ -e "$DIR" ]; then echo "ATTEMPT_DIR_EXISTS $DIR" >&2; exit 96; fi
mkdir "$DIR" 2>/dev/null || { echo "MKDIR_FAIL (no on-disk evidence possible)" >&2; exit 97; }
exec > "$DIR/launcher_stdout.log" 2> "$DIR/launcher_stderr.log"
echo "$$" > "$DIR/pid.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_start.txt"
fail() { echo "LAUNCH_FAIL: $1" >&2; printf '%s\n' "$1" > "$DIR/FAIL_REASON.txt"; exit 94; }
trap 'rc=$?; echo "$rc" > "$DIR/rc.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_end.txt"' EXIT
printf 'args=%s\n' "$*" > "$DIR/argv.txt"
sha256sum "$0" > "$DIR/launcher_self.sha256" || fail "launcher hash"
SNAP="$DIR/snapshot"; mkdir "$SNAP" || fail "snapshot mkdir"
for f in launch_qdecomp.sh inner_qdecomp.sh q_error_decomposition.py test_q_error_decomposition.py; do
  cp "$HERE/$f" "$SNAP/$f" || fail "copy $f"
done
( cd "$SNAP" && sha256sum launch_qdecomp.sh inner_qdecomp.sh q_error_decomposition.py test_q_error_decomposition.py ) > "$SNAP/sha256.manifest" || fail "manifest"
MODE=${1:?mode}
shift 1
case "$MODE" in
  official)
    [ $# -eq 3 ] || fail "official needs PY EVIDENCE_DIR NEW_OUT"
    PY=$1; EVID=$2; OUT=$3
    [ -e "$OUT" ] && fail "NEW_OUT_EXISTS $OUT"
    S1=("$PY" -m pytest "$SNAP/test_q_error_decomposition.py" -p no:cacheprovider -q)
    S2=(/usr/bin/timeout -k 1 10 /usr/bin/time -v "$PY" "$SNAP/q_error_decomposition.py" "$EVID" "$OUT")
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
bash "$SNAP/inner_qdecomp.sh" "$DIR" "${S1[@]}" -- "${S2[@]}"
exit $?
