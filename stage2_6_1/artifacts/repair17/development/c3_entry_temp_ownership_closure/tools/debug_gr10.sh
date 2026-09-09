#!/usr/bin/env bash
# 单跑 R10/G01 看 traceback,定位环境差异。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd "$REPO/stage2_6_1"
python -m pytest "tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py::TestR10NegativeExitInjection::test_r10_real_rejection_still_zero" "tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py::TestG01DeclaredCoordinates::test_g01_full_slice_all_requests_kept" -q --no-header 2>&1 | grep -v "^$" | head -60
