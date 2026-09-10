#!/usr/bin/env bash
# [新执行 2026-09-10] 第4项补件之一:D3 反例(追加副本)上 legacy 单独运行
# 与强制门禁 wrapper 的退出码复核。与原件 d3_codes.sh 同参数;
# --root 指向原始执行位置的 copy_root(字节与归档副本一致,由 07 项核验),
# legacy/wrapper 的 --out 只写本目录。预期:LEGACY rc=0 且 ok=true(legacy 可 PASS),
# WRAPPER rc!=0 且 overall_ok=false(门禁整体拒绝)。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
DELIV=$BASE/native_sampler_validation_delivery
NEW=$DELIV/new_executions_20260910
RUNNER=/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner
AGG=$BASE/c3_entry_temp_ownership_closure/tools/aggregate_v6.py
SMOKE=/mnt/f/trading/r17_native_smoke_logs

python3 "$AGG" \
  --config "$DELIV/originals/03_aggregate/aggregate_config_neg_append.json" \
  --out "$NEW/03_d3_rerun/legacy_standalone_rerun.json"
LRC=$?
echo "LEGACY_STANDALONE_RC=$LRC"

python3 "$RUNNER/r17_verified_aggregate.py" \
  --root "$SMOKE/copy_root" \
  --record "$SMOKE/copy_root/runs/r17ns_dpos_20260909T170033/run_record.json" \
  --legacy-script "$AGG" \
  --config "$DELIV/originals/03_aggregate/aggregate_config_neg_append.json" \
  --out "$NEW/03_d3_rerun/verified_aggregate_neg_append_rerun.json"
WRC=$?
echo "WRAPPER_RC=$WRC"

if [ "$LRC" -eq 0 ] && [ "$WRC" -ne 0 ]; then
  echo "D3_OUTCOME=LEGACY_PASS_WRAPPER_REJECT(符合预期)"
  exit 0
else
  echo "D3_OUTCOME=UNEXPECTED"
  exit 1
fi
