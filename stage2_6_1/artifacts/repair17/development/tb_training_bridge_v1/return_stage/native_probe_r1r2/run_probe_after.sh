#!/bin/bash
set -uo pipefail
OUT=/mnt/f/trading/tmp_probe_native/out_c6
rm -rf "$OUT"
cd /home/cryptorl/projects/crypto_rl
source activate-freqtrade.sh >/dev/null 2>&1 || true
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  /mnt/f/trading/trading/goal_incoming/RouteC_TrainingBridge_FinalReview_2575deb2/probes/reproduce_remaining_native.py \
  --project /home/cryptorl/projects/crypto_rl \
  --repo /mnt/f/trading/freqai-rl-audit \
  --return-root /mnt/f/trading/tmp_probe_native/ret/RouteC_QualifiedInput_TrainingBridge_v1_RETURN \
  --out "$OUT" > /mnt/f/trading/tmp_probe_native/probe_c6_stdout.txt 2> /mnt/f/trading/tmp_probe_native/probe_c6_stderr.txt
rc=$?
echo "probe_rc=$rc"
tail -30 /mnt/f/trading/tmp_probe_native/probe_c6_stdout.txt
