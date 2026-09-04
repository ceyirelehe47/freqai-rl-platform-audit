#!/usr/bin/env bash
# R14 Commit B 组装:正式执行 artifacts -> 发布仓库(严格 results-only)
# 1) 全部正式链 raw logs(§十-2 manifest + 每步 log/err)进 raw_logs/
# 2) 正式 artifacts 顶层文件
# 3) raw log 完整性机器检查已在链尾执行(r14_formal_log_verification.json)
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair14"
DST="$REPO/stage2_6_1/artifacts/repair14"

cd "$REPO"
git checkout route-c-stage2-6-1-repair14 2>/dev/null || true

mkdir -p "$DST/raw_logs"

# 1) 工程证据目录(determinism/preplan/rehearsal)由 assemble_r14_a 组装;
#    本脚本只拷正式链产物(顶层 json/jsonl/txt)
for f in "$ART"/*.json "$ART"/*.jsonl "$ART"/*.txt; do
  [ -f "$f" ] && cp "$f" "$DST/" || true
done

# 2) 全部 raw logs(每步 .log/.err + manifest + 回归/收尾日志)
for f in "$SRC/r14_formal_logs"/*.log \
         "$SRC/r14_formal_logs"/*.err \
         "$SRC/r14_formal_logs"/r14_formal_log_manifest.jsonl; do
  [ -f "$f" ] && cp "$f" "$DST/raw_logs/" || true
done

# 3) rehearsal 与工程产物目录
for d in real_artifact_rehearsal determinism preplan shadow; do
  if [ -d "$ART/$d" ]; then
    mkdir -p "$DST/$d"
    cp -r "$ART/$d/." "$DST/$d/"
  fi
done

echo "assemble_r14_b: done (含全部 raw logs)"
