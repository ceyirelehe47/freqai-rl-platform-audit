#!/usr/bin/env bash
# R16 Commit A 组装:WSL 工程 artifacts -> 发布仓库
# (实现冻结点:执行治理内核 + 所有权生命周期 + 授权矩阵 +
#  发布入口一致性 + bootstrap 边界 + 全部工程证据)
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair16"
DST="$REPO/stage2_6_1/artifacts/repair16"

cd "$REPO"
git checkout route-c-stage2-6-1-repair16 2>/dev/null || true

# 1) 确定性矩阵(冻结前工程命令)
mkdir -p "$DST/determinism"
cp "$ART"/determinism/*.json "$DST/determinism/" 2>/dev/null || true

# 2) GateTopologyReconciliation-v2(任何正式数据前锁定)
for f in gate_topology_reconciliation.json \
         gate_topology_reconciliation_digest.txt; do
  [ -f "$ART/$f" ] && cp "$ART/$f" "$DST/" || true
done

# 3) 测试证据(JUnit XML + 完整输出 + 环境身份)
mkdir -p "$DST/test_evidence"
for f in "$SRC"/r16_test_evidence/*; do
  [ -f "$f" ] && cp "$f" "$DST/test_evidence/" || true
done

# 4) 发布布局 rehearsal(real-artifact round-trip:同一 execute_
#    workflow_chain_r16;含 plan/chain 记录/manifest/日志)
mkdir -p "$DST/real_artifact_rehearsal"
if [ -d "$ART/real_artifact_rehearsal" ]; then
  cp -r "$ART/real_artifact_rehearsal/." "$DST/real_artifact_rehearsal/"
fi

echo "assemble_r16_a: done -> $DST"
