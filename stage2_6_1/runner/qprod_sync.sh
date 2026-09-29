#!/usr/bin/env bash
# RouteC_QualificationProducer_Integration_v1 (QProd) 开发同步:
# 发布仓库 -> WSL 部署树(逐文件 tr -d CR;LF 保证;不触碰冻结 pyc)。
# 映射(与 r17_sync/r21 映射一致):
#   stage2_6_1/src/rl_curriculum/*.py  -> $D/src/rl_curriculum/
#   stage2_6_2/src/rl_curriculum/*.py  -> $D/src/rl_curriculum/   (262 面平铺合并)
#   stage2_6_1/tests/**/*.py           -> $D/tests/route_c_stage2_6_1/
#   stage2_6_2/tests/**/*.py           -> $D/tests/route_c_stage2_6_2/
#   stage2_6_1/runner/*.{sh,py}        -> $D/stage2_6_1_runner/
# 用法(Windows): wsl -d CryptoRL-Ubuntu-24.04 -- bash -c "tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/qprod_sync.sh | bash"
set -euo pipefail
D="$HOME/projects/crypto_rl"
R="${RELEASE_REPO:-/mnt/f/trading/freqai-rl-audit}"
mkdir -p "$D/src/rl_curriculum" "$D/tests/route_c_stage2_6_1" \
  "$D/tests/route_c_stage2_6_2" "$D/stage2_6_1_runner"
find "$R/stage2_6_1/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/src/rl_curriculum/$(basename "$f")"
done
find "$R/stage2_6_2/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/src/rl_curriculum/$(basename "$f")"
done
find "$R/stage2_6_1/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/tests/route_c_stage2_6_1/$(basename "$f")"
done
find "$R/stage2_6_2/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$D/tests/route_c_stage2_6_2/$(basename "$f")"
done
find "$R/stage2_6_1/runner" -maxdepth 1 \( -name '*.sh' -o -name '*.py' \) | while read -r f; do
  tr -d '\r' < "$f" > "$D/stage2_6_1_runner/$(basename "$f")"
  chmod +x "$D/stage2_6_1_runner/$(basename "$f")" 2>/dev/null || true
done
echo "qprod_sync: done (261+262 src/tests + runner -> $D)"
