#!/usr/bin/env bash
# [新执行 2026-09-10] R17 原生采样器证据补交:新执行编排器。
# 七项全部为只读复验或作用于自建副本/work_pkg 的负例,输出只落本目录;
# originals/、runs/ 既有目录、full2_pkg/copy_root 原件位置均不被写入。
# 每项的命令、stdout、stderr、rc 分目录保存(rc.txt 为该项脚本退出码)。
set -u
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
NEW=$BASE/native_sampler_validation_delivery/new_executions_20260910

for item in 01_full2_wrapper_rerun 02_r3_audit_only_rerun 03_d3_rerun \
            04_pkg_cold_positive_rerun 05_pkg_negatives \
            06_post_seal_observation 07_archive_integrity; do
  echo "=== RUN $item start=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  bash "$NEW/$item/cmd.sh" > "$NEW/$item/stdout.log" 2> "$NEW/$item/stderr.log"
  RC=$?
  echo "$RC" > "$NEW/$item/rc.txt"
  echo "=== $item RC=$RC end=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
done
echo ALL_ITEMS_EXECUTED
