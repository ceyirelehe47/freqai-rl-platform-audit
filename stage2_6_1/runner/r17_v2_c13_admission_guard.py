"""R17 admission boundary v3b (test mapping repair). Standard-library-only, no generation/fit/eval.

This module strengthens evidence consumption; it does not replace the existing
supervisor, sampler, scientific reader, statistics, or C2 selector. Files in a
sealed evidence package are never repaired or re-signed by a verifier.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any, Callable
import xml.etree.ElementTree as ET

RELEASE_ROOT = Path('/mnt/f/trading/freqai-rl-audit')
DEPLOY_ROOT = Path('/home/cryptorl/projects/crypto_rl')
CLAIM_REL = 'stage2_6_1/artifacts/repair17/development/v2_c13_engineering_claim'
EVIDENCE_PREFIX = 'stage2_6_1/artifacts/repair17/development/'
NEW_EVIDENCE_ROOT = EVIDENCE_PREFIX + 'v2_c13_admission_boundary_closure_v3'
CODE_PATHS = ('stage2_6_1/runner', 'stage2_6_1/src', 'stage2_6_1/tests')
ROLE_PATHS = {
    'junit_xml': 'junit.xml',
    'business_stdout': 'business.stdout.log',
    'business_stderr': 'business.stderr.log',
    'telemetry_guest': 'supervision/telemetry/guest_samples.jsonl',
    'telemetry_win': 'supervision/telemetry/win_samples.jsonl',
    'alerts': 'supervision/alerts/alerts.jsonl',
    'native_sampler_identity': 'supervision/native_sampler/identity.json',
    'native_sampler_terminal': 'supervision/native_sampler/terminal.json',
    'native_sampler_confirmation': 'supervision/native_sampler/native_confirmation.json',
    'summary': 'supervision/summary.json',
    'run_record': 'supervision/run_record.json',
}
CRITICAL_TEST_FILES = (
    'test_curriculum261_r17_v2_c13_claim_protocol',
    'test_curriculum261_r17_v2_c13_reader_binding',
    'test_curriculum261_r17_v2_c13_synthetic_chain',
    'test_curriculum261_r17_c2_launch_prep',
    'test_curriculum261_r17_v2_c13_regression_evidence',
    'test_curriculum261_r17_v2_c13_source_provenance',
    'test_curriculum261_r17_v2_c13_pipeline',
    'test_curriculum261_r17_v2_c13_admission_guard',
)
HISTORICAL_SKIP_IDS = frozenset({
    'tests.route_c_stage2_6_1.test_curriculum261_r12_governance_r12.TestHistoricalEvidenceBinding::test_ancestry_semantics_pass',
    'tests.route_c_stage2_6_1.test_curriculum261_r13_governance.TestHistoricalEvidenceBindingR13::test_ancestry_and_r12_clean_chain',
    'tests.route_c_stage2_6_1.test_curriculum261_r14_governance.TestHistoricalEvidenceBindingR14::test_ancestry_and_r13_clean_chain',
    'tests.route_c_stage2_6_1.test_curriculum261_r15_governance.TestHistoricalEvidenceBindingR15::test_ancestry_and_r13_clean_chain',
    'tests.route_c_stage2_6_1.test_curriculum261_r16_governance.TestExecutionSurfaceBytes::test_r16_formal_wrapper_selfcheck_present',
    'tests.route_c_stage2_6_1.test_curriculum261_r16_governance.TestExecutionSurfaceBytes::test_runner_shell_scripts_lf',
    'tests.route_c_stage2_6_1.test_curriculum261_r16_governance.TestHistoricalEvidenceBindingR16::test_ancestry_and_r15_clean_chain',
})


class AdmissionError(RuntimeError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strict_json(data: bytes | str) -> Any:
    def unique(items):
        out = {}
        for k, v in items:
            if k in out:
                raise AdmissionError(f'duplicate JSON key: {k}')
            out[k] = v
        return out

    def invalid(value):
        raise AdmissionError(f'nonfinite JSON value: {value}')

    return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)


def no_symlink_path(path: Path, *, must_exist: bool = False) -> Path:
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise AdmissionError(f'absolute non-escaping path required: {path}')
    probe = Path(path.anchor)
    missing = False
    for part in path.parts[1:]:
        probe /= part
        try:
            st = probe.lstat()
        except FileNotFoundError:
            missing = True
            continue
        if missing:
            raise AdmissionError(f'path changed during traversal: {path}')
        if stat.S_ISLNK(st.st_mode):
            raise AdmissionError(f'symlink component rejected: {probe}')
        if probe != path and not stat.S_ISDIR(st.st_mode):
            raise AdmissionError(f'non-directory ancestor rejected: {probe}')
    if must_exist and missing:
        raise AdmissionError(f'required path missing: {path}')
    return path


def authority_values(repo_root: Path, claim_root: Path, synthetic: bool) -> None:
    """Validate even direct dataclass construction; frozen != trusted."""
    if type(synthetic) is not bool or not isinstance(repo_root, Path) \
            or not isinstance(claim_root, Path):
        raise AdmissionError('authority requires Path roots and an exact bool')
    no_symlink_path(repo_root)
    no_symlink_path(claim_root)
    if not claim_root.is_relative_to(repo_root):
        raise AdmissionError('claim root escapes authority')
    fixed_root = Path('/mnt/f/trading/freqai-rl-audit')
    fixed_claim = fixed_root / 'stage2_6_1/artifacts/repair17/development/v2_c13_engineering_claim'
    if not synthetic:
        if repo_root != fixed_root or claim_root != fixed_claim:
            raise AdmissionError('noncanonical production authority rejected')
    else:
        temp = Path(tempfile.gettempdir()).resolve()
        if not repo_root.is_relative_to(temp) or repo_root == temp:
            raise AdmissionError('synthetic authority requires a dedicated system temp subtree')
        for p in (repo_root, claim_root):
            if p.is_relative_to(fixed_root) or fixed_root.is_relative_to(p):
                raise AdmissionError('synthetic authority overlaps production')


def stable_bytes(path: Path) -> bytes:
    """Reject non-regular files before reading (including FIFOs/devices)."""
    path = no_symlink_path(Path(path), must_exist=True)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise AdmissionError(f'non_regular_file: {path}')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
                 | getattr(os, 'O_NONBLOCK', 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or (st.st_dev, st.st_ino) != (
                before.st_dev, before.st_ino):
            raise AdmissionError(f'file changed before read: {path}')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            data = f.read()
        after = os.fstat(fd)
        now = path.lstat()
        ident = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        if ident(before) != ident(after) or ident(after) != ident(now) \
                or len(data) != after.st_size:
            raise AdmissionError(f'file changed during read: {path}')
        return data
    finally:
        os.close(fd)


def tree_index(root: Path, *, identities: bool = False) -> dict:
    root = no_symlink_path(Path(root), must_exist=True)
    if not root.is_dir():
        raise AdmissionError(f'package_root_missing: {root}')
    out = {}
    def walk(folder):
        for p in sorted(folder.iterdir()):
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode):
                raise AdmissionError(f'non_regular_file: symlink {p}')
            if stat.S_ISDIR(st.st_mode):
                walk(p)
            elif stat.S_ISREG(st.st_mode):
                data = stable_bytes(p)
                meta = {'size': len(data), 'sha256': sha256(data)}
                if identities:
                    meta['identity'] = [st.st_dev, st.st_ino, st.st_mtime_ns, st.st_ctime_ns]
                out[p.relative_to(root).as_posix()] = meta
            else:
                raise AdmissionError(f'non_regular_file: {p}')
    walk(root)
    return out


def junit_details(data: bytes) -> tuple[dict, list, list]:
    """Count testcase entities once; separately audit all declared totals."""
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise AdmissionError('JUnit DTD/entity rejected')
    root = ET.fromstring(data)
    if root.tag not in ('testsuite', 'testsuites'):
        raise AdmissionError('JUnit root must be testsuite/testsuites')
    cases = []
    errors = []
    nodes = list(root.iter('testcase'))
    for node in nodes:
        classname, name = node.get('classname', ''), node.get('name', '')
        skipped = node.find('skipped') is not None
        failed = node.find('failure') is not None
        errored = node.find('error') is not None
        if not classname or not name or sum((skipped, failed, errored)) > 1:
            errors.append(('junit_malformed', 'missing identity or contradictory testcase status'))
        cases.append({'id': classname + '::' + name, 'classname': classname,
                      'name': name, 'skipped': skipped, 'failed': failed, 'error': errored})
    totals = {'tests': len(cases), 'failures': sum(c['failed'] for c in cases),
              'errors': sum(c['error'] for c in cases),
              'skipped': sum(c['skipped'] for c in cases)}
    ids = [c['id'] for c in cases]
    if len(set(ids)) != len(ids):
        errors.append(('junit_duplicate_case', 'duplicate testcase identities'))
    for suite in root.iter():
        if suite.tag not in ('testsuite', 'testsuites'):
            continue
        local = list(suite.iter('testcase'))
        actual = {'tests': len(local),
                  'failures': sum(n.find('failure') is not None for n in local),
                  'errors': sum(n.find('error') is not None for n in local),
                  'skipped': sum(n.find('skipped') is not None for n in local)}
        for key, value in actual.items():
            raw = suite.get(key)
            if raw is None and suite.tag == 'testsuites':
                continue
            if raw is None or re.fullmatch(r'\d+', raw) is None or int(raw) != value:
                errors.append(('junit_count_inconsistent', f'{key}: declared={raw}, actual={value}'))
            if key == 'tests' and raw == '0':
                errors.append(('junit_empty', 'suite declares zero tests'))
    if totals['tests'] == 0:
        errors.append(('junit_empty', 'no testcase entities'))
    if totals['failures']:
        errors.append(('junit_failures_nonzero', 'actual testcase contains failure'))
    if totals['errors']:
        errors.append(('junit_errors_nonzero', 'actual testcase contains error'))
    return totals, cases, errors


def junit_nodeid(case: dict) -> str:
    parts = case['classname'].split('.')
    prefix = ['tests', 'route_c_stage2_6_1']
    if parts[:2] != prefix or len(parts) < 3 or not parts[2].startswith('test_'):
        raise AdmissionError(f'unknown JUnit classname: {case["classname"]}')
    return '/'.join(parts[:3]) + '.py::' + '::'.join(parts[3:] + [case['name']])


def git_checked(repo: Path, *args: str, missing_ok: bool = False) -> bytes:
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=120)
    if p.returncode != 0:
        if missing_ok and p.returncode == 1:
            return b''
        raise AdmissionError(f'git command failed ({p.returncode}): {args}: '
                             f'{p.stderr.decode(errors="replace")[:400]}')
    return p.stdout


def verify_candidate_history(repo: Path, candidate: str, collected_head: str) -> dict:
    """Accept evidence-only descendants, never alter the historical C anchor.

    Inspect every intermediate commit: a code change followed by a revert is
    not an evidence-only lineage. New evidence paths must be absent at C.
    """
    no_symlink_path(repo, must_exist=True)
    if re.fullmatch(r'[a-f0-9]{40}', candidate or '') is None:
        raise AdmissionError('candidate_commit_malformed')
    git_checked(repo, 'cat-file', '-e', candidate + '^{commit}')
    if collected_head != candidate:
        raise AdmissionError('collect-time HEAD must equal the tested candidate')
    head = git_checked(repo, 'rev-parse', 'HEAD').decode().strip()
    git_checked(repo, 'merge-base', '--is-ancestor', candidate, head)
    dirty = git_checked(repo, 'status', '--porcelain=v1', '--', *CODE_PATHS)
    if dirty.strip():
        raise AdmissionError('worktree_not_clean: runner/src/tests drift')
    if git_checked(repo, 'diff', '--name-only', candidate, head, '--', *CODE_PATHS).strip():
        raise AdmissionError('candidate_drift: source or test trees differ')
    commits = git_checked(repo, 'rev-list', '--reverse', candidate + '..' + head).decode().splitlines()
    candidate_paths = set(p.decode() for p in git_checked(
        repo, 'ls-tree', '-r', '--name-only', '-z', candidate, '--', NEW_EVIDENCE_ROOT).split(b'\0') if p)
    for commit in commits:
        parents = git_checked(repo, 'rev-list', '--parents', '-n', '1', commit).decode().split()
        if len(parents) != 2:
            raise AdmissionError('candidate_drift: merge/nonlinear evidence history rejected')
        changed = git_checked(repo, 'diff-tree', '--no-commit-id', '--name-status',
                              '-r', '--no-renames', '-z', parents[1], commit).split(b'\0')
        fields = [v.decode() for v in changed if v]
        if len(fields) % 2:
            raise AdmissionError('malformed git name-status result')
        modes = {}
        for item in git_checked(repo, 'ls-tree', '-r', '-z', commit, '--', NEW_EVIDENCE_ROOT).split(b'\0'):
            if item:
                header, path_bytes = item.split(b'\t', 1)
                modes[path_bytes.decode()] = header.decode().split()[:2]
        for status, path in zip(fields[::2], fields[1::2]):
            if path == '.gitattributes':
                old = git_checked(repo, 'show', parents[1] + ':.gitattributes')
                new = git_checked(repo, 'show', commit + ':.gitattributes')
                suffix = new[len(old):] if new.startswith(old) else b'!'
                allowed = (NEW_EVIDENCE_ROOT + '/** -text').encode()
                if any(line.strip() not in (b'', allowed) for line in suffix.splitlines()):
                    raise AdmissionError('candidate_drift: .gitattributes change not evidence-only')
                continue
            if status not in ('A', 'M') or not path.startswith(NEW_EVIDENCE_ROOT + '/'):
                raise AdmissionError(f'candidate_drift: non-evidence change {status} {path}')
            # ls-tree empty is an unambiguous absent-at-C fact, not swallowed errors.
            if path in candidate_paths:
                raise AdmissionError(f'candidate_drift: historical evidence changed: {path}')
            if modes.get(path) not in (['100644', 'blob'], ['100755', 'blob']):
                raise AdmissionError('candidate_drift: evidence is not a regular Git blob')
    return {'candidate': candidate, 'head': head,
            'evidence_descendants': commits, 'source_test_trees_unchanged': True}


def candidate_test_map(repo: Path, candidate: str) -> dict[str, dict[str, Any]]:
    """Git-owned recursive source -> r17_sync basename/CR-removal mapping.

    Includes support .py files so basename collisions cannot silently overwrite
    a test or conftest. No lookup is guessed from the deployment's directory.
    The candidate, not a caller manifest, determines the complete member set.
    """
    from pathlib import PurePosixPath

    no_symlink_path(Path(repo), must_exist=True)
    if re.fullmatch(r'[0-9a-f]{40}', candidate or '') is None:
        raise AdmissionError('candidate_commit_malformed')
    git_checked(repo, 'cat-file', '-e', candidate + '^{commit}')
    source_root = 'stage2_6_1/tests/'
    deployed_root = 'tests/route_c_stage2_6_1/'
    tree = git_checked(repo, 'ls-tree', '-r', '-z', '--full-tree', candidate,
                       '--', source_root.rstrip('/'))
    result: dict[str, dict[str, Any]] = {}
    folded: dict[str, str] = {}
    for item in tree.split(b'\0'):
        if not item:
            continue
        try:
            header, raw = item.split(b'\t', 1)
            mode, kind, oid = header.decode('ascii').split()
            source = raw.decode('utf-8', errors='strict')
        except (ValueError, UnicodeError) as exc:
            raise AdmissionError('test_source_mapping_invalid: malformed Git tree') from exc
        if not source.endswith('.py'):
            continue
        parts = PurePosixPath(source).parts
        if not source.startswith(source_root) or '..' in parts \
                or any(c in source for c in ('\r', '\n', '\t', '\\')):
            raise AdmissionError('test_source_mapping_invalid: unsafe source path')
        if mode not in ('100644', '100755') or kind != 'blob':
            raise AdmissionError('test_source_mapping_invalid: nonregular Python source: ' + source)
        leaf = parts[-1]
        destination = deployed_root + leaf
        # Also reject case-fold collisions: the release tree may live on DrvFS.
        key = destination.casefold()
        if key in folded:
            raise AdmissionError('test_source_collision: ' + source + ' and '
                                 + result[folded[key]]['source_path'])
        body = git_checked(repo, 'cat-file', 'blob', oid)
        normalized = body.replace(b'\r', b'')  # exact existing tr -d '\r' rule
        result[destination] = {
            'source_path': source, 'deploy_path': destination,
            'git_blob': oid, 'git_mode': mode,
            'source_sha256': sha256(body), 'source_size': len(body),
            'deploy_sha256': sha256(normalized), 'deploy_size': len(normalized),
            'is_test': leaf.startswith('test_'),
            'normalization': 'delete-all-CR-bytes/r17_sync.sh',
        }
        folded[key] = destination
    if not result or not any(row['is_test'] for row in result.values()):
        raise AdmissionError('test_source_mapping_empty: candidate has no tests')
    return dict(sorted(result.items()))


def deployment_test_errors(deploy_root: Path, mapping: dict) -> list:
    """All Python files in the deployed test surface must match the candidate."""
    errors = []
    directory = Path(deploy_root) / 'tests/route_c_stage2_6_1'
    try:
        no_symlink_path(directory, must_exist=True)
        if not directory.is_dir():
            raise AdmissionError('test deployment directory missing')
        found = {}
        # The sync target is flat. A nested source/symlink directory is not an
        # alternate place to find candidates. __pycache__ is not source.
        for path in directory.iterdir():
            st = path.lstat()
            if path.name == '__pycache__' and stat.S_ISDIR(st.st_mode):
                continue
            if path.suffix == '.py':
                found['tests/route_c_stage2_6_1/' + path.name] = path
            elif stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
                errors.append(('test_file_set_changed',
                               'unexpected directory/link in flat test surface: ' + str(path)))
        if set(found) != set(mapping):
            errors.append(('test_file_set_changed', canonical({
                'missing': sorted(set(mapping) - set(found)),
                'extra': sorted(set(found) - set(mapping))})))
        for rel in sorted(set(mapping) & set(found)):
            try:
                body = stable_bytes(found[rel])
                row = mapping[rel]
                if sha256(body) != row['deploy_sha256'] or len(body) != row['deploy_size']:
                    errors.append(('test_file_hash_mismatch',
                                   'deployed bytes differ from candidate normalization: ' + rel))
            except (OSError, AdmissionError) as exc:
                errors.append(('test_file_hash_mismatch', str(exc)))
    except (OSError, AdmissionError) as exc:
        errors.append(('test_file_set_changed', str(exc)))
    return errors


def verify_candidate_tests(repo: Path, candidate: str, deploy_root: Path,
                           manifest: bytes, collection: list[str],
                           cases: list[dict]) -> list:
    """Bind candidate, deployment, manifest and executed file membership.

    Exact testcase multiset equality remains enforced by package_semantics.
    This layer additionally prevents dropping a tracked file from *both* the
    deployed tree and the supplied manifest/collection to obtain a green subset.
    Synthetic full-mode fixtures obey the same rules; no fixture bypass.
    """
    from collections import Counter

    errors = []
    try:
        mapping = candidate_test_map(repo, candidate)
    except (OSError, ValueError, AdmissionError, subprocess.SubprocessError) as exc:
        return [('test_source_mapping_invalid', str(exc))]
    expected = {rel: row for rel, row in mapping.items() if row['is_test']}
    entries: dict[str, str] = {}
    try:
        for line in manifest.decode('utf-8', errors='strict').splitlines():
            m = re.fullmatch(r'([0-9a-f]{64})  (tests/route_c_stage2_6_1/test_[^/\r\n]+\.py)', line)
            if not m:
                errors.append(('test_manifest_malformed', 'malformed test manifest row'))
                continue
            if m[2] in entries:
                errors.append(('test_manifest_duplicate', m[2]))
            entries[m[2]] = m[1]
    except UnicodeError as exc:
        errors.append(('test_manifest_malformed', str(exc)))
    if set(entries) != set(expected):
        errors.append(('test_candidate_set_mismatch', canonical({
            'missing': sorted(set(expected) - set(entries)),
            'extra': sorted(set(entries) - set(expected))})))
    for rel in sorted(set(expected) & set(entries)):
        if entries[rel] != expected[rel]['deploy_sha256']:
            errors.append(('test_file_hash_mismatch',
                           'manifest digest differs from candidate normalized bytes: ' + rel))
    errors.extend(deployment_test_errors(deploy_root, mapping))
    # Use the existing JUnit identity conversion. Comparing path sets does not
    # replace the existing exact ID multiset / testcase-status verification.
    try:
        collected = [node for node in collection if '::' in node]
        executed = [junit_nodeid(case) for case in cases]
        if any(n != 1 for n in Counter(collected).values()):
            errors.append(('collected_membership_mismatch', 'duplicate collected node id'))
        if Counter(collected) != Counter(executed):
            errors.append(('collected_membership_mismatch', 'JUnit/collection node multiset differs'))
        for label, nodes in (('collection', collected), ('execution', executed)):
            represented = {node.split('::', 1)[0] for node in nodes}
            if represented != set(expected):
                errors.append(('test_execution_set_mismatch', canonical({
                    'layer': label, 'missing': sorted(set(expected) - represented),
                    'extra': sorted(represented - set(expected))})))
    except (KeyError, TypeError, AdmissionError) as exc:
        errors.append(('test_execution_set_mismatch', str(exc)))
    return errors


def package_semantics(root: Path, *, synthetic: bool, full: bool,
                      release_repo: Path | None, deploy_root: Path | None,
                      current_sources: dict | None) -> list:
    """Extra binding rules missing from the v2 reader. No trusted summaries."""
    errors = []
    def bad(k, m):
        errors.append((k, m))
    def doc(rel):
        return strict_json(stable_bytes(root / rel))
    run = doc('run_meta.json')
    rr = doc('supervision/run_record.json')
    req = doc('required_files.json')
    closure = doc('source_closure.json')
    critical = doc('critical_tests.json')
    allow = doc('skips_allowlist.json')
    if not isinstance(run, dict) or type(run.get('synthetic')) is not bool:
        bad('synthetic_marker_missing', 'run_meta must explicitly distinguish fixture from production')
    elif run['synthetic'] != synthetic:
        bad('synthetic_package_rejected', 'evidence kind does not match authority/verification context')
    if not isinstance(run, dict) or run.get('worktree_clean') is not True:
        bad('worktree_not_clean', 'recorded candidate was not clean')
    if not isinstance(closure, dict) or closure.get('candidate_commit') != run.get('candidate_commit'):
        bad('candidate_drift', 'run_meta/source_closure candidate mismatch')
    expected_critical = {'test_synth'} if synthetic else set(CRITICAL_TEST_FILES)
    declared = critical.get('critical_test_files') if isinstance(critical, dict) else None
    if not isinstance(declared, list) or any(type(x) is not str for x in declared) \
            or len(declared) != len(set(declared)) or set(declared) != expected_critical:
        bad('critical_policy_mismatch', 'critical modules must equal source-owned nonempty policy')
    allowed = allow.get('allowed_skips') if isinstance(allow, dict) else None
    if not isinstance(allowed, list) or any(type(x) is not str for x in allowed):
        bad('allowlist_malformed', 'skip allowlist must enumerate exact ids')
    elif len(allowed) != len(set(allowed)) or (not synthetic and set(allowed) != HISTORICAL_SKIP_IDS):
        bad('allowlist_policy_mismatch', 'skip policy differs from fixed historical allowlist')
    roles = req.get('entries') if isinstance(req, dict) else None
    expected_roles = set(ROLE_PATHS)
    if not isinstance(roles, list) or any(not isinstance(x, dict) for x in roles):
        bad('required_file_mismatch', 'required entries must be a list of records')
        roles = []
    actual_roles = [e.get('role') for e in roles]
    if Counter(actual_roles) != Counter(expected_roles):
        bad('required_role_set_mismatch', 'required roles missing, duplicate, or unexpected')
    rr_roles = rr.get('required') if isinstance(rr, dict) else None
    if not isinstance(rr_roles, list) or any(not isinstance(x, dict) for x in rr_roles):
        bad('required_role_set_mismatch', 'supervisor required list missing')
        rr_roles = []
    if Counter(e.get('role') for e in rr_roles) != Counter(expected_roles - {'run_record'}):
        bad('required_role_set_mismatch', 'supervisor role set differs from fixed roles')
    sup = {e.get('role'): e for e in rr_roles}
    for e in roles:
        role = e.get('role')
        if role not in ROLE_PATHS or e.get('path') != ROLE_PATHS[role]:
            bad('required_file_mismatch', 'role path is not its fixed package-relative path')
            continue
        data = stable_bytes(root / ROLE_PATHS[role])
        if type(e.get('size')) is not int or e['size'] != len(data) or e.get('sha256') != sha256(data):
            bad('required_file_mismatch', f'role bytes differ: {role}')
        if role != 'run_record':
            s = sup.get(role, {})
            if s.get('status') != 'present' or s.get('sha256') != sha256(data) \
                    or type(s.get('bytes')) is not int or s.get('bytes') != len(data):
                bad('required_role_sha_mismatch', f'supervisor role anchor differs: {role}')
    if not isinstance(rr, dict) or rr.get('finalized') is not True:
        bad('supervision_not_finalized', 'supervisor not finalized')
    if type((rr.get('business') or {}).get('rc')) is not int or (rr.get('business') or {}).get('rc') != 0:
        bad('supervision_rc_mismatch', 'supervisor business rc must be explicitly zero')
    if run.get('task_kind') != 'pytest' or rr.get('task_kind') != 'pytest':
        bad('run_meta_incomplete', 'not a pytest monitored task')
    totals, cases, junit_errors = junit_details(stable_bytes(root / 'junit.xml'))
    errors.extend(junit_errors)
    collection = [s.strip() for s in stable_bytes(root / 'collected_tests.txt').decode().splitlines()
                  if '::' in s]
    try:
        executed_ids = [junit_nodeid(c) for c in cases]
        if Counter(collection) != Counter(executed_ids) or len(set(collection)) != len(collection):
            bad('collected_membership_mismatch', 'JUnit/collection ids must be exactly the same multiset')
    except AdmissionError as exc:
        bad('collected_membership_mismatch', str(exc))
    if len(collection) != totals['tests']:
        bad('collected_count_mismatch', 'collection length differs from testcase entities')
    # Missing summary is not silently accepted; use the final pytest summary line.
    text = stable_bytes(root / 'business.stdout.log').decode('utf-8')
    found = re.findall(r'(\d+) passed(?:, (\d+) skipped)?[^\n]*\bin\b', text)
    if not found or tuple(map(int, (found[-1][0], found[-1][1] or '0'))) != (
            totals['tests'] - totals['failures'] - totals['errors'] - totals['skipped'], totals['skipped']):
        bad('stdout_summary_mismatch', 'stdout pass/skip counts differ from actual testcase statuses')
    for stem in expected_critical:
        members = [c for c in cases if c['classname'].split('.')[2:3] == [stem]]
        if not members:
            bad('critical_module_absent', f'critical module absent: {stem}')
        if any(c['skipped'] for c in members):
            bad('critical_test_skipped', f'critical module contains skip/xfail: {stem}')
    identities = doc('import_identity.json')
    members = closure.get('members', {})
    if not isinstance(members, dict) or not members:
        bad('closure_digest_mismatch', 'source closure cannot be empty')
    if full:
        import ast
        try:
            lock_path = release_repo / 'stage2_6_1/runner/r17_v2_c13_governance_source_lock.py'
            syntax = ast.parse(stable_bytes(lock_path))
            literal = {}
            for node in syntax.body:
                if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                        and isinstance(node.targets[0], ast.Name) \
                        and node.targets[0].id in ('SOURCE_SHA256', 'MEMBER_MODULES'):
                    literal[node.targets[0].id] = ast.literal_eval(node.value)
            if literal.get('SOURCE_SHA256') != members \
                    or set(literal.get('MEMBER_MODULES', ())) != set(members):
                bad('closure_member_mismatch', 'closure differs from the actual governance lock member map')
            for module, expected in members.items():
                rel = ('stage2_6_1/src/' + module.replace('.', '/') + '.py'
                       if module.startswith('rl_curriculum.') else
                       'stage2_6_1/runner/' + module + '.py')
                blob = git_checked(release_repo, 'show', run['candidate_commit'] + ':' + rel)
                if sha256(blob) != expected:
                    bad('closure_member_mismatch', 'source member differs from candidate Git object: ' + module)
        except (OSError, ValueError, KeyError, AdmissionError, subprocess.SubprocessError) as exc:
            bad('closure_member_mismatch', str(exc))
        # In synthetic full-mode fixtures real files are still read and checked.
        for side in ('release', 'deploy'):
            mapping = identities.get(side) if isinstance(identities, dict) else None
            if not isinstance(mapping, dict) or set(mapping) != set(members):
                bad('import_identity_mismatch', f'{side} import member set differs from closure')
                continue
            base = release_repo if side == 'release' else deploy_root
            for name, digest_value in members.items():
                if name.startswith('rl_curriculum.'):
                    rel = ('stage2_6_1/src/' if side == 'release' else 'src/') + name.replace('.', '/') + '.py'
                else:
                    rel = ('stage2_6_1/runner/' if side == 'release' else 'stage2_6_1_runner/') + name + '.py'
                info = mapping[name]
                wanted = base / rel
                if not isinstance(info, dict) or info.get('file') != str(wanted):
                    bad('import_identity_mismatch', f'{side} origin differs from canonical module path: {name}')
                    continue
                try:
                    actual = sha256(stable_bytes(wanted))
                except (OSError, AdmissionError) as exc:
                    bad('import_identity_mismatch', f'missing/nonregular import origin: {wanted}: {exc}')
                    continue
                if actual != info.get('sha256') or actual != digest_value:
                    bad('import_identity_mismatch', f'{side} import bytes differ: {name}')
        try:
            verify_candidate_history(release_repo, run.get('candidate_commit', ''),
                                     run.get('git_head_at_collect', ''))
        except (OSError, AdmissionError, subprocess.SubprocessError) as exc:
            key = 'worktree_not_clean' if 'worktree_not_clean' in str(exc) else 'candidate_drift'
            bad(key, str(exc))
        # Candidate Git tree is the source of the complete recursive test map.
        errors.extend(verify_candidate_tests(
            release_repo, run['candidate_commit'], deploy_root,
            stable_bytes(root / 'test_files.sha256'), collection, cases))
    return errors


def guarded_verify(root: Path, *, legacy: Callable, authority: Any = None,
                   current_sources: dict | None = None, checks: str = 'full',
                   release_repo: Path | None = None, deploy_root: Path | None = None) -> dict:
    """Public verifier wrapper. structural results are never real admission."""
    root = Path(root)
    errors = []
    fmt = 'R17V2C13FullRegressionEvidence-v1'
    fail = lambda k, m: errors.append((k, m))
    report = {'format': fmt, 'checks': {'layers_evaluated': False}, 'summary': {}}
    if checks not in ('full', 'structural'):
        fail('verification_mode_invalid', 'unknown verification mode')
    if not root.exists():
        return {**report, 'ok': False, 'errors': [('package_root_missing', str(root))],
                'package_sha256': None, 'admission_eligible': False}
    try:
        before = tree_index(root, identities=True)
    except (OSError, AdmissionError) as exc:
        msg = str(exc)
        key = 'non_regular_file' if 'non_regular_file' in msg else 'symlink_component'
        if '..' in root.parts:
            key = 'domain_escape'
        return {**report, 'ok': False, 'errors': [(key, msg)],
                'package_sha256': None, 'admission_eligible': False}
    try:
        run = strict_json(stable_bytes(root / 'run_meta.json'))
        synthetic = run.get('synthetic') is True
        if authority is not None:
            from r17_v2_c13_profile import resolve_authority
            auth = resolve_authority(authority)
            if not root.is_relative_to(auth.repo_root):
                fail('domain_escape', 'package not in authority domain')
            if auth.synthetic != synthetic:
                fail('synthetic_package_rejected', 'synthetic evidence cannot satisfy production admission')
            if not auth.synthetic and checks != 'full':
                fail('verification_mode_invalid', 'production admission requires full verification')
        if checks == 'full':
            if synthetic:
                # Full fake-ecosystem tests must explicitly provide synthetic authority.
                if authority is None or not authority.synthetic:
                    fail('synthetic_package_rejected', 'fixture full verification requires explicit synthetic authority')
                release_repo = Path(release_repo or run.get('release_repo', ''))
                deploy_root = Path(deploy_root or run.get('deploy_root', ''))
            else:
                if release_repo not in (None, RELEASE_ROOT) or deploy_root not in (None, DEPLOY_ROOT) \
                        or run.get('release_repo') != str(RELEASE_ROOT) or run.get('deploy_root') != str(DEPLOY_ROOT):
                    fail('domain_escape', 'production source/deploy roots cannot come from caller evidence')
                release_repo, deploy_root = RELEASE_ROOT, DEPLOY_ROOT
        # Validate JSON strictly before passing to the legacy algebra/byte checks.
        for rel in before:
            if rel.endswith('.json'):
                strict_json(stable_bytes(root / rel))
        report = legacy(root, authority=authority, current_sources=current_sources,
                        checks=checks, release_repo=release_repo, deploy_root=deploy_root)
        errors.extend(report.get('errors', []))
        errors.extend(package_semantics(root, synthetic=synthetic, full=checks == 'full',
                                        release_repo=release_repo, deploy_root=deploy_root,
                                        current_sources=current_sources))
    except (OSError, ValueError, TypeError, KeyError, AttributeError, AdmissionError,
            subprocess.SubprocessError, ET.ParseError) as exc:
        fail('evidence_invalid', f'{type(exc).__name__}: {exc}')
    try:
        after = tree_index(root, identities=True)
        if before != after:
            fail('evidence_changed_during_verify', 'sealed tree changed during read')
        index = {k: {field: v[field] for field in ('size', 'sha256')} for k, v in after.items()}
        digest_value = sha256(canonical(index).encode())
    except (OSError, AdmissionError) as exc:
        digest_value = None
        fail('evidence_changed_during_verify', str(exc))
    return {**report, 'ok': not errors, 'errors': errors, 'package_sha256': digest_value,
            'validation_scope': checks,
            'admission_eligible': bool(not errors and checks == 'full'
                                       and authority is not None and not authority.synthetic),
            'guard_version': 'R17AdmissionBoundary-v3b'}
