#!/usr/bin/env bash
# R16 开发同步:发布仓库 -> WSL 开发树(逐文件 tr -d CR;LF 保证)
# 用法(Windows): wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "tr -d '\r' < /mnt/e/trading/freqai-rl-audit/stage2_6_1/runner/r16_sync.sh | bash"
# 或(WSL内): tr -d '\r' < /mnt/e/trading/freqai-rl-audit/stage2_6_1/runner/r16_sync.sh | bash
set -euo pipefail
D="$HOME/projects/crypto_rl"
R="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
mkdir -p "$D/src/rl_curriculum" "$D/tests/route_c_stage2_6_1" "$D/stage2_6_1_runner"
find "$R/stage2_6_1/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/src/rl_curriculum/$(basename "$f")"
done
find "$R/stage2_6_1/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/tests/route_c_stage2_6_1/$(basename "$f")"
done
# R16 变更:runner 执行面同样同步到 WSL 本地文件系统(§4.3 正式
# 协调限定已验证本地 fs;不再从 /mnt/e drvfs 执行 shell/python)
find "$R/stage2_6_1/runner" -maxdepth 1 \( -name '*.sh' -o -name '*.py' \) | while read -r f; do
  tr -d '\r' < "$f" > "$D/stage2_6_1_runner/$(basename "$f")"
  chmod +x "$D/stage2_6_1_runner/$(basename "$f")" 2>/dev/null || true
done
mkdir -p "$D/artifacts/route_c_stage2_6_1_repair16"
echo "r16_sync: done (src+tests+runner -> $D)"
