#!/usr/bin/env bash
# [新执行 2026-09-10] 第4项补件之二:隔离交付副本包(full2_pkg)冷读正例重跑。
# 与原件 build_pkg.sh 第5步同参数(--root 为包本身、config=cold_config.json、
# legacy=包内 aggregate_v6);包本体只读,--out 只写本目录。预期 rc=0。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
NEW=$BASE/native_sampler_validation_delivery/new_executions_20260910
PKG=/mnt/f/trading/r17_native_smoke_logs/full2_pkg

python3 "$PKG/code/r17_verified_aggregate.py" \
  --root "$PKG" \
  --record "$PKG/runs/r17ns_full2_20260909T174348/run_record.json" \
  --legacy-script "$PKG/code/aggregate_v6.py" \
  --config "$PKG/cold_config.json" \
  --out "$NEW/04_pkg_cold_positive_rerun/verified_aggregate_cold_rerun.json"
RC=$?
echo "COLD_READ_RC=$RC"
exit "$RC"
