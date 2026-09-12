"""Local patch/delegation/evidence-shape checks, not a full project/WSL run."""
from __future__ import annotations
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app = load('v3a_fixture_app', ROOT / 'tools/apply_fixture_patch.py')
guard = load('r17_v2_c13_admission_guard', ROOT / 'references/guard_v3_unmodified.py')
ORIGINAL = (ROOT / 'references/original_v10_excerpt.py').read_bytes()
PAYLOAD = (ROOT / 'payload/pipeline_fixture.py').read_bytes()


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    assert p.returncode == 0, p.stderr
    return p.stdout.decode().strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-q', '-b', app.BRANCH)
    git(root, 'config', 'user.email', 'local-validation@example.invalid')
    git(root, 'config', 'user.name', 'Local validation fixture')
    for relative, data in ((app.TARGET, ORIGINAL),
                           (app.SUPPORT, b'# local support placeholder\n'),
                           (app.HISTORICAL_LOCK, b'# local historical placeholder\n')):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(root, 'add', '.')
    git(root, 'commit', '-qm', 'local applier fixture')
    # Explicit local test configuration; the distributed CLI has no pin override.
    monkeypatch.setattr(app, 'BASELINE', git(root, 'rev-parse', 'HEAD'))
    monkeypatch.setattr(app, 'TARGET_BLOB', git(root, 'rev-parse', 'HEAD:' + app.TARGET))
    monkeypatch.setattr(app, 'SUPPORT_BLOB', git(root, 'rev-parse', 'HEAD:' + app.SUPPORT))
    monkeypatch.setattr(app, 'HISTORICAL_SHA256', app.sha((root/app.HISTORICAL_LOCK).read_bytes()))
    return root


def test_transform_keeps_original_tests_verbatim():
    out = app.transform(ORIGINAL, PAYLOAD)
    before_nodes, after_nodes = app.definitions(ORIGINAL.decode()), app.definitions(out.decode())
    for name in before_nodes:
        if name != '_claim_fixture':
            assert app.source_of(ORIGINAL.decode(), before_nodes[name]) == app.source_of(out.decode(), after_nodes[name])
    assert set(after_nodes) == set(before_nodes) | set(app.NEW_TESTS)


def test_transform_rejects_repeat():
    once = app.transform(ORIGINAL, PAYLOAD)
    with pytest.raises(RuntimeError, match='already exists'):
        app.transform(once, PAYLOAD)


def test_transform_rejects_absent_original_test():
    text = ORIGINAL.replace(b'def test_v10_one_shot_claim(', b'def missing_test(')
    with pytest.raises(RuntimeError, match='required unchanged regression absent'):
        app.transform(text, PAYLOAD)


def test_transform_rejects_duplicate_definitions():
    with pytest.raises(RuntimeError, match='duplicate'):
        app.transform(ORIGINAL + b'\ndef _claim_fixture():\n    pass\n', PAYLOAD)


def test_transform_rejects_extra_payload():
    with pytest.raises(RuntimeError, match='definition set'):
        app.transform(ORIGINAL, PAYLOAD + b'\ndef sneak():\n    pass\n')


def test_payload_has_four_named_rejection_cases():
    nodes = app.definitions(PAYLOAD.decode())
    decorator = nodes['test_v10_unhealthy_fixture_is_still_rejected'].decorator_list[0]
    cases = ast.literal_eval(decorator.args[1])
    assert [c[0] for c in cases] == ['production_contract', 'missing_regression',
                                   'fake_regression_digest', 'missing_admission']
    assert len({c[1] for c in cases}) == 4


def test_check_mode_is_readonly(repo):
    before = (repo/app.TARGET).read_bytes()
    report = app.run(repo, apply=False, recovery=None)
    assert report['modified_files'] == [app.TARGET]
    assert report['applied'] is False
    assert (repo/app.TARGET).read_bytes() == before
    assert git(repo, 'status', '--porcelain=v1') == ''


