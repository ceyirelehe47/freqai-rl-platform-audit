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
                    predeclared_transform_df: Any) -> dict:
    """Fit the unified three-curriculum V2 exactly once, then freeze.

    记录 fit 调用;序列化完整 envelope;用原 load_envelope 重载;三层
    hash 前后对拍;预声明 fit 行 transform 逐位对拍;写冻结 checkpoint
    (引用初始 plan 摘要,不回填)。
    """
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
    require(manifest['n_pairs'] == 72 and manifest['n_episodes'] == 144,
            f'fit bank size {manifest["n_pairs"]} != 72 pairs')
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
                            handles: dict[str, Any]) -> list[Any]:
    """选中名单 -> fit records(A09:来源隔离校验)。"""
    selection = read_json(root / 'stages' / stage_name / 'selection.json')
    require(selection['quota_filled'] and selection['evaluation_not_started'],
            'fit requires a closed fit stage')
    stage = next(s for s in fixed_contract()['stages']
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
    require(len(records) == 72, 'fit bank must carry exactly 72 pairs')
    return records


# ----------------------------------------------------------- evaluation
def evaluate_split(root: Path, split: str, handles: dict[str, Any],
                   params_snapshot: dict, plan: dict,
                   ledger: Any) -> dict:
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
        role, v2, v2c13=True,
        expected_bundle_hash=frozen['hashes']['preprocessor_bundle_hash'])

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
        require(len(records) == 40,
                f'{family} eval corpus must hold 40 pairs')
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
    require(len(equiv_records) == 24,
            f'canonical subset must hold 24 pairs, got {len(equiv_records)}')
    equiv_bundle = require_eval_routing_r17(
        routing, eval_namespace, context=f'reference_equivalence_{split}',
        ledger=ledger)
    equiv_report = reference_equivalence_run_r17(
        equiv_records, equiv_bundle, pack, eval_namespace=eval_namespace,
        ledger=ledger,
        expected_bundle_hash=frozen['hashes']['preprocessor_bundle_hash'])
    write_reference_equivalence_artifacts_r17(
        eval_dir, equiv_report, stem='reference_equivalence')
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
def run(out_dir: Path) -> int:
    root = Path(out_dir)
    require(root.parent.is_dir(), 'output parent must already exist')
    root = root.parent.resolve(strict=True) / root.name
    root.mkdir(exist_ok=False)

    result = {'contract': CONTRACT, 'engineering_only': True,
              'status': 'error', 'rc': 3, 'error': None,
              'phase': 'init', 'engineering_path_complete': False,
              'statistical': None, 'formal_qualification_issued': False,
              'calibration_qualified': False}
    ledger = None
    handles: dict[str, Any] = {}
    try:
        sources = source_guard()
        params_snapshot = parameter_snapshot()
        from r17_v2_c13_profile import RELEASE_REPO_ROOT
        repo_root = RELEASE_REPO_ROOT
        ns_check = namespace_unused_evidence(repo_root)
        require(ns_check['namespaces_unused'],
                f'namespaces already consumed: {ns_check["hits"][:5]}')
        backend = RealBackend(params_snapshot)
        runtime = backend.describe()
        runtime['sources'] = sources
        runtime['namespace_unused'] = ns_check
        plan = make_plan(runtime)
        validate_plan(plan)

        # One-shot claim (S2/S3):second main experiment is refused even
        # with a fresh out dir or monitored run id.
        claim = claim_state()
        require(not claim['consumed'],
                f'generation claim already consumed: {claim}')
        consumed = consume_generation_claim(plan)
        new_json(root / 'plan.json', plan)
        new_json(root / 'params_snapshot.json', params_snapshot)
        new_json(root / 'claim.json', consumed)

        bundles: dict[str, dict[str, Any]] = {}
        contract = fixed_contract()
        for stage in contract['stages']:
            stage_name = stage['stage']
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
                records = _fit_records_from_stage(
                    root, stage_name, stage_handles)
                from rl_curriculum.curriculum261_r3_calibration import (
                    fit_matrix_from_records,
                )

                predeclared = fit_matrix_from_records(records[:8])
                split = stage['split']
                bundles[split] = fit_and_freeze(
                    root, split, records, params_snapshot, plan,
                    predeclared)
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
            split_out = evaluate_split(
                root, split, handles, params_snapshot, plan, ledger)
            for family in ('c1_opportunity', 'c3_cost'):
                stats[f'{family}_{split}'] = {
                    'strict_pass':
                        split_out['families'][family]['strict_pass'],
                    'conditions':
                        split_out['families'][family]['conditions']}
            result.setdefault('reference_equivalence', {})[split] = \
                split_out['reference_equivalence']
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
        'format': 'R17V2C13EngineeringDelivery-v1',
        'contract': CONTRACT,
        'baseline': BASELINE,
        'engineering_consumer_complete':
            bool(result['engineering_path_complete']),
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
def _cluster_stats(values: list[float]) -> dict:
    """纯算术 pair-cluster 统计(冷读复算;与 R4 cluster_stats 同口径)。"""
    n = len(values)
    if n == 0:
        return {'n': 0, 'mean': None, 'se': None}
    mean = sum(values) / n
    if n == 1:
        return {'n': 1, 'mean': mean, 'se': 0.0}
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    return {'n': n, 'mean': mean, 'se': var ** 0.5 / n ** 0.5}


