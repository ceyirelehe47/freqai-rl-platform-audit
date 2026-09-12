"""治理 source lock(R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2)。

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
    "r17_v2_c13_batch",
    "r17_v2_c13_pipeline",
    "r17_v2_c13_profile",
    "r17_v2_c13_regression_evidence",
    "rl_curriculum.curriculum261_pairs",
    "rl_curriculum.curriculum261_r17_c2_launch_prep",
    "rl_curriculum.curriculum261_r17_param_pack",
    "rl_curriculum.curriculum261_r6_design",
    "rl_curriculum.curriculum261_r6_param_pack",
)

#: 成员 → 实际导入字节 SHA-256(由 r17_v2_c13_governance_relock.py
#: 在候选冻结时从部署导入面生成;生成后本文件随候选提交冻结)。
SOURCE_SHA256 = {
    "r17_v2_c13_batch": "bb02cdacd929b63eea290447a37797e2437523974dcb4e24953655692a78a531",
    "r17_v2_c13_pipeline": "9c52f0788f5f8f704e0c0b46fb2adde1c26e0ad8da634177497239fa1e4991c1",
    "r17_v2_c13_profile": "6057491afa5bb59fc9c84336dcf6b7c59635b9cb938940355c02c7f51115c50b",
    "r17_v2_c13_regression_evidence": "0ca3dc15c6410df263d9be3388da3d2582711e552a5fa319ce7734bcab8f7604",
    "rl_curriculum.curriculum261_pairs": "f3b75a011639938e6a61d11fd41f739897a932d04757dc1a4a90c3f17dab48fd",
    "rl_curriculum.curriculum261_r17_c2_launch_prep": "4b21a068918fbb8428d11f18eb1590324bce131d6cf30f4893bd841b5af45036",
    "rl_curriculum.curriculum261_r17_param_pack": "427886de7abc1ff98e0772e4932587b8d54390cb92d14b5f4797e866ca5ca893",
    "rl_curriculum.curriculum261_r6_design": "80765edefdd1c78f405180cb883b5f49b06f949833da3c63bc9e0a0f6555cda4",
    "rl_curriculum.curriculum261_r6_param_pack": "c86153681a72859676fc89973e669e1774bacd339f23feb1092061df7d316afc"
}


def validate_member_set() -> None:
    """成员集合同一性:键集必须与 MEMBER_MODULES 精确相等。"""
    import hashlib
    import json

    lock_keys = set(SOURCE_SHA256)
    declared = set(MEMBER_MODULES)
    if lock_keys != declared or len(SOURCE_SHA256) != len(MEMBER_MODULES):
        raise RuntimeError(
            f'governance source lock member set mismatch: '
            f'extra={sorted(lock_keys - declared)} '
            f'missing={sorted(declared - lock_keys)}')
    import re

    for name, sha in SOURCE_SHA256.items():
        if re.fullmatch(r'[0-9a-f]{64}', sha) is None:
            raise RuntimeError(
                f'governance lock member not signed with a real sha256 '
                f'(PENDING-RELOCK or malformed): {name}')


def source_closure_digest() -> str:
    """成员映射的内容寻址 digest(与 regression evidence 同口径)。"""
    validate_member_set()
    import hashlib
    import json

    body = json.dumps(SOURCE_SHA256, sort_keys=True,
                      separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()
