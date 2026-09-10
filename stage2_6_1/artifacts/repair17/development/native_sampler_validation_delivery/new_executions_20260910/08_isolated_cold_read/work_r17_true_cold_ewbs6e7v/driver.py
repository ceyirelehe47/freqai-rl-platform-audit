#!/usr/bin/env python3
"""One evidence-only cold read: unchanged package, hidden original roots, no training.

Run on the user's WSL. This script DOES NOT patch the repository, start samplers,
modify old records, or mount anything in the caller's mount namespace.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile

DEFAULT_PACKAGE = Path('/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/native_sampler_validation_delivery/originals/04_full2_pkg')
RUN_ID = 'r17ns_full2_20260909T174348'
CODE_BLOBS = {
    'r17_required_bytes.py': '5c22c2c750b6135ddae839e733edc84f309b40b5',
    'r17_verified_aggregate.py': 'a73da796bba0eedcfa8f776b8577a9744ad7f9bd',
    'aggregate_v6.py': '97953f8fd243d6e94569d9d146151aa776657f18',
}
KEYS = ('full_run_record', 'full_stdout', 'full_junit', 'c3_semantic_receipt',
        'c3_cold_read_report', 'old_counterexamples', 'fixed_flip', 'candidate_reader')
CASES = ('healthy', 'missing', 'append', 'same_length')


def write_new(path: Path, obj):
    with path.open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')


def snapshot(root: Path):
    """Reject links/special files; file identities are bytes, not copied mtimes."""
    result = {}
    for p in sorted(root.rglob('*')):
        st = p.lstat()
        if stat.S_ISDIR(st.st_mode):
            result[str(p.relative_to(root)) + '/'] = None
            continue
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f'package must contain only regular files/directories: {p}')
        h = hashlib.sha256()
        with p.open('rb') as f:
            for b in iter(lambda: f.read(1 << 20), b''):
                h.update(b)
        after = p.stat()
        if (st.st_size, st.st_mtime_ns, st.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError(f'input changed during snapshot: {p}')
        result[str(p.relative_to(root))] = {'bytes': st.st_size, 'sha256': h.hexdigest()}
    return result


def blob(path: Path):
    b = path.read_bytes()
    return hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()


def rebase_config(cfg, destination: Path, run_id: str):
    if not isinstance(cfg, dict) or set(cfg) != set(KEYS):
        raise ValueError('unexpected legacy config keys; do not infer a replacement')
    suffix = f'/runs/{run_id}/run_record.json'
    if not isinstance(cfg['full_run_record'], str) or not cfg['full_run_record'].endswith(suffix):
        raise ValueError('config does not identify the fixed full2 run')
    original_root = PurePosixPath(cfg['full_run_record'][:-len(suffix)])
    if not original_root.is_absolute() or str(original_root) == '/':
        raise ValueError('invalid original package root')
    rebased = {}
    for k, v in cfg.items():
        if not isinstance(v, str) or '..' in PurePosixPath(v).parts:
            raise ValueError(f'invalid config reference: {k}')
        rel = PurePosixPath(v).relative_to(original_root)
        p = destination.joinpath(*rel.parts)
        if not p.is_file() or not p.resolve(strict=True).is_relative_to(destination.resolve(strict=True)):
            raise ValueError(f'missing or external package reference: {k}')
        rebased[k] = str(p)
    return rebased


def prepare(package: Path, work: Path, hidden: list[Path], probes: list[Path], *,
            expected_code=CODE_BLOBS, run_id=RUN_ID):
    """Only copies and new derived configs. Does not mount or mutate the source."""
    package = package.resolve(strict=True)
    work = work.resolve(strict=True)
    hidden = [p.resolve(strict=True) for p in hidden]
    if not all(p.is_dir() and p != Path('/') for p in hidden):
        raise ValueError('each hidden root must be a real directory, never /')
    if any(work.is_relative_to(p) or Path(sys.executable).resolve().is_relative_to(p) for p in hidden):
        raise ValueError('work directory/interpreter would be hidden')
    if not all(p.is_file() for p in probes):
        raise ValueError('visibility probes must exist BEFORE isolation')
    if not all(any(p.resolve().is_relative_to(h) for p in probes) for h in hidden):
        raise ValueError('each original root needs an existing visibility probe')
    before = snapshot(package)
    for name, sha in expected_code.items():
        if blob(package / 'code' / name) != sha:
            raise ValueError(f'package code is not the reviewed candidate: {name}')
    cfg = json.loads((package / 'cold_config.json').read_text())
    (work / 'cases').mkdir()
    (work / 'configs').mkdir()
    (work / 'results').mkdir()
    planned = []
    for name in CASES:
        dst = work / 'cases' / name
        shutil.copytree(package, dst)
        if snapshot(dst) != before:
            raise ValueError('copy differs from its source')
        derived = rebase_config(cfg, dst, run_id)
        tel = dst / 'runs' / run_id / 'telemetry' / 'win_samples.jsonl'
        if name == 'missing':
            tel.unlink()
        elif name == 'append':
            with tel.open('ab') as f:
                f.write(b'\n{"cold_read_test":"appended_only_to_private_copy"}\n')
        elif name == 'same_length':
            b = bytearray(tel.read_bytes())
            if not b:
                raise ValueError('cannot test same-length mutation on an empty file')
            b[0] ^= 1
            tel.write_bytes(b)
        config_path = work / 'configs' / (name + '.json')
        write_new(config_path, derived)
        planned.append({'name': name, 'root': str(dst), 'config': str(config_path),
                        'snapshot': snapshot(dst), 'expected_rc': 0 if name == 'healthy' else 1})
    if snapshot(package) != before:
        raise ValueError('source changed during preparation')
    plan = {'source': str(package), 'source_snapshot': before,
            'run_id': run_id, 'hidden_roots': [str(x) for x in hidden],
            'visibility_probes': [str(p.resolve()) for p in probes],
            'outer_mount_namespace': os.readlink('/proc/self/ns/mnt'),
            'candidate_code_blobs': expected_code, 'cases': planned,
            'note': 'Derived configs are outside copied payloads; old cold_config/record/anchors remain unchanged.'}
    write_new(work / 'plan.json', plan)
    return plan


def invisible(probes):
    observations = []
    for raw in probes:
        try:
            with open(raw, 'rb') as f:
                f.read(1)
        except FileNotFoundError:
            observations.append({'path': raw, 'readable': False, 'reason': 'FileNotFoundError'})
        else:
            raise RuntimeError(f'original file still readable inside isolation: {raw}')
    return observations


def namespace_child(work: Path):
    plan = json.loads((work / 'plan.json').read_text())
    now_ns = os.readlink('/proc/self/ns/mnt')
    if now_ns == plan['outer_mount_namespace']:
        raise RuntimeError('REFUSE: child is not in a separate mount namespace')
    os.chdir(work)
    subprocess.run(['mount', '--make-rprivate', '/'], check=True, timeout=10)
    for case in plan['cases']:
        root = case['root']
        subprocess.run(['mount', '--bind', root, root], check=True, timeout=10)
        subprocess.run(['mount', '-o', 'remount,bind,ro', root], check=True, timeout=10)
    for hidden in plan['hidden_roots']:
        subprocess.run(['mount', '-t', 'tmpfs', '-o', 'size=1m,mode=000', 'r17-cold-hidden', hidden],
                       check=True, timeout=10)
    proofs = {'parent_mount_namespace': plan['outer_mount_namespace'],
              'child_mount_namespace': now_ns, 'before': invisible(plan['visibility_probes'])}
    (work / 'mountinfo.txt').write_text(Path('/proc/self/mountinfo').read_text())
    results = []
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    for case in plan['cases']:
        root = Path(case['root'])
        dest = work / 'results' / case['name']
        dest.mkdir()
        command = [sys.executable, '-B', '-s', str(root / 'code' / 'r17_verified_aggregate.py'),
                   '--root', str(root), '--record', str(root / 'runs' / plan['run_id'] / 'run_record.json'),
                   '--legacy-script', str(root / 'code' / 'aggregate_v6.py'),
                   '--config', case['config'], '--out', str(dest / 'verified.json')]
        write_new(dest / 'command.json', command)
        with (dest / 'stdout.log').open('xb') as so, (dest / 'stderr.log').open('xb') as se:
            proc = subprocess.run(command, stdout=so, stderr=se, env=env, cwd=work, timeout=90)
        (dest / 'rc.txt').write_text(str(proc.returncode) + '\n')
        doc = json.loads((dest / 'verified.json').read_text()) if (dest / 'verified.json').is_file() else {}
        unchanged = snapshot(root) == case['snapshot']
        ok = proc.returncode == case['expected_rc'] and unchanged
        if case['name'] == 'healthy':
            ok = ok and doc.get('overall_ok') is True
        else:
            tel = [r for r in doc.get('required_bytes', {}).get('files', []) if r.get('role') == 'telemetry_win']
            ok = ok and doc.get('overall_ok') is False and len(tel) == 1 and tel[0].get('ok') is False
            if ok and case['name'] == 'append':
                ok = tel[0]['actual']['bytes'] > tel[0]['expected_bytes']
            elif ok and case['name'] == 'same_length':
                ok = (tel[0]['actual']['bytes'] == tel[0]['expected_bytes'] and
                      tel[0]['actual']['sha256'] != tel[0]['expected_sha256'])
            elif ok and case['name'] == 'missing':
                ok = 'FileNotFoundError' in tel[0].get('reason', '')
        results.append({'case': case['name'], 'rc': proc.returncode, 'payload_unchanged': unchanged, 'ok': bool(ok)})
    proofs['after'] = invisible(plan['visibility_probes'])
    write_new(work / 'isolation_proof.json', proofs)
    outcome = {'scope': 'new isolated evidence-only validation; not a historical run or model qualification',
               'isolation_established': True, 'cases': results, 'overall_ok': all(x['ok'] for x in results)}
    write_new(work / 'isolated_result.json', outcome)
    return 0 if outcome['overall_ok'] else 1


def launch(plan, work: Path):
    driver = work / 'driver.py'
    shutil.copyfile(Path(__file__), driver)
    cmd = ['unshare', '--user', '--map-root-user', '--mount', '--fork', '--kill-child',
           '--propagation', 'private', sys.executable, '-B', '-s', str(driver), '--child', str(work)]
    write_new(work / 'launch.json', cmd)
    with (work / 'isolation_stdout.log').open('xb') as so, (work / 'isolation_stderr.log').open('xb') as se:
        p = subprocess.run(cmd, stdout=so, stderr=se, timeout=420)
    (work / 'isolation_rc.txt').write_text(str(p.returncode) + '\n')
    source_ok = snapshot(Path(plan['source'])) == plan['source_snapshot']
    write_new(work / 'source_after.json', {'source_bytes_unchanged': source_ok})
    result_path = work / 'isolated_result.json'
    result = json.loads(result_path.read_text()) if result_path.is_file() else {}
    ok = p.returncode == 0 and source_ok and result.get('overall_ok') is True
    print(json.dumps({'work_dir': str(work), 'overall_ok': ok, 'namespace_rc': p.returncode,
                      'note': 'No fallback to a non-isolated verifier; all outputs retained.'}, ensure_ascii=False))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', type=Path, default=DEFAULT_PACKAGE)
    ap.add_argument('--child', type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.child:
        return namespace_child(args.child)
    work = Path(tempfile.mkdtemp(prefix='r17_true_cold_', dir='/tmp'))
    print('WORK_DIR=' + str(work), flush=True)
    try:
        plan = prepare(args.package, work,
                       [Path('/mnt'), Path('/home/cryptorl/projects')],
                       [args.package / 'code/r17_verified_aggregate.py',
                        Path('/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_supervision.py')])
        return launch(plan, work)
    except Exception as exc:
        write_new(work / 'failure.json', {'type': type(exc).__name__, 'error': str(exc), 'overall_ok': False})
        print(f'validation did not complete: {type(exc).__name__}: {exc}; evidence={work}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
