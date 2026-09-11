#!/usr/bin/env python3
"""治理 lock 一次性再签工具(仅在候选冻结步骤运行;非运行时依赖)。

从当前部署导入面重建 ``r17_v2_c13_governance_source_lock.py`` 的
SOURCE_SHA256,并要求发布库与部署树的同名文件字节逐位一致后写回。
本工具不参与 source_guard/校验路径;再签结果随候选提交 C 冻结。
"""
from __future__ import annotations

import hashlib
import importlib
import re
import sys
from pathlib import Path

MEMBER_MODULES = (
    'r17_v2_c13_batch',
    'r17_v2_c13_pipeline',
    'r17_v2_c13_profile',
    'r17_v2_c13_regression_evidence',
    'rl_curriculum.curriculum261_pairs',
    'rl_curriculum.curriculum261_r17_c2_launch_prep',
    'rl_curriculum.curriculum261_r17_param_pack',
    'rl_curriculum.curriculum261_r6_design',
    'rl_curriculum.curriculum261_r6_param_pack',
)

_TEMPLATE = '''"""治理 source lock(R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2)。

角色声明(§6.2,不可改写):本文件锁定【本轮治理候选 C】的
preclaim/claim/reader 实际导入源码闭包 —— 它是事后治理与未来
preclaim 基础设施的闭包,**不是** 2026-09-10 v2 主 run 的实际执行
源码。v2 主 run 的执行闭包 591b1f35... 的源字节已不可用,由
``r17_v2_c13_source_lock.py`` 在提交 d3cdf3d1 的历史字节只读承载
(永不重签);任何事后 reader/verifier 闭包(含本文件)都不得被写成
旧主 run 的实际执行源码。

成员集固定:``MEMBER_MODULES`` 与 ``SOURCE_SHA256`` 的键集必须精确
相等(重复/缺失/额外成员一律拒绝);每个成员可在发布库与部署树
分别复算(见 r17_v2_c13_regression_evidence)。本文件不锁定自身
(无自指 hash),不混入 artifact、日志或时间戳。
"""
BASELINE = '685d2c9b9a5c2c812ae75b23e2050c5383b38e7b'
GOVERNANCE_ROLE = (
    'post-run governance / future preclaim closure; NOT the v2 main-run '
    'execution closure (bytes of 591b1f35... remain unavailable by '
    'design)')

MEMBER_MODULES = (
{members_block}
)

#: 成员 → 实际导入字节 SHA-256(由 r17_v2_c13_governance_relock.py
#: 在候选冻结时从部署导入面生成;生成后本文件随候选提交冻结)。
SOURCE_SHA256 = {{
{entries_block}
}}


def validate_member_set() -> None:
    """成员集合同一性:键集必须与 MEMBER_MODULES 精确相等。"""
    import hashlib
    import json

    lock_keys = set(SOURCE_SHA256)
    declared = set(MEMBER_MODULES)
    if lock_keys != declared or len(SOURCE_SHA256) != len(MEMBER_MODULES):
        raise RuntimeError(
            f'governance source lock member set mismatch: '
            f'extra={{sorted(lock_keys - declared)}} '
            f'missing={{sorted(declared - lock_keys)}}')
    import re

    for name, sha in SOURCE_SHA256.items():
        if re.fullmatch(r'[0-9a-f]{{64}}', sha) is None:
            raise RuntimeError(
                f'governance lock member not signed with a real sha256 '
                f'(PENDING-RELOCK or malformed): {{name}}')


def source_closure_digest() -> str:
    """成员映射的内容寻址 digest(与 regression evidence 同口径)。"""
    validate_member_set()
    import hashlib
    import json

    body = json.dumps(SOURCE_SHA256, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()
'''


def _member_paths(module: str) -> tuple[str, str]:
    """(发布库相对, 部署相对) 两树路径。"""
    if module.startswith('rl_curriculum.'):
        return (f'stage2_6_1/src/{module.replace(".", "/")}.py',
                f'src/{module.replace(".", "/")}.py')
    return f'stage2_6_1/runner/{module}.py', f'stage2_6_1_runner/{module}.py'


def main() -> int:
    import json

    release = Path('/mnt/f/trading/freqai-rl-audit')
    deploy = Path.home() / 'projects' / 'crypto_rl'
    sys.path.insert(0, str(deploy / 'stage2_6_1_runner'))
    sys.path.insert(0, str(deploy / 'src'))
    sys.path.insert(0, str(release / 'stage2_6_1' / 'runner'))

    entries: list[tuple[str, str]] = []
    for module in MEMBER_MODULES:
        imported = importlib.import_module(module)
        path = Path(imported.__file__).resolve(strict=True)
        data = path.read_bytes()
        deploy_sha = hashlib.sha256(data).hexdigest()
        rel_release, _rel_deploy = _member_paths(module)
        release_path = release / rel_release
        release_sha = (hashlib.sha256(release_path.read_bytes()).hexdigest()
                       if release_path.is_file() else None)
        if release_sha != deploy_sha:
            raise SystemExit(
                f'release/deploy bytes differ for {module}: '
                f'{release_path} ({release_sha}) vs {path} ({deploy_sha}); '
                'run r17_sync.sh first')
        entries.append((module, deploy_sha))

    entries_block = ',\n'.join(
        f'    {json.dumps(m)}' for m in MEMBER_MODULES) + ','
    entries_map = ',\n'.join(
        f'    {json.dumps(m)}: {json.dumps(sha)}' for m, sha in entries)
    content = _TEMPLATE.format(members_block=entries_block,
                               entries_block=entries_map)
    target = release / 'stage2_6_1' / 'runner' / (
        'r17_v2_c13_governance_source_lock.py')
    target.write_text(content, encoding='utf-8', newline='\n')
    print(f'relock wrote {target}')
    for m, sha in entries:
        print(f'  {m} {sha[:16]}...')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
