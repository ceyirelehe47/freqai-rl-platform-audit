#!/bin/bash
# inner_qdecomp.sh — q_error_decomposition 内部 wrapper(复用已验 inner_official v2 终版语义,零逻辑改动)
# - 解析在捕获内:恰一个 "--"、两侧非空,否则 PARSE_ERROR exit98;
# - stage1 非零 → 立即退出该 rc,stage2 绝不启动;
# - stage2 须自带 /usr/bin/timeout -k 1 60 /usr/bin/time -v 前缀
#   (TERM@60s+KILL 宽限 1s);rc 原样保留于 stage2_rc.txt;
#   124=TERM 超时;137=SIGKILL(仅陈述被杀,不无证据断言超时);
# - time -v **严格解析**:四字段各恰一次、数值非负有限
#   (缺项/重复/NaN/非数字 → exit45 fail-closed,禁止当 0);
#   wall 完整 h:mm:ss(含小时);RSS KiB 阈值 1048576;
# - 外部终态超限(wall/cpu/rss)不因 stage2 rc=0 豁免:
#   41/42/43;124/137 → 44(注明原因);成功才 SCIENCE_OK。
set -u
DIR=${1:?attempt_dir}
shift 1
S1=(); S2=(); sep=0; nsep=0
for a in "$@"; do
  if [ "$a" = "--" ]; then nsep=$((nsep+1)); sep=1; continue; fi
  if [ "$sep" = 0 ]; then S1+=("$a"); else S2+=("$a"); fi
done
if [ "$nsep" -ne 1 ] || [ ${#S1[@]} -eq 0 ] || [ ${#S2[@]} -eq 0 ]; then
  echo "PARSE_ERROR: exactly one '--' with non-empty both sides (nsep=$nsep s1=${#S1[@]} s2=${#S2[@]})" | tee "$DIR/PARSE_ERROR.txt" >&2
  exit 98
fi
echo "stage1: ${S1[*]}" > "$DIR/stage1_cmd.txt"
"${S1[@]}" > "$DIR/stage1_stdout.log" 2> "$DIR/stage1_stderr.log"
rc1=$?
echo "$rc1" > "$DIR/stage1_rc.txt"
if [ "$rc1" -ne 0 ]; then
  echo "STAGE1_NONZERO_ABORT rc=$rc1 (stage2 NOT started)" >&2
  exit "$rc1"
fi
echo "stage2: ${S2[*]}" > "$DIR/stage2_cmd.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/stage2_utc_start.txt"
"${S2[@]}" > "$DIR/stage2_stdout.log" 2> "$DIR/stage2_time.log"
rc2=$?
echo "$rc2" > "$DIR/stage2_rc.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$DIR/stage2_utc_end.txt"
TLOG="$DIR/stage2_time.log"
# 先判被杀(被杀时 time -v 可能无统计):rc 原样已存
if [ "$rc2" -eq 124 ]; then
  printf '{"wall_s":">=60.0(TERM at 60s)","stage2_rc_raw":124,"note":"external timeout TERM fired; killed stats unavailable"}\n' > "$DIR/resources.json"
  echo "STAGE2_TERM_TIMEOUT" >&2; exit 44
fi
if [ "$rc2" -eq 137 ]; then
  printf '{"stage2_rc_raw":137,"signal":"SIGKILL","cause":"unproven","budget":"not_passed","note":"SIGKILL observed; cause NOT established (60s is the failure threshold; -k 1 is cleanup grace — kept distinct)"}\n' > "$DIR/resources.json"
  echo "STAGE2_SIGKILL_OBSERVED_CAUSE_UNPROVEN" >&2; exit 44
fi
res_fail() { echo "RESOURCES_PARSE_ERROR: $1" | tee "$DIR/RESOURCES_ERROR.txt" >&2; exit 45; }
cnt() { grep -cF "$1" "$TLOG" || true; }
[ "$(cnt 'Elapsed (wall clock) time')" -eq 1 ] || res_fail "wall count"
[ "$(cnt 'User time (seconds):')" -eq 1 ] || res_fail "user count"
[ "$(cnt 'System time (seconds):')" -eq 1 ] || res_fail "sys count"
[ "$(cnt 'Maximum resident set size')" -eq 1 ] || res_fail "rss count"
WALL=$(grep -F 'Elapsed (wall clock) time' "$TLOG" | awk '{print $NF}')
UT=$(grep -F 'User time (seconds):' "$TLOG" | awk '{print $NF}')
ST=$(grep -F 'System time (seconds):' "$TLOG" | awk '{print $NF}')
RSSK=$(grep -F 'Maximum resident set size' "$TLOG" | awk '{print $NF}')
WH=0; WM=; WS=
if [[ "$WALL" =~ ^([0-9]+):([0-9]{1,2}):([0-9]{1,2}(\.[0-9]+)?)$ ]]; then
  WH=${BASH_REMATCH[1]}; WM=${BASH_REMATCH[2]}; WS=${BASH_REMATCH[3]}
elif [[ "$WALL" =~ ^([0-9]+):([0-9]{1,2}(\.[0-9]+)?)$ ]]; then
  WH=0; WM=${BASH_REMATCH[1]}; WS=${BASH_REMATCH[2]}
else
  res_fail "wall fmt '$WALL'"
fi
[ -n "$WM" ] && [ -n "$WS" ] || res_fail "wall parts '$WALL'"
awk "BEGIN{exit !($WM>=60)}" && res_fail "wall minutes '$WM'"
awk "BEGIN{exit !($WS>=60)}" && res_fail "wall seconds '$WS'"
echo "$UT" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || res_fail "cpu fmt '$UT'"
echo "$ST" | grep -Eq '^[0-9]+(\.[0-9]+)?$' || res_fail "sys fmt '$ST'"
echo "$RSSK" | grep -Eq '^[0-9]+$' || res_fail "rss fmt '$RSSK'"
WALL_S=$(awk "BEGIN{printf \"%.3f\", $WH*3600+$WM*60+$WS}")
CPU=$(awk "BEGIN{printf \"%.3f\", $UT+$ST}")
printf '{"wall_s":%s,"cpu_s":%s,"rss_kib":%s,"limits":{"wall_s":60.0,"cpu_s":30.0,"rss_kib":1048576},"stage2_rc_raw":%s,"note":"wall external via timeout -k 1 60 (TERM@60s,KILL grace 1s); CPU/RSS internal post-hoc check + external terminal record (no OS hard limit); SIGKILL only states killed"}\n' "$WALL_S" "$CPU" "$RSSK" "$rc2" > "$DIR/resources.json"
if awk -v w="$WALL_S" 'BEGIN{exit !(w>60.0)}'; then echo "WALL_OVER $WALL_S" >&2; exit 41; fi
if awk -v c="$CPU" 'BEGIN{exit !(c>30.0)}'; then echo "CPU_OVER $CPU" >&2; exit 42; fi
if awk -v r="$RSSK" 'BEGIN{exit !(r>1048576)}'; then echo "RSS_OVER $RSSK" >&2; exit 43; fi
if [ "$rc2" -ne 0 ]; then exit "$rc2"; fi
echo ok > "$DIR/SCIENCE_OK.marker"
exit 0
