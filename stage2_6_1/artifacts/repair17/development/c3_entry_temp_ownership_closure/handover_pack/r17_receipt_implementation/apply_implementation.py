#!/usr/bin/env python3
"""Apply the supplied inline implementation to the exact reviewed reader.

Dry-run by default. No network, commits, staging, reset, or data generation.
Uses a complete-file Git blob guard and git apply's checked multi-file patch.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import sys

BASE_COMMIT = '24eaa81cf36b1bfa8755145ba56d1996653e9d50'
BASE_READER_BLOB = '93d0172b6428b1710ebc21900247473b5a4d3e64'
READER = 'stage2_6_1/runner/r17_c3_engineering_slice.py'
TEST = ('stage2_6_1/tests/route_c_stage2_6_1/'
        'test_curriculum261_r17_receipt_entry_cleanup_unit.py')
START = '# ---------------------------------------- 回执写入隔离(WP2,写前准入)\n'
END = '\n\nclass _Problems:'
REPLACED_NAMES = {
    'ReportTargetRejected', 'ReceiptWriteError', '_resolve_target_strict',
    '_assert_report_target_safe', '_atomic_write_receipt',
}
BUNDLE = Path(__file__).resolve().parent


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def transform(source: str, block: str) -> str:
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError('Expected unique reviewed helper boundaries were not found')
    a = source.index(START)
    b = source.index(END, a)
    updated = source[:a] + block.rstrip() + source[b:]
    # Compile the FULL real reader; additionally ensure all pre-existing
    # unrelated functions/classes retain the same syntax tree.
    old_tree = ast.parse(source)
    new_tree = ast.parse(updated)
    new_defs = {n.name: n for n in new_tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for n in old_tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.name not in REPLACED_NAMES:
                if n.name not in new_defs or ast.dump(n) != ast.dump(new_defs[n.name]):
                    raise ValueError(f'Unexpected change outside receipt helpers: {n.name}')
    compile(updated, READER, 'exec')
    return updated


def diff_file(name: str, old: str, new: str, added: bool = False) -> str:
    heading = f'diff --git a/{name} b/{name}\n'
    if added:
        heading += 'new file mode 100644\n'
    return heading + ''.join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile='/dev/null' if added else f'a/{name}', tofile=f'b/{name}'))


def run_git(repo: Path, *args, data: bytes | None = None):
    return subprocess.run(['git', '-C', str(repo), *args], input=data,
                          capture_output=True, check=False, timeout=30)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True, type=Path,
                   help='Git checkout with stage2_6_1/ layout (the published repository)')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--check', action='store_true', help='Default: validate only')
    group.add_argument('--apply', action='store_true', help='Apply after every guard passes')
    p.add_argument('--patch-out', type=Path,
                   help='Optional NEW file outside checkout for the generated git patch')
    args = p.parse_args(argv)
    repo = args.repo.resolve(strict=True)
    probe = run_git(repo, 'rev-parse', '--show-toplevel')
    if probe.returncode or Path(probe.stdout.decode().strip()).resolve() != repo:
        p.error('--repo must be the Git repository root, not the deployment tree')
    head = run_git(repo, 'rev-parse', 'HEAD').stdout.decode().strip()
    anc = run_git(repo, 'merge-base', '--is-ancestor', BASE_COMMIT, 'HEAD')
    if anc.returncode:
        p.error('Reviewed baseline is not a local ancestor; fetch/read history first, never reset')
    reader_path = repo / READER
    if reader_path.is_symlink():
        p.error('Reader path is a symlink; refusing replacement')
    raw = reader_path.read_bytes()
    actual_blob = git_blob(raw)
    if actual_blob != BASE_READER_BLOB:
        p.error(f'Reader changed: {actual_blob} != {BASE_READER_BLOB}. '
                'Do not force; inspect the newer implementation.')
    test_path = repo / TEST
    if test_path.exists() or test_path.is_symlink():
        p.error(f'New test path already exists; not overwriting: {TEST}')
    block = (BUNDLE / 'implementation/receipt_block.py').read_text(encoding='utf-8')
    tests = (BUNDLE / 'tests' / Path(TEST).name).read_text(encoding='utf-8')
    updated = transform(raw.decode('utf-8'), block)
    compile(tests, TEST, 'exec')
    patch = (diff_file(READER, raw.decode('utf-8'), updated)
             + diff_file(TEST, '', tests, added=True)).encode('utf-8')
    checked = run_git(repo, 'apply', '--check', '--whitespace=error', '-', data=patch)
    if checked.returncode:
        print(checked.stderr.decode(), file=sys.stderr)
        return 2
    if args.patch_out:
        dest = args.patch_out.resolve()
        if dest == repo or repo in dest.parents:
            p.error('--patch-out must be outside the checkout')
        with dest.open('xb') as f:
            f.write(patch)
    if args.apply:
        # Detect an ordinary intervening edit before applying. git apply
        # does its own hunk checks too; no --reject/--3way/force fallback.
        if reader_path.read_bytes() != raw:
            p.error('Reader changed after validation; nothing applied')
        applied = run_git(repo, 'apply', '--whitespace=error', '-', data=patch)
        if applied.returncode:
            print(applied.stderr.decode(), file=sys.stderr)
            return 2
        if reader_path.read_bytes() != updated.encode():
            raise RuntimeError('Post-apply reader verification failed; inspect working tree')
    print(json.dumps({
        'mode': 'APPLIED' if args.apply else 'CHECK_ONLY',
        'baseline': BASE_COMMIT, 'checkout_head': head,
        'original_reader_git_blob': actual_blob,
        'candidate_reader_git_blob': git_blob(updated.encode()),
        'candidate_reader_sha256': hashlib.sha256(updated.encode()).hexdigest(),
        'inline_implementation_sha256': hashlib.sha256(block.encode()).hexdigest(),
        'changed_paths': [READER, TEST],
        'unrelated_functions_preserved': True,
        'repository_tests_executed': False,
        'note': 'Working-tree patch only. No commit, push, formal run, or business generation.'
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'Implementation not applied: {type(exc).__name__}: {exc}', file=sys.stderr)
        raise SystemExit(2)
