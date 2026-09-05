#!/usr/bin/env bash
# R17 Commit B 组包:manifest 驱动 + 严格校验(F4 闭合)。
# 与 R16 的差异:不再从猜测目录 glob 复制(!! R16 从少一层
# artifacts/ 的路径复制并 || true 静默跳过);一切源文件来自
# run manifest 登记的绝对路径,逐文件 sha256/bytes 校验。
set -euo pipefail

PROJECT_ROOT="${R17_PROJECT_ROOT:-$HOME/projects/crypto_rl}"
SRC="$PROJECT_ROOT"
ART="$SRC/artifacts/route_c_stage2_6_1_repair17"
RUNNER_DIR="$SRC/stage2_6_1_runner"
DST_PARENT="${R17_DELIVERY_PARENT:-$SRC/r17_delivery}"
DST="$DST_PARENT/repair17_release"

RELEASE_REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
B_STAGE="$RELEASE_REPO/stage2_6_1/artifacts/repair17"

MANIFEST="$ART/r17_formal_log_manifest.jsonl"
if [ ! -f "$MANIFEST" ]; then
  echo "FATAL: run manifest 不存在:$MANIFEST" >&2
  echo "(R16 组包缺陷反例:正是静默跳过缺失 manifest 导致交付不完整)" >&2
  exit 1
fi

# ---- 组包(严格;任何缺失/哈希不符 → 非零退出) ----
# extras 逐项追加(存在才登记;不存在 = 不交付,由 manifest 覆盖
# 的必需文件承担完整性责任):
EXTRA_ARGS=()
for f in "$ART/r16_failure_binding.json" \
         "$ART/r17_chain_result.json" \
         "$ART/r17_bootstrap_accepted.json" \
         "$ART/r17_fail_closure_summary.json"; do
  if [ -f "$f" ]; then
    EXTRA_ARGS+=(--extra="$f=formal/$(basename "$f")")
  fi
done
python3 "$RUNNER_DIR/verify_delivery_r17.py" assemble \
  --manifest "$MANIFEST" \
  --delivery-dir "$DST" \
  "${EXTRA_ARGS[@]+${EXTRA_ARGS[@]}}"

# ---- 交付冷读(独立核验;仅依赖交付映射) ----
python3 "$RUNNER_DIR/verify_delivery_r17.py" cold-read \
  --delivery-dir "$DST"

# ---- 同步到发布仓库 B 阶段区(字节一致复制;rsync 不可用时 cp) ----
mkdir -p "$B_STAGE/delivery"
cp -r "$DST/." "$B_STAGE/delivery/"
echo "assemble_r17_b: done -> $B_STAGE/delivery"
