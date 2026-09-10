#!/usr/bin/env python3
"""Read-only handoff of the accepted C3 engineering batch to calibration statistics.

This is NOT a scaled calibration, a new sample draw, or a qualification runner.
The RUN path calls existing R4/R5 statistical primitives. VERIFY is stdlib-only.
"""
from __future__ import annotations
import argparse
import hashlib
import math
from pathlib import Path
import shutil
import statistics
import sys

import r17_c3_reserve_batch as batch

CONTRACT = 'C3CalibrationConsumerBridge-v1-engineering'
BASELINE = '5607876b213af825d618868ba89cb0705cfdc472'
INPUT_RUN = 'c3reserve_v1_20260910T050655_93442'
INPUT_MANIFEST_BLOB = '0ef26c7edd2a3b41aac345a751304fb4df2b75bc'
POLICIES = tuple(batch.POLICIES)
BASELINES = ('always_flat', 'always_long', 'c3_cost_ignorant')
SPLITS = ('main', 'validation')
RUNGS = tuple(batch.RUNGS)
KAPPA = 1.5
BOOTSTRAP_N = 5000
BOOTSTRAP_SEED = 20260901
NOT_EVALUATED = ['V2 fit/transform/normalization', 'full-size calibration', 'C1', 'C2',
                 'supervised learnability', 'formal qualification', 'PPO']
need = batch.require
read = batch.read_json
new = batch.new_json
meta = batch.file_meta
snapshot = batch.tree_snapshot


def blob(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def contract() -> dict:
    return {'version': CONTRACT, 'engineering_only': True,
            'source_run': INPUT_RUN, 'source_manifest_git_blob': INPUT_MANIFEST_BLOB,
            'source_contract': batch.CONTRACT, 'input_mode': 'saved_raw_production_observation_evaluation',
            'pairs_per_split_rung': 2, 'splits': list(SPLITS), 'rungs': list(RUNGS),
            'policies': list(POLICIES), 'required_baselines': list(BASELINES),
            'pair_unit': 'mean(A,B), never treat A and B as independent clusters',
            'difficulty': 'reference_pair - always_flat_pair',
            'kappa': KAPPA, 'decision': 'strict main AND strict engineering validation; no pooled rescue',
            'bootstrap': {'resamples': BOOTSTRAP_N, 'seed': BOOTSTRAP_SEED,
                          'binding': False, 'cold_numerical_replay': False},
            'new_generation_permitted': False, 'normalization_fit_permitted': False,
            'formal_calibration_qualified': False, 'ppo_training_permitted': False}


def load_input(root: Path, *, test_mode: bool = False) -> tuple[dict, dict, dict]:
    root = root.resolve(strict=True)
    identity = meta(root / 'manifest.json')
    if not test_mode:
        need(blob((root / 'manifest.json').read_bytes()) == INPUT_MANIFEST_BLOB,
             'input is not the approved existing batch manifest')
    verified = batch.verify(root, allow_test_fixture=test_mode)
    need(verified.get('engineering_batch_complete') is True, 'input batch is incomplete')
    plan = read(root / 'plan.json')
    need(plan['runtime']['kind'] == ('test_fixture' if test_mode else 'real_c3'), 'input execution kind mismatch')
    selection = read(root / 'selection.json')
    lookup = {q.key: q for q in batch.requests()}
    rows = {s: [] for s in SPLITS}
    used = []
    for key in selection['selected']:
        need(key in lookup, 'undeclared selected request')
        q = lookup[key]
        proof = read(root / 'requests' / (key + '.json'))
        ev = read(root / 'evaluations' / (key + '.json'))
        batch.validate_evaluation(q, ev, proof)
        for row in ev['episodes']:
            # Explicit whitelist: pair IDs and *_trades are NOT returns.
            rows[q.split].append({k: row[k] for k in ('rung', 'pair', 'side', 'episode_hash') + POLICIES})
        used.append({'key': key, 'coordinate': q.coordinate,
                     'request': meta(root / 'requests' / (key + '.json')),
                     'evaluation': meta(root / 'evaluations' / (key + '.json'))})
    validate_rows(rows)
    need(identity == meta(root / 'manifest.json'), 'input manifest changed during validation')
    return rows, {'manifest': identity, 'plan_sha256': plan['plan_sha256'],
                  'selection': meta(root / 'selection.json'), 'selected': used}, verified


def validate_rows(rows: dict) -> None:
    need(set(rows) == set(SPLITS), 'split set mismatch')
    all_hashes = set()
    for split in SPLITS:
        need(len(rows[split]) == 16, 'expected 8 pairs / 16 episodes in each split')
        seen = set()
        for row in rows[split]:
            need(set(row) == set(('rung', 'pair', 'side', 'episode_hash') + POLICIES), 'unexpected/missing row fields')
            key = (row['rung'], row['pair'], row['side'])
            need(type(row['pair']) is int and row['pair'] in (0, 1, 2, 3), 'invalid pair coordinate')
            need(row['rung'] in RUNGS and row['side'] in ('A', 'B') and key not in seen, 'duplicate or invalid episode')
            seen.add(key)
            h = row['episode_hash']
            need(isinstance(h, str) and h.startswith('ce-') and h not in all_hashes, 'duplicate/invalid episode identity')
            all_hashes.add(h)
            for p in POLICIES:
                need(type(row[p]) in (float, int) and math.isfinite(row[p]), 'invalid policy return: ' + p)
            need(row['always_flat'] == 0.0, 'always-flat contract changed')
        for rung in RUNGS:
            ids = {i for r, i, s in seen if r == rung}
            need(len(ids) == 2 and all((rung, i, s) in seen for i in ids for s in ('A', 'B')), 'broken pair cluster')


def sign_counts(rows: dict) -> dict:
    result = {}
    for p in POLICIES:
        values = [r[p] for s in SPLITS for r in rows[s]]
        result[p] = {'n': len(values), 'negative': sum(v < 0 for v in values),
                     'positive': sum(v > 0 for v in values), 'zero': sum(v == 0 for v in values)}
    return {'policies': result, 'n_episodes': 32, 'n_policy_returns': 160,
            'totals': {k: sum(v[k] for v in result.values()) for k in ('negative', 'positive', 'zero')},
            'excluded_metadata': ['pair', '*_trades']}


def _close(a, b) -> bool:
    # This tolerance is ONLY numerical cross-checking. Gate comparisons below
    # use the authoritative reported values and exact >= / >, never this tolerance.
    return (type(a) in (float, int) and type(b) in (float, int)
            and math.isfinite(a) and math.isfinite(b)
            and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12))


