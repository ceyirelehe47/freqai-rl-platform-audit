#!/usr/bin/env python3
"""Run actual reader CLI against COPIES of the saved eight-pair/p52 evidence.

No business generation, no formal namespaces, no source modification. This
script has not been run in the author's container: it requires a real checkout.
Every destructive argument targets a newly-created external test directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SOURCE = ('stage2_6_1/artifacts/repair17/development/'
          'c3_evidence_generation_slice/engineering_slice')
P52 = ('stage2_6_1/artifacts/repair17/development/blocker_diagnosis/'
       'runs/20260906T134324Z_1475/'
       'generation_failure_envelopes_calibrate_c3_cost_D0_p52.json')
P52_SHA256 = '08fe856acb7c9c720d0930f9909d9bad15783a8ef953b5c4987b9ead096eabef'
READER = 'stage2_6_1/runner/r17_c3_engineering_slice.py'


def snapshot(root: Path):
    result = {}
    for p in [root, *sorted(root.rglob('*'))]:
        st = p.lstat()
        payload = (['link', os.readlink(p)] if p.is_symlink() else
                   ['file', hashlib.sha256(p.read_bytes()).hexdigest()]
                   if p.is_file() else ['directory'])
        result[str(p.relative_to(root))] = [
            st.st_mode, st.st_dev, st.st_ino, st.st_mtime_ns, *payload]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True,
                        help='NEW external directory; refused if it already exists')
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    out = args.out.resolve()
    if out == repo or repo in out.parents:
        parser.error('--out must be outside checkout')
    if out.exists() or out.is_symlink():
        parser.error('--out already exists; preserve it and choose a new run id')
    reader = repo / READER
    src = repo / SOURCE
    original = repo / P52
    if not reader.is_file() or not src.is_dir() or not original.is_file():
        parser.error('Expected reader/saved evidence not found; no generation fallback')
    if hashlib.sha256(original.read_bytes()).hexdigest() != P52_SHA256:
        parser.error('Original p52 identity mismatch; do not repair/overwrite it')
    original_before = snapshot(src)
    original_p52_before = snapshot(original.parent)
    out.mkdir(parents=True)
    records = []

    def setup(name):
        case = out / name
        case.mkdir()
        shutil.copytree(src, case / 'source')
        shutil.copy2(original, case / 'p52.json')
        (case / 'receipts').mkdir()
        (case / 'elsewhere').mkdir()
        return case

    def cli(case, report, expected, *, relative=False, unchanged=False,
            omit_report=False, cwd=None):
        before = snapshot(case)
        source_before = snapshot(case / 'source')
        p52_bytes = (case / 'p52.json').read_bytes()
        argv = [sys.executable, str(reader), '--readback', str(case / 'source'),
                '--p52-envelope', str(case / 'p52.json')]
        if not omit_report:
            arg = os.path.relpath(report, case) if relative else str(report)
            argv += ['--report', arg]
        run = subprocess.run(argv, cwd=cwd or case,
                             capture_output=True, timeout=60, check=False)
        # Capture before writing the observer's own log files.
        after = snapshot(case)
        ok = (run.returncode == expected
              and snapshot(case / 'source') == source_before
              and (case / 'p52.json').read_bytes() == p52_bytes
              and (not unchanged or before == after))
        if expected == 0:
            try:
                rb = json.loads(report.read_text())
                ok = ok and rb.get('readback_verdict') == 'PASS'
            except (OSError, ValueError):
                ok = False
        index = len(records)
        (out / f'{index:02d}_stdout.log').write_bytes(run.stdout)
        (out / f'{index:02d}_stderr.log').write_bytes(run.stderr)
        records.append({'case': case.name, 'argv': argv,
                        'cwd': str(cwd or case), 'expected_rc': expected,
                        'actual_rc': run.returncode,
                        'all_objects_unchanged': before == after,
                        'source_unchanged': snapshot(case / 'source') == source_before,
                        'ok': bool(ok)})
        return run

    case = setup('healthy')
    cli(case, case / 'receipts/new.json', 0)

    for relative in (False, True):
        case = setup('dangling_relative' if relative else 'dangling_cross_directory')
        target = case / 'receipts/result.json'
        target.symlink_to('../elsewhere/missing.json')
        cli(case, target, 2, relative=relative, unchanged=True)

    case = setup('parent_and_terminal_links')
    (case / 'alias').symlink_to('receipts')
    (case / 'receipts/r.json').symlink_to('../elsewhere/missing.json')
    cli(case, case / 'alias/r.json', 2, unchanged=True)

    for tail in ('recipe.json', 'new/deep/r.json'):
        case = setup('source_dotdot_existing' if tail == 'recipe.json'
                     else 'source_dotdot_missing')
        (case / 'source/child').mkdir(exist_ok=True)
        (case / 'receipts/alias').symlink_to('../source/child')
        cli(case, case / 'receipts/alias' / '..' / tail, 2, unchanged=True)

    for tail, name in [('new.json', 'not_directory'),
                       ('../new.json', 'not_directory_dotdot')]:
        case = setup(name)
        (case / 'receipts/file').write_text('KEEP')
        cli(case, case / 'receipts/file' / tail, 2, unchanged=True)

    case = setup('loop_ancestor')
    (case / 'receipts/a').symlink_to('b')
    (case / 'receipts/b').symlink_to('a')
    cli(case, case / 'receipts/a/r.json', 2, unchanged=True)

    case = setup('existing_receipt')
    target = case / 'receipts/r.json'
    cli(case, target, 0)
    cli(case, target, 2, unchanged=True)

    case = setup('healthy_parent_link')
    (case / 'alias').symlink_to('receipts')
    cli(case, case / 'alias/new.json', 0)

    case = setup('healthy_nested_new')
    cli(case, case / 'receipts/new/deep/r.json', 0)

    case = setup('default_report_inside_input')
    cli(case, case / 'unused', 2, unchanged=True, omit_report=True,
        cwd=case / 'source')

    source_unchanged = (snapshot(src) == original_before
                        and snapshot(original.parent) == original_p52_before)
    summary = {'scope': 'actual checkout reader CLI, saved-data copies only',
               'python': sys.version, 'reader': str(reader),
               'reader_sha256': hashlib.sha256(reader.read_bytes()).hexdigest(),
               'original_evidence_unchanged': source_unchanged,
               'cases': records,
               'ok': source_unchanged and all(r['ok'] for r in records)}
    (out / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({'ok': summary['ok'], 'cases': len(records),
                      'result': str(out / 'result.json')}, ensure_ascii=False))
    return 0 if summary['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
