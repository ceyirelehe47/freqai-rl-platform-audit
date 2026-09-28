#!/usr/bin/env python3
"""E02 只读核验器：7e9e547 完整回归原件逐项复核（不触发 pytest/研究生成）。

对象：stage2_6_1/artifacts/repair17/development/r25_final_closure_20260928T160624/full_regression_v1/
依据：EVIDENCE_READBACK.md §3。全部只读；输出 E02_REGRESSION_VERIFICATION.json。
"""
import json, hashlib, sys, re
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import Counter

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]  # .../freqai-rl-audit
REG = REPO / 'stage2_6_1/artifacts/repair17/development/r25_final_closure_20260928T160624/full_regression_v1'
OUT = HERE / 'E02_REGRESSION_VERIFICATION.json'

def sha256(b): return hashlib.sha256(b).hexdigest()
def norm(b): return b.replace(b'\r\n', b'\n')

results = {}
def check(name, ok, detail=''):
    results[name] = {'ok': bool(ok), 'detail': str(detail)}
    print(('PASS ' if ok else 'FAIL ') + name + ((' :: ' + str(detail)) if detail else ''))
    return ok

files = ['audit_collection.json','audit_collection.json.lifecycle.jsonl','audit_execution.json',
         'audit_execution.json.lifecycle.jsonl','audit_manifest.json','collection.stderr.txt',
         'collection.stdout.txt','execution.stderr.txt','execution.stdout.txt','junit.xml',
         'regression_evidence_v3_record.json','summary.json']
blobs = {}
for f in files:
    p = REG / f
    if not p.exists():
        check(f'exists:{f}', False, 'MISSING IN WORKTREE'); sys.exit(1)
    blobs[f] = p.read_bytes()

record = json.loads(blobs['regression_evidence_v3_record.json'])

# 1. record SHA 复算（锚声明 611b234d…c2819d）
rsha = sha256(blobs['regression_evidence_v3_record.json'])
check('record_sha256_recomputed', rsha == '611b234d6a0f7a5d6e00f680da83a286332913b367affa18fdcae1ac0ec2819d', rsha)

# 2. record 字节锚：junit / audit_manifest / 两 run 的 stdout/stderr/audit/lifecycle 引用
j = record['junit'][0]
check('record_junit_sha', sha256(blobs['junit.xml']) == j['sha256'], j['path'])
am = record['audit_manifest']
check('record_audit_manifest_sha', sha256(blobs['audit_manifest.json']) == am['sha256'], am['path'])
coll = record['collection_run']['runs'][0]; exe = record['execution']['runs'][0]
for nm, run in (('collection', coll), ('execution', exe)):
    for f_ in ('stdout', 'stderr'):
        ref = run[f_]; loc = REG / ref['path']
        check(f'record_{nm}_{f_}_sha', loc.exists() and sha256(loc.read_bytes()) == ref['sha256'], ref['path'])
    for f_ in ('audit', 'audit_lifecycle'):
        ref = run[f_]; loc = REG / ref['path']
        check(f'record_{nm}_{f_}_sha', loc.exists() and sha256(loc.read_bytes()) == ref['sha256'], ref['path'])

# 3. 命令/解释器/cwd/rc/候选
check('collection_command_recorded', coll.get('command') == ['/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python','-m','pytest','-p','r21_collection_auditor','tests/route_c_stage2_6_1','--collect-only','-q'], coll.get('command'))
check('execution_command_junit_target', isinstance(exe.get('command'), list) and 'tests/route_c_stage2_6_1' in exe['command'] and any('junitxml' in str(x) for x in exe['command']), str(exe.get('command'))[:200])
check('collection_rc_0', coll.get('returncode') == 0, coll.get('returncode'))
check('execution_rc_0', exe.get('returncode') == 0, exe.get('returncode'))
check('interpreter_recorded', '/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python' in str(coll.get('interpreter')), coll.get('interpreter'))
check('cwd_deploy_root', coll.get('cwd') == '/home/cryptorl/projects/crypto_rl', coll.get('cwd'))
check('commit_a_is_C', record['commit_a_sha'] == '7e9e5470889884bad296a2dbb4b3e55ca38bc151', record['commit_a_sha'])

