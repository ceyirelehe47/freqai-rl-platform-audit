#!/bin/bash
# R21:发布仓库(F:/trading/freqai-rl-audit) -> WSL 部署树
# (~/projects/crypto_rl)。CR 字节剥离(与 r12_sync 同规则)。
# 用法(WSL 内): tr -d '\r' < /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r21_sync.sh | bash
# RELEASE_REPO/RELEASE_DEST 可覆盖(隔离同步验证测试用临时目录)。
set -euo pipefail
REPO="${RELEASE_REPO:-/mnt/f/trading/freqai-rl-audit}"
D="${RELEASE_DEST:-$HOME/projects/crypto_rl}"
# 位置参数优先(env 变量经 wsl.exe/bash.exe 启动不透传,见 #54):
if [ "$#" -ge 1 ] && [ -n "$1" ]; then REPO="$1"; fi
if [ "$#" -ge 2 ] && [ -n "$2" ]; then D="$2"; fi

mkdir -p "$D/src/rl_curriculum" "$D/tests/route_c_stage2_6_1" "$D/stage2_6_1_runner"

# 1) src 面:候选全体 rl_curriculum 模块(v3 import_surface 要求
#    部署 src 与候选 Git blob 逐成员 CR 规范化字节一致;漏同步
#    会在全量自验 fail-closed——见 attempt4_deploy_drift_reject)
for f in "$REPO"/stage2_6_1/src/rl_curriculum/*.py; do
  tr -d '\r' < "$f" > "$D/src/rl_curriculum/$(basename "$f")"
done
# 2) runner(v4 执行器 + in-process 审计器;签发器一并重放保证一致。
#    v4 要求部署 stage2_6_1_runner 的 executor/auditor 字节与候选
#    blob 一致(record executor_face 绑定))
for f in r21_full_collection_regression.py \
         r21_collection_auditor.py \
         r17_admission_issue.py; do
  tr -d '\r' < "$REPO/stage2_6_1/runner/$f" > "$D/stage2_6_1_runner/$f"
done

# 3) 测试(v3 支撑 + substance 测试 + 监护/r18 消费方)
for f in conftest.py \
         r17_admission_substance_test_support.py \
         test_curriculum261_r17_admission_substance.py \
         test_curriculum261_r20_design_math.py \
         test_curriculum261_r17_supervision_unit.py \
         test_r18_launch_behavioral.py; do
  tr -d '\r' < "$REPO/stage2_6_1/tests/route_c_stage2_6_1/$f" \
    > "$D/tests/route_c_stage2_6_1/$f"
done

# 4) report(C 设计计算被测对象;math 测试 import 该脚本与 JSON)
mkdir -p "$D/report"
tr -d '\r' < "$REPO/stage2_6_1/report/r20_design_calc_v3.py" \
  > "$D/report/r20_design_calc_v3.py"
tr -d '\r' < "$REPO/stage2_6_1/report/r20_design_calc_v3.json" \
  > "$D/report/r20_design_calc_v3.json"
tr -d '\r' < "$REPO/stage2_6_1/report/route_c_stage2_6_1_r20_research_design_v3.md" \
  > "$D/report/route_c_stage2_6_1_r20_research_design_v3.md"

echo "r21_sync: done (substance v4 + executor + auditor + tests -> $D)"
