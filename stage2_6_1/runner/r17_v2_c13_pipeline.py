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
    canonical, claim_state, consume_generation_claim, digest,
    engineering_pack, fixed_contract, make_plan, namespace_unused_evidence,
    parameter_snapshot, request_key, stage_requests, validate_plan)
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
    from r17_v2_c13_batch import ensure_imports as _ei

    _ei()
    import importlib

    from r17_v2_c13_source_lock import SOURCE_SHA256
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
            context=f'calibration_{split}_{family}', ledger=ledger)
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
        ledger=ledger)
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
def run(out_dir: Path, *, backend: Any = None,
        contract: dict | None = None) -> int:
    """执行完整工程链。backend/contract 仅测试合成链注入用(生产
    CLI 不传:固定 RealBackend + 权威 fixed_contract);注入产物强制
    标记 synthetic,verify 不授予工程完成。"""
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
        from r17_v2_c13_profile import RELEASE_REPO_ROOT
        repo_root = RELEASE_REPO_ROOT
        ns_check = namespace_unused_evidence(repo_root)
        require(ns_check['namespaces_unused'],
                f'namespaces already consumed or evidence unreadable: '
                f'{ns_check["hits"][:5]} {ns_check["unreadable_evidence"][:5]}')
        backend = RealBackend(params_snapshot) if backend is None \
            else backend
        runtime = backend.describe()
        runtime['sources'] = sources
        runtime['namespace_unused'] = ns_check
        result['phase'] = 'plan_assembly'
        plan = make_plan(runtime, contract)
        validate_plan(plan)

        # One-shot claim (S2/S3):second main experiment is refused even
        # with a fresh out dir or monitored run id.
        result['phase'] = 'claim'
        claim = claim_state()
        require(not claim['consumed'],
                f'generation claim already consumed: {claim}')
        consumed = consume_generation_claim(plan)
        new_json(root / 'plan.json', plan)
        new_json(root / 'params_snapshot.json', params_snapshot)
        new_json(root / 'claim.json', consumed)

        bundles: dict[str, dict[str, Any]] = {}
        contract = contract if contract is not None else fixed_contract()
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
        # episode CSV 与记录的 hash 对拍(选定数值输入不变)。
        for key, meta in stage_result.get('episode_artifacts',
                                          {}).items():
            for side in ('A', 'B'):
                path = root / 'episodes' / name / meta[side]['csv']
                require(file_meta(path)['sha256']
                        == meta[side]['csv_sha256'],
                        f'episode csv drift: {key}/{side}')

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
        envelope_hashes[split] = envelope['hashes']

    # evaluations:统计代数复算 + strict 布尔对拍(完整 run 才存在)。
    stats_recomputed = {}
    for split in ('main', 'validation'):
        edir = root / 'evaluations' / split
        if not edir.is_dir():
            require(not run_complete,
                    f'complete run missing evaluations: {split}')
            continue
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
            recomputed = _recompute_strict(report['family_report'])
            require(recomputed['strict_pass_recomputed']
                    == bool(report['conditions']['pass']),
                    f'strict algebra mismatch: {family}/{split}')
            stats_recomputed[f'{family}_{split}'] = recomputed
        equiv = _read_reference_equivalence(
            root / 'evaluations' / split / 'reference_equivalence.json')
        require(equiv['eval_namespace'] == EVAL_NAMESPACES[split],
                'equivalence namespace mismatch')
        require(equiv['n_episodes'] == 2 * plan['contract'].get(
                    'canonical_pairs_per_split', 24),
                'equivalence subset episodes != 2 x canonical pairs '
                'per split')

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
    return {
        'evidence_consistent': True,
        'engineering_complete': (result['status'] == 'complete'
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
