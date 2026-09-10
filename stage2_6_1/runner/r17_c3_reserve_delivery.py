#!/usr/bin/env python3
"""Read-only composition: monitored-run required bytes AND C3 batch semantics.
No historical aggregate is rewritten; no training or generation imports.
"""
import argparse
from pathlib import Path
import sys
from r17_c3_reserve_batch import verify, read_json, canonical, file_meta, require
from r17_required_bytes import delivery_check


def check(root, record):
    root=root.resolve(strict=True); record=record.resolve(strict=True)
    require(record.is_relative_to(root), 'record outside delivery root')
    identity=file_meta(record)
    r=read_json(record)
    require(r.get('task_kind')=='engineering', 'not an engineering run')
    require(r.get('run_id')==record.parent.name, 'run identity/path mismatch')
    argv=r.get('argv')
    require(isinstance(argv,list) and len(argv)==5 and Path(argv[1]).name=='r17_c3_reserve_batch.py'
            and argv[2:4]==['run','--out'], 'business was not the fixed reserve-batch command')
    # Archived absolute argv is a provenance string, not a path to read.
    original_out=Path(argv[4])
    require(original_out.name=='c3_finite_reserve' and original_out.parent.name==r['run_id'],
            'business output was not the expected child of this run')
    batch=record.parent/'c3_finite_reserve'
    native=delivery_check(root,record)
    semantics=verify(batch)
    after=delivery_check(root,record)
    require(identity==file_meta(record), 'record changed during composed verification')
    ok=native['delivery_ok'] and after['delivery_ok'] and semantics['engineering_batch_complete']
    return {'overall_ok':ok,'native_and_required_before':native,'batch':semantics,
            'native_and_required_after':after,
            'scope':'engineering batch only; not calibration/qualification/Stage 2.6.1 PASS'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True); p.add_argument('--record',type=Path,required=True)
    a=p.parse_args()
    try:
        result=check(a.root,a.record); print(canonical(result)); return 0 if result['overall_ok'] else 1
    except Exception as exc:
        print(canonical({'overall_ok':False,'error':type(exc).__name__+': '+str(exc)}))
        return 1


if __name__=='__main__': raise SystemExit(main())
