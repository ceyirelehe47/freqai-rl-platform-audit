#!/usr/bin/env python3
"""Immutable engineering profile for R17 V2 C1/C3 calibration.

This module is the single authority for the fixed plan of
R17V2C13EngineeringCalibration-v1: namespaces, per-stratum quotas,
parameter snapshot derivation and the one-shot generation claim.

It contains no generation code and imports nothing from the deployed
project at module import time (the heavy imports happen inside
``engineering_pack()`` so the plan/verify CLI stays import-light).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CONTRACT = 'R17V2C13EngineeringCalibration-v1'
BASELINE = '3e377add6f6b3ba68c24a50ccfffe7534983ca9b'
PARENT = '5607876b213af825d618868ba89cb0705cfdc472'
RUNGS = ('D0', 'D1', 'D2', 'D3')
FIT_FAMILIES = ('c1_opportunity', 'c2_context', 'c3_cost')
EVAL_FAMILIES = ('c1_opportunity', 'c3_cost')
FAMILY_C3 = 'c3_cost'

#: 四个新工程 namespace(与 api/registry 双表一致;engineering-only)。
FIT_NAMESPACES = {'main': 'preplan_v2c13_fit_main_r17',
                  'validation': 'preplan_v2c13_fit_validation_r17'}
EVAL_NAMESPACES = {'main': 'preplan_v2c13_eval_main_r17',
                   'validation': 'preplan_v2c13_eval_validation_r17'}

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

#: 发布仓库固定根(生成证据所在;env 覆盖仅用于隔离验证副本)。
import os as _os

RELEASE_REPO_ROOT = Path(_os.environ.get(
    'R17_V2C13_REPO_ROOT', '/mnt/f/trading/freqai-rl-audit'))

#: 一次性工程 claim 固定位置(profile 决定;换 out/run_id 不重新取得;
#: 落在发布仓库固定开发证据域,与部署布局无关)。
CLAIM_ROOT = RELEASE_REPO_ROOT / (
    'stage2_6_1/artifacts/repair17/development/v2_c13_engineering_claim')


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


def make_plan(runtime: dict[str, Any]) -> dict[str, Any]:
    contract = fixed_contract()
    plan = {'contract': contract, 'contract_sha256': digest(contract),
            'baseline': BASELINE, 'runtime': runtime,
            'requests': [{'key': request_key(q), 'tier': q['tier'],
                          **{k: q[k] for k in ('stage', 'kind', 'split',
                                               'namespace', 'family',
                                               'rung', 'pair_index')}}
                         for q in all_requests()]}
    plan['plan_sha256'] = digest(plan)
    return json.loads(canonical(plan))


def validate_plan(plan: dict[str, Any]) -> None:
    require(plan['contract'] == fixed_contract(),
            'contract differs from authorized fixed engineering plan')
    expected = make_plan(plan['runtime'])
    require(plan == expected, 'plan identity/request list mismatch')
    require(plan['runtime']['kind'] in ('real', 'test_fixture'),
            'unknown backend kind')


def namespace_unused_evidence(repo_root: Path) -> dict[str, Any]:
    """运行前核对四个新 namespace 尚未被任何真实生成消费。

    扫描发布仓库的 artifacts 与部署侧 run 证据目录,寻找包含新
    namespace 的既有生成记录(排除 registry/api/routing/测试/本轮
    profile 自身)。只读;结果进入主计划。
    """
    repo_root = Path(repo_root) if repo_root is not None \
        else RELEASE_REPO_ROOT
    names = list(FIT_NAMESPACES.values()) + list(EVAL_NAMESPACES.values())
    hits: list[dict[str, Any]] = []
    scan_roots = [repo_root / 'stage2_6_1' / 'artifacts']
    deploy_runs = Path.home() / 'projects' / 'crypto_rl' / (
        'stage2_6_1_runner')
    if deploy_runs.is_dir():
        scan_roots.append(deploy_runs)
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in root.rglob('*.json'):
            try:
                text = path.read_text(encoding='utf-8', errors='strict')
            except (OSError, UnicodeDecodeError):
                continue
            found = [n for n in names if n in text]
            if found:
                hits.append({'path': str(path), 'namespaces': found})
    return {'scanned_roots': [str(r) for r in scan_roots],
            'n_hits': len(hits), 'hits': hits,
            'namespaces_unused': not hits}


def consume_generation_claim(plan: dict[str, Any]) -> dict[str, Any]:
    """一次性工程 claim:create-only;同 profile 第二次主实验被拒。

    claim 路径由 profile 常量决定,与输出目录/监护 run_id 无关。
    """
    import os
    import time

    CLAIM_ROOT.mkdir(parents=True, exist_ok=True)
    path = CLAIM_ROOT / f'{CONTRACT}.json'
    payload = {
        'profile': CONTRACT, 'plan_sha256': plan['plan_sha256'],
        'baseline': BASELINE, 'consumed_utc': time.strftime(
            '%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    body = (canonical(payload) + '\n').encode('utf-8')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.write(fd, body)
        os.fsync(fd)
    finally:
        os.close(fd)
    return {'path': str(path), 'plan_sha256': plan['plan_sha256']}


def claim_state() -> dict[str, Any]:
    path = CLAIM_ROOT / f'{CONTRACT}.json'
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