# 4. pytest 汇总行
exe_out = (REG / 'execution.stdout.txt').read_text()
m = re.search(r'(\d+) passed, (\d+) skipped(?:, (\d+) warnings)? in ([\d.]+)s ', exe_out)
check('pytest_summary_line', bool(m), m.group(0) if m else 'NOT FOUND')
if m: results['pytest_summary'] = {'passed': int(m.group(1)), 'skipped': int(m.group(2)), 'warnings': m.group(3), 'seconds': m.group(4)}

# 5. JUnit 逐 testcase
root = ET.fromstring(blobs['junit.xml'])
suites = [root] if root.tag == 'testsuite' else root.findall('testsuite')
tcs, fails, errs, skips, skip_ids = [], 0, 0, 0, []
for s in suites:
    for tc in s.findall('testcase'):
        cid = f"{tc.get('classname')}::{tc.get('name')}"
        tcs.append(cid)
        if tc.find('failure') is not None: fails += 1
        if tc.find('error') is not None: errs += 1
        sk = tc.find('skipped')
        if sk is not None:
            skips += 1; skip_ids.append(cid)
junit_ids = Counter(tcs)
check('junit_total_2541', len(tcs) == 2541, len(tcs))
check('junit_failures_0', fails == 0, fails)
check('junit_errors_0', errs == 0, errs)
check('junit_skipped_7', skips == 7, skips)
results['junit'] = {'total': len(tcs), 'failures': fails, 'errors': errs, 'skipped': skips, 'skip_ids': skip_ids}

