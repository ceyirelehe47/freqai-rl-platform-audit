#!/usr/bin/env bash
# 查看 run e verification 状态与冷读工作根现场。
set -uo pipefail
VER=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery/verification
echo "=== verification/ ==="; ls "$VER" 2>/dev/null
echo "=== build/finalize verdict ==="
python3 -c "
import json
b = json.load(open('$VER/build_report.json', encoding='utf-8'))
print('build:', b['build_verdict'], b['n_problems'])
f = json.load(open('$VER/finalize_report.json', encoding='utf-8'))
print('finalize verifier_rc:', f['verifier_rc'], '| roles:', f['n_required_roles_appended'])
" 2>&1
echo "=== package/ ==="; ls "$VER/package" "$VER/package/payload" 2>/dev/null
echo "=== manifest 行数 ==="; wc -l "$VER/package/manifest.jsonl" 2>/dev/null
echo "=== /home/cryptorl/r17rdd_cold ==="; ls /home/cryptorl/r17rdd_cold 2>/dev/null || echo "不存在"
echo "=== cold receipts ==="; ls "$VER/cold_read" 2>/dev/null || echo "无"
