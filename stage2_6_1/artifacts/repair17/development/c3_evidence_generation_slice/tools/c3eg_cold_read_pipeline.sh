#!/usr/bin/env bash
# R17 C3 证据轮完整交付冷读(复用 fail_closed_integrity_delivery 轮
# pipeline 的既有能力;§9.2)。
#
# 追加本轮核对(轻量,不发展成新平台):
#   - 负例(缺件/篡改)的每个拒绝原因逐条落盘
#   - 实际 verifier argv 完整记录(build 与 verify 两侧)
set -uo pipefail
FC_TOOLS=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/fail_closed_integrity_delivery/tools
RR=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eg_full_20260908/run_record.json
# WORK 必须在 /mnt 与 /home/cryptorl/projects 之外(隔离冷读用 tmpfs
# 覆盖两个原根;上轮同款约束)——放 /home/cryptorl/r17c3eg_cold
WORKROOT=/home/cryptorl/r17c3eg_cold
WORK="$WORKROOT/cold_read_$(date -u +%Y%m%dT%H%M%SZ)"

if [ ! -f "$RR" ]; then
  echo "FATAL: run_record 不存在: $RR" >&2
  exit 2
fi
mkdir -p "$WORKROOT"

echo "== 复用上轮 pipeline(build→冷拷→双原根隔离冷读→负例) =="
bash "$FC_TOOLS/fc_cold_read_pipeline.sh" "$RR" "$WORK" \
  > "$WORKROOT/pipeline_stdout.log" 2>&1
RC=$?
echo "pipeline_rc=$RC"
tail -20 "$WORKROOT/pipeline_stdout.log"

echo "== 本轮追加:负例拒绝原因逐条核对 =="
grep -o '"reason"[^,}]*\|missing[^,}]*\|unreadable[^,}]*\|tamper[^,}]*\|control_failures[^,}]*' \
  "$WORK/negative.log" 2>/dev/null | sort | uniq -c | head -20 \
  > "$WORK/negative_reasons_summary.txt" || true
cat "$WORK/negative_reasons_summary.txt" 2>/dev/null || echo "(negative.log 无匹配模式;检查原始日志)"
if [ ! -s "$WORK/negative_reasons_summary.txt" ]; then
  echo "WARN: 负例原因摘要为空——如 negative.log 存在请人工检查" >&2
fi

echo "== 本轮追加:实际 verifier argv 记录 =="
{
  echo "# build argv"
  grep -m2 'r17_verify_delivery.py build' "$WORK/build.log" 2>/dev/null || true
  echo "# verify argv(冷读脚本内部调用;从 isolated/negative 日志提取)"
  grep -m2 'r17_verify_delivery.py verify' "$WORK/isolated.log" "$WORK/negative.log" 2>/dev/null || true
} > "$WORK/verifier_argv_record.txt"
cat "$WORK/verifier_argv_record.txt"

echo "FINAL_RC=$RC"
exit $RC