# 6. collection multiset == junit multiset（collection.stdout.txt 为 pytest --collect-only -q 输出）
def collect_lines(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or '::' not in line or line.startswith('==') or 'tests collected' in line or 'test session' in line or line.startswith('rootdir') or line.startswith('configfile') or line.startswith('plugins') or line.startswith('collected'):
            continue
        out.append(line)
    return out
col_lines = collect_lines((REG / 'collection.stdout.txt').read_text())
def to_junit_id(line):
    # pytest collect 行 path::[Class::]...::name → junit classname(点连接全部中段)::name
    parts = line.split('::')
    path = parts[0].replace('/', '.')
    if path.endswith('.py'): path = path[:-3]
    return '.'.join([path] + parts[1:-1]) + '::' + parts[-1]
col_ids = Counter(to_junit_id(l) for l in col_lines)
check('collection_count_2541', sum(col_ids.values()) == 2541, sum(col_ids.values()))
diff_jc = junit_ids - col_ids; diff_cj = col_ids - junit_ids
check('collection_equals_junit_multiset', not diff_jc and not diff_cj,
      f'junit-only={list(diff_jc)[:5]} coll-only={list(diff_cj)[:5]}')
param_lines = sum(1 for l in col_lines if '[' in l)
results['collection_shape'] = {'nonparam_lines': len(col_lines) - param_lines, 'param_lines': param_lines,
    'note': 'static_tests=2060 的运行期语义 = 候选 Git 树静态推导(static_collection_ids)，非参数行启发式计数；静态推导由 E02_WSL_AUTHORITATIVE_VERIFY.json 的权威核验器闭合'}

# 7. counts 一致性
c = record['counts']
check('record_counts_match_junit', (c['tests'],c['failures'],c['errors'],c['skipped']) == (len(tcs),fails,errs,skips), str(c))
summary = json.loads(blobs['summary.json'])
results['summary_json'] = summary
check('summary_aggregate_match', summary['aggregate'] == {'tests':2541,'failures':0,'errors':0,'skipped':7}, str(summary.get('aggregate')))
check('summary_record_sha_anchor', summary.get('record_sha256') == rsha, summary.get('record_sha256'))
check('summary_ok_true', summary.get('ok') is True)
check('verify_counts_2541_2060_148', (summary['verify']['collection_tests'], summary['verify']['static_tests'], summary['verify']['test_files']) == (2541,2060,148), str(summary.get('verify')))

# 8. 历史 skip 具体身份（record vs junit）
hs = sorted(record['historical_skip_ids']); js = sorted(skip_ids)
check('skip_ids_match_record', hs == js, f'record={hs} junit={js}')
results['historical_skip_ids'] = hs

# 9. record.test_files == 148，且与 summary.test_files 一致
check('record_test_files_148', len(record['test_files']) == 148, len(record['test_files']))

# 10. auditor 输出：r24 collection-audit verdict=pass、violations=0、stages 存在；lifecycle.jsonl 可解析
ac = json.loads(blobs['audit_collection.json'])
check('audit_collection_verdict_pass', ac.get('verdict') == 'pass' and ac.get('violations') == [], f"{ac.get('verdict')} violations={ac.get('violations')}")
check('audit_collection_stages_present', isinstance(ac.get('stages'), list) and len(ac['stages']) > 0, [s.get('name') if isinstance(s,dict) else s for s in ac.get('stages',[])][:6])
check('audit_collection_format_v3', ac.get('format') == 'cur261-r24-collection-audit-v3', ac.get('format'))
ae = json.loads(blobs['audit_execution.json'])
check('audit_execution_verdict_pass', ae.get('verdict') == 'pass' and ae.get('violations') == [], f"{ae.get('verdict')} violations={ae.get('violations')}")
for f in ['audit_collection.json.lifecycle.jsonl', 'audit_execution.json.lifecycle.jsonl']:
    lines = [l for l in blobs[f].decode().splitlines() if l.strip()]
    kinds = []
    okp = True
    for l in lines:
        try:
            o = json.loads(l); kinds.append(o.get('kind') or o.get('event') or o.get('phase'))
        except Exception:
            okp = False
    check(f'lifecycle_parse_{f}', okp and len(lines) > 0, f'{len(lines)} events kinds={sorted(set(map(str,kinds)))[:8]}')

# 11. 审计 manifest：auditor 模块与零批准生成测试
aman = json.loads(blobs['audit_manifest.json'])
check('audit_manifest_zero_approved_generate', aman.get('approved_generate_tests') == {}, str(aman.get('approved_generate_tests'))[:100])
check('audit_manifest_auditor_module', aman.get('auditor',{}).get('module') == 'r21_collection_auditor', aman.get('auditor'))

# 12. supervision：record 内 present=False（监护由外部 monitored run 承担，E03 核验 20260928T160934_4301_1088）
check('record_supervision_external', record['run']['supervision'].get('present') is False, str(record['run']['supervision']))
results['env'] = {'python_version': exe['env'].get('python_version'), 'pytest_version_output': (exe['env'].get('pytest_version_output') or '')[:100], 'hostname': record['run'].get('hostname'), 'user': record['run'].get('user'), 'run_id': record['run'].get('run_id')}

# 13. 源面核验：import_surface.members(315) 与 test_files(148) 按同步规范（deploy=候选 CR 规范化字节）
bad = []
for rel, want in record['import_surface']['members'].items():
    p = REPO / rel
    if not p.exists(): bad.append((rel, 'MISSING')); continue
    if sha256(norm(p.read_bytes())) != want: bad.append((rel, 'SHA(CR-norm)'))
check('import_surface_315_repo_match_CRnorm', len(record['import_surface']['members']) == 315 and not bad,
      f'members={len(record["import_surface"]["members"])} bad={bad[:5]}')
tf_bad = []
for t in record['test_files']:
    p = REPO / t['source_path']
    if not p.exists(): tf_bad.append((t['source_path'], 'MISSING')); continue
    b = norm(p.read_bytes())
    if len(b) != t.get('deploy_size', len(b)) or sha256(b) != t['deploy_sha256']:
        tf_bad.append((t['source_path'], 'SHA/SIZE(CR-norm)'))
check('test_files_148_source_match_CRnorm', not tf_bad, f'bad={tf_bad[:5]}')

ok_all = all(v['ok'] for v in results.values() if isinstance(v, dict) and 'ok' in v)
results['_overall'] = {'all_ok': ok_all, 'checked_at_utc': '2026-09-29T01:xx', 'record_path': str(REG.relative_to(REPO)), 'record_format': record.get('format')}
OUT.write_text(json.dumps(results, indent=1, sort_keys=True))
print(f"\nOVERALL: {'ALL PASS' if ok_all else 'HAS FAIL'} -> {OUT.name}")
sys.exit(0 if ok_all else 2)
