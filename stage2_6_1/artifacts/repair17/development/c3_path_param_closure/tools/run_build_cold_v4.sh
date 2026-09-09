#!/bin/bash
# 阶段三:v4 包构建 + 隔离冷读。stdin 方式执行,路径硬编码。
set -u
T=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_path_param_closure
REPO=/mnt/f/trading/freqai-rl-audit
source "$HOME/projects/crypto_rl/activate-freqtrade.sh" >/dev/null 2>&1

if [ ! -f "$T/verification_v4/build_report_v4.json" ]; then
  rm -rf "$T/verification_v4"
  mkdir -p "$T/verification_v4"
  python "$T/tools/build_v4_package.py" build --repo "$REPO" \
    --out "$T/verification_v4/package"
  echo "BUILD_RC=$?"
else
  echo "BUILD_ALREADY_DONE"
fi

rm -rf /tmp/c3pp_cold_work
tr -d '\r' < "$T/tools/cold_read_v4.sh" | bash -s \
  "$T/verification_v4/package" /tmp/c3pp_cold_work \
  "$T/verification_v4/cold_read_report_v4.json"
echo "COLD_RC=$?"
