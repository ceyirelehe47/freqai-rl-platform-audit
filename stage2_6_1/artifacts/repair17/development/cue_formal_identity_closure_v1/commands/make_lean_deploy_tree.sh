#!/bin/bash
set -euo pipefail
# 全新精简部署投影树(RouteC_CueAudit_FormalIdentityClosure_v1 CI09):
# FR2 口径 = r21 在干净投影树跑(P3);crypto_rl 已积累 27G .regression_state,
# 使 runtime_closure RD 夹具(整树复制 deploy root)每测试 29G×10 触发
# 300G 存储天花板。建 crypto_rl_cue_ci 只含套件所需面。
SRC_TREE="$HOME/projects/crypto_rl"
DST="$HOME/projects/crypto_rl_cue_ci"
R="/mnt/f/trading/freqai-rl-audit"
rm -rf "$DST"
mkdir -p "$DST"
# src/tests/runner 从仓库同步(CR 剥离,LF;与 qprod_sync 同口径)
mkdir -p "$DST/src/rl_curriculum" "$DST/tests/route_c_stage2_6_1" "$DST/tests/route_c_stage2_6_2" "$DST/stage2_6_1_runner"
find "$R/stage2_6_1/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$DST/src/rl_curriculum/$(basename "$f")"; done
find "$R/stage2_6_2/src" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$DST/src/rl_curriculum/$(basename "$f")"; done
find "$R/stage2_6_1/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$DST/tests/route_c_stage2_6_1/$(basename "$f")"; done
find "$R/stage2_6_2/tests" -name '*.py' | while read -r f; do
  tr -d '\r' < "$f" > "$DST/tests/route_c_stage2_6_2/$(basename "$f")"; done
find "$R/stage2_6_1/runner" -maxdepth 1 \( -name '*.sh' -o -name '*.py' \) | while read -r f; do
  tr -d '\r' < "$f" > "$DST/stage2_6_1_runner/$(basename "$f")"
  chmod +x "$DST/stage2_6_1_runner/$(basename "$f")" 2>/dev/null || true; done
# runtime_closure 夹具自 old_p 绝对路径读取的已接受原件(crypto_rl 原树不动)
for rel in "user_data/strategies/RouteCStrategy.py" "requirements-lock.txt" \
           "environment.yml" "activate-freqtrade.sh" \
           "experiments/freqai_rl_stage2_5_2a/runtime/config_stage252a-rc-e9b373b3c9_smoke-reload.json"; do
  mkdir -p "$DST/$(dirname "$rel")"
  cp "$SRC_TREE/$rel" "$DST/$rel"
done
echo "tree_ready: $DST"
du -xsh "$DST"
