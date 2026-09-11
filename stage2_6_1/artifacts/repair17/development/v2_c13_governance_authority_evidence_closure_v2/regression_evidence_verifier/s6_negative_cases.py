#!/usr/bin/env python3
"""S6:完整回归证据包独立负例(每个 case 对临时副本只做一种变异)。

输出每 case:mutation.txt / before.sha256 / after.sha256 / command.txt /
stdout.log / stderr.log / rc.txt;健康控制组通过;原健康包前后不变。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

W = Path('/home/cryptorl/projects/crypto_rl/work/'
         'R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2')
RELEASE = Path('/mnt/f/trading/freqai-rl-audit')
DEPLOY = Path('/home/cryptorl/projects/crypto_rl')
CANDIDATE = (W / 'CANDIDATE_COMMIT.txt').read_text().strip()
CASES_ROOT = W / 'negative_cases'
PKG_SRC = W / 'healthy_package'

sys.path.insert(0, str(DEPLOY / 'stage2_6_1_runner'))
import r17_v2_c13_regression_evidence as rev  # noqa: E402


def tree_index(root: Path) -> dict:
    return rev.package_content_index(root)


def sha_of_index(index: dict) -> str:
    return hashlib.sha256(rev._canonical(index).encode()).hexdigest()


def remanifest(pkg: Path) -> None:
    idx = {rel: m for rel, m in rev.package_content_index(pkg).items()
           if rel != 'manifest.json'}
    (pkg / 'manifest.json').write_text(json.dumps(
        {'format': rev.PACKAGE_FORMAT, 'files': idx}, indent=2,
        sort_keys=True), encoding='utf-8')


def read_json(pkg: Path, rel):
    return json.loads((pkg / rel).read_text(encoding='utf-8'))


def write_json(pkg: Path, rel, doc):
    (pkg / rel).write_text(json.dumps(doc, indent=2, sort_keys=True),
                           encoding='utf-8')


def junit_text(pkg: Path) -> str:
    return (pkg / 'junit.xml').read_text(encoding='utf-8')


def write_junit(pkg: Path, text: str):
    (pkg / 'junit.xml').write_text(text, encoding='utf-8')


def run_verify(target: Path, case_dir: Path) -> int:
    cmd = ['python', str(DEPLOY / 'stage2_6_1_runner' /
                         'r17_v2_c13_regression_evidence.py'),
           'verify', '--package', str(target),
           '--release-repo', str(RELEASE),
           '--deploy-root', str(DEPLOY)]
    (case_dir / 'command.txt').write_text(' '.join(cmd) + '\n')
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    (case_dir / 'stdout.log').write_text(proc.stdout)
    (case_dir / 'stderr.log').write_text(proc.stderr)
    (case_dir / 'rc.txt').write_text(f'{proc.returncode}\n')
    return proc.returncode


def case(name: str, mutate=None, target_override=None) -> dict:
    d = CASES_ROOT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    before_idx = tree_index(PKG_SRC)
    (d / 'before.sha256').write_text(
        f'{sha_of_index(before_idx)}  healthy-package\n')
    target = PKG_SRC
    if mutate is not None:
        pkg = d / 'package'
        shutil.copytree(PKG_SRC, pkg)
        mutate(pkg, d)
        target = pkg
    if target_override is not None:
        target = target_override(d)
    rc = run_verify(target, d)
    after_idx = tree_index(PKG_SRC)
    (d / 'after.sha256').write_text(
        f'{sha_of_index(after_idx)}  healthy-package\n')
    ok = (after_idx == before_idx)
    return {'case': name, 'rc': rc, 'healthy_unchanged': ok}


def m_rc0_junit_failure(pkg, d):
    write_junit(pkg, junit_text(pkg).replace(
        'failures="0"', 'failures="1"', 1))
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        'junit.xml failures 0→1(保持 rc=0)+ 重签 manifest\n')


def m_business_rc(pkg, d):
    (pkg / 'business.rc').write_text('2\n', encoding='utf-8')
    remanifest(pkg)
    (d / 'mutation.txt').write_text('business.rc 0→2 + 重签 manifest\n')


def m_entry_rc(pkg, d):
    (pkg / 'entry.rc').write_text('1\n', encoding='utf-8')
    remanifest(pkg)
    (d / 'mutation.txt').write_text('entry.rc 0→1 + 重签 manifest\n')


def m_junit_empty(pkg, d):
    import xml.etree.ElementTree as ET

    tree = ET.parse(pkg / 'junit.xml')
    for ts in tree.getroot().iter('testsuite'):
        ts.set('tests', '0')
        for tc in list(ts):
            ts.remove(tc)
    (pkg / 'junit.xml').write_text(_tostring(tree), encoding='utf-8')
    (pkg / 'collected_tests.txt').write_text(
        '0 tests collected\n', encoding='utf-8')
    (pkg / 'business.stdout.log').write_text(
        'no tests ran in 0.01s\n', encoding='utf-8')
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        'junit tests=0 且清空用例;collected=0;stdout=no tests ran\n')


def _tostring(tree):
    import xml.etree.ElementTree as ET

    body = ET.tostring(tree.getroot(), encoding='unicode')
    return '<?xml version="1.0" encoding="utf-8"?>' + body


def m_delete_test_file_entry(pkg, d):
    lines = (pkg / 'test_files.sha256').read_text(
        encoding='utf-8').splitlines()
    removed = lines.pop(0)
    (pkg / 'test_files.sha256').write_text(
        '\n'.join(lines) + '\n', encoding='utf-8')
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        f'test_files.sha256 删除一行(部署树仍有该文件): {removed[:100]}\n')


def m_add_unregistered_test_file(pkg, d):
    with open(pkg / 'test_files.sha256', 'a', encoding='utf-8') as fh:
        fh.write('0' * 64 + '  tests/route_c_stage2_6_1/'
                 'test_sneaky_extra.py\n')
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        'test_files.sha256 追加未登记测试文件条目(两树均不存在)\n')


def m_stdout_appended(pkg, d):
    with open(pkg / 'business.stdout.log', 'ab') as fh:
        fh.write(b'appended-evidence-line\n')
    (d / 'mutation.txt').write_text(
        'business.stdout.log 追加一行(manifest 不重签)\n')


def m_junit_equal_length_tamper(pkg, d):
    body = (pkg / 'junit.xml').read_bytes()
    marker = b'tests="'
    i = body.index(marker) + len(marker)
    # 等长篡改:tests 数值首个字符替换(如 2→3,长度不变)。
    tampered = body[:i] + bytes([body[i] + 1]) + body[i + 1:]
    assert len(tampered) == len(body)
    (pkg / 'junit.xml').write_bytes(tampered)
    (d / 'mutation.txt').write_text(
        'junit.xml tests 属性等长篡改(manifest 不重签)\n')


def m_manifest_resign(pkg, d):
    body = (pkg / 'junit.xml').read_bytes()
    marker = b'tests="'
    i = body.index(marker) + len(marker)
    (pkg / 'junit.xml').write_bytes(
        body[:i] + bytes([body[i] + 1]) + body[i + 1:])
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        'junit 篡改 + 外层 manifest 重签(内层 required 角色锚仍拒绝;'
        '包 digest 漂移破坏 receipt 锚)\n')


def m_source_closure_mismatch(pkg, d):
    doc = read_json(pkg, 'source_closure.json')
    first = sorted(doc['members'])[0]
    doc['members'][first] = 'ff' * 32
    doc['members_digest'] = rev._sha256_bytes(
        rev._canonical(doc['members']).encode('utf-8'))
    write_json(pkg, 'source_closure.json', doc)
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        f'source_closure 成员 {first} 改为伪 sha(与部署实际 import 不同)\n')


def m_candidate_missing(pkg, d):
    doc = read_json(pkg, 'run_meta.json')
    doc['candidate_commit'] = 'de' * 20
    write_json(pkg, 'run_meta.json', doc)
    remanifest(pkg)
    (d / 'mutation.txt').write_text('run_meta candidate_commit = deadbeef\n')


def m_candidate_drift(pkg, d):
    doc = read_json(pkg, 'run_meta.json')
    doc['candidate_commit'] = 'bcc02aacb7877c015d6544c344d2eba82f05c5bc'
    write_json(pkg, 'run_meta.json', doc)
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        'run_meta candidate_commit = HEAD^(bcc02aa,runner/src/tests 在'
        '其..HEAD 间有漂移)\n')


def m_critical_skipped(pkg, d):
    crit = read_json(pkg, 'critical_tests.json')
    stem = crit['critical_test_files'][0]
    text = junit_text(pkg)
    import re
    # 找到该 critical 模块的第一个用例,标记 skip。
    m = re.search(r'<testcase classname="([^"]*%s[^"]*)" name="([^"]+)"'
                  r'([^/>]*)/>' % re.escape(stem), text)
    assert m, f'critical case not found for {stem}'
    whole = m.group(0)
    replaced = (f'<testcase classname="{m.group(1)}" name="{m.group(2)}"'
                f'{m.group(3)}>'
                f'<skipped type="pytest.skip"/></testcase>')
    text = text.replace(whole, replaced, 1)
    write_junit(pkg, text)
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        f'critical 模块 {stem} 首个用例标记 skipped + 重签 manifest\n')


def m_required_missing(pkg, d):
    (pkg / 'supervision/summary.json').unlink()
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        '删除 required 文件 supervision/summary.json + 重签 manifest\n')


def m_required_changed(pkg, d):
    data = (pkg / 'supervision/run_record.json').read_bytes()
    (pkg / 'supervision/run_record.json').write_bytes(data + b' ')
    remanifest(pkg)
    (d / 'mutation.txt').write_text(
        'supervision/run_record.json 追加一个字节 + 重签 manifest'
        '(required 条目 sha 失配)\n')


def t_missing(d):
    return d / 'no_such_package'


def t_unspecified(d):
    return Path('unspecified')


def t_symlink(d):
    target = d / 'link_to_healthy'
    target.symlink_to(PKG_SRC, target_is_directory=True)
    (d / 'mutation.txt').write_text('symlink 指向健康包\n')
    return target


def t_dotdot(d):
    outside = d / 'outside' / 'pkg'
    outside.parent.mkdir(parents=True)
    shutil.copytree(PKG_SRC, outside)
    return d / 'package_placeholder' / '..' / 'outside' / 'pkg'


def main():
    if CASES_ROOT.exists():
        shutil.rmtree(CASES_ROOT)
    CASES_ROOT.mkdir(parents=True)
    results = []
    healthy = case('00_healthy_control')
    results.append(healthy)
    table = [
        ('01_root_missing', None, t_missing),
        ('02_unspecified', None, t_unspecified),
        ('03_rc0_junit_failure', m_rc0_junit_failure, None),
        ('04_junit_green_business_rc', m_business_rc, None),
        ('05_entry_rc', m_entry_rc, None),
        ('06_junit_empty', m_junit_empty, None),
        ('07_test_file_entry_deleted', m_delete_test_file_entry, None),
        ('08_unregistered_test_file', m_add_unregistered_test_file, None),
        ('09_stdout_appended', m_stdout_appended, None),
        ('10_junit_equal_length_tamper', m_junit_equal_length_tamper, None),
        ('11_manifest_resign', m_manifest_resign, None),
        ('12_source_lock_vs_deploy_differ', m_source_closure_mismatch, None),
        ('13_candidate_commit_missing', m_candidate_missing, None),
        ('14_candidate_drift', m_candidate_drift, None),
        ('15_symlink_to_healthy', None, t_symlink),
        ('16_dotdot_escape', None, t_dotdot),
        ('17_critical_test_skipped', m_critical_skipped, None),
        ('18_required_file_missing', m_required_missing, None),
        ('19_required_file_changed', m_required_changed, None),
    ]
    for name, mutate, override in table:
        results.append(case(name, mutate, override))
        print(results[-1])
    summary = {
        'healthy_control_rc': healthy['rc'],
        'healthy_control_rejected_expected_rc_nonzero... see rc.txt': True,
        'cases': results,
        'all_mutated_rejected': all(
            r['rc'] != 0 for r in results[1:]) and healthy['rc'] == 0,
        'healthy_package_unchanged_all_cases': all(
            r['healthy_unchanged'] for r in results),
    }
    (CASES_ROOT / 'summary.json').write_text(
        json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary['all_mutated_rejected'],
                     indent=2))
    print('healthy unchanged:', summary[
        'healthy_package_unchanged_all_cases'])
    return 0 if (summary['all_mutated_rejected'] and summary[
        'healthy_package_unchanged_all_cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
