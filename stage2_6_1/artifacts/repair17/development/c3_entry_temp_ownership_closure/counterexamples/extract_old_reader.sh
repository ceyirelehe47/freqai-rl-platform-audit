#!/usr/bin/env bash
# 提取 HEAD(24eaa81) 的旧 reader blob 到 /tmp,跑阶段一反例。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
CE="$DEV/c3_entry_temp_ownership_closure/counterexamples"
OLD_DIR=/tmp/c3eto_old_reader_v5
mkdir -p "$OLD_DIR"
git -C "$REPO" cat-file blob 93d0172b6428b1710ebc21900247473b5a4d3e64 \
  > "$OLD_DIR/r17_c3_engineering_slice.py"
mkdir -p "$OLD_DIR/runner"
mv "$OLD_DIR/r17_c3_engineering_slice.py" "$OLD_DIR/runner/"
# src 解析:脚本用 reader.parent.parent/src 定位权威模块;借用发布树
ln -sfn "$REPO/stage2_6_1/src" "$OLD_DIR/src"
sha256sum "$OLD_DIR/runner/r17_c3_engineering_slice.py"
tr -d '\r' < "$CE/run_ce_v5.sh" | bash -s -- \
  "$OLD_DIR/runner/r17_c3_engineering_slice.py" \
  "$CE/old_reader_counterexamples_v5.json"
