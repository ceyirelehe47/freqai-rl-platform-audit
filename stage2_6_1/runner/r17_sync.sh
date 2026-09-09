#!/usr/bin/env bash
# R17 开发同步:发布仓库 -> WSL 开发树(逐文件 tr -d CR;LF 保证)。
# 用法(Windows): wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_sync.sh | bash"
# 或(WSL内): tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_sync.sh | bash
set -euo pipefail
D="$HOME/projects/crypto_rl"
R="${RELEASE_REPO:-/mnt/f/trading/freqai-rl-audit}"
mkdir -p "$D/src/rl_curriculum" "$D/tests/route_c_stage2_6_1" "$D/stage2_6_1_runner"
find "$R/stage2_6_1/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/src/rl_curriculum/$(basename "$f")"
done
find "$R/stage2_6_1/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/tests/route_c_stage2_6_1/$(basename "$f")"
done
# runner 执行面同样同步到 WSL 本地文件系统(§8.2:真实 Linux
# checkout;不从 /mnt/f drvfs 执行 shell/python)。
# 原生采样器伴生件(.ps1/.cs)按补丁包 README_AGENT §2.3"部署同步
# 必须覆盖,不能因 .cs 扩展名漏掉"一并入同步面;WSL 侧仅为只读
# 副本(供源码断言测试与部署哈希核对),执行仍走 Windows 侧 runner。
find "$R/stage2_6_1/runner" -maxdepth 1 \( -name '*.sh' -o -name '*.py' -o -name '*.ps1' -o -name '*.cs' \) | while read -r f; do
  tr -d '\r' < "$f" > "$D/stage2_6_1_runner/$(basename "$f")"
  chmod +x "$D/stage2_6_1_runner/$(basename "$f")" 2>/dev/null || true
done
mkdir -p "$D/artifacts/route_c_stage2_6_1_repair17"
echo "r17_sync: done (src+tests+runner -> $D)"
