#!/usr/bin/env bash
# 稳定候选全量(R17 系先跑排序;与 c3rdd/c3irac full 同款)。
set -euo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
R=tests/route_c_stage2_6_1
R17="$(ls "$R"/test_curriculum261_r17_*.py | sort | tr '\n' ' ')"
REST="$(ls "$R"/test_*.py | grep -v '/test_curriculum261_r17_' | sort | tr '\n' ' ')"
# shellcheck disable=SC2086
python -m pytest $R17 $REST -q --no-header "$@"
