#!/usr/bin/env bash
# format 升 v5 后重建整条验证链:清理半途全量 run + 重新同步部署树
# + 重跑 135 项 + 重建 v5 包与冷读 + 重跑翻转。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEP=/home/cryptorl/projects/crypto_rl
TOOLS="$REPO/stage2_6_1/artifacts/repair17/development/c3_entry_temp_ownership_closure/tools"
CE="$REPO/stage2_6_1/artifacts/repair17/development/c3_entry_temp_ownership_closure/counterexamples"
VER="$REPO/stage2_6_1/artifacts/repair17/development/c3_entry_temp_ownership_closure/verification_v5"
RUN="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eto_full_20260909"

# 1) 半途失败 run(被停时业务已启动,无 run_record)保留为失败痕迹,
#    新全量换 c3eto_full_20260909_r2(不清除旧失败日志)
echo "旧半途 run 保留: $RUN (无 run_record,未完成痕迹)"

# 2) 重新同步部署树
cp "$REPO/stage2_6_1/runner/r17_c3_engineering_slice.py" "$DEP/stage2_6_1_runner/"
cp "$REPO/stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py" "$DEP/tests/route_c_stage2_6_1/"
sha256sum "$DEP/stage2_6_1_runner/r17_c3_engineering_slice.py"
source "$DEP/activate-freqtrade.sh"

# 3) 重跑 135 项
cd "$DEP"
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py \
  -q --no-header 2>&1 | tail -3

# 4) 重建 v5 包+冷读(一次性:清掉旧 verification_v5)
rm -rf "$VER"
mkdir -p "$VER"
CONDA_PY="$HOME/miniforge3/envs/freqtrade-rl/bin/python"
"$CONDA_PY" "$TOOLS/build_v5_package.py" build --repo "$REPO" \
  --out "$VER/package" --authority-src "$HOME/projects/crypto_rl/src"
BUILD_RC=$?
echo "BUILD_RC=$BUILD_RC"
[ "$BUILD_RC" = "0" ] || exit "$BUILD_RC"
rm -rf /tmp/c3eto_cold_v5_work
tr -d '\r' < "$TOOLS/cold_read_v5.sh" | bash -s -- \
  "$VER/package" /tmp/c3eto_cold_v5_work "$VER/cold_read_report_v5.json"
COLD_RC=$?
echo "COLD_RC=$COLD_RC"

# 5) 重跑翻转
rm -rf /tmp/c3eto_old_reader_v5
tr -d '\r' < "$CE/extract_old_reader.sh" | bash
echo "CHAIN_REBUILT"