def _stats(values) -> dict:
    need(len(values) >= 2, 'SE requires at least two pair clusters')
    sd = statistics.stdev(values)
    return {'n': len(values), 'mean': statistics.mean(values), 'sd': sd, 'se': sd / math.sqrt(len(values))}


def _check_stats(actual: dict, values: list[float], where: str) -> None:
    expected = _stats(values)
    need(actual.get('n') == expected['n'] and type(actual.get('n')) is int, where + ': cluster n mismatch')
    for k in ('mean', 'sd', 'se'):
        need(_close(actual.get(k), expected[k]), where + ': statistic mismatch: ' + k)
    ci = actual.get('bootstrap_ci', {})
    need(ci.get('n') == len(values) and ci.get('resamples') == BOOTSTRAP_N
         and ci.get('seed') == BOOTSTRAP_SEED, where + ': bootstrap metadata mismatch')
    need(_close(ci.get('mean'), expected['mean']), where + ': bootstrap mean mismatch')
    lo, hi = ci.get('ci_low'), ci.get('ci_high')
    need(type(lo) in (int, float) and type(hi) in (int, float)
         and math.isfinite(lo) and math.isfinite(hi) and min(values)-1e-12 <= lo <= hi <= max(values)+1e-12,
         where + ': bootstrap interval impossible')


