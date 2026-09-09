#!/usr/bin/env bash
# E05 汇总:正例 + 两个缺件负例(缺语义回执/缺本轮 junit)。
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_identity_receipt_archive_closure
RUNS=$BASE/../run_supervision/runs
OUT=$BASE/verification_v3/aggregate
mkdir -p "$OUT"
PY=/usr/bin/python3

cat > "$OUT/config_pos.json" <<EOF
{
 "full_run_record": "$RUNS/c3irac_full_20260909/run_record.json",
 "full_stdout": "$RUNS/c3irac_full_20260909/business/stdout.log",
 "full_junit": "$RUNS/c3irac_full_20260909/junit.xml",
 "c3_semantic_receipt": "$BASE/verification_v3/receipts_v3/semantic_health.json",
 "c3_cold_read_report": "$BASE/verification_v3/cold_read_report_v3.json",
 "historical_archive_dir": "$BASE/historical_full_archive"
}
EOF
"$PY" "$BASE/tools/aggregate_v3.py" --config "$OUT/config_pos.json" \
  --out "$OUT/aggregate_report.json" > "$OUT/pos_stdout.log" 2>&1
POS_RC=$?

# 负例 1:缺本轮语义回执(指向不存在路径;缺件必须 FAIL)
sed "s|\"c3_semantic_receipt\": .*|\"c3_semantic_receipt\": \"$BASE/verification_v3/receipts_v3/semantic_receipt_MISSING.json\",|" \
  "$OUT/config_pos.json" > "$OUT/config_neg1.json"
"$PY" "$BASE/tools/aggregate_v3.py" --config "$OUT/config_neg1.json" \
  --out "$OUT/aggregate_neg_missing_semantic.json" \
  > "$OUT/neg1_stdout.log" 2>&1
NEG1_RC=$?
# 负例 2:缺本轮 junit
sed "s|\"full_junit\": .*|\"full_junit\": \"$BASE/verification_v3/junit_MISSING.xml\",|" \
  "$OUT/config_pos.json" > "$OUT/config_neg2.json"
"$PY" "$BASE/tools/aggregate_v3.py" --config "$OUT/config_neg2.json" \
  --out "$OUT/aggregate_neg_missing_junit.json" \
  > "$OUT/neg2_stdout.log" 2>&1
NEG2_RC=$?
echo "POS_RC=$POS_RC NEG1_RC=$NEG1_RC(expected 1) NEG2_RC=$NEG2_RC(expected 1)"
[ "$POS_RC" -eq 0 ] && [ "$NEG1_RC" -eq 1 ] && [ "$NEG2_RC" -eq 1 ]
