#!/usr/bin/env bash
# 全量回归收尾:build + verify + git blob 登记(在发布仓库内执行)
set -euo pipefail
RD="$1"   # run 目录
FR="$(dirname "$(dirname "$RD")")"   # full_regression 根
REPO=/mnt/f/trading/freqai-rl-audit
cd "$REPO"
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python

echo "=== run_record 摘要:"
"$PY" -c 'import json,sys; r=json.load(open(sys.argv[1])); print(json.dumps({k:r[k] for k in ("schema","evidence_complete","missing_roles","business")}, ensure_ascii=False))' "$RD/run_record.json"

echo "=== build:"
"$PY" stage2_6_1/runner/r17_verify_delivery.py build \
  --run-record "$RD/run_record.json" \
  --manifest-out "$FR/delivery_manifest_v2.jsonl" \
  --anchor-out "$FR/anchors/final.anchor.json" \
  --root "$FR"

echo "=== 验证前缺件反例(追加 1 字节 → 必须 rc=1 检出 → 恢复):"
CP="$RD/telemetry/guest_samples.jsonl"
H0=$(sha256sum "$CP" | cut -d" " -f1)
printf ' ' >> "$CP"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$FR/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$FR/verify_receipts" 2>&1 | tail -2 || true
head -c -1 "$CP" > /tmp/_trim && mv /tmp/_trim "$CP"
H1=$(sha256sum "$CP" | cut -d" " -f1)
[ "$H0" = "$H1" ] || { echo "FATAL: 恢复失败"; exit 1; }
echo "反例后恢复一致: $H1"

echo "=== verify(正式):"
"$PY" stage2_6_1/runner/r17_verify_delivery.py verify \
  --root "$FR" --manifest "$FR/delivery_manifest_v2.jsonl" \
  --anchor-file "$FR/anchors/final.anchor.json" \
  --run-record "$RD/run_record.json" \
  --receipt-dir "$FR/verify_receipts"

echo "=== git blob(hash-object,不依赖暂存;记独立登记文件,不改锚):"
MAN_BLOB=$(git hash-object "$FR/delivery_manifest_v2.jsonl")
printf 'manifest_blob_id=%s\nregistered_utc=%s\n' \
  "$MAN_BLOB" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  > "$FR/anchors/final.anchor.blob.txt"
echo "manifest_blob_id=$MAN_BLOB"
echo DONE
