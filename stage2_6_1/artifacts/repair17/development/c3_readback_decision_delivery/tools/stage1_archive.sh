#!/usr/bin/env bash
# 阶段一证据归档:探针 JSON + 各 case stdout/stderr → 交付目录 counterexamples/stage1/
set -euo pipefail
DEST=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery/counterexamples/stage1
SRC=/home/cryptorl/r17rdd_dev
mkdir -p "$DEST"
cp "$SRC/stage1_old_reader_probes.json" "$DEST/"
for c in health r02_rows_reordered r03a_p52_file_deleted \
         r03b_recipe_negative_removed r04_p52_tampered_accepted \
         r05_cross_coord_detail; do
  cp "$SRC/rc_$c.stdout" "$DEST/$c.stdout"
  cp "$SRC/rc_$c.stderr" "$DEST/$c.stderr"
done
ls -la "$DEST"
