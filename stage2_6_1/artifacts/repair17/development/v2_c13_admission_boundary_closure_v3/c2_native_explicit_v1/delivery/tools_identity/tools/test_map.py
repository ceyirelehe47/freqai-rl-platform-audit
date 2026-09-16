#!/usr/bin/env python3
"""Full Git-tree -> deployed flattened test mapping, including 31 root tests."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
BASELINE='ef55c96d9858dbf1f04f83e5ec22854a88883b5b'


def need(ok,msg):
    if not ok: raise RuntimeError(msg)


def sha(b): return hashlib.sha256(b).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,required=True);p.add_argument('--deploy',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    m=json.loads((ROOT/'PAYLOAD.json').read_text())
    proc=subprocess.run(['git','-C',str(a.repo),'ls-tree','-r','--name-only',BASELINE,'--','stage2_6_1/tests'],
                        capture_output=True,check=True,timeout=120)
    paths={s for s in proc.stdout.decode().splitlines() if s.endswith('.py')}
    paths|={s for s in m['files'] if s.startswith('stage2_6_1/tests/') and s.endswith('.py')}
    names={};mapping=[]
    for rel in sorted(paths):
        src=a.repo/rel;key=src.name.casefold()
        need(key not in names,'basename/case collision: '+rel);names[key]=rel
        need(src.is_file() and not src.is_symlink(),'source type: '+rel)
        raw=src.read_bytes()
        if rel in m['files']:
            need(sha(raw)==m['files'][rel]['sha256'],'payload test bytes changed')
        else:
            base=subprocess.run(['git','-C',str(a.repo),'show',BASELINE+':'+rel],capture_output=True,check=True,timeout=120).stdout
            need(raw==base,'historical test modified: '+rel)
        dest_rel='tests/route_c_stage2_6_1/'+src.name
        dest=a.deploy/dest_rel
        need(dest.is_file() and not dest.is_symlink(),'missing deployed test: '+dest_rel)
        deployed=dest.read_bytes()
        need(deployed==raw.replace(b'\r',b''),'delete_all_CR_bytes mismatch: '+rel)
        mapping.append({'release':rel,'deploy':dest_rel,'release_sha256':sha(raw),'deployed_sha256':sha(deployed)})
    disk={p.name.casefold() for p in (a.deploy/'tests/route_c_stage2_6_1').rglob('*.py')}
    need(disk==set(names),'extra/missing deployed Python tests')
    tests=[r['deploy'] for r in mapping if Path(r['deploy']).name.startswith('test_')]
    tests.sort(key=lambda s: ('r17' not in Path(s).name,Path(s).name))
    targeted=[s for s in tests if Path(s).name.startswith('test_r17_c2_native_')
              or any(x in Path(s).name for x in ('r17_c2_consumer','r17_cue','r17_reference','r17_calibration'))]
    need(any(s.endswith('test_curriculum261_r17_c2_consumer.py') for s in targeted),'missing existing 53-test consumer')
    runner=a.deploy/'stage2_6_1_runner'
    sys.path.insert(0,str(runner))
    import r17_v2_c13_admission_guard as guard
    need(len(guard.HISTORICAL_SKIP_IDS)==7,'historical skip policy drift')
    a.out.mkdir(parents=True,exist_ok=False)
    (a.out/'mapping.json').write_text(json.dumps({'files':mapping,'python_files':len(mapping),
                    'test_files':len(tests),'targeted_files':targeted,'full_files':tests},indent=2)+'\n')
    (a.out/'full_targets.txt').write_text('\n'.join(tests)+'\n')
    (a.out/'targeted_targets.txt').write_text('\n'.join(targeted)+'\n')
    (a.out/'test_files.sha256').write_text(''.join(r['deployed_sha256']+'  '+r['deploy']+'\n' for r in mapping if Path(r['deploy']).name.startswith('test_')))
    (a.out/'skips_allowlist.json').write_text(json.dumps({'allowed_skips':sorted(guard.HISTORICAL_SKIP_IDS)},indent=2)+'\n')
    (a.out/'critical_stems.txt').write_text(','.join(guard.CRITICAL_TEST_FILES)+'\n')
    print(json.dumps({'ok':True,'python_files':len(mapping),'test_files':len(tests),'targeted_files':len(targeted)}))


if __name__=='__main__': main()
