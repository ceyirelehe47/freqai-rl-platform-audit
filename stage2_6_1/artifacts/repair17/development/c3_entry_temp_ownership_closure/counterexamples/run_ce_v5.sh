#!/usr/bin/env bash
# R17 c3-entry-temp-ownership-closure:阶段一旧行为反例(旧 reader=HEAD
# blob 93d0172b)。stdin 方式执行($0 不可用),路径硬编码。
# 用法: tr -d '\r' < run_ce_v5.sh | bash <reader_path> <out_json>
set -uo pipefail
READER="$1"
OUT="$2"
REPO=/mnt/f/trading/freqai-rl-audit
DEV="$REPO/stage2_6_1/artifacts/repair17/development"
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
WORK=$(mktemp -d /tmp/c3eto_ce_v5.XXXXXX)
trap 'rm -rf "$WORK"' EXIT

ORIG="$DEV/c3_evidence_generation_slice/engineering_slice"
P52="$DEV/blocker_diagnosis/runs/20260906T134324Z_1475/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json"

"$PY" "$DEV/c3_entry_temp_ownership_closure/counterexamples/make_old_counterexamples_v5.py" \
  --reader "$READER" --orig-slice "$ORIG" --p52 "$P52" --out "$OUT"
echo "CE_RC=$?"
