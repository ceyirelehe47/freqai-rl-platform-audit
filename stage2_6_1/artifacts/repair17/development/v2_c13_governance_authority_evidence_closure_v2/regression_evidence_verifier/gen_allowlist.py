#!/usr/bin/env python3
"""从本轮 junit 生成 allowlist(id 用本轮 classname 格式),并对照上一轮
绿色全量证明无新增 skip(按 文件stem+用例名 匹配,跨 id 格式稳定)。"""
import json
import sys
import xml.etree.ElementTree as ET

W = '/home/cryptorl/projects/crypto_rl/work/R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2'
STAMP = sys.argv[1]
this_junit = f'{W}/full_regression_{STAMP}/monitored_run/junit.xml'
prev_junit = ('/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/'
              'repair17/development/v2_c13_postrun_governance_closure/'
              'full_regression/junit.xml')


def skips_of(path):
    out = []
    for ts in ET.parse(path).getroot().iter('testsuite'):
        for tc in ts.iter('testcase'):
            if tc.find('skipped') is not None:
                cid = tc.get('classname', '')
                stem = cid.rsplit('.', 1)[-1] if '.' in cid else cid
                out.append({'id': f'{cid}::{tc.get("name", "")}',
                            'stem': stem, 'name': tc.get('name', '')})
    return out


this = skips_of(this_junit)
prev = skips_of(prev_junit)
prev_keys = {(s['stem'], s['name']) for s in prev}
new_skips = [s for s in this if (s['stem'], s['name']) not in prev_keys]
doc = {
    'allowed_skips': sorted(s['id'] for s in this),
    'provenance': {
        'this_run': f'full_regression_{STAMP} (junit of the monitored run on candidate C2)',
        'previous_green': 'v2_c13_postrun_governance_closure/full_regression/junit.xml (1992 tests, 7 skips, baseline 685d2c9)',
        'matching_rule': '(file stem, test name) pairs must all pre-exist in the previous green full regression',
        'this_run_skips': len(this),
        'previous_skips': len(prev),
        'new_skips': [s['id'] for s in new_skips],
        'no_new_skips': not new_skips,
        'stem_name_pairs_this': sorted(f"{s['stem']}::{s['name']}" for s in this),
        'stem_name_pairs_prev': sorted(f"{s['stem']}::{s['name']}" for s in prev),
    },
}
open(f'{W}/skips_allowlist.json', 'w', encoding='utf-8').write(
    json.dumps(doc, indent=2, ensure_ascii=False))
print('this skips:', len(this), 'prev skips:', len(prev),
      'new:', len(new_skips))
print(json.dumps(doc['provenance']['stem_name_pairs_this'], indent=1))
sys.exit(0 if not new_skips else 1)
