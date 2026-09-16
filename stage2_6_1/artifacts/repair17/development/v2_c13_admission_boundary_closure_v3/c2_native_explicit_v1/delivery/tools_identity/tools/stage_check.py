#!/usr/bin/env python3
"""Check the exact already-staged code/evidence set before a normal commit."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REL='stage2_6_1/artifacts/repair17/development/v2_c13_admission_boundary_closure_v3/c2_native_explicit_v1/delivery'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True);p.add_argument('--kind',choices=['code','evidence'],required=True)
    p.add_argument('--head',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    def git(*args): return subprocess.run(['git','-C',str(a.repo),*args],check=True,capture_output=True,timeout=120).stdout
    def need(ok,msg):
        if not ok: raise RuntimeError(msg)
    need(git('rev-parse','HEAD').decode().strip()==a.head,'staging HEAD mismatch')
    changed={s for s in git('diff','--cached','--name-only','-z').decode().split('\0') if s}
    if a.kind=='code':
        m=json.loads((ROOT/'PAYLOAD.json').read_text())['files']
        expected={k:v['sha256'] for k,v in m.items()}
    else:
        root=a.repo/REL;manifest=json.loads((root/'GIT_EXPORT.json').read_text())
        expected={REL+'/'+k:v['sha256'] for k,v in manifest['exported'].items()}
        expected[REL+'/GIT_EXPORT.json']=hashlib.sha256((root/'GIT_EXPORT.json').read_bytes()).hexdigest()
    need(changed==set(expected),'staged paths are not exactly the authorized delivery')
    rows={}
    for rel,sha in expected.items():
        p=a.repo/rel;need(p.is_file() and not p.is_symlink(),'non-regular working file')
        data=git('show',':'+rel)
        need(hashlib.sha256(data).hexdigest()==sha and p.read_bytes()==data,'staged bytes mismatch: '+rel)
        mode=git('ls-files','-s','--',rel).decode().split()[0]
        need(mode=='100644','nonregular/executable staged mode: '+rel)
        rows[rel]={'sha256':sha,'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),'mode':mode}
    git('diff','--cached','--check')
    with a.out.open('x') as f: json.dump({'ok':True,'head':a.head,'kind':a.kind,'files':rows},f,indent=2);f.write('\n')
    print(json.dumps({'ok':True,'kind':a.kind,'files':len(rows)}))


if __name__=='__main__': main()
