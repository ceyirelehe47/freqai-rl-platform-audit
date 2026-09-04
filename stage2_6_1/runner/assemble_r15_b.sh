#!/usr/bin/env bash
# R15 Commit B 组装:正式执行 artifacts -> 发布仓库(严格 results-only)
# 1) 全部正式链 raw logs(§十-2 manifest + 每步 log/err)进 raw_logs/
# 2) 正式 artifacts 顶层文件(含 r15_workflow_plan_formal.json 与
#    r15_chain_result.json——权威编排的可复核证据)
# 3) raw log 完整性机器检查在链尾由 verify-formal-logs 步执行
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair15"
DST="$REPO/stage2_6_1/artifacts/repair15"

cd "$REPO"
git checkout route-c-stage2-6-1-repair15 2>/dev/null || true

mkdir -p "$DST/raw_logs"

# 1) 工程证据目录(determinism/preplan/rehearsal)由 assemble_r15_a 组装;
#    本脚本只拷正式链产物(顶层 json/jsonl/txt)
for f in "$ART"/*.json "$ART"/*.jsonl "$ART"/*.txt; do
  [ -f "$f" ] && cp "$f" "$DST/" || true
done

# 2) 全部 raw logs(每步 .log/.err + manifest + chain/fail 日志)
for f in "$SRC/r15_formal_logs"/*.log \
         "$SRC/r15_formal_logs"/*.err \
         "$SRC/r15_formal_logs"/r15_formal_log_manifest.jsonl; do
  [ -f "$f" ] && cp "$f" "$DST/raw_logs/" || true
done
# chain 执行器自身的日志(log_dir = <ART>_chain_logs)
for f in "$SRC/route_c_stage2_6_1_repair15_chain_logs"/*.log \
         "$SRC/route_c_stage2_6_1_repair15_chain_logs"/*.err; do
  [ -f "$f" ] && cp "$f" "$DST/raw_logs/chain/" 2>/dev/null || {
    mkdir -p "$DST/raw_logs/chain"; cp "$f" "$DST/raw_logs/chain/"; } || true
done

# 3) rehearsal 与工程产物目录
for d in real_artifact_rehearsal determinism preplan shadow; do
  if [ -d "$ART/$d" ]; then
    mkdir -p "$DST/$d"
    cp -r "$ART/$d/." "$DST/$d/"
  fi
done

echo "assemble_r15_b: done (含全部 raw logs)"
