#!/bin/bash
# R17 c3-path-param-closure:E05 汇总三例(正例+缺语义回执负例+缺 junit 负例)。
# stdin 方式执行,路径硬编码。
set -u
T=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_path_param_closure
RUNS=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs
AGG="$T/tools/aggregate_v4.py"
OUT="$T/verification_v4/aggregate"

mkdir -p "$OUT"

cat > "$OUT/config_pos.json" <<EOF
{
  "full_run_record": "$RUNS/c3ppc_full_20260909/run_record.json",
  "full_stdout": "$RUNS/c3ppc_full_20260909/business/stdout.log",
  "full_junit": "$RUNS/c3ppc_full_20260909/junit.xml",
  "c3_semantic_receipt": "$T/verification_v4/receipts_v4/semantic_health.json",
  "c3_cold_read_report": "$T/verification_v4/cold_read_report_v4.json",
  "old_counterexamples": "$T/counterexamples/old_reader_counterexamples.json",
  "fixed_flip": "$T/counterexamples/fixed_reader_flip.json",
  "candidate_reader": "/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_c3_engineering_slice.py"
}
EOF

# 负例 1:缺当前语义回执(路径指向不存在文件)
sed 's#"c3_semantic_receipt": "[^"]*"#"c3_semantic_receipt": "'"$T"'/verification_v4/receipts_v4/semantic_receipt_MISSING.json"#' \
  "$OUT/config_pos.json" > "$OUT/config_neg1.json"
# 负例 2:缺 junit(路径指向不存在文件)
sed 's#"full_junit": "[^"]*"#"full_junit": "'"$RUNS"'/c3ppc_full_20260909/junit_MISSING.xml"#' \
  "$OUT/config_pos.json" > "$OUT/config_neg2.json"

python3 "$AGG" --config "$OUT/config_pos.json" --out "$OUT/aggregate_report.json" \
  > "$OUT/pos_stdout.log" 2>&1
POS_RC=$?
python3 "$AGG" --config "$OUT/config_neg1.json" --out "$OUT/aggregate_neg_missing_semantic.json" \
  > "$OUT/neg1_stdout.log" 2>&1
NEG1_RC=$?
python3 "$AGG" --config "$OUT/config_neg2.json" --out "$OUT/aggregate_neg_missing_junit.json" \
  > "$OUT/neg2_stdout.log" 2>&1
NEG2_RC=$?

echo "POS_RC=$POS_RC NEG1_RC=$NEG1_RC NEG2_RC=$NEG2_RC"
[ "$POS_RC" -eq 0 ] && [ "$NEG1_RC" -eq 1 ] && [ "$NEG2_RC" -eq 1 ]
