#!/usr/bin/env bash
# 阶段四主执行链:C3 关联交付(受监护 build run → finalize → 隔离冷读)。
#
# 用法: bash run_verification_pipeline.sh [RUN_NAME(缺省 c3rdd_pkg_build_20260909)]
# 返回: 0=全部通过;非零=对应步骤失败(保留现场)
set -uo pipefail
RUN_NAME="${1:-c3rdd_pkg_build_20260909}"
REPO=/mnt/f/trading/freqai-rl-audit
DELIV="$REPO/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery"
VER="$DELIV/verification"
TOOLS="$DELIV/tools"
RUNNER=~/projects/crypto_rl/stage2_6_1_runner
RUN_DIR_REL="stage2_6_1/artifacts/repair17/development/run_supervision/runs/$RUN_NAME"
RR_REL="$RUN_DIR_REL/run_record.json"

source ~/projects/crypto_rl/activate-freqtrade.sh

# 0) 同步最新代码(新 reader 等)
tr -d '\r' < "$REPO/stage2_6_1/runner/r17_sync.sh" | bash

# 1) 受监护 build run(kind=engineering;run 目录一次性预指定)
export R17_RUN_DIR="$REPO/$RUN_DIR_REL"
bash "$RUNNER/r17_monitored_entry.sh" engineering --max-seconds 900 -- \
  python3 "$TOOLS/verify_c3_package.py" --repo "$REPO" --out "$VER" --build
BUILD_RC=$?
echo "STEP1 build rc=$BUILD_RC"
if [ "$BUILD_RC" -ne 0 ]; then
  echo "BUILD_FAIL(现场保留: $VER 与 run 目录)" >&2
  exit 1
fi

# 2) finalize:run_record 已关闭 → 追加 record 行+交付根直接 verify
python3 "$TOOLS/verify_c3_package.py" --repo "$REPO" --out "$VER" \
  --finalize-record "$RR_REL"
FIN_RC=$?
echo "STEP2 finalize rc=$FIN_RC"
if [ "$FIN_RC" -ne 0 ]; then exit 1; fi

# 3) 隔离冷读 + 三负例
bash "$TOOLS/cold_read_c3_package.sh" "$REPO" "$DELIV" /home/cryptorl/r17rdd_cold
COLD_RC=$?
echo "STEP3 cold rc=$COLD_RC"
exit "$COLD_RC"
