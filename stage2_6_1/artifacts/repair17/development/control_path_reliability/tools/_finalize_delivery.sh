#!/usr/bin/env bash
# 控制路径可靠性轮:全量回归收尾(build+verify+反例+blob)
set -euo pipefail
RD="$1"
FR="$(dirname "$(dirname "$RD")")"
REPO=/mnt/f/trading/freqai-rl-audit
cd "$REPO"
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
echo "=== build:"
"$PY" stage2_6_1/runner/r17_verify_delivery.py build \
  --run-record "$RD/run_record.json" \
  --manifest-out "$FR/delivery_manifest_v2.jsonl" \
  --anchor-out "$FR/anchors/final.anchor.json" \
  --root "$FR"
echo "=== 验证前篡改反例(追加 1 字节 → rc=1 检出 → 恢复):"
CP="$RD/telemetry/guest_samples.jsonl"
H0=$(sha256sum "$CP" | cut -d" " -f1)
printf ' ' >> "$CP"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$FR/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$FR/verify_receipts" >/dev/null 2>&1 && { echo "FATAL: 篡改未检出"; exit 1; } || echo "反例检出 rc!=0 OK"
head -c -1 "$CP" > /tmp/_trim && mv /tmp/_trim "$CP"
H1=$(sha256sum "$CP" | cut -d" " -f1)
[ "$H0" = "$H1" ] || { echo "FATAL: 恢复失败"; exit 1; }
echo "反例后恢复一致"
echo "=== verify(正式):"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$FR/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$FR/verify_receipts"
MAN_BLOB=$(git hash-object "$FR/delivery_manifest_v2.jsonl")
printf 'manifest_blob_id=%s\nregistered_utc=%s\n' \
  "$MAN_BLOB" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$FR/anchors/final.anchor.blob.txt"
echo "manifest_blob_id=$MAN_BLOB"
echo DONE
