#!/usr/bin/env bash
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/control_path_reliability
for run in "$BASE"/t21_alert_reception/run_a_A "$BASE"/t21_alert_reception/run_b_B; do
  echo "== $run =="
  python3 -c "
import json
s = json.load(open('$run/summary.json'))
print('business:', s['business']['rc'], 'stops:', s['stop_requested_reasons'][:1])
print('io:', s['io'])
print('admission:', (s.get('admission') or {}).get('ok'))
inc = s['incidents'][0] if s['incidents'] else {}
print('incident:', inc.get('kind'), inc.get('severity'), 'delivered:', inc.get('delivered_count'))
r = json.load(open('$run/run_record.json'))
print('run_record: evidence_complete=', r['evidence_complete'], 'finalized=', r['finalized'])
alerts = open('$run/alerts/alerts.jsonl').read()
print('alerts_lines:', len(alerts.splitlines()))
print('has stop_requested+sigterm:', '\"event\":\"stop_requested\"' in alerts and '\"event\":\"sigterm_sent\"' in alerts)
"
done
