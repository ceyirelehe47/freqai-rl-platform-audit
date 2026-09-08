#!/usr/bin/env bash
# R17 C3 证据轮:稳定候选全量启动 wrapper(受监护;R17_RUN_DIR 预指定
# 使 junit 物理落在 run 目录内——run_record 必需集合全相对路径,
# build/冷读可完整组包;E01 同 run 绑定)。外层 rc 用无管道重定向捕获。
set -uo pipefail
RUN_DIR=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eg_full_20260908
LOGROOT=/mnt/f/trading/r17c3eg_dev
if [ -e "$RUN_DIR" ]; then
  echo "FATAL: run 目录已存在(一次性合同): $RUN_DIR" >&2
  exit 2
fi
mkdir -p "$LOGROOT/full_run"
export R17_RUN_DIR="$RUN_DIR"
cd /home/cryptorl/projects/crypto_rl
bash /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh \
  pytest --max-seconds 3600 -- \
  bash /home/cryptorl/r17c3eg_dev/full_run_ordered.sh \
  --junitxml="$RUN_DIR/junit.xml" \
  > "$LOGROOT/full_run/entry_stdout.log" 2>&1
RC=$?
echo "OUTER_RC=$RC" > "$LOGROOT/full_run/outer_rc.txt"
echo "OUTER_RC=$RC"
exit $RC
