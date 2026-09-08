#!/usr/bin/env bash
# 稳定候选全量启动 wrapper(受监护;R17_RUN_DIR 预指定使 junit 物理
# 落在 run 目录内——run_record 必需集合全相对路径,build/冷读可完整
# 组包;E03 同 run 绑定)。外层 rc 用无管道重定向捕获(不依赖
# PIPESTATUS)。
set -uo pipefail
RUN_DIR=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/fcid_full_20260908
if [ -e "$RUN_DIR" ]; then
  echo "FATAL: run 目录已存在(一次性合同): $RUN_DIR" >&2
  exit 2
fi
export R17_RUN_DIR="$RUN_DIR"
cd /home/cryptorl/projects/crypto_rl
bash /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh \
  pytest --max-seconds 3600 -- \
  bash /home/cryptorl/r17fc_dev/full_run_ordered.sh \
  --junitxml="$RUN_DIR/junit.xml" \
  > /mnt/f/trading/r17fc_dev/full_run/entry_stdout.log 2>&1
RC=$?
echo "OUTER_RC=$RC" > /mnt/f/trading/r17fc_dev/full_run/outer_rc.txt
echo "OUTER_RC=$RC"
exit $RC
