#!/usr/bin/env bash
# [新执行 2026-09-10] 第3项补件:full2 强制字节门禁 wrapper 只读重跑。
# 原始执行的输出 JSON 已存(originals/03_aggregate/verified_aggregate_full2.json),
# 但当时 stdout/rc 未落文件;本重跑用同一 config 字节、同一代码(仓库 29101e0 检出)
# 补齐 stdout/stderr/rc。对 full2 run 目录只读,--out 只写本目录。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
DELIV=$BASE/native_sampler_validation_delivery
NEW=$DELIV/new_executions_20260910
RUNNER=/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner
AGG=$BASE/c3_entry_temp_ownership_closure/tools/aggregate_v6.py

python3 "$RUNNER/r17_verified_aggregate.py" \
  --root "$BASE/run_supervision" \
  --record "$BASE/run_supervision/runs/r17ns_full2_20260909T174348/run_record.json" \
  --legacy-script "$AGG" \
  --config "$DELIV/originals/03_aggregate/aggregate_config_full2.json" \
  --out "$NEW/01_full2_wrapper_rerun/out.json"
RC=$?
echo "WRAPPER_RC=$RC"
exit "$RC"
