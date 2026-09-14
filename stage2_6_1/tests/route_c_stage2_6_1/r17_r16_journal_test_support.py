"""Test-only real subprocess harness. Never imports a generator or runs a policy.

All authority is confined to a caller-provided system-temp subtree. Worker
stdout/stderr go straight to files, not discarded PIPE outputs. The production
module is loaded in full from its actual __file__, without copied functions.
"""
from __future__ import annotations
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback


def load_module(path):
    spec = importlib.util.spec_from_file_location('r16_actual_worker', str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, sort_keys=True, indent=2, ensure_ascii=False)
        f.write('\n')


def wait_for(path, timeout=20):
    deadline = time.monotonic() + timeout
    while not Path(path).is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError('barrier deadline: ' + str(path))
        time.sleep(0.005)


def temp_state(path):
    path = Path(path).absolute()
    root = Path(tempfile.gettempdir()).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('test state must be a dedicated system-temp subtree')
    probe = path
    while probe != probe.parent:
        if probe.is_symlink():
            raise ValueError('test state symlink rejected')
        probe = probe.parent
    return path


def evidence_dir(tmp_path, label):
    declared = os.environ.get('R17_R16_TEST_EVIDENCE_DIR')
    root = Path(declared) if declared else Path(tmp_path) / 'forensics'
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('absolute evidence directory required')
    # This env is test evidence only, never authority or a production root.
    for forbidden in ('/mnt/f/trading/freqai-rl-audit',
                      '/home/cryptorl/projects/crypto_rl/src',
                      '/home/cryptorl/projects/crypto_rl/stage2_6_1_runner',
                      '/home/cryptorl/projects/crypto_rl/artifacts'):
        if root.is_relative_to(forbidden):
            raise ValueError('refuse evidence in protected/production tree')
    probe = root
    while probe != probe.parent:
        if probe.is_symlink():
            raise ValueError('evidence symlink rejected')
        probe = probe.parent
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=label + '_', dir=root))


def snapshot_state(state, out):
    state = Path(state)
    rows = {}
    rawroot = out / 'state_bytes'
    rawroot.mkdir()
    for path in sorted(state.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('unexpected link in temporary state')
        if path.is_file():
            rel = path.relative_to(state).as_posix()
            data = path.read_bytes()
            target = rawroot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            rows[rel] = {'size':len(data), 'sha256':hashlib.sha256(data).hexdigest(),
                         'base64':base64.b64encode(data).decode('ascii')}
    write_json(out / 'state_snapshot.json', rows)
    return rows


def _worker(module_path, root, control, role, mode):
    eg = load_module(module_path)
    root = temp_state(root)
    os.environ['CURRICULUM261_R16_STATE_ROOT'] = str(root)
    os.environ.pop('CURRICULUM261_R16_EXECUTOR_TOKEN', None)
    control = Path(control)
    phase = control / (role + '.phases.jsonl')
    def trace(name):
        with phase.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'phase':name, 'pid':os.getpid(),
                                'monotonic_ns':time.monotonic_ns()})+'\n')
            f.flush()
    trace('ready')
    (control/(role+'.ready')).touch(exist_ok=False)
    wait_for(control/'go')
    session = None
    try:
        trace('acquire_enter')
        try:
            session = eg.R16FormalSession.acquire(binding={'role':role})
        except eg.R16OwnershipError as exc:
            trace('rejected')
            (control/(role+'.rejected')).touch(exist_ok=False)
            print(json.dumps({'role':role,'acquired':False,'error':str(exc)}),flush=True)
            return 3
        trace('acquired')
        (control/(role+'.acquired')).touch(exist_ok=False)
        if mode == 'crash_after_acquire':
            raise RuntimeError('injected child failure after real acquire')
        # Both processes were released by the same go barrier. The winner
        # stays owner until the real loser finishes its rejection; no sleep
        # assumption about A being faster or about scheduling fairness.
        other = 'B' if role == 'A' else 'A'
        wait_for(control/(other+'.rejected'))
        trace('exposure_enter')
        session.record_exposure_started('digest-comp')
        trace('exposure_written')
        session.issue_generation_grant()
        trace('grant_issued')
        session.revoke_generation_grant()
        trace('grant_revoked')
        session.commit_qualification_terminal('completed','digest-comp')
        trace('terminal_written')
        session.release()
        trace('released')
        # Never print success early to hide a failed terminal/release.
        print(json.dumps({'role':role,'acquired':True}),flush=True)
        return 0
    except BaseException:
        trace('exception')
        traceback.print_exc()
        return 1