def _strict_from_report(rep: dict) -> dict:
    """Independent stdlib check of frozen R5 booleans, not a new gate contract."""
    ladder = rep['difficulty_ladder']
    gaps = rep['adjacent_rung_gaps']
    margins = rep['fixed_baseline_margins']
    conditions = {
        'ordering_ok': all(ladder[a]['mean'] > ladder[b]['mean'] for a, b in zip(RUNGS, RUNGS[1:])),
        'gaps_ge_kappa_se': all(v['gap'] > 0 and v['gap'] >= KAPPA * v['se_pair_cluster'] for v in gaps.values()),
        'd3_positive': ladder['D3']['mean'] > 0,
        'd3_mean_ge_kappa_se': ladder['D3']['mean'] >= KAPPA * ladder['D3']['se'],
        'margins_ok': all(st['mean'] > 0 and st['mean'] >= KAPPA*st['se'] for per in margins.values() for st in per.values()),
        'pair_integrity_unity': rep['pair_integrity_pass_rate'] == 1.0,
        'oracle_positive': rep['oracle_positive_all_rungs'] is True}
    conditions['pass'] = all(conditions.values())
    return conditions


def check_analysis(rows: dict, doc: dict) -> dict:
    """Bind authority outputs to source episodes, pair statistics, and strict leaves."""
    validate_rows(rows)
    need(set(doc) == {'contract','mode','kappa','corpora','strict_both_pass','return_counts','not_evaluated'}, 'unexpected/missing analysis fields')
    need(doc.get('not_evaluated') == NOT_EVALUATED, 'scope/evaluation claims changed')
    need(doc.get('contract') == CONTRACT and doc.get('mode') == 'raw_saved_results', 'analysis mode/contract mismatch')
    need(doc.get('kappa') == KAPPA and set(doc.get('corpora', {})) == set(SPLITS), 'analysis split/kappa mismatch')
    statuses = {}
    for split in SPLITS:
        obj = doc['corpora'][split]
        rep, cond = obj['report'], obj['conditions']
        ns = batch.NAMESPACES[split]
        need(rep['family'] == batch.FAMILY and rep['corpus'] == ns, 'report family/corpus mismatch')
        table = rep['pair_table']
        need(table['corpus'] == ns and table['family'] == batch.FAMILY
             and table['n_pairs'] == 8 and len(table['rows']) == 8, 'pair table shape mismatch')
        source = {(r['rung'], r['pair'], r['side']): r for r in rows[split]}
        ids = sorted({(r['rung'], r['pair']) for r in rows[split]})
        need([(r['rung'], r['pair_index']) for r in table['rows']] == ids, 'pair table membership/order mismatch')
        for r in table['rows']:
            key = (r['rung'], r['pair_index'])
            need(r['corpus'] == ns and r['family'] == batch.FAMILY, 'table split identity mismatch')
            need(r['episode_hashes'] == {s: source[key+(s,)]['episode_hash'] for s in ('A', 'B')}, 'pair output identity mismatch')
            need(set(r['returns']) == set(POLICIES), 'metadata leaked into policy return table')
            for p in POLICIES:
                need(_close(r['returns'][p], (source[key+('A',)][p]+source[key+('B',)][p])/2), 'A/B mean mismatch')
        series = lambda rung, p: [r['returns'][p] for r in table['rows'] if r['rung'] == rung]
        need(set(rep['difficulty_ladder']) == set(RUNGS) and set(rep['fixed_baseline_margins']) == set(BASELINES), 'missing ladder/margin')
        for rung in RUNGS:
            refs = series(rung, 'reference'); flat = series(rung, 'always_flat')
            _check_stats(rep['difficulty_ladder'][rung], [a-b for a,b in zip(refs,flat)], split+'/'+rung)
            for p in BASELINES:
                need(set(rep['fixed_baseline_margins'][p]) == set(RUNGS), 'margin rung missing')
                _check_stats(rep['fixed_baseline_margins'][p][rung],
                             [a-b for a,b in zip(refs,series(rung,p))], split+'/'+p+'/'+rung)
        need(set(rep['adjacent_rung_gaps']) == {'D0-D1','D1-D2','D2-D3'}, 'adjacent gap set mismatch')
        for a,b in zip(RUNGS,RUNGS[1:]):
            gap=rep['adjacent_rung_gaps'][a+'-'+b]
            la,lb=rep['difficulty_ladder'][a],rep['difficulty_ladder'][b]
            need(_close(gap['gap'],la['mean']-lb['mean']) and _close(gap['se_pair_cluster'],math.hypot(la['se'],lb['se'])), 'gap mean/SE mismatch')
        need(rep['pair_integrity_pass_rate'] == 1.0, 'accepted input integrity was changed')
        oracle = all(statistics.mean(series(r,'oracle')) > 0 for r in RUNGS)
        need(rep['oracle_positive_all_rungs'] is oracle, 'oracle flag mismatch')
        expected = _strict_from_report(rep)
        need(cond.get('kappa') == KAPPA, 'strict gate kappa drift')
        for k,v in expected.items():
            need(cond.get(k) is v, 'strict gate leaf contradiction: '+split+'/'+k)
        # All numeric condition details must bind to the report, too.
        need(_close(cond.get('d3_mean'),rep['difficulty_ladder']['D3']['mean'])
             and _close(cond.get('d3_se'),rep['difficulty_ladder']['D3']['se']), 'condition D3 evidence mismatch')
        need(set(cond['fixed_baseline_margins']) == set(BASELINES), 'condition baseline set mismatch')
        for p in BASELINES:
            need(set(cond['fixed_baseline_margins'][p]) == set(RUNGS), 'condition margin missing')
            for r in RUNGS:
                x=cond['fixed_baseline_margins'][p][r]; st=rep['fixed_baseline_margins'][p][r]
                need(_close(x['mean'],st['mean']) and _close(x['se'],st['se'])
                     and _close(x['kappa_times_se'],KAPPA*st['se'])
                     and x['ok'] is (st['mean']>0 and st['mean']>=KAPPA*st['se'])
                     and x['bootstrap_ci']==st['bootstrap_ci'], 'condition margin binding mismatch')
        need(set(cond['gaps']) == set(rep['adjacent_rung_gaps']), 'condition gaps missing')
        for k,v in rep['adjacent_rung_gaps'].items():
            x=cond['gaps'][k]
            need(_close(x['gap'],v['gap']) and _close(x['se_pair_cluster'],v['se_pair_cluster'])
                 and _close(x['kappa_times_se'],KAPPA*v['se_pair_cluster'])
                 and x['ok'] is (v['gap']>0 and v['gap']>=KAPPA*v['se_pair_cluster']), 'condition gap binding mismatch')
        need(cond['d3_bootstrap_ci']==rep['difficulty_ladder']['D3']['bootstrap_ci'], 'condition D3 CI mismatch')
        statuses[split] = cond['pass']
    need(doc.get('strict_both_pass') is all(statuses.values()), 'split AND replaced or contradicted')
    need(doc.get('return_counts') == sign_counts(rows), 'policy-return counts mismatch')
    return statuses


