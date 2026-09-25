"""Real local pytest counterexample to the v3 effective-collection guard.
All candidate files are identical for control and filtered run. An imported
hook uses an otherwise-untracked development environment setting. Both full
commands stay unchanged and PYTEST_ADDOPTS/PYTEST_PLUGINS are absent.
This is an isolated component check, NOT a WSL full-issuer bypass claim.
"""
from __future__ import annotations
import ast, hashlib, json, os, platform, subprocess, sys, time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
import verifier_excerpts as v

ROOT=Path(__file__).resolve().parent
DEPLOY=ROOT/'probe_worktree'
TESTS=DEPLOY/'tests'/'route_c_stage2_6_1'
TARGET='tests/route_c_stage2_6_1'
OUT=ROOT/'probe_runs'

# Explicit synthetic stubs with the project's seven historical skip IDs.
HISTORY=[
 ('test_curriculum261_r12_governance_r12','TestHistoricalEvidenceBinding','test_ancestry_semantics_pass'),
 ('test_curriculum261_r13_governance','TestHistoricalEvidenceBindingR13','test_ancestry_and_r12_clean_chain'),
 ('test_curriculum261_r14_governance','TestHistoricalEvidenceBindingR14','test_ancestry_and_r13_clean_chain'),
 ('test_curriculum261_r15_governance','TestHistoricalEvidenceBindingR15','test_ancestry_and_r13_clean_chain'),
 ('test_curriculum261_r16_governance','TestExecutionSurfaceBytes','test_r16_formal_wrapper_selfcheck_present'),
 ('test_curriculum261_r16_governance','TestExecutionSurfaceBytes','test_runner_shell_scripts_lf'),
 ('test_curriculum261_r16_governance','TestHistoricalEvidenceBindingR16','test_ancestry_and_r15_clean_chain'),
]

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def write_sources()->None:
    TESTS.mkdir(parents=True,exist_ok=True)
    (DEPLOY/'tests'/'__init__.py').write_text('')
    (TESTS/'__init__.py').write_text('')
    (TESTS/'conftest.py').write_text('from .selection_support import pytest_collection_modifyitems\n')
    (TESTS/'selection_support.py').write_text(
        'import os\n\ndef pytest_collection_modifyitems(items):\n'
        '    if os.environ.get("LOCAL_QUICK_TESTS") == "1":\n'
        '        items[:] = [item for item in items if item.name != "test_parameter[1]"]\n')
    (TESTS/'test_parameter.py').write_text(
        'import pytest\n\n@pytest.mark.parametrize("x", [0, 1, 2])\n'
        'def test_parameter(x):\n    assert x != 1\n')
    grouped={}
    for mod,cl,fn in HISTORY: grouped.setdefault(mod,{}).setdefault(cl,[]).append(fn)
    for mod,classes in grouped.items():
        text='import pytest\n\n'
        for cl,fns in classes.items():
            text+=f'class {cl}:\n'
            for fn in fns:
                text+=f'    @pytest.mark.skip(reason="synthetic historical skip stub")\n    def {fn}(self):\n        pass\n'
            text+='\n'
        (TESTS/(mod+'.py')).write_text(text)

def snapshot()->dict:
    return {str(p.relative_to(DEPLOY)):sha(p.read_bytes()) for p in sorted(DEPLOY.rglob('*.py'))}

def run_one(mode:str,collect:bool)->dict:
    directory=OUT/mode
    directory.mkdir(parents=True,exist_ok=True)
    stem='collection' if collect else 'execution'
    env={k:val for k,val in os.environ.items() if k not in ('PYTEST_ADDOPTS','PYTEST_PLUGINS','LOCAL_QUICK_TESTS')}
    env['PYTHONDONTWRITEBYTECODE']='1'
    if mode=='filtered': env['LOCAL_QUICK_TESTS']='1'
    command=[sys.executable,'-m','pytest',TARGET]
    command+=['--collect-only','-q'] if collect else ['-q',f'--junitxml={directory/"junit.xml"}']
    v._verify_run_argv(command,collect_only=collect,positionals_rule=[TARGET])
    start=time.time()
    p=subprocess.run(command,cwd=DEPLOY,env=env,capture_output=True,timeout=30)
    elapsed=time.time()-start
    (directory/f'{stem}.stdout.txt').write_bytes(p.stdout)
    (directory/f'{stem}.stderr.txt').write_bytes(p.stderr)
    run=dict(command=command,cwd=str(DEPLOY),interpreter=sys.executable,
             returncode=p.returncode,elapsed_seconds=elapsed,
             env_delta={'LOCAL_QUICK_TESTS':env.get('LOCAL_QUICK_TESTS')},
             stdout_sha256=sha(p.stdout),stderr_sha256=sha(p.stderr))
    (directory/f'{stem}.run.json').write_text(json.dumps(run,indent=2)+'\n')
    run['stdout_bytes']=p.stdout
    return run

