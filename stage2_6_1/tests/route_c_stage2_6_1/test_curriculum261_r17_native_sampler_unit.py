"""Native lifecycle protocol tests. Windows API execution is a separate host test.

These tests call the implementation module, use real files, and replace only
native transport replies. They NEVER count interop returncode as native exit.
"""
from __future__ import annotations
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import pytest


def load_module(name):
    here=Path(__file__).resolve()
    roots=[here.parent.parent/'implementation',here.parents[2]/'runner',
           here.parents[2]/'stage2_6_1_runner']
    root=next(p for p in roots if (p/(name+'.py')).is_file())
    spec=importlib.util.spec_from_file_location(name,root/(name+'.py'))
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod

m=load_module('r17_native_sampler')


@pytest.fixture
def live(tmp_path):
    log=tmp_path/'win.jsonl'; log.write_bytes(b'{"event":"sampler_end"}\n')
    session=m.NativeSamplerControl('test-run',tmp_path/'control',log,
        r'F:\data\win.jsonl',r'F:\data\control','powershell.exe','control.ps1',4096)
    identity={'protocol':m.PROTOCOL,'run_id':session.run_id,'token':session.token,
              'pid':1234,'creation_filetime':'133999999999999999','out_file':session.out_win,
              'started_utc':'2026-09-09T00:00:00Z'}
    m._new_json(session.directory/'identity.json',identity)
    session.refresh_identity()
    return session,identity


def terminal(session,identity,**extra):
    b=session.telemetry.read_bytes()
    result={**identity,'clean':True,'reason':'stop_requested','bytes':len(b),
            'sha256':hashlib.sha256(b).hexdigest(),**extra}
    m._new_json(session.directory/'terminal.json',result)


def confirmation(identity,status='exited',**extra):
    return {k:identity[k] for k in ('protocol','run_id','token','pid','creation_filetime')}|{
        'native_exited':True,'status':status,'identity_matched':True,'forced':False,
        'actual_creation_filetime':identity['creation_filetime'],'win32_error':0,**extra}


def test_cooperative_terminal_and_real_bytes(live):
    session,ident=live; terminal(session,ident)
    result=session.close(time.monotonic()+5,invoke=lambda req,dl:confirmation(ident))
    assert result['native_exit_confirmed'] and result['terminal_verified']
    assert result['unconfirmed'] is False and result['exited'] is True
    stop=json.loads((session.directory/'stop.json').read_text())
    assert stop['token']==ident['token'] and stop['run_id']==ident['run_id']
    assert session.telemetry.read_bytes()==b'{"event":"sampler_end"}\n'


@pytest.mark.parametrize('status', ['wait_failed','force_timeout','query_failed','open_failed','deadline_expired'])
def test_wrapper_exit_does_not_prove_native_exit(live,status):
    session,ident=live; terminal(session,ident)
    r=session.close(time.monotonic()+5,invoke=lambda req,dl:confirmation(ident,status,native_exited=False))
    assert r['unconfirmed'] and not r['native_exit_confirmed']
    assert r['errors']


@pytest.mark.parametrize('field,value', [('token','0'*64),('run_id','old-run'),('pid',4321),
                                         ('creation_filetime','133888888888888888'),('pid',True)])
def test_stale_or_foreign_confirmation_rejected(live,field,value):
    session,ident=live; terminal(session,ident)
    r=session.close(time.monotonic()+5,invoke=lambda req,dl:confirmation(ident,**{field:value}))
    assert r['unconfirmed'] and not r['native_exit_confirmed']


def test_pid_reuse_is_old_exit_without_terminating_new_instance(live):
    session,ident=live; terminal(session,ident)
    reply=confirmation(ident,'pid_reused',identity_matched=False,
                       actual_creation_filetime='134000000000000000')
    r=session.close(time.monotonic()+5,invoke=lambda req,dl:reply)
    assert not r['unconfirmed'] and r['forced'] is False
    assert r['native_status']=='pid_reused'


@pytest.mark.parametrize('err', [5,0,123,87])
def test_absence_requires_specific_native_error(live,err):
    session,ident=live; terminal(session,ident)
    r=session.close(time.monotonic()+5,invoke=lambda req,dl:confirmation(
        ident,'absent',identity_matched=False,actual_creation_filetime='',win32_error=err))
    assert (not r['unconfirmed']) is (err==87)


def test_forced_death_without_terminal_is_not_complete(live):
    session,ident=live
    r=session.close(time.monotonic()+5,invoke=lambda req,dl:confirmation(ident,'forced_exited',forced=True))
    assert r['native_exit_confirmed'] and r['exited']
    assert r['unconfirmed'] and not r['terminal_verified']


