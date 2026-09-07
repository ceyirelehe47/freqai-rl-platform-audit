#!/usr/bin/env bash
d=$(ls -dt /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/e2e_* 2>/dev/null | head -1)
echo "RUN=$d"
python3 -c "
import json
r = json.load(open('$d/run_record.json'))
print('missing:', [(x['role'], x['status']) for x in r['required'] if x['status'] != 'present'])
print('io:', r.get('io'))
s = json.load(open('$d/summary.json'))
print('biz_rc:', s['business']['rc'], 'stops:', s['stop_requested_reasons'])
"
