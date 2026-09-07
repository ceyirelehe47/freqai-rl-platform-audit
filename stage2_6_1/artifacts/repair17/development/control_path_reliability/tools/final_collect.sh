#!/usr/bin/env bash
set -uo pipefail
RD=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/control_path_reliability/full_regression/runs/final_20260907T013347
echo "== junit =="
python3 -c "
import xml.etree.ElementTree as ET
r = ET.parse('$RD/junit.xml').getroot()
s = r.find('testsuite') if r.tag == 'testsuites' else r
tot = int(s.get('tests', 0)); fail = int(s.get('failures', 0)); err = int(s.get('errors', 0)); sk = int(s.get('skipped', 0))
print(f'tests={tot} failures={fail} errors={err} skipped={sk} passed={tot-fail-err-sk}')
"
echo "== summary 关键字段 =="
python3 -c "
import json
s = json.load(open('$RD/summary.json'))
print('business rc:', s['business']['rc'])
print('incidents:', len(s['incidents']), 'stops:', s['stop_requested_reasons'])
print('admission:', s.get('admission'))
print('io:', s.get('io'))
print('coverage:', {k: s['coverage'][k] for k in ('win_parse_errors','win_invalid_samples','guest_invalid_samples','telemetry_capped','stdout_failures','log_failures')})
print('telemetry_bytes:', s['telemetry_bytes'])
rr = json.load(open('$RD/run_record.json'))
print('evidence_complete:', rr['evidence_complete'], 'finalized:', rr['finalized'])
print('roles:', [(r['role'], r['status']) for r in rr['required']])
"
echo "== 资源复算 =="
python3 /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/supervision_closure/tools/_recompute_stats.py "$RD" 2>/dev/null | head -3