def test_apply_changes_only_one_file_and_retains_recovery(repo, tmp_path):
    recovery = tmp_path / 'recovery'
    report = app.run(repo, apply=True, recovery=recovery)
    assert report['production_code_changes'] == 0
    assert git(repo, 'diff', '--name-only') == app.TARGET
    assert (recovery/'target.before.worktree.py').read_bytes() == ORIGINAL
    assert app.sha((repo/app.TARGET).read_bytes()) == report['after_sha256']
    assert (repo/app.SUPPORT).read_bytes() == b'# local support placeholder\n'
    assert (repo/app.HISTORICAL_LOCK).read_bytes() == b'# local historical placeholder\n'


@pytest.mark.parametrize('field,value,message', [
    ('BASELINE', 'a'*40, 'HEAD differs'),
    ('BRANCH', 'wrong-branch', 'wrong branch'),
    ('TARGET_BLOB', 'b'*40, 'target Git blob'),
    ('SUPPORT_BLOB', 'c'*40, 'helper Git blob'),
    ('HISTORICAL_SHA256', 'd'*64, 'historical lock'),
    ('PAYLOAD_SHA256', 'e'*64, 'payload SHA'),
])
def test_bad_precondition_stops_before_writes(repo, tmp_path, monkeypatch, field, value, message):
    monkeypatch.setattr(app, field, value)
    with pytest.raises(RuntimeError, match=message):
        app.run(repo, apply=True, recovery=tmp_path/'recovery')
    assert (repo/app.TARGET).read_bytes() == ORIGINAL
    assert not (tmp_path/'recovery').exists()


def test_dirty_target_never_overwritten(repo, tmp_path):
    path = repo/app.TARGET
    dirty = path.read_bytes() + b'\n# user change\n'
    path.write_bytes(dirty)
    with pytest.raises(RuntimeError, match='dirty'):
        app.run(repo, apply=True, recovery=tmp_path/'recovery')
    assert path.read_bytes() == dirty


def test_recovery_inside_repo_rejected(repo):
    with pytest.raises(RuntimeError, match='outside repository'):
        app.run(repo, apply=True, recovery=repo/'bad-recovery')
    assert (repo/app.TARGET).read_bytes() == ORIGINAL


def test_missing_recovery_rejected(repo):
    with pytest.raises(RuntimeError, match='requires'):
        app.run(repo, apply=True, recovery=None)
    assert (repo/app.TARGET).read_bytes() == ORIGINAL


def test_existing_recovery_rejected(repo, tmp_path):
    recovery = tmp_path/'old-recovery'
    recovery.mkdir()
    with pytest.raises(RuntimeError, match='fresh'):
        app.run(repo, apply=True, recovery=recovery)
    assert (repo/app.TARGET).read_bytes() == ORIGINAL


def test_source_symlink_rejected(tmp_path):
    repo = tmp_path/'root'
    repo.mkdir()
    target = tmp_path/'outside.py'
    target.write_text('pass\n')
    (repo/'test.py').symlink_to(target)
    with pytest.raises(RuntimeError, match='symlink'):
        app.regular_path(repo, 'test.py')


def fixture_namespace(monkeypatch, helper):
    support = types.ModuleType('test_curriculum261_r17_v2_c13_claim_protocol')
    support._persist_plan_and_receipt = helper
    monkeypatch.setitem(sys.modules, support.__name__, support)
    ns = {'copy': copy, 'prof': types.SimpleNamespace(synthetic_authority=lambda r,c:(r,c))}
    node = app.definitions(PAYLOAD.decode())['_claim_fixture']
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<new-fixture-delegation>', 'exec'), ns)
    return ns['_claim_fixture']


