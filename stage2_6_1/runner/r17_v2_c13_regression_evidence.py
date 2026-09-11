#!/usr/bin/env python3
"""完整回归证据包采集器 + fail-closed 校验器(R17 V2 C1/C3 治理 v2)。

B1/B4/F01-F12:preclaim gate 只能接受机器验证过、内容寻址、与当前
候选源码闭包一致的真实完整回归证据。本模块提供:

- ``collect``(CLI):把受监护全量回归(run 目录 + 顶层 entry 日志 +
  仓库/部署/解释器身份)组装为固定布局的证据包;只写调用方给定的
  工作目录,永不写生产 authority 根;
- ``verify_package``:只读、fail-closed 校验证据包(任务书 §5.2 的
  16 项事实),返回带命名错误键的 verdict — 每个负例都能到达预期
  校验层,不被无关前置错误挡住;
- ``build_synthetic_package``:pytest 临时目录用的合成健康包(显式
  synthetic;production 校验的域检查会拒绝它指向生产根)。

本模块不生成任何 episode、不训练、不写 claim;verify 全程只读。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

PACKAGE_FORMAT = 'R17V2C13FullRegressionEvidence-v1'

#: 证据包固定布局(§5.2-3 必需文件;全部必须是 regular file)。
REQUIRED_PACKAGE_FILES = (
    'manifest.json',
    'run_meta.json',
    'entry.rc',
    'entry.stdout.log',
    'entry.stderr.log',
    'business.rc',
    'business.stdout.log',
    'business.stderr.log',
    'junit.xml',
    'collected_tests.txt',
    'test_files.sha256',
    'required_files.json',
    'import_identity.json',
    'source_closure.json',
    'skips_allowlist.json',
    'critical_tests.json',
    'supervision/run_record.json',
    'supervision/summary.json',
)

#: supervisor run_record['required'] 角色 → 包内目标路径(采集映射)。
REQUIRED_ROLE_DESTINATION = {
    'junit_xml': 'junit.xml',
    'business_stdout': 'business.stdout.log',
    'business_stderr': 'business.stderr.log',
    'telemetry_guest': 'supervision/telemetry/guest_samples.jsonl',
    'telemetry_win': 'supervision/telemetry/win_samples.jsonl',
    'alerts': 'supervision/alerts/alerts.jsonl',
    'native_sampler_identity': 'supervision/native_sampler/identity.json',
    'native_sampler_terminal': 'supervision/native_sampler/terminal.json',
    'native_sampler_confirmation': (
        'supervision/native_sampler/native_confirmation.json'),
    'summary': 'supervision/summary.json',
}

#: run_record['required'] 里角色对应的 run 目录内来源(采集映射)。
ROLE_RUNDIR_SOURCE = {
    'junit_xml': 'junit.xml',
    'business_stdout': 'business/stdout.log',
    'business_stderr': 'business/stderr.log',
    'telemetry_guest': 'telemetry/guest_samples.jsonl',
    'telemetry_win': 'telemetry/win_samples.jsonl',
    'alerts': 'alerts/alerts.jsonl',
    'native_sampler_identity': 'native_sampler/identity.json',
    'native_sampler_terminal': 'native_sampler/terminal.json',
    'native_sampler_confirmation': 'native_sampler/native_confirmation.json',
    'summary': 'summary.json',
}


class EvidenceError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_meta(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {'size': len(data), 'sha256': _sha256_bytes(data)}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


# ------------------------------------------------------------------ digest
def package_content_index(root: Path) -> dict[str, dict[str, Any]]:
    """包内全部 regular 文件的 {rel: {size, sha256}}(manifest 含自身)。"""
    root = Path(root)
    index: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob('*')):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        index[rel] = _file_meta(path)
    return index


def package_digest(root: Path) -> str:
    """内容寻址包 digest(canonical 全文件索引的 sha256)。

    外层 manifest 重签(F10)改变 manifest 字节 → digest 改变;receipt/
    claim 锚定的 package_sha256 即此值,重签无法救回内层篡改。
    """
    return _sha256_bytes(_canonical(package_content_index(root)).encode())


# ------------------------------------------------------------------ verify
def _lstat_not_symlink(path: Path, errors: list, key: str,
                       label: str) -> bool:
    try:
        st = os.lstat(path)
    except OSError as exc:
        errors.append((key, f'{label}: lstat failed: {exc}'))
        return False
    if stat.S_ISLNK(st.st_mode):
        errors.append((key, f'{label}: symlink component rejected: {path}'))
        return False
    return True


def _parse_junit(path: Path):
    """返回 (totals, cases):cases = [{id, classname, name, skipped}]。"""
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    totals = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    cases: list[dict[str, str]] = []
    for suite in root.iter('testsuite'):
        for key in totals:
            totals[key] += int(suite.get(key) or 0)
        for case in suite.iter('testcase'):
            skipped = case.find('skipped') is not None
            cases.append({
                'id': f"{case.get('classname', '')}::{case.get('name', '')}",
                'classname': case.get('classname', ''),
                'name': case.get('name', ''),
                'skipped': skipped})
    return totals, cases


def _collected_ids(path: Path) -> list[str]:
    ids: list[str] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line.endswith('tests collected') or line.endswith('test collected'):
            continue
        if '::' in line:
            ids.append(line)
    return ids


def _business_summary_counts(stdout_text: str) -> tuple[int, int] | None:
    """business stdout 末尾 pytest 摘要 'N passed, M skipped' 解析。"""
    m = re.findall(r'(\d+) passed(?:, (\d+) skipped)?', stdout_text)
    if not m:
        return None
    passed, skipped = m[-1]
    return int(passed), int(skipped or 0)


def _recompute_members(release_repo: Path, deploy_root: Path,
                       members: dict[str, str]) -> dict[str, dict[str, Any]]:
    """在发布库与部署树分别复算成员字节(§6.2 双树复算)。"""
    out: dict[str, dict[str, Any]] = {}
    for module, sha in members.items():
        entry: dict[str, Any] = {}
        if module.startswith('rl_curriculum.'):
            rel = 'stage2_6_1/src/' + module.replace('.', '/') + '.py'
            deploy_rel = 'src/' + module.replace('.', '/') + '.py'
        else:
            rel = f'stage2_6_1/runner/{module}.py'
            deploy_rel = f'stage2_6_1_runner/{module}.py'
        for label, base, sub in (('release', release_repo, rel),
                                 ('deploy', deploy_root, deploy_rel)):
            p = Path(base) / sub
            entry[label] = ({'path': str(p),
                             'sha256': _file_meta(p)['sha256']}
                            if p.is_file() else {'path': str(p),
                                                 'missing': True})
        entry['recorded_sha256'] = sha
        out[module] = entry
    return out


def verify_package(root: Path, *, authority: Any = None,
                   current_sources: dict[str, Any] | None = None,
                   checks: str = 'full',
                   release_repo: Path | None = None,
                   deploy_root: Path | None = None
                   ) -> dict[str, Any]:
    """只读校验完整回归证据包;返回 {ok, errors:[(key,msg)], checks}。

    ``checks='full'`` 跑全部 16 项事实(含 git/双树/部署 import 复算);
    ``'structural'`` 只跑包内自洽 + 与 current_sources 的候选闭包对比
    (合成链在临时 authority 上使用)。所有层独立评估并汇总错误,负例
    不会被无关前置错误挡住(§5.4)。
    """
    root = Path(root)
    errors: list[tuple[str, str]] = []
    flags: dict[str, bool] = {}

    def fail(key: str, message: str) -> None:
        errors.append((key, message))

    # ---- 1/2 根存在、允许域、路径无逃逸、组件无符号链接
    if not root.is_dir():
        fail('package_root_missing', f'evidence root missing: {root}')
        return {'ok': False, 'format': PACKAGE_FORMAT, 'errors': errors,
                'checks': {'package_root_missing': True},
                'package_sha256': None}
    if authority is not None:
        repo_root = Path(authority.repo_root).resolve(strict=True)
        resolved = root.resolve(strict=True)
        if not (resolved == repo_root or resolved.is_relative_to(repo_root)):
            fail('domain_escape',
                 f'evidence root outside the allowed authority domain: '
                 f'{root} not under {repo_root}')
        # 逐组件拒绝符号链接:对原始词法路径(abspath 仅折叠 ..,不解析
        # symlink)从文件系统根 lstat — 健康 symlink 也拒绝(F02)。
        _lstat_not_symlink(repo_root, errors, 'symlink_root', 'root')
        lexical = Path(os.path.abspath(str(root)))
        probe = Path(lexical.anchor)
        for part in lexical.parts[1:]:
            probe = probe / part
            _lstat_not_symlink(probe, errors, 'symlink_component',
                               'component')
    else:
        # 无 authority 时仍对包根做 lstat 拒绝(相对/符号链接根)。
        _lstat_not_symlink(root, errors, 'symlink_root', 'root')
    # 包内文件全部 regular(拒绝 symlink/设备/FIFO;§5.2-3)。
    for path in sorted(root.rglob('*')):
        if path.is_dir():
            continue
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            fail('non_regular_file',
                 f'package member is not a regular file: {path}')

    # ---- 3 必需文件
    for rel in REQUIRED_PACKAGE_FILES:
        if not (root / rel).is_file():
            fail('missing_required_file', f'required file missing: {rel}')

    # 包内容索引 + manifest 对拍(等长篡改/追加/未登记文件全部在此层)
    index = package_content_index(root)
    manifest = None
    mf_path = root / 'manifest.json'
    if mf_path.is_file():
        try:
            manifest = json.loads(mf_path.read_text(encoding='utf-8'))
        except ValueError as exc:
            fail('manifest_malformed', f'manifest.json unparsable: {exc}')
        if isinstance(manifest, dict) and isinstance(
                manifest.get('files'), dict):
            recorded = manifest['files']
            for rel, meta in sorted(recorded.items()):
                actual = index.get(rel)
                if actual is None:
                    fail('manifest_mismatch',
                         f'manifest entry has no package file: {rel}')
                elif actual != {'size': meta.get('size'),
                                'sha256': meta.get('sha256')}:
                    fail('manifest_mismatch',
                         f'package file bytes differ from manifest: {rel}')
            for rel in sorted(index):
                if rel != 'manifest.json' and rel not in recorded:
                    fail('unmanifested_file',
                         f'package file absent from manifest: {rel}')
        else:
            fail('manifest_malformed', 'manifest.json missing files map')

    def read_json(rel: str) -> Any:
        p = root / rel
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except ValueError:
            return None

    run_meta = read_json('run_meta.json')
    # ---- 4 命令/argv/cwd/env 身份完整
    if not isinstance(run_meta, dict):
        fail('run_meta_incomplete', 'run_meta.json missing/unparsable')
    else:
        argv = run_meta.get('argv')
        ok_identity = (
            isinstance(argv, list) and argv
            and all(isinstance(a, str) for a in argv)
            and isinstance(run_meta.get('cwd'), str)
            and str(run_meta.get('cwd', '')).startswith('/')
            and isinstance(run_meta.get('env'), dict)
            and run_meta.get('env'))
        if not ok_identity:
            fail('run_meta_incomplete',
                 f'run_meta missing command/argv/cwd/env identity: '
                 f'{sorted(run_meta) if isinstance(run_meta, dict) else run_meta}')

    # ---- 5 rc 与 supervisor/finalized 一致性
    def rc_value(rel: str) -> str | None:
        p = root / rel
        return p.read_text(encoding='utf-8').strip() if p.is_file() else None

    entry_rc = rc_value('entry.rc')
    business_rc = rc_value('business.rc')
    if entry_rc is None or not entry_rc.lstrip('-').isdigit():
        fail('entry_rc_nonzero', f'entry rc missing/malformed: {entry_rc!r}')
    elif int(entry_rc) != 0:
        fail('entry_rc_nonzero', f'entry rc != 0: {entry_rc}')
    if business_rc is None or not business_rc.lstrip('-').isdigit():
        fail('business_rc_nonzero',
             f'business rc missing/malformed: {business_rc!r}')
    elif int(business_rc) != 0:
        fail('business_rc_nonzero', f'business rc != 0: {business_rc}')
    run_record = read_json('supervision/run_record.json')
    if not isinstance(run_record, dict):
        fail('supervision_not_finalized',
             'supervision run_record.json missing/unparsable')
    else:
        if run_record.get('finalized') is not True:
            fail('supervision_not_finalized',
                 f'supervisor not finalized: {run_record.get("finalized")}')
        sup_rc = (run_record.get('business') or {}).get('rc')
        if business_rc is not None and sup_rc is not None \
                and int(sup_rc) != int(business_rc):
            fail('supervision_rc_mismatch',
                 f'supervisor business rc {sup_rc} != package business rc '
                 f'{business_rc}')
        if isinstance(argv := run_record.get('argv'), list) and \
                isinstance(run_meta, dict):
            if list(run_meta.get('argv') or []) != list(argv):
                fail('supervision_rc_mismatch',
                     'run_meta argv differs from supervisor run_record argv')

    # ---- 7 JUnit
    junit_path = root / 'junit.xml'
    totals: dict[str, int] = {}
    cases: list[dict[str, str]] = []
    if junit_path.is_file():
        try:
            totals, cases = _parse_junit(junit_path)
        except Exception as exc:  # noqa: BLE001 - 任一解析错误都归此层
            fail('junit_malformed', f'junit.xml unparsable: {exc}')
            totals = {}
        if totals:
            if totals['tests'] <= 0:
                fail('junit_empty', 'junit reports zero tests')
            if totals['failures'] != 0:
                fail('junit_failures_nonzero',
                     f'junit failures={totals["failures"]}')
            if totals['errors'] != 0:
                fail('junit_errors_nonzero',
                     f'junit errors={totals["errors"]}')

    # ---- 8 collected/pass/skip 计数一致
    collected = (_collected_ids(root / 'collected_tests.txt')
                 if (root / 'collected_tests.txt').is_file() else None)
    if collected is not None and totals:
        if len(collected) != totals['tests']:
            fail('collected_count_mismatch',
                 f'collected ids={len(collected)} != junit tests='
                 f'{totals["tests"]}')
        executed = (totals['tests'])
        accounted = sum(totals[k] for k in
                        ('failures', 'errors', 'skipped'))
        # pytest: tests = pass + fail + error + skip → pass = tests - 其他
        if executed < accounted:
            fail('junit_count_inconsistent',
                 f'junit accounting inconsistent: tests={executed} < '
                 f'fail+err+skip={accounted}')
    business_stdout = ((root / 'business.stdout.log').read_text(
        encoding='utf-8', errors='replace')
        if (root / 'business.stdout.log').is_file() else '')
    summary = _business_summary_counts(business_stdout)
    if summary is not None and totals:
        passed, skipped = summary
        if passed + skipped != totals['tests']:
            fail('stdout_summary_mismatch',
                 f'business stdout summary {passed} passed + {skipped} '
                 f'skipped != junit tests {totals["tests"]}')

    # ---- 9 critical tests 不得 skip/xfail
    critical = read_json('critical_tests.json')
    if isinstance(critical, dict) and isinstance(
            critical.get('critical_test_files'), list):
        for stem in critical['critical_test_files']:
            if not isinstance(stem, str) or not stem:
                fail('critical_module_absent', f'malformed stem: {stem!r}')
                continue
            mod_cases = [c for c in cases
                         if stem in (c['classname'] or '')
                         or stem in (c['id'] or '')]
            if not mod_cases:
                fail('critical_module_absent',
                     f'critical test module produced no junit cases: '
                     f'{stem}')
            for c in mod_cases:
                if c['skipped']:
                    fail('critical_test_skipped',
                         f'critical test skipped/xfail: {c["id"]}')

    # ---- 10 历史 skip 逐 id allowlist
    allowlist = read_json('skips_allowlist.json')
    if not (isinstance(allowlist, dict)
            and isinstance(allowlist.get('allowed_skips'), list)
            and all(isinstance(s, str) for s in
                    allowlist['allowed_skips'])):
        fail('allowlist_malformed',
             'skips_allowlist.json must enumerate concrete test ids')
    else:
        allowed = set(allowlist['allowed_skips'])
        for c in cases:
            if c['skipped'] and c['id'] not in allowed:
                fail('unexpected_skip', f'unlisted skipped test: {c["id"]}')

    # ---- 11 测试文件集合与 SHA(记录完整性;live 模式重算对拍)
    tf_path = root / 'test_files.sha256'
    recorded_tests: dict[str, str] = {}
    if tf_path.is_file():
        for line in tf_path.read_text(encoding='utf-8').splitlines():
            m = re.fullmatch(r'([0-9a-f]{64})  (\S.*)', line.strip())
            if not m:
                fail('test_manifest_malformed',
                     f'test_files.sha256 line malformed: {line[:120]!r}')
                continue
            recorded_tests[m.group(2)] = m.group(1)
        if not recorded_tests:
            fail('test_manifest_empty',
                 'test_files.sha256 records no test files')
    else:
        fail('test_manifest_malformed', 'test_files.sha256 missing')
    if checks == 'full' and isinstance(run_meta, dict):
        deploy_root = (Path(deploy_root) if deploy_root is not None
                       else Path(run_meta.get('deploy_root', '')))
        release_repo = (Path(release_repo) if release_repo is not None
                        else Path(run_meta.get('release_repo', '')))
        # 记录路径为部署相对(tests/route_c_stage2_6_1/...);发布库同
        # 文件在 stage2_6_1/ 之下。任一存在即重算对拍;两边都缺即失败。
        for rel, sha in sorted(recorded_tests.items()):
            candidates = [deploy_root / rel,
                          release_repo / 'stage2_6_1' / rel]
            found = [p for p in candidates if p.is_file()]
            if not found:
                fail('test_file_hash_mismatch',
                     f'recorded test file missing in both trees: {rel}')
                continue
            for p in found:
                if _sha256_bytes(p.read_bytes()) != sha:
                    fail('test_file_hash_mismatch',
                         f'test file bytes differ from recorded manifest: '
                         f'{p}')
        # 集合相等:部署树 tests 目录实际文件 == 记录集合。
        tests_dir = deploy_root / 'tests' / 'route_c_stage2_6_1'
        if tests_dir.is_dir():
            live_files = {f'tests/route_c_stage2_6_1/{p.name}'
                          for p in tests_dir.glob('test_*.py')}
            if live_files != set(recorded_tests):
                only_live = sorted(live_files - set(recorded_tests))
                only_rec = sorted(set(recorded_tests) - live_files)
                fail('test_file_set_changed',
                     f'test file set changed: unregistered={only_live[:5]} '
                     f'missing={only_rec[:5]}')

    # ---- 13 import identity(记录完整性;live 重算)
    import_identity = read_json('import_identity.json')
    if not (isinstance(import_identity, dict)
            and import_identity.get('deploy')
            and import_identity.get('release')):
        fail('import_identity_mismatch',
             'import_identity.json missing release/deploy identities')
    elif checks == 'full':
        for side in ('release', 'deploy'):
            for module, meta in sorted(
                    (import_identity.get(side) or {}).items()):
                if not isinstance(meta, dict):
                    continue
                p = Path(meta.get('file', ''))
                if p.is_file():
                    actual = _sha256_bytes(p.read_bytes())
                    if actual != meta.get('sha256'):
                        fail('import_identity_mismatch',
                             f'{side} import identity drift: {p}')

    # ---- 14 source closure(治理 lock 成员逐项;候选一致性)
    closure = read_json('source_closure.json')
    closure_members: dict[str, str] = {}
    if not (isinstance(closure, dict)
            and isinstance(closure.get('members'), dict)):
        fail('closure_digest_mismatch',
             'source_closure.json missing members map')
    else:
        closure_members = {
            m: s for m, s in closure['members'].items()
            if isinstance(m, str) and isinstance(s, str)}
        recorded_digest = closure.get('members_digest')
        computed = _sha256_bytes(
            _canonical(closure['members']).encode('utf-8'))
        if recorded_digest != computed:
            fail('closure_digest_mismatch',
                 f'closure members digest mismatch: {recorded_digest} != '
                 f'{computed}')
        if current_sources is not None:
            live_flat = {m: v['sha256']
                         for m, v in current_sources.items()}
            if live_flat != closure['members']:
                fail('source_closure_mismatch',
                     'regression candidate source closure differs from '
                     'the current imported closure (stale or foreign '
                     'candidate regression)')
        if checks == 'full':
            lock_meta = closure.get('governance_lock_file') or {}
            release_repo = (Path(release_repo) if release_repo is not None
                            else Path(run_meta.get('release_repo', ''))
                            ) if isinstance(run_meta, dict) else None
            if release_repo:
                lock_path = release_repo / 'stage2_6_1' / 'runner' / (
                    'r17_v2_c13_governance_source_lock.py')
                if lock_path.is_file():
                    actual = _sha256_bytes(lock_path.read_bytes())
                    if actual != lock_meta.get('sha256'):
                        fail('governance_lock_drift',
                             'governance lock file bytes differ from the '
                             'recorded closure anchor')
                else:
                    fail('governance_lock_drift',
                         f'governance lock file missing: {lock_path}')
            if isinstance(run_meta, dict) and run_meta.get('deploy_root'):
                deploy_root = (Path(deploy_root) if deploy_root is not None
                               else Path(run_meta['deploy_root']))
                recomputed = _recompute_members(
                    release_repo or Path(run_meta.get('release_repo', '')),
                    deploy_root, closure['members'])
                for module, entry in sorted(recomputed.items()):
                    for side in ('release', 'deploy'):
                        got = entry[side].get('sha256')
                        if got is None or got != entry['recorded_sha256']:
                            fail('closure_member_mismatch',
                                 f'{side} member bytes differ from lock: '
                                 f'{module} at {entry[side].get("path")}')

    # ---- 12 候选 commit(full:git 对象、运行时 clean、无候选后漂移)
    if isinstance(run_meta, dict):
        cand = run_meta.get('candidate_commit', '')
        if not (isinstance(cand, str)
                and re.fullmatch(r'[0-9a-f]{40}', cand) is not None):
            fail('candidate_commit_malformed',
                 f'candidate commit malformed: {cand!r}')
        elif checks == 'full':
            import subprocess

            repo = (Path(release_repo) if release_repo is not None
                    else Path(run_meta.get('release_repo', '')))
            if not repo.is_dir():
                fail('candidate_commit_missing',
                     f'release repo not available for git checks: {repo}')
            else:

                def git(*args: str) -> tuple[int, str]:
                    proc = subprocess.run(
                        ['git', '-C', str(repo), *args],
                        capture_output=True, text=True, timeout=120)
                    return proc.returncode, (proc.stdout + proc.stderr).strip()

                rc, _ = git('cat-file', '-e', f'{cand}^{{commit}}')
                if rc != 0:
                    fail('candidate_commit_missing',
                         f'candidate commit object missing in git: {cand}')
                else:
                    paths = ['stage2_6_1/runner', 'stage2_6_1/src',
                             'stage2_6_1/tests']
                    rc, out = git('diff', '--name-only', f'{cand}..HEAD',
                                  '--', *paths)
                    if rc == 0 and out:
                        fail('candidate_drift',
                             f'runner/src/tests drifted after the '
                             f'regression candidate: {out.splitlines()[:5]}')
                    rc, out = git('status', '--porcelain=v1', '--', *paths)
                    if rc == 0 and out:
                        fail('worktree_not_clean',
                             f'regression candidate worktree not clean '
                             f'for runner/src/tests: {out.splitlines()[:5]}')
                    rc, head = git('rev-parse', 'HEAD')
                    if run_meta.get('git_head_at_collect') \
                            and rc == 0 \
                            and run_meta['git_head_at_collect'] != head:
                        fail('candidate_drift',
                             'collect-time HEAD differs from current HEAD')

    # ---- 15 required/native 文件实际 size/SHA
    required = read_json('required_files.json')
    if not (isinstance(required, dict)
            and isinstance(required.get('entries'), list)):
        fail('required_file_mismatch',
             'required_files.json missing entries list')
    else:
        for entry in required['entries']:
            if not (isinstance(entry, dict) and entry.get('role')
                    and entry.get('path')):
                fail('required_file_mismatch',
                     f'malformed required entry: {entry!r}')
                continue
            p = root / entry['path']
            if not p.is_file():
                fail('required_file_mismatch',
                     f'required file missing: {entry["role"]} -> '
                     f'{entry["path"]}')
                continue
            meta = _file_meta(p)
            if meta['sha256'] != entry.get('sha256') \
                    or meta['size'] != entry.get('size'):
                fail('required_file_mismatch',
                     f'required file bytes differ: {entry["role"]} -> '
                     f'{entry["path"]}')
        if isinstance(run_record, dict):
            by_role = {e.get('role'): e for e in required['entries']
                       if isinstance(e, dict)}
            for rr in run_record.get('required', []):
                role = rr.get('role')
                sup_sha = rr.get('sha256')
                if role in by_role and sup_sha \
                        and by_role[role].get('sha256') != sup_sha:
                    fail('required_role_sha_mismatch',
                         f'supervisor-recorded sha for role {role} '
                         f'differs from the package copy')

    flags['layers_evaluated'] = True
    return {
        'ok': not errors,
        'format': PACKAGE_FORMAT,
        'errors': errors,
        'checks': flags,
        'package_sha256': package_digest(root),
        'summary': {
            'entry_rc': (int(entry_rc)
                         if entry_rc is not None
                         and entry_rc.lstrip('-').isdigit() else entry_rc),
            'business_rc': (int(business_rc)
                            if business_rc is not None
                            and business_rc.lstrip('-').isdigit()
                            else business_rc),
            'junit': totals, 'n_collected': (len(collected)
                                             if collected is not None
                                             else None),
            'n_critical_files': (
                len(critical['critical_test_files'])
                if isinstance(critical, dict)
                and isinstance(critical.get('critical_test_files'), list)
                else None),
            'n_allowed_skips': (
                len(allowlist['allowed_skips'])
                if isinstance(allowlist, dict)
                and isinstance(allowlist.get('allowed_skips'), list)
                else None),
        },
    }


# ------------------------------------------------------------------ collect
def collect_package(*, run_dir: Path, out_dir: Path,
                    entry_stdout: Path, entry_stderr: Path, entry_rc: Path,
                    candidate_commit: str, release_repo: Path,
                    deploy_root: Path, collected: Path,
                    test_files: Path, skips_allowlist: Path,
                    critical_test_files: list[str]) -> dict[str, Any]:
    """把受监护全量回归组装为证据包(只写 out_dir;永不写生产根)。"""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    release_repo, deploy_root = Path(release_repo), Path(deploy_root)
    if out_dir.exists():
        raise EvidenceError(f'output package dir already exists: {out_dir}')
    out_dir.mkdir(parents=True)

    def copy_to(src: Path, rel: str) -> dict[str, Any]:
        src = Path(src)
        if not src.is_file():
            raise EvidenceError(f'source artifact missing: {src}')
        dst = out_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        data = src.read_bytes()
        dst.write_bytes(data)
        return {'role': None, 'path': rel,
                'sha256': _sha256_bytes(data), 'size': len(data)}

    run_record = json.loads(
        (run_dir / 'run_record.json').read_text(encoding='utf-8'))
    required_entries: list[dict[str, Any]] = []
    sup_by_role = {r.get('role'): r for r in run_record.get('required', [])}
    for role, dest in REQUIRED_ROLE_DESTINATION.items():
        src = run_dir / ROLE_RUNDIR_SOURCE[role]
        entry = copy_to(src, dest)
        sup = sup_by_role.get(role) or {}
        if sup.get('sha256') and entry['sha256'] != sup['sha256']:
            raise EvidenceError(
                f'collected artifact sha differs from supervisor record '
                f'for role {role}: {entry["sha256"]} != {sup["sha256"]}')
        entry['role'] = role
        required_entries.append(entry)
    rr_entry = copy_to(run_dir / 'run_record.json',
                       'supervision/run_record.json')
    rr_entry['role'] = 'run_record'
    required_entries.append(rr_entry)

    for src, rel in ((entry_stdout, 'entry.stdout.log'),
                     (entry_stderr, 'entry.stderr.log')):
        copy_to(src, rel)
    (out_dir / 'entry.rc').write_text(
        Path(entry_rc).read_text(encoding='utf-8').strip() + '\n',
        encoding='utf-8')
    (out_dir / 'business.rc').write_text(
        f"{(run_record.get('business') or {}).get('rc')}\n",
        encoding='utf-8')
    copy_to(collected, 'collected_tests.txt')
    copy_to(test_files, 'test_files.sha256')
    copy_to(skips_allowlist, 'skips_allowlist.json')

    # import 身份与治理 source closure(在当前进程/两棵树复算)。
    import sys

    sys.path.insert(0, str(release_repo / 'stage2_6_1' / 'runner'))
    sys.path.insert(0, str(deploy_root / 'stage2_6_1_runner'))
    sys.path.insert(0, str(deploy_root / 'src'))
    from r17_v2_c13_governance_source_lock import (  # noqa: E402
        SOURCE_SHA256,
    )

    import_identity: dict[str, Any] = {'release': {}, 'deploy': {}}
    for module in SOURCE_SHA256:
        for side, base, sub in (
                ('release', release_repo,
                 'stage2_6_1/runner' if not module.startswith('rl_')
                 else 'stage2_6_1/src/rl_curriculum'),
                ('deploy', deploy_root,
                 'stage2_6_1_runner' if not module.startswith('rl_')
                 else 'src/rl_curriculum')):
            leaf = (f'{module}.py' if not module.startswith('rl_')
                    else module.split('.')[-1] + '.py')
            p = base / sub / leaf
            import_identity[side][module] = {
                'file': str(p),
                'sha256': (_sha256_bytes(p.read_bytes())
                           if p.is_file() else None)}
    (out_dir / 'import_identity.json').write_text(
        json.dumps(import_identity, indent=2, sort_keys=True),
        encoding='utf-8')

    lock_path = release_repo / 'stage2_6_1' / 'runner' / (
        'r17_v2_c13_governance_source_lock.py')
    members_digest = _sha256_bytes(
        _canonical(dict(SOURCE_SHA256)).encode('utf-8'))
    closure = {
        'candidate_commit': candidate_commit,
        'governance_lock_file': {
            'path': str(lock_path),
            'sha256': _sha256_bytes(lock_path.read_bytes())},
        'members': dict(SOURCE_SHA256),
        'members_digest': members_digest,
    }
    (out_dir / 'source_closure.json').write_text(
        json.dumps(closure, indent=2, sort_keys=True), encoding='utf-8')
    (out_dir / 'critical_tests.json').write_text(
        json.dumps({'critical_test_files': list(critical_test_files)},
                   indent=2), encoding='utf-8')

    import subprocess

    def git(*args: str) -> str:
        proc = subprocess.run(['git', '-C', str(release_repo), *args],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            raise EvidenceError(
                f'git {args} failed: {proc.stderr.strip()[:300]}')
        return proc.stdout.strip()

    head = git('rev-parse', 'HEAD')
    if head != candidate_commit:
        raise EvidenceError(
            f'candidate commit {candidate_commit} != current HEAD {head}; '
            'collect must run on the frozen candidate worktree')
    status = git('status', '--porcelain=v1', '--', 'stage2_6_1/runner',
                 'stage2_6_1/src', 'stage2_6_1/tests')
    run_meta = {
        'format': PACKAGE_FORMAT,
        'task_kind': run_record.get('task_kind'),
        'run_id': run_record.get('run_id'),
        'candidate_commit': candidate_commit,
        'git_head_at_collect': head,
        'worktree_clean': not status,
        'argv': list(run_record.get('argv') or []),
        'cwd': str(deploy_root),
        'release_repo': str(release_repo),
        'deploy_root': str(deploy_root),
        'env': {
            'python': sys.version.split()[0],
            'executable': sys.executable,
            'r17_run_dir': os.environ.get('R17_RUN_DIR', ''),
        },
        'started_utc': run_record.get('started_utc'),
        'ended_utc': run_record.get('ended_utc'),
        'entry_command': 'r17_monitored_entry.sh ' + ' '.join(
            run_record.get('argv') or []),
    }
    (out_dir / 'run_meta.json').write_text(
        json.dumps(run_meta, indent=2, sort_keys=True), encoding='utf-8')

    # manifest 最后写(覆盖除自身外全部文件)。
    index = {rel: meta for rel, meta in package_content_index(out_dir).items()
             if rel != 'manifest.json'}
    (out_dir / 'manifest.json').write_text(
        json.dumps({'format': PACKAGE_FORMAT, 'files': index}, indent=2,
                   sort_keys=True), encoding='utf-8')
    return {'package_root': str(out_dir),
            'package_sha256': package_digest(out_dir),
            'required_roles': [e['role'] for e in required_entries]}


# ------------------------------------------------------------------ provenance
#: v2 主 run 实际执行闭包(§6.3/P04;字节不可用,永不重构/伪造)。
V2_MAIN_RUN_EXECUTION_CLOSURE = (
    '591b1f35606c6fa2e75fbbb36ab8c87529064c771c93c604038de11ef1c80f85')

#: 独立审查否决的上一轮治理候选(接手 HEAD 685d2c9 时的被覆盖 lock)。
PREVIOUS_GOVERNANCE_LOCK_SHA256 = (
    '86ffe739f2ff31e91832f4a33f640ac93f6603a12bb801d99f0ccd604c5d2662')


def build_source_provenance(release_repo: Path,
                            candidate_commit: str) -> dict[str, Any]:
    """§6.3 来源分层 provenance(只读;不得把事后闭包写成执行源码)。"""
    release_repo = Path(release_repo)
    lock_path = release_repo / 'stage2_6_1' / 'runner' / (
        'r17_v2_c13_governance_source_lock.py')
    lock_bytes = lock_path.read_bytes()
    from r17_v2_c13_governance_source_lock import (  # noqa: E402
        GOVERNANCE_ROLE, MEMBER_MODULES, SOURCE_SHA256,
    )

    members_digest = _sha256_bytes(
        _canonical(dict(SOURCE_SHA256)).encode('utf-8'))
    # 归档 v2 主 run 的 plan.json 仍记录执行闭包 digest(只读核对)。
    archived_plan = release_repo / (
        'stage2_6_1/artifacts/repair17/development/'
        'v2_c13_engineering_v2_delivery/main_run/monitored_run/'
        'v2_c13_engineering_v2/plan.json')
    archived_witness = None
    if archived_plan.is_file():
        text = archived_plan.read_text(encoding='utf-8')
        archived_witness = V2_MAIN_RUN_EXECUTION_CLOSURE in text
    return {
        'format': 'R17V2C13SourceProvenance-v2',
        'closures': {
            'v2_main_run_execution': {
                'sha256': V2_MAIN_RUN_EXECUTION_CLOSURE,
                'role': 'v2 主 run(2026-09-11 00:51-00:56 UTC)实际执行'
                        '的 pipeline 字节;source bytes unavailable',
                'bytes_available': False,
                'archived_plan_witness': archived_witness,
                'usable_for_future_preclaim': False,
            },
            'previous_post_run_reader': {
                'pipeline_sha256': (
                    '93f2d59af8b1279f9bd5f7faf0102ca2f75a8a570a6aa85fe'
                    '4d4339d213985d7'),
                'role': 'v2 轮主 run 后 cold reader 闭包;不是执行字节'
                        '(上一轮 provenance_dual_closure.json 承载)',
                'bytes_available': True,
                'usable_for_future_preclaim': False,
            },
            'previous_governance_candidate_rejected': {
                'source_lock_file_sha256': PREVIOUS_GOVERNANCE_LOCK_SHA256,
                'role': '接手 HEAD 685d2c9 时被原地重签的治理 lock;'
                        '独立审查五项 blocker 否决,本轮恢复历史字节并'
                        '另建治理闭包',
                'bytes_available': True,
                'usable_for_future_preclaim': False,
            },
            'current_candidate_governance': {
                'candidate_commit': candidate_commit,
                'governance_lock_file_sha256': _sha256_bytes(lock_bytes),
                'members_digest': members_digest,
                'members': dict(SOURCE_SHA256),
                'role': GOVERNANCE_ROLE,
                'member_count': len(MEMBER_MODULES),
                'bytes_available': True,
                'usable_for_future_preclaim': True,
            },
            'evidence_only_commit': {
                'role': '证据提交 E:只新增证据目录/checksum/.gitattributes;'
                        'runner/src/tests 冻结,无源码变化',
                'bytes_available': True,
                'usable_for_future_preclaim': False,
            },
        },
    }


# --------------------------------------------------- synthetic (pytest-only)
def build_synthetic_package(root: Path, *, current_sources: dict[str, Any],
                            candidate_commit: str = '0' * 40,
                            n_tests: int = 3) -> dict[str, Any]:
    """pytest 临时目录合成健康包(显式 synthetic;域校验拒生产根)。

    用于合成链协议测试与校验器单元测试;产物永远位于 tmp,production
    verifier 的允许域检查拒绝其冒充生产证据。
    """
    import shutil
    import tempfile

    tmp_base = Path(tempfile.gettempdir())
    root = Path(root)
    require_synthetic = root.resolve(strict=False).is_relative_to(tmp_base)
    if not require_synthetic:
        raise EvidenceError(
            f'synthetic package must live under the system temp dir: '
            f'{root}')
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    members = {m: v['sha256'] for m, v in current_sources.items()}
    cases = ''.join(
        f'<testcase classname="tests.route_c_stage2_6_1.test_synth" '
        f'name="test_synth_{i}" time="0.001"/>' for i in range(n_tests))
    junit = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites><testsuite name="route_c_stage2_6_1" '
        f'tests="{n_tests}" failures="0" errors="0" skipped="0">'
        f'{cases}</testsuite></testsuites>')
    (root / 'junit.xml').write_text(junit, encoding='utf-8')
    ids = [f'tests/route_c_stage2_6_1/test_synth.py::test_synth_{i}'
           for i in range(n_tests)]
    (root / 'collected_tests.txt').write_text(
        '\n'.join(ids) + f'\n{n_tests} tests collected\n', encoding='utf-8')
    (root / 'entry.rc').write_text('0\n', encoding='utf-8')
    (root / 'business.rc').write_text('0\n', encoding='utf-8')
    (root / 'entry.stdout.log').write_text('entry ok\n', encoding='utf-8')
    (root / 'entry.stderr.log').write_text('', encoding='utf-8')
    (root / 'business.stdout.log').write_text(
        f'{n_tests} passed in 0.01s\n', encoding='utf-8')
    (root / 'business.stderr.log').write_text('', encoding='utf-8')
    (root / 'test_files.sha256').write_text(
        _sha256_bytes(b'synthetic') + '  tests/route_c_stage2_6_1/'
        'test_synth.py\n', encoding='utf-8')
    (root / 'skips_allowlist.json').write_text(
        '{"allowed_skips": []}', encoding='utf-8')
    (root / 'critical_tests.json').write_text(
        '{"critical_test_files": ["test_synth"]}', encoding='utf-8')
    run_record = {
        'run_id': 'synthetic-chain', 'task_kind': 'pytest',
        'finalized': True,
        'argv': ['python', '-m', 'pytest', '-q',
                 'tests/route_c_stage2_6_1'],
        'business': {'rc': 0, 'signal': None},
        'required': [
            {'role': 'junit_xml', 'path': 'runs/s/junit.xml',
             'status': 'present',
             'sha256': _sha256_bytes(junit.encode('utf-8'))},
            {'role': 'business_stdout', 'path': 'runs/s/b.out',
             'status': 'present', 'sha256': _sha256_bytes(
                 f'{n_tests} passed in 0.01s\n'.encode('utf-8'))},
        ],
        'started_utc': '2026-09-11T00:00:00Z',
        'ended_utc': '2026-09-11T00:00:01Z'}
    (root / 'supervision').mkdir()
    (root / 'supervision/run_record.json').write_text(
        json.dumps(run_record, indent=2), encoding='utf-8')
    (root / 'supervision/summary.json').write_text(
        json.dumps({'run_id': 'synthetic-chain', 'schema':
                    'r17-supervision-summary-v1'}), encoding='utf-8')
    required_entries = [
        {'role': 'junit_xml', 'path': 'junit.xml',
         'sha256': _sha256_bytes(junit.encode('utf-8')),
         'size': len(junit.encode('utf-8'))},
        {'role': 'business_stdout', 'path': 'business.stdout.log',
         'sha256': _sha256_bytes(
             f'{n_tests} passed in 0.01s\n'.encode('utf-8')),
         'size': len(f'{n_tests} passed in 0.01s\n'.encode('utf-8'))},
        {'role': 'run_record', 'path': 'supervision/run_record.json',
         'sha256': _file_meta(root / 'supervision/run_record.json')['sha256'],
         'size': _file_meta(root / 'supervision/run_record.json')['size']},
    ]
    (root / 'required_files.json').write_text(
        json.dumps({'entries': required_entries}, indent=2),
        encoding='utf-8')
    (root / 'import_identity.json').write_text(
        json.dumps({'release': {'synthetic-package': {
            'file': str(root / 'junit.xml'), 'sha256': _sha256_bytes(
                junit.encode('utf-8'))}},
            'deploy': {'synthetic-package': {
                'file': str(root / 'junit.xml'), 'sha256': _sha256_bytes(
                    junit.encode('utf-8'))}}}, indent=2),
        encoding='utf-8')
    closure = {
        'candidate_commit': candidate_commit,
        'governance_lock_file': {'path': 'synthetic', 'sha256':
                                 _sha256_bytes(b'synthetic')},
        'members': members,
        'members_digest': _sha256_bytes(_canonical(members).encode('utf-8')),
    }
    (root / 'source_closure.json').write_text(
        json.dumps(closure, indent=2, sort_keys=True), encoding='utf-8')
    (root / 'run_meta.json').write_text(
        json.dumps({
            'format': PACKAGE_FORMAT, 'task_kind': 'pytest',
            'run_id': 'synthetic-chain', 'candidate_commit':
            candidate_commit, 'git_head_at_collect': candidate_commit,
            'worktree_clean': True,
            'argv': list(run_record['argv']), 'cwd': '/tmp',
            'release_repo': str(root), 'deploy_root': str(root),
            'env': {'python': 'synthetic'},
            'started_utc': run_record['started_utc'],
            'ended_utc': run_record['ended_utc'],
            'entry_command': 'synthetic'}, indent=2, sort_keys=True),
        encoding='utf-8')
    index = {rel: meta for rel, meta in package_content_index(root).items()
             if rel != 'manifest.json'}
    (root / 'manifest.json').write_text(
        json.dumps({'format': PACKAGE_FORMAT, 'files': index}, indent=2,
                   sort_keys=True), encoding='utf-8')
    return {'package_root': str(root),
            'package_sha256': package_digest(root)}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    pc = sub.add_parser('collect', help='assemble an evidence package '
                        '(writes only the given out dir)')
    pc.add_argument('--run-dir', type=Path, required=True)
    pc.add_argument('--out', type=Path, required=True)
    pc.add_argument('--entry-stdout', type=Path, required=True)
    pc.add_argument('--entry-stderr', type=Path, required=True)
    pc.add_argument('--entry-rc', type=Path, required=True)
    pc.add_argument('--candidate-commit', required=True)
    pc.add_argument('--release-repo', type=Path, required=True)
    pc.add_argument('--deploy-root', type=Path, required=True)
    pc.add_argument('--collected', type=Path, required=True)
    pc.add_argument('--test-files', type=Path, required=True)
    pc.add_argument('--skips-allowlist', type=Path, required=True)
    pc.add_argument('--critical-tests', required=True,
                    help='comma-separated critical test module stems')
    pv = sub.add_parser('verify', help='read-only verification')
    pv.add_argument('--package', type=Path, required=True)
    pv.add_argument('--release-repo', type=Path)
    pv.add_argument('--deploy-root', type=Path)
    pv.add_argument('--structural', action='store_true',
                    help='skip live git/tree recomputation checks')
    args = ap.parse_args(argv)
    if args.command == 'collect':
        out = collect_package(
            run_dir=args.run_dir, out_dir=args.out,
            entry_stdout=args.entry_stdout, entry_stderr=args.entry_stderr,
            entry_rc=args.entry_rc, candidate_commit=args.candidate_commit,
            release_repo=args.release_repo, deploy_root=args.deploy_root,
            collected=args.collected, test_files=args.test_files,
            skips_allowlist=args.skips_allowlist,
            critical_test_files=[s.strip() for s in
                                 args.critical_tests.split(',') if s.strip()])
        print(_canonical(out))
        return 0
    verdict = verify_package(
        args.package, checks='structural' if args.structural else 'full',
        release_repo=args.release_repo, deploy_root=args.deploy_root)
    print(_canonical(verdict))
    return 0 if verdict['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