def run_competition(module_path, state, work, evidence, *, mode='normal'):
    """One two-process competition, not retry-until-green. Always save first."""
    state = temp_state(state)
    state.mkdir(parents=True, exist_ok=True)
    work, evidence = Path(work), Path(evidence)
    work.mkdir(parents=True, exist_ok=True)
    procs = {}; handles = []; commands = {}; errors = []
    try:
        for role in ('A','B'):
            command=[sys.executable, str(Path(__file__).resolve()),
                     '--worker', str(module_path), str(state), str(work), role, mode]
            commands[role]=command
            f=(evidence/(role+'.stdout.log')).open('xb')
            e=(evidence/(role+'.stderr.log')).open('xb')
            handles += [f,e]
            env = dict(os.environ)
            env.pop('CURRICULUM261_R16_EXECUTOR_TOKEN',None)
            procs[role]=subprocess.Popen(command,env=env,stdout=f,stderr=e)
        wait_for(work/'A.ready'); wait_for(work/'B.ready')
        (work/'go').touch(exist_ok=False)
        deadline=time.monotonic()+30
        for role,proc in procs.items():
            proc.wait(timeout=max(0.1,deadline-time.monotonic()))
    except BaseException as exc:
        errors.append(type(exc).__name__+': '+str(exc))
    finally:
        for role,proc in procs.items():
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill();proc.wait(timeout=3)
        for h in handles:h.close()
    raw = {};results=[]
    for role,proc in procs.items():
        stdout=(evidence/(role+'.stdout.log')).read_bytes()
        stderr=(evidence/(role+'.stderr.log')).read_bytes()
        raw[role]={'rc':proc.returncode,'stdout':stdout.decode(errors='replace'),
                   'stderr':stderr.decode(errors='replace')}
        (evidence/(role+'.rc')).write_text(str(proc.returncode)+'\n')
        for line in stdout.decode(errors='replace').splitlines():
            try:value=json.loads(line)
            except ValueError:
                errors.append('non-JSON child stdout: '+role);continue
            results.append(value)
        if (work/(role+'.phases.jsonl')).is_file():
            (evidence/(role+'.phases.jsonl')).write_bytes((work/(role+'.phases.jsonl')).read_bytes())
    snapshots=snapshot_state(state,evidence)
    journal=snapshots.get('r16_execution_journal.jsonl',{})
    sequence=[]
    try:
        for line in base64.b64decode(journal.get('base64','')).splitlines():
            if line.strip():sequence.append(json.loads(line)['seq'])
    except ValueError:errors.append('journal JSON parse failure')
    winners=[r for r in results if r.get('acquired') is True]
    losers=[r for r in results if r.get('acquired') is False]
    ok=(not errors and len(winners)==1 and len(losers)==1
        and {r.get('role') for r in results}=={'A','B'}
        and raw[winners[0]['role']]['rc']==0
        and raw[losers[0]['role']]['rc']==3
        and all(not r['stderr'] for r in raw.values())
        and sequence==list(range(1,len(sequence)+1)))
    report={'ok':ok,'children':raw,'results':results,'errors':errors,
            'journal_sequence':sequence,'journal':journal,'commands':commands,
            'module_file':str(module_path),
            'module_sha256':hashlib.sha256(Path(module_path).read_bytes()).hexdigest(),
            'evidence_dir':str(evidence)}
    write_json(evidence/'result.json',report)
    return report