def test_fixture_uses_shared_helper_default_nonempty_runtime(monkeypatch, tmp_path):
    calls = []
    def helper(auth, *, runtime):
        calls.append((auth, runtime))
        return 'plan', 'persisted', 'receipt'
    fn = fixture_namespace(monkeypatch, helper)
    out = fn(tmp_path, monkeypatch)
    assert len(calls) == 1 and calls[0][1] is None
    assert out[:3] == ('plan', 'persisted', 'receipt')
    assert out[3] == calls[0][0]


def test_fixture_deep_copies_explicit_runtime(monkeypatch, tmp_path):
    original = {'sources': {'x': {'sha256': 'ab'*32}}}
    seen = []
    def helper(auth, *, runtime):
        seen.append(runtime)
        runtime['sources'].clear()
        return {}, {}, {}
    fixture_namespace(monkeypatch, helper)(tmp_path, monkeypatch, runtime=original)
    assert original['sources'] and seen[0]['sources'] == {}


def test_fixture_propagates_real_builder_failure(monkeypatch, tmp_path):
    def helper(auth, *, runtime):
        raise ValueError('builder failed, must not fabricate success')
    with pytest.raises(ValueError, match='must not fabricate'):
        fixture_namespace(monkeypatch, helper)(tmp_path, monkeypatch)


def builder():
    code = (ROOT/'references/evidence_functions_v3_unmodified.py').read_text()
    node = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef)
                and n.name == 'build_synthetic_package')
    ns = {'Path':Path, 'Any':Any, 'json':json, 'EvidenceError':guard.AdmissionError,
          '_sha256_bytes':guard.sha256, '_canonical':guard.canonical,
          'PACKAGE_FORMAT':'R17V2C13FullRegressionEvidence-v1',
          'package_digest':lambda p:guard.sha256(guard.canonical(guard.tree_index(p)).encode())}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<unchanged-v3-builder>', 'exec'),ns)
    return ns['build_synthetic_package']


def test_existing_builder_makes_guard_compatible_real_fixture_bytes(tmp_path):
    package = tmp_path/'package'
    builder()(package,current_sources={'fixture_mod': {'path':'/fixture/proto.py','sha256':hashlib.sha256(b'proto').hexdigest()}})
    before = guard.tree_index(package)
    assert guard.package_semantics(package,synthetic=True,full=False,
          release_repo=None,deploy_root=None,current_sources=None) == []
    assert guard.tree_index(package) == before
    assert json.loads((package/'run_meta.json').read_text())['synthetic'] is True


@pytest.mark.parametrize('name,expected', [
    ('empty_required', 'required_role_set_mismatch'),
    ('empty_critical', 'critical_policy_mismatch'),
    ('hidden_failure', 'junit_failures_nonzero'),
])
def test_existing_guard_keeps_bad_fixture_rejection(tmp_path, name, expected):
    package = tmp_path/'package'
    builder()(package,current_sources={'fixture_mod': {'path':'/fixture/p.py','sha256':'ab'*32}})
    if name == 'empty_required':
        (package/'required_files.json').write_text('{"entries": []}')
    elif name == 'empty_critical':
        (package/'critical_tests.json').write_text('{"critical_test_files": []}')
    else:
        import xml.etree.ElementTree as ET
        p = package/'junit.xml'
        doc = ET.fromstring(p.read_bytes())
        ET.SubElement(next(doc.iter('testcase')), 'failure')
        p.write_bytes(ET.tostring(doc))
    errors = guard.package_semantics(package,synthetic=True,full=False,
                    release_repo=None,deploy_root=None,current_sources=None)
    assert expected in [key for key,_ in errors]


