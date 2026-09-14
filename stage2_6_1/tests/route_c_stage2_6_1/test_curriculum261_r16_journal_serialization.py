"""Journal transactions: real full module, processes, locks and partial I/O.

No generator, V2 fit, policy evaluation, production claim or production state.
"""
from __future__ import annotations
import concurrent.futures
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading

import pytest
from rl_curriculum import curriculum261_r16_execgov as eg
from r17_r16_journal_test_support import controlled_case, evidence_dir, run_competition


@pytest.fixture()
def root(tmp_path, monkeypatch):
    p=tmp_path/'state';p.mkdir()
    monkeypatch.setenv('CURRICULUM261_R16_STATE_ROOT',str(p))
    monkeypatch.delenv('CURRICULUM261_R16_EXECUTOR_TOKEN',raising=False)
    eg._deactivate_grant()
    return p


def record(seq=1, **kw):
    return {"seq":seq,"event":"session_acquired","iteration":"r16","pid":1,**kw}


def test_read_empty_is_truly_read_only(tmp_path,monkeypatch):
    absent=tmp_path/'missing'/'state'
    monkeypatch.setenv('CURRICULUM261_R16_STATE_ROOT',str(absent))
    assert eg.journal_entries()==[]
    assert not absent.exists()
    assert not absent.parent.exists()


def test_legacy_valid_journal_keeps_prefix(root):
    p=eg.r16_journal_path();before=(json.dumps(record())+'\n').encode()
    p.write_bytes(before);inode=p.stat().st_ino
    assert eg.journal_append('session_rejected',{'reason':'test'},durable=False)==2
    assert p.read_bytes().startswith(before) and p.stat().st_ino==inode
    assert [e['seq'] for e in eg.journal_entries()]==[1,2]
    assert set(x.name for x in root.iterdir())=={eg.R16_JOURNAL_NAME}


@pytest.mark.parametrize('bad',[
    b'{broken\n',json.dumps(record()).encode(),
    (json.dumps(record())+'\n'+json.dumps(record())+'\n').encode(),
    (json.dumps(record(2))+'\n').encode(),
    (json.dumps(record(True))+'\n').encode(),
    (json.dumps(record(event='unknown'))+'\n').encode(),
    (json.dumps(record(iteration='r17'))+'\n').encode(),
    b'{"seq":1,"seq":1,"event":"session_acquired","iteration":"r16"}\n',
    b'{"seq":1,"event":"session_acquired","iteration":"r16","x":NaN}\n',
    b'{"seq":1,"event":"session_acquired","iteration":"r16","x":"\xff"}\n',
    b' ',
])
def test_corrupt_prefix_never_read_as_healthy_or_appended(root,bad):
    p=eg.r16_journal_path();p.write_bytes(bad)
    with pytest.raises(eg.R16JournalCorruption):eg.journal_entries()
    with pytest.raises(eg.R16JournalCorruption):eg.journal_append('session_rejected',durable=False)
    assert p.read_bytes()==bad
    eg.R16FormalSession._record_rejection({},'bad',None)
    assert p.read_bytes()==bad
    assert isinstance(eg.journal_entries(strict=False),list)
    assert p.read_bytes()==bad


@pytest.mark.parametrize('key',['seq','utc','event','iteration','pid'])
def test_payload_cannot_replace_identity(root,key):
    with pytest.raises(ValueError):eg.journal_append('session_acquired',{key:1})
    assert not eg.r16_journal_path().exists()


def test_bad_payload_serialization_does_not_create_journal(root):
    with pytest.raises((ValueError,TypeError)):eg.journal_append('session_acquired',{'x':float('nan')})
    assert not eg.r16_journal_path().exists()


@pytest.mark.parametrize('kind',['symlink','directory','fifo'])
def test_nonregular_journal_never_followed_or_blocked(root,kind):
    p=eg.r16_journal_path();target=root/'target';target.write_bytes(b'unchanged')
    if kind=='symlink':p.symlink_to(target)
    elif kind=='directory':p.mkdir()
    else:os.mkfifo(p)
    for action in (eg.journal_entries,lambda:eg.journal_append('session_acquired')):
        with pytest.raises((OSError,eg.R16JournalCorruption)):action()
    assert target.read_bytes()==b'unchanged'


def test_lock_released_on_write_exception(root,monkeypatch):
    original=eg._write_journal_record
    def fail(*a):raise OSError('injected before first byte')
    monkeypatch.setattr(eg,'_write_journal_record',fail)
    with pytest.raises(OSError):eg.journal_append('session_acquired')
    fd=os.open(eg.r16_journal_path(),os.O_RDONLY)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:os.close(fd)
    monkeypatch.setattr(eg,'_write_journal_record',original)
    assert eg.journal_append('session_rejected')==1


def test_short_and_interrupted_writes_complete_once(root,monkeypatch):
    original=os.write;calls=[]
    def short(fd,data):
        calls.append(len(data))
        if len(calls)==1:raise InterruptedError()
        return original(fd,bytes(data[:7]))
    monkeypatch.setattr(os,'write',short)
    assert eg.journal_append('session_acquired',{'utf8':'中文'})==1
    assert eg.journal_entries()[0]['utf8']=='中文'
    assert len(calls)>3