# Multiprocessing helpers are top-level so spawn uses a clean interpreter.
def _capture_child(module_path, state, control, output, role, action, ready,
                   release, blocked, other_done, complete, phase='read'):
    output = Path(output)
    with (output/(role+'.stdout.log')).open('xb',buffering=0) as out, \
         (output/(role+'.stderr.log')).open('xb',buffering=0) as err:
        os.dup2(out.fileno(),1);os.dup2(err.fileno(),2)
        code=0
        try:
            eg=load_module(module_path)
            os.environ['CURRICULUM261_R16_STATE_ROOT']=str(temp_state(state))
            os.environ.pop('CURRICULUM261_R16_EXECUTOR_TOKEN',None)
            import fcntl
            flock_original=fcntl.flock
            def observed_flock(fd,mode):
                path=os.readlink('/proc/self/fd/'+str(fd))
                if path.endswith(eg.R16_JOURNAL_NAME) and mode in (fcntl.LOCK_EX,fcntl.LOCK_SH):
                    try:return flock_original(fd,mode|fcntl.LOCK_NB)
                    except BlockingIOError:
                        blocked.set()
                        return flock_original(fd,mode)
                return flock_original(fd,mode)
            if action in ('contender','reader'):
                fcntl.flock=observed_flock
            if action in ('owner','writer'):
                if phase=='read':
                    if hasattr(eg,'_journal_records_locked'):
                        original=eg._journal_records_locked
                        def pause(fh,*a,**kw):
                            value=original(fh,*a,**kw)
                            if (fcntl.fcntl(fh.fileno(),fcntl.F_GETFL)&os.O_ACCMODE)==os.O_RDWR and not ready.is_set():
                                ready.set()
                                if not release.wait(20):raise TimeoutError('release writer')
                            return value
                        eg._journal_records_locked=pause
                    else:
                        original=eg._journal_entries_lenient
                        def pause(*a,**kw):
                            value=original(*a,**kw)
                            if not ready.is_set():
                                ready.set()
                                if not release.wait(20):raise TimeoutError('release baseline writer')
                            return value
                        eg._journal_entries_lenient=pause
                elif phase=='partial':
                    original=eg._write_journal_record
                    def partial(fd, data):
                        # Real exact prefix, not a made-up corrupt record.
                        cut=len(data)//2
                        n=os.write(fd,data[:cut])
                        ready.set()
                        if not release.wait(20):raise TimeoutError('release partial writer')
                        return original(fd,data[n:])
                    eg._write_journal_record=partial
                elif phase in ('file_fsync','dir_fsync'):
                    original=os.fsync
                    import stat
                    def fsync(fd):
                        is_dir=stat.S_ISDIR(os.fstat(fd).st_mode)
                        if is_dir==(phase=='dir_fsync') and not ready.is_set():
                            ready.set()
                            if not release.wait(20):raise TimeoutError('release fsync')
                        return original(fd)
                    os.fsync=fsync
            if action=='owner':
                s=eg.R16FormalSession.acquire(binding={'role':'A'})
                if not other_done.wait(20):raise TimeoutError('contender not done')
                s.record_exposure_started('forced-race')
                s.issue_generation_grant();s.revoke_generation_grant()
                s.commit_qualification_terminal('completed','forced-race')
                s.release()
                print(json.dumps({'acquired':True,'role':role}),flush=True)
            elif action=='contender':
                try:
                    s=eg.R16FormalSession.acquire(binding={'role':'B'})
                except eg.R16OwnershipError as exc:
                    print(json.dumps({'acquired':False,'error':str(exc)}),flush=True)
                    code=3
                else:
                    s.release()
                    raise AssertionError('contender wrongly acquired session')
                finally:other_done.set()
            elif action=='writer':
                print(json.dumps({'seq':eg.journal_append('session_acquired',{'role':'A'})}),flush=True)
            elif action=='reader':
                try:
                    records=eg.journal_entries()
                    print(json.dumps({'records':records,'strict_ok':True}),flush=True)
                except eg.R16JournalCorruption as exc:
                    print(json.dumps({'strict_ok':False,'error':type(exc).__name__,'detail':str(exc)}),flush=True)
                    code=4
            else:raise ValueError(action)
        except BaseException:
            traceback.print_exc();code=1
        finally:complete.set()
    raise SystemExit(code)


