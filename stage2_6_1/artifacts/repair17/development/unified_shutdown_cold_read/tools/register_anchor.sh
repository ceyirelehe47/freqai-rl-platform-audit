#!/usr/bin/env bash
# 两段式 git 登记第二段:manifest 已入库后运行(在最终 commit 之前)。
# 用法: tr -d '\r' < register_anchor.sh | bash
set -euo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEL="$REPO/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/delivery_closure"
DEV="$HOME/projects/crypto_rl/stage2_6_1_runner"
# 前置:manifest 已 git add(入 index 即可被 hash-object 校验路径存在)
git -C "$REPO" add \
  "stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/delivery_closure/delivery_manifest_v2.jsonl"
python3 "$DEV/r17_verify_delivery.py" register-git \
  --anchor "$DEL/anchors/final.anchor.json" \
  --repo "$REPO" \
  --commit "$(git -C "$REPO" rev-parse HEAD)" \
  --manifest-repo-path \
  "stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/delivery_closure/delivery_manifest_v2.jsonl"
git -C "$REPO" hash-object "$DEL/delivery_manifest_v2.jsonl" \
  | tee "$DEL/anchors/final.anchor.blob.txt"
echo "register done;anchor 已更新(git blob 见上)"
