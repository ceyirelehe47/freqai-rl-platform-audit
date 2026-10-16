#!/bin/bash
# launch_official.sh — 唯一最外层入口(v2 终版)
# 保证顺序:
#  1) 独占 attempt 目录(失败→stderr+exit97:目录都无法创建,
#     如实无盘上证据可留);
#  2) **立即**安装整段 stdout/stderr 捕获 + EXIT 真实 rc/UTC
#     持久化(trap),此后一切检查/失败均在捕获内 fail-closed;
#  3) 再做参数/NEW_OUT/源码 copy+hash 快照(argv 固化);
#  4) 重定向启动保存的 inner 快照,同 rc 退出。
# rc 表:95 NEW_OUT 已存在/96 目录已存在/97 mkdir 失败/
#       94 参数或快照失败/99 未知模式。
set -u
ROOT=${1:?attempt_root}
LABEL=${2:?label}
MODE=${3:?mode}
shift 3
HERE=$(cd "$(dirname "$0")" && pwd)
DIR="$ROOT/${LABEL}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
if [ -e "$DIR" ]; then
  echo "ATTEMPT_DIR_EXISTS $DIR" >&2; exit 96
fi
mkdir "$DIR" 2>/dev/null || { echo "MKDIR_FAIL $DIR (no on-disk evidence possible)" >&2; exit 97; }
# —— 捕获从此刻起覆盖本进程一切输出/失败 ——
exec > "$DIR/launcher_stdout.log" 2> "$DIR/launcher_stderr.log"
echo "$$" > "$DIR/pid.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_start.txt"
fail() { echo "LAUNCH_FAIL: $1" >&2
         printf '%s\n' "$1" > "$DIR/FAIL_REASON.txt"
         exit 94; }
trap 'rc=$?; echo "$rc" > "$DIR/rc.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/utc_end.txt"' EXIT
printf 'mode=%s args=%s\n' "$MODE" "$*" > "$DIR/argv.txt"
sha256sum "$0" > "$DIR/launcher_self.sha256" || fail "launcher hash"
SNAP="$DIR/snapshot"; mkdir "$SNAP" || fail "snapshot mkdir"
for f in launch_official.sh inner_official.sh tau_sensitivity.py test_tau_official_v2.py; do
  cp "$HERE/$f" "$SNAP/$f" || fail "copy $f"
done
( cd "$SNAP" && sha256sum launch_official.sh inner_official.sh tau_sensitivity.py test_tau_official_v2.py ) > "$SNAP/sha256.manifest" || fail "manifest"
case "$MODE" in
  official)
    [ $# -eq 4 ] || fail "official needs PY A V2 OUT"
    PY=$1; A=$2; V2=$3; OUT=$4
    [ -e "$OUT" ] && fail "NEW_OUT_EXISTS $OUT"
    S1=("$PY" -m pytest "$SNAP/test_tau_official_v2.py" -p no:cacheprovider -q)
    S2=(/usr/bin/timeout -k 1 10 /usr/bin/time -v "$PY" "$SNAP/tau_sensitivity.py" "$A" "$V2" "$OUT")
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
bash "$SNAP/inner_official.sh" "$DIR" "${S1[@]}" -- "${S2[@]}"
rc=$?
exit "$rc"