def parse_result(path:Path)->tuple[dict,Counter,list]:
    root=ET.parse(path).getroot()
    cases=list(root.iter('testcase'))
    ids=[]; skipped=[]
    agg=dict(tests=len(cases),failures=0,errors=0,skipped=0)
    for c in cases:
        cl,name=c.attrib['classname'],c.attrib['name']
        parts=cl.split('.')
        ids.append('/'.join(parts[:3])+'.py::'+'::'.join(parts[3:]+[name]))
        agg['failures']+=len(c.findall('failure'))
        agg['errors']+=len(c.findall('error'))
        if c.find('skipped') is not None:
            skipped.append(cl+'::'+name);agg['skipped']+=1
    return agg,Counter(ids),skipped

def main()->None:
    if OUT.exists(): raise RuntimeError('Refusing to overwrite existing probe evidence')
    write_sources()
    before=snapshot()
    guard_pass=True
    v._reject_config_filters(TESTS/'conftest.py',(TESTS/'conftest.py').read_bytes())
    try:
        v._reject_config_filters(Path('conftest.py'),b'def pytest_collection_modifyitems(items):\n    pass\n')
    except v.SubstanceError as e:
        direct_rejected=str(e)
    else: raise AssertionError('Direct hook control should have been rejected')
    control_c=run_one('control',True); control_e=run_one('control',False)
    filtered_c=run_one('filtered',True); filtered_e=run_one('filtered',False)
    control_ids=v.parse_collection_stdout(control_c['stdout_bytes'].decode())
    filtered_ids=v.parse_collection_stdout(filtered_c['stdout_bytes'].decode())
    cagg,cex,cskip=parse_result(OUT/'control'/'junit.xml')
    fagg,fex,fskip=parse_result(OUT/'filtered'/'junit.xml')
    v._verify_execution_summary(filtered_e['stdout_bytes'],fagg)
    static=set()
    for p in TESTS.glob('test_*.py'):
        prefix=TARGET+'/'+p.name+'::'
        mod=ast.parse(p.read_bytes())
        for n in mod.body:
            if isinstance(n,ast.FunctionDef) and n.name.startswith('test_'): static.add(prefix+n.name)
            elif isinstance(n,ast.ClassDef) and n.name.startswith('Test'):
                for t in n.body:
                    if isinstance(t,ast.FunctionDef) and t.name.startswith('test_'): static.add(prefix+n.name+'::'+t.name)
    import pytest
    env_view=dict(python_version=platform.python_version(),pytest_version_output=pytest.__version__,
                  pytest_addopts=None,pytest_plugins_env=None,
                  config_scan=[{'path':str(TESTS/'conftest.py'),'sha256':sha((TESTS/'conftest.py').read_bytes())}])
    identity=dict(interpreter=sys.executable,cwd=str(DEPLOY),env=env_view)
    v._verify_run_identity([identity],identity,'probe')
    hist={f'tests.route_c_stage2_6_1.{m}.{c}::{f}' for m,c,f in HISTORY}
    checks={
      'same_source_files_control_and_filtered':before==snapshot(),
      'imported_hook_config_guard_accepts':guard_pass,
      'direct_hook_control_rejected':direct_rejected,
      'full_directory_argv_accepted':True,
      'raw_filtered_collection_equals_execution':Counter(filtered_ids)==fex,
      'filtered_base_ids_equal_static_full_function_set':{v._param_base(i) for i in filtered_ids}==static,
      'filtered_all_test_files_still_covered':{i.split('::')[0] for i in filtered_ids}=={TARGET+'/'+p.name for p in TESTS.glob('test_*.py')},
      'filtered_historical_skip_set_exact':set(fskip)==hist,
      'filtered_stdout_summary_matches_junit':True,
      'tracked_identity_fields_compatible':True,
    }
    assert control_c['returncode']==0 and control_e['returncode']==1
    assert filtered_c['returncode']==0 and filtered_e['returncode']==0
    assert all(value is True for key,value in checks.items() if key!='direct_hook_control_rejected')
    result=dict(scope='Real local pytest runs plus specified verifier function excerpts; not full issuer/consumer or WSL verification.',
                runtime=dict(python=sys.version,pytest=pytest.__version__),
                original_commit='9be9f1f61075936a20d27254e4cff6462959e3f6',
                control=dict(collected=len(control_ids),junit=cagg,rc=control_e['returncode']),
                filtered=dict(collected=len(filtered_ids),junit=fagg,rc=filtered_e['returncode']),
                missing_ids=sorted(set(control_ids)-set(filtered_ids)),
                checks=checks,source_snapshot=before,
                conclusion='An imported effective collection hook is not detected by the current top-level-def config scan. Raw collect+run agreement does not establish absence of shared filtering.')
    (ROOT/'imported_hook_probe_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
