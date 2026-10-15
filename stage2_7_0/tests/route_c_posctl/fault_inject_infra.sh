#!/usr/bin/env bash
# 故障注入验证(TEST-ONLY 包装会话:INFRA_REPRO_ALLOW_HOOKS=1;
# 官方运行拒绝一切钩子——见 test_entry_infra.sh E4)。
# 用法: fault_inject_infra.sh EVIDENCE_ROOT
set -u
export INFRA_REPRO_ALLOW_HOOKS=1   # 包装测试会话(官方运行拒钩子)
R=${1:?usage: fault_inject_infra.sh EVIDENCE_ROOT}
HERE=$(cd "$(dirname "$0")" && pwd)
RUNNER="$HERE/run_infra_repro.sh"
SUM=0; note() { echo "[$1] rc=$2 expect_nonzero"; }

# F1 真实 pytest 失败
D="$R/f1"; mkdir -p "$D"
printf 'def test_injected_failure():\n    assert 0, "injected"\n' > "$D/fail_test.py"
INFRA_REPRO_EXTRA_TESTS="$D/fail_test.py" \
  bash "$RUNNER" "$D/runs" synthetic >/dev/null 2>&1
rc=$?; note F1_pytest_fail $rc; [ "$rc" -ne 0 ] || SUM=1

# F2 真实扫描错误(扫描目标文件缺失;/mnt/f 上 chmod 000 被
# DrvFs 忽略,不可读路径无法构造,故用缺文件路径)
D="$R/f2"; mkdir -p "$D/scan"
INFRA_REPRO_ALLOW_HOOKS=1 \
  INFRA_REPRO_SCAN_TARGET="$D/scan" \
  bash "$RUNNER" "$D/runs" synthetic >/dev/null 2>&1
rc=$?; note F2_scan_error $rc; [ "$rc" -ne 0 ] || SUM=1

# F3 真实输入变化(附加哈希输入在前后之间被改)
D="$R/f3"; mkdir -p "$D"
printf 'before' > "$D/probe.txt"
INFRA_REPRO_EXTRA_INPUTS="$D/probe.txt" \
  INFRA_REPRO_AFTER_HOOK="printf 'after' >| '$D/probe.txt'" \
  bash "$RUNNER" "$D/runs" synthetic >/dev/null 2>&1
rc=$?; note F3_input_change $rc; [ "$rc" -ne 0 ] || SUM=1

# F4 golden 异常退出(篡改 manifest 副本 → 生产信任表拒 → rc3)
D="$R/f4"; mkdir -p "$D"
G=/mnt/f/trading/c1_course_offline_v1_20261015/manifest_v1.json
sed 's/ck131072/ckX31072/' "$G" > "$D/tampered.json"
INFRA_REPRO_ALLOW_HOOKS=1 \
  INFRA_REPRO_GOLDEN_MANIFEST="$D/tampered.json" \
  bash "$RUNNER" "$D/runs" golden >/dev/null 2>&1
rc=$?; note F4_golden_abnormal $rc; [ "$rc" -ne 0 ] || SUM=1

echo "FAULT_INJECT_SUM=$SUM (0=all four correctly nonzero)"
exit "$SUM"
