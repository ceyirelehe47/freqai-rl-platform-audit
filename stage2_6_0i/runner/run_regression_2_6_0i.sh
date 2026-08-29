#!/usr/bin/env bash
# 阶段 2.6.0i 全量回归:全部历史测试目录 + 2.6.0i 新增,零失败零跳过零 xfail
set -u
source "$HOME/projects/crypto_rl/activate-freqtrade.sh" >/dev/null 2>&1
cd "$HOME/projects/crypto_rl"

LOG="$HOME/projects/crypto_rl/logs/regression_2_6_0i_raw.log"
SUMMARY="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_0i/regression_test_summary.md"
UPSTREAM="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_0i/upstream_integrity.txt"
mkdir -p "$(dirname "$LOG")" "$(dirname "$SUMMARY")"
: > "$LOG"

DIRS=(
  tests/freqai_rl_platform_audit
  tests/freqai_rl_stage2_5
  tests/freqai_rl_stage2_5_1
  tests/freqai_rl_stage2_5_2
  tests/freqai_rl_stage2_5_2a
  tests/route_c_stage2_6_0
  tests/route_c_stage2_6_0a
  tests/route_c_stage2_6_0b
  tests/route_c_stage2_6_0c
  tests/route_c_stage2_6_0d
  tests/route_c_stage2_6_0e
  tests/route_c_stage2_6_0f
  tests/route_c_stage2_6_0g
  tests/route_c_stage2_6_0h
  tests/route_c_stage2_6_0i
)

TOTAL=0
FAIL=0
{
  echo "# 阶段 2.6.0i 全量回归摘要"
  echo
  echo "| 目录 | 结果 |"
  echo "|---|---|"
} > "$SUMMARY"

for d in "${DIRS[@]}"; do
  echo "=== $d ===" | tee -a "$LOG"
  OUT=$(timeout 3600 env PYTHONPATH=src python -m pytest "$d" -q -p no:cacheprovider 2>&1)
  echo "$OUT" >> "$LOG"
  LINE=$(echo "$OUT" | tail -1)
  echo "$LINE"
  N=$(echo "$LINE" | grep -oE "[0-9]+ passed" | grep -oE "[0-9]+" || echo 0)
  TOTAL=$((TOTAL + N))
  STATUS="OK"
  if ! echo "$LINE" | grep -qE "passed" || \
     echo "$LINE" | grep -qE "[1-9][0-9]* (failed|error)"; then
    FAIL=$((FAIL + 1))
    STATUS="FAILED"
    echo "!!! FAILURE in $d"
  fi
  if echo "$LINE" | grep -qE "[1-9][0-9]* (skipped|xfail)"; then
    FAIL=$((FAIL + 1))
    STATUS="SKIP/XFAIL"
    echo "!!! SKIP/XFAIL in $d"
  fi
  echo "| \`$d\` | $LINE |" >> "$SUMMARY"
done

W=$(echo "$LINE" | true)
WARN=$(grep -c "warning" "$LOG" || true)
{
  echo
  echo "**总计: $TOTAL passed / 失败目录数: $FAIL / warning 行数(不计失败): $WARN**"
  echo
  echo "原始日志: regression_raw.log(逐目录完整输出)"
} >> "$SUMMARY"

# vendor/freqtrade 上游完整性
{
  echo "# upstream integrity (vendor/freqtrade)"
  echo "expected HEAD: 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
  cd vendor/freqtrade || exit 1
  echo "actual HEAD:   $(git rev-parse HEAD)"
  if [ -n "$(git status --porcelain)" ]; then
    echo "worktree: DIRTY"
    git status --porcelain | head -20
  else
    echo "worktree: clean"
  fi
} > "$UPSTREAM" 2>&1

echo "=================================="
echo "TOTAL PASSED: $TOTAL  FAILED DIRS: $FAIL"
echo "log: $LOG"
echo "summary: $SUMMARY"
echo "upstream: $UPSTREAM"
