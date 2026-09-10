#!/usr/bin/env python3
"""Read-only calibration-consumer delivery check using the already adopted unshare pattern.

Creates five NEW /tmp copies. Does not start samplers, generate episodes, run
pytest, modify the source run, or mount anything in the parent's namespace.
Native Windows lifecycle testing is outside this tool's scope.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

CODE = ('r17_c3_calibration_bridge.py','r17_c3_calibration_authority.py',
        'r17_c3_calibration_delivery.py','r17_c3_calibration_source_lock.py',
        'r17_c3_reserve_batch.py','r17_c3_reserve_source_lock.py','r17_required_bytes.py')
HIDDEN = (Path('/mnt'), Path('/home/cryptorl/projects'))
CASES = ('healthy', 'bridge_missing', 'bridge_append', 'bridge_same_length', 'telemetry_append')


def write(path, obj):
    with path.open('x', encoding='utf-8') as f: json.dump(obj, f, ensure_ascii=False, indent=2)


def snap(root):
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink(): raise RuntimeError('symlink in delivery input: '+str(p))
        if p.is_file():
            b=p.read_bytes(); result[p.relative_to(root).as_posix()] = [len(b),hashlib.sha256(b).hexdigest()]
        elif not p.is_dir(): raise RuntimeError('nonregular input')
    return result


def unreadable(probes):
    result=[]
    for name in probes:
        try:
            with open(name,'rb') as f: f.read(1)
        except FileNotFoundError:
            result.append({'path':name,'readable':False,'reason':'FileNotFoundError'})
        else: raise RuntimeError('original still readable: '+name)
    return result


def child(work):
    plan=json.loads((work/'plan.json').read_text())
    outputs=[]
    try:
        parent=plan['parent_namespace']; current=os.readlink('/proc/self/ns/mnt')
        if parent==current: raise RuntimeError('mount namespace unchanged')
        for case in plan['cases']:
            root=Path(case['root'])
            subprocess.run(['mount','--bind',str(root),str(root)],check=True)
            subprocess.run(['mount','-o','remount,bind,ro',str(root)],check=True)
        for target in HIDDEN:
            subprocess.run(['mount','-t','tmpfs','-o','size=1m,mode=000','r17-c3-calbridge-hidden',str(target)],check=True)
        before=unreadable(plan['probes'])
        (work/'mountinfo.txt').write_text(Path('/proc/self/mountinfo').read_text())
        for case in plan['cases']:
            root=Path(case['root']); res=work/'results'/case['name'];res.mkdir(parents=True)
            command=[sys.executable,'-B','-s',str(root/'code/r17_c3_calibration_delivery.py'),
                     '--root',str(root),'--record',str(root/'runs'/plan['run_id']/'run_record.json')]
            write(res/'command.json',command)
            env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1';env.pop('PYTHONPATH',None)
            with (res/'stdout.log').open('xb') as so,(res/'stderr.log').open('xb') as se:
                p=subprocess.run(command,stdout=so,stderr=se,env=env,cwd=work,timeout=60)
            (res/'rc.txt').write_text(str(p.returncode)+'\n')
            doc=json.loads((res/'stdout.log').read_text())
            expected=0 if case['name']=='healthy' else 1
            unchanged=snap(root)==case['snapshot']
            if case['name']=='healthy': reason_ok=doc.get('overall_ok') is True
            elif case['name']=='telemetry_append':
                bad=[x for x in doc.get('native_and_required_before',{}).get('files',[]) if not x.get('ok')]
                reason_ok=any(x.get('role')=='telemetry_win' for x in bad) and doc.get('overall_ok') is False
            else:
                reason_ok='bridge evidence byte set mismatch' in doc.get('error','') and doc.get('overall_ok') is False
            outputs.append({'case':case['name'],'rc':p.returncode,'payload_unchanged':unchanged,
                            'ok':p.returncode==expected and unchanged and reason_ok})
        after=unreadable(plan['probes'])
        write(work/'isolation_proof.json',{'parent':parent,'child':current,'before':before,'after':after})
        result={'overall_ok':len(outputs)==5 and all(x['ok'] for x in outputs),'cases':outputs}
    except Exception as exc:
        result={'overall_ok':False,'cases':outputs,'error':type(exc).__name__+': '+str(exc)}
    write(work/'isolated_result.json',result)
    return 0 if result['overall_ok'] else 1


def parent(a):
    source=a.record.resolve(strict=True).parent;runner=a.runner.resolve(strict=True)
    for path in (source,runner):
        if not any(path.is_relative_to(h) for h in HIDDEN):
            raise RuntimeError('input outside supported original roots: '+str(path))
    for h in HIDDEN:
        if not h.is_dir(): raise RuntimeError('expected original root missing: '+str(h))
    record=json.loads(a.record.read_text());rid=record['run_id']
    if rid!=source.name or record['task_kind']!='engineering': raise RuntimeError('not the expected engineering run')
    initial=snap(source)
    if 'c3_calibration_bridge/manifest.json' not in initial: raise RuntimeError('bridge manifest missing')
    runtime_sources=json.loads((source/'c3_calibration_bridge/plan.json').read_text())['authority']['sources']
    for name in CODE:
        if name in ('r17_c3_reserve_source_lock.py','r17_c3_calibration_source_lock.py'):
            continue
        got=hashlib.sha256((runner/name).read_bytes()).hexdigest()
        if got != runtime_sources[Path(name).stem]:
            raise RuntimeError('cold verifier differs from execution source: '+name)
    work=Path(tempfile.mkdtemp(prefix='r17_c3_calbridge_cold_',dir='/tmp'))
    print('WORK_DIR='+str(work),flush=True)
    try:
        probes=[str(source/'c3_calibration_bridge/plan.json'),str(runner/'r17_c3_calibration_delivery.py')]
        for path in probes:
            with open(path,'rb') as f: f.read(1) # prove the originals existed before isolation
        plan={'run_id':rid,'source':str(source),'source_snapshot':initial,'probes':probes,
              'parent_namespace':os.readlink('/proc/self/ns/mnt'),'cases':[]}
        for case in CASES:
            root=work/'cases'/case
            shutil.copytree(source,root/'runs'/rid)
            if snap(root/'runs'/rid)!=initial: raise RuntimeError('copied run differs')
            (root/'code').mkdir()
            for name in CODE:
                raw=(runner/name).read_bytes();(root/'code'/name).write_bytes(raw)
            batch=root/'runs'/rid/'c3_calibration_bridge'
            target=batch/'analysis.json'
            if case=='bridge_missing': target.unlink()
            elif case=='bridge_append': target.write_bytes(target.read_bytes()+b' ')
            elif case=='bridge_same_length':
                data=target.read_bytes(); target.write_bytes(b'['+data[1:])
            elif case=='telemetry_append':
                tel=root/'runs'/rid/'telemetry/win_samples.jsonl'
                tel.write_bytes(tel.read_bytes()+b'"controlled-test-append"\n')
            plan['cases'].append({'name':case,'root':str(root),'snapshot':snap(root)})
        write(work/'plan.json',plan)
        shutil.copyfile(__file__,work/'driver.py')
        command=['unshare','--user','--map-root-user','--mount','--fork','--kill-child',
                 '--propagation','private',sys.executable,'-B','-s',str(work/'driver.py'),'--child',str(work)]
        write(work/'launch.json',command)
        with (work/'namespace.stdout.log').open('xb') as so,(work/'namespace.stderr.log').open('xb') as se:
            p=subprocess.run(command,stdout=so,stderr=se,timeout=360)
        (work/'namespace.rc.txt').write_text(str(p.returncode)+'\n')
        unchanged=snap(source)==initial
        write(work/'source_after.json',{'source_unchanged':unchanged})
        if p.returncode or not unchanged: return 1
        return 0
    except Exception as exc:
        write(work/'failure.json',{'error':type(exc).__name__+': '+str(exc)})
        return 1


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--record',type=Path);p.add_argument('--runner',type=Path)
    p.add_argument('--child',type=Path)
    a=p.parse_args()
    if a.child: return child(a.child)
    if a.record is None or a.runner is None: p.error('--record and --runner required')
    try: return parent(a)
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
