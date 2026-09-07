#!/usr/bin/env bash
# 冷读:交付集合复制到独立目录(/tmp)后 verify(脱离开发绝对路径)
set -euo pipefail
FR=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/control_path_reliability/full_regression
COLD=/tmp/r17_cpr_cold_read_$$
mkdir -p "$COLD"
RD="$FR/runs/final_20260907T013347"
# 复制必需件(run 目录内 7 件+run_record;清单行 path 相对 full_regression 根)
mkdir -p "$COLD/runs"
cp -r "$RD" "$COLD/runs/"
cp "$FR/delivery_manifest_v2.jsonl" "$COLD/"
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
cd /mnt/f/trading/freqai-rl-audit
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$COLD" --manifest "$COLD/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$COLD/runs/final_20260907T013347/run_record.json" \
  --receipt-dir "$FR/verify_receipts"
rm -rf "$COLD"
echo COLD_READ_DONE