@pytest.fixture
def history_repo(tmp_path):
    root = tmp_path/'history'
    root.mkdir()
    git(root,'init','-q')
    git(root,'config','user.email','local-validation@example.invalid')
    git(root,'config','user.name','Local validation')
    (root/'.gitattributes').write_text(guard.NEW_EVIDENCE_ROOT+'/** -text\n')
    old = root/guard.NEW_EVIDENCE_ROOT/'REPORT.md'
    old.parent.mkdir(parents=True)
    old.write_text('v3 failure remains FAIL\n')
    test = root/app.TARGET
    test.parent.mkdir(parents=True)
    test.write_bytes(app.transform(ORIGINAL,PAYLOAD))
    git(root,'add','.')
    git(root,'commit','-qm','new code candidate including fixture fix')
    return root,git(root,'rev-parse','HEAD')


def test_real_guard_accepts_continuation_subdir_e_and_e2(history_repo):
    root,candidate = history_repo
    report=root/guard.NEW_EVIDENCE_ROOT/'continuation_v3a/REPORT.md'
    report.parent.mkdir()
    report.write_text('new evidence only\n')
    git(root,'add','.')
    git(root,'commit','-qm','E continuation evidence')
    first=guard.verify_candidate_history(root,candidate,candidate)
    assert first['source_test_trees_unchanged'] is True
    report.write_text('new evidence plus after-E verification\n')
    git(root,'add','.')
    git(root,'commit','-qm','E2 continuation verification')
    assert len(guard.verify_candidate_history(root,candidate,candidate)['evidence_descendants'])==2


def test_real_guard_rejects_old_failure_report_rewrite(history_repo):
    root,candidate = history_repo
    (root/guard.NEW_EVIDENCE_ROOT/'REPORT.md').write_text('not permitted to turn old FAIL into PASS\n')
    git(root,'add','.')
    git(root,'commit','-qm','bad evidence commit')
    with pytest.raises(guard.AdmissionError,match='historical evidence changed'):
        guard.verify_candidate_history(root,candidate,candidate)


def test_real_guard_rejects_new_sibling_root(history_repo):
    root,candidate = history_repo
    path=root/'stage2_6_1/artifacts/repair17/development/v2_c13_wrong_v3a/REPORT.md'
    path.parent.mkdir(parents=True)
    path.write_text('must not extend whitelist\n')
    git(root,'add','.')
    git(root,'commit','-qm','wrong E destination')
    with pytest.raises(guard.AdmissionError,match='non-evidence change'):
        guard.verify_candidate_history(root,candidate,candidate)


def make_targeted_junit(path, *, fail=False, skip=False, omit_negative=False):
    import xml.etree.ElementTree as ET
    checker = load('v3a_target_checker_fixture', ROOT/'tools/check_targeted_junit.py')
    suite = ET.Element('testsuite', name='pytest', failures='0', errors='0', skipped='0', tests='0')
    for module in sorted(checker.EXPECTED_FILES):
        if module.endswith('_pipeline'):
            names = ['test_v10_one_shot_claim',
                     'test_v10_corrupted_claim_is_consumed_not_retried',
                     'test_v10_fixture_is_evidence_backed_and_not_production']
            names += [f'test_v10_unhealthy_fixture_is_still_rejected[case{i}]'
                      for i in range(3 if omit_negative else 4)]
        else:
            names = ['test_checker_fixture']
        for name in names:
            ET.SubElement(suite, 'testcase', classname='tests.route_c_stage2_6_1.'+module, name=name)
    suite.set('tests',str(len(list(suite))))
    if fail:
        ET.SubElement(suite[0], 'failure')
        suite.set('failures','1')
    if skip:
        ET.SubElement(suite[0], 'skipped')
        suite.set('skipped','1')
    path.write_bytes(ET.tostring(suite))
    return checker


@pytest.mark.parametrize('flag,expected', [('healthy',0),('fail',1),('skip',1),('omit',1)])
def test_targeted_checker_uses_entity_status_and_required_v10_names(tmp_path, flag, expected):
    p=tmp_path/'junit.xml'
    checker=make_targeted_junit(p,fail=flag=='fail',skip=flag=='skip',omit_negative=flag=='omit')
    assert checker.main(['--runner',str(ROOT/'references'),'--junit',str(p)]) == expected
