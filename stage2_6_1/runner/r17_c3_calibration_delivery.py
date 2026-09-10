#!/usr/bin/env python3
"""Composition of monitor bytes and bridge consistency; never a calibration PASS."""
from pathlib import Path
import argparse
import sys
import r17_c3_reserve_batch as batch
from r17_c3_calibration_bridge import verify, need, read, meta
from r17_required_bytes import delivery_check


def check(root: Path, record: Path) -> dict:
    root=root.resolve(strict=True);record=record.resolve(strict=True)
    need(record.is_relative_to(root),'monitor record outside root')
    saved=meta(record);doc=read(record)
    need(doc.get('task_kind')=='engineering' and doc.get('run_id')==record.parent.name,'monitor identity/kind mismatch')
    argv=doc.get('argv',[])
    need(len(argv)==7 and Path(argv[1]).name=='r17_c3_calibration_bridge.py'
         and argv[2:4]==['run','--batch'] and argv[5]=='--out','not the fixed bridge business command')
    out=Path(argv[6]);inp=Path(argv[4])
    need(out.name=='c3_calibration_bridge' and out.parent.name==doc['run_id'],'wrong bridge output binding')
    need(inp.name=='c3_finite_reserve','wrong source batch argument')
    before=delivery_check(root,record)
    result=verify(record.parent/'c3_calibration_bridge')
    after=delivery_check(root,record)
    need(saved==meta(record),'monitor record changed during verification')
    return {'overall_ok':before['delivery_ok'] and after['delivery_ok'] and result['engineering_consumer_complete'],
            'native_and_required_before':before,'bridge':result,'native_and_required_after':after,
            'calibration_qualified':False,
            'scope':'engineering handoff only; statistical FAIL is not suppressed or turned into a qualification'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--record',type=Path,required=True);a=p.parse_args()
    try:
        result=check(a.root,a.record);print(batch.canonical(result));return 0 if result['overall_ok'] else 1
    except Exception as exc:
        print(batch.canonical({'overall_ok':False,'calibration_qualified':False,'error':type(exc).__name__+': '+str(exc)}));return 1

if __name__=='__main__':raise SystemExit(main())
