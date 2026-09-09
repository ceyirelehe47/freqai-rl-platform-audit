#!/usr/bin/env python3
"""Read-only supplementary run audit; never repair/re-sign/truncate evidence.

Checks EVERY required file against the existing run_record's size and SHA-256.
Optional Windows-telemetry hints distinguish append/newline hypotheses, without
turning a transformed match into an accepted original. No project imports, no
subprocesses, no process signals, and no output file creation. JSON goes to stdout.
This is not a replacement for the project's delivery/semantic verifier.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

CHUNK = 1024 * 1024
HINT_LIMIT = 32 * CHUNK


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(s: os.stat_result) -> tuple[int, ...]:
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def within(root: Path, p: Path) -> bool:
    return p == root or root in p.parents


def observed_file(path: Path, keep_small: bool = False) -> tuple[dict, bytes | None]:
    """Stream hash a regular file; reject a file that changed during this read."""
    with path.open('rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f'not a regular file: {path}')
        pieces = [] if keep_small and before.st_size <= HINT_LIMIT else None
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = f.read(min(CHUNK, max(1, before.st_size + 1 - size)))
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            if size > before.st_size:
                break  # growth already proves this is not a sealed object
            if pieces is not None:
                if size > HINT_LIMIT:
                    pieces = None
                else:
                    pieces.append(chunk)
        after = os.fstat(f.fileno())
    path_after = path.stat()
    stable = identity(before) == identity(after) == identity(path_after)
    return ({'bytes': size, 'sha256': digest.hexdigest(),
             'stable_during_read': stable},
            b''.join(pieces) if pieces is not None else None)


def parse_utc(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return d if d.tzinfo is not None else None
    except ValueError:
        return None


def telemetry_hints(data: bytes, expected_size: int, expected_sha: str,
                    ended_utc: str | None, run_id: str | None) -> dict:
    """Hypotheses only: do not write the transformed bytes or change verdict."""
    lf = data.replace(b'\r\n', b'\n')
    variants = {'raw': data, 'CRLF_to_LF': lf, 'LF_to_CRLF': lf.replace(b'\n', b'\r\n')}
    comparisons = {}
    for label, candidate in variants.items():
        comparisons[label] = {
            'transformed_bytes': len(candidate),
            'whole_matches_record': len(candidate) == expected_size and sha256(candidate) == expected_sha,
            'prefix_matches_record': len(candidate) >= expected_size and sha256(candidate[:expected_size]) == expected_sha,
        }
    ended = parse_utc(ended_utc)
    counts = Counter()
    invalid_lines = 0
    late_count = 0
    first_late = last_late = None
    first_utc = last_utc = None
    for line in data.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if not isinstance(obj, dict):
                raise ValueError('non-object')
        except (ValueError, UnicodeError):
            invalid_lines += 1
            continue
        event = obj.get('event')
        counts[str(event)] += 1
        stamp = obj.get('utc')
        if isinstance(stamp, str):
            first_utc = first_utc or stamp
            last_utc = stamp
        dt = parse_utc(stamp)
        if event == 'sample' and obj.get('run_id') == run_id and ended and dt and dt > ended:
            late_count += 1
            row = {'utc': stamp, 'seq': obj.get('seq'), 'run_id': obj.get('run_id')}
            first_late = first_late or row
            last_late = row
    return {
        'hypotheses_only_never_accept_transformed_bytes': True,
        'raw_crlf_count': data.count(b'\r\n'), 'raw_lf_count': data.count(b'\n'),
        'comparisons': comparisons, 'event_counts': dict(counts),
        'invalid_json_lines': invalid_lines, 'first_record_utc': first_utc,
        'last_record_utc': last_utc, 'same_run_sample_rows_after_record_end': late_count,
        'first_late_sample': first_late, 'last_late_sample': last_late,
        'time_note': 'Reported clocks only; identify the actual native writer before attributing the cause.'}


def audit(root: Path, record_path: Path, hints: bool = False) -> dict:
    root = root.resolve(strict=True)
    record_path = record_path.resolve(strict=True)
    if not root.is_dir() or not within(root, record_path):
        raise ValueError('record must be inside the declared evidence root')
    record_meta, rb = observed_file(record_path, True)
    if rb is None:
        raise ValueError('run_record exceeds the diagnostic size limit')
    rec = json.loads(rb)
    if not isinstance(rec, dict):
        raise ValueError('run_record is not an object')
    problems = []
    rows = rec.get('required')
    if not isinstance(rows, list) or not rows:
        raise ValueError('required must be a nonempty list')
    seen_paths, seen_roles = set(), set()
    results = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            problems.append(f'required[{index}] is not an object')
            continue
        out = {'role': row.get('role'), 'path': row.get('path'), 'ok': False}
        results.append(out)
        try:
            role, rel = row.get('role'), row.get('path')
            if not isinstance(role, str) or not role or not isinstance(rel, str) or not rel:
                raise ValueError('role/path must be nonempty strings')
            if rel in seen_paths or role in seen_roles:
                raise ValueError('duplicate required role or path')
            seen_paths.add(rel); seen_roles.add(role)
            if Path(rel).is_absolute() or '..' in Path(rel).parts:
                raise ValueError('required path must be root-relative without parent traversal')
            if row.get('live_writers'):
                raise ValueError('required file still has an unconfirmed writer')
            if row.get('status') != 'present':
                raise ValueError(f"required status is {row.get('status')!r}, not present")
            n, h = row.get('bytes'), row.get('sha256')
            if type(n) is not int or n < 0 or not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h):
                raise ValueError('invalid expected bytes or SHA-256')
            path = (root / rel).resolve(strict=True)
            if not within(root, path):
                raise ValueError('required file resolves outside evidence root')
            actual, data = observed_file(path, hints and role == 'telemetry_win')
            out.update(expected_bytes=n, expected_sha256=h, actual=actual)
            out['ok'] = actual['bytes'] == n and actual['sha256'] == h and actual['stable_during_read']
            if not out['ok']:
                out['reason'] = 'size/hash mismatch or file changed during read'
            if hints and role == 'telemetry_win':
                out['telemetry_hints'] = (telemetry_hints(data, n, h, rec.get('ended_utc'), rec.get('run_id'))
                                           if data is not None else {'skipped': 'file exceeds 32 MiB hint limit'})
        except (OSError, ValueError, RuntimeError) as exc:
            out['reason'] = f'{type(exc).__name__}: {exc}'
    record_after, _ = observed_file(record_path)
    record_unchanged = (record_meta['sha256'] == record_after['sha256'] and
                        record_meta['bytes'] == record_after['bytes'] and
                        record_meta['stable_during_read'] and record_after['stable_during_read'])
    if not record_unchanged:
        problems.append('record changed during audit')
    ok = not problems and all(r['ok'] for r in results) and len(results) == len(rows)
    return {'scope': 'supplementary exact-byte audit of every required file; not a qualification verdict',
            'run_id': rec.get('run_id'), 'record': str(record_path),
            'record_sha256': record_meta['sha256'], 'record_unchanged': record_unchanged,
            'declared_evidence_complete': rec.get('evidence_complete'),
            'task_kind': rec.get('task_kind'), 'control_failures': rec.get('control_failures'),
            'business_rc': (rec.get('business') or {}).get('rc'),
            'writers': rec.get('writers'),
            'declared_finalized': rec.get('finalized'), 'ended_utc': rec.get('ended_utc'),
            'required_count': len(rows), 'files': results, 'problems': problems,
            'exact_bytes_ok': ok,
            'note': 'No source is modified. A prefix/newline hypothesis NEVER repairs the original verdict.'}



CORE_PYTEST_ROLES = frozenset(('telemetry_guest', 'telemetry_win', 'alerts',
                             'business_stdout', 'business_stderr', 'junit_xml', 'summary'))
NATIVE_ROLES = frozenset(('native_sampler_identity', 'native_sampler_terminal',
                         'native_sampler_confirmation'))


def delivery_check(root: Path, record_path: Path) -> dict:
    report = audit(root, record_path)
    reasons = []
    if report['declared_finalized'] is not True:
        reasons.append('run is not finalized')
    if report['declared_evidence_complete'] is not True:
        reasons.append('run declared incomplete evidence')
    if report['control_failures'] != []:
        reasons.append('control failures missing or nonempty')
    if type(report['business_rc']) is not int or report['business_rc'] != 0:
        reasons.append('business did not return zero')
    roles = {x.get('role') for x in report['files']}
    if report['task_kind'] == 'pytest' and not CORE_PYTEST_ROLES <= roles:
        reasons.append('pytest required role set incomplete')
    writers = report.get('writers')
    if not isinstance(writers, dict):
        reasons.append('writer closure facts missing')
    else:
        win = writers.get('win')
        if not isinstance(win, dict):
            reasons.append('native sampler closure facts missing')
        elif win.get('protocol') != 'r17-native-sampler-v1':
            reasons.append('legacy interop-only closure is not native process confirmation')
        elif (win.get('native_exit_confirmed') is not True or
              win.get('terminal_verified') is not True or win.get('unconfirmed') is not False):
            reasons.append('native sampler not fully closed')
        if not NATIVE_ROLES <= roles:
            reasons.append('native identity/terminal/confirmation evidence missing')
    report['delivery_problems'] = reasons
    report['delivery_ok'] = report['exact_bytes_ok'] and not reasons
    return report

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--record', required=True, type=Path)
    ap.add_argument('--telemetry-hints', action='store_true')
    args = ap.parse_args(argv)
    try:
        report = audit(args.root, args.record, args.telemetry_hints)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['exact_bytes_ok'] else 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'exact_bytes_ok': False, 'error': f'{type(exc).__name__}: {exc}'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
