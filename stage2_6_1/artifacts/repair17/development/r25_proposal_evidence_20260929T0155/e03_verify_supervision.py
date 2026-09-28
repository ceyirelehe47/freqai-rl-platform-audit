#!/usr/bin/env python3
"""E03 只读核验器：5 个监护 run 逐成员大小/SHA + 身份/终止/覆盖复核。

对象（repo HEAD 树内原件，工作树逐字节复算）：
  新候选: 20260928T160626_7004_367(真实 launcher 集成), 20260928T160934_4301_1088(完整回归监护)
  上轮:   20260926T212149_1124_424(Binding 集成), 20260926T212354_1984_392(失败回归监护),
          20260926T220905_5450_537(最终回归监护)
全部只读；输出 E03_SUPERVISION_VERIFICATION.json。
"""
import json, hashlib, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RUNS = REPO / 'stage2_6_1/artifacts/repair17/development/run_supervision/runs'
OUT = HERE / 'E03_SUPERVISION_VERIFICATION.json'
REPO = HERE.parents[4]
def sha256(b): return hashlib.sha256(b).hexdigest()

results = {'runs': {}, 'cross_package': {}}
def check(run, name, ok, detail=''):
    results['runs'].setdefault(run, {})[name] = {'ok': bool(ok), 'detail': str(detail)[:400]}
    print(('PASS ' if ok else 'FAIL ') + f'[{run}] {name}' + (f' :: {detail}' if detail else ''))
    return ok

RUNS_TO_VERIFY = ['20260928T160626_7004_367', '20260928T160934_4301_1088',
                  '20260926T212149_1124_424', '20260926T212354_1984_392',
                  '20260926T220905_5450_537']

for rid in RUNS_TO_VERIFY:
    d = RUNS / rid
    if not d.is_dir():
        check(rid, 'run_dir_exists', False); continue
    rec = json.loads((d / 'run_record.json').read_text(encoding='utf-8'))
    summ = json.loads((d / 'summary.json').read_text(encoding='utf-8'))
    check(rid, 'record_schema_v2', rec.get('schema') == 'r17-run-record-v2', rec.get('schema'))
    check(rid, 'summary_schema_v1', summ.get('schema') == 'r17-supervision-summary-v1', summ.get('schema'))
    check(rid, 'ids_match', rec.get('run_id') == rid == summ.get('run_id'))
    # required 逐成员：路径（相对 runs/ 根）、大小、SHA
    req = rec.get('required', [])
    bad = []
    roles = []
    for m in req:
        roles.append(m.get('role'))
        p = RUNS / m['path'].removeprefix('runs/')
        if not p.is_file():
            bad.append((m['role'], 'MISSING')); continue
        b = p.read_bytes()
        if len(b) != m.get('bytes'):
            bad.append((m['role'], f"SIZE {len(b)}!={m.get('bytes')}")); continue
        if sha256(b) != m.get('sha256'):
            bad.append((m['role'], 'SHA'))
    check(rid, f'required_all_verified_n{len(req)}', not bad, f'roles={roles} bad={bad}')
    check(rid, 'record_finalized', rec.get('finalized') is True and rec.get('evidence_complete') is True
          and not rec.get('missing_roles') and not rec.get('control_failures'),
          f"finalized={rec.get('finalized')} evidence_complete={rec.get('evidence_complete')} missing={rec.get('missing_roles')} ctrl_fail={rec.get('control_failures')}")
    check(rid, 'policy_sha_match', rec.get('policy', {}).get('sha256') == summ.get('policy_sha256'),
          str(rec.get('policy', {}).get('sha256')))
    b = rec.get('business', {})
    check(rid, 'business_rc_recorded', isinstance(b.get('rc'), int), f"rc={b.get('rc')} signal={b.get('signal')}")
    check(rid, 'summary_business_rc_same', summ.get('business', {}).get('rc') == b.get('rc'))
    rc = b.get('rc')
    inc = summ.get('incidents', [])
    inc_ok = (rc == 0 and inc == []) or (rc != 0 and any(i.get('kind') == 'worker_exit' for i in inc))
    check(rid, 'incidents_consistent_with_rc', inc_ok,
          f'rc={rc} incidents={[i.get("kind") for i in inc]}（rc=4 失败回归监护的 worker_exit incident 属真实历史记录）')
    # 命令身份（argv 锚）
    check(rid, 'argv_recorded', isinstance(rec.get('argv'), list) and len(rec['argv']) >= 2, ' '.join(rec.get('argv', []))[:200])
    # 遥测采样序列与覆盖
    cov = summ.get('coverage', {})
    seq_ok = all(cov.get(k) == 0 for k in ('win_parse_errors', 'win_invalid_samples', 'win_duplicate_seq',
                                           'win_seq_regressions', 'guest_duplicate_seq') if k in cov)
    keys = [k for k in cov if k.endswith('_regressions') or k.endswith('_errors') or k.endswith('_failures')]
    neg = {k: cov[k] for k in keys if cov.get(k)}
    check(rid, 'telemetry_sequence_clean', seq_ok and not neg, f'nonzero={neg}')
    # 遥测文件实际行数与 jsonl 可解析（required 已验 SHA，这里验内容可读）
    tel_bad = []
    for side in ('guest_samples.jsonl', 'win_samples.jsonl'):
        p = d / 'telemetry' / side
        if not p.is_file(): tel_bad.append((side, 'MISSING')); continue
        for i, line in enumerate(p.read_text(encoding='utf-8').splitlines()):
            if line.strip():
                try: json.loads(line)
                except Exception: tel_bad.append((side, f'line{i}'))
    check(rid, 'telemetry_jsonl_parseable', not tel_bad, str(tel_bad[:3]))

