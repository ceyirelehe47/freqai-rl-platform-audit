#!/usr/bin/env bash
# 恢复 run e 成功产物到 verification/;attempt2 保持为 run d 失败现场。
set -uo pipefail
D=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery
echo "=== attempt2/verification(run e 产物?) ==="
ls "$D/verification_attempt2/verification" 2>/dev/null
python3 -c "
import json
f = json.load(open('$D/verification_attempt2/verification/finalize_report.json', encoding='utf-8'))
print('run-e finalize verifier_rc:', f['verifier_rc'], '| roles:', f['n_required_roles_appended'])
print('record_rel:', f.get('record_rel_in_payload'))
" 2>&1
if [ -d "$D/verification_attempt2/verification/package" ]; then
  mv "$D/verification_attempt2/verification" "$D/verification"
  echo "RESTORED -> $D/verification"
  wc -l "$D/verification/package/manifest.jsonl"
  ls "$D/verification/package/payload"
fi
