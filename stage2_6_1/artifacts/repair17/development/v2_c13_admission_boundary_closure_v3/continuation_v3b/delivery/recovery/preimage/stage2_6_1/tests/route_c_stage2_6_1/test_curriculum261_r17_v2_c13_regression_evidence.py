"""R17 V2 C1/C3 治理 v2:完整回归证据包校验器测试(F01-F12;§5.4 全部
负例;任务 R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2)。

负例逐项到达预期校验层(错误键命名断言,不被无关前置错误挡住);
校验器只读(F12 前后 tree snapshot 不变);生产 verifier 拒绝合成包
冒充(domain check)。full 模式的 git/双树复算用确定性 fake 生态
(临时 git 仓库 + 双树成员副本)覆盖,不依赖真实仓库工作区状态。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

HERE = Path(__file__).resolve()
for base in HERE.parents:
    for runner in (base / 'implementation', base / 'runner',
                   base / 'stage2_6_1' / 'runner',
                   base / 'stage2_6_1_runner'):
        if (runner / 'r17_v2_c13_profile.py').is_file():
            sys.path.insert(0, str(runner))
            break
    else:
        continue
    break
else:
    raise RuntimeError('v2c13 implementation not found')

import r17_v2_c13_profile as prof
import r17_v2_c13_regression_evidence as rev

_RUNNER_MEMBERS = ('r17_v2_c13_admission_guard',
                   'r17_v2_c13_batch', 'r17_v2_c13_pipeline',
                   'r17_v2_c13_profile', 'r17_v2_c13_regression_evidence')
_SRC_MEMBERS = ('curriculum261_pairs', 'curriculum261_r17_c2_launch_prep',
                'curriculum261_r17_param_pack', 'curriculum261_r6_design',
                'curriculum261_r6_param_pack')


def _tree_snapshot(root: Path) -> dict[str, tuple[int, str]]:
    out: dict[str, tuple[int, str]] = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_file():
            data = p.read_bytes()
            out[p.relative_to(root).as_posix()] = (len(data),
                                                   hashlib.sha256(
                                                       data).hexdigest())
    return out


def _remanifest(pkg: Path) -> None:
    index = {rel: meta for rel, meta in rev.package_content_index(pkg).items()
             if rel != 'manifest.json'}
    (pkg / 'manifest.json').write_text(
        json.dumps({'format': rev.PACKAGE_FORMAT, 'files': index}, indent=2,
                   sort_keys=True), encoding='utf-8')


def _read_json(pkg: Path, rel: str):
    return json.loads((pkg / rel).read_text(encoding='utf-8'))


def _write_json(pkg: Path, rel: str, doc) -> None:
    (pkg / rel).write_text(json.dumps(doc, indent=2, sort_keys=True),
                           encoding='utf-8')


def _sources_stub() -> dict:
    return {m: {'path': f'/deployed/{m}.py', 'sha256': hashlib.sha256(
        m.encode()).hexdigest()} for m in _RUNNER_MEMBERS + tuple(
        'rl_curriculum.' + s for s in _SRC_MEMBERS)}


@pytest.fixture
def healthy(tmp_path):
    """结构层健康包 + 合成 authority(域内)。"""
    repo = tmp_path / 'repo'
    claim = repo / 'claim'
    claim.mkdir(parents=True)
    auth = prof.synthetic_authority(repo, claim)
    pkg = prof.authoritative_full_regression_path(auth)
    built = rev.build_synthetic_package(pkg, current_sources=_sources_stub())
    return auth, pkg, built


# ------------------------------------------------------------ 健康控制组
def test_healthy_control_passes_structural_and_is_read_only(healthy):
    """F12:健康包结构校验通过;校验器只读(前后 tree snapshot 相同)。"""
    auth, pkg, built = healthy
    before = _tree_snapshot(pkg)
    verdict = rev.verify_package(pkg, authority=auth,
                                 current_sources=_sources_stub(),
                                 checks='structural')
    assert verdict['ok'], verdict['errors']
    assert verdict['package_sha256'] == built['package_sha256']
    assert verdict['summary']['junit']['tests'] == 3
    after = _tree_snapshot(pkg)
    assert before == after
    # 同包重复校验 digest 稳定(内容寻址)。
    again = rev.verify_package(pkg, authority=auth, checks='structural')
    assert again['package_sha256'] == verdict['package_sha256']


def test_production_verifier_rejects_synthetic_domain(healthy, tmp_path):
    """R02:生产 authority 的域检查拒绝 tmp 合成包(不冒充生产证据)。"""
    _auth, pkg, _built = healthy
    verdict = rev.verify_package(pkg, authority=prof.production_authority(),
                                 checks='structural')
    assert verdict['ok'] is False
    assert any(key == 'domain_escape'
               for key, _ in verdict['errors']), verdict['errors']


# ------------------------------------------------------- §5.4 负例(结构层)
def _expect_reject(auth, pkg, expected_key, **kwargs):
    verdict = rev.verify_package(pkg, authority=auth,
                                 current_sources=kwargs.pop(
                                     'current_sources', _sources_stub()),
                                 checks=kwargs.pop('checks', 'structural'),
                                 **kwargs)
    keys = [key for key, _ in verdict['errors']]
    assert verdict['ok'] is False
    assert expected_key in keys, (
        f'expected {expected_key}, got {keys}: '
        f'{[m for _, m in verdict["errors"]][:4]}')


def test_negative_root_missing(healthy):
    auth, pkg, _ = healthy
    shutil.rmtree(pkg)
    verdict = rev.verify_package(pkg, authority=auth, checks='structural')
    assert verdict['ok'] is False
    assert verdict['errors'][0][0] == 'package_root_missing'


def test_negative_rc0_but_junit_failure(healthy):
    auth, pkg, _ = healthy
    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace('failures="0"', 'failures="1"').replace(
            '<testcase ', '<testcase ', 1).replace(
            'test_synth_0" time="0.001"/>',
            'test_synth_0" time="0.001"><failure t="x"/></testcase>'),
        encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'junit_failures_nonzero')


def test_negative_junit_green_but_business_rc(healthy):
    auth, pkg, _ = healthy
    (pkg / 'business.rc').write_text('2\n', encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'business_rc_nonzero')


def test_negative_entry_rc_nonzero(healthy):
    auth, pkg, _ = healthy
    (pkg / 'entry.rc').write_text('1\n', encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'entry_rc_nonzero')


def test_negative_junit_empty(healthy):
    auth, pkg, _ = healthy
    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace('tests="3"', 'tests="0"').replace(
            '<testcase classname="tests.route_c_stage2_6_1.test_synth" '
            'name="test_synth_0" time="0.001"/>', ''),
        encoding='utf-8')
    (pkg / 'collected_tests.txt').write_text(
        '0 tests collected\n', encoding='utf-8')
    (pkg / 'business.stdout.log').write_text(
        'no tests ran in 0.01s\n', encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'junit_empty')


def test_negative_supervision_not_finalized(healthy):
    auth, pkg, _ = healthy
    rr = _read_json(pkg, 'supervision/run_record.json')
    rr['finalized'] = False
    _write_json(pkg, 'supervision/run_record.json', rr)
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'supervision_not_finalized')


def test_negative_stdout_appended(healthy):
    """stdout 追加:字节与 manifest 不一致(manifest 不重签)。"""
    auth, pkg, _ = healthy
    with open(pkg / 'business.stdout.log', 'ab') as fh:
        fh.write(b'appended-line\n')
    _expect_reject(auth, pkg, 'manifest_mismatch')


def test_negative_junit_equal_length_tamper(healthy):
    """JUnit 等长篡改(不改长度,不重签 manifest)→ manifest_mismatch。"""
    auth, pkg, _ = healthy
    body = (pkg / 'junit.xml').read_bytes()
    i = body.index(b'test_synth_0')
    tampered = body[:i] + b'test_syNth_0' + body[i + len(b'test_synth_0'):]
    assert len(tampered) == len(body)
    (pkg / 'junit.xml').write_bytes(tampered)
    _expect_reject(auth, pkg, 'manifest_mismatch')


def test_negative_tamper_with_manifest_resign_caught_by_role_anchor(healthy):
    """F10 内层语义锚:篡改 junit + 重签外层 manifest + 改 required
    条目,supervisor run_record 记录的角色 sha 仍然拒绝。"""
    auth, pkg, _ = healthy
    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace('test_synth_0', 'test_syNth_0'), encoding='utf-8')
    required = _read_json(pkg, 'required_files.json')
    data = (pkg / 'junit.xml').read_bytes()
    for e in required['entries']:
        if e['path'] == 'junit.xml':
            e['sha256'] = hashlib.sha256(data).hexdigest()
            e['size'] = len(data)
    _write_json(pkg, 'required_files.json', required)
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'required_role_sha_mismatch')


def test_negative_package_digest_changes_on_manifest_resign(healthy):
    """F10:重签外层 manifest 改变内容寻址包 digest(receipt 锚定值
    因此失配;chain 层在 reader_binding/synthetic_chain 覆盖)。"""
    auth, pkg, built = healthy
    before = rev.package_digest(pkg)
    assert before == built['package_sha256']
    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace('test_synth_0', 'test_syNth_0'), encoding='utf-8')
    _remanifest(pkg)
    after = rev.package_digest(pkg)
    assert after != before


def test_negative_critical_test_skipped(healthy):
    auth, pkg, _ = healthy
    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace(
            'test_synth_0" time="0.001"/>',
            'test_synth_0" time="0.001"><skipped type="pytest.skip"/>'
            '</testcase>').replace(
            'tests="3" failures="0" errors="0" skipped="0"',
            'tests="3" failures="0" errors="0" skipped="1"'),
        encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'critical_test_skipped')


def test_negative_unlisted_skip_rejected_and_allowlist_must_name_ids(healthy):
    """F05:非 critical 的 skip 必须逐 test id 列名;数字 allowlist 拒绝。"""
    auth, pkg, _ = healthy
    # 在非 critical 模块加一个 skip case(allowlist 为空 → 拒绝)。
    junit = (pkg / 'junit.xml').read_text(encoding='utf-8')
    (pkg / 'junit.xml').write_text(
        junit.replace(
            '</testsuite>',
            '<testcase classname="tests.route_c_stage2_6_1.test_other" '
            'name="test_old_legacy"><skipped/></testcase></testsuite>'
        ).replace('tests="3"', 'tests="4"').replace('skipped="0"',
                                                    'skipped="1"'),
        encoding='utf-8')
    (pkg / 'collected_tests.txt').write_text(
        (pkg / 'collected_tests.txt').read_text(encoding='utf-8').replace(
            '3 tests collected', '4 tests collected')
        + 'tests/route_c_stage2_6_1/test_other.py::test_old_legacy\n',
        encoding='utf-8')
    (pkg / 'business.stdout.log').write_text(
        '3 passed, 1 skipped in 0.01s\n', encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'unexpected_skip')
    # allowlist 写数字(不列 id)→ 形状拒绝。
    _write_json(pkg, 'skips_allowlist.json', {'allowed_skips': [1]})
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'allowlist_malformed')


def test_negative_collected_count_mismatch(healthy):
    auth, pkg, _ = healthy
    (pkg / 'collected_tests.txt').write_text(
        'tests/route_c_stage2_6_1/test_synth.py::test_synth_0\n'
        '2 tests collected\n', encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'collected_count_mismatch')


def test_negative_stdout_summary_mismatch(healthy):
    auth, pkg, _ = healthy
    (pkg / 'business.stdout.log').write_text(
        '2 passed in 0.01s\n', encoding='utf-8')
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'stdout_summary_mismatch')


def test_negative_missing_required_file(healthy):
    auth, pkg, _ = healthy
    (pkg / 'skips_allowlist.json').unlink()
    _expect_reject(auth, pkg, 'missing_required_file')


def test_negative_required_file_bytes_changed(healthy):
    """F09/§15:required/native 文件字节变更拒绝。"""
    auth, pkg, _ = healthy
    data = (pkg / 'supervision/run_record.json').read_bytes()
    (pkg / 'supervision/run_record.json').write_bytes(data + b' ')
    _expect_reject(auth, pkg, 'manifest_mismatch')
    # 重签 manifest 后 required 条目字节层拒绝。
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'required_file_mismatch')


def test_negative_symlink_to_healthy_package(healthy, tmp_path):
    """F02:健康包的 symlink 也拒绝(组件级 lstat)。"""
    auth, pkg, _ = healthy
    link_dir = pkg.parent / 'link_pkg'
    link_dir.symlink_to(pkg, target_is_directory=True)
    _expect_reject(auth, link_dir, 'symlink_component')


def test_negative_dotdot_escape_rejected(healthy, tmp_path):
    """F02:.. 路径逃逸(resolve 后在允许域外)拒绝。"""
    auth, pkg, _ = healthy
    outside = auth.repo_root.parent / 'outside' / 'pkg'
    outside.parent.mkdir(parents=True)
    shutil.copytree(pkg, outside)
    # claim 在 repo 下一级:两级 .. 即逃出 repo 根。
    esc = auth.repo_root / 'claim' / '..' / '..' / 'outside' / 'pkg'
    verdict = rev.verify_package(esc, authority=auth, checks='structural')
    keys = [k for k, _ in verdict['errors']]
    assert verdict['ok'] is False
    assert 'domain_escape' in keys or 'symlink_component' in keys, keys


def test_negative_non_regular_file(healthy):
    """包成员不是 regular file(symlink 成员也拒绝;F02/§5.2-3)。"""
    auth, pkg, _ = healthy
    target = pkg / 'business.stderr.log'
    (pkg / 'entry.rc').unlink()
    (pkg / 'entry.rc').symlink_to(target)
    try:
        verdict = rev.verify_package(pkg, authority=auth,
                                     checks='structural')
        keys = [k for k, _ in verdict['errors']]
        assert 'non_regular_file' in keys, keys
    finally:
        (pkg / 'entry.rc').unlink()
        (pkg / 'entry.rc').write_text('0\n', encoding='utf-8')


def test_negative_source_closure_mismatch(healthy):
    """不同候选回归:包记录闭包 ≠ 当前导入闭包 → 拒绝(B4/F11)。"""
    auth, pkg, _ = healthy
    wrong = {k: dict(v, sha256='ff' * 32 if i == 0 else v['sha256'])
             for i, (k, v) in enumerate(_sources_stub().items())}
    _expect_reject(auth, pkg, 'source_closure_mismatch',
                   current_sources=wrong)


def test_negative_unmanifested_extra_file(healthy):
    auth, pkg, _ = healthy
    (pkg / 'sneaky.txt').write_text('x', encoding='utf-8')
    _expect_reject(auth, pkg, 'unmanifested_file')


def test_negative_run_meta_identity_incomplete(healthy):
    """§5.2-4:命令/argv/cwd/env 身份缺失拒绝。"""
    auth, pkg, _ = healthy
    meta = _read_json(pkg, 'run_meta.json')
    meta['argv'] = []
    _write_json(pkg, 'run_meta.json', meta)
    _remanifest(pkg)
    _expect_reject(auth, pkg, 'run_meta_incomplete')


# --------------------------------------------- full 模式(fake 生态确定性)
@pytest.fixture
def full_eco(tmp_path):
    """确定性 fake 生态:git 候选仓库 + 发布/部署双树成员副本 + 记录
    一致的 full 模式证据包(源从发布库布局或部署平铺布局解析)。"""
    src_root = HERE.parents[0]
    while src_root.parent != src_root:
        # 布局判定以关键成员文件为准(部署树存在遗留 stage2_6_1/runner
        # 目录,不能仅凭目录名误判为发布布局)。
        if (src_root / 'stage2_6_1' / 'runner' / (
                'r17_v2_c13_profile.py')).is_file():
            layout = {'runner': src_root / 'stage2_6_1' / 'runner',
                      'src': src_root / 'stage2_6_1' / 'src' /
                      'rl_curriculum',
                      'tests': src_root / 'stage2_6_1' / 'tests' /
                      'route_c_stage2_6_1'}
            break
        if (src_root / 'stage2_6_1_runner' / (
                'r17_v2_c13_profile.py')).is_file():
            layout = {'runner': src_root / 'stage2_6_1_runner',
                      'src': src_root / 'src' / 'rl_curriculum',
                      'tests': src_root / 'tests' / 'route_c_stage2_6_1'}
            break
        src_root = src_root.parent
    else:
        raise RuntimeError('neither release nor deploy layout found')
    release = tmp_path / 'fake_release'
    deploy = tmp_path / 'fake_deploy'
    for sub in ('stage2_6_1/runner', 'stage2_6_1/src/rl_curriculum',
                'stage2_6_1/tests/route_c_stage2_6_1'):
        (release / sub).mkdir(parents=True)
    for sub in ('stage2_6_1_runner', 'src/rl_curriculum',
                'tests/route_c_stage2_6_1'):
        (deploy / sub).mkdir(parents=True)

    def copy(src: Path, rel_release, rel_deploy):
        data = src.read_bytes()
        (release / rel_release).write_bytes(data)
        (deploy / rel_deploy).write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    members: dict[str, str] = {}
    for m in _RUNNER_MEMBERS:
        members[m] = copy(layout['runner'] / f'{m}.py',
                          f'stage2_6_1/runner/{m}.py',
                          f'stage2_6_1_runner/{m}.py')
    for m in _SRC_MEMBERS:
        members[f'rl_curriculum.{m}'] = copy(
            layout['src'] / f'{m}.py',
            f'stage2_6_1/src/rl_curriculum/{m}.py',
            f'src/rl_curriculum/{m}.py')
    lock_src = layout['runner'] / 'r17_v2_c13_governance_source_lock.py'
    lock_data = lock_src.read_bytes()
    lock_file = release / 'stage2_6_1' / 'runner' / (
        'r17_v2_c13_governance_source_lock.py')
    lock_file.write_bytes(lock_data)
    test_rel = []
    for f in sorted(layout['tests'].glob('test_*.py')):
        data = f.read_bytes()
        (release / 'stage2_6_1' / 'tests' / 'route_c_stage2_6_1' /
         f.name).write_bytes(data)
        (deploy / 'tests' / 'route_c_stage2_6_1' / f.name).write_bytes(data)
        test_rel.append((f'tests/route_c_stage2_6_1/{f.name}',
                         hashlib.sha256(data).hexdigest()))

    def git(*args):
        proc = subprocess.run(['git', '-C', str(release), *args],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return proc.stdout.strip()

    git('init', '-q')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    git('add', '-A')
    git('commit', '-qm', 'candidate')
    candidate = git('rev-parse', 'HEAD')

    repo = tmp_path / 'fake_repo'
    claim = repo / 'claim'
    claim.mkdir(parents=True)
    auth = prof.synthetic_authority(repo, claim)
    pkg = prof.authoritative_full_regression_path(auth)
    sources = {m: {'path': str(deploy / m), 'sha256': s}
               for m, s in members.items()}
    rev.build_synthetic_package(pkg, current_sources=sources)
    # 用 fake 生态事实覆写记录层。
    closure = _read_json(pkg, 'source_closure.json')
    closure['candidate_commit'] = candidate
    closure['governance_lock_file'] = {
        'path': str(release / 'stage2_6_1' / 'runner' / (
            'r17_v2_c13_governance_source_lock.py')),
        'sha256': hashlib.sha256(lock_data).hexdigest()}
    closure['members'] = members
    closure['members_digest'] = rev._sha256_bytes(
        rev._canonical(members).encode('utf-8'))
    _write_json(pkg, 'source_closure.json', closure)
    meta = _read_json(pkg, 'run_meta.json')
    meta.update(candidate_commit=candidate,
                git_head_at_collect=candidate,
                release_repo=str(release), deploy_root=str(deploy))
    _write_json(pkg, 'run_meta.json', meta)
    (pkg / 'test_files.sha256').write_text(
        ''.join(f'{sha}  {rel}\n' for rel, sha in sorted(test_rel)),
        encoding='utf-8')
    identity = {'release': {}, 'deploy': {}}
    for m in _RUNNER_MEMBERS:
        identity['release'][m] = {
            'file': str(release / 'stage2_6_1' / 'runner' / f'{m}.py'),
            'sha256': members[m]}
        identity['deploy'][m] = {
            'file': str(deploy / 'stage2_6_1_runner' / f'{m}.py'),
            'sha256': members[m]}
    for m in _SRC_MEMBERS:
        identity['release'][f'rl_curriculum.{m}'] = {
            'file': str(release / 'stage2_6_1' / 'src' / 'rl_curriculum'
                        / f'{m}.py'),
            'sha256': members[f'rl_curriculum.{m}']}
        identity['deploy'][f'rl_curriculum.{m}'] = {
            'file': str(deploy / 'src' / 'rl_curriculum' / f'{m}.py'),
            'sha256': members[f'rl_curriculum.{m}']}
    _write_json(pkg, 'import_identity.json', identity)
    _remanifest(pkg)
    return {'auth': auth, 'pkg': pkg, 'release': release, 'deploy': deploy,
            'candidate': candidate, 'members': members, 'git': git,
            'sources': sources, 'lock_file': lock_file,
            'lock_data': lock_data}


def test_full_mode_healthy_and_candidate_layers(full_eco):
    """full 模式健康控制组:git/双树/lock/import 全部闭合。"""
    eco = full_eco
    verdict = rev.verify_package(eco['pkg'], authority=eco['auth'],
                                 current_sources=eco['sources'],
                                 checks='full')
    assert verdict['ok'], verdict['errors']


def test_full_mode_candidate_commit_missing(full_eco):
    eco = full_eco
    meta = _read_json(eco['pkg'], 'run_meta.json')
    meta['candidate_commit'] = 'de' * 20
    _write_json(eco['pkg'], 'run_meta.json', meta)
    _remanifest(eco['pkg'])
    _expect_reject(eco['auth'], eco['pkg'], 'candidate_commit_missing',
                   current_sources=eco['sources'], checks='full')


def test_full_mode_candidate_drift_after_regression(full_eco):
    """候选 commit 存在,但回归后 runner/src/tests 漂移 → 拒绝。"""
    eco = full_eco
    target = eco['release'] / 'stage2_6_1' / 'runner' / (
        'r17_v2_c13_batch.py')
    target.write_bytes(target.read_bytes() + b'\n# drift\n')
    eco['git']('add', '-A')
    eco['git']('commit', '-qm', 'drift')
    _expect_reject(eco['auth'], eco['pkg'], 'candidate_drift',
                   current_sources=eco['sources'], checks='full')


def test_full_mode_worktree_dirty(full_eco):
    eco = full_eco
    target = eco['release'] / 'stage2_6_1' / 'tests' / (
        'route_c_stage2_6_1')
    (target / 'test_drift_uncommitted.py').write_text('x = 1\n',
                                                      encoding='utf-8')
    try:
        _expect_reject(eco['auth'], eco['pkg'], 'worktree_not_clean',
                       current_sources=eco['sources'], checks='full')
    finally:
        (target / 'test_drift_uncommitted.py').unlink()


def test_full_mode_lock_vs_deploy_import_differ(full_eco):
    """source lock 与部署实际 import 不同 → 拒绝(§5.2-13)。"""
    eco = full_eco
    victim = eco['deploy'] / 'stage2_6_1_runner' / 'r17_v2_c13_batch.py'
    victim.write_bytes(victim.read_bytes() + b'\n# tampered\n')
    verdict = rev.verify_package(eco['pkg'], authority=eco['auth'],
                                 current_sources=eco['sources'],
                                 checks='full')
    keys = [k for k, _ in verdict['errors']]
    assert 'closure_member_mismatch' in keys and \
        'import_identity_mismatch' in keys, keys


def test_full_mode_test_file_deleted_or_changed(full_eco):
    """删除/变更测试文件:记录集合与部署树实际集合/字节失配 → 拒绝
    (live 复算只针对部署树,即 pytest 实际运行面)。"""
    eco = full_eco
    some = sorted((eco['deploy'] / 'tests' / 'route_c_stage2_6_1').glob(
        'test_*.py'))[0]
    some.unlink()
    try:
        _expect_reject(eco['auth'], eco['pkg'], 'test_file_set_changed',
                       current_sources=eco['sources'], checks='full')
    finally:
        shutil.copy2(
            eco['release'] / 'stage2_6_1' / 'tests' / 'route_c_stage2_6_1'
            / some.name, some)
    # 部署树字节变更:hash 失配(发布库副本无关)。
    data = some.read_bytes()
    try:
        some.write_bytes(data + b'\n# x\n')
        _expect_reject(eco['auth'], eco['pkg'], 'test_file_hash_mismatch',
                       current_sources=eco['sources'], checks='full')
    finally:
        some.write_bytes(data)


def test_full_mode_governance_lock_drift(full_eco):
    eco = full_eco
    eco['lock_file'].write_bytes(eco['lock_data'] + b'\n# drifted\n')
    try:
        _expect_reject(eco['auth'], eco['pkg'], 'governance_lock_drift',
                       current_sources=eco['sources'], checks='full')
    finally:
        eco['lock_file'].write_bytes(eco['lock_data'])
