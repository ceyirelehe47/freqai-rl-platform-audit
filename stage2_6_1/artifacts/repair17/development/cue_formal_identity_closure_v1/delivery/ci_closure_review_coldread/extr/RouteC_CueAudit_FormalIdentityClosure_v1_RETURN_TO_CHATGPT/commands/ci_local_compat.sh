#!/bin/bash
# 局部兼容快验:cue/coordinate/formal/runtime 相邻面
set -u
EV=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/cue_formal_identity_closure_v1/commands
cd /home/cryptorl/projects/crypto_rl || exit 96
export PYTHONDONTWRITEBYTECODE=1
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_r10_cue_contract.py \
  tests/route_c_stage2_6_1/test_curriculum261_r9_cue_contract.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_coordinate.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_formal_repair.py \
  tests/route_c_stage2_6_1/test_curriculum261_qaf_v3_runtime_closure.py \
  tests/route_c_stage2_6_1/test_curriculum261_r17_cue_formal_identity.py \
  tests/route_c_stage2_6_1/test_qaf_child_watcher_originals.py \
  --junitxml="$EV/CI_local_compat.junit.xml" -q \
  > "$EV/CI_local_compat.stdout.log" 2> "$EV/CI_local_compat.stderr.log"
echo $? > "$EV/CI_local_compat.rc.txt"
tail -3 "$EV/CI_local_compat.stdout.log" > "$EV/CI_local_compat.done.txt"