def _recompute_strict(family_report: dict) -> dict:
    """从封存 pair 表重算 R5 strict 布尔(κ=1.5;不含 bootstrap CI)。"""
    kappa = 1.5
    rows = family_report['pair_table']['rows']
    policies = set()
    for row in rows:
        policies.update(row['returns'])
    baselines = [p for p in policies
                 if p not in ('reference', 'oracle')]
    ladder: dict[str, dict] = {}
    for rung in RUNGS:
        vals = [r['returns']['reference'] - r['returns']['always_flat']
                for r in rows if r['rung'] == rung]
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
        se = ((ladder[hi]['se'] ** 2 + ladder[lo]['se'] ** 2)
              if ladder[hi]['se'] is not None
              and ladder[lo]['se'] is not None else None)
        ok = bool(gap > 0 and se is not None and gap >= kappa * se)
        gaps_ok = gaps_ok and ok
        gap_detail[f'{hi}-{lo}'] = {'gap': gap, 'se': se, 'ok': ok}
    margins_ok = True
    margin_detail = {}
    for b in baselines:
        if b == 'always_flat':
            continue
        margin_detail[b] = {}
        for rung in RUNGS:
            vals = [r['returns']['reference'] - r['returns'][b]
                    for r in rows if r['rung'] == rung]
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
    return {'ordering_ok': ordering_ok, 'gaps': gap_detail,
            'gaps_ok': gaps_ok, 'd3_positive': d3_positive,
            'd3_mean_ge_kappa_se': d3_ge, 'margins': margin_detail,
            'margins_ok': margins_ok, 'pair_integrity_unity':
                integrity_unity, 'oracle_positive': oracle_positive,
            'strict_pass_recomputed': strict_pass}


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
    require(delivery['engineering_consumer_complete']
            is bool(result['engineering_path_complete']),
            'delivery/result engineering flag mismatch')
    require(delivery['calibration_qualified'] is False
            and delivery['formal_qualification_issued'] is False,
            'formal qualification must never be issued here')

    stage_reports = {}
    for stage in fixed_contract()['stages']:
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
    # delivery)。
    envelope_hashes = {}
    for split in ('main', 'validation'):
        frozen = read_json(root / 'bundles' / split
                           / 'frozen_checkpoint.json')
        envelope = read_json(root / 'bundles' / split / 'envelope.json')
        require(frozen['hashes'] == envelope['hashes'],
                f'{split} frozen checkpoint / envelope hashes mismatch')
        require(frozen['plan_sha256'] == plan['plan_sha256'],
                f'{split} frozen not bound to initial plan')
        require(frozen['namespace'] == FIT_NAMESPACES[split],
                f'{split} frozen namespace mismatch')
        manifest_doc = envelope['fit_manifest']
        require(manifest_doc['n_entries'] == 144,
                f'{split} fit manifest entries != 144')
        require(manifest_doc['namespace'] == FIT_NAMESPACES[split],
                f'{split} fit manifest namespace mismatch')
        families = {e['family'] for e in manifest_doc['entries']}
        require(families == {'c1_opportunity', 'c2_context', 'c3_cost'},
                f'{split} fit manifest not three-curriculum')
        rungs_seen = {e['rung'] for e in manifest_doc['entries']}
        require(rungs_seen == set(RUNGS),
                f'{split} fit manifest rungs incomplete')
        envelope_hashes[split] = envelope['hashes']

    # evaluations:统计代数复算 + strict 布尔对拍。
    stats_recomputed = {}
    for split in ('main', 'validation'):
        for family in ('c1_opportunity', 'c3_cost'):
            path = root / 'evaluations' / split / f'{family}_report.json'
            report = read_json(path)
            require(report['family_report']['corpus']
                    == EVAL_NAMESPACES[split],
                    'evaluation corpus/namespace mismatch')
            require(len(report['family_report']['pair_table']['rows'])
                    == 40, 'eval pair table must hold 40 pairs')
            recomputed = _recompute_strict(report['family_report'])
            require(recomputed['strict_pass_recomputed']
                    == bool(report['conditions']['pass']),
                    f'strict algebra mismatch: {family}/{split}')
            stats_recomputed[f'{family}_{split}'] = recomputed
        equiv = read_json(root / 'evaluations' / split
                          / 'reference_equivalence.json')
        require(equiv['eval_namespace'] == EVAL_NAMESPACES[split],
                'equivalence namespace mismatch')
        require(equiv['n_episodes'] == 48,
                'equivalence subset must hold 48 episodes per split')

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
        'engineering_complete': result['status'] == 'complete',
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
