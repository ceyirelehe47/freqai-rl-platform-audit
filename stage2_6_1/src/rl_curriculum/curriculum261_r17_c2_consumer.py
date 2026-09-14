"""C2 report-consumption spine, engineering/synthetic only.

No generator, fit, evaluator, namespace-registration, claim or pack writer is
called here. The ordinary R17 run_design_stage entry point is deliberately NOT
used: it has production namespace/write side effects and binds matched cue
metrics. We reuse its numerical primitives and the actual R6 selector, while
binding cue metrics only to dedicated semantic reports.

This is not an episode-provenance verifier or a production authorization API.
Upstream cue bootstrap / global-K results are consumed, not re-executed.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
from typing import Any

FORMAT = 'R17C2PreparedReports-v1'
RESULT_FORMAT = 'R17C2ConsumerResult-v1'
CANDIDATES = ('historical', 'conservative', 'midpoint')
SPLITS = ('main', 'validation')
RUNGS = ('D0', 'D1', 'D2', 'D3')
N_OPTIONS = (10, 15, 20)
BASELINES = ('always_flat', 'always_long', 'c2_local_only')
SHARED_LEAVES = frozenset({
    'canonical_consistency', 'recall_lcb_ge_floor', 'noncue_fp_ucb_le_max',
    'n_unique_positive_cues_ge_min', 'coverage_complete',
    'per_event_k_complete', 'noise_replay_integrity', 'aggregate_recompute_ok',
})
AUDIT_LEAVES = frozenset({
    'mc_close_to_analytic', 'model_corpus_ok', 'validation_corpus_ok',
    'once_vs_attempts_consistent', 'aggregate_recompute_ok',
    'tail_mirror_bound_integrity_pass', 'global_k_audit_pass',
    'global_k_audit_not_indeterminate',
})
PRODUCERS = {
    'audit': 'rl_curriculum.curriculum261_r17_cue_contract.run_cue_contract_audit',
    'design_matched': 'rl_curriculum.curriculum261_r17_design._evaluate_candidate_matched_r17',
    'semantic': 'rl_curriculum.curriculum261_r17_calibration.run_c2_semantic_corpus_r17',
    'matched': 'rl_curriculum.curriculum261_r17_calibration.run_c2_matched_corpus_r17',
    'independent': 'rl_curriculum.curriculum261_r17_calibration.c2_independent_marginal_guard_r17',
}
DEPENDENCIES = (
    'rl_curriculum.curriculum261_r17_c2_launch_prep',
    'rl_curriculum.curriculum261_r6_design',
    'rl_curriculum.curriculum261_r6_param_pack',
    'rl_curriculum.curriculum261_r17_design',
    'rl_curriculum.curriculum261_r17_calibration',
    'rl_curriculum.curriculum261_r17_cue_contract',
    'rl_curriculum.curriculum261_r6_pairs',
    'rl_curriculum.curriculum261_r4_pairs',
    'rl_curriculum.curriculum261_r5_pairs',
)


class InputError(ValueError):
    """Malformed/contradictory evidence, distinct from a valid negative gate."""


def canonical(x: Any) -> str:
    return json.dumps(x, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def digest(x: Any) -> str:
    return hashlib.sha256(canonical(x).encode('utf-8')).hexdigest()


def _need(ok: bool, text: str) -> None:
    if not ok:
        raise InputError(text)


def _number(x: Any, name: str) -> float:
    _need(type(x) in (int, float) and math.isfinite(x), f'{name}: finite number required')
    return float(x)


def _probability(x: Any, name: str) -> float:
    value = _number(x, name)
    _need(0 <= value <= 1, name + ': probability outside [0,1]')
    return value


def _bool(x: Any, name: str) -> bool:
    _need(type(x) is bool, f'{name}: exact boolean required')
    return x


def _keys(value: Any, expected, name: str) -> None:
    _need(isinstance(value, dict) and set(value) == set(expected), f'{name}: exact key set required')


def _same(a: Any, b: Any, name: str) -> None:
    _need(canonical(a) == canonical(b), name + ': inconsistent value')


def _module(short: str):
    return importlib.import_module('rl_curriculum.' + short)


def fixed_design() -> dict:
    prep = _module('curriculum261_r17_c2_launch_prep')
    spec = copy.deepcopy(prep.FIXED_DESIGN_LITERAL)
    ladders = copy.deepcopy(prep.next_calibration_candidates())
    _keys(ladders, CANDIDATES, 'candidate ladders')
    _same(spec['n_options'], list(N_OPTIONS), 'n options')
    native_baselines = _module('curriculum261_r6_pairs').REQUIRED_BASELINES['c2_context']
    _same(list(native_baselines), list(BASELINES), 'native C2 fixed baselines')
    for cid in CANDIDATES:
        _keys(ladders[cid], RUNGS, cid)
        for axis in ('alpha_bps', 'wick_kappa'):
            _same([ladders[cid][r][axis] for r in RUNGS],
                  spec['candidates'][cid][axis], cid + '/' + axis)
    return {'literal': spec, 'ladders': ladders}


def wrap_report(kind: str, phase: str, split: str, candidate: str | None,
                namespace: str, payload: dict) -> dict:
    """Adapt native JSON-safe reports without relabeling them as production data."""
    _need(kind in PRODUCERS, 'unknown report kind')
    return {'kind': kind, 'phase': phase, 'split': split, 'candidate': candidate,
            'namespace': namespace, 'producer_interface': PRODUCERS[kind],
            'payload': copy.deepcopy(payload), 'payload_sha256': digest(payload)}


def _unwrap(node: dict, *, kind: str, phase: str, split: str,
            candidate: str | None) -> dict:
    for k, v in {'kind': kind, 'phase': phase, 'split': split,
                 'candidate': candidate, 'producer_interface': PRODUCERS[kind]}.items():
        _same(node[k], v, 'report ' + k)
    ns = node['namespace']
    _need(isinstance(ns, str) and ns.startswith('fixture_c2_') and len(ns) < 180,
          'only explicit fixture_c2_ report identities are accepted in v1')
    payload = node['payload']
    _need(isinstance(payload, dict), 'report payload must be a mapping')
    _same(node['payload_sha256'], digest(payload), 'report content digest')
    return payload


def _checks(doc: dict, names, name: str) -> bool:
    _keys(doc['checks'], names, name + ' checks')
    values = [_bool(doc['checks'][k], name + '/' + k) for k in sorted(names)]
    result = all(values)
    _same(_bool(doc['pass'], name + '/pass'), result, name + ' aggregate')
    return result


def audit_gate(node: dict) -> tuple[bool, float]:
    report = _unwrap(node, kind='audit', phase='audit', split='both', candidate=None)
    cue = _module('curriculum261_r17_cue_contract')
    _same(report['format'], 'cur261-r17-cue-contract-audit-v1', 'audit format')
    _same(report['audit_blocks_per_corpus'], cue.AUDIT_BLOCKS_PER_CORPUS, 'audit scale')
    _keys(report['audit_namespaces'], ('model', 'validation'), 'audit corpora')
    _need(len(set(report['audit_namespaces'].values())) == 2, 'audit corpora must be distinct')
    _need(report.get('formal_audit') is False, 'fixture audit cannot be formal')
    p = _number(report['p_contract'], 'p_contract')
    _need(0 <= p <= 1, 'p_contract outside probability range')
    floor = cue.recall_floor(p)
    _same(report['noninferiority']['recall_floor'], floor, 'recall floor')
    ok = _checks(report, AUDIT_LEAVES, 'audit')
    _same(report['checks']['global_k_audit_pass'],
          _bool(report['global_k_audit']['pass'], 'global K pass'), 'global K linkage')
    _same(report['checks']['global_k_audit_not_indeterminate'],
          report['global_k_audit']['verdict'] != 'INDETERMINATE', 'global K indeterminate')
    _same(report['checks']['tail_mirror_bound_integrity_pass'],
          _bool(report['tail_mirror_bound_integrity']['pass'], 'tail pass'), 'tail linkage')
    return ok, floor


def semantic_gate(node: dict, phase: str, split: str, cid: str, floor: float) -> dict:
    report = _unwrap(node, kind='semantic', phase=phase, split=split, candidate=cid)
    cue = _module('curriculum261_r17_cue_contract')
    _same(report['format'], 'cur261-r17-semantic-corpus-v1', 'semantic format')
    _same(report['namespace'], node['namespace'], 'semantic namespace')
    _same(report['ladder'], cid, 'semantic candidate')
    _same(report['n_blocks'], 160, 'dedicated scale')
    _same(report['semantic_blocks_per_corpus_expected'], 160, 'dedicated expected scale')
    _same(report['n_semantic_episodes'], 1280, 'dedicated episode declaration')
    shared, cand = report['shared'], report['candidate']
    _same(shared['n_blocks'], 160, 'shared scale')
    _same(shared['cluster_unit'], 'matched_block', 'shared cluster')
    _same(shared['canonical'], 'D0/A', 'shared canonical')
    _same(shared['recall_floor'], floor, 'semantic recall floor')
    _same(shared['min_unique_positive_cues'], cue.MIN_UNIQUE_POSITIVE_CUES, 'unique cue minimum')
    shared_ok = _checks(shared, SHARED_LEAVES, 'dedicated shared')
    _same(shared['checks']['recall_lcb_ge_floor'],
          _probability(shared['recall']['bound'], 'recall LCB') >= floor, 'recall leaf')
    _same(shared['checks']['noncue_fp_ucb_le_max'],
          _probability(shared['noncue_false_positive']['bound'], 'noncue UCB') <= cue.C2_NON_CUE_FALSE_POSITIVE_MAX,
          'noncue leaf')
    _need(type(shared['n_unique_positive_cues']) is int and shared['n_unique_positive_cues'] >= 0,
          'positive cue count must be a nonnegative integer')
    _same(shared['checks']['n_unique_positive_cues_ge_min'],
          _number(shared['n_unique_positive_cues'], 'positive count') >= cue.MIN_UNIQUE_POSITIVE_CUES,
          'coverage leaf')
    _same(cand['candidate'], cid, 'dedicated candidate identity')
    _same(cand['cluster_unit'], 'matched_block', 'candidate cluster')
    _keys(cand['per_rung'], RUNGS, 'candidate rungs')
    all_rungs = []
    for rung in RUNGS:
        rs = cand['per_rung'][rung]
        _keys(rs['sides'], ('A', 'B'), 'candidate sides')
        sides = []
        for side in ('A', 'B'):
            value = rs['sides'][side]
            precision, false_cue = value['cue_precision'], value['payoff_false_cue']
            _same(precision['min'], cue.C2_CUE_PRECISION_MIN, 'precision threshold')
            _same(false_cue['max'], cue.C2_PAYOFF_BAR_FALSE_CUE_MAX, 'false cue threshold')
            cp = _probability(precision['bound'], 'precision bound') >= cue.C2_CUE_PRECISION_MIN
            fc = _probability(false_cue['bound'], 'payoff bound') <= cue.C2_PAYOFF_BAR_FALSE_CUE_MAX
            _same(_bool(precision['pass'], 'precision pass'), cp, 'precision leaf')
            _same(_bool(false_cue['pass'], 'payoff pass'), fc, 'payoff leaf')
            _same(_bool(value['pass'], 'side pass'), cp and fc, 'side aggregate')
            sides.append(cp and fc)
        _same(_bool(rs['pass'], 'rung pass'), all(sides), 'rung aggregate')
        all_rungs.append(all(sides))
    _same(_bool(cand['pass'], 'candidate cue pass'), all(all_rungs), 'candidate aggregate')
    _same(_bool(report['pass'], 'semantic pass'), shared_ok and all(all_rungs), 'semantic aggregate')
    return {'pass': report['pass'], 'shared_pass': shared_ok,
            'candidate': copy.deepcopy(cand), 'source_sha256': node['payload_sha256'],
            'namespace': node['namespace']}


def block_table_checked(table: dict, namespace: str, expected_n: int) -> dict:
    """Do not trust duplicated difficulty/margin/gap columns or implicit rows."""
    _same(table['corpus'], namespace, 'block corpus')
    _same(table['family'], 'c2_context', 'block family')
    _same(table['n_blocks'], expected_n, 'block count')
    _need(type(expected_n) is int and expected_n >= 2, 'at least two blocks required')
    rows = table['rows']
    _need(isinstance(rows, list) and len(rows) == expected_n, 'block row count mismatch')
    seen = set()
    for row in rows:
        i = row['block_index']
        _need(type(i) is int and 0 <= i < expected_n and i not in seen, 'duplicate/foreign block index')
        seen.add(i)
        _same(row['corpus'], namespace, 'row corpus')
        _same(row['family'], 'c2_context', 'row family')
        _bool(row['cross_rung_integrity_pass'], 'cross-rung integrity')
        _bool(row['pair_integrity_all_pass'], 'pair integrity')
        _keys(row['pair_metrics'], RUNGS, 'block rungs')
        for r in RUNGS:
            pm = row['pair_metrics'][r]
            _need(set(pm['returns']) >= set(BASELINES) | {'reference', 'oracle'}, 'fixed baseline missing')
            ref = _number(pm['returns']['reference'], 'reference')
            for name in (*BASELINES, 'oracle'):
                _number(pm['returns'][name], name)
            _same(pm['difficulty'], ref - pm['returns']['always_flat'], 'difficulty definition')
            _need(set(pm['margins']) >= set(BASELINES), 'baseline margins missing')
            for b in BASELINES:
                _same(pm['margins'][b], ref - pm['returns'][b], 'margin definition')
        expected_gaps = {f'{hi}-{lo}': row['pair_metrics'][hi]['difficulty'] -
                         row['pair_metrics'][lo]['difficulty']
                         for hi, lo in zip(RUNGS[:-1], RUNGS[1:])}
        _same(row['gaps'], expected_gaps, 'matched gap definition')
    _same(sorted(seen), list(range(expected_n)), 'complete blocks')
    return copy.deepcopy(table)


def design_statistics(table: dict) -> dict:
    """Assemble R17 design tests using original R4/R6 primitives/constants.

    R6 simulation runs at its original defaults. No resized bootstrap, pooled
    rescue or independent-rung gap-SE substitution is available here.
    """
    d = _module('curriculum261_r17_design')
    p = _module('curriculum261_r6_pairs')
    r4 = _module('curriculum261_r4_pairs')
    per_n = {}
    for n in N_OPTIONS:
        gaps = {}
        for hi, lo in zip(RUNGS[:-1], RUNGS[1:]):
            series = p.block_gap_series(table, hi, lo)
            st = r4.cluster_stats(series)
            se = d._se_at_n(st['sd'], n)
            rate = sum(float(v) > 0 for v in series) / len(series)
            gaps[f'{hi}-{lo}'] = {'mean': st['mean'], 'sd_blockwise': st['sd'],
                'se_at_n': se, 'ratio': st['mean'] / se if se else None,
                'positive_gap_block_rate': rate,
                'ok': bool(st['mean'] > 0 and st['mean'] >= d.DESIGN_TARGET_GAP_FACTOR * se
                           and rate >= p.R6_POSITIVE_GAP_RATE_MIN)}
        ds = r4.cluster_stats(p.block_difficulty_series(table, 'D3'))
        se3 = d._se_at_n(ds['sd'], n)
        d3ok = bool(ds['mean'] > 0 and ds['mean'] >= d.DESIGN_TARGET_D3_FACTOR * se3)
        margins = {}
        for b in ('always_long', 'c2_local_only'):
            for r in RUNGS:
                st = r4.cluster_stats(p.block_margin_series(table, r, b))
                ok = st['mean'] > 0 and (r not in ('D2', 'D3') or
                     st['mean'] >= d.DESIGN_TARGET_MARGIN_FACTOR * d._se_at_n(st['sd'], n))
                margins[b + '_' + r] = {'mean': st['mean'], 'ok': bool(ok),
                                        'requires_factor_se': r in ('D2', 'D3')}
        sim = p.simulate_formal_gate_pass_r6_matched(table, n_formal_blocks=n)
        means = [r4.cluster_stats(p.block_difficulty_series(table, r))['mean'] for r in RUNGS]
        reasons = {'ordering_ok': bool(means[0] > means[1] > means[2] > means[3]),
            'gaps_ge_3x_se_and_positive_rate': all(x['ok'] for x in gaps.values()),
            'd3_ge_2p5x_se': d3ok,
            'margins_positive_and_d2_d3_ge_2p5x_se': all(x['ok'] for x in margins.values()),
            'formal_gate_probability_ge_0p90': bool(sim['gate_pass_probability'] >= d.DESIGN_TARGET_GATE_PROB)}
        per_n[str(n)] = {'n_formal_blocks': n, 'gap_checks': gaps,
            'd3_check': {'mean': ds['mean'], 'se_at_n': se3,
                         'ratio': ds['mean'] / se3 if se3 else None, 'ok': d3ok},
            'margin_checks': margins, 'formal_gate_simulation': sim,
            'reasons': reasons, 'qualified': all(reasons.values())}
    return per_n


def _density(gates: dict) -> bool:
    _keys(gates, RUNGS, 'density rungs')
    gate_fn = _module('curriculum261_r5_pairs').density_gate_r5
    for rung in RUNGS:
        _need(_number(gates[rung]['median_reference_trades_per_episode'], 'median trades') >= 0,
              'median trades must not be negative')
        _probability(gates[rung]['reference_long_label_rate'], 'long label rate')
        actual = gate_fn(gates[rung])
        _same(_bool(gates[rung]['pass'], 'density pass'), actual['pass'], 'density gate')
    return all(gates[r]['pass'] for r in RUNGS)


def _structure(report: dict) -> tuple[bool, bool]:
    s = report['semantics']
    return (_bool(s['local_cue_independence']['pass'], 'local cue independence'),
            _bool(s['context_observability']['pass'], 'context observability'))


def independent_gate(node: dict, phase: str, split: str, cid: str) -> dict:
    data = _unwrap(node, kind='independent', phase=phase, split=split, candidate=cid)
    report, conditions = data['report'], data['conditions']
    _same(conditions['namespace'], node['namespace'], 'independent namespace')
    _same(conditions['pairs_per_rung'], 20, 'independent pair scale')
    table = report['pair_table']
    _same(table['corpus'], node['namespace'], 'independent corpus')
    _same(table['family'], 'c2_context', 'independent family')
    _same(table['n_pairs'], 80, 'independent pair count')
    _need(len(table['rows']) == 80, 'independent rows missing')
    r4 = _module('curriculum261_r4_pairs')
    seen = set()
    for row in table['rows']:
        key = (row['rung'], row['pair_index'])
        _need(key[0] in RUNGS and type(key[1]) is int and 0 <= key[1] < 20 and key not in seen,
              'independent coordinate missing/duplicate/foreign')
        seen.add(key)
        _same(row['corpus'], node['namespace'], 'pair row corpus')
        _same(row['family'], 'c2_context', 'pair row family')
        _keys(row['episode_hashes'], ('A', 'B'), 'independent A/B members')
        _need(all(isinstance(v, str) and v for v in row['episode_hashes'].values()), 'empty episode identity')
        for name in (*BASELINES, 'reference', 'oracle'):
            _number(row['returns'][name], 'independent ' + name)
    # R4 calculations; no optional baseline can become a new binding leaf.
    rebuilt = copy.deepcopy(report)
    rebuilt['difficulty_ladder'] = {r: r4.cluster_stats(r4.difficulty_series(table, r)) for r in RUNGS}
    rebuilt['fixed_baseline_margins'] = {
        b: {r: r4.cluster_stats(r4.margin_series(table, r, b)) for r in RUNGS} for b in BASELINES}
    rebuilt['oracle_positive_all_rungs'] = all(
        r4.cluster_stats(r4.table_series(table, r, 'oracle'))['mean'] > 0 for r in RUNGS)
    _number(report['pair_integrity_pass_rate'], 'pair integrity rate')
    _need(0 <= report['pair_integrity_pass_rate'] <= 1, 'pair integrity rate range')
    density = _density(conditions['density_gates'])
    base = _module('curriculum261_r6_pairs').c2_marginal_guard_conditions(
        rebuilt, density={'pass': density}, semantics=None)
    local, context = _structure(conditions)
    cue = conditions['cue_semantics']['structural']
    _keys(cue['checks'], ('canonical_consistency',), 'independent structural leaves')
    canonical_ok = _checks(cue, ('canonical_consistency',), 'independent canonical')
    # Intentionally NOT cue_point_diagnostics.pass or legacy point recall.
    leaves = {k: _bool(base[k], k) for k in (
        'mean_ordering_ok', 'd3_mean_positive', 'fixed_baseline_means_positive',
        'integrity_unity', 'oracle_positive', 'density_pass')}
    leaves.update(local_cue_independence=local, context_observability=context,
                  independent_cue_canonical_consistency=canonical_ok)
    return {'pass': all(leaves.values()), 'checks': leaves, 'statistical': base,
            'cue_point_metrics_binding': False, 'source_sha256': node['payload_sha256']}


def select_design(packet: dict, trace: list) -> dict:
    d = _module('curriculum261_r17_design')
    p = _module('curriculum261_r6_param_pack')
    selector = _module('curriculum261_r6_design').mechanical_selection
    frozen = fixed_design()
    _same(packet['fixed_design'], frozen, 'frozen design')
    trace.append('audit')
    audit_ok, floor = audit_gate(packet['audit'])
    if not audit_ok:
        return {'status': 'NO_SELECTION', 'reason': 'audit_gate_failed',
                'selection': None, 'audit_pass': False, 'floor': floor}
    design = packet['design']
    _keys(design['matched'], CANDIDATES, 'matched candidates')
    _keys(design['semantic'], CANDIDATES, 'semantic candidates')
    dedicated = {}
    all_shared = True
    for cid in CANDIDATES:
        _keys(design['semantic'][cid], SPLITS, 'semantic splits')
        dedicated[cid] = {}
        namespaces = []
        for split in SPLITS:
            trace.append(f'design/dedicated/{cid}/{split}')
            dedicated[cid][split] = semantic_gate(design['semantic'][cid][split], 'design', split, cid, floor)
            namespaces.append(dedicated[cid][split]['namespace'])
            all_shared = all_shared and dedicated[cid][split]['shared_pass']
        _need(len(set(namespaces)) == 2, 'semantic splits share namespace')
    if not all_shared:
        return {'status': 'NO_SELECTION', 'reason': 'dedicated_shared_gate_failed',
                'selection': None, 'audit_pass': True, 'floor': floor, 'dedicated': dedicated}
    table, corpora_all = {}, {}
    for cid in CANDIDATES:
        _keys(design['matched'][cid], SPLITS, 'matched splits')
        corpora = []
        namespaces = []
        for split in SPLITS:
            trace.append(f'design/matched/{cid}/{split}')
            node = design['matched'][cid][split]
            raw = _unwrap(node, kind='design_matched', phase='design', split=split, candidate=cid)
            _same(raw['candidate'], cid, 'design report candidate')
            _same(raw['corpus'], node['namespace'], 'design corpus')
            _same(raw['n_blocks'], d.DESIGN_BLOCKS_PER_CORPUS_R17, 'design block scale')
            _need(node['namespace'] != dedicated[cid][split]['namespace'], 'dedicated source replaced by matched')
            namespaces.append(node['namespace'])
            block = block_table_checked(raw['block_table'], node['namespace'], d.DESIGN_BLOCKS_PER_CORPUS_R17)
            view = copy.deepcopy(raw)
            view['block_table'] = block
            view['per_formal_block_count'] = design_statistics(block)
            local, context = _structure(raw)
            view['semantics_pass'] = local and context and dedicated[cid][split]['pass']
            view['density_pass'] = _density(raw['density_gates'])
            view['pair_integrity_unity'] = all(x['pair_integrity_all_pass'] and
                                              x['cross_rung_integrity_pass'] for x in block['rows'])
            view['oracle_positive'] = all(sum(x['pair_metrics'][r]['returns']['oracle']
                                                for x in block['rows']) > 0 for r in RUNGS)
            # The R17 scorer reads this key. Route it to dedicated data, not
            # the matched producer's optional precision/payoff diagnostics.
            view['semantics']['candidate_cue_semantics_r17_cluster_aware'] = copy.deepcopy(
                dedicated[cid][split]['candidate'])
            corpora.append(view)
        _need(len(set(namespaces)) == 2, 'matched splits share namespace')
        qualified = {str(n): bool(d._qualified_at_n(corpora, n)) for n in N_OPTIONS}
        table[cid] = {'qualified_by_block_count': qualified,
            'maximin_score_by_qualified_n': {str(n): d._maximin_score_r17(corpora, n)
                                             for n in N_OPTIONS if qualified[str(n)]},
            'param_distance_from_historical': p.ladder_distance_from_historical(frozen['ladders'][cid])}
        corpora_all[cid] = corpora
    trace.append('design/mechanical_selection')
    selected_id, selected_n = selector(table)
    result = {'audit_pass': True, 'floor': floor, 'candidate_results': table,
              'recomputed_design_corpora': corpora_all, 'dedicated': dedicated,
              'selection': None, 'status': 'NO_SELECTION', 'reason': 'no_qualified_combination'}
    if selected_id is None:
        _need(selected_n is None, 'selector returned partial selection')
        return result
    _need(selected_id in CANDIDATES and type(selected_n) is int and selected_n in N_OPTIONS,
          'selector returned undeclared combination')
    trace.append('design/selected_independent')
    marginal = independent_gate(design['independent'][selected_id], 'design', 'both', selected_id)
    result.update(status='SELECTED' if marginal['pass'] else 'NO_SELECTION',
                  reason='selected' if marginal['pass'] else 'design_independent_failed',
                  independent=marginal,
                  mechanical_choice={'candidate_id': selected_id, 'n_blocks': selected_n})
    if marginal['pass']:
        result['selection'] = {'candidate_id': selected_id, 'n_blocks': selected_n,
                               'ladder': frozen['ladders'][selected_id],
                               'formal_pack_created': False, 'synthetic': True}
    return result


def calibration_split(data: dict, split: str, selection: dict, floor: float) -> dict:
    cid, n = selection['candidate_id'], selection['n_blocks']
    node = data['matched']
    raw = _unwrap(node, kind='matched', phase='calibration', split=split, candidate=cid)
    _same(raw['seed_namespace'], node['namespace'], 'calibration namespace')
    _same(raw['n_blocks'], n, 'selected calibration n')
    block = block_table_checked(raw['block_table'], node['namespace'], n)
    actual = _module('curriculum261_r6_pairs').c2_matched_conditions(block)
    local, context = _structure(data['matched_conditions'])
    density = _density(data['matched_conditions']['density_gates'])
    checks = {'statistical_block_conditions': actual['pass'],
              'shared_tape_cross_rung': all(r['cross_rung_integrity_pass'] for r in block['rows']),
              'block_pair_integrity': all(r['pair_integrity_all_pass'] for r in block['rows']),
              'density_pass': density, 'local_cue_independence': local,
              'context_observability': context}
    semantic = semantic_gate(data['semantic'], 'calibration', split, cid, floor)
    marginal = independent_gate(data['independent'], 'calibration', split, cid)
    _need(len({node['namespace'], semantic['namespace'], data['independent']['namespace']}) == 3,
          'calibration corpus roles must be disjoint')
    return {'pass': all(checks.values()) and semantic['pass'] and marginal['pass'],
            'matched': {'pass': all(checks.values()), 'checks': checks, 'statistical': actual},
            'dedicated': semantic, 'independent': marginal,
            'matched_source_sha256': node['payload_sha256']}


def consume(packet: dict) -> dict:
    """Complete synthetic report->selection->two-split decision. Never launches data."""
    # Clone to isolate caller aliases and reject JSON nonfinite values up front.
    try:
        packet = json.loads(canonical(packet))
        _same(packet['format'], FORMAT, 'input format')
        _need(packet['synthetic'] is True, 'production execution is not authorized')
        _need(packet['upstream_episode_provenance_verified'] is False,
              'report fixture cannot claim rebuilt episode provenance')
        trace = []
        result = {'format': RESULT_FORMAT, 'synthetic': True,
            'input_sha256': digest(packet), 'engineering_complete': False,
            'business_statistics': 'NOT_RUN', 'formal_qualification': 'NOT_ISSUED',
            'launch_authorized': False, 'upstream_episode_provenance_rebuilt': False,
            'cue_bootstrap_and_global_k_reexecuted': False,
            'formal_parameter_pack_created': False, 'trace': trace}
        design = select_design(packet, trace)
        result['design'] = design
        if design['selection'] is None:
            result.update(engineering_complete=True, terminal_stage='design',
                          fixture_gate_outcome='FAIL', calibration={'status': 'NOT_RUN'})
            return result
        selection = design['selection']
        cid = selection['candidate_id']
        _keys(packet['calibration'][cid], SPLITS, 'calibration splits')
        outcomes, namespace_sets = {}, []
        # Always evaluate both supplied split reports; never pool or use one to
        # rescue the other. Data is not generated here and selection is frozen.
        for split in SPLITS:
            trace.append('calibration/' + split)
            data = packet['calibration'][cid][split]
            outcomes[split] = calibration_split(data, split, selection, design['floor'])
            namespace_sets.append({data[k]['namespace'] for k in ('matched', 'semantic', 'independent')})
        _need(not namespace_sets[0] & namespace_sets[1], 'main/validation corpus reuse')
        joint = all(outcomes[s]['pass'] for s in SPLITS)
        result.update(engineering_complete=True, terminal_stage='calibration',
                      fixture_gate_outcome='PASS' if joint else 'FAIL',
                      calibration={'status': 'COMPLETE', 'splits': outcomes, 'strict_and': joint})
        return result
    except InputError:
        raise
    except (KeyError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise InputError(f'malformed prepared evidence: {type(exc).__name__}: {exc}') from exc
