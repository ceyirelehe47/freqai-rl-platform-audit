#!/usr/bin/env bash
# E03/E05:汇总判定(正例 + 两负例:缺当前语义回执/缺 junit → 整体 FAIL)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
TOOLS="$DEV/c3_entry_temp_ownership_closure/tools"
CE="$DEV/c3_entry_temp_ownership_closure/counterexamples"
VER="$DEV/c3_entry_temp_ownership_closure/verification_v5"
AGG="$VER/aggregate"
RUN="$DEV/run_supervision/runs/c3eto_full_20260909_r2"
CONDA_PY="$HOME/miniforge3/envs/freqtrade-rl/bin/python"
mkdir -p "$AGG"

cat > "$AGG/config_pos.json" <<EOF
{
 "full_run_record": "$RUN/run_record.json",
 "full_stdout": "$RUN/business/stdout.log",
 "full_junit": "$RUN/junit.xml",
 "c3_semantic_receipt": "$VER/receipts_v5/semantic_health.json",
 "c3_cold_read_report": "$VER/cold_read_report_v5.json",
 "old_counterexamples": "$CE/old_reader_counterexamples_v5.json",
 "fixed_flip": "$CE/fixed_reader_flip_v5.json",
 "candidate_reader": "$REPO/stage2_6_1/runner/r17_c3_engineering_slice.py"
}
EOF
# 负例 1:缺当前语义回执(指向不存在路径)
sed 's|"c3_semantic_receipt": ".*"|"c3_semantic_receipt": "/nonexistent/semantic.json"|' \
  "$AGG/config_pos.json" > "$AGG/config_neg1.json"
# 负例 2:缺 junit(指向不存在路径)
sed 's|"full_junit": ".*"|"full_junit": "/nonexistent/junit.xml"|' \
  "$AGG/config_pos.json" > "$AGG/config_neg2.json"

RC=0
for name in pos neg1 neg2; do
  "$CONDA_PY" "$TOOLS/aggregate_v5.py" --config "$AGG/config_$name.json" \
    --out "$AGG/aggregate_report_$name.json" \
    > "$AGG/stdout_$name.log" 2>&1
  rc=$?
  echo "AGG_$name rc=$rc $(tail -1 "$AGG/stdout_$name.log" 2>/dev/null)"
done
echo "E05_DONE"
