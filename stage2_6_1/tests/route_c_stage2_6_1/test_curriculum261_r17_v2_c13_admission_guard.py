"""v3 direct-boundary integration tests: real patched modules, no production writes."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import shutil
import sys

import pytest

HERE = Path(__file__).resolve()
for base in HERE.parents:
    for runner in (base/'implementation', base/'runner', base/'stage2_6_1/runner',
                   base/'stage2_6_1_runner'):
        if (runner/'r17_v2_c13_profile.py').is_file():
            sys.path.insert(0, str(runner)); break
    else:
        continue
    break
else:
    raise RuntimeError('patched runner not found')

import r17_v2_c13_profile as prof
import r17_v2_c13_regression_evidence as rev
import r17_v2_c13_admission_guard as guard
from test_curriculum261_r17_v2_c13_claim_protocol import (authority, _persist_plan_and_receipt)
from test_curriculum261_r17_v2_c13_regression_evidence import (healthy, full_eco, _remanifest)


def edit(pkg, rel, fn):
    p = pkg/rel
    doc = json.loads(p.read_text())
    fn(doc)
    p.write_text(json.dumps(doc))
    _remanifest(pkg)


def errors(auth, pkg, **kw):
    r = rev.verify_package(pkg, authority=auth, checks=kw.pop('checks', 'structural'), **kw)
    assert r['ok'] is False, r
    return {k for k, _ in r['errors']}


def test_direct_foreign_production_authority_is_rejected(tmp_path):
    with pytest.raises(prof.ProfileError, match='noncanonical'):
        prof.Authority(tmp_path/'foreign', tmp_path/'foreign/claim', synthetic=False)
    assert not (tmp_path/'foreign').exists()


def test_resolve_rechecks_even_a_forged_dataclass(tmp_path):
    obj = object.__new__(prof.Authority)
    object.__setattr__(obj, 'repo_root', tmp_path/'foreign')
    object.__setattr__(obj, 'claim_root', tmp_path/'foreign/claim')
    object.__setattr__(obj, 'synthetic', False)
    for call in (prof.resolve_authority, prof.authoritative_plan_path,
                 prof.authoritative_full_regression_path, prof.consume_production_claim):
        with pytest.raises(prof.ProfileError):
            call(authority=obj)
    assert not (tmp_path/'foreign').exists()


@pytest.mark.parametrize('missing', ['regression', 'admission'])
def test_direct_claim_missing_dependency_cannot_use_just_receipt(authority, missing):
    _persist_plan_and_receipt(authority)
    if missing == 'regression':
        shutil.rmtree(prof.authoritative_full_regression_path(authority))
    else:
        prof.authoritative_evidence_path(authority).unlink()
    with pytest.raises(Exception):
        prof.consume_production_claim(authority=authority)
    assert not (authority.claim_root/f'{prof.CONTRACT}.json').exists()


def test_direct_claim_revalidates_real_package_digest(authority):
    _persist_plan_and_receipt(authority)
    pkg = prof.authoritative_full_regression_path(authority)
    # Valid JSON/outer manifest, invalid role set: direct entry must still reject.
    edit(pkg, 'required_files.json', lambda d: d.update(entries=[]))
    with pytest.raises(Exception, match='full regression evidence rejected'):
        prof.consume_production_claim(authority=authority)
    assert not (authority.claim_root/f'{prof.CONTRACT}.json').exists()


def test_direct_claim_does_not_trust_receipt_source_string(authority):
    _persist_plan_and_receipt(authority)
    p = prof.receipt_path(authority)
    d = json.loads(p.read_text()); d['source_closure_sha256'] = 'cd'*32
    p.write_text(json.dumps(d))
    with pytest.raises(Exception, match='different source closure'):
        prof.consume_production_claim(authority=authority)
    assert not (authority.claim_root/f'{prof.CONTRACT}.json').exists()


def test_complete_fixture_claim_stays_synthetic(authority):
    _persist_plan_and_receipt(authority)
    verdict = prof.validate_claim_admission(authority)
    assert verdict['full_regression_evidence_sha256'] == rev.package_digest(
        prof.authoritative_full_regression_path(authority))
    prof.consume_production_claim(authority=authority)
    claim = json.loads((authority.claim_root/f'{prof.CONTRACT}.json').read_text())
    assert claim['synthetic'] is True


@pytest.mark.parametrize('role', sorted(guard.ROLE_PATHS))
def test_required_role_omission_cannot_be_resigned_away(healthy, role):
    auth,pkg,_=healthy
    edit(pkg,'required_files.json',lambda d:d.update(entries=[e for e in d['entries'] if e['role']!=role]))
    assert 'required_role_set_mismatch' in errors(auth,pkg)


def test_empty_critical_policy_rejected(healthy):
    auth,pkg,_=healthy
    edit(pkg,'critical_tests.json',lambda d:d.update(critical_test_files=[]))
    assert 'critical_policy_mismatch' in errors(auth,pkg)


def test_empty_required_and_supervisor_sets_both_rejected(healthy):
    auth,pkg,_=healthy
    edit(pkg,'required_files.json',lambda d:d.update(entries=[]))
    edit(pkg,'supervision/run_record.json',lambda d:d.update(required=[]))
    assert 'required_role_set_mismatch' in errors(auth,pkg)


def test_failure_entity_cannot_hide_under_zero_suite_count(healthy):
    auth,pkg,_=healthy
    p=pkg/'junit.xml'
    p.write_text(p.read_text().replace('test_synth_0" time="0.001"/>',
        'test_synth_0" time="0.001"><failure/></testcase>'))
    _remanifest(pkg)
    keys=errors(auth,pkg)
    assert 'junit_failures_nonzero' in keys and 'junit_count_inconsistent' in keys


def test_same_count_different_testcase_is_rejected(healthy):
    auth,pkg,_=healthy
    p=pkg/'collected_tests.txt'; p.write_text(p.read_text().replace('test_synth_0','test_unexecuted'))
    _remanifest(pkg)
    assert 'collected_membership_mismatch' in errors(auth,pkg)


def test_directory_symlink_rejected_before_read(healthy):
    auth,pkg,_=healthy
    (pkg/'alias').symlink_to(pkg/'supervision', target_is_directory=True)
    assert 'non_regular_file' in errors(auth,pkg)


def test_production_cannot_downgrade_to_structural(healthy):
    _,pkg,_=healthy
    r=rev.verify_package(pkg,authority=prof.production_authority(),checks='structural')
    assert r['ok'] is False and r['admission_eligible'] is False


def test_full_c_to_e_to_e2_cold_read_accepts_unchanged_code(full_eco):
    e=full_eco
    def check():
        r=rev.verify_package(e['pkg'],authority=e['auth'],current_sources=e['sources'],checks='full')
        assert r['ok'],r['errors']
    check()
    path=e['release']/guard.NEW_EVIDENCE_ROOT/'report.md'
    path.parent.mkdir(parents=True); path.write_text('E evidence\n')
    e['git']('add','-A'); e['git']('commit','-qm','E evidence only')
    check()
    path.write_text('E2 evidence erratum\n')
    e['git']('add','-A'); e['git']('commit','-qm','E2 evidence only')
    check()
    assert json.loads((e['pkg']/'run_meta.json').read_text())['git_head_at_collect']==e['candidate']


def test_import_origin_missing_is_not_skipped(full_eco):
    e=full_eco
    path=e['deploy']/'stage2_6_1_runner/r17_v2_c13_profile.py'
    path.unlink()
    assert 'import_identity_mismatch' in errors(e['auth'],e['pkg'],checks='full',current_sources=e['sources'])


def test_same_size_missing_origin_path_not_accepted(full_eco):
    e=full_eco
    edit(e['pkg'],'import_identity.json',lambda d:d['deploy']['r17_v2_c13_profile'].update(file='/nonexistent/profile.py'))
    assert 'import_identity_mismatch' in errors(e['auth'],e['pkg'],checks='full',current_sources=e['sources'])


def test_code_change_then_revert_is_not_evidence_only(full_eco):
    e=full_eco
    path=e['release']/'stage2_6_1/runner/r17_v2_c13_batch.py'
    data=path.read_bytes(); path.write_bytes(data+b'\n# changed\n')
    e['git']('add','-A'); e['git']('commit','-qm','source change')
    path.write_bytes(data); e['git']('add','-A'); e['git']('commit','-qm','revert')
    assert 'candidate_drift' in errors(e['auth'],e['pkg'],checks='full',current_sources=e['sources'])

# v3b: candidate-owned complete recursive test set. No production writes.
@pytest.fixture
def v3b_test_ecology(tmp_path):
    import hashlib
    import subprocess
    repo = tmp_path / 'map_repo'
    deploy = tmp_path / 'map_deploy'
    repo.mkdir()
    def git(*args):
        return guard.git_checked(repo, *args).decode().strip()
    git('init', '-q'); git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'user.name', 'R17 synthetic mapping tests')
    git('config', 'core.autocrlf', 'false')
    files = {
        'stage2_6_1/tests/test_root.py': b'def test_root():\r\n    assert True\r\n',
        'stage2_6_1/tests/route_c_stage2_6_1/test_nested.py': b'def test_nested():\n    assert True\n',
        'stage2_6_1/tests/route_c_stage2_6_1/conftest.py': b'# candidate support file\n',
    }
    for source, body in files.items():
        src = repo / source; src.parent.mkdir(parents=True, exist_ok=True); src.write_bytes(body)
        dst = deploy / 'tests/route_c_stage2_6_1' / src.name
        dst.parent.mkdir(parents=True, exist_ok=True); dst.write_bytes(body.replace(b'\r', b''))
    git('add', '.'); git('commit', '-qm', 'synthetic candidate')
    candidate = git('rev-parse', 'HEAD')
    mapping = guard.candidate_test_map(repo, candidate)
    manifest = ''.join(row['deploy_sha256'] + '  ' + rel + '\n'
                       for rel, row in mapping.items() if row['is_test']).encode()
    cases = [{'classname': 'tests.route_c_stage2_6_1.test_root', 'name': 'test_root', 'skipped': False},
             {'classname': 'tests.route_c_stage2_6_1.test_nested', 'name': 'test_nested', 'skipped': False}]
    collection = [guard.junit_nodeid(c) for c in cases]
    return {'repo': repo, 'deploy': deploy, 'candidate': candidate, 'git': git,
            'mapping': mapping, 'manifest': manifest, 'cases': cases, 'collection': collection}


def v3b_map_check(e, **overrides):
    values = {k: e[k] for k in ('repo', 'candidate', 'manifest', 'collection', 'cases')}
    values['deploy_root'] = e['deploy']; values.update(overrides)
    return guard.verify_candidate_tests(**values)


def test_v3b_root_and_nested_candidate_tests_are_both_required(v3b_test_ecology):
    e = v3b_test_ecology
    assert len(e['mapping']) == 3
    assert e['mapping']['tests/route_c_stage2_6_1/test_root.py']['source_path'] == 'stage2_6_1/tests/test_root.py'
    assert v3b_map_check(e) == []


@pytest.mark.parametrize('mutation', ['deploy_only', 'manifest_only', 'both', 'everything'])
def test_v3b_dropping_root_origin_never_produces_green_subset(v3b_test_ecology, mutation):
    e = v3b_test_ecology; rel = 'tests/route_c_stage2_6_1/test_root.py'
    if mutation in ('deploy_only', 'both', 'everything'):
        (e['deploy'] / rel).unlink()
    if mutation in ('manifest_only', 'both', 'everything'):
        e['manifest'] = b''.join(line for line in e['manifest'].splitlines(keepends=True) if rel.encode() not in line)
    if mutation == 'everything':
        e['collection'] = [n for n in e['collection'] if not n.startswith(rel+'::')]
        e['cases'] = [c for c in e['cases'] if not c['classname'].endswith('test_root')]
    keys = {k for k, _ in v3b_map_check(e)}
    assert keys
    if mutation in ('manifest_only', 'both', 'everything'):
        assert 'test_candidate_set_mismatch' in keys
    if mutation == 'everything':
        assert 'test_execution_set_mismatch' in keys


@pytest.mark.parametrize('same_bytes', [False, True])
def test_v3b_duplicate_basename_rejected_even_with_equal_bytes(v3b_test_ecology, same_bytes):
    e = v3b_test_ecology
    p = e['repo'] / 'stage2_6_1/tests/another/test_root.py'; p.parent.mkdir(parents=True)
    p.write_bytes((e['repo'] / 'stage2_6_1/tests/test_root.py').read_bytes() if same_bytes else b'# alternate\n')
    e['git']('add', '.'); e['git']('commit', '-qm', 'synthetic duplicate')
    with pytest.raises(guard.AdmissionError, match='test_source_collision'):
        guard.candidate_test_map(e['repo'], e['git']('rev-parse', 'HEAD'))


def test_v3b_casefold_collision_rejected(v3b_test_ecology):
    e = v3b_test_ecology
    p = e['repo'] / 'stage2_6_1/tests/test_ROOT.py'; p.write_bytes(b'# different case\n')
    e['git']('add', '.'); e['git']('commit', '-qm', 'synthetic case collision')
    with pytest.raises(guard.AdmissionError, match='test_source_collision'):
        guard.candidate_test_map(e['repo'], e['git']('rev-parse', 'HEAD'))


def test_v3b_normalization_matches_all_CR_removal_not_just_CRLF(v3b_test_ecology):
    e = v3b_test_ecology
    p = e['repo'] / 'stage2_6_1/tests/test_root.py'
    p.write_bytes(b'def test_root():\r\n    assert True\r# CR inside comment\n')
    e['git']('add', '.'); e['git']('commit', '-qm', 'synthetic CR fixture')
    mapping = guard.candidate_test_map(e['repo'], e['git']('rev-parse', 'HEAD'))
    import hashlib
    row = mapping['tests/route_c_stage2_6_1/test_root.py']
    assert row['deploy_sha256'] == hashlib.sha256(p.read_bytes().replace(b'\r', b'')).hexdigest()
    assert row['deploy_sha256'] != hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


@pytest.mark.parametrize('mutation', ['duplicate_manifest', 'empty_manifest', 'foreign_manifest', 'extra_deployed', 'missing_support', 'support_tamper', 'missing_execution', 'foreign_execution', 'duplicate_collection'])
def test_v3b_mapping_and_execution_negatives(v3b_test_ecology, mutation):
    e = v3b_test_ecology
    if mutation == 'duplicate_manifest':
        e['manifest'] += e['manifest'].splitlines(keepends=True)[0]
    elif mutation == 'empty_manifest':
        e['manifest'] = b''
    elif mutation == 'foreign_manifest':
        e['manifest'] += b'aa' * 32 + b'  tests/route_c_stage2_6_1/test_foreign.py\n'
    elif mutation == 'extra_deployed':
        (e['deploy'] / 'tests/route_c_stage2_6_1/test_foreign.py').write_bytes(b'def test_foreign(): pass\n')
    elif mutation == 'missing_support':
        (e['deploy'] / 'tests/route_c_stage2_6_1/conftest.py').unlink()
    elif mutation == 'support_tamper':
        (e['deploy'] / 'tests/route_c_stage2_6_1/conftest.py').write_bytes(b'# changed\n')
    elif mutation == 'missing_execution':
        e['collection'] = e['collection'][1:]; e['cases'] = e['cases'][1:]
    elif mutation == 'foreign_execution':
        e['collection'][0] += '_foreign'
    else:
        e['collection'].append(e['collection'][0])
    assert v3b_map_check(e)


@pytest.mark.parametrize('source_link', [False, True])
def test_v3b_test_symlink_is_not_a_source_or_deployed_test(v3b_test_ecology, source_link):
    e = v3b_test_ecology
    if source_link:
        path = e['repo'] / 'stage2_6_1/tests/test_link.py'
        path.symlink_to('test_root.py')
        e['git']('add', '.'); e['git']('commit', '-qm', 'synthetic link')
        with pytest.raises(guard.AdmissionError, match='nonregular'):
            guard.candidate_test_map(e['repo'], e['git']('rev-parse', 'HEAD'))
    else:
        path = e['deploy'] / 'tests/route_c_stage2_6_1/test_root.py'
        path.unlink(); path.symlink_to(e['repo'] / 'stage2_6_1/tests/test_root.py')
        assert 'test_file_hash_mismatch' in {k for k, _ in v3b_map_check(e)}


def test_v3b_collection_and_junit_class_parameter_identity(v3b_test_ecology):
    e = v3b_test_ecology
    e['cases'][0].update(classname='tests.route_c_stage2_6_1.test_root.TestClass', name='test_root[x.y]')
    e['collection'][0] = 'tests/route_c_stage2_6_1/test_root.py::TestClass::test_root[x.y]'
    assert v3b_map_check(e) == []
