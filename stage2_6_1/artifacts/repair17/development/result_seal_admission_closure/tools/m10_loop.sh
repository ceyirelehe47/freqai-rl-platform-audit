#!/usr/bin/env bash
# m10 稳定性验证(N 次连跑)
set -u
N="${1:-12}"
cd ~/projects/crypto_rl || exit 1
source activate-freqtrade.sh >/dev/null 2>&1 || true
fails=0
for i in $(seq 1 "$N"); do
  python3 -m pytest \
    tests/route_c_stage2_6_1/test_curriculum261_r17_supervision_unit.py::TestSupervisorE2E::test_m10_critical_stops_business_without_agent \
    -q --no-header -p no:cacheprovider --tb=no > /tmp/m10_run.txt 2>&1
  rc=$?
  tail -1 /tmp/m10_run.txt | tr -d "\n"
  echo " (rc=$rc)"
  [ "$rc" -ne 0 ] && fails=$((fails + 1))
done
echo "FAILS=$fails/$N"
