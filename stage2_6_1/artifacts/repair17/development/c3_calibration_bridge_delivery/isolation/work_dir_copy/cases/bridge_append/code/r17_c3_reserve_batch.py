#!/usr/bin/env python3
"""Fixed C3 finite-reserve ENGINEERING batch. No formal or training entrypoint.

Generation completes and membership is sealed before ANY evaluator invocation.
Only evidenced C3 structural exhaustion permits another predeclared coordinate.
The CLI verifier is read-only and prints JSON to stdout: no arbitrary receipt path.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
from typing import Any

CONTRACT = 'C3FiniteReserveBatch-v1-engineering'
BASELINE = '08b3f4a2b9c53529a7de1507bf1a70ae9b771b90'
FAMILY = 'c3_cost'
RUNGS = ('D0', 'D1', 'D2', 'D3')
NAMESPACES = {'main': 'c3_reserve_main_eng_r17',
              'validation': 'c3_reserve_validation_eng_r17'}
# Engineering validation is NOT a frozen holdout.
PARAMS = {
    'D0': dict(alpha_bps=70.0, payoff_bars=1, vol_bps=18.0, cue_rate=.200,
               mixture=[.60, .25, .15], distractor_rate=.015),
    'D1': dict(alpha_bps=62.0, payoff_bars=1, vol_bps=18.0, cue_rate=.210,
               mixture=[.46, .32, .22], distractor_rate=.025),
    'D2': dict(alpha_bps=54.0, payoff_bars=1, vol_bps=18.0, cue_rate=.220,
               mixture=[.34, .35, .31], distractor_rate=.040),
    'D3': dict(alpha_bps=46.0, payoff_bars=1, vol_bps=18.0, cue_rate=.230,
               mixture=[.14, .36, .50], distractor_rate=.060),
}
DEFAULTS = {'margin': 1.10, 'any_signal_s': .22}
CODES = ('too_few_signals', 'too_few_above_cost_signals',
         'too_few_below_cost_signals', 'missing_signal_directions', 'too_few_distractors')
ALLOWED_REJECTIONS = frozenset(f'{side}:{code}' for side in ('A', 'B', 'pair') for code in CODES)
POLICIES = ('always_flat', 'always_long', 'c3_cost_ignorant', 'reference', 'oracle')


class EvidenceError(ValueError):
    pass


def require(ok: bool, message: str) -> None:
    if not ok:
        raise EvidenceError(message)


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode('utf-8')).hexdigest()


def envelope_digest(env: dict, call: bool = False) -> str:
    # Persisted JSON subset of the authoritative generation-envelope contract.
    return ('r11call-' if call else 'r11env-') + digest(
        {k: v for k, v in env.items() if k not in ('digest', 'runtime')})


def file_meta(path: Path) -> dict:
    before = path.stat()
    h = hashlib.sha256()
    n = 0
    with path.open('rb') as f:
        while chunk := f.read(1 << 20):
            h.update(chunk); n += len(chunk)
    after = path.stat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    require(identity(before) == identity(after) and n == after.st_size, 'file changed while reading')
    return {'bytes': n, 'sha256': h.hexdigest()}


def read_json(path: Path) -> Any:
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, f'duplicate JSON key: {k}')
            result[k] = v
        return result
    def invalid(value):
        raise EvidenceError(f'nonfinite JSON value: {value}')
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique, parse_constant=invalid)


def new_json(path: Path, value: Any) -> None:
    """Internal, create-only names under our newly owned run tree; no overwrite."""
    payload = (canonical(value) + '\n').encode('utf-8')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + path.name + '.' + secrets.token_hex(12) + '.tmp')
    owned = False
    try:
        with tmp.open('xb') as f:
            owned = True
            f.write(payload); f.flush(); os.fsync(f.fileno())
        os.link(tmp, path)
    finally:
        if owned:
            tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class Request:
    split: str
    rung: str
    index: int

    @property
    def key(self) -> str:
        return f'{self.split}_{self.rung}_p{self.index}'

    @property
    def coordinate(self) -> dict:
        return {'namespace': NAMESPACES[self.split], 'family': FAMILY,
                'rung': self.rung, 'pair_index': self.index}

    @property
    def tier(self) -> str:
        return 'primary' if self.index < 2 else 'reserve'


def requests() -> list[Request]:
    return [Request(s, r, i) for s in NAMESPACES for r in RUNGS for i in range(4)]


def fixed_contract() -> dict:
    return {'version': CONTRACT, 'engineering_only': True,
            'purpose': 'engineering development, NOT calibration/holdout/qualification/training',
            'family': FAMILY, 'namespaces': NAMESPACES, 'rungs': list(RUNGS),
            'quota_per_stratum': 2, 'primary_indices': [0, 1], 'reserve_indices': [2, 3],
            'max_pair_requests': 32, 'max_attempts_per_pair': 5, 'max_attempt_envelopes': 160,
            'target_pairs': 16, 'selection_rule': 'primary_order_then_reserve_order_until_quota',
            'generation_before_evaluation': True, 'abort_batch_on_exhaustion': True,
            'allowed_rejection_reasons': sorted(ALLOWED_REJECTIONS),
            'rung_params': PARAMS, 'reference_defaults': DEFAULTS}


def make_plan(runtime: dict) -> dict:
    contract = fixed_contract()
    plan = {'contract': contract, 'contract_sha256': digest(contract),
            'baseline': BASELINE, 'runtime': runtime,
            'requests': [{'key': q.key, 'tier': q.tier, 'split': q.split, **q.coordinate}
                         for q in requests()]}
    plan['plan_sha256'] = digest(plan)
    return json.loads(canonical(plan))


def validate_plan(plan: dict) -> None:
    require(plan['contract'] == fixed_contract(), 'contract differs from authorized fixed engineering plan')
    expected = make_plan(plan['runtime'])
    require(plan == expected, 'plan identity/request list mismatch')
    require(plan['runtime']['kind'] in ('real_c3', 'test_fixture'), 'unknown backend kind')
    require(isinstance(plan['runtime']['generator'], dict) and bool(plan['runtime']['generator']),
            'missing frozen generator identity')
    if plan['runtime']['kind'] == 'real_c3':
        from r17_c3_reserve_source_lock import SOURCE_SHA256
        sources = plan['runtime'].get('sources', {})
        require(set(sources) == set(SOURCE_SHA256) and all(
            sources[n].get('sha256') == h for n, h in SOURCE_SHA256.items()),
            'execution sources do not match installed candidate')


def expected_seed(q: Request, attempt: int) -> int:
    fields = ['stage2_6_1', q.coordinate['namespace'], FAMILY, q.rung, q.index, attempt]
    return int.from_bytes(hashlib.sha256(canonical(fields).encode()).digest()[:8], 'big')


def validate_proof(q: Request, proof: dict, plan: dict) -> str:
    """Classify only complete, identity-bound proof. Unknown/errors NEVER reserve."""
    require(proof['coordinate'] == q.coordinate, 'request identity mismatch')
    require(proof['status'] in ('accepted', 'structural_rejected'), 'unknown generation status')
    require(proof.get('recorder_errors') == [], 'recorder errors or missing recorder fact')
    call = proof['call_envelope']
    require(call['digest'] == envelope_digest(call, True), 'call envelope digest mismatch')
    for k, v in q.coordinate.items():
        require(call.get(k) == v and type(call.get(k)) is type(v), f'call {k} mismatch')
    rp = {**PARAMS[q.rung], 'cur261_rung': q.rung}
    require(call.get('rung_params') == rp and call.get('max_attempts') == 5,
            'call params or attempts changed')
    require(call.get('iteration') == 'r17', 'call iteration mismatch')
    require(call.get('generator') == plan['runtime']['generator'], 'generator identity mismatch')
    require(call.get('split') == 'curriculum261_' + q.coordinate['namespace']
            and call.get('timeframe') == '15m', 'call split/timeframe mismatch')
    log, envs = proof['attempt_log'], proof['attempt_envelopes']
    for k in ('family', 'rung', 'pair_index'):
        require(log.get(k) == q.coordinate[k], 'attempt log coordinate mismatch')
    require(log.get('seed_namespace') == q.coordinate['namespace'] and log.get('max_attempts') == 5,
            'attempt log namespace/budget mismatch')
    require(isinstance(envs, list) and 1 <= len(envs) <= 5, 'attempt evidence missing/outside budget')
    accepted = proof['status'] == 'accepted'
    selected = len(envs) - 1 if accepted else None
    require(type(log.get('selected_attempt')) is (int if accepted else type(None)), 'selected type invalid')
    require(log.get('selected_attempt') == selected, 'first-pass selection mismatch')
    require(accepted or len(envs) == 5, 'rejection must exhaust exactly five attempts')
    require(len(log['attempts']) == len(envs), 'log/envelope length mismatch')
    for i, (env, att) in enumerate(zip(envs, log['attempts'])):
        require(type(env.get('attempt_index')) is int and type(att.get('index')) is int
                and env['attempt_index'] == i and att['index'] == i, 'attempt order mismatch')
        require(env['digest'] == envelope_digest(env), 'attempt digest mismatch')
        for k, v in q.coordinate.items():
            require(env.get(k) == v and type(env.get(k)) is type(v), f'envelope {k} mismatch')
        require(env.get('generator') == call['generator'], 'attempt generator mismatch')
        require(env.get('iteration') == 'r17' and env.get('split') == call['split']
                and env.get('timeframe') == '15m', 'attempt phase/timeframe mismatch')
        require(type(env.get('outer_seed')) is int and env['outer_seed'] == expected_seed(q, i),
                'outer seed mismatch')
        require(type(env.get('internal_derived_seed')) is int and env['internal_derived_seed'] >= 0,
                'internal seed missing')
        require(env.get('seed_derivation_fields') == {**q.coordinate, 'attempt': i, 'stage_id': 'stage2_6_1'},
                'seed fields mismatch')
        require(env.get('exception') is None, 'generator exception is not reserve-eligible')
        require(env.get('generator_state_changed') is False
                and env.get('generator_state_changed_since_call_start') is False, 'generator state drift')
        passed = accepted and i == selected
        require(env.get('accepted') is passed and att.get('accepted') is passed, 'acceptance contradiction')
        reasons = env.get('rejection_reasons')
        require(isinstance(reasons, list) and env.get('structural_validator_results') == reasons,
                'structural reason mismatch')
        if passed:
            require(reasons == [] and att.get('reason') == '', 'accepted attempt has rejection reasons')
        else:
            require(bool(reasons) and all(isinstance(x, str) and x in ALLOWED_REJECTIONS for x in reasons),
                    'non-whitelisted rejection: stop instead of substitute')
            require(att.get('reason') == '; '.join(reasons), 'log reasons mismatch')
        for side in ('A', 'B'):
            bp = env['base_params'][side]
            expected_params = {**rp, 'pair_variant': side, 'episode_bars': 288, 'initial_price': 1.0}
            require(set(bp) == set(expected_params), 'undeclared generator override or missing base parameter')
            for k, v in expected_params.items():
                require(k in bp and bp[k] == v and not isinstance(bp[k], bool), f'base param missing/changed: {side}.{k}')
            table = env['event_table'][side]
            require(table['bars'] == 288 and isinstance(table['hidden_digest'], str) and bool(table['hidden_digest']),
                    'incomplete event table')
            require(isinstance(table['episode_content_hash'], str)
                    and re.fullmatch(r'ce-[a-f0-9]{64}', table['episode_content_hash']) is not None,
                    'episode content hash invalid')
            counts = table['counts']
            for k in ('n_signals', 'n_above_cost', 'n_below_cost', 'n_distractors'):
                require(type(counts.get(k)) is int and 0 <= counts[k] <= 288, 'missing/invalid C3 counts')
            require(counts['n_above_cost'] + counts['n_below_cost'] == counts['n_signals'], 'inconsistent signal counts')
            if passed:
                require(counts['n_signals'] >= 6 and counts['n_below_cost'] >= 2 and counts['n_distractors'] >= 1,
                        'accepted sample violates C3 counts')
                require(counts['n_above_cost'] >= 2 if side == 'A' else counts['n_above_cost'] == 0,
                        'accepted cost structure invalid')
        # Count-backed reason consistency. 'pair:' is the A-side C3 content
        # check in the unchanged pair_structural_contract. Direction membership
        # itself is certified by the pinned validator; no latent re-generation.
        for label, side in (('A', 'A'), ('B', 'B'), ('pair', 'A')):
            c = env['event_table'][side]['counts']
            expected_flags = {
                'too_few_signals': c['n_signals'] < 6,
                'too_few_distractors': c['n_distractors'] < 1,
                'too_few_below_cost_signals': c['n_below_cost'] < 2,
                'too_few_above_cost_signals': c['n_above_cost'] < 2 if side == 'A' else c['n_above_cost'] != 0,
            }
            for code, should_fail in expected_flags.items():
                require((label + ':' + code in reasons) == should_fail, 'count/rejection-reason contradiction')
    if accepted:
        hashes = {s: envs[-1]['event_table'][s]['episode_content_hash'] for s in ('A', 'B')}
        require(proof.get('episode_hashes') == hashes == log.get('output_episode_hashes'),
                'selected envelope/output identity mismatch')
        integrity = proof.get('integrity')
        require(isinstance(integrity, dict) and integrity.get('pass') is True,
                'integrity failure is fatal, not eligible for reserve')
        for k in ('family', 'rung', 'pair_index'):
            require(integrity.get(k) == q.coordinate[k], 'integrity identity mismatch')
    else:
        require(log.get('output_episode_hashes') == {} and proof.get('episode_hashes') == {},
                'rejected request has selected output')
    return proof['status']


def validate_evaluation(q: Request, ev: dict, proof: dict) -> None:
    require(ev.get('family') == FAMILY, 'evaluation family mismatch')
    rows = ev.get('episodes')
    require(isinstance(rows, list) and len(rows) == 2, 'evaluation must contain one A/B pair')
    require([r.get('side') for r in rows] == ['A', 'B'], 'evaluation side/order mismatch')
    for row in rows:
        require(row.get('pair') == q.index and row.get('rung') == q.rung, 'evaluation coordinate mismatch')
        require(row.get('episode_hash') == proof['episode_hashes'][row['side']], 'evaluation output mismatch')
        for name in POLICIES:
            v = row.get(name)
            require(type(v) in (int, float) and math.isfinite(v), f'invalid metric {name}')
    for name in POLICIES:
        mean = sum(r[name] for r in rows) / 2
        value = ev.get('policy_means', {}).get(name)
        require(type(value) in (int, float) and math.isfinite(value) and math.isclose(value, mean, abs_tol=1e-12),
                'evaluation mean inconsistent')
    means = ev['policy_means']
    metric = means['reference'] - max(0., means['always_long'])
    require(type(ev.get('difficulty_metric')) in (int, float)
            and math.isclose(ev['difficulty_metric'], metric, abs_tol=1e-12), 'difficulty metric inconsistent')
    expected = means['reference'] > max(means[n] for n in POLICIES[:3])
    require(ev.get('reference_beats_required_baselines') is expected
            and ev.get('oracle_positive') is (means['oracle'] > 0), 'evaluation diagnostics inconsistent')
    # Negative performance is valid data; none of these diagnostics gate membership or batch success.


@dataclass
class Generated:
    proof: dict
    handle: Any = None


class Cursor:
    """Single schedule source used by execution and cold readback."""
    def __init__(self):
        self.all = requests()
        self.pos = 0
        self.counts = {(s, r): 0 for s in NAMESPACES for r in RUNGS}
        self.states = {q.key: 'not_started' for q in self.all}
        self.selected = []
        self.attempted = []
        self.stop = None

    def next(self) -> Request | None:
        if self.stop:
            return None
        while self.pos < len(self.all):
            q = self.all[self.pos]
            if self.counts[q.split, q.rung] == 2:
                self.states[q.key] = 'not_needed'
                self.pos += 1
                continue
            return q
        return None

    def consume(self, q: Request, status: str):
        require(self.next() == q, 'out-of-order/unapproved request')
        require(status in ('accepted', 'structural_rejected', 'fatal'), 'unknown request result')
        self.attempted.append(q.key)
        self.states[q.key] = status
        self.pos += 1
        if status == 'accepted':
            self.counts[q.split, q.rung] += 1
            self.selected.append(q.key)
        elif status == 'fatal':
            self.stop = 'fatal'
        if q.index == 3 and self.counts[q.split, q.rung] < 2 and not self.stop:
            self.stop = 'reserve_exhausted'

    def snapshot(self) -> dict:
        self.next()  # mark all skipped reserves after the last accepted slot
        return {'attempted': list(self.attempted), 'selected': list(self.selected),
                'states': dict(self.states), 'stop': self.stop,
                'quota_filled': all(n == 2 for n in self.counts.values())}


def tree_snapshot(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'symlink not allowed in batch evidence')
        if p.is_file():
            out[p.relative_to(root).as_posix()] = file_meta(p)
        else:
            require(p.is_dir(), 'nonregular evidence object')
    return out


def execute(out_dir: Path, backend, *, source_guard=lambda: None) -> dict:
    """One fresh execution. Caller may not retry into this directory after any failure."""
    root = Path(out_dir)
    require(root.parent.is_dir(), 'output parent must already exist')
    root = root.parent.resolve(strict=True) / root.name
    root.mkdir(exist_ok=False)
    cursor = Cursor()
    handles, proofs, index, evaluations = {}, {}, [], []
    result = {'contract': CONTRACT, 'engineering_only': True, 'status': 'error', 'rc': 3,
              'evaluated': [], 'error': None, 'evaluation_started': None}
    try:
        source_guard()
        plan = make_plan(backend.describe())
        validate_plan(plan)
        new_json(root / 'plan.json', plan)
        while (q := cursor.next()) is not None:
            new_json(root / 'starts' / (q.key + '.json'), {'coordinate': q.coordinate, 'ordinal': len(index)})
            observed = []
            def observe(kind, obj):
                require(kind in ('call', 'attempt'), 'unknown recorder event')
                suffix = 'call' if kind == 'call' else f"attempt_{obj['attempt_index']}"
                new_json(root / 'attempts' / q.key / (suffix + '.json'), obj)
                observed.append((kind, obj))
            try:
                generated = backend.generate(q, observe)
                proof = generated.proof
                # Preserve received evidence before classifying it, including malformed evidence.
                new_json(root / 'requests' / (q.key + '.json'), proof)
                status = validate_proof(q, proof, plan)
                require(observed == [('call', proof['call_envelope'])] +
                        [('attempt', e) for e in proof['attempt_envelopes']],
                        'per-attempt persistence differs from final proof')
                require(not (status == 'accepted' and generated.handle is None), 'missing accepted in-memory pair')
                if status == 'accepted':
                    handles[q.key] = generated.handle; proofs[q.key] = proof
                index.append({'key': q.key, 'status': status})
                cursor.consume(q, status)
            except Exception as exc:
                index.append({'key': q.key, 'status': 'fatal'})
                cursor.consume(q, 'fatal')
                new_json(root / 'errors' / (q.key + '.json'),
                         {'type': type(exc).__name__, 'message': str(exc)[:2000]})
                raise
        state = cursor.snapshot()
        selection = {'plan_sha256': plan['plan_sha256'], **state,
                     'evaluation_not_started': True,
                     'selected_proof_sha256': {k: file_meta(root / 'requests' / (k+'.json'))['sha256']
                                               for k in state['selected']}}
        # Membership is fixed before evaluation, even for an incomplete batch.
        new_json(root / 'selection.json', selection)
        if not state['quota_filled']:
            result.update(status='reserve_exhausted', rc=4)
        else:
            source_guard()
            by_key = {q.key: q for q in requests()}
            for key in state['selected']:
                q = by_key[key]
                result['evaluation_started'] = key
                new_json(root / 'evaluation_starts' / (key + '.json'),
                         {'key': key, 'selection_sha256': file_meta(root / 'selection.json')['sha256']})
                ev = backend.evaluate(q, handles[key])
                new_json(root / 'evaluations' / (key + '.json'), ev)
                validate_evaluation(q, ev, proofs[key])
                evaluations.append(key)
                # Release heavy references after evaluation; no generation/replacement in this phase.
                del handles[key]
            source_guard()
            result.update(status='complete', rc=0)
    except Exception as exc:
        result['error'] = {'type': type(exc).__name__, 'message': str(exc)[:2000]}
    result.update(schedule=cursor.snapshot(), results=index, evaluated=evaluations)
    new_json(root / 'result.json', result)
    # Snapshot belongs to this execution only; never re-sign an earlier run.
    manifest = {'contract': CONTRACT, 'files': tree_snapshot(root)}
    new_json(root / 'manifest.json', manifest)
    return result


def verify(root: Path, *, allow_test_fixture=False) -> dict:
    """Cold read of fixed plan/observed request sequence. No generation and no writes."""
    root = root.resolve(strict=True)
    before = tree_snapshot(root)
    manifest = read_json(root / 'manifest.json')
    require(manifest.get('contract') == CONTRACT, 'manifest contract mismatch')
    require(manifest['files'] == {k: v for k, v in before.items() if k != 'manifest.json'},
            'evidence byte set mismatch')
    plan = read_json(root / 'plan.json'); validate_plan(plan)
    require(allow_test_fixture or plan['runtime']['kind'] == 'real_c3', 'fixture is not real batch evidence')
    result = read_json(root / 'result.json')
    require(result.get('contract') == CONTRACT and result.get('engineering_only') is True, 'result contract mismatch')
    cursor = Cursor(); proofs = {}
    for ordinal, row in enumerate(result['results']):
        q = cursor.next()
        require(q is not None and row['key'] == q.key, 'attempted sequence not authorized')
        require(read_json(root / 'starts' / (q.key+'.json')) == {'coordinate': q.coordinate, 'ordinal': ordinal},
                'missing/changed request start')
        if row['status'] == 'fatal':
            require((root/'errors'/(q.key+'.json')).is_file(), 'fatal record missing')
            cursor.consume(q, 'fatal')
        else:
            p = read_json(root / 'requests' / (q.key+'.json'))
            require(validate_proof(q, p, plan) == row['status'], 'row/proof status mismatch')
            require(read_json(root/'attempts'/q.key/'call.json') == p['call_envelope'], 'call journal mismatch')
            for env in p['attempt_envelopes']:
                require(read_json(root/'attempts'/q.key/f"attempt_{env['attempt_index']}.json") == env,
                        'attempt journal mismatch')
            proofs[q.key] = p
            cursor.consume(q, row['status'])
    state = cursor.snapshot()
    require(state == result['schedule'], 'schedule/result mismatch')
    if state['quota_filled'] or state['stop'] == 'reserve_exhausted':
        selection = read_json(root/'selection.json')
        require(selection == {'plan_sha256': plan['plan_sha256'], **state,
                             'evaluation_not_started': True,
                             'selected_proof_sha256': {k: file_meta(root/'requests'/(k+'.json'))['sha256']
                                                       for k in state['selected']}}, 'selection not bound to fixed schedule')
    elif result['status'] != 'error':
        raise EvidenceError('incomplete schedule cannot be successful')
    require(result['evaluated'] == state['selected'][:len(result['evaluated'])], 'evaluation order changed')
    require(not result['evaluated'] or state['quota_filled'], 'evaluation before quota closure')
    by_key = {q.key: q for q in requests()}
    for k in result['evaluated']:
        start = read_json(root/'evaluation_starts'/(k+'.json'))
        require(start == {'key': k, 'selection_sha256': file_meta(root/'selection.json')['sha256']},
                'evaluation not bound to sealed selection')
        validate_evaluation(by_key[k], read_json(root/'evaluations'/(k+'.json')), proofs[k])
    # No accepted result may hide an extra generated/evaluated coordinate.
    if result['status'] in ('complete', 'reserve_exhausted'):
        actual_requests = {p.stem for p in (root/'requests').glob('*.json')}
        require(actual_requests == set(state['attempted']), 'extra/missing generation artifact')
        actual_evals = {p.stem for p in (root/'evaluations').glob('*.json')}
        require(actual_evals == set(result['evaluated']), 'extra/missing evaluation artifact')
        actual_starts = {p.stem for p in (root/'evaluation_starts').glob('*.json')}
        require(actual_starts == set(result['evaluated']), 'extra evaluation invocation')
        allowed = {'plan.json', 'selection.json', 'result.json', 'manifest.json'}
        for k in state['attempted']:
            allowed.update({f'starts/{k}.json', f'requests/{k}.json', f'attempts/{k}/call.json'})
            allowed.update(f"attempts/{k}/attempt_{e['attempt_index']}.json" for e in proofs[k]['attempt_envelopes'])
        for k in result['evaluated']:
            allowed.update({f'evaluation_starts/{k}.json', f'evaluations/{k}.json'})
        require(set(before) == allowed, 'extra/unaccounted invocation evidence')
    if result['status'] == 'complete':
        require(result['rc'] == 0 and result['error'] is None and state['quota_filled']
                and result['evaluated'] == state['selected'] and len(result['evaluated']) == 16,
                'false successful batch')
    elif result['status'] == 'reserve_exhausted':
        require(result['rc'] == 4 and state['stop'] == 'reserve_exhausted' and not result['evaluated'],
                'exhaustion must remain non-success with no evaluation')
    else:
        require(result['status'] == 'error' and result['rc'] == 3 and result['error'] is not None,
                'unknown terminal state')
    require(before == tree_snapshot(root), 'verification changed/read unstable input')
    return {'evidence_consistent': True, 'engineering_batch_complete': result['status'] == 'complete',
            'status': result['status'], 'plan_sha256': plan['plan_sha256'],
            'n_requests': len(state['attempted']), 'n_selected': len(state['selected']),
            'n_evaluated': len(result['evaluated']), 'scope': CONTRACT}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    sub.add_parser('plan', help='print fixed contract without generating data')
    p = sub.add_parser('run'); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('verify'); p.add_argument('--root', type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        if args.command == 'plan':
            print(canonical(fixed_contract())); return 0
        if args.command == 'verify':
            report = verify(args.root)
            print(canonical(report))
            return 0 if report['engineering_batch_complete'] else 1
        from r17_c3_reserve_adapter import RealC3Backend, verify_sources
        backend = RealC3Backend()
        result = execute(args.out, backend, source_guard=verify_sources)
        print(canonical({'status': result['status'], 'rc': result['rc'], 'out': str(args.out)}))
        return result['rc']
    except Exception as exc:
        print(canonical({'status': 'invocation_failed', 'error_type': type(exc).__name__,
                         'error': str(exc)[:2000]}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
