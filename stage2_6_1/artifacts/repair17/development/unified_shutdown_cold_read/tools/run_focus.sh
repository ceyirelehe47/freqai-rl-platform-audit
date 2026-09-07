#!/usr/bin/env bash
# 本轮专项:5 个 R17 测试文件(read_signal/unified_shutdown/cold_copy/
# result_seal/supervision + control_path 的 t14 系)串行。
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1
timeout 2400 python -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_r17_read_signal_unit.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_unified_shutdown_unit.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_cold_copy_unit.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_result_seal_unit.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_supervision_unit.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_control_path_unit.py \
  -q 2>&1 | tail -4
