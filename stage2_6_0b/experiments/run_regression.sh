#!/usr/bin/env bash
# 阶段 2.6.0b 全量回归(2.5 -> 2.6.0b)
set -uo pipefail

cd "$(dirname "$0")/../.."
source activate-freqtrade.sh

OUT="artifacts/route_c_stage2_6_0b/regression_test_summary.md"
LOGDIR="logs/route_c_stage2_6_0b"
mkdir -p "$LOGDIR" artifacts/route_c_stage2_6_0b

DIRS=(
  tests/freqai_rl_platform_audit
  tests/freqai_rl_stage2_5
  tests/freqai_rl_stage2_5_1
  tests/freqai_rl_stage2_5_2
  tests/freqai_rl_stage2_5_2a
  tests/route_c_stage2_6_0
  tests/route_c_stage2_6_0a
  tests/route_c_stage2_6_0b
)

echo "# 阶段 2.6.0b 全量回归测试汇总" > "$OUT"
echo "" >> "$OUT"
echo "- 日期: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$OUT"
echo "- 环境: WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python $(python --version 2>&1 | cut -d' ' -f2)" >> "$OUT"
echo "" >> "$OUT"
echo "| 测试目录 | passed | failed | error | 耗时(s) |" >> "$OUT"
echo "|---|---|---|---|---|" >> "$OUT"

TOTAL_P=0
TOTAL_F=0
TOTAL_E=0
FAILANY=0

for d in "${DIRS[@]}"; do
  name=$(basename "$d")
  log="$LOGDIR/regress_${name}.log"
  echo "[regression] running $d ..."
  if timeout 5400 python -m pytest "$d" -q -p no:cacheprovider > "$log" 2>&1; then
    status=0
  else
    status=$?
    FAILANY=1
  fi
  tail_line=$(tail -n 3 "$log" | grep -E "passed|failed|error" | tail -n 1)
  passed=$(echo "$tail_line" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+" || echo 0)
  failed=$(echo "$tail_line" | grep -oE "[0-9]+ failed" | grep -oE "[0-9]+" || echo 0)
  error=$(echo "$tail_line" | grep -oE "[0-9]+ error" | grep -oE "[0-9]+" || echo 0)
  duration=$(echo "$tail_line" | grep -oE "in [0-9.]+s" | grep -oE "[0-9.]+" || echo "?")
  echo "| $name | $passed | $failed | $error | $duration |" >> "$OUT"
  TOTAL_P=$((TOTAL_P + passed))
  TOTAL_F=$((TOTAL_F + failed))
  TOTAL_E=$((TOTAL_E + error))
done

echo "" >> "$OUT"
echo "**合计: $TOTAL_P passed / $TOTAL_F failed / $TOTAL_E error**" >> "$OUT"
echo "" >> "$OUT"
echo "汇总:"
cat "$OUT"
exit $FAILANY
