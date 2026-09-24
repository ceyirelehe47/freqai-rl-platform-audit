#!/bin/bash
# R21:发布仓库(F:/trading/freqai-rl-audit) -> WSL 部署树
# (~/projects/crypto_rl)。CR 字节剥离(与 r12_sync 同规则)。
# 用法(WSL 内): tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r21_sync.sh | bash
set -euo pipefail
REPO="${RELEASE_REPO:-/mnt/f/trading/freqai-rl-audit}"
D="$HOME/projects/crypto_rl"

[ -d "$REPO/stage2_6_1/src/rl_curriculum" ] || { echo "repo 不存在: $REPO"; exit 1; }

mkdir -p "$D/src/rl_curriculum" "$D/tests/route_c_stage2_6_1" "$D/stage2_6_1_runner"

# 1) 本轮变更的 src 模块(substance v3)
tr -d '\r' < "$REPO/stage2_6_1/src/rl_curriculum/curriculum261_r17_admission_substance.py" \
  > "$D/src/rl_curriculum/curriculum261_r17_admission_substance.py"

# 2) runner(v3 执行器;签发器/闸门未变,一并重放保证一致)
tr -d '\r' < "$REPO/stage2_6_1/runner/r21_full_collection_regression.py" \
  > "$D/stage2_6_1_runner/r21_full_collection_regression.py"
tr -d '\r' < "$REPO/stage2_6_1/runner/r17_admission_issue.py" \
  > "$D/stage2_6_1_runner/r17_admission_issue.py"

# 3) 测试(v3 支撑 + substance 测试 + 监护/r18 消费方)
for f in conftest.py \
         r17_admission_substance_test_support.py \
         test_curriculum261_r17_admission_substance.py \
         test_curriculum261_r17_supervision_unit.py \
         test_r18_launch_behavioral.py; do
  tr -d '\r' < "$REPO/stage2_6_1/tests/route_c_stage2_6_1/$f" \
    > "$D/tests/route_c_stage2_6_1/$f"
done

echo "r21_sync: done (substance v3 + executor + tests -> $D)"
