#!/usr/bin/env bash
# 入口行为测试:文档命令原样可用/未知模式拒/多余参数拒/官方拒钩子。
# 用法: test_entry_infra.sh EVIDENCE_ROOT
set -u
R=${1:?usage: test_entry_infra.sh EVIDENCE_ROOT}
HERE=$(cd "$(dirname "$0")" && pwd)
RUNNER="$HERE/run_infra_repro.sh"
SUM=0

# E1 README 原样命令(--mode golden):golden 真实执行(非 MODE=--mode)
D="$R/e1"; mkdir -p "$D"
bash "$RUNNER" "$D/runs" --mode golden >/dev/null 2>&1
rc=$?
gr=$(grep -o "GOLDEN_RC=[-0-9]*" "$D"/runs/run_*/run_rc.txt | tail -1)
mr=$(grep -o "MODE=golden" "$D"/runs/run_*/run_rc.txt | head -1)
echo "[E1] rc=$rc $gr $mr (expect rc0 GOLDEN_RC=0|1 MODE=golden)"
[ "$rc" -eq 0 ] && [ "$gr" != "GOLDEN_RC=-1" ] && [ -n "$mr" ] || SUM=1

# E2 未知模式拒
D="$R/e2"; mkdir -p "$D"
bash "$RUNNER" "$D/runs" --mode bogus >/dev/null 2>&1
rc=$?; echo "[E2] rc=$rc expect=97"; [ "$rc" -eq 97 ] || SUM=1

# E3 多余参数拒
D="$R/e3"; mkdir -p "$D"
bash "$RUNNER" "$D/runs" --mode synthetic extra >/dev/null 2>&1
rc=$?; echo "[E3] rc=$rc expect=97"; [ "$rc" -eq 97 ] || SUM=1
bash "$RUNNER" "$D/r3b" synthetic extra >/dev/null 2>&1
rc=$?; echo "[E3b] rc=$rc expect=97"; [ "$rc" -eq 97 ] || SUM=1

# E4 官方运行拒绝任何钩子
D="$R/e4"; mkdir -p "$D"
INFRA_REPRO_AFTER_HOOK="true" \
  bash "$RUNNER" "$D/runs" synthetic >/dev/null 2>&1
rc=$?; echo "[E4] rc=$rc expect=11"; [ "$rc" -eq 11 ] || SUM=1
INFRA_REPRO_EXTRA_TESTS="/nonexistent" \
  bash "$RUNNER" "$D/r4b" synthetic >/dev/null 2>&1
rc=$?; echo "[E4b] rc=$rc expect=11"; [ "$rc" -eq 11 ] || SUM=1

# E5 位置式模式同义
D="$R/e5"; mkdir -p "$D"
bash "$RUNNER" "$D/runs" synthetic >/dev/null 2>&1
rc=$?; echo "[E5] rc=$rc expect=0"; [ "$rc" -eq 0 ] || SUM=1

echo "ENTRY_TEST_SUM=$SUM (0=all pass)"
exit "$SUM"
