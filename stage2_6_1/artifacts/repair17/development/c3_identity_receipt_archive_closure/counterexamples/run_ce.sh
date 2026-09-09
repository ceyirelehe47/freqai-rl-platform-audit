#!/bin/bash
set -euo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
mkdir -p /home/cryptorl/tmp_r17irac_ce
python /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_identity_receipt_archive_closure/counterexamples/make_counterexamples.py
