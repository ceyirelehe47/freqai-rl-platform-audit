#!/bin/bash
# outer_run.sh v3 — 最早外层捕获(捕获先于一切解析)
# 语义:
#  唯一前提=capture 根已存在且可写(不可写→97,不承诺落盘);
#  CAP=mktemp -d 原子独占(失败 96);
#  先 exec 重定向+EXIT trap(原 rc/utc_end)→utc_start→
#  外层源快照+hash+argv;**此后**才解析 label/--/command;
#  缺 label/分隔符/命令=98;源快照/hash 失败=94。
# 用法: outer_run.sh <capture_root> <label> -- <cmd...>
set -u
CR=${1:-}
if [ -z "$CR" ] || [ ! -d "$CR" ] || [ ! -w "$CR" ]; then
  echo "CAPTURE_ROOT_INVALID $CR" >&2
  exit 97
fi
CAP=$(mktemp -d "$CR/fivepoint_capture_XXXXXXXX") || {
  echo "MKTEMP_FAIL" >&2; exit 96; }
exec > "$CAP/stdout.log" 2> "$CAP/stderr.log"
trap 'rc=$?; echo "$rc" > "$CAP/rc.txt"; date -u +%Y-%m-%dT%H:%M:%SZ > "$CAP/utc_end.txt"' EXIT
date -u +%Y-%m-%dT%H:%M:%SZ > "$CAP/utc_start.txt"
printf '%s\n' "$*" > "$CAP/argv.txt"
if ! cp "$0" "$CAP/outer_source.sh" 2>/dev/null \
   || ! sha256sum "$0" > "$CAP/outer_source.sha256" 2>/dev/null; then
  echo "SOURCE_SNAPSHOT_FAIL" >&2
  exit 94
fi
# —— 捕获与源快照就绪,以下才解析 ——
shift || { echo "MISSING_LABEL" > "$CAP/FAIL_REASON.txt"; exit 98; }
LABEL=${1:-}
if [ -z "$LABEL" ]; then
  echo "MISSING_LABEL" > "$CAP/FAIL_REASON.txt"; exit 98
fi
shift || { echo "MISSING_SEP" > "$CAP/FAIL_REASON.txt"; exit 98; }
if [ "${1:-}" != "--" ]; then
  echo "MISSING_SEP" > "$CAP/FAIL_REASON.txt"; exit 98
fi
shift || { echo "MISSING_COMMAND" > "$CAP/FAIL_REASON.txt"; exit 98; }
if [ $# -lt 1 ]; then
  echo "MISSING_COMMAND" > "$CAP/FAIL_REASON.txt"; exit 98
fi
printf '%s\n' "$*" > "$CAP/cmd.txt"
"$@"
exit $?
