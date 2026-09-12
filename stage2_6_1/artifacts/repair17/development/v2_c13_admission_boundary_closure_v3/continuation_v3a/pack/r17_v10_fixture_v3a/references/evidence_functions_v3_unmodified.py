def package_content_index(root: Path) -> dict[str, dict[str, Any]]:
    from r17_v2_c13_admission_guard import tree_index
    return tree_index(Path(root))


def _parse_junit(path: Path):
    from r17_v2_c13_admission_guard import junit_details, stable_bytes
    totals, cases, _diagnostics = junit_details(stable_bytes(path))
    return totals, cases


def verify_package(root: Path, *, authority: Any = None,
                   current_sources: dict[str, Any] | None = None,
                   checks: str = 'full', release_repo: Path | None = None,
                   deploy_root: Path | None = None) -> dict[str, Any]:
    from r17_v2_c13_admission_guard import guarded_verify
    return guarded_verify(root, legacy=_verify_package_core, authority=authority,
                          current_sources=current_sources, checks=checks,
                          release_repo=release_repo, deploy_root=deploy_root)


def build_synthetic_package(root: Path, *, current_sources: dict[str, Any],
                            candidate_commit: str = '0' * 40,
                            n_tests: int = 3) -> dict[str, Any]:
    """Explicit fixture evidence, not a production certificate."""
    from r17_v2_c13_admission_guard import (ROLE_PATHS, no_symlink_path,
                                           stable_bytes, tree_index)
    import tempfile
    root = Path(root)
    no_symlink_path(root)
    if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or root.exists():
        raise EvidenceError('synthetic package requires a fresh dedicated temporary directory')
    root.mkdir(parents=True)
    def write(rel, value):
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            target.write_text(value, encoding='utf-8')
        else:
            target.write_text(json.dumps(value, indent=2, sort_keys=True), encoding='utf-8')
    cases = ''.join(f'<testcase classname="tests.route_c_stage2_6_1.test_synth" '
                    f'name="test_synth_{i}" time="0.001"/>' for i in range(n_tests))
    junit = ('<?xml version="1.0" encoding="utf-8"?><testsuites>'
             '<testsuite name="fixture" '
             f'tests="{n_tests}" failures="0" errors="0" skipped="0">'
             f'{cases}</testsuite></testsuites>')
    write('junit.xml', junit)
    write('collected_tests.txt', '\n'.join(
        f'tests/route_c_stage2_6_1/test_synth.py::test_synth_{i}' for i in range(n_tests))
        + f'\n{n_tests} tests collected\n')
    for rel in ('entry.rc', 'business.rc'):
        write(rel, '0\n')
    write('entry.stdout.log', 'synthetic fixture entry\n')
    write('entry.stderr.log', '')
    write('business.stdout.log', f'{n_tests} passed in 0.01s\n')
    write('business.stderr.log', '')
    write('test_files.sha256', _sha256_bytes(b'synthetic') + '  tests/route_c_stage2_6_1/test_synth.py\n')
    write('critical_tests.json', {'critical_test_files': ['test_synth']})
    write('skips_allowlist.json', {'allowed_skips': []})
    for role, rel in ROLE_PATHS.items():
        if not (root / rel).exists() and role != 'run_record':
            write(rel, {'synthetic': True, 'run_id': 'synthetic-chain', 'role': role})
    rr = {'run_id': 'synthetic-chain', 'task_kind': 'pytest', 'finalized': True,
          'argv': ['python', '-m', 'pytest', '-q', 'tests/route_c_stage2_6_1'],
          'business': {'rc': 0, 'signal': None},
          'started_utc': '2026-09-12T00:00:00Z', 'ended_utc': '2026-09-12T00:00:01Z',
          'required': []}
    entries = []
    for role, rel in ROLE_PATHS.items():
        if role == 'run_record':
            continue
        data = stable_bytes(root / rel)
        sha = _sha256_bytes(data)
        rr['required'].append({'role': role, 'path': rel, 'status': 'present',
                               'sha256': sha, 'bytes': len(data)})
        entries.append({'role': role, 'path': rel, 'sha256': sha, 'size': len(data)})
    write('supervision/run_record.json', rr)
    data = stable_bytes(root / ROLE_PATHS['run_record'])
    entries.append({'role': 'run_record', 'path': ROLE_PATHS['run_record'],
                    'sha256': _sha256_bytes(data), 'size': len(data)})
    write('required_files.json', {'entries': entries})
    members = {m: v['sha256'] for m, v in current_sources.items()}
    write('source_closure.json', {
        'candidate_commit': candidate_commit, 'governance_lock_file': {
            'path': 'synthetic', 'sha256': _sha256_bytes(b'synthetic')},
        'members': members, 'members_digest': _sha256_bytes(_canonical(members).encode())})
    write('import_identity.json', {
        side: {m: {'file': v['path'], 'sha256': v['sha256']} for m, v in current_sources.items()}
        for side in ('release', 'deploy')})
    write('run_meta.json', {
        'format': PACKAGE_FORMAT, 'synthetic': True, 'task_kind': 'pytest',
        'run_id': rr['run_id'], 'candidate_commit': candidate_commit,
        'git_head_at_collect': candidate_commit, 'worktree_clean': True,
        'argv': rr['argv'], 'cwd': '/tmp', 'release_repo': str(root), 'deploy_root': str(root),
        'env': {'python': 'synthetic'}, 'entry_command': 'synthetic',
        'started_utc': rr['started_utc'], 'ended_utc': rr['ended_utc']})
    write('manifest.json', {'format': PACKAGE_FORMAT, 'files': tree_index(root)})
    return {'package_root': str(root), 'package_sha256': package_digest(root)}
