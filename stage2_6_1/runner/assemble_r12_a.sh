#!/usr/bin/env bash
# R12 Commit A 组装:WSL 工程 artifacts -> 发布仓库
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair12"
DST="$REPO/stage2_6_1/artifacts/repair12"

cd "$REPO"
git checkout route-c-stage2-6-1-repair12

# 1) 确定性矩阵
mkdir -p "$DST/determinism"
cp "$ART"/determinism/*.json "$DST/determinism/"

# 2) 两次 cold shadow + 比较
mkdir -p "$DST/shadow"
cp -r "$ART"/shadow/A "$ART"/shadow/B "$DST/shadow/"
cp "$ART"/shadow/shadow_two_cold_runs_comparison.json "$DST/shadow/"

# 3) preplan 工程 + rehearsal
mkdir -p "$DST/preplan"
cp "$ART"/preplan/*.json "$ART"/preplan/*.jsonl "$DST/preplan/" 2>/dev/null || cp "$ART"/preplan/*.json "$DST/preplan/"
cp "$ART"/preplan_engineering_smoke.json "$DST/" 2>/dev/null || true
cp "$ART"/preplan_full_pipeline_rehearsal.json "$DST/" 2>/dev/null || true

# 4) release rehearsal / supervised rehearsal
cp "$ART"/pre_freeze_release_rehearsal.json "$DST/" 2>/dev/null || true
cp "$ART"/full_supervised_release_rehearsal.json "$DST/"
cp "$ART"/full_supervised_rehearsal_main.json "$DST/" 2>/dev/null || true
cp "$ART"/full_supervised_rehearsal_holdout.json "$DST/" 2>/dev/null || true

# 5) raw logs 占位(工程命令输出)
mkdir -p "$DST/raw_logs"

echo "assemble_r12_a: done -> $DST"
