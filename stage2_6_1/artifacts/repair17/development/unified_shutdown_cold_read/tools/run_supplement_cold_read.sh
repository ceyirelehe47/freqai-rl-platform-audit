#!/usr/bin/env bash
# 旧 run(final_20260907T140907)补充冷读:完整复制→隔离验证→负例→归档。
# 副本建在家目录(隔离时 /mnt 被遮蔽,副本必须在 /mnt 之外);
# 验证通过后整包归档回发布树(回执如实记录验证时 copy_root)。
set -euo pipefail
T=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read
DEV=$HOME/projects/crypto_rl/stage2_6_1_runner
OLD=$T/../read_failure_closure
SRC=$OLD/../read_failure_signal_safety/full_regression
COPY=$HOME/r17u_cold_supplement
STAMP=$(date -u +%Y%m%dT%H%M%SZ)

rm -rf "$COPY" "$T/cold_copies/r17u_supplement_final_140907" || true
python3 "$T/tools/build_cold_copy.py" \
  --source-root "$SRC" \
  --manifest "$OLD/delivery_manifest_v2.jsonl" \
  --anchor "$OLD/anchors/final.anchor.json" \
  --record-rel runs/final_20260907T140907/run_record.json \
  --verifier "$DEV/r17_verify_delivery.py" \
  --dest "$COPY"

mkdir -p "$T/receipts/r17u_supplement_final_140907"
bash "$T/tools/cold_read_isolated.sh" "$COPY" \
  "$T/receipts/r17u_supplement_final_140907" | tee "$T/receipts/r17u_supplement_final_140907/positive_stdout.txt"
bash "$T/tools/cold_read_negative.sh" "$COPY" \
  "$T/receipts/r17u_supplement_final_140907" | tee "$T/receipts/r17u_supplement_final_140907/negative_stdout.txt"

# 归档(验证后的持久化;不改变验证事实)
cp -r "$COPY" "$T/cold_copies/r17u_supplement_final_140907"
echo "ARCHIVED to $T/cold_copies/r17u_supplement_final_140907 (stamp $STAMP)"
