#!/usr/bin/env bash
set -uo pipefail
D=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery
echo "=== attempt2/ ==="; ls "$D/verification_attempt2" 2>/dev/null
if [ -f "$D/verification_attempt2/build_report.json" ]; then
python3 -c "
import json
b = json.load(open('$D/verification_attempt2/build_report.json', encoding='utf-8'))
print('build:', b['build_verdict'], '| problems:', b['n_problems'])
f = json.load(open('$D/verification_attempt2/finalize_report.json', encoding='utf-8'))
print('finalize verifier_rc:', f['verifier_rc'], '| roles:', f['n_required_roles_appended'])
print('record_rel:', f['record_rel_in_payload'])
"
wc -l "$D/verification_attempt2/package/manifest.jsonl" 2>/dev/null
ls "$D/verification_attempt2/package/payload" 2>/dev/null
fi
echo "=== 旧 attempt1 还在? ==="; ls "$D/verification_attempt1" 2>/dev/null | head -5
echo "=== run 目录清单 ==="; ls /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision/runs/ | grep c3rdd
