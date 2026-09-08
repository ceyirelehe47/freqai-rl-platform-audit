#!/usr/bin/env bash
# R17 C3 证据轮:三个受监护工程运行(A 诊断重放 / B 八坐标切片 / C readback)。
# 用法(WSL 内): tr -d '\r' < 本文件 | bash
set -uo pipefail

RUNNER=/home/cryptorl/projects/crypto_rl/stage2_6_1_runner
DELIV=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_evidence_generation_slice
ENV_ORIG=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/blocker_diagnosis/runs/20260906T134324Z_1475/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json
SUPERV_ROOT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision
LOGS=/tmp/c3_evidence_runs
mkdir -p "$DELIV/c3_evidence" "$LOGS"

echo "== [A] c3diag: p52 完整重放诊断 v2 =="
R17_RUN_DIR="$SUPERV_ROOT/runs/c3diag_p52_v2_20260908" \
  bash "$RUNNER/r17_monitored_entry.sh" c3diag --max-seconds 900 -- \
  python "$RUNNER/r17_c3_p52_diagnosis.py" \
    --envelope "$ENV_ORIG" \
    --out "$DELIV/c3_evidence/p52_diagnosis_v2.json" \
  > "$LOGS/runA.log" 2>&1
RC_A=$?
echo "runA_rc=$RC_A"
tail -4 "$LOGS/runA.log"

echo "== [B] engineering: 八坐标切片 + p52 负例 =="
R17_RUN_DIR="$SUPERV_ROOT/runs/c3slice_20260908" \
  bash "$RUNNER/r17_monitored_entry.sh" engineering --max-seconds 1800 -- \
  python "$RUNNER/r17_c3_engineering_slice.py" \
    --out-dir "$DELIV/engineering_slice" \
    --p52-negative "$ENV_ORIG" \
  > "$LOGS/runB.log" 2>&1
RC_B=$?
echo "runB_rc=$RC_B"
tail -4 "$LOGS/runB.log"

echo "== [C] engineering: 新进程只读 readback =="
R17_RUN_DIR="$SUPERV_ROOT/runs/c3readback_20260908" \
  bash "$RUNNER/r17_monitored_entry.sh" engineering --max-seconds 600 -- \
  python "$RUNNER/r17_c3_engineering_slice.py" \
    --readback "$DELIV/engineering_slice" \
  > "$LOGS/runC.log" 2>&1
RC_C=$?
echo "runC_rc=$RC_C"
tail -4 "$LOGS/runC.log"

echo "FINAL rcA=$RC_A rcB=$RC_B rcC=$RC_C"
