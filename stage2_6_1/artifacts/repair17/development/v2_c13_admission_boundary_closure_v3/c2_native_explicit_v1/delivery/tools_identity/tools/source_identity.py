#!/usr/bin/env python3
"""Actual import and release/deploy identity; no generator/fit/claim execution."""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BASELINE='ef55c96d9858dbf1f04f83e5ec22854a88883b5b'
VENDOR='52bc96f4480b1a0da6a9b455bd00b17fbb6786a5'


def need(ok,msg):
    if not ok: raise RuntimeError(msg)


def sha(b): return hashlib.sha256(b).hexdigest()


def regular(p):
    import stat
    p=Path(p).absolute()
    need(not any(q.is_symlink() for q in (p,*p.parents)), 'symlink source: '+str(p))
    need(stat.S_ISREG(p.stat().st_mode), 'not a regular source: '+str(p))
    return p.read_bytes()


def git(repo,*args):
    return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,timeout=120).stdout


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True);p.add_argument('--deploy',type=Path,required=True)
    p.add_argument('--phase',choices=['baseline','applied'],required=True)
    p.add_argument('--head',required=True);p.add_argument('--same-code-as')
    p.add_argument('--compare',type=Path);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();repo=a.repo.absolute();deploy=a.deploy.absolute()
    need(git(repo,'rev-parse','HEAD').decode().strip()==a.head,'HEAD changed')
    need(git(repo,'branch','--show-current').decode().strip()=='route-c-stage2-6-1-repair17','branch')
    need(Path(sys.executable).resolve()==Path('/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python').resolve(),
         'wrong actual interpreter')
    need(git(deploy/'vendor/freqtrade','rev-parse','HEAD').decode().strip()==VENDOR,'vendor pin')
    need(not git(deploy/'vendor/freqtrade','status','--porcelain=v1'),'vendor must be clean')
    payload=json.loads((ROOT/'PAYLOAD.json').read_text())['files']
    sources=json.loads((ROOT/'NATIVE_BASELINE_SOURCES.json').read_text())
    expected={r['module']:{'release':r['remote_path'],'sha256':r['sha256']} for r in sources}
    if a.phase=='applied':
        for rel,entry in payload.items():
            if '/src/rl_curriculum/' in rel:
                mod='rl_curriculum.'+Path(rel).stem
            elif '/runner/' in rel:
                mod=Path(rel).stem
            elif '/tests/' in rel and not Path(rel).name.startswith('test_'):
                mod=Path(rel).stem
            else: continue
            expected[mod]={'release':rel,'sha256':entry['sha256']}
    sys.path[:0]=[str(deploy/'src'),str(deploy/'stage2_6_1_runner'),str(deploy/'tests/route_c_stage2_6_1')]
    actual={}
    for mod,e in sorted(expected.items()):
        if '/src/' in e['release']: target=deploy/'src'/Path(*mod.split('.')).with_suffix('.py')
        elif '/runner/' in e['release']: target=deploy/'stage2_6_1_runner'/(mod+'.py')
        else: target=deploy/'tests/route_c_stage2_6_1'/(mod+'.py')
        raw=regular(repo/e['release']);deployed=regular(target)
        need(raw.replace(b'\r',b'')==deployed and sha(deployed)==e['sha256'],'source bytes: '+mod)
        loaded=importlib.import_module(mod)
        need(Path(loaded.__file__).absolute()==target.absolute(),'shadowed import: '+mod)
        actual[mod]={'file':str(target),'release':e['release'],'sha256':sha(deployed),'release_sha256':sha(raw)}
    trees={k:git(repo,'rev-parse',a.head+':stage2_6_1/'+k).decode().strip() for k in ('src','runner','tests')}
    if a.same_code_as:
        need(all(v==git(repo,'rev-parse',a.same_code_as+':stage2_6_1/'+k).decode().strip() for k,v in trees.items()),
             'C/E code trees differ')
    if a.compare:
        previous=json.loads(a.compare.read_text())
        need(actual==previous['sources'],'source identity changed since prior observation')
    result={'ok':True,'head':a.head,'phase':a.phase,'python':sys.executable,'version':sys.version,
            'cwd':os.getcwd(),'sources':actual,'trees':trees,'vendor_pin':VENDOR,
            'scope':'explicit baseline/payload import surface, not a complete third-party dependency closure',
            'status':git(repo,'status','--porcelain=v1','--untracked-files=all').decode()}
    with a.out.open('x') as f: json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'ok':True,'head':a.head,'modules':len(actual),'out':str(a.out)}))


if __name__=='__main__': main()
