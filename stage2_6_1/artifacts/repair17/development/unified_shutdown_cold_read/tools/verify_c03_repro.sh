#!/usr/bin/env bash
# 手动核实 C03/C04 失败原因=缺件/篡改检出(非脚本崩溃假绿)。
set -uo pipefail
T=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read
GOOD=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/cold_copies/r17u_supplement_final_140907
rm -rf /tmp/negcheck /tmp/negcheck_r
cp -r "$GOOD" /tmp/negcheck
F=$(cd /tmp/negcheck/payload && find . -type f | sort | head -1)
rm "/tmp/negcheck/payload/$F"
echo "== C03 removed: $F =="
bash "$T/tools/cold_read_isolated.sh" /tmp/negcheck /tmp/negcheck_r >/tmp/negcheck_out.txt 2>&1
echo "exit=$?"
python3 - <<'PYEOF'
import glob, json
receipts = sorted(glob.glob("/tmp/negcheck_r/verify_*/verify_*.json"))
for r in receipts:
    d = json.load(open(r, encoding="utf-8"))
    print("verify receipt:", json.dumps(
        {k: d.get(k) for k in ("rc", "rows", "problems")},
        ensure_ascii=False))
    for pr in (d.get("problems_list") or [])[:4]:
        print("  problem:", str(pr)[:120])
PYEOF
cat /tmp/negcheck_out.txt | tail -2
