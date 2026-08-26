#!/usr/bin/env bash
# 阶段 2.6.0a 全量回归:2.5 / 2.5.1 / 2.5.2 / 2.5.2a / platform_audit /
# 2.6.0 / 2.6.0a(输出逐目录计数与汇总到 artifacts)
set -uo pipefail

source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1
cd ~/projects/crypto_rl

OUT=artifacts/route_c_stage2_6_0a/regression_test_summary.md
LOGDIR=logs/route_c_stage2_6_0a
mkdir -p "$LOGDIR"

{
echo "# 阶段 2.6.0a 回归测试汇总"
echo
echo "- 日期(UTC): $(date -u '+%Y-%m-%d %H:%M:%S')"
echo "- 命令: python -m pytest <dir> -q(逐目录)"
echo
echo "| 目录 | 通过 | 失败 | 错误 | 耗时 |"
echo "|---|---|---|---|---|"
} > "$OUT"

TOTAL_PASS=0
TOTAL_FAIL=0
for d in \
  tests/freqai_rl_platform_audit \
  tests/freqai_rl_stage2_5 \
  tests/freqai_rl_stage2_5_1 \
  tests/freqai_rl_stage2_5_2 \
  tests/freqai_rl_stage2_5_2a \
  tests/route_c_stage2_6_0 \
  tests/route_c_stage2_6_0a; do
  name=$(basename "$d")
  echo "[regression] running $name ..." >&2
  log="$LOGDIR/regress_${name}.log"
  timeout 3000 python -m pytest "$d" -q -p no:cacheprovider >"$log" 2>&1
  rc=$?
  tail_line=$(tail -n 1 "$log")
  if [[ "$tail_line" =~ ([0-9]+)\ passed ]]; then pass="${BASH_REMATCH[1]}"; else pass=0; fi
  if [[ "$tail_line" =~ ([0-9]+)\ failed ]]; then fail="${BASH_REMATCH[1]}"; else fail=0; fi
  if [[ "$tail_line" =~ ([0-9]+)\ error ]]; then err="${BASH_REMATCH[1]}"; else err=0; fi
  if [[ "$tail_line" =~ in\ ([0-9.]+)s ]]; then dur="${BASH_REMATCH[1]}s"; else dur="?"; fi
  echo "| $name | $pass | $fail | $err | $dur |" >> "$OUT"
  TOTAL_PASS=$((TOTAL_PASS+pass)); TOTAL_FAIL=$((TOTAL_FAIL+fail+err))
done

{
echo
echo "**合计: $TOTAL_PASS 通过 / $TOTAL_FAIL 失败+错误**"
echo
echo "判定: $([ "$TOTAL_FAIL" -eq 0 ] && echo '全部通过' || echo '存在失败')"
} >> "$OUT"
cat "$OUT"
