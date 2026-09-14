#!/usr/bin/env python3
"""Synthetic-only C2 consumer rehearsal and read-only bundle verifier.

No production launch subcommand; never writes a plan, pack, claim or namespace.
Only exclusive new output under a dedicated system-temp subtree is supported.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from contextlib import contextmanager


def _core():
    from rl_curriculum import curriculum261_r17_c2_consumer
    return curriculum261_r17_c2_consumer


def _safe(path: Path, *, exists=False) -> Path:
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute path without traversal required')
    current=Path(path.anchor)
    for component in path.parts[1:]:
        current/=component
        try:s=current.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(s.st_mode):raise ValueError('symlink path rejected: '+str(current))
        if current!=path and not stat.S_ISDIR(s.st_mode):raise ValueError('non-directory parent')
    if exists and not path.exists():raise ValueError('required path missing: '+str(path))
    return path


def _bytes(path: Path) -> bytes:
    _safe(path,exists=True)
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size>64*1024*1024:
            raise ValueError('regular bounded-size file required')
        with os.fdopen(fd,'rb',closefd=False) as stream:body=stream.read()
        after=os.fstat(fd)
        if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
            raise ValueError('input changed during read')
        return body
    finally:os.close(fd)


def _json(data):
    def pairs(items):
        out={}
        for key,value in items:
            if key in out:raise ValueError('duplicate JSON key')
            out[key]=value
        return out
    def bad(x):raise ValueError('nonfinite JSON literal: '+x)
    return json.loads(data,object_pairs_hook=pairs,parse_constant=bad)


def _new(path,body):
    _safe(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        with os.fdopen(fd,'wb',closefd=False) as f:
            f.write(body);f.flush();os.fsync(fd)
    finally:os.close(fd)


def _dump(path,obj):
    _new(path,(_core().canonical(obj)+'\n').encode('utf-8'))


def _index(root):
    _safe(root,exists=True)
    result={}
    for p in sorted(root.iterdir()):
        body=_bytes(p)
        result[p.name]={'size':len(body),'sha256':hashlib.sha256(body).hexdigest()}
    return result


def source_identity():
    c=_core();out={}
    for name in (*c.DEPENDENCIES,'rl_curriculum.curriculum261_r17_c2_consumer'):
        m=importlib.import_module(name);path=Path(m.__file__).absolute()
        b=_bytes(path);out[name]={'file':str(path),'sha256':hashlib.sha256(b).hexdigest()}
    path=Path(__file__).absolute();out['r17_c2_consumer_rehearsal']={
        'file':str(path),'sha256':hashlib.sha256(_bytes(path)).hexdigest()}
    return out


# WSL test runner only: install before consumer calls. Importing the real graph
# does not count as generation; every listed callable must exist or this fails.
SENTINELS=(
 ('rl_curriculum.curriculum261_api','generate_pair_with_attempts'),
 ('rl_curriculum.curriculum261_pairs','generate_pair'),
 ('rl_curriculum.curriculum261_r6_tape','generate_matched_block_with_attempts'),
 ('rl_curriculum.curriculum261_r6_tape','generate_matched_block_once'),
 ('rl_curriculum.curriculum261_r17_calibration','generate_fit_bank_r17'),
 ('rl_curriculum.curriculum261_r17_calibration','fit_preprocessor_v2_from_bank_r17'),
 ('rl_curriculum.curriculum261_r17_calibration','run_c2_matched_corpus_r17'),
 ('rl_curriculum.curriculum261_r17_calibration','run_c2_independent_corpus_r17'),
 ('rl_curriculum.curriculum261_r17_calibration','run_c2_semantic_corpus_r17'),
 ('rl_curriculum.curriculum261_r17_design','run_design_stage_r17'),
 ('rl_curriculum.curriculum261_r17_cue_contract','run_cue_contract_audit'),
 ('rl_curriculum.evaluator','run_policy_episode'),
 ('r17_v2_c13_profile','consume_production_claim'),
 ('r17_v2_c13_profile','persist_final_plan'),
 ('r17_v2_c13_profile','write_preclaim_receipt'),
 ('rl_curriculum.curriculum261_r17_registry','mark_design_data_started'),
)


@contextmanager
def zero_calls():
    installed=[];counts={}
    try:
        for mod,name in SENTINELS:
            module=importlib.import_module(mod);original=getattr(module,name)
            if not callable(original):raise RuntimeError('noncallable sentinel '+mod+'.'+name)
            key=mod+'.'+name;counts[key]=0
            def forbidden(*args,_key=key,**kwargs):
                counts[_key]+=1
                raise RuntimeError('production/generation boundary reached: '+_key)
            setattr(module,name,forbidden);installed.append((module,name,original))
        yield counts
    finally:
        for module,name,original in reversed(installed):setattr(module,name,original)


def write_bundle(packet,out: Path):
    c=_core();out=_safe(Path(out))
    temp=Path(tempfile.gettempdir()).resolve()
    if not out.is_relative_to(temp) or out==temp:raise ValueError('new dedicated system temp output required')
    if os.path.lexists(out):raise FileExistsError(str(out))
    sources=source_identity()
    out.mkdir(parents=True,exist_ok=False)
    # Ownership belongs to this call; failures remain for diagnosis, never unlink.
    _dump(out/'input.json',packet)
    try:result=c.consume(packet)
    except Exception as exc:
        _dump(out/'error.json',{'engineering_complete':False,'phase':'report_consumer',
            'exception':type(exc).__name__,'message':str(exc),
            'business_statistics':'NOT_RUN','formal_qualification':'NOT_ISSUED'})
        raise
    if source_identity()!=sources:raise RuntimeError('source identity changed during consumer run')
    _dump(out/'result.json',result);_dump(out/'sources.json',sources)
    manifest={'format':'R17C2SyntheticBundle-v1','synthetic':True,
              'input_sha256':c.digest(packet),'files':_index(out)}
    _dump(out/'manifest.json',manifest)
    return {'output':str(out),'input_sha256':manifest['input_sha256'],
            'engineering_complete':result['engineering_complete'],
            'fixture_gate_outcome':result['fixture_gate_outcome'],
            'business_statistics':'NOT_RUN','formal_qualification':'NOT_ISSUED'}


def verify_bundle(root: Path, expected_input_sha256: str):
    c=_core();root=_safe(Path(root),exists=True)
    before=_index(root)
    if set(before)!={'input.json','result.json','sources.json','manifest.json'}:
        raise ValueError('bundle file set mismatch')
    manifest=_json(_bytes(root/'manifest.json'))
    if manifest['format']!='R17C2SyntheticBundle-v1' or manifest['synthetic'] is not True:
        raise ValueError('not a synthetic C2 consumer bundle')
    if manifest['files']!={k:v for k,v in before.items() if k!='manifest.json'}:
        raise ValueError('bundle bytes differ from manifest')
    packet=_json(_bytes(root/'input.json'))
    if c.digest(packet)!=expected_input_sha256 or manifest['input_sha256']!=expected_input_sha256:
        raise ValueError('input identity mismatch')
    sources=_json(_bytes(root/'sources.json'))
    if sources!=source_identity():raise ValueError('consumer source identity differs')
    actual=c.consume(packet);stored=_json(_bytes(root/'result.json'))
    if c.canonical(actual)!=c.canonical(stored):raise ValueError('result differs from reconsumed reports')
    if _index(root)!=before:raise ValueError('verification changed or raced bundle bytes')
    return {'ok':True,'scope':'synthetic-report-reconsumption','input_sha256':expected_input_sha256,
            'business_statistics':'NOT_RUN','formal_qualification':'NOT_ISSUED',
            'launch_authorized':False,'upstream_episode_provenance_rebuilt':False}


def _fixtures():
    here=Path(__file__).resolve()
    roots=[here.parent.parent/'tests/route_c_stage2_6_1']
    for root in roots:
        if (root/'r17_c2_consumer_fixtures.py').is_file():
            sys.path.insert(0,str(root));break
    from r17_c2_consumer_fixtures import make_packet
    return make_packet


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('describe')
    run=sub.add_parser('rehearse');run.add_argument('--out',type=Path,required=True)
    check=sub.add_parser('verify');check.add_argument('--bundle',type=Path,required=True)
    check.add_argument('--expected-input-sha256',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='describe':
            value={'format':_core().FORMAT,'fixed_design':_core().fixed_design(),
                   'scope':'synthetic report consumer only','launch_authorized':False}
        else:
            with zero_calls() as counts:
                if args.command=='rehearse':value=write_bundle(_fixtures()(),args.out)
                else:value=verify_bundle(args.bundle,args.expected_input_sha256)
                if any(counts.values()):raise RuntimeError('zero-call boundary violated')
                value['zero_call_counts']=dict(counts)
        print(json.dumps(value,sort_keys=True,ensure_ascii=False,indent=2,allow_nan=False));return 0
    except Exception as exc:
        print(json.dumps({'ok':False,'error':type(exc).__name__,'message':str(exc),
                          'business_statistics':'NOT_RUN','formal_qualification':'NOT_ISSUED'},ensure_ascii=False))
        return 1


if __name__=='__main__':raise SystemExit(main())
