"""Per-run Windows sampler lifecycle. No business imports or process-name kills.

The interop Popen is only a transport handle. Native exit evidence comes from
r17_win_sampler_control.ps1, which validates creation time on one native handle.
A clean terminal acknowledgement PLUS native exit PLUS exact bytes is required.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import time

PROTOCOL = 'r17-native-sampler-v1'
JSON_LIMIT = 64 * 1024


def _file_identity(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def _load(path: Path):
    with path.open('rb') as f:
        data = f.read(JSON_LIMIT + 1)
    if len(data) > JSON_LIMIT:
        raise ValueError('control JSON exceeds limit')
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError('control JSON must be an object')
    return value


def _new_json(path: Path, value):
    """Create a complete control file without replacing existing evidence."""
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(12) + '.tmp')
    owned = False
    try:
        with tmp.open('xb') as f:
            owned = True
            f.write(payload); f.flush(); os.fsync(f.fileno())
        os.link(tmp, path)  # create-only, works on the supported local/DrvFS volumes
    finally:
        if owned:
            tmp.unlink(missing_ok=True)


def _same_win_path(a, b):
    return (isinstance(a, str) and isinstance(b, str) and
            ntpath.normcase(ntpath.normpath(a)) == ntpath.normcase(ntpath.normpath(b)))


def validate_identity(doc, run_id, token, out_win):
    if doc.get('protocol') != PROTOCOL or doc.get('run_id') != run_id or doc.get('token') != token:
        raise ValueError('native identity belongs to another launch')
    if type(doc.get('pid')) is not int or not 0 < doc['pid'] < 2**32:
        raise ValueError('native PID invalid')
    creation = doc.get('creation_filetime')
    if not isinstance(creation, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', creation) or int(creation) >= 2**64:
        raise ValueError('native creation time invalid')
    if not _same_win_path(doc.get('out_file'), out_win):
        raise ValueError('native identity output path mismatch')
    return dict(doc)


def validate_confirmation(doc, ident):
    for key in ('protocol', 'run_id', 'token', 'pid', 'creation_filetime'):
        if doc.get(key) != ident.get(key) or type(doc.get(key)) is not type(ident.get(key)):
            raise ValueError('native confirmation identity mismatch: ' + key)
    if doc.get('native_exited') is not True:
        raise ValueError('native exit unconfirmed: ' + str(doc.get('status')))
    status = doc.get('status')
    actual = doc.get('actual_creation_filetime')
    matched, forced = doc.get('identity_matched'), doc.get('forced')
    if status in ('exited', 'forced_exited'):
        if matched is not True or actual != ident['creation_filetime']:
            raise ValueError('native handle creation time not bound')
        if forced is not (status == 'forced_exited'):
            raise ValueError('native force status contradictory')
    elif status == 'absent':
        if doc.get('win32_error') != 87 or matched is not False or forced is not False:
            raise ValueError('absence not certified by native query')
    elif status == 'pid_reused':
        if (not isinstance(actual, str) or not actual.isdigit() or int(actual) <= 0 or
                actual == ident['creation_filetime'] or matched is not False or forced is not False):
            raise ValueError('PID reuse proof invalid')
    else:
        raise ValueError('unknown native confirmation status')
    return dict(doc)


def check_terminal(doc, ident, telemetry: Path, max_bytes: int):
    validate_identity(doc, ident['run_id'], ident['token'], ident['out_file'])
    if doc['pid'] != ident['pid'] or doc['creation_filetime'] != ident['creation_filetime']:
        raise ValueError('terminal belongs to another process instance')
    if doc.get('clean') is not True or doc.get('reason') not in ('stop_requested', 'max_seconds'):
        raise ValueError('native terminal did not confirm clean telemetry closure')
    n, digest = doc.get('bytes'), doc.get('sha256')
    if type(n) is not int or n < 0 or n > max_bytes:
        raise ValueError('terminal telemetry size invalid or over budget')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('terminal telemetry digest invalid')
    with telemetry.open('rb') as f:
        st0 = os.fstat(f.fileno())
        if not stat.S_ISREG(st0.st_mode) or st0.st_size != n:
            raise ValueError('telemetry size differs from terminal acknowledgement')
        h, count = hashlib.sha256(), 0
        # Bounded at the certified size + one byte; never chase a growing file.
        while count <= n:
            chunk = f.read(min(1 << 20, n + 1 - count))
            if not chunk:
                break
            h.update(chunk); count += len(chunk)
        st1 = os.fstat(f.fileno())
    st2 = telemetry.stat()
    if count != n or h.hexdigest() != digest or _file_identity(st0) != _file_identity(st1) or _file_identity(st1) != _file_identity(st2):
        raise ValueError('telemetry changed or hash differs from terminal acknowledgement')
    return {'bytes': n, 'sha256': digest, 'stable_during_read': True}


class NativeSamplerControl:
    def __init__(self, run_id: str, control_dir: Path, telemetry: Path,
                 out_win: str, control_win: str, powershell: str,
                 controller_win: str, max_bytes: int, *, clock=time.monotonic):
        self.run_id = run_id
        self.directory = Path(control_dir)
        self.telemetry = Path(telemetry)
        self.out_win, self.control_win = out_win, control_win
        self.powershell, self.controller_win = powershell, controller_win
        self.max_bytes, self.clock = max_bytes, clock
        self.token = secrets.token_hex(32)
        self.identity = None
        self.result = None
        self.directory.mkdir(parents=False, exist_ok=False)

    def required(self):
        return [
            {'role': 'native_sampler_identity', 'path': self.directory / 'identity.json'},
            {'role': 'native_sampler_terminal', 'path': self.directory / 'terminal.json'},
            {'role': 'native_sampler_confirmation', 'path': self.directory / 'native_confirmation.json'},
        ]

    def refresh_identity(self):
        doc = validate_identity(_load(self.directory / 'identity.json'), self.run_id,
                                self.token, self.out_win)
        if self.identity is not None and self.identity != doc:
            raise ValueError('native launch identity changed after acceptance')
        self.identity = doc
        return doc

    def wait_identity(self, deadline: float, cancelled=lambda: False):
        while self.clock() < deadline and not cancelled():
            try:
                return self.refresh_identity()
            except FileNotFoundError:
                time.sleep(min(0.05, max(0.0, deadline - self.clock())))
        raise TimeoutError('native sampler did not publish launch identity within startup window')

    def _invoke(self, request: dict, deadline: float):
        request_file = self.directory / 'native_request.json'
        _new_json(request_file, request)
        win_request = ntpath.join(self.control_win, 'native_request.json')
        # No pipe capture: a broken Windows helper cannot block shutdown on full stdout.
        proc = subprocess.Popen([self.powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', self.controller_win, '-RequestFile', win_request],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        result_file = self.directory / 'native_confirmation.json'
        try:
            while self.clock() < deadline:
                try:
                    return _load(result_file)  # atomically published, never later rewritten
                except FileNotFoundError:
                    pass
                time.sleep(min(0.05, max(0.0, deadline - self.clock())))
            raise TimeoutError('native confirmation deadline expired')
        finally:
            # Reap only the CONTROLLER transport. Its exit does not prove sampler exit.
            try:
                if proc.poll() is None:
                    remaining = max(0.0, deadline - self.clock())
                    if remaining:
                        proc.wait(timeout=min(0.2, remaining))
                if proc.poll() is None:
                    proc.kill()
                    try: proc.wait(timeout=min(0.2, max(0.0, deadline-self.clock())))
                    except subprocess.TimeoutExpired: pass
            except (OSError, subprocess.SubprocessError):
                pass

    def close(self, deadline: float, *, invoke=None):
        # One close attempt per run; a retry cannot erase an earlier failure.
        if self.result is not None:
            return dict(self.result)
        state = {'protocol': PROTOCOL, 'stop_requested': False, 'started': True,
                 'native_exit_confirmed': False, 'exited': False, 'waited': False,
                 'unconfirmed': True, 'terminal_verified': False, 'errors': [],
                 'token': self.token, 'run_id': self.run_id}
        self.result = state  # set before I/O, including error/timeout paths
        try:
            if self.clock() >= deadline:
                raise TimeoutError('no remaining shutdown budget')
            # Cooperative request failure must not prevent an independent,
            # instance-bound native stop attempt. Keep the failure sticky.
            try:
                _new_json(self.directory / 'stop.json',
                          {'protocol': PROTOCOL, 'run_id': self.run_id, 'token': self.token})
                state['stop_requested'] = True
            except OSError as exc:
                state['errors'].append(f'stop_request: {type(exc).__name__}: {exc}'[:400])
            ident = self.refresh_identity()
            state.update(windows_pid=ident['pid'], creation_filetime=ident['creation_filetime'])
            remaining = max(0.0, deadline - self.clock())
            if remaining <= 0:
                raise TimeoutError('no budget for native process confirmation')
            budget_ms = int(remaining * 1000)
            # Reserve force confirmation time instead of consuming all budget cooperatively.
            request = {k: ident[k] for k in ('protocol','run_id','token','pid','creation_filetime')}
            request.update(budget_ms=budget_ms,
                           cooperate_ms=min(8000, budget_ms // 2),
                           force_wait_ms=min(5000, budget_ms // 3),
                           expires_utc=(datetime.now(timezone.utc)+timedelta(seconds=remaining)).isoformat())
            state['waited'] = True
            reply = (invoke or self._invoke)(request, deadline)
            if self.clock() > deadline:
                raise TimeoutError('native confirmation arrived outside shutdown budget')
            proof = validate_confirmation(reply, ident)
            state.update(native_exit_confirmed=True, exited=True,
                         native_status=proof['status'], forced=proof['forced'],
                         native_proof=proof)
            # A proof of death alone is not a clean telemetry close (e.g. forced termination).
            terminal = _load(self.directory / 'terminal.json')
            observed = check_terminal(terminal, ident, self.telemetry, self.max_bytes)
            state.update(terminal_verified=True, telemetry=observed,
                         terminal_reason=terminal['reason'], unconfirmed=bool(state['errors']))
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            state['errors'].append(f'{type(exc).__name__}: {exc}'[:400])
        return dict(state)