def test_zero_progress_leaves_no_fake_success(root,monkeypatch):
    monkeypatch.setattr(os,'write',lambda fd,data:0)
    with pytest.raises(OSError):eg.journal_append('session_acquired')
    assert eg.r16_journal_path().read_bytes()==b''


@pytest.mark.parametrize('which',['file','directory'])
def test_fsync_error_propagates_without_retry_or_history_rewrite(root,monkeypatch,which):
    original=os.fsync;calls=[]
    def fail(fd):
        isdir=stat.S_ISDIR(os.fstat(fd).st_mode);calls.append('directory' if isdir else 'file')
        if isdir==(which=='directory'):raise OSError('injected fsync failure')
        original(fd)
    monkeypatch.setattr(os,'fsync',fail)
    with pytest.raises(OSError):eg.journal_append('session_acquired')
    assert len(eg.journal_entries())==1
    assert calls.count(which)==1


def test_durable_false_still_validates_and_uses_mutex(root,monkeypatch):
    operations=[];original=fcntl.flock
    def spy(fd,mode):operations.append(mode);return original(fd,mode)
    monkeypatch.setattr(fcntl,'flock',spy)
    monkeypatch.setattr(os,'fsync',lambda fd:(_ for _ in ()).throw(AssertionError('not durable')))
    assert eg.journal_append('session_rejected',durable=False)==1
    assert operations==[fcntl.LOCK_EX,fcntl.LOCK_UN]


def test_session_fd_released_if_initial_journal_write_fails(root,monkeypatch):
    monkeypatch.setattr(eg,'_write_journal_record',lambda *a:(_ for _ in ()).throw(OSError('injected')))
    with pytest.raises(OSError):eg.R16FormalSession.acquire(binding={})
    fd=os.open(root/eg.R16_SESSION_LOCK_NAME,os.O_RDONLY)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:os.close(fd)


def test_threads_allocate_unique_sequences(root):
    barrier=threading.Barrier(4)
    def work(worker):
        barrier.wait(timeout=10)
        return [eg.journal_append('session_rejected',{'worker':worker,'i':i},durable=False) for i in range(8)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        sequences=[s for block in pool.map(work,range(4)) for s in block]
    assert sorted(sequences)==list(range(1,33))
    assert [e['seq'] for e in eg.journal_entries()]==list(range(1,33))


def test_forced_owner_and_rejection_interleaving(root,tmp_path):
    ev=evidence_dir(tmp_path,'forced_owner_rejection')
    r=controlled_case(Path(eg.__file__),root,ev)
    assert not r['errors'] and r['observed_required_interleaving'],r
    assert r['children']['A']['rc']==0 and r['children']['B']['rc']==3,r
    assert all(not x['stderr'] for x in r['children'].values()),r
    entries=eg.journal_entries()
    assert [e['seq'] for e in entries]==list(range(1,len(entries)+1))
    assert [e['event'] for e in entries[:2]]==['session_acquired','session_rejected']
    assert eg.exposure_state()['terminal']
    assert len([e for e in entries if e['event']=='exposure_started'])==1


@pytest.mark.parametrize('phase',['read','partial','file_fsync','dir_fsync'])
def test_reader_cannot_observe_an_inflight_append(root,tmp_path,phase):
    ev=evidence_dir(tmp_path,'reader_'+phase)
    r=controlled_case(Path(eg.__file__),root,ev,mode='reader',phase=phase)
    assert not r['errors'] and r['observed_required_interleaving'],r
    assert r['children']['A']['rc']==0 and r['children']['B']['rc']==0,r
    assert json.loads(r['children']['B']['stdout'])['strict_ok'] is True
    assert r['journal_sequence']==[1]


def test_killed_partial_append_is_preserved_and_refused(root,tmp_path):
    ev=evidence_dir(tmp_path,'killed_partial')
    r=controlled_case(Path(eg.__file__),root,ev,mode='reader',phase='partial',kill=True)
    assert not r['errors'] and r['observed_required_interleaving'],r
    assert r['children']['A']['rc']==-9 and r['children']['B']['rc']==4,r
    before=eg.r16_journal_path().read_bytes()
    assert before and not before.endswith(b'\n')
    with pytest.raises(eg.R16JournalCorruption):eg.journal_entries()
    with pytest.raises(eg.R16JournalCorruption):eg.journal_append('session_rejected')
    assert before==eg.r16_journal_path().read_bytes()


def test_competition_child_exception_has_durable_diagnostics(root,tmp_path):
    ev=evidence_dir(tmp_path,'child_crash')
    r=run_competition(Path(eg.__file__),root,tmp_path/'control',ev,mode='crash_after_acquire')
    assert r['ok'] is False
    assert any('injected child failure' in c['stderr'] for c in r['children'].values()),r
    assert (ev/'state_snapshot.json').is_file() and (ev/'result.json').is_file()
    assert all((ev/(role+'.rc')).is_file() and (ev/(role+'.stderr.log')).is_file() for role in ('A','B'))