def result_for(analysis: dict) -> dict:
    return {'contract': CONTRACT, 'engineering_consumer_complete': True,
            'statistical_diagnostic_pass': analysis['strict_both_pass'],
            'statistical_diagnostic_verdict': 'PASS' if analysis['strict_both_pass'] else 'FAIL',
            'split_pass': {s: analysis['corpora'][s]['conditions']['pass'] for s in SPLITS},
            'calibration_qualified': False, 'scaled_pipeline_validated': False,
            'preprocessor_fit_performed': False, 'new_pair_requests': 0,
            'new_evaluator_invocations': 0, 'formal_run_permitted': False,
            'status': 'complete', 'rc': 0,
            'scope': 'saved raw engineering data; 2 pairs/rung; not a full calibration or a model qualification'}


def validate_authority(identity: dict, *, test_mode=False) -> None:
    need(identity.get('kind') == ('test_fixture' if test_mode else 'repository_r4_r5_primitives'), 'authority kind mismatch')
    if not test_mode:
        from r17_c3_calibration_source_lock import SOURCE_SHA256
        need(identity.get('sources') == SOURCE_SHA256, 'calibration authority sources changed')


def execute(source: Path, out: Path, authority, *, test_mode: bool = False) -> dict:
    source = source.resolve(strict=True)
    # No normalization of symlink/.. before confirming the existing parent.
    need(out.name not in ('','.', '..') and out.parent.is_dir(), 'output parent must exist')
    dest = out.parent.resolve(strict=True) / out.name
    need(not dest.is_relative_to(source) and not source.is_relative_to(dest), 'output overlaps input')
    need(not dest.is_symlink() and not dest.exists(), 'output already exists')
    before = snapshot(source)
    rows, input_identity, source_verdict = load_input(source, test_mode=test_mode)
    identity = authority.describe()
    validate_authority(identity, test_mode=test_mode)
    dest.mkdir(exist_ok=False)
    try:
        shutil.copytree(source, dest/'input_batch')
        need(before == snapshot(dest/'input_batch') == snapshot(source), 'source/copy bytes changed')
        plan = {'contract': contract(), 'input_identity': input_identity,
                'source_batch_verdict': source_verdict, 'authority': identity,
                'kind': 'test_fixture' if test_mode else 'real_handoff'}
        new(dest/'plan.json', plan)
        new(dest/'episodes.json', rows)
        analysis = authority.analyze(rows)
        new(dest/'analysis.json', analysis)  # preserve even invalid authority response
        check_analysis(rows, analysis)
        need(identity == authority.describe(), 'authority drifted during calculation')
        need(before == snapshot(source) == snapshot(dest/'input_batch'), 'read-only source changed')
        result = result_for(analysis)
        new(dest/'result.json', result)
        new(dest/'manifest.json', {'contract':CONTRACT, 'files':snapshot(dest)})
        # Finished outputs must be independently consumable; result booleans alone are not enough.
        verify(dest, test_mode=test_mode)
        need(before == snapshot(source), 'source changed at publication boundary')
        return result
    except Exception as exc:
        try:
            new(dest/'failure.json', {'error':type(exc).__name__+': '+str(exc),
                                      'status':'error','rc':3, 'calibration_qualified':False})
        except Exception:
            pass  # preserve the primary exception and all existing files
        raise


