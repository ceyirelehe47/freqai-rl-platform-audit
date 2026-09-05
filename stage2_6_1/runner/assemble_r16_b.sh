#!/usr/bin/env bash
# R16 Commit B 组装:正式执行 artifacts -> 发布仓库(严格 results-only)
# 1) 全部正式链 raw logs(manifest + 每步 log/err + 启动证据)
# 2) 正式 artifacts 顶层文件(含 workflow plan/chain result)
# 3) 权威 execution journal + exposure 投影
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair16"
DST="$REPO/stage2_6_1/artifacts/repair16"

cd "$REPO"
git checkout route-c-stage2-6-1-repair16 2>/dev/null || true

mkdir -p "$DST/raw_logs"

# 1) 正式链产物(顶层 json/jsonl/txt)
for f in "$ART"/*.json "$ART"/*.jsonl "$ART"/*.txt; do
  [ -f "$f" ] && cp "$f" "$DST/" || true
done

# 2) 全部 raw logs(每步 .log/.err + manifest + chain/fail/启动日志)
for f in "$SRC/r16_formal_logs"/*.log \
         "$SRC/r16_formal_logs"/*.err \
         "$SRC/r16_formal_logs"/*.jsonl; do
  [ -f "$f" ] && cp "$f" "$DST/raw_logs/" || true
done
for f in "$SRC/route_c_stage2_6_1_repair16_chain_logs"/*.log \
         "$SRC/route_c_stage2_6_1_repair16_chain_logs"/*.err; do
  [ -f "$f" ] && {
    mkdir -p "$DST/raw_logs/chain"
    cp "$f" "$DST/raw_logs/chain/"
  } || true
done

# 3) rehearsal 与工程产物目录
for d in real_artifact_rehearsal determinism test_evidence; do
  if [ -d "$ART/$d" ]; then
    mkdir -p "$DST/$d"
    cp -r "$ART/$d/." "$DST/$d/"
  fi
done

echo "assemble_r16_b: done (含全部 raw logs + execution journal)"
