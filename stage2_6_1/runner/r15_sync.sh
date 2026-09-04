#!/usr/bin/env bash
# R15:发布仓库(E:\trading\freqai-rl-audit) -> WSL 开发树(~/projects/crypto_rl)
# 用法(Windows): wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "tr -d '\r' < /mnt/e/trading/freqai-rl-audit/stage2_6_1/runner/r15_sync.sh | bash"
# 或(WSL内): tr -d '\r' < /mnt/e/trading/freqai-rl-audit/stage2_6_1/runner/r15_sync.sh | bash
set -euo pipefail
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
D="$HOME/projects/crypto_rl"

[ -d "$REPO/stage2_6_1/src/rl_curriculum" ] || { echo "repo 不存在: $REPO"; exit 1; }

# 1) 源码(全部 stage2_6_1 源码,含 r14 新模块)
mkdir -p "$D/src/rl_curriculum" "$D/tests/route_c_stage2_6_1"
find "$REPO/stage2_6_1/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/src/rl_curriculum/$(basename "$f")"
done
# api.py 等共享模块直接落在 src/rl_curriculum(与 stage2_6_1/src 结构一致)

# 2) 测试
find "$REPO/stage2_6_1/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/tests/route_c_stage2_6_1/$(basename "$f")"
done

# 3) 2.6.2 共享模块
if [ -d "$REPO/stage2_6_2/src/rl_curriculum" ]; then
  find "$REPO/stage2_6_2/src" -name '*.py' | while read -r f; do
    case "$(basename "$f")" in
      curriculum261_*) continue ;;
    esac
    mkdir -p "$D/src/rl262"
    tr -d '\r' < "$f" > "$D/src/rl262/$(basename "$f")"
  done
fi

mkdir -p "$D/artifacts/route_c_stage2_6_1_repair15"
echo "r15_sync: done (src+tests -> $D)"