def verify(root: Path, *, test_mode: bool = False) -> dict:
    root = root.resolve(strict=True)
    before = snapshot(root)
    manifest = read(root/'manifest.json')
    need(manifest.get('contract') == CONTRACT, 'wrong bridge manifest contract')
    actual = {k:v for k,v in before.items() if k!='manifest.json'}
    need(actual == manifest.get('files'), 'bridge evidence byte set mismatch')
    plan = read(root/'plan.json')
    need(plan.get('contract') == contract(), 'bridge contract drift')
    need(plan.get('kind') == ('test_fixture' if test_mode else 'real_handoff'), 'fixture cannot pass production verification')
    validate_authority(plan['authority'], test_mode=test_mode)
    rows, identity, source_verdict = load_input(root/'input_batch', test_mode=test_mode)
    need(plan['input_identity']==identity and plan['source_batch_verdict']==source_verdict, 'source binding mismatch')
    need(read(root/'episodes.json') == rows, 'episodes do not match selected source evaluations')
    allowed = {'plan.json','episodes.json','analysis.json','result.json'} | {'input_batch/'+k for k in snapshot(root/'input_batch')}
    need(set(actual)==allowed, 'unexpected/missing bridge artifact')
    analysis = read(root/'analysis.json')
    check_analysis(rows,analysis)
    result = read(root/'result.json')
    need(result == result_for(analysis), 'result promotion or contradiction')
    need(before == snapshot(root), 'bridge changed while verifying')
    return {'evidence_consistent':True, **result,
            'bridge_manifest':meta(root/'manifest.json')}


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('run');p.add_argument('--batch',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p=sub.add_parser('verify');p.add_argument('--root',type=Path,required=True)
    sub.add_parser('contract')
    args=parser.parse_args(argv)
    try:
        if args.cmd=='contract': doc=contract()
        elif args.cmd=='verify': doc=verify(args.root)
        else:
            from r17_c3_calibration_authority import RepositoryAuthority
            doc=execute(args.batch,args.out,RepositoryAuthority())
        print(batch.canonical(doc));return 0
    except Exception as exc:
        print(batch.canonical({'engineering_consumer_complete':False,'calibration_qualified':False,
                               'error':type(exc).__name__+': '+str(exc)}));return 3

if __name__=='__main__': raise SystemExit(main())
