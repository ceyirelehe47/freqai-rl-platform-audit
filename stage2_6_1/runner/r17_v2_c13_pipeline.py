#!/usr/bin/env python3
"""One-shot engineering pipeline for R17 V2 C1/C3 calibration.

Stage order is fixed and fail-closed (taskbook S3):
  1. source guard + parameter snapshot + namespace-unconsumed check
  2. claim the one-shot generation right for this profile
  3. fit_main stage  -> unified V2 (fit once, save, reload, freeze)
  4. fit_validation  -> unified V2 (same discipline)
  5. eval_main + eval_validation generation -> sealed membership
  6. explicit v2c13 routing -> scaled evaluation -> canonical checks
  7. R4 pair statistics + R5 strict conditions per family x split
  8. delivery.json (engineering / statistical / formal separated)

Engineering rc=0 requires the full engineering path (bundles, routing,
scaled evaluation, canonical equivalence, evidence). Strict statistical
FAIL does not fail engineering; numerical/routing/evidence errors do.

The verify subcommand is a read-only cold reader (standard library
only): it re-derives schedules, re-validates proofs, cross-checks the
three-layer identities between artifacts and re-computes the strict
statistical algebra from the sealed episode rows. It does NOT re-execute
vendor transforms or NumPy bootstrap (S3 reload/transform originals
carry that scope).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from r17_v2_c13_profile import (
    BASELINE, CONTRACT, EVAL_NAMESPACES, FIT_NAMESPACES, RUNGS,
    authoritative_plan_path, canonical, claim_state,
    consume_production_claim, digest, engineering_pack,
    fixed_contract, load_preclaim_receipt, make_plan,
    namespace_unused_evidence, parameter_snapshot, persist_authoritative_evidence,
    persist_final_plan, request_key, stage_requests, validate_plan,
    validate_preclaim_receipt, write_preclaim_receipt)
from r17_v2_c13_batch import (
    RealBackend, StageCursor, execute_stage, file_meta, new_json,
    read_json, require, tree_snapshot, validate_proof)

#: 主流程 fit 计数(A10:恰好两次;eval 期间 refit 即工程错误)。
FIT_CALL_LOG: list[str] = []

#: 评估政策调用计数(A06:任一 eval 分层耗尽时必须为零)。
POLICY_EVALUATION_STARTED: bool = False

#: eval 阶段激活标志(B05:评估开始后任何主流程 fit/refit 入口调用
#: 被拒;独立于 FIT_CALL_LOG 自报列表的硬守卫)。
_EVAL_PHASE_ACTIVE: bool = False


def ensure_imports() -> None:
    try:
        import rl_curriculum.curriculum261_api  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name not in ('rl_curriculum',
                            'rl_curriculum.curriculum261_api'):
            raise
        src = Path(__file__).resolve().parent.parent / 'src'
        if not src.is_dir():
            raise
        sys.path.insert(0, str(src))


def source_guard() -> dict:
    """治理 source guard(P03):使用本轮治理闭包 lock,不再借历史
    v2 主 run 执行闭包(r17_v2_c13_source_lock.py,d3cdf3d1 字节只读)
    给新代码背书。成员集固定,重复/缺失/额外成员拒绝。"""
    from r17_v2_c13_batch import ensure_imports as _ei

    _ei()
    import importlib

    from r17_v2_c13_governance_source_lock import SOURCE_SHA256
    from r17_v2_c13_governance_source_lock import (
        validate_member_set as _validate_members,
    )

    _validate_members()
    actual = {}
    for name, expected in SOURCE_SHA256.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        got = file_meta(path)['sha256']
        require(got == expected,
                f'actual imported source drift: {name} ({path})')
        actual[name] = {'path': str(path), 'sha256': got}
    return actual


# ------------------------------------------------------------- fit/freeze
def fit_and_freeze(root: Path, split: str, records: list[Any],
                    params_snapshot: dict, plan: dict,
                    predeclared_transform_df: Any,
                    expected_fit_pairs: int = 72) -> dict:
    """Fit the unified three-curriculum V2 exactly once, then freeze.

    记录 fit 调用;序列化完整 envelope;用原 load_envelope 重载;三层
    hash 前后对拍;预声明 fit 行 transform 逐位对拍;写冻结 checkpoint
    (引用初始 plan 摘要,不回填)。

    expected_fit_pairs 默认 72(生产合同);合成链的小 profile 由
    run() 从合同传下来,数值面不变。
    """
    global _EVAL_PHASE_ACTIVE
    require(not _EVAL_PHASE_ACTIVE,
            'refit blocked: evaluation phase already started')
    ensure_imports()
    from rl_curriculum.curriculum261_r17_calibration import (
        fit_preprocessor_v2_from_bank_r17,
    )

    pack = params_snapshot['pack']
    namespace = FIT_NAMESPACES[split]
    FIT_CALL_LOG.append(f'fit_{split}')
    require(len(FIT_CALL_LOG) <= 2,
            f'more than two main-flow fits: {FIT_CALL_LOG}')
    v2, manifest = fit_preprocessor_v2_from_bank_r17(
        namespace, pack, records=list(records),
        parameter_pack_identity=pack['digest'])
    require(manifest['n_pairs'] == expected_fit_pairs
            and manifest['n_episodes'] == 2 * expected_fit_pairs,
            f'fit bank size {manifest["n_pairs"]} != {expected_fit_pairs} '
            f'pairs')
    bundle_dir = root / 'bundles' / split
    bundle_dir.mkdir(parents=True, exist_ok=True)
    envelope_path = bundle_dir / 'envelope.json'
    require(not envelope_path.exists(), 'envelope already exists')
    v2.serialize_envelope(envelope_path)

    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2,
    )

    reloaded = RouteCPreprocessorV2.load_envelope(envelope_path)
    before = {
        'parameter_state_hash': v2.parameter_state_hash,
        'fit_manifest_multiset_hash': v2.manifest_multiset_hash,
        'preprocessor_bundle_hash': v2.bundle_hash,
    }
    after = {
        'parameter_state_hash': reloaded.parameter_state_hash,
        'fit_manifest_multiset_hash': reloaded.manifest_multiset_hash,
        'preprocessor_bundle_hash': reloaded.bundle_hash,
    }
    require(before == after, 'reload changed the three-layer identity')
    t1 = v2.transform(predeclared_transform_df).to_numpy()
    t2 = reloaded.transform(predeclared_transform_df).to_numpy()
    require((t1 == t2).all(),
            'reloaded transform not bitwise equal on predeclared rows')
    verify_report = reloaded.verify()
    require(bool(verify_report.get('pass')), f'v2.verify() failed: {verify_report}')
    # verify() 可重算不等于仍等于冻结值:显式对照(任务书 §5.3)。
    require(after == before, 'verify-passing object drifted from freeze')
    checkpoint = {
        'split': split, 'namespace': namespace,
        'plan_sha256': plan['plan_sha256'],
        'contract': CONTRACT,
        'frozen_before_any_eval': True,
        'hashes': after,
        'envelope_file_sha256': file_meta(envelope_path)['sha256'],
        'manifest_summary': {
            'n_pairs': manifest['n_pairs'],
            'n_episodes': manifest['n_episodes'],
            'n_rows': manifest['n_rows'],
            'multiset_hash': manifest['multiset_hash']},
        'verify_report': verify_report,
        'reload_transform_bitwise_equal': True,
    }
    new_json(bundle_dir / 'frozen_checkpoint.json', checkpoint)
    new_json(bundle_dir / 'fit_manifest.json', manifest)
    return {'checkpoint': checkpoint, 'manifest': manifest,
            'hashes': after}


def _fit_records_from_stage(root: Path, stage_name: str,
                            handles: dict[str, Any],
                            expected_fit_pairs: int = 72,
                            contract: dict | None = None) -> list[Any]:
    """选中名单 -> fit records(A09:来源隔离校验)。

    contract=None 用权威 fixed_contract()(生产);合成链注入小合同。
    """
    contract = fixed_contract() if contract is None else contract
    selection = read_json(root / 'stages' / stage_name / 'selection.json')
    require(selection['quota_filled'] and selection['evaluation_not_started'],
            'fit requires a closed fit stage')
    stage = next(s for s in contract['stages']
                 if s['stage'] == stage_name)
    coords = {(q['family'], q['rung'], q['pair_index']): q
              for q in stage_requests(stage)}
    per_stratum: dict[tuple[str, str], int] = {}
    records = []
    for coord in selection['member_coordinates']:
        key = request_key(coord)
        require(key in handles, f'selected member missing handle: {key}')
        rec = handles[key]
        require((rec.family, rec.rung, rec.pair_index)
                == (coord['family'], coord['rung'], coord['pair_index']),
                'handle identity mismatch')
        require(rec.family in stage['families'],
                'foreign family in fit bank')
        require(getattr(rec.attempt_log, 'seed_namespace', None)
                == stage['namespace'],
                'record generated under a foreign namespace cannot '
                'enter this fit bank')
        require(rec.integrity_ok is True,
                'integrity-failed record cannot enter fit')
        per_stratum[(rec.family, rec.rung)] = per_stratum.get(
            (rec.family, rec.rung), 0) + 1
        records.append(rec)
    require(set(per_stratum) == {(f, r) for f in stage['families']
                                  for r in RUNGS},
            'fit bank strata incomplete')
    require(all(n == stage['quota_per_stratum']
                for n in per_stratum.values()),
            'fit bank stratum quota mismatch')
    require(len(records) == expected_fit_pairs,
            f'fit bank must hold exactly {expected_fit_pairs} pairs')
    return records


# ----------------------------------------------------------- evaluation
def evaluate_split(root: Path, split: str, handles: dict[str, Any],
                   params_snapshot: dict, plan: dict,
                   ledger: Any, expected_eval_pairs: int = 40,
                   expected_canonical_pairs: int = 24) -> dict:
    """One split: explicit routing -> scaled eval -> canonical -> R4/R5."""
    ensure_imports()
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r4_pairs import (
        rung_report_r4,
    )
    from rl_curriculum.curriculum261_r5_pairs import corpus_conditions_r5
    from rl_curriculum.curriculum261_r17_param_pack import (
        r17_family_rung_params,
    )
    from rl_curriculum.curriculum261_r17_reference import (
        reference_equivalence_run_r17,
        write_reference_equivalence_artifacts_r17,
    )
    from rl_curriculum.curriculum261_r17_routing import (
        build_routing_r17, require_eval_routing_r17,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2,
    )

    global POLICY_EVALUATION_STARTED
    global _EVAL_PHASE_ACTIVE
    _EVAL_PHASE_ACTIVE = True

    pack = params_snapshot['pack']
    specs = family_specs()
    eval_namespace = EVAL_NAMESPACES[split]
    role = 'main' if split == 'main' else 'holdout'
    frozen = read_json(root / 'bundles' / split / 'frozen_checkpoint.json')
    require(frozen['frozen_before_any_eval'] is True,
            'bundle not frozen before evaluation')
    require(frozen['plan_sha256'] == plan['plan_sha256'],
            'frozen checkpoint not bound to the initial plan')
    envelope_path = root / 'bundles' / split / 'envelope.json'
    v2 = RouteCPreprocessorV2.load_envelope(envelope_path)
    require({
        'parameter_state_hash': v2.parameter_state_hash,
        'fit_manifest_multiset_hash': v2.manifest_multiset_hash,
        'preprocessor_bundle_hash': v2.bundle_hash,
    } == frozen['hashes'],
        f'reloaded {split} bundle deviates from frozen checkpoint')
    routing = build_routing_r17(
        role, v2, v2c13v2=True,
        expected_bundle_hash=frozen['hashes']['preprocessor_bundle_hash'])

    def _recheck_frozen(anchor: str) -> None:
        """评估调用后再次核对实际对象与 envelope 文件未漂移(WP3.5)。

        routing.bundle() 已在取用时重算实际三层身份(B4);此处补评估
        后检查:对象身份必须仍等于冻结值,envelope 文件字节必须仍等于
        checkpoint 记录的 hash。验证边界覆盖实际对象,不用
        v2.verify().pass 或缓存 hash 代替。
        """
        routing._require_actual_object_matches_frozen(anchor)
        require(file_meta(envelope_path)['sha256']
                == frozen['envelope_file_sha256'],
                f'envelope file drifted after evaluation: {anchor}')

    stage_name = f'eval_{split}'
    selection = read_json(root / 'stages' / stage_name / 'selection.json')
    require(selection['quota_filled'], 'eval stage not closed')
    coords = selection['member_coordinates']
    members = [request_key(c) for c in coords]
    by_key = {request_key(c): c for c in coords}

    # 评估输入不变性锚点(评估不得改变生成输入)。
    from rl_curriculum.curriculum261_api import episode_content_hash

    anchor = {k: {s: episode_content_hash(handles[k].episodes[s])
                  for s in ('A', 'B')} for k in members}

    POLICY_EVALUATION_STARTED = True
    out: dict[str, Any] = {'split': split, 'eval_namespace': eval_namespace,
                           'role': role,
                           'role_note': ('engineering validation reuses '
                                         'legacy holdout-role; not a frozen '
                                         'holdout') if split == 'validation'
                         else 'engineering main',
                         'families': {}}
    eval_dir = root / 'evaluations' / split
    for family in ('c1_opportunity', 'c3_cost'):
        bundle = require_eval_routing_r17(
            routing, eval_namespace,
            context=f'calibration_{split}_{family}', ledger=ledger,
            expected_bundle_hash=frozen['hashes'][
                'preprocessor_bundle_hash'])
        records = [handles[k] for k in members
                   if by_key[k]['family'] == family]
        require(len(records) == expected_eval_pairs,
                f'{family} eval corpus must hold {expected_eval_pairs} '
                f'pairs')
        rung_params = r17_family_rung_params(family, pack)
        thresholds = dict(specs[family].reference_defaults)
        family_report = rung_report_r4(
            records, family, rung_params, thresholds, preproc=bundle,
            corpus=eval_namespace)
        conditions = corpus_conditions_r5(family_report, kappa=1.5)
        new_json(eval_dir / f'{family}_report.json',
                 {'family_report': family_report,
                  'conditions': conditions,
                  'rung_params': rung_params,
                  'thresholds': thresholds,
                  'member_keys': [k for k in members
                                  if by_key[k]['family'] == family]})
        out['families'][family] = {
            'strict_pass': bool(conditions['pass']),
            'conditions': conditions,
        }
        # 每条 family 评估完成后核对冻结对象/envelope 未漂移(WP3.5)。
        _recheck_frozen(f'{split}/{family}/scaled_eval')

    # canonical 等价:每 family 每 rung 选择顺序前 3 对(共 24 pair/
    # 48 episode per split;两分区合计 48 pair / 96 episode)。
    equiv_records = []
    equiv_keys: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for k in members:
        c = by_key[k]
        slot = (c['family'], c['rung'])
        if seen.get(slot, 0) < 3:
            seen[slot] = seen.get(slot, 0) + 1
            equiv_records.append(handles[k])
            equiv_keys.append(k)
    require(len(equiv_records) == expected_canonical_pairs,
            f'canonical subset must hold {expected_canonical_pairs} '
            f'pairs, got {len(equiv_records)}')
    equiv_bundle = require_eval_routing_r17(
        routing, eval_namespace, context=f'reference_equivalence_{split}',
        ledger=ledger,
        expected_bundle_hash=frozen['hashes']['preprocessor_bundle_hash'])
    equiv_report = reference_equivalence_run_r17(
        equiv_records, equiv_bundle, pack, eval_namespace=eval_namespace,
        ledger=ledger,
        expected_bundle_hash=frozen['hashes']['preprocessor_bundle_hash'])
    write_reference_equivalence_artifacts_r17(
        eval_dir, equiv_report, stem='reference_equivalence')
    # canonical 调用后再次核对冻结对象/envelope 未漂移(WP3.5)。
    _recheck_frozen(f'{split}/canonical')
    out['reference_equivalence'] = {
        'pass': bool(equiv_report['pass']),
        'n_episodes': equiv_report['n_episodes'],
        'canonical_scaled_full_equality':
            equiv_report['canonical_scaled_full_equality'],
        'unexplained_mismatches': equiv_report['unexplained_mismatches'],
        'legacy_action_diffs_total':
            equiv_report['legacy_action_diffs_total'],
        'float64_math_path_pass':
            equiv_report['float64_math_path']['pass'],
        'member_keys': equiv_keys,
    }

    # 评估后输入不变性对拍。
    for k in members:
        for s in ('A', 'B'):
            require(episode_content_hash(handles[k].episodes[s])
                    == anchor[k][s],
                    f'evaluation mutated generation input: {k}/{s}')
    out['n_ledger_rows'] = len(ledger.rows)
    return out


# ------------------------------------------------------------------- run
def prepare_authoritative_plan(*, backend: Any = None,
                               contract: dict | None = None,
                               authority: Any = None
                               ) -> dict:
    """preclaim gate 流程(G03/G05/G11 + B1/B2/§5.3):组装并持久化权威
    交付三元组。

    生产上这是独立于 ``run`` 的准入步骤,只能在同候选完整回归之后执行。
    顺序(§5.3,全部在写入前完成拒绝):

    1. 解析 authority(默认生产字面常量)并校验 backend/contract 组合;
    2. 读取并机器验证权威完整回归证据包(固定路径;缺省/伪/过期/
       不同候选回归在创建 plan/receipt/claim 之前拒绝 — F01/F11);
    3. 验证当前 source closure 与回归候选闭包相同(B4);
    4. source guard + 参数快照 + namespace-unconsumed 扫描(零生成);
    5. 扫描结果 create-only 持久化为 admission evidence 权威副本;
    6. 最终计划 create-only 持久化(计划以 {path, sha256} 引用 evidence);
    7. preclaim receipt create-only 写入,绑定 plan digest、plan 文件
       字节、source closure digest 与机器验证的回归证据包 digest。

    幂等性:create-only,任何已存在即拒绝(不允许覆盖重试)。调用方
    不能传任意 regression path 或自报 rc — 证据包只从 authority 推导
    的固定路径读取(B1)。"""
    import hashlib

    from r17_v2_c13_profile import (
        authoritative_full_regression_path, enforce_authority_combination,
        resolve_authority,
    )

    auth = resolve_authority(authority)
    # A04/B2:组合校验先于任何写入(合成 authority + RealBackend/生产
    # 合同在此拒绝)。
    enforce_authority_combination(auth, backend=backend, contract=contract)

    pkg_path = authoritative_full_regression_path(auth)
    # 先取当前闭包,再让校验器对拍证据包记录的候选闭包(不同候选
    # 回归在此拒绝)。
    sources = source_guard()
    from r17_v2_c13_regression_evidence import verify_package

    regression_verdict = verify_package(
        pkg_path, authority=auth, current_sources=sources,
        checks=('full' if not auth.synthetic else 'structural'))
    require(regression_verdict['ok'],
            f'full regression evidence rejected at preclaim: '
            f'{regression_verdict["errors"][:5]}')
    snapshot = parameter_snapshot()  # 参数面校验(零生成)
    ns_check = namespace_unused_evidence(auth.repo_root)
    require(ns_check['namespaces_unused'],
            f'namespaces already consumed or evidence unreadable: '
            f'{ns_check["hits"][:5]}')
    backend = RealBackend(snapshot) if backend is None else backend
    runtime = backend.describe()
    runtime['sources'] = sources
    ev = persist_authoritative_evidence(ns_check, authority=auth)
    plan = make_plan(
        runtime, contract, admission_evidence={
            'kind': 'namespace_unused_v1',
            'path': plan_admission_evidence_ref(),
            'sha256': ev['sha256']})
    validate_plan(plan)
    persisted = persist_final_plan(plan, authority=auth)
    receipt = {
        'profile': CONTRACT,
        'admitted': True,
        'plan_sha256': persisted['plan_sha256'],
        'plan_file_sha256': persisted['file_sha256'],
        'source_closure_sha256': digest(sources),
        'full_regression_evidence': {
            'path': str(pkg_path),
            'package_sha256': regression_verdict['package_sha256'],
            'entry_rc': regression_verdict['summary']['entry_rc'],
            'business_rc': regression_verdict['summary']['business_rc'],
            'format': regression_verdict['format'],
        },
        'evidence_sha256': ev['sha256'],
    }
    write_preclaim_receipt(receipt, authority=auth)
    return {'plan': plan, 'persisted': persisted,
            'receipt_written': receipt,
            'regression_verdict': regression_verdict}


def plan_admission_evidence_ref() -> str:
    """计划内 evidence 引用路径(权威 claim 根内文件名;G12 稳定身份)。"""
    from r17_v2_c13_profile import EVIDENCE_FILENAME

    return EVIDENCE_FILENAME


def normalize_ns_evidence(ns_check: dict, authority: Any = None) -> dict:
    """namespace 扫描结果的"决策身份"规范化(G12 §5.2)。

    权威 claim 根内的 plan/receipt/evidence 文件自身会作为
    planning-only 命中出现(preclaim 落盘前后两次扫描内容因此不同);
    它们不是真实生成证据,从 planning 命中中剔除后再参与 evidence
    身份对比。真实生成 hits(proof/claim 消费载荷)与 unreadable
    绝不剔除 —— 权威根内出现它们仍然是硬阻塞。
    """
    from r17_v2_c13_profile import resolve_authority

    claim_root = str(resolve_authority(authority).claim_root.resolve(
        strict=False))
    out = json.loads(canonical(ns_check))
    kept = [h for h in out.get('planning_only_hits', [])
            if not str(h.get('path', '')).startswith(claim_root + '/')]
    out['planning_only_hits'] = kept
    # 仅当输入已携带该计数字段时同步更新(不向无键输入引入新键,
    # 保持 canonical 身份稳定)。
    if 'n_planning_only_hits' in out:
        out['n_planning_only_hits'] = len(kept)
    return out


def run(out_dir: Path, *, backend: Any = None,
        contract: dict | None = None, authority: Any = None) -> int:
    """执行完整工程链。backend/contract 仅测试合成链注入用(生产
    CLI 不传:固定 RealBackend + 权威 fixed_contract);注入产物强制
    标记 synthetic,verify 不授予工程完成。

    治理修复(G03/G04/G11/G12 + B2/B4):run 不再组装计划——它只消费
    preclaim 流程持久化的权威 plan 文件,复验 receipt(同 plan/同
    source closure/同回归证据包 digest)与 admission evidence(当前
    namespace 扫描摘要必须仍等于计划引用值),然后在任何生成之前
    重新机器验证权威完整回归证据包(篡改/重签 manifest 在 claim 前
    拒绝),最后从固定权威路径取得一次性 claim。"""
    from r17_v2_c13_profile import (
        enforce_authority_combination, resolve_authority,
    )

    auth = resolve_authority(authority)
    enforce_authority_combination(auth, backend=backend, contract=contract)
    root = Path(out_dir)
    require(root.parent.is_dir(), 'output parent must already exist')
    root = root.parent.resolve(strict=True) / root.name
    root.mkdir(exist_ok=False)

    result = {'contract': CONTRACT, 'engineering_only': True,
              'status': 'error', 'rc': 3, 'error': None,
              'phase': 'init', 'engineering_path_complete': False,
              'statistical': None, 'formal_qualification_issued': False,
              'calibration_qualified': False,
              'synthetic': bool(backend is not None
                                or contract is not None)}
    ledger = None
    handles: dict[str, Any] = {}
    try:
        result['phase'] = 'preflight_source_guard'
        sources = source_guard()
        result['phase'] = 'preflight_parameter_snapshot'
        params_snapshot = parameter_snapshot()
        result['phase'] = 'preflight_namespace_unused_check'
        ns_check = namespace_unused_evidence(auth.repo_root)
        require(ns_check['namespaces_unused'],
                f'namespaces already consumed or evidence unreadable: '
                f'{ns_check["hits"][:5]} {ns_check["unreadable_evidence"][:5]}')
        backend = RealBackend(params_snapshot) if backend is None \
            else backend

        # G12:run 不重新组装计划。消费 preclaim 流程持久化的同一权威
        # plan 文件;当前扫描摘要必须仍等于计划引用值(namespace 状态
        # 漂移在 claim 前拒绝)。摘要口径与持久化 evidence 文件字节
        # 一致(canonical + 换行)。
        import hashlib

        result['phase'] = 'authoritative_plan_consumption'
        plan_path = authoritative_plan_path(auth)
        require(plan_path.is_file(),
                f'authoritative final plan missing (preclaim not run?): '
                f'{plan_path}')
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        validate_plan(plan)
        current_evidence_sha = hashlib.sha256(
            (canonical(normalize_ns_evidence(ns_check, authority=auth))
             + '\n').encode('utf-8')).hexdigest()
        require(plan.get('admission_evidence', {}).get('sha256')
                == current_evidence_sha,
                'namespace admission evidence drifted from the '
                'persisted plan (state changed after preclaim)')
        runtime = backend.describe()
        runtime['sources'] = sources
        require(plan['runtime'] == json.loads(canonical(runtime)),
                'live backend runtime differs from the persisted plan '
                '(candidate drift after preclaim)')
        persisted_plan_sha = plan['plan_sha256']
        persisted_file_sha = hashlib.sha256(
            plan_path.read_bytes()).hexdigest()

        # G11:production 入口复验权威 preclaim receipt(同 plan digest、
        # 同 source closure);缺失/过期/不同候选一律拒绝,不消费 claim。
        result['phase'] = 'preclaim_receipt_validation'
        receipt = load_preclaim_receipt(auth)
        validate_preclaim_receipt(
            receipt, plan_sha256=persisted_plan_sha,
            source_closure_sha256=digest(sources))
        require(receipt['plan_file_sha256'] == persisted_file_sha,
                'authoritative plan file bytes differ from the receipt '
                'anchor (tampered or replaced plan)')

        # B4/F09/F10/F11:在任何生成之前重新机器验证权威完整回归证据
        # 包,并核对 receipt 锚定的包 digest(追加/等长篡改/重签外层
        # manifest 都改变包 digest,在此拒绝)。
        result['phase'] = 'full_regression_evidence_revalidation'
        from r17_v2_c13_profile import authoritative_full_regression_path
        from r17_v2_c13_regression_evidence import verify_package

        pkg_path = authoritative_full_regression_path(auth)
        regression_verdict = verify_package(
            pkg_path, authority=auth, current_sources=sources,
            checks=('full' if not auth.synthetic else 'structural'))
        require(regression_verdict['ok'],
                f'full regression evidence rejected before claim: '
                f'{regression_verdict["errors"][:5]}')
        validate_preclaim_receipt(
            receipt, plan_sha256=persisted_plan_sha,
            source_closure_sha256=digest(sources),
            full_regression_evidence_sha256=(
                regression_verdict['package_sha256']))

        # One-shot claim (S2/S3):claim 只能从固定权威路径取得(G04/
        # A07:不接受 caller 传 plan path 或内存 receipt);second main
        # experiment is refused even with a fresh out dir or monitored
        # run id.
        result['phase'] = 'claim'
        claim = claim_state(auth)
        require(not claim['consumed'],
                f'generation claim already consumed: {claim}')
        consumed = consume_production_claim(authority=auth)
        # run root 保存权威计划的字节副本(plan.json);副本与权威文件
        # 字节一致,manifest/verify 以此为 run 内锚点。
        plan_copy = root / 'plan.json'
        plan_copy.write_bytes(plan_path.read_bytes())
        require(hashlib.sha256(plan_copy.read_bytes()).hexdigest()
                == persisted_file_sha,
                'run-local plan copy diverges from authoritative plan')
        new_json(root / 'params_snapshot.json', params_snapshot)
        new_json(root / 'claim.json', consumed)

        bundles: dict[str, dict[str, Any]] = {}
        # stages 循环与计划共用同一合同(权威 plan 内嵌合同;传入
        # contract 仅用于 synthetic 标记判定,不得分叉)。
        if contract is not None:
            require(plan['contract'] == contract,
                    'run contract argument differs from the persisted '
                    'plan contract')
        contract = plan['contract']
        for stage in contract['stages']:
            stage_name = stage['stage']
            result['phase'] = f'{stage_name}_generation'
            stage_result, stage_handles = execute_stage(
                root, stage, backend, params_snapshot, runtime)
            if stage_result['rc'] != 0:
                result.update(
                    status='generation_failed', rc=stage_result['rc'],
                    phase=f'{stage_name}_generation',
                    error=stage_result.get('error'),
                    stop=stage_result.get('stop'))
                raise RuntimeError(
                    f"stage {stage_name} did not close: "
                    f"{stage_result.get('status')}/"
                    f"{stage_result.get('stop')}")
            if stage['kind'] == 'fit':
                result['phase'] = f'{stage_name}_fit_record_assembly'
                records = _fit_records_from_stage(
                    root, stage_name, stage_handles,
                    expected_fit_pairs=contract.get(
                        'n_fit_pairs_per_bank', 72),
                    contract=plan['contract'])
                from rl_curriculum.curriculum261_r3_calibration import (
                    fit_matrix_from_records,
                )

                predeclared = fit_matrix_from_records(records[:8])
                split = stage['split']
                result['phase'] = f'{stage_name}_fit_serialize_reload_freeze'
                bundles[split] = fit_and_freeze(
                    root, split, records, params_snapshot, plan,
                    predeclared,
                    expected_fit_pairs=contract.get(
                        'n_fit_pairs_per_bank', 72))
                new_json(root / 'bundles' / split / 'fit_inputs.json',
                         {'member_keys': [
                             request_key(c) for c in read_json(
                                 root / 'stages' / stage_name
                                 / 'selection.json')['member_coordinates']],
                          'n_records': len(records)})
                # 资源纪律:fit 完成后释放 bank 引用。
                del records, stage_handles
            else:
                handles.update(stage_handles)
        require(len(FIT_CALL_LOG) == 2,
                f'exactly two main-flow fits required: {FIT_CALL_LOG}')
        require(POLICY_EVALUATION_STARTED is False,
                'policy evaluation must not start before membership sealed')

        # 两分区成员全部持久化后才准入评估(任务书 §4.4)。
        result['phase'] = 'eval_membership_seal'
        eval_selection = {
            'main': read_json(
                root / 'stages' / 'eval_main' / 'selection.json'),
            'validation': read_json(
                root / 'stages' / 'eval_validation' / 'selection.json'),
            'evaluation_not_started': True,
        }
        require(all(eval_selection[s]['quota_filled']
                    for s in ('main', 'validation')),
                'eval membership incomplete')
        new_json(root / 'eval_selection.json', eval_selection)

        from rl_curriculum.curriculum261_r17_routing import (
            RoutingLedgerR17,
        )

        ledger = RoutingLedgerR17()
        stats: dict[str, Any] = {}
        for split in ('main', 'validation'):
            result['phase'] = f'eval_{split}_scaled_canonical_statistics'
            split_out = evaluate_split(
                root, split, handles, params_snapshot, plan, ledger,
                expected_eval_pairs=contract.get(
                    'n_eval_pairs_per_family_per_split', 40),
                expected_canonical_pairs=contract.get(
                    'canonical_pairs_per_split', 24))
            for family in ('c1_opportunity', 'c3_cost'):
                stats[f'{family}_{split}'] = {
                    'strict_pass':
                        split_out['families'][family]['strict_pass'],
                    'conditions':
                        split_out['families'][family]['conditions']}
            result.setdefault('reference_equivalence', {})[split] = \
                split_out['reference_equivalence']
        result['phase'] = 'statistics_aggregation'
        require(ledger.all_pass(), 'routing matrix not all pass')

        equiv_all = all(
            v['pass'] for v in result['reference_equivalence'].values())
        require(equiv_all,
                'unexplained canonical equivalence failure is an '
                'engineering error, not a statistical FAIL')
        stats['c1_strict_pass_both_splits'] = bool(
            stats['c1_opportunity_main']['strict_pass']
            and stats['c1_opportunity_validation']['strict_pass'])
        stats['c3_strict_pass_both_splits'] = bool(
            stats['c3_cost_main']['strict_pass']
            and stats['c3_cost_validation']['strict_pass'])
        stats['overall_strict_pass'] = bool(
            stats['c1_strict_pass_both_splits']
            and stats['c3_strict_pass_both_splits'])
        stats['note'] = ('strict statistical FAIL is preserved; it does '
                         'not fail the engineering path and never grants '
                         'calibration qualification')
        result['phase'] = 'publication'
        result.update(
            status='complete', rc=0, phase='delivered',
            engineering_path_complete=True, statistical=stats)
    except Exception as exc:
        if result['status'] == 'error':
            result['error'] = {'type': type(exc).__name__,
                               'message': str(exc)[:2000]}
    result['fit_calls'] = list(FIT_CALL_LOG)
    result['policy_evaluation_started'] = POLICY_EVALUATION_STARTED
    new_json(root / 'result.json', result)
    delivery = {
        'format': 'R17V2C13EngineeringDelivery-v2',
        'contract': CONTRACT,
        'baseline': BASELINE,
        'synthetic': bool(result['synthetic']),
        'engineering_consumer_complete':
            bool(result['engineering_path_complete'])
            and not result['synthetic'],
        'statistical_diagnostic': result['statistical'],
        'calibration_qualified': False,
        'formal_qualification_issued': False,
        'routing_matrix': ledger.matrix() if ledger is not None else [],
        'result_status': result['status'],
    }
    new_json(root / 'delivery.json', delivery)
    manifest = {'contract': CONTRACT,
                'files': tree_snapshot(root)}
    new_json(root / 'manifest.json', manifest)
    return int(result['rc'])


# ---------------------------------------------------------------- verify
#: 必需基线白名单的冷读快照(任务书 WP2:verify 只用标准库,不允许
#: import 生产 numpy 链;运行时测试断言本快照与
#: curriculum261_qualification.REQUIRED_BASELINES 相等,源码锁钉住
#: qualification 文件身份。输入文件不能自定义绑定集合)。
REQUIRED_BASELINES_COLDREAD: dict[str, tuple[str, ...]] = {
    'c1_opportunity': ('always_flat', 'always_long'),
    'c2_context': ('always_flat', 'always_long', 'c2_local_only'),
    'c3_cost': ('always_flat', 'always_long', 'c3_cost_ignorant'),
}

#: 权威 κ(R5 ROBUSTNESS_KAPPA;测试与真实 gate 对拍)。
STRICT_KAPPA = 1.5


def _cluster_stats(values: list[float]) -> dict:
    """纯算术 pair-cluster 统计(冷读复算;与 R4 cluster_stats 同口径)。

    n=1 时 sd=0/se=0、n=0 拒绝由调用方 require 保证(权威对 n=0 返回
    mean=NaN/se=inf,在生产 canonical JSON 中不可序列化,冷读端直接
    拒绝空集合而不是用 SE=0 填平)。
    """
    n = len(values)
    if n == 0:
        return {'n': 0, 'mean': None, 'se': None}
    mean = sum(values) / n
    if n == 1:
        return {'n': 1, 'mean': mean, 'se': 0.0}
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return {'n': n, 'mean': mean, 'se': var ** 0.5 / n ** 0.5}


def _recompute_strict(family_report: dict) -> dict:
    """从封存 pair 表重算 R5 strict 布尔(κ=1.5;不含 bootstrap CI)。

    v2 修复(B3),与权威逐叶对齐:
    - 相邻 gap 的 pair-cluster SE 开平方根(rung_report_r4 的
      sqrt(SE_hi**2 + SE_lo**2),不是平方和);
    - 基线集合只来自 authority 的 family 合白白名单快照
      (REQUIRED_BASELINES),不做"全部数值列都是基线"的自动扩展;
      always_flat 在每个 rung 都检查,不因难度已用 flat 而省略;
    - *_trades / pair 编号 / C1 诊断列只是报告数据,不构成新 gate;
    - margin/gap 均为 mean>0 且 mean>=κ·SE(> 与 >= 的边界语义与
      corpus_conditions_r5 一致);
    - 缺必需基线列、n=0、rung 不全直接拒绝。
    """
    kappa = STRICT_KAPPA
    family = family_report.get('family')
    require(family in REQUIRED_BASELINES_COLDREAD,
            f'unknown family for strict recompute: {family!r}')
    baselines = REQUIRED_BASELINES_COLDREAD[family]
    rows = family_report['pair_table']['rows']
    require(isinstance(rows, list) and rows, 'empty pair table rejected')
    # rung/列完整性:每 rung 必须有行,每个必需基线列必须存在。
    rung_rows: dict[str, list[dict]] = {r: [] for r in RUNGS}
    for row in rows:
        require(row.get('rung') in rung_rows,
                f'unknown rung in pair table: {row.get("rung")!r}')
        rung_rows[row['rung']].append(row)
    require(all(rung_rows[r] for r in RUNGS),
            'pair table missing rows for some rung')
    for b in baselines + ('reference',):
        require(all(b in row['returns'] for rows_ in rung_rows.values()
                    for row in rows_),
                f'missing required returns column: {b}')
    ladder: dict[str, dict] = {}
    for rung in RUNGS:
        vals = [r['returns']['reference'] - r['returns']['always_flat']
                for r in rung_rows[rung]]
        ladder[rung] = _cluster_stats(vals)
    means = [ladder[r]['mean'] for r in RUNGS]
    ordering_ok = bool(
        means[0] > means[1] > means[2] > means[3])
    d3 = ladder['D3']
    d3_positive = bool(d3['mean'] > 0.0)
    d3_ge = bool(d3['mean'] >= kappa * d3['se']
                 if d3['se'] is not None else False)
    gaps_ok = True
    gap_detail = {}
    for k in range(3):
        hi, lo = RUNGS[k], RUNGS[k + 1]
        gap = ladder[hi]['mean'] - ladder[lo]['mean']
        se = ((ladder[hi]['se'] ** 2 + ladder[lo]['se'] ** 2) ** 0.5
              if ladder[hi]['se'] is not None
              and ladder[lo]['se'] is not None else None)
        ok = bool(gap > 0 and se is not None and gap >= kappa * se)
        gaps_ok = gaps_ok and ok
        gap_detail[f'{hi}-{lo}'] = {'gap': gap, 'se': se, 'ok': ok}
    margins_ok = True
    margin_detail = {}
    for b in baselines:
        margin_detail[b] = {}
        for rung in RUNGS:
            vals = [r['returns']['reference'] - r['returns'][b]
                    for r in rung_rows[rung]]
            st = _cluster_stats(vals)
            ok = bool(st['mean'] > 0.0 and st['mean'] >= kappa * st['se'])
            margins_ok = margins_ok and ok
            margin_detail[b][rung] = {'mean': st['mean'], 'se': st['se'],
                                      'ok': ok}
    integrity_unity = bool(
        family_report['pair_integrity_pass_rate'] == 1.0)
    oracle_positive = bool(family_report['oracle_positive_all_rungs'])
    strict_pass = bool(ordering_ok and gaps_ok and d3_positive
                       and d3_ge and margins_ok and integrity_unity
                       and oracle_positive)
    return {'family': family,
            'required_baselines': list(baselines),
            'ordering_ok': ordering_ok, 'gaps': gap_detail,
            'gaps_ok': gaps_ok, 'd3_positive': d3_positive,
            'd3_mean_ge_kappa_se': d3_ge, 'margins': margin_detail,
            'margins_ok': margins_ok, 'pair_integrity_unity':
                integrity_unity, 'oracle_positive': oracle_positive,
            'strict_pass_recomputed': strict_pass}


#: reference writer 的解释性字段允许 ±Infinity(策略阈值距离可为
#: 无穷;writer 用默认 json.dumps 写出非标 token)。gate/统计字段
#: 出现非有限值仍然拒绝。
_EQUIV_INFINITE_OK_FIELDS = frozenset({
    'decision_margin_to_threshold',
    'float32_relative_quantum',
})


def _assert_equiv_finite(value: Any, key: str = '') -> None:
    import math

    if isinstance(value, float) and not math.isfinite(value):
        require(key in _EQUIV_INFINITE_OK_FIELDS,
                f'nonfinite value outside explanatory fields: {key}')
    elif isinstance(value, dict):
        for k, v in value.items():
            _assert_equiv_finite(v, k)
    elif isinstance(value, list):
        for item in value:
            _assert_equiv_finite(item, key)


def _read_reference_equivalence(path: Path) -> dict:
    """读 reference equivalence 报告。

    证据文件整体仍走严格 JSON(禁非有限常量);历史 writer 对解释性
    字段写出 Infinity token 时,退回默认解析并仅当非有限值全部位于
    白名单解释字段内才接受(S6 reader 缺陷修复,不动主产物)。
    """
    text = path.read_text(encoding='utf-8')

    def _invalid(v):
        raise ValueError(f'nonfinite JSON value: {v}')

    try:
        return json.loads(text, parse_constant=_invalid)
    except ValueError:
        doc = json.loads(text)
        _assert_equiv_finite(doc)
        return doc


# --------------------------------------- producer/consumer binding (WP3)
def _entry_multiset_hash(entries: list[dict]) -> str:
    """stdlib 重算 fit manifest multiset hash(与 r4 同口径;E04)。

    与 curriculum261_r4_preprocessing 完全一致:entry canonical 用
    json.dumps(sort_keys, separators=(',',':'), ensure_ascii=False,
    default=str);entry_hash = sha256(canonical)(无前缀);multiset =
    'r4fm-' + sha256(canonical({n_entries, sorted entry_hashes}))。
    """
    import hashlib

    def r4_canonical(obj):
        return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, default=str)

    hashes = sorted(
        hashlib.sha256(r4_canonical(e).encode('utf-8')).hexdigest()
        for e in entries)
    return 'r4fm-' + hashlib.sha256(r4_canonical({
        'n_entries': len(hashes), 'entry_hashes': hashes,
    }).encode('utf-8')).hexdigest()


def _reload_episode_identity(root: Path, stage: str, key: str,
                             side: str, meta: dict) -> str | None:
    """重载持久化 episode 并调用生产 ``episode_content_hash``(E02/E03)。

    v2 持久化格式({key}_{side}.csv + .hidden.csv + 完整 spec.json)可
    重建 GeneratedEpisode 等价对象 → 返回重算的完整内容指纹;旧格式
    (无 hidden/params)该层不可重建 → 返回 None,由调用方按 partial
    诚实登记,绝不复制旧 hash 字段冒充重算。
    CSV 文件字节与 meta.csv_sha256 的对拍在调用方完成(分层:文件
    字节 ≠ episode 身份)。
    """
    ensure_imports()
    import pandas as pd

    from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode
    from rl_curriculum.curriculum261_api import episode_content_hash

    ep_dir = root / 'episodes' / stage
    spec_doc = read_json(ep_dir / f'{key}_{side}.spec.json')
    if (spec_doc.get('format') != 'v2c13-episode-persist-v2'
            or 'hidden_csv' not in meta):
        return None
    df = pd.read_csv(ep_dir / meta['csv'], float_precision='round_trip')
    hidden = pd.read_csv(ep_dir / meta['hidden_csv'],
                         float_precision='round_trip')
    spec = EpisodeSpec(
        family=spec_doc['family'], params=spec_doc['params'],
        seed=int(spec_doc['seed']), split=spec_doc['split'],
        timeframe=spec_doc['timeframe'])
    episode = GeneratedEpisode(
        spec=spec, df=df, hidden=hidden,
        family_version=spec_doc['family_version'],
        timeframe=spec_doc['timeframe'],
        is_null=spec_doc['is_null'],
        generator_fingerprint=spec_doc['generator_fingerprint'],
        meta={})
    return episode_content_hash(episode)


def verify(root: Path) -> dict:
    """Cold read of the whole delivery. No generation, no writes, no
    vendor transforms, no NumPy bootstrap — the sealed bytes, schedule,
    proofs, three-layer identity cross-links and strict statistical
    algebra are re-derived with the standard library only."""
    root = Path(root).resolve(strict=True)
    before = tree_snapshot(root)
    manifest = read_json(root / 'manifest.json')
    require(manifest.get('contract') == CONTRACT,
            'manifest contract mismatch')
    require(manifest['files'] == {
        k: v for k, v in before.items() if k != 'manifest.json'},
        'evidence byte set mismatch')
    plan = read_json(root / 'plan.json')
    validate_plan(plan)
    result = read_json(root / 'result.json')
    delivery = read_json(root / 'delivery.json')
    synthetic = bool(result.get('synthetic'))
    if synthetic:
        require(delivery.get('synthetic') is True
                and delivery['engineering_consumer_complete'] is False,
                'synthetic run must stay marked and never count as '
                'engineering completion')
    else:
        require(delivery.get('synthetic') is False,
                'real run must not carry a synthetic flag')
    require(delivery['engineering_consumer_complete']
            is (bool(result['engineering_path_complete'])
                and not synthetic),
            'delivery/result engineering flag mismatch')
    require(delivery['calibration_qualified'] is False
            and delivery['formal_qualification_issued'] is False,
            'formal qualification must never be issued here')

    stage_reports = {}
    #: producer/consumer 绑定证据(E01-E08);governance flags 驱动四态
    #: verdict(§7.7) —— 旧 v2 归档按事实置 false,不抛错、不翻绿。
    proof_episode_hashes: dict[str, dict[str, dict[str, str]]] = {}
    episode_identity = {'full': 0, 'partial_legacy': 0, 'mismatch': 0}
    for stage in plan['contract']['stages']:
        name = stage['stage']
        sdir = root / 'stages' / name
        stage_result = read_json(sdir / 'result.json')
        cursor = StageCursor(stage)
        proofs = {}
        for ordinal, row in enumerate(stage_result['results']):
            q = cursor.next()
            require(q is not None and row['key'] == request_key(q),
                    'attempted sequence not authorized')
            require(read_json(sdir / 'starts' / (row['key'] + '.json'))
                    == {'coordinate': dict(q), 'ordinal': ordinal},
                    'missing/changed request start')
            if row['status'] == 'fatal':
                require((sdir / 'errors' / (row['key'] + '.json')).is_file(),
                        'fatal record missing')
                cursor.consume(q, 'fatal')
            else:
                proof = read_json(sdir / 'requests' / (row['key'] + '.json'))
                require(validate_proof(
                    q, proof,
                    read_json(root / 'params_snapshot.json'),
                    plan['runtime']) == row['status'],
                    'row/proof status mismatch')
                require(read_json(
                    sdir / 'attempts' / row['key'] / 'call.json')
                    == proof['call_envelope'], 'call journal mismatch')
                for env in proof['attempt_envelopes']:
                    require(read_json(
                        sdir / 'attempts' / row['key']
                        / f"attempt_{env['attempt_index']}.json") == env,
                        'attempt journal mismatch')
                proofs[row['key']] = proof
                cursor.consume(q, row['status'])
        state = cursor.snapshot()
        require(state == stage_result['schedule'],
                'schedule/result mismatch')
        if stage_result['status'] != 'complete':
            # 失败/耗尽的 stage:selection 未必存在(生成中途停止);
            # 已完成部分已逐请求核验,后续 stage 不得出现。
            stage_reports[name] = {
                'status': stage_result['status'],
                'quota_filled': state['quota_filled'],
                'n_selected': len(state['selected'])}
            break
        selection = read_json(sdir / 'selection.json')
        require(selection['member_coordinates'] == [
            dict(q) for q in stage_requests(stage)
            if request_key(q) in set(state['selected'])],
            'selection not bound to fixed schedule')
        stage_reports[name] = {
            'quota_filled': state['quota_filled'],
            'n_selected': len(state['selected'])}
        require(stage_result['status'] == 'complete',
                f'stage {name} not complete')
        # E01:episode_artifacts 键集必须精确等于 selected key set ——
        # 空/缺项字典不得绕过循环;未选/reserve/rejected 不得出现;
        # 每 key 恰好 A/B 两侧;meta 文件名必须是目录内 basename(无
        # 路径逃逸),文件本身为 regular file。
        artifacts = stage_result.get('episode_artifacts', {})
        require(set(artifacts) == set(selection['members']),
                f'episode_artifacts key set != selected key set: '
                f'{name}')
        selected_proofs = {}
        for key in selection['members']:
            require(key in proofs,
                    f'selected member missing validated proof: {key}')
            selected_proofs[key] = proofs[key]['episode_hashes']
        proof_episode_hashes[name] = selected_proofs
        for key, meta in artifacts.items():
            require(set(meta) == {'A', 'B'},
                    f'episode artifact must carry exactly A/B: {key}')
            for side in ('A', 'B'):
                fname = meta[side]['csv']
                require(isinstance(fname, str) and '/' not in fname
                        and '\\' not in fname and fname != '.'
                        and fname != '..'
                        and not fname.startswith('.'),
                        f'episode artifact escapes episode dir: {fname}')
                path = root / 'episodes' / name / fname
                require(path.is_file() and not path.is_symlink(),
                        f'episode artifact not a regular file: {path}')
                # 字节层:CSV 文件 sha 与生成时记录对拍(选定数值输入
                # 不变)。CSV 字节 ≠ episode 身份(E03 分层)。
                require(file_meta(path)['sha256']
                        == meta[side]['csv_sha256'],
                        f'episode csv drift: {key}/{side}')
                # 身份层(E02/E03):对实际重载对象重算权威
                # episode_content_hash;旧格式缺 hidden → partial。
                recomputed = _reload_episode_identity(
                    root, name, key, side, meta[side])
                if recomputed is None:
                    episode_identity['partial_legacy'] += 1
                elif recomputed == meta[side]['episode_content_hash']:
                    episode_identity['full'] += 1
                else:
                    episode_identity['mismatch'] += 1
                    require(False,
                            f'episode identity hash mismatch on reload: '
                            f'{name}/{key}/{side}')
        # v2 持久化格式的 hidden 文件也必须在字节集中(由 manifest 全集
        # 对拍覆盖);meta 引用的 hidden_csv 同样要求 regular file。
        for key, meta in artifacts.items():
            for side in ('A', 'B'):
                hidden_name = meta[side].get('hidden_csv')
                if hidden_name is None:
                    continue
                hp = root / 'episodes' / name / hidden_name
                require(hp.is_file() and not hp.is_symlink(),
                        f'hidden artifact not a regular file: {hp}')
                require(file_meta(hp)['sha256']
                        == meta[side]['hidden_csv_sha256'],
                        f'hidden csv drift: {key}/{side}')

    # bundles:三层身份链交叉对拍(plan -> frozen -> envelope JSON ->
    # delivery);envelope 文件字节与 checkpoint 锚点对照;独立
    # fit_manifest.json 与 envelope 内嵌成员多重集交叉核对。
    envelope_hashes = {}
    run_complete = result['status'] == 'complete'
    for split in ('main', 'validation'):
        bdir = root / 'bundles' / split
        if not bdir.is_dir():
            require(not run_complete,
                    f'complete run missing bundle: {split}')
            continue
        frozen = read_json(bdir / 'frozen_checkpoint.json')
        envelope = read_json(bdir / 'envelope.json')
        require(frozen['hashes'] == envelope['hashes'],
                f'{split} frozen checkpoint / envelope hashes mismatch')
        require(frozen['plan_sha256'] == plan['plan_sha256'],
                f'{split} frozen not bound to initial plan')
        require(frozen['namespace'] == FIT_NAMESPACES[split],
                f'{split} frozen namespace mismatch')
        require(frozen.get('envelope_file_sha256')
                == file_meta(bdir / 'envelope.json')['sha256'],
                f'{split} envelope file bytes drift from freeze anchor')
        manifest_doc = envelope['fit_manifest']
        require(manifest_doc['n_entries'] == 2 * plan['contract'].get(
                    'n_fit_pairs_per_bank', 72),
                f'{split} fit manifest entries != 2 x per-bank pairs')
        require(manifest_doc['namespace'] == FIT_NAMESPACES[split],
                f'{split} fit manifest namespace mismatch')
        families = {e['family'] for e in manifest_doc['entries']}
        require(families == {'c1_opportunity', 'c2_context', 'c3_cost'},
                f'{split} fit manifest not three-curriculum')
        rungs_seen = {e['rung'] for e in manifest_doc['entries']}
        require(rungs_seen == set(RUNGS),
                f'{split} fit manifest rungs incomplete')
        # 独立 fit_manifest.json 与 envelope 内嵌条目/摘要一致。
        side_manifest = read_json(bdir / 'fit_manifest.json')
        require(side_manifest.get('document', {}).get('entries')
                == manifest_doc['entries'],
                f'{split} side fit manifest entries drift from envelope')
        require(side_manifest.get('multiset_hash')
                == frozen['manifest_summary']['multiset_hash'],
                f'{split} side fit manifest multiset hash drift')
        # E04:fit manifest 逐成员绑定 selected fit proof ——
        # (family, rung, pair_index, side) 多重集精确等于 fit stage
        # 的选定坐标×A/B,每条 entry 的 episode_hash 必须等于该 proof
        # 记录的对应侧 episode 内容指纹;namespace 逐条一致;multiset
        # hash 用 stdlib 同口径重算。dup/漏 side/跨 bank/eval 混入、
        # 只比数量或 family/rung 集合都过不了这一层。
        fit_stage = f'fit_{split}'
        require(fit_stage in proof_episode_hashes,
                f'{split} bundle without member-bound fit proofs')
        fit_selection = read_json(
            root / 'stages' / fit_stage / 'selection.json')
        expected_members: dict[tuple, str] = {}
        for coord in fit_selection['member_coordinates']:
            key = request_key(coord)
            for side in ('A', 'B'):
                expected_members[(
                    coord['family'], coord['rung'],
                    int(coord['pair_index']), side)] = \
                    proof_episode_hashes[fit_stage][key][side]
        actual_members: dict[tuple, str] = {}
        for e in manifest_doc['entries']:
            member = (e['family'], e['rung'], int(e['pair_index']),
                      e['side'])
            require(member not in actual_members,
                    f'{split} fit manifest duplicate member: {member}')
            require(e['namespace'] == FIT_NAMESPACES[split],
                    f'{split} fit manifest entry foreign namespace: {e}')
            actual_members[member] = e['episode_hash']
        require(actual_members == expected_members,
                f'{split} fit manifest members/episode hashes not '
                f'member-bound to selected fit proofs')
        require(_entry_multiset_hash(manifest_doc['entries'])
                == manifest_doc['multiset_hash'],
                f'{split} fit manifest multiset hash recompute mismatch')
        envelope_hashes[split] = envelope['hashes']

    # evaluations:统计代数复算 + strict 布尔对拍(完整 run 才存在)。
    stats_recomputed = {}
    governance_routing = {'rows': 0, 'unbound': 0, 'legacy_rows': 0,
                          'hash_mismatch': 0, 'pass_false': 0}
    for split in ('main', 'validation'):
        edir = root / 'evaluations' / split
        if not edir.is_dir():
            require(not run_complete,
                    f'complete run missing evaluations: {split}')
            continue
        eval_stage = f'eval_{split}'
        eval_selection = read_json(
            root / 'stages' / eval_stage / 'selection.json')
        eval_members = [request_key(c)
                        for c in eval_selection['member_coordinates']]
        by_member = {request_key(c): c
                     for c in eval_selection['member_coordinates']}
        for family in ('c1_opportunity', 'c3_cost'):
            path = root / 'evaluations' / split / f'{family}_report.json'
            report = read_json(path)
            require(report['family_report']['corpus']
                    == EVAL_NAMESPACES[split],
                    'evaluation corpus/namespace mismatch')
            require(len(report['family_report']['pair_table']['rows'])
                    == plan['contract'].get(
                        'n_eval_pairs_per_family_per_split', 40),
                    'eval pair table rows != per-family pairs')
            # E05:选定成员 → 持久化 episode → pair row 逐成员一致;
            # reserve index 保留原值;episode hashes ↔ proof 对拍。
            family_members = [k for k in eval_members
                              if by_member[k]['family'] == family]
            require(report['member_keys'] == family_members,
                    f'member_keys not bound to eval selection: '
                    f'{family}/{split}')
            row_keys = {}
            for row in report['family_report']['pair_table']['rows']:
                member = (row['rung'], int(row['pair_index']))
                require(member not in row_keys,
                        f'duplicate pair row: {family}/{split}/{member}')
                require(sorted(row['episode_hashes']) == ['A', 'B'],
                        f'pair row missing A/B: {family}/{split}/{member}')
                row_keys[member] = row['episode_hashes']
            expected_rows = {}
            for k in family_members:
                c = by_member[k]
                expected_rows[(c['rung'], int(c['pair_index']))] = \
                    proof_episode_hashes[eval_stage][k]
            require(row_keys == expected_rows,
                    f'pair rows not member-bound to selected episodes: '
                    f'{family}/{split}')
            recomputed = _recompute_strict(report['family_report'])
            require(recomputed['strict_pass_recomputed']
                    == bool(report['conditions']['pass']),
                    f'strict algebra mismatch: {family}/{split}')
            # E06:result/delivery 的统计必须从已复核 conditions 派生
            # —— 翻绿/删改叶子即使外层 manifest 重签也在此拒绝。
            if run_complete:
                sealed = result['statistical'][f'{family}_{split}']
                require(bool(sealed['strict_pass'])
                        == bool(report['conditions']['pass']),
                        f'result strict flag not derived from report: '
                        f'{family}/{split}')
                require(sealed['conditions'] == report['conditions'],
                        f'result conditions not the reviewed report: '
                        f'{family}/{split}')
            stats_recomputed[f'{family}_{split}'] = recomputed
        equiv = _read_reference_equivalence(
            root / 'evaluations' / split / 'reference_equivalence.json')
        require(equiv['eval_namespace'] == EVAL_NAMESPACES[split],
                'equivalence namespace mismatch')
        require(equiv['n_episodes'] == 2 * plan['contract'].get(
                    'canonical_pairs_per_split', 24),
                'equivalence subset episodes != 2 x canonical pairs '
                'per split')
        # E07:canonical 集合精确 = 每 family×rung 选定顺序前 3 pair;
        # 核对具体成员(不只 n_episodes)、per-episode 结论、unexplained
        # 与 result 声明一致、bundle 绑定等于冻结 hash。
        seen: dict[tuple[str, str], int] = {}
        expected_canonical: list[str] = []
        for k in eval_members:
            c = by_member[k]
            slot = (c['family'], c['rung'])
            if seen.get(slot, 0) < 3:
                seen[slot] = seen.get(slot, 0) + 1
                expected_canonical.append(k)
        if run_complete:
            declared = result['reference_equivalence'][split]
            require(declared['member_keys'] == expected_canonical,
                    f'canonical member set not the fixed first-3-per-'
                    f'stratum selection: {split}')
            require(declared['n_episodes']
                    == 2 * len(expected_canonical),
                    f'canonical episode count mismatch: {split}')
            require(declared['unexplained_mismatches'] == 0
                    and equiv['unexplained_mismatches'] == 0,
                    f'unexplained canonical mismatch is engineering '
                    f'failure: {split}')
            require(declared['pass'] is True
                    and equiv['pass'] is True,
                    f'canonical equivalence not passing: {split}')

    # E08:routing 矩阵与 frozen checkpoint 交叉验证 —— 每行必须携带
    # 真实 expected/actual bundle hash(legacy "(unbound)" 行按治理缺口
    # 计,不抛错:四态 verdict 用),三层身份等于冻结值,pass 全真。
    frozen_hashes = {s: read_json(root / 'bundles' / s
                                  / 'frozen_checkpoint.json')['hashes']
                     for s in ('main', 'validation')
                     if (root / 'bundles' / s).is_dir()}
    routing_matrix = delivery.get('routing_matrix') or []
    for row in routing_matrix:
        governance_routing['rows'] += 1
        if row.get('pass') is not True:
            governance_routing['pass_false'] += 1
        expected_hash = row.get('expected_bundle_hash')
        corpus = str(row.get('corpus', ''))
        split = ('validation' if 'validation' in corpus
                 else 'main' if 'main' in corpus else None)
        frozen = frozen_hashes.get(split) if split else None
        if expected_hash in (None, '(unbound)'):
            governance_routing['unbound'] += 1
            continue
        if 'actual_parameter_state_hash' not in row:
            governance_routing['legacy_rows'] += 1
        if frozen is None:
            require(False, f'routing row without frozen bundle: {corpus}')
        if expected_hash != frozen['preprocessor_bundle_hash']:
            require(False,
                    f'routing expected hash != frozen bundle hash: '
                    f'{corpus}')
        if row.get('actual_bundle_hash') != frozen[
                'preprocessor_bundle_hash']:
            require(False,
                    f'routing actual bundle hash drift: {corpus}')
        if ('actual_parameter_state_hash' in row
                and row['actual_parameter_state_hash']
                != frozen['parameter_state_hash']):
            require(False, f'routing parameter state drift: {corpus}')
        if ('actual_manifest_multiset_hash' in row
                and row['actual_manifest_multiset_hash']
                != frozen['fit_manifest_multiset_hash']):
            require(False, f'routing manifest multiset drift: {corpus}')
    if run_complete:
        require(routing_matrix,
                'complete run missing routing matrix')

    if result['status'] == 'complete':
        require(result['rc'] == 0 and result['error'] is None
                and result['engineering_path_complete'] is True,
                'false successful delivery')
        require(result['fit_calls'] == ['fit_main', 'fit_validation'],
                'fit call log mismatch')
    else:
        require(result['rc'] != 0 and (
            result['error'] is not None or result.get('stop')),
            'failed delivery must carry its real failure')
    require(before == tree_snapshot(root),
            'verification changed/read unstable input')
    statistical = delivery['statistical_diagnostic']

    # ------------------------------------------------ 四态 verdict(§7.7/S02)
    # 旧 v2 归档:数值链真实完成 + stored pair table strict PASS 保留,
    # 但 preclaim/claim 顺序、root 旁路、源码闭包与 producer/consumer
    # 绑定缺口使 governance_contract_pass=false —— 新 verifier 的
    # "evidence self-consistent" 不再自动输出 engineering_complete。
    numerical_path_complete = bool(
        result['status'] == 'complete'
        and result['engineering_path_complete'] is True
        and len(envelope_hashes) == 2
        and len(stats_recomputed) == 4)
    strict_all = [
        bool(v['strict_pass']) for k, v in (statistical or {}).items()
        if isinstance(v, dict) and 'strict_pass' in v]
    if len(strict_all) == 4:
        stored_table_strict_diagnostic = ('PASS' if all(strict_all)
                                          else 'FAIL')
    else:
        stored_table_strict_diagnostic = 'NOT_RUN'
    plan_format_layered = (
        isinstance(plan.get('admission_evidence'), dict)
        and 'namespace_unused' not in plan['runtime'])
    claim_doc = (read_json(root / 'claim.json')
                 if (root / 'claim.json').is_file() else None)
    claim_bound_to_plan = bool(
        claim_doc and claim_doc.get('plan_sha256') == plan['plan_sha256'])
    episode_identity_rebuildable = bool(
        episode_identity['full'] > 0
        and episode_identity['mismatch'] == 0
        and episode_identity['partial_legacy'] == 0)
    governance_flags = {
        'plan_format_layered': plan_format_layered,
        'claim_bound_to_plan': claim_bound_to_plan,
        'episode_identity_fully_rebuildable': episode_identity_rebuildable,
        'routing_matrix_binds_frozen_hash': bool(
            governance_routing['rows'] > 0
            and governance_routing['unbound'] == 0
            and governance_routing['legacy_rows'] == 0
            and governance_routing['hash_mismatch'] == 0
            and governance_routing['pass_false'] == 0),
    }
    governance_contract_pass = bool(
        numerical_path_complete and all(governance_flags.values()))
    return {
        'evidence_consistent': True,
        'engineering_complete': bool(
            numerical_path_complete and governance_contract_pass
            and not synthetic),
        'synthetic': synthetic,
        'status': result['status'],
        'plan_sha256': plan['plan_sha256'],
        'stage_reports': stage_reports,
        'envelope_hashes': envelope_hashes,
        'strict_recomputed_matches_sealed': {
            k: v['strict_pass_recomputed']
            for k, v in stats_recomputed.items()},
        'statistical_strict_pass': {
            k: bool(v['strict_pass'])
            for k, v in (statistical or {}).items()
            if isinstance(v, dict) and 'strict_pass' in v},
        'numerical_path_complete': numerical_path_complete,
        'stored_table_strict_diagnostic': stored_table_strict_diagnostic,
        'governance_contract_pass': governance_contract_pass,
        'governance_flags': governance_flags,
        'episode_identity_reload': episode_identity,
        'routing_audit': governance_routing,
        'formal_qualification_issued': False,
        'scope': CONTRACT,
    }


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run')
    p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('verify')
    p.add_argument('--root', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'verify':
            report = verify(args.root)
            print(canonical(report))
            return 0 if report['engineering_complete'] else 1
        rc = run(args.out)
        print(canonical({'status': 'run_finished', 'rc': rc,
                         'out': str(args.out)}))
        return rc
    except Exception as exc:
        print(canonical({'status': 'invocation_failed',
                         'error_type': type(exc).__name__,
                         'error': str(exc)[:2000]}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
