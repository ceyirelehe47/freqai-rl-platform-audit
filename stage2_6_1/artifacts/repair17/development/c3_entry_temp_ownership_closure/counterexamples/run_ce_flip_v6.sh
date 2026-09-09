#!/usr/bin/env bash
# R17 c3-entry-temp-ownership-closure(交接包路线):
# 阶段一旧反例 v6 重跑(旧 reader blob 93d0172b→9869ea6a) + 交接包
# 候选(7a5ccc19)同脚本翻转。stdin 方式执行($0 不可用),路径硬编码。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
CE="$DEV/c3_entry_temp_ownership_closure/counterexamples"
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python

# 1) 旧 reader 提取(blob 93d0172b = 字节 sha256 9869ea6c)
OLD_DIR=/tmp/c3eto_old_reader_v6
rm -rf "$OLD_DIR"; mkdir -p "$OLD_DIR/runner"
git -C "$REPO" cat-file blob 93d0172b6428b1710ebc21900247473b5a4d3e64 \
  > "$OLD_DIR/runner/r17_c3_engineering_slice.py"
ln -sfn "$REPO/stage2_6_1/src" "$OLD_DIR/src"
OLD_SHA=$(sha256sum "$OLD_DIR/runner/r17_c3_engineering_slice.py" | cut -d' ' -f1)
echo "old_reader_sha256=$OLD_SHA"
[ "$OLD_SHA" = "9869ea6ccc319e7ebf6ad85cf3b70e669fcf59baeb11e46dc730aa8198853886" ] \
  || { echo "FATAL: 旧 reader 身份漂移" >&2; exit 2; }

# 2) 阶段一反例(旧 reader 三缺陷复现)→ v6 名输出
tr -d '\r' < "$CE/run_ce_v5.sh" | bash -s -- \
  "$OLD_DIR/runner/r17_c3_engineering_slice.py" \
  "$CE/old_reader_counterexamples_v6.json"
CE_RC=$?
echo "CE_RC=$CE_RC"

# 3) 交接包候选编译 + 同脚本翻转
CAND="$REPO/stage2_6_1/runner/r17_c3_engineering_slice.py"
"$PY" -m py_compile "$CAND" || { echo "FATAL: 候选编译失败" >&2; exit 2; }
tr -d '\r' < "$CE/run_ce_v5.sh" | bash -s -- \
  "$CAND" "$CE/fixed_reader_flip_v6.json"
FLIP_RC=$?
echo "FLIP_RC=$FLIP_RC"
