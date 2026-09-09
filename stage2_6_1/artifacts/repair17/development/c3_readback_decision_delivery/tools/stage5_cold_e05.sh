#!/usr/bin/env bash
# 阶段五收尾:全量数字提取 → 全量包冷读(E04) → E05 汇总(正例+负例)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
D="$REPO/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery"
RUN=c3rdd_full_20260909
RDIR="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision/runs/$RUN"

source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1

echo "=== full stdout tail ==="
tail -3 "$RDIR/business/stdout.log"
echo "=== run_record 状态 ==="
python3 -c "
import json
rr = json.load(open('$RDIR/run_record.json', encoding='utf-8'))
print('finalized:', rr['finalized'], '| evidence_complete:', rr['evidence_complete'], '| business.rc:', rr['business']['rc'])
print('n_required:', len(rr['required']))
"
echo "=== junit 汇总 ==="
python3 -c "
import xml.etree.ElementTree as ET
t = ET.parse('$RDIR/junit.xml'); r = t.getroot()
s = r if r.tag=='testsuites' else [r][0]
tot=fa=er=sk=0
for ts in (s.findall('testsuite') if r.tag=='testsuites' else [s]):
    tot+=int(ts.get('tests',0)); fa+=int(ts.get('failures',0)); er+=int(ts.get('errors',0)); sk+=int(ts.get('skipped',0))
print(f'junit: {tot} tests / {fa} failures / {er} errors / {sk} skipped')
"
echo "=== 全量冷读(E04) ==="
tr -d '\r' < "$D/tools/full_cold_read.sh" > /tmp/fcr.sh
bash /tmp/fcr.sh "$REPO" "$RUN" /home/cryptorl/r17rdd_fullcold "$D/verification/full_cold_read"
COLD_RC=$?
echo "FULL_COLD_RC=$COLD_RC"
[ "$COLD_RC" -ne 0 ] && exit 1
echo "=== E05 汇总 ==="
tr -d '\r' < "$D/tools/run_e05.sh" > /tmp/e05.sh
bash /tmp/e05.sh "$REPO"
exit $?