def controlled_case(module_path, state, evidence, *, mode='race', phase='read', baseline=False, kill=False):
    """Observe an actual incompatible flock, then release a single barrier.

    baseline=True expects the old algorithm's contender to finish before the
    paused writer. This mode is only for the shipped historical source probe.
    """
    import multiprocessing as mp
    ctx=mp.get_context('spawn')
    state=temp_state(state);state.mkdir(parents=True,exist_ok=True)
    evidence=Path(evidence)
    ready,release,blocked,other_done,ca,cb=[ctx.Event() for _ in range(6)]
    action='owner' if mode=='race' else 'writer'
    baction='contender' if mode=='race' else 'reader'
    args=(str(module_path),str(state),'',str(evidence))
    a=ctx.Process(target=_capture_child,args=(*args,'A',action,ready,release,blocked,other_done,ca,phase))
    b=ctx.Process(target=_capture_child,args=(*args,'B',baction,ready,release,blocked,other_done,cb,phase))
    errors=[];observed=False
    try:
        a.start()
        if not ready.wait(15):raise TimeoutError('writer did not reach injection boundary')
        b.start()
        if baseline:
            if not cb.wait(15):raise TimeoutError('old contender did not finish without journal lock')
            observed=not blocked.is_set()
        else:
            if not blocked.wait(15):raise TimeoutError('reader/writer did not observe incompatible journal flock')
            observed=not cb.is_set()
        if kill:
            a.kill();a.join(5)
        else:release.set()
        b.join(20);a.join(20)
        if a.is_alive() or b.is_alive():raise TimeoutError('controlled child not finished')
    except BaseException as exc:errors.append(type(exc).__name__+': '+str(exc))
    finally:
        if not kill:
            release.set()
        other_done.set()
        for proc in (a,b):
            if proc.pid is not None and proc.is_alive():
                proc.terminate();proc.join(3)
                if proc.is_alive():proc.kill();proc.join(3)
    children={}
    for role,proc in (('A',a),('B',b)):
        child={'rc':proc.exitcode}
        for stream in ('stdout','stderr'):
            path=evidence/(role+'.'+stream+'.log')
            child[stream]=path.read_text(errors='replace') if path.exists() else '<not created>'
        children[role]=child
        (evidence/(role+'.rc')).write_text(str(proc.exitcode)+'\n')
    snapshots=snapshot_state(state,evidence)
    journal=snapshots.get('r16_execution_journal.jsonl',{})
    sequence=[]
    try:
        sequence=[json.loads(x)['seq'] for x in base64.b64decode(journal.get('base64','')).splitlines() if x.strip()]
    except ValueError:pass
    result={'observed_required_interleaving':observed,'baseline':baseline,'mode':mode,'phase':phase,
            'killed_writer':kill,'children':children,'errors':errors,'journal_sequence':sequence,
            'journal':journal,'module_sha256':hashlib.sha256(Path(module_path).read_bytes()).hexdigest(),
            'evidence_dir':str(evidence)}
    write_json(evidence/'result.json',result)
    return result


if __name__=='__main__':
    if len(sys.argv)!=7 or sys.argv[1]!='--worker':
        raise SystemExit('worker-only test helper')
    # argv length is program,--worker,module,state,control,role,mode (7)
    raise SystemExit(_worker(*sys.argv[2:]))