# ---- 真实集成 run 深核：worker/checker rc 与实例身份、覆盖与峰值 ----
rid = '20260928T160626_7004_367'
d = RUNS / rid
out = (d / 'business' / 'stdout.log').read_text(encoding='utf-8', errors='replace')
import re
probe_rc = {f'w{m.group(1)}': m.group(2) for m in re.finditer(r'probe end w(\d) rc=(\d+)', out)}
checker_rc = {f'w{m.group(1)}': m.group(2) for m in re.finditer(r'checker w(\d) rc=(\d+)', out)}
verdicts = re.findall(r'"verdict": "clean", "rc": 0', out)
ok_int = (probe_rc.get('w1') == '0' and probe_rc.get('w2') == '0' and probe_rc.get('w3') == '124'
          and checker_rc.get('w1') == '0' and checker_rc.get('w2') == '0' and checker_rc.get('w3') == '0'
          and len(verdicts) == 3)
results['runs'][rid]['integration_stdout'] = {
    'ok': ok_int,
    'detail': f'probe={probe_rc} checker={checker_rc} clean_json={len(verdicts)}'}
print(('PASS ' if ok_int else 'FAIL ') + f'[{rid}] integration_stdout :: probe={probe_rc} checker={checker_rc} clean_json={len(verdicts)}')
# registry v2 先验完整性 + 逐实例真实身份（pid/start_ticks 严格正、created_roles 多重集=instances、恰一 root 且=root_pid）
reg_checks = []
reg_ok = True
for w in ('w1', 'w2', 'w3'):
    p = RUNS.parents[1] / 'r25_final_closure_20260928T160624' / 'i01_probe' / 'logs' / f'{w}_registry.json'
    if not p.is_file():
        reg_ok = False; reg_checks.append((w, 'MISSING')); continue
    reg = json.loads(p.read_text(encoding='utf-8'))
    fmt = reg.get('format', '')
    insts = reg.get('instances', [])
    from collections import Counter as _C
    roles_multiset_ok = _C(reg.get('created_roles', [])) == _C(i.get('role') for i in insts)
    pids = [i.get('pid') for i in insts]
    pids_ok = all(isinstance(p_, int) and not isinstance(p_, bool) and p_ > 0 for p_ in pids) and len(set(pids)) == len(pids)
    ticks_ok = all(isinstance(i.get('start_ticks'), int) and i.get('start_ticks', 0) >= 1 for i in insts)
    roots = [i for i in insts if i.get('role') == 'root']
    root_ok = len(roots) == 1 and roots[0].get('pid') == reg.get('root_pid')
    w_ok = (fmt == 'r25-worker-registry-v2' and roles_multiset_ok and pids_ok and ticks_ok and root_ok
            and isinstance(reg.get('identity_sources'), dict))
    reg_ok = reg_ok and w_ok
    reg_checks.append((w, fmt, f'n={len(insts)}', f'roles_ok={roles_multiset_ok} pids_ok={pids_ok} ticks_ok={ticks_ok} root_ok={root_ok}'))
results['runs'][rid]['registries_v2_real_identity'] = {'ok': reg_ok, 'detail': str(reg_checks)}
print(('PASS ' if reg_ok else 'FAIL ') + f'[{rid}] registries_v2_real_identity :: {reg_checks}')

# ---- 与 E01 包内副本对拍（两个最新 run 的 run_supervision_runs 副本 == repo 原件字节） ----
import zipfile
zo = zipfile.ZipFile(HERE / 'input_return' / 'RouteC_R25_FinalClosure_TrainingReadiness_v1_RETURN_TO_CHATGPT.zip')
prefix = 'RouteC_R25_FinalClosure_TrainingReadiness_v1_RETURN_TO_CHATGPT/run_supervision_runs/'
n_ok = n_bad = 0
bad_list = []
for info in zo.infolist():
    if not info.filename.startswith(prefix) or info.filename == prefix:
        continue
    rel = info.filename[len(prefix):]
    local = RUNS / rel
    if not local.is_file():
        n_bad += 1; bad_list.append((rel, 'MISSING-LOCAL')); continue
    if sha256(zo.read(info.filename)) == sha256(local.read_bytes()):
        n_ok += 1
    else:
        n_bad += 1; bad_list.append((rel, 'SHA'))
results['cross_package'] = {'ok': n_bad == 0 and n_ok > 0, 'matched': n_ok, 'bad': n_bad, 'bad_list': bad_list[:5]}
print(f"{'PASS' if n_bad == 0 else 'FAIL'} cross_package_member_bytes :: matched={n_ok} bad={n_bad} {bad_list[:3]}")

ok_all = all(v.get('ok', True) for r in results['runs'].values() for v in r.values()) and results['cross_package']['ok']
results['_overall'] = {'all_ok': ok_all, 'checked_at_utc': '2026-09-29'}
OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True))
print(f'\nOVERALL: {"ALL PASS" if ok_all else "HAS FAIL"} -> {OUT.name}')
sys.exit(0 if ok_all else 2)
