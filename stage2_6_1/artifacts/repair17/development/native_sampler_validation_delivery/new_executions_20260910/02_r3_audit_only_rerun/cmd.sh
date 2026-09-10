#!/usr/bin/env bash
# [新执行 2026-09-10] r3 旧 run 的必要字节审计只读重跑(与原件 r3_audit_only.json
# 同参数:--telemetry-hints)。r3 run 目录只读;预期 telemetry_win 仍不匹配
# (记录锚 264179/f502a49f vs 工作树现状),即 r3 判定维持 FAIL,不追改。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
NEW=$BASE/native_sampler_validation_delivery/new_executions_20260910
RUNNER=/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner

python3 "$RUNNER/r17_required_bytes.py" \
  --root "$BASE/run_supervision" \
  --record "$BASE/run_supervision/runs/c3eto_full_20260909_r3/run_record.json" \
  --telemetry-hints \
  > "$NEW/02_r3_audit_only_rerun/audit_stdout.json" \
  2> "$NEW/02_r3_audit_only_rerun/audit_stderr.log"
RC=$?
echo "R3_AUDIT_ONLY_RC=$RC(非0为预期:telemetry_win 字节不匹配=FAIL 维持)"
exit "$RC"
