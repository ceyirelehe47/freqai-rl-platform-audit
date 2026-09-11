#!/usr/bin/env python3
"""Immutable engineering profile for R17 V2 C1/C3 calibration (v2).

This module is the single authority for the fixed plan of
R17V2C13EngineeringCalibration-v2: namespaces, per-stratum quotas,
parameter snapshot derivation and the one-shot generation claim.

v1 (R17V2C13EngineeringCalibration-v1) closed as an honest engineering
FAIL at the first C1 request (single-family generator identity check).
Its namespaces, claim and archived evidence stay untouched and are
never reused: the v1 constants below are retained read-only for
regression diagnostics and admission checks only.

It contains no generation code and imports nothing from the deployed
project at module import time (the heavy imports happen inside
``engineering_pack()`` so the plan/verify CLI stays import-light).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT = 'R17V2C13EngineeringCalibration-v2'
BASELINE = '769b6d282b6e870491e31e92f96828543d23ab24'
PARENT = 'b3bb6087dfb886791e82a66745f0816f4949ee33'
RUNGS = ('D0', 'D1', 'D2', 'D3')
FIT_FAMILIES = ('c1_opportunity', 'c2_context', 'c3_cost')
EVAL_FAMILIES = ('c1_opportunity', 'c3_cost')
FAMILY_C3 = 'c3_cost'

#: v1 合同与四 namespace(只读历史:保留旧失败原件的对照身份;不可用于
#: 新真实生成,v2 admission 拒绝把 v1 proof 填入 v2 配额)。
V1_CONTRACT = 'R17V2C13EngineeringCalibration-v1'
V1_BASELINE = '3e377add6f6b3ba68c24a50ccfffe7534983ca9b'
V1_FIT_NAMESPACES = {'main': 'preplan_v2c13_fit_main_r17',
                     'validation': 'preplan_v2c13_fit_validation_r17'}
V1_EVAL_NAMESPACES = {'main': 'preplan_v2c13_eval_main_r17',
                      'validation': 'preplan_v2c13_eval_validation_r17'}

#: 四个 v2 工程 namespace(与 api/registry 双表一致;engineering-only;
#: 任务书 §3.1 固定名,不复用任何 v1 namespace)。
FIT_NAMESPACES = {'main': 'preplan_v2c13_v2_fit_main_r17',
                  'validation': 'preplan_v2c13_v2_fit_validation_r17'}
EVAL_NAMESPACES = {'main': 'preplan_v2c13_v2_eval_main_r17',
                   'validation': 'preplan_v2c13_v2_eval_validation_r17'}

#: 配额(任务书 §3.1)。
FIT_QUOTA_PER_STRATUM = 6
EVAL_QUOTA_PER_STRATUM = 10
FIT_RESERVE_INDICES = (6, 7)
EVAL_RESERVE_INDICES = (10, 11)

#: 全局预算上限(任务书 §3.2;机器核对,不是运行时配额)。
MAX_PAIR_REQUESTS = 336
MAX_ATTEMPTS_PER_PAIR = 5
MAX_PAIR_ATTEMPTS = 1680

#: C3 备援资格:仅五类原生内容拒绝(带侧前缀;任务书 §4.2)。
C3_RESERVE_CODES = ('too_few_signals', 'too_few_above_cost_signals',
                    'too_few_below_cost_signals', 'missing_signal_directions',
                    'too_few_distractors')
C3_ALLOWED_REJECTIONS = frozenset(
    f'{scope}:{code}' for scope in ('A', 'B', 'pair')
    for code in C3_RESERVE_CODES)

#: 治理修复 v2(B2/A02/A03):生产 authority 是不可变事实。
#:
#: v2 轮缺陷:``RELEASE_REPO_ROOT``/``CLAIM_ROOT`` 是可变模块全局,公开
#: ``set_test_authority()`` 或测试直接 monkeypatch 模块属性即可把生产
#: prepare/run/consume 指到任意临时根。本轮废除可变全局与注入函数:
#: 生产入口每次调用都从下方字面常量重新推导 canonical authority,
#: 不读环境变量、cwd、out、run id 或任何模块可变状态;合成 authority
#: 只能以显式 ``Authority(synthetic=True)`` 实例传入,并且与
#: RealBackend/生产合同组合时在任何持久化、claim、生成之前被拒绝
#: (enforce_authority_combination)。生产 CLI 不暴露任何 root 参数。


class ProfileError(RuntimeError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ProfileError(message)


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


# ------------------------------------------------------------- authority
@dataclass(frozen=True)
class Authority:
    """不可变 authority:frozen 数据类,无任何可变模块状态。

    生产实例由 ``production_authority()`` 从字面常量推导(每次调用
    重新构建,等值比较);合成实例由 ``synthetic_authority()`` 显式
    构建并携带 ``synthetic=True`` 标记。任何写入/claim/生成入口都
    必须先 ``resolve_authority()`` 并通过
    ``enforce_authority_combination()`` 组合校验。
    """

    repo_root: Path
    claim_root: Path
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.synthetic is False:
            require(
                self.claim_root == self.repo_root
                or self.claim_root.is_relative_to(self.repo_root),
                f'production claim root escapes the release repo '
                f'authority: {self.claim_root}')


def production_authority() -> Authority:
    """从字面常量重建生产 authority(不读任何模块可变状态/环境)。

    发布仓库固定根(生成证据所在);一次性工程 claim 根落在发布仓库
    固定开发证据域,与部署布局、out、run id、cwd 无关。
    """
    root = Path('/mnt/f/trading/freqai-rl-audit')
    return Authority(
        repo_root=root,
        claim_root=root / ('stage2_6_1/artifacts/repair17/development/'
                           'v2_c13_engineering_claim'),
        synthetic=False)


def synthetic_authority(repo_root, claim_root) -> Authority:
    """测试专用:显式合成 authority(必须给出独立的临时根)。

    合成根必须位于系统临时目录(pytest tmp_path 即在其中)且不得与
    生产根重叠;合成实例只能配合显式 fixture backend 与声明
    synthetic 的注入合同使用,与 RealBackend/生产合同组合在写入前
    被拒绝。
    """
    import tempfile

    root = Path(repo_root)
    claim = Path(claim_root)
    prod = production_authority()
    for forbidden in (prod.repo_root, prod.claim_root):
        require(not (root == forbidden or claim == forbidden
                     or claim.is_relative_to(forbidden)
                     or root.is_relative_to(forbidden)),
                f'synthetic authority must not overlap the production '
                f'root: {forbidden}')
    tmp = Path(tempfile.gettempdir()).resolve()
    require(root.is_absolute() and claim.is_absolute()
            and (claim == root or claim.is_relative_to(root))
            and root.resolve(strict=False).is_relative_to(tmp),
            'synthetic authority roots must be absolute, nested and '
            'located inside the system temp directory')
    return Authority(repo_root=root, claim_root=claim, synthetic=True)


def resolve_authority(authority: Authority | None = None) -> Authority:
    """None → 从字面常量重建生产 authority;显式实例原样返回。

    每次调用重新推导,不缓存,不读模块可变状态(A02)。"""
    return production_authority() if authority is None else authority


def enforce_authority_combination(authority: Authority, *,
                                  backend: Any = None,
                                  contract: dict | None = None
                                  ) -> None:
    """B2/A04:authority 与 backend/contract 组合在任何持久化、claim、
    生成之前校验。

    - 生产 authority 只能与 RealBackend(None 视为 RealBackend)和
      权威 fixed_contract 组合;
    - 合成 authority 必须与显式 fixture backend(拒绝 None/RealBackend)
      和声明 synthetic 的注入合同组合。
    """
    require(isinstance(authority, Authority),
            'authority must be an immutable Authority instance')
    if not authority.synthetic:
        if backend is not None:
            from r17_v2_c13_batch import RealBackend

            require(isinstance(backend, RealBackend),
                    'production authority cannot pair with a fixture '
                    'backend (synthetic generation into the production '
                    'claim root is forbidden)')
        if contract is not None:
            require(contract == fixed_contract(),
                    'production authority cannot pair with an injected '
                    'contract')
    else:
        if backend is None:
            require(False, 'synthetic authority cannot pair with the '
                           'default RealBackend; pass an explicit '
                           'fixture backend')
        from r17_v2_c13_batch import RealBackend

        require(not isinstance(backend, RealBackend),
                'RealBackend with a synthetic authority is rejected '
                'before any persistence, claim or generation')
        require(isinstance(contract, dict)
                and contract.get('engineering_only') is True
                and contract.get('synthetic_profile') is True,
                'synthetic authority requires an explicit declared-'
                'synthetic contract')


# ---------------------------------------------------------------- stages
def _stage_list() -> list[dict[str, Any]]:
    stages = []
    for split in ('main', 'validation'):
        stages.append({
            'stage': f'fit_{split}', 'kind': 'fit', 'split': split,
            'namespace': FIT_NAMESPACES[split],
            'families': list(FIT_FAMILIES),
            'quota_per_stratum': FIT_QUOTA_PER_STRATUM,
            'reserve_indices': {'c3_cost': list(FIT_RESERVE_INDICES)},
        })
    for split in ('main', 'validation'):
        stages.append({
            'stage': f'eval_{split}', 'kind': 'eval', 'split': split,
            'namespace': EVAL_NAMESPACES[split],
            'families': list(EVAL_FAMILIES),
            'quota_per_stratum': EVAL_QUOTA_PER_STRATUM,
            'reserve_indices': {'c3_cost': list(EVAL_RESERVE_INDICES)},
        })
    return stages


def stage_requests(stage: dict[str, Any]) -> list[dict[str, Any]]:
    """一个 stage 的全部预声明坐标(主额 + C3 备援;固定顺序)。"""
    out = []
    quota = stage['quota_per_stratum']
    for family in stage['families']:
        reserve = stage['reserve_indices'].get(family, [])
        n_indices = quota + len(reserve)
        for rung in RUNGS:
            for index in range(n_indices):
                out.append({
                    'stage': stage['stage'], 'kind': stage['kind'],
                    'split': stage['split'], 'namespace': stage['namespace'],
                    'family': family, 'rung': rung, 'pair_index': index,
                    'tier': 'primary' if index < quota else 'reserve',
                })
    return out


def all_requests() -> list[dict[str, Any]]:
    out = []
    for stage in _stage_list():
        out.extend(stage_requests(stage))
    return out


def request_key(q: dict[str, Any]) -> str:
    return f"{q['stage']}_{q['family']}_{q['rung']}_p{q['pair_index']}"


def fixed_contract() -> dict[str, Any]:
    stages = _stage_list()
    requests = all_requests()
    fit_req = [q for q in requests if q['kind'] == 'fit']
    eval_req = [q for q in requests if q['kind'] == 'eval']
    selected_fit = sum(
        len(s['families']) * len(RUNGS) * s['quota_per_stratum']
        for s in stages if s['kind'] == 'fit')
    selected_eval = sum(
        len(s['families']) * len(RUNGS) * s['quota_per_stratum']
        for s in stages if s['kind'] == 'eval')
    contract = {
        'version': CONTRACT,
        'engineering_only': True,
        'purpose': 'engineering V2 C1/C3 calibration; NOT formal '
                   'qualification, NOT C2 design selection, NOT training',
        'baseline': BASELINE, 'parent': PARENT,
        'rungs': list(RUNGS),
        'stages': stages,
        'namespaces': {'fit': dict(FIT_NAMESPACES),
                       'eval': dict(EVAL_NAMESPACES)},
        'formal_namespaces_touched': [],
        'max_pair_requests': MAX_PAIR_REQUESTS,
        'max_attempts_per_pair': MAX_ATTEMPTS_PER_PAIR,
        'max_pair_attempts': MAX_PAIR_ATTEMPTS,
        'n_planned_requests': len(requests),
        'n_fit_requests': len(fit_req), 'n_eval_requests': len(eval_req),
        'n_selected_pairs_total': selected_fit + selected_eval,
        'n_selected_fit_pairs': selected_fit,
        'n_selected_eval_pairs': selected_eval,
        'n_fit_manifest_entries_per_bank': 2 * (
            FIT_QUOTA_PER_STRATUM * len(FIT_FAMILIES) * len(RUNGS)),
        'n_main_scaled_eval_episodes': 2 * selected_eval,
        'n_fit_pairs_per_bank': FIT_QUOTA_PER_STRATUM * len(FIT_FAMILIES)
        * len(RUNGS),
        'n_eval_pairs_per_family_per_split': EVAL_QUOTA_PER_STRATUM
        * len(RUNGS),
        'canonical_pairs_per_split': 3 * len(EVAL_FAMILIES) * len(RUNGS),
        'c3_reserve_allowed_rejections': sorted(C3_ALLOWED_REJECTIONS),
        'c1_c2_reserve_allowed': False,
        'generation_before_evaluation': True,
        'abort_on_exhaustion': True,
        'eval_requires_both_bundles_frozen': True,
    }
    require(contract['n_planned_requests'] == MAX_PAIR_REQUESTS,
            'planned request list does not match declared 336 budget')
    require(contract['n_fit_requests'] == 160
            and contract['n_eval_requests'] == 176,
            'fit/eval request split does not match 160/176 budget')
    require(contract['n_selected_fit_pairs'] == 144
            and contract['n_selected_eval_pairs'] == 160,
            'selected pair counts do not match 144/160 budget')
    require(contract['n_fit_manifest_entries_per_bank'] == 144,
            'fit manifest entries per bank must be 144')
    require(contract['n_fit_pairs_per_bank'] == 72
            and contract['n_eval_pairs_per_family_per_split'] == 40
            and contract['canonical_pairs_per_split'] == 24,
            'per-bank/per-corpus scales do not match the authorized '
            'engineering plan')
    return contract


# ------------------------------------------------------- parameter snapshot
def engineering_pack() -> dict[str, Any]:
    """本轮工程参数快照(任务书 §2.2 的唯一来源派生;不复制字面量)。

    C1/C3 D0-D2 与 reference defaults 来自 family_specs 原值;D3 来自
    R4_SELECTED_*;C2 四档 = c2l_historical_control(仅工程归一化控制,
    不是 R17 design 选择)。digest 由 R6 pack_digest 原语计算。
    """
    import copy

    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES,
        R4_PARAMETER_PACK_DIGEST,
        R4_SELECTED_C1_D3,
        R4_SELECTED_C3_D3,
        R5_DESIGN_PLAN_DIGEST,
        pack_digest,
    )

    pack = {
        'pack_kind': 'engineering_v2_c13',
        'version': CONTRACT,
        'note': 'engineering normalization control only; NOT an R17 '
                'design selection and NOT a formal parameter pack',
        'd3_overrides': {
            'c1_opportunity': copy.deepcopy(R4_SELECTED_C1_D3),
            'c3_cost': copy.deepcopy(R4_SELECTED_C3_D3),
        },
        'c2_ladder': copy.deepcopy(
            C2_LADDER_CANDIDATES['c2l_historical_control']),
        'r4_parameter_pack_digest': R4_PARAMETER_PACK_DIGEST,
        'r5_design_plan_digest': R5_DESIGN_PLAN_DIGEST,
    }
    pack['digest'] = pack_digest(pack)
    return pack


def parameter_snapshot() -> dict[str, Any]:
    """完整有效参数 + 来源核对(A07;在生成任何 episode 前校验)。"""
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r17_param_pack import (
        r17_family_rung_params,
    )
    from rl_curriculum.curriculum261_r6_param_pack import (
        R4_PARAMETER_PACK_DIGEST,
        R4_SELECTED_C1_D3,
        R4_SELECTED_C3_D3,
        C2_LADDER_CANDIDATES,
        verify_r4_inheritance,
    )

    pack = engineering_pack()
    specs = family_specs()
    rung_params = {f: r17_family_rung_params(f, pack)
                   for f in FIT_FAMILIES}
    reference_defaults = {f: dict(specs[f].reference_defaults)
                          for f in FIT_FAMILIES}

    # 逐位核对:C1/C3 D0-D2 == family_specs 原值;D3 == R4 继承。
    for family in ('c1_opportunity', 'c3_cost'):
        for rung in ('D0', 'D1', 'D2'):
            require(rung_params[family][rung] == specs[family].rung_params[rung],
                    f'{family} {rung} deviates from family_specs baseline')
        selected = (R4_SELECTED_C1_D3 if family == 'c1_opportunity'
                    else R4_SELECTED_C3_D3)
        require(rung_params[family]['D3'] == selected,
                f'{family} D3 does not match R4 inheritance')
        # 参数键集与历史一致(无额外键/缺键)。
        require(set(rung_params[family]['D3']) == set(specs[family].rung_params['D3']),
                f'{family} D3 key set deviates from baseline')
    # C3-D3 防旧小试值(46 / [.14,.36,.50])意外回退。
    require(rung_params['c3_cost']['D3']['alpha_bps'] == 50.0
            and rung_params['c3_cost']['D3']['mixture'] == [0.20, 0.36, 0.44],
            'C3-D3 fell back to the old raw-batch values')
    # C2 == historical control(键集与历史一致;非 design 选择)。
    require(rung_params['c2_context'] == C2_LADDER_CANDIDATES[
        'c2l_historical_control'], 'C2 ladder is not the historical control')
    inheritance = verify_r4_inheritance(pack)
    require(bool(inheritance.get('pass')),
            f'R4 inheritance verification failed: {inheritance}')

    return {
        'pack': pack,
        'rung_params': rung_params,
        'reference_defaults': reference_defaults,
        'r4_parameter_pack_digest': R4_PARAMETER_PACK_DIGEST,
        'sources': {
            'c1_c3_d0_d2': 'family_specs() baseline at HEAD',
            'c1_d3': 'R4_SELECTED_C1_D3',
            'c3_d3': 'R4_SELECTED_C3_D3',
            'c2_ladder': "C2_LADDER_CANDIDATES_R17['c2l_historical_control']",
            'reference_defaults': 'family_specs() baseline at HEAD',
        },
        'r4_inheritance': inheritance,
    }


def make_plan(runtime: dict[str, Any],
              contract: dict[str, Any] | None = None,
              admission_evidence: dict[str, Any] | None = None
              ) -> dict[str, Any]:
    """组装计划。contract=None 用权威 fixed_contract()(生产路径);
    合成链测试可注入小合同(仅测试入口,生产 CLI 不暴露)。请求清单
    一律从传入合同的 stages 派生,生产合同与 all_requests() 等价。

    身份分层(G12):``runtime`` 只承载稳定事实(kind/generators/sources/
    interpreter);namespace 扫描等易变运行观察以 ``admission_evidence``
    的 {path, sha256} 引用进入计划,内容不内嵌 —— 同一证据内容得到
    同一 plan digest,plan 文件自身成为 planning-only 命中也不再改变
    科学计划身份。v2 轮把扫描结果整包内嵌 runtime,导致 preclaim 计划
    (66cbf9f3)与主 run 计划(4fbbb91a)digest 分叉,本轮治理修复废除
    该形态;冷读旧 v2 计划走 validate_plan 的 legacy 分支。
    """
    contract = fixed_contract() if contract is None else contract
    requests = []
    for stage in contract['stages']:
        for q in stage_requests(stage):
            requests.append(
                {'key': request_key(q), 'tier': q['tier'],
                 **{k: q[k] for k in ('stage', 'kind', 'split',
                                      'namespace', 'family', 'rung',
                                      'pair_index')}})
    plan: dict[str, Any] = {
        'contract': contract, 'contract_sha256': digest(contract),
        'baseline': BASELINE, 'runtime': runtime,
        'requests': requests}
    if admission_evidence is not None:
        require(isinstance(admission_evidence, dict)
                and isinstance(admission_evidence.get('path'), str)
                and isinstance(admission_evidence.get('sha256'), str)
                and re.fullmatch(r'[a-f0-9]{64}',
                                 admission_evidence['sha256']) is not None,
                'admission_evidence must be a {path, sha256} content '
                'reference, not an embedded observation')
        plan['admission_evidence'] = {
            'kind': admission_evidence.get('kind', 'namespace_unused_v1'),
            'path': admission_evidence['path'],
            'sha256': admission_evidence['sha256']}
    plan['plan_sha256'] = digest(plan)
    return json.loads(canonical(plan))


def _plan_core(plan: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in plan.items() if k != 'plan_sha256'}


def validate_plan(plan: dict[str, Any]) -> None:
    """计划身份自洽校验(G03/G12 的 digest 层)。

    - plan_sha256 必须等于除自身外全字段的 canonical digest(对持久化
      文件重读同样成立;不再要求与重新 make_plan 逐字段等价 —— 那依赖
      runtime 内嵌易变观察的可重放性,正是 v2 轮 digest 分叉根因);
    - 请求清单仍必须与合同的 stages 派生清单精确等价(科学坐标固定);
    - runtime 形态:新形态不携带 namespace_unused 等易变键;v2 归档的
      legacy 形态(runtime 内嵌 namespace_unused/sources)允许冷读,
      由 verify 的 governance verdict 单独标记,不在此拒绝。
    """
    require(isinstance(plan, dict) and 'plan_sha256' in plan,
            'plan missing plan_sha256')
    require(digest(_plan_core(plan)) == plan['plan_sha256'],
            'plan digest does not match its own content')
    require(plan.get('contract_sha256') == digest(plan['contract']),
            'contract digest mismatch')
    derived: list[dict[str, Any]] = []
    for stage in plan['contract']['stages']:
        for q in stage_requests(stage):
            derived.append(
                {'key': request_key(q), 'tier': q['tier'],
                 **{k: q[k] for k in ('stage', 'kind', 'split',
                                      'namespace', 'family', 'rung',
                                      'pair_index')}})
    require(plan['requests'] == derived,
            'plan identity/request list mismatch')
    require(plan['runtime']['kind'] in ('real', 'test_fixture'),
            'unknown backend kind')
    require(plan['runtime'].get('generators') is not None
            and set(plan['runtime']['generators'])
            == set(FIT_FAMILIES),
            'runtime must carry the three-family generator map')
    if 'admission_evidence' in plan:
        require(isinstance(plan['admission_evidence'], dict)
                and re.fullmatch(r'[a-f0-9]{64}',
                                 str(plan['admission_evidence'].get(
                                     'sha256'))) is not None
                and isinstance(plan['admission_evidence'].get('path'),
                               str),
                'admission_evidence reference malformed')
    if plan['contract'] == fixed_contract():
        return  # 生产合同:结构自洽即通过
    # 注入合同(仅合成链):必须自我声明 engineering_only 与 synthetic
    # 语义,且规模字段与 stages 自洽(不能伪装生产 336 合同)。
    require(plan['contract'].get('engineering_only') is True
            and plan['contract'].get('synthetic_profile') is True,
            'injected contract must be declared synthetic/engineering-only')


def _generation_evidence_marker(doc: Any) -> bool:
    """区分真实生成痕迹与仅计划/任务书/夹具中出现的名字。

    真实生成痕迹的可靠内容特征:proof(call/attempt envelope)或已
    消费的 claim payload。计划、preclaim 回执、任务书文本即使含有
    namespace 字符串也不构成消费(任务书 V09)。
    """
    if not isinstance(doc, dict):
        return False
    if 'call_envelope' in doc or 'attempt_envelopes' in doc:
        return True
    if 'consumed_utc' in doc and 'plan_sha256' in doc:
        return True
    return False


def namespace_unused_evidence(repo_root: Path) -> dict[str, Any]:
    """运行前核对四个 v2 namespace 尚未被任何真实生成消费。

    扫描发布仓库的 artifacts 与部署侧 run 证据目录,寻找包含新
    namespace 的既有记录。命中分为两类:真实生成证据(proof/claim
    → 已消费,阻止运行)与 planning-only(计划/任务书/夹具中的名字
    → 不阻止,V09:不能因新计划包含 namespace 就拒绝自身)。

    只读;结果进入主计划。必要根不可读或 JSON 损坏按"未知"报告并
    停止(V09:不能吞异常后宣布零命中)。
    """
    import os

    repo_root = Path(repo_root) if repo_root is not None \
        else production_authority().repo_root
    names = list(FIT_NAMESPACES.values()) + list(EVAL_NAMESPACES.values())
    hits: list[dict[str, Any]] = []
    planning_hits: list[dict[str, Any]] = []
    unreadable: list[dict[str, Any]] = []
    scan_roots = [repo_root / 'stage2_6_1' / 'artifacts']
    deploy_runs = Path.home() / 'projects' / 'crypto_rl' / (
        'stage2_6_1_runner')
    if deploy_runs.is_dir():
        scan_roots.append(deploy_runs)
    for root in scan_roots:
        if not root.is_dir():
            continue
        if not os.access(root, os.R_OK | os.X_OK):
            unreadable.append({'path': str(root),
                               'reason': 'scan root unreadable'})
            continue
        for path in root.rglob('*.json'):
            # 归档树内的符号链接(含历史 dangling link)不是 regular
            # evidence 实体:自然跳过,不算"必要证据不可读"。真实
            # regular 文件的读取/解析失败仍按未知上报并停止。
            try:
                is_regular = path.is_file()
            except OSError:
                is_regular = False
            if not is_regular:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='strict')
            except (OSError, UnicodeDecodeError) as exc:
                # 必要证据损坏/不可读:报告未知并停止,不吞掉继续。
                unreadable.append({'path': str(path),
                                   'reason': f'{type(exc).__name__}'})
                continue
            found = [n for n in names if n in text]
            if not found:
                continue
            try:
                doc = json.loads(text)
            except ValueError:
                doc = None
            entry = {'path': str(path), 'namespaces': found}
            if _generation_evidence_marker(doc):
                hits.append(entry)
            else:
                planning_hits.append(entry)
    return {'scanned_roots': [str(r) for r in scan_roots],
            'n_hits': len(hits), 'hits': hits,
            'n_planning_only_hits': len(planning_hits),
            'planning_only_hits': planning_hits,
            'unreadable_evidence': unreadable,
            'namespaces_unused': (not hits) and (not unreadable)}


# ------------------------------------------------- plan/receipt/claim protocol
#: 权威最终计划/preclaim receipt/admission evidence 固定位置(与 claim
#: 同根;由 preclaim gate 流程 create-only 写入;production run 只消费
#: 已持久化的同一 plan 文件,不重新组装计划 — G03/G05/G11/G12)。
#: 权威完整回归证据包固定目录(§4.2):同样只由合同与 authority 推导,
#: 调用方不能传任意 regression path(B1/F01)。
RECEIPT_FILENAME = f'{CONTRACT}.preclaim.json'
PLAN_FILENAME = f'{CONTRACT}.plan.json'
EVIDENCE_FILENAME = f'{CONTRACT}.admission_evidence.json'
FULL_REGRESSION_DIRNAME = f'{CONTRACT}.full_regression'


def _fsync_dir(path: Path) -> None:
    import os

    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _guarded_claim_path(filename: str,
                        authority: Authority | None = None) -> Path:
    """权威 claim 根内路径守卫(G07)。

    最终路径 resolve 后必须严格位于 authority 的 claim_root(resolve)
    之内;符号链接、``..``、相对逃逸与第二 checkout 在此拒绝。生产
    claim 根自身也必须在发布仓库根(resolve)之内,防止注入根本身被
    指到权威域外后把 claim 写去任意位置。
    """
    auth = resolve_authority(authority)
    claim_root = auth.claim_root.resolve(strict=True)
    repo_root = auth.repo_root.resolve(strict=True)
    require(claim_root == repo_root or claim_root.is_relative_to(repo_root),
            f'claim root escapes release repo authority: {auth.claim_root}')
    path = claim_root / filename
    resolved = path.resolve(strict=False)
    require(resolved.is_relative_to(claim_root),
            f'claim path escapes authority root: {path}')
    return path


def authoritative_plan_path(authority: Authority | None = None) -> Path:
    return resolve_authority(authority).claim_root / PLAN_FILENAME


def authoritative_evidence_path(authority: Authority | None = None) -> Path:
    return resolve_authority(authority).claim_root / EVIDENCE_FILENAME


def receipt_path(authority: Authority | None = None) -> Path:
    return resolve_authority(authority).claim_root / RECEIPT_FILENAME


def authoritative_full_regression_path(
        authority: Authority | None = None) -> Path:
    """权威完整回归证据包固定目录(只由合同与 authority 推导)。"""
    return (resolve_authority(authority).claim_root
            / FULL_REGRESSION_DIRNAME)


def persist_final_plan(plan: dict[str, Any], *,
                      authority: Authority | None = None
                      ) -> dict[str, Any]:
    """create-only 持久化最终计划(G03):O_EXCL 写入 + 文件与目录 fsync
    + 重读回算 canonical digest 与文件 sha256 对拍。

    落点只由 authority 推导(A06:调用方不能传任意 plan path);已存在
    即拒绝(不覆盖、不重试);调用方随后才能申请 claim。
    """
    import os
    import secrets

    validate_plan(plan)
    path = authoritative_plan_path(authority)
    require(not path.exists(), f'final plan already persisted: {path}')
    payload = (canonical(plan) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(12)
                        + '.tmp')
    try:
        with tmp.open('xb') as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)
    # readback:字节与 digest 双对拍。
    reread = json.loads(path.read_text(encoding='utf-8'))
    require(reread == plan, 'persisted plan readback differs from plan')
    import hashlib

    file_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    require(digest(_plan_core(reread)) == reread['plan_sha256'],
            'persisted plan digest self-check failed')
    return {'path': str(path), 'plan_sha256': plan['plan_sha256'],
            'bytes': len(payload), 'file_sha256': file_sha}


def persist_authoritative_evidence(evidence: dict[str, Any], *,
                                   authority: Authority | None = None
                                   ) -> dict[str, Any]:
    """create-only 持久化 admission evidence 权威副本(namespace 扫描
    结果;plan 以 {path, sha256} 引用)。run() 重算扫描并与该摘要对拍
    —— namespace 消费状态漂移在 claim 前拒绝,而非静默通过。"""
    import hashlib
    import os

    target = authoritative_evidence_path(authority)
    require(not target.exists(),
            f'admission evidence already persisted: {target}')
    body = (canonical(evidence) + '\n').encode('utf-8')
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'xb') as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    _fsync_dir(target.parent)
    return {'path': str(target), 'sha256':
            hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def write_preclaim_receipt(receipt: dict[str, Any], *,
                           authority: Authority | None = None
                           ) -> dict[str, Any]:
    """create-only 写权威 preclaim receipt(G05)。

    receipt 必须绑定:同候选 source closure digest、机器验证过的完整
    回归证据引用(package digest)、最终 plan digest 与 plan 文件字节
    digest;只在最后一次影响主链/guard 的改动与其对应完整回归之后由
    preclaim gate 写入。写入后不得改 guard 沿用旧回执。落点只由
    authority 推导(A06)。
    """
    validate_preclaim_receipt_shape(receipt)
    target = receipt_path(authority)
    require(not target.exists(),
            f'preclaim receipt already exists: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    body = (canonical(receipt) + '\n').encode('utf-8')
    import os

    with open(target, 'xb') as fh:
        fh.write(body)
        fh.flush()
        os.fsync(fh.fileno())
    _fsync_dir(target.parent)
    import hashlib

    return {'path': str(target), 'bytes': len(body),
            'file_sha256': hashlib.sha256(body).hexdigest()}


def validate_preclaim_receipt_shape(receipt: dict[str, Any]) -> None:
    require(isinstance(receipt, dict) and receipt.get('admitted') is True,
            'preclaim receipt not admitted')
    require(receipt.get('profile') == CONTRACT,
            'preclaim receipt bound to a different profile')
    require(isinstance(receipt.get('plan_sha256'), str)
            and re.fullmatch(r'[a-f0-9]{64}',
                             receipt['plan_sha256']) is not None,
            'preclaim receipt missing plan digest')
    require(isinstance(receipt.get('plan_file_sha256'), str)
            and re.fullmatch(r'[a-f0-9]{64}',
                             receipt['plan_file_sha256']) is not None,
            'preclaim receipt missing mandatory plan file byte digest')
    require(isinstance(receipt.get('source_closure_sha256'), str)
            and re.fullmatch(r'[a-f0-9]{64}',
                             receipt['source_closure_sha256']) is not None,
            'preclaim receipt missing source closure digest')
    # B1/F01:完整回归证据必须是机器验证过的内容寻址引用;禁止
    # path=unspecified / caller 自报 entry_rc=0 的伪绿色形态。
    fre = receipt.get('full_regression_evidence')
    require(isinstance(fre, dict)
            and isinstance(fre.get('path'), str)
            and fre['path'] not in ('', 'unspecified')
            and re.fullmatch(r'[a-f0-9]{64}',
                             str(fre.get('package_sha256'))) is not None
            and fre.get('entry_rc') == 0
            and fre.get('business_rc') == 0,
            'preclaim receipt missing machine-verified full-regression '
            'evidence reference (path/package_sha256/entry_rc/'
            'business_rc); caller self-reported rc alone is not '
            'acceptable')


def load_preclaim_receipt(
        authority: Authority | None = None) -> dict[str, Any]:
    """读权威 receipt;缺失/损坏按异常拒绝(fail closed,不静默)。"""
    path = receipt_path(authority)
    require(path.is_file(),
            f'authoritative preclaim receipt missing: {path}')
    try:
        receipt = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ProfileError(
            f'preclaim receipt unreadable (fail closed): {exc}') from exc
    validate_preclaim_receipt_shape(receipt)
    return receipt


def validate_preclaim_receipt(receipt: dict[str, Any], *,
                              plan_sha256: str,
                              source_closure_sha256: str,
                              full_regression_evidence_sha256: str | None
                              = None) -> None:
    """production entry 复验 receipt(G11):同 plan digest、同 source
    closure、(提供时)同完整回归证据包 digest。receipt 过期(候选已改)
    在此拒绝,不能靠 operator 自报。"""
    validate_preclaim_receipt_shape(receipt)
    require(receipt['plan_sha256'] == plan_sha256,
            'preclaim receipt bound to a different plan')
    require(receipt['source_closure_sha256'] == source_closure_sha256,
            'preclaim receipt bound to a different source closure '
            '(stale candidate)')
    if full_regression_evidence_sha256 is not None:
        require(receipt['full_regression_evidence']['package_sha256']
                == full_regression_evidence_sha256,
                'preclaim receipt bound to a different full-regression '
                'evidence package (regressed or replaced evidence)')


def consume_production_claim(*, authority: Authority | None = None
                             ) -> dict[str, Any]:
    """一次性工程 claim 只能从固定权威 plan/receipt 取得(G04/A07)。

    v2 轮缺陷:``run()`` 可用内存 dict 与任意 plan path 消费 claim;
    上一治理轮仍保留 caller 传入 plan_path/receipt 的 API。本轮废除
    caller 输入 — 本函数只从 authority 推导的固定路径读取:

    - 重读权威 plan 文件并重算 plan_sha256 + 文件字节 sha;
    - 权威 receipt 必须通过 validate_preclain_receipt_shape 且绑定
      同 plan digest 与同 plan 文件字节;
    - O_EXCL 创建 claim;两进程竞态恰好一个成功,失败方不删不重试;
    - claim payload 绑定合同、plan 内容 digest、plan 文件字节 digest、
      source closure digest、完整回归证据包 digest 与消费时间(§4.3);
    - claim 后崩溃/业务失败:claim 永久保留,无恢复路径(G10)。
    """
    import hashlib
    import os
    import time

    auth = resolve_authority(authority)
    plan_path = authoritative_plan_path(auth)
    require(plan_path.is_file(),
            f'authoritative plan file missing; claim requires the '
            f'persisted final plan: {plan_path}')
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    validate_plan(plan)
    receipt = load_preclaim_receipt(auth)
    require(receipt['plan_sha256'] == plan['plan_sha256'],
            'preclaim receipt bound to a different plan digest')
    plan_file_sha = hashlib.sha256(
        plan_path.read_bytes()).hexdigest()
    require(receipt['plan_file_sha256'] == plan_file_sha,
            'persisted plan file bytes differ from the receipt anchor '
            '(tampered or replaced plan)')
    auth.claim_root.mkdir(parents=True, exist_ok=True)
    path = _guarded_claim_path(f'{CONTRACT}.json', auth)
    payload = {
        'profile': CONTRACT,
        'contract_sha256': digest(plan['contract']),
        'plan_sha256': plan['plan_sha256'],
        'plan_file_sha256': plan_file_sha,
        'source_closure_sha256': receipt['source_closure_sha256'],
        'full_regression_evidence_sha256': (
            receipt['full_regression_evidence']['package_sha256']),
        'baseline': BASELINE,
        'consumed_utc': time.strftime(
            '%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    body = (canonical(payload) + '\n').encode('utf-8')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)
    return {'path': str(path), 'plan_sha256': plan['plan_sha256'],
            'plan_path': str(plan_path),
            'full_regression_evidence_sha256': (
                payload['full_regression_evidence_sha256'])}


def claim_state(authority: Authority | None = None) -> dict[str, Any]:
    auth = resolve_authority(authority)
    if not auth.claim_root.is_dir():
        return {'consumed': False,
                'path': str(auth.claim_root / f'{CONTRACT}.json')}
    try:
        path = _guarded_claim_path(f'{CONTRACT}.json', auth)
    except (ProfileError, OSError) as exc:
        return {'consumed': True,
                'path': str(auth.claim_root / f'{CONTRACT}.json'),
                'error': f'authority guard rejected: {exc}'}
    if not path.is_file():
        return {'consumed': False, 'path': str(path)}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        return {'consumed': True, 'path': str(path), 'error': str(exc)}
    return {'consumed': True, 'path': str(path),
            'plan_sha256': data.get('plan_sha256'),
            'consumed_utc': data.get('consumed_utc')}


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('plan', help='print fixed contract (no generation)')
    sub.add_parser('namespaces', help='check the four namespaces are unused')
    p = sub.add_parser('params', help='print parameter snapshot (no generation)')
    args = ap.parse_args(argv)
    if args.command == 'plan':
        print(canonical(fixed_contract()))
    elif args.command == 'namespaces':
        print(canonical(namespace_unused_evidence(None)))
    elif args.command == 'params':
        print(canonical(parameter_snapshot()))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
