from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import pytest

HERE=Path(__file__).resolve()
ROOT=next(p for p in (HERE.parent.parent/'implementation',HERE.parents[2]/'runner',
                       HERE.parents[2]/'stage2_6_1_runner') if (p/'r17_required_bytes.py').is_file())
spec=importlib.util.spec_from_file_location('r17_required_bytes',ROOT/'r17_required_bytes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


@pytest.fixture
def run(tmp_path):
    root=tmp_path/'evidence'; rd=root/'runs'/'r';rd.mkdir(parents=True)
    roles=sorted(m.CORE_PYTEST_ROLES | m.NATIVE_ROLES)
    required=[]
    for role in roles:
        p=rd/(role+'.txt');p.write_bytes((role+'\n').encode())
        b=p.read_bytes();required.append({'role':role,'path':str(p.relative_to(root)),
            'status':'present','bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
    rec={'run_id':'r','task_kind':'pytest','finalized':True,'evidence_complete':True,
         'control_failures':[],'business':{'rc':0},'writers':{'win':{
           'protocol':'r17-native-sampler-v1','native_exit_confirmed':True,
           'terminal_verified':True,'unconfirmed':False}},'required':required}
    record=rd/'run_record.json';record.write_text(json.dumps(rec))
    return root,record,rec


def save(record,rec): record.write_text(json.dumps(rec))


def test_exact_all_required_healthy(run):
    root,record,rec=run
    assert m.audit(root,record)['exact_bytes_ok']
    assert m.delivery_check(root,record)['delivery_ok']


@pytest.mark.parametrize('role',sorted(m.CORE_PYTEST_ROLES | m.NATIVE_ROLES))
def test_each_required_role_append_is_failure_even_when_pytest_passed(run,role):
    root,record,rec=run; row=next(x for x in rec['required'] if x['role']==role)
    with (root/row['path']).open('ab') as f:f.write(b'APPENDED_AFTER_SEAL\n')
    out=m.delivery_check(root,record)
    assert not out['delivery_ok'] and not out['exact_bytes_ok']
    bad=[x['role'] for x in out['files'] if not x['ok']]
    assert bad==[role]


def test_r3_shaped_prefix_match_is_diagnostic_not_pass(run):
    root,record,rec=run;row=next(x for x in rec['required'] if x['role']=='telemetry_win')
    original=(root/row['path']).read_bytes()
    with (root/row['path']).open('ab') as f:f.write(b'{"seq":351}\n')
    out=m.audit(root,record,hints=True)
    bad=next(x for x in out['files'] if x['role']=='telemetry_win')
    assert bad['telemetry_hints']['comparisons']['raw']['prefix_matches_record']
    assert not out['exact_bytes_ok']
    assert (root/row['path']).read_bytes()==original+b'{"seq":351}\n'


@pytest.mark.parametrize('mode',['missing','same_size','status','live','bad_hash','bad_bytes'])
def test_required_failures(run,mode):
    root,record,rec=run;row=next(x for x in rec['required'] if x['role']=='telemetry_win');p=root/row['path']
    if mode=='missing':p.unlink()
    if mode=='same_size':p.write_bytes(b'x'*p.stat().st_size)
    if mode=='status':row['status']='unreadable'
    if mode=='live':row['live_writers']=True
    if mode=='bad_hash':row['sha256']=None
    if mode=='bad_bytes':row['bytes']=True
    save(record,rec)
    assert not m.delivery_check(root,record)['delivery_ok']


@pytest.mark.parametrize('kind',['empty','duplicate','dropped_role','outside'])
def test_incomplete_or_ambiguous_required_set(run,kind):
    root,record,rec=run
    if kind=='empty':rec['required']=[]
    if kind=='duplicate':rec['required'].append(dict(rec['required'][0]))
    if kind=='dropped_role':rec['required']=[r for r in rec['required'] if r['role']!='telemetry_win']
    if kind=='outside':rec['required'][0]['path']='../elsewhere'
    save(record,rec)
    try:out=m.delivery_check(root,record)
    except ValueError:assert kind=='empty'
    else:assert not out['delivery_ok']


@pytest.mark.parametrize('mutation',[{'exited':True,'unconfirmed':False},
                                    {'protocol':'r17-native-sampler-v1','native_exit_confirmed':False},
                                    {'protocol':'r17-native-sampler-v1','native_exit_confirmed':True,
                                     'terminal_verified':False,'unconfirmed':True}])
def test_self_reported_legacy_exit_not_enough(run,mutation):
    root,record,rec=run;rec['writers']['win']=mutation;save(record,rec)
    assert not m.delivery_check(root,record)['delivery_ok']


def test_reads_do_not_mutate_source(run):
    root,record,rec=run
    before={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    m.delivery_check(root,record)
    assert before=={str(p):p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_verified_aggregate_cannot_use_legacy_green_to_hide_append(run,tmp_path):
    import subprocess
    root,record,rec=run
    legacy=tmp_path/'legacy.py'
    legacy.write_text("import sys,json,pathlib\np=pathlib.Path(sys.argv[sys.argv.index('--out')+1]);p.write_text(json.dumps({'ok':True}))\n")
    config=tmp_path/'config.json';config.write_text(json.dumps({'full_run_record':str(record)}))
    out=tmp_path/'result.json'
    cmd=[sys.executable,str(ROOT/'r17_verified_aggregate.py'),'--root',str(root),
         '--record',str(record),'--legacy-script',str(legacy),'--config',str(config),
         '--out',str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
    assert r.returncode==0,r.stderr
    assert json.loads(out.read_text())['overall_ok'] is True
    row=next(r for r in rec['required'] if r['role']=='telemetry_win')
    with (root/row['path']).open('ab') as f:f.write(b'AFTER_SEAL')
    cmd[-1]=str(tmp_path/'after.json')
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=5)
    assert r.returncode==1
    assert json.loads((tmp_path/'after.json').read_text())['overall_ok'] is False