@pytest.mark.parametrize('change', ['append','same_length','missing','bad_size','bad_hash','unclean','wrong_token'])
def test_terminal_and_bytes_must_match(live,change):
    session,ident=live
    kwargs={}
    if change=='bad_size':kwargs['bytes']=999
    if change=='bad_hash':kwargs['sha256']='0'*64
    if change=='unclean':kwargs['clean']=False
    if change=='wrong_token':kwargs['token']='0'*64
    terminal(session,ident,**kwargs)
    if change=='append':
        with session.telemetry.open('ab') as f:f.write(b'{"seq":351}\n')
    elif change=='same_length':
        b=session.telemetry.read_bytes();session.telemetry.write_bytes(b'X'+b[1:])
    elif change=='missing': session.telemetry.unlink()
    r=session.close(time.monotonic()+5,invoke=lambda req,dl:confirmation(ident))
    assert r['native_exit_confirmed'] and r['unconfirmed'] and not r['terminal_verified']


def test_zero_budget_starts_no_controller(live):
    session,_=live
    r=session.close(time.monotonic()-1,invoke=lambda *a:pytest.fail('controller started without budget'))
    assert r['unconfirmed'] and not (session.directory/'stop.json').exists()


def test_same_run_deadline_failure_cannot_be_erased(live):
    session,ident=live
    first=session.close(time.monotonic()-1)
    second=session.close(time.monotonic()+100,invoke=lambda *a:pytest.fail('retry restarted budget'))
    assert first==second and second['unconfirmed']


def test_late_confirmation_never_certifies(live):
    session,ident=live; terminal(session,ident)
    now=[10.0]; session.clock=lambda:now[0]
    def invoke(req,deadline):
        assert deadline==10.5 and req['budget_ms']==500
        assert req['cooperate_ms']+req['force_wait_ms']<=500
        now[0]=10.6;return confirmation(ident)
    r=session.close(10.5,invoke=invoke)
    assert r['unconfirmed'] and not r['native_exit_confirmed']


@pytest.mark.parametrize('mutation',[{'token':'0'*64},{'pid':True},{'creation_filetime':None},
                                     {'creation_filetime':0},{'out_file':r'F:\other.json'}])
def test_launch_identity_validation(live,mutation):
    s,i=live
    with pytest.raises(ValueError):m.validate_identity(i|mutation,s.run_id,s.token,s.out_win)


def test_identity_changed_after_acceptance(live):
    s,i=live
    (s.directory/'identity.json').write_text(json.dumps(i|{'started_utc':'changed'}))
    with pytest.raises(ValueError,match='changed'):s.refresh_identity()


def test_unmatched_creation_cannot_claim_forced_success(live):
    s,i=live;terminal(s,i)
    r=s.close(time.monotonic()+3,invoke=lambda *a:confirmation(i,'forced_exited',forced=True,
                       actual_creation_filetime='134000000000000000'))
    assert r['unconfirmed'] and not r['native_exit_confirmed']


def test_control_file_write_does_not_overwrite_existing(live):
    s,i=live;target=s.directory/'stop.json';target.write_text('OLD')
    r=s.close(time.monotonic()+1,invoke=lambda *a:confirmation(i))
    assert target.read_text()=='OLD' and r['unconfirmed']
    assert not list(s.directory.glob('*.tmp'))


def test_required_contains_native_proofs(live):
    s,_=live
    assert {r['role'] for r in s.required()}=={
        'native_sampler_identity','native_sampler_terminal','native_sampler_confirmation'}


def test_transport_exited_without_reply_does_not_return_success(live,monkeypatch):
    s,i=live
    class Transport:
        def poll(self):return 0
    monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**k:Transport())
    t=time.monotonic()
    with pytest.raises(TimeoutError):s._invoke({'protocol':m.PROTOCOL},t+0.06)
    assert time.monotonic()-t<0.5


def test_no_process_name_kill_or_interop_exit_proof_in_native_source():
    root=Path(m.__file__).parent
    cs=(root/'r17_win_process.cs').read_text()
    assert 'TerminateProcess(h, 137)' in cs
    assert cs.index('actual != expected') < cs.index('TerminateProcess(h, 137)')
    assert 'finally { CloseHandle(h); }' in cs
    assert 'Get-Process -Name' not in (root/'r17_win_sampler_control.ps1').read_text()


def test_stop_request_write_failure_does_not_skip_native_control(live):
    s,i=live;terminal(s,i)
    (s.directory/'stop.json').write_text('OLD_STOP_REQUEST')
    calls=[]
    def invoke(request,deadline):
        calls.append(request)
        return confirmation(i)
    r=s.close(time.monotonic()+3,invoke=invoke)
    assert calls and r['native_exit_confirmed']
    assert r['unconfirmed'] and r['errors']  # failure is not erased by later proof
    assert (s.directory/'stop.json').read_text()=='OLD_STOP_REQUEST'
