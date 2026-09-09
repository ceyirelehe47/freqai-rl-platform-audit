#!/usr/bin/env bash
# 提交前事实核对:全量 run_record/部署树一致性/关键回执数字。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
D="$REPO/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery"
RDIR="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3rdd_full_20260909"

echo "=== run_record ==="
python3 -c "
import json
rr = json.load(open('$RDIR/run_record.json', encoding='utf-8'))
print('finalized:', rr['finalized'], '| evidence_complete:', rr['evidence_complete'], '| business.rc:', rr['business']['rc'], '| control_failures:', rr.get('control_failures'))
"
echo "=== full stdout 末行(passed 数) ==="
grep -E "passed|failed" "$RDIR/business/stdout.log" | tail -1
echo "=== 部署树 vs 工作树一致性 ==="
for f in stage2_6_1_runner/r17_c3_engineering_slice.py stage2_6_1_runner/r17_verify_delivery.py; do
  a=$(sha256sum ~/projects/crypto_rl/$f | cut -d' ' -f1)
  b=$(sha256sum $REPO/stage2_6_1/runner/$(basename $f) | cut -d' ' -f1)
  [ "$a" = "$b" ] && echo "OK  $(basename $f) $a" || echo "DIFF $(basename $f) deploy=$a wt=$b"
done
t_a=$(sha256sum ~/projects/crypto_rl/tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py | cut -d' ' -f1)
t_b=$(sha256sum $REPO/stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_c3_slice_unit.py | cut -d' ' -f1)
[ "$t_a" = "$t_b" ] && echo "OK  test_curriculum261_r17_c3_slice_unit.py $t_a" || echo "DIFF test"
echo "=== 语义正例/冷读/汇总回执 ==="
python3 -c "
import json
s = json.load(open('$D/verification/receipts/semantic_health.json', encoding='utf-8'))
print('semantic_health verdict:', s['readback_verdict'], '| reader_sha256:', s['reader_sha256'][:16])
c = json.load(open('$D/verification/cold_read/cold_read_report.json', encoding='utf-8'))
print('c3 cold rc:', c['rc'])
f = json.load(open('$D/verification/full_cold_read/full_cold_read_report.json', encoding='utf-8'))
print('full cold rc:', f['rc'])
a = json.load(open('$D/verification/aggregate/aggregate_report.json', encoding='utf-8'))
print('aggregate:', a['aggregate_verdict'])
"
