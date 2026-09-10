#!/usr/bin/env python3
"""Mandatory final gate: every required byte AND the existing semantic aggregate.

Old aggregate scripts/outputs stay immutable. This wrapper calls a selected
existing aggregate into a NEW private output, and never accepts its PASS alone.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from r17_required_bytes import delivery_check


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', required=True, type=Path)
    ap.add_argument('--record', required=True, type=Path)
    ap.add_argument('--legacy-script', required=True, type=Path)
    ap.add_argument('--config', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    args = ap.parse_args(argv)
    target = args.out.absolute()
    try:
        if os.path.lexists(target):
            raise ValueError('new aggregate output required; existing file will not be overwritten')
        # Output must not land in the raw run tree. Other prior outputs are create-only too.
        run_root = args.record.resolve(strict=True).parent
        if target.resolve().is_relative_to(run_root):
            raise ValueError('aggregate output must be outside the raw run directory')
        cfg = json.loads(args.config.read_text(encoding='utf-8'))
        if Path(cfg['full_run_record']).resolve() != args.record.resolve():
            raise ValueError('legacy aggregate config and byte audit refer to different runs')
        audit = delivery_check(args.root, args.record)
        legacy_rc = None; legacy_doc = None
        # A corrupt raw run never becomes healthy by rehashing it into another manifest.
        if audit['delivery_ok']:
            with tempfile.TemporaryDirectory(prefix='r17_aggregate_') as temp:
                report = Path(temp) / 'legacy.json'
                proc = subprocess.run([sys.executable, str(args.legacy_script), '--config',
                                       str(args.config), '--out', str(report)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      timeout=60, check=False)
                legacy_rc = proc.returncode
                legacy_doc = json.loads(report.read_text()) if report.is_file() else None
            # Re-check source bytes after the legacy reader. It cannot mask changes.
            after = delivery_check(args.root, args.record)
            if after['record_sha256'] != audit['record_sha256']:
                after['delivery_ok'] = False
                after['delivery_problems'].append('record changed between validation stages')
            audit = after
        ok = (audit['delivery_ok'] and legacy_rc == 0 and isinstance(legacy_doc, dict)
              and legacy_doc.get('ok') is True)
        out = {'overall_ok': ok, 'required_bytes': audit, 'legacy_rc': legacy_rc,
               'legacy': legacy_doc,
               'note': 'All required raw bytes and native closure must pass; no re-signing or repair.'}
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print('verified_aggregate=' + ('PASS' if ok else 'FAIL'))
        return 0 if ok else 1
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        print(f'verified aggregate failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
