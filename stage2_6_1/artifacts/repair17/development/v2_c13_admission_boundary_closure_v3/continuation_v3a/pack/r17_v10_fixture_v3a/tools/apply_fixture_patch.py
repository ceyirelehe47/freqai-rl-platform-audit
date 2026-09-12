#!/usr/bin/env python3
"""Pinned one-file test-fixture fix. No production changes, tests, sync or Git writes.

Default mode checks only. --apply requires a fresh external recovery directory.
Unknown HEAD/blob/worktree state and payload drift stop before source writes.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

BASELINE = '1ea193c0f1eb710e37aa23aa89f261617eb93c43'
BRANCH = 'route-c-stage2-6-1-repair17'
TARGET = 'stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py'
TARGET_BLOB = '92350d8ae5bdace6801efc120f83d616e2a24d29'
SUPPORT = 'stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_claim_protocol.py'
SUPPORT_BLOB = '0e6b2746df08d56b4ef4537dfba232b72cd79b75'
HISTORICAL_LOCK = 'stage2_6_1/runner/r17_v2_c13_source_lock.py'
HISTORICAL_SHA256 = 'c9152b62192a93571c16ba62e0ef2e70522f108726f3eb83fd25d48007a77c55'
ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'payload/pipeline_fixture.py'
PAYLOAD_SHA256 = 'ee44796d4bdd0c2854be600d5bc3a01cf7862a9de68fe98f69d5703f1a24dc3f'
NEW_TESTS = ('test_v10_fixture_is_evidence_backed_and_not_production',
             'test_v10_unhealthy_fixture_is_still_rejected')
CODE_PATHS = ('stage2_6_1/runner', 'stage2_6_1/src', 'stage2_6_1/tests', '.gitattributes')


def git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, timeout=120)
    if proc.returncode:
        raise RuntimeError(f'git {args} failed: {proc.stderr.decode(errors="replace")[:600]}')
    return proc.stdout


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def definitions(text: str) -> dict:
    result = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in result:
                raise RuntimeError(f'duplicate top-level definition: {node.name}')
            result[node.name] = node
    return result


def source_of(text: str, node: ast.AST) -> str:
    start = min([node.lineno] + [n.lineno for n in getattr(node, 'decorator_list', [])])
    return ''.join(text.splitlines(keepends=True)[start-1:node.end_lineno])


def transform(before: bytes, payload: bytes) -> bytes:
    """Replace only _claim_fixture; leave every existing test body unchanged."""
    text, code = before.decode('utf-8'), payload.decode('utf-8')
    original, replacement = definitions(text), definitions(code)
    if set(replacement) != {'_claim_fixture', *NEW_TESTS}:
        raise RuntimeError('payload definition set differs from one fixture + two test functions')
    if '_claim_fixture' not in original:
        raise RuntimeError('fixture definition missing')
    if any(name in original for name in NEW_TESTS):
        raise RuntimeError('new test already exists; refuse repeat application')
    for name in ('test_v10_one_shot_claim', 'test_v10_corrupted_claim_is_consumed_not_retried'):
        if name not in original:
            raise RuntimeError(f'required unchanged regression absent: {name}')
    old = original['_claim_fixture']
    lines = text.splitlines(keepends=True)
    lines[old.lineno-1:old.end_lineno] = [source_of(code, replacement['_claim_fixture']).rstrip() + '\n']
    out = ''.join(lines)
    out += '\n\n# v3a: fixture migration must not relax claim admission.\n'
    out += '\n\n'.join(source_of(code, replacement[name]).rstrip() for name in NEW_TESTS) + '\n'
    resulting = definitions(out)
    for name, node in original.items():
        if name != '_claim_fixture' and source_of(text, node) != source_of(out, resulting[name]):
            raise RuntimeError('unrelated definition changed: ' + name)
    compile(out, TARGET, 'exec')
    return out.encode('utf-8')


def regular_path(repo: Path, relative: str) -> Path:
    target = repo / relative
    for p in (repo, *[repo.joinpath(*Path(relative).parts[:i])
                      for i in range(1, len(Path(relative).parts)+1)]):
        if p.is_symlink():
            raise RuntimeError(f'symlink path component: {p}')
    if not target.is_file() or not stat.S_ISREG(target.lstat().st_mode):
        raise RuntimeError('target is not a regular file: ' + relative)
    return target


def run(repo: Path, *, apply: bool, recovery: Path | None) -> dict:
    repo = repo.resolve(strict=True)
    if git(repo, 'rev-parse', 'HEAD').decode().strip() != BASELINE:
        raise RuntimeError('HEAD differs from pinned failure baseline; do not reset or merge automatically')
    if git(repo, 'branch', '--show-current').decode().strip() != BRANCH:
        raise RuntimeError('wrong branch')
    if git(repo, 'status', '--porcelain=v1', '--', *CODE_PATHS).strip():
        raise RuntimeError('source/test/config worktree dirty; do not overwrite')
    if git(repo, 'rev-parse', 'HEAD:' + TARGET).decode().strip() != TARGET_BLOB:
        raise RuntimeError('target Git blob mismatch')
    if git(repo, 'rev-parse', 'HEAD:' + SUPPORT).decode().strip() != SUPPORT_BLOB:
        raise RuntimeError('healthy protocol helper Git blob mismatch')
    target = regular_path(repo, TARGET)
    support = regular_path(repo, SUPPORT)
    # Exact Git objects are the application basis, accepting only existing CRLF representation.
    preimage = git(repo, 'show', 'HEAD:' + TARGET)
    original_worktree = target.read_bytes()
    if original_worktree not in (preimage, preimage.replace(b'\n', b'\r\n')):
        raise RuntimeError('target worktree does not match pinned Git bytes/CRLF representation')
    support_blob = git(repo, 'show', 'HEAD:' + SUPPORT)
    if support.read_bytes() not in (support_blob, support_blob.replace(b'\n', b'\r\n')):
        raise RuntimeError('support helper worktree drift')
    old_lock = regular_path(repo, HISTORICAL_LOCK)
    if sha(old_lock.read_bytes()) != HISTORICAL_SHA256:
        raise RuntimeError('historical lock bytes differ; no change authorized')
    payload = PAYLOAD.read_bytes()
    if sha(payload) != PAYLOAD_SHA256:
        raise RuntimeError('payload SHA-256 mismatch')
    output = transform(preimage, payload)
    report = {'baseline': BASELINE, 'target': TARGET, 'target_blob_before': TARGET_BLOB,
              'before_git_sha256': sha(preimage), 'before_worktree_sha256': sha(original_worktree),
              'after_sha256': sha(output), 'applied': apply,
              'modified_files': [TARGET], 'existing_test_bodies_unchanged': True,
              'added_test_functions': list(NEW_TESTS), 'added_collected_cases': 5,
              'production_code_changes': 0, 'new_experiment_authorized': False}
    if not apply:
        return report
    if recovery is None:
        raise RuntimeError('--apply requires a fresh external --recovery directory')
    recovery = recovery.absolute()
    if recovery.exists() or recovery.is_symlink() or recovery.resolve().is_relative_to(repo):
        raise RuntimeError('recovery must be fresh and outside repository')
    for parent in recovery.parents:
        if parent.is_symlink():
            raise RuntimeError('recovery parent is a symlink')
    recovery.mkdir(parents=True, exist_ok=False)
    (recovery / 'target.before.worktree.py').write_bytes(original_worktree)
    (recovery / 'target.before.git.py').write_bytes(preimage)
    (recovery / 'target.after.py').write_bytes(output)
    (recovery / 'application.json').write_text(json.dumps(report, indent=2) + '\n')
    if target.read_bytes() != original_worktree:
        raise RuntimeError('target changed during preflight; no write performed')
    fd, tmp = tempfile.mkstemp(prefix='.' + target.name + '.', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, stat.S_IMODE(target.stat().st_mode))
        os.replace(tmp, target)
        dfd = os.open(target.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
    if sha(target.read_bytes()) != report['after_sha256']:
        raise RuntimeError('post-write hash mismatch; preserve recovery and stop')
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--recovery', type=Path)
    args = parser.parse_args(argv)
    try:
        report = run(args.repo, apply=args.apply, recovery=args.recovery)
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f'PATCH_STOP: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
