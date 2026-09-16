#!/usr/bin/env python3
"""Synthetic native integration and read-only report reconsumption. Not production."""
from __future__ import annotations

import argparse
import copy
import gc
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import sys
import stat
import time
import traceback

from rl_curriculum.curriculum261_r17_c2_native_codec import (
    canonical, digest, load_document, need, regular_bytes, save_document, write_new, parse_json,
)

BLOCKED = (
    ('rl_curriculum.generator_api', 'BaseMarketGenerator.generate'),
    ('rl_curriculum.curriculum261_c1', 'C1OpportunityGenerator._generate'),
    ('rl_curriculum.curriculum261_c2', 'C2ContextGatingGenerator._generate'),
    ('rl_curriculum.curriculum261_c3', 'C3CostAwareGenerator._generate'),
    ('rl_curriculum.curriculum261_r17_registry', 'require_r17_namespace_registered'),
    ('rl_curriculum.curriculum261_api', 'generate_pair_with_attempts'),
    ('rl_curriculum.curriculum261_api', 'derive261_seed'),
    ('rl_curriculum.curriculum261_pairs', 'generate_pair'),
    ('rl_curriculum.curriculum261_r6_tape', 'generate_matched_block_once'),
    ('rl_curriculum.curriculum261_r6_tape', 'generate_matched_block_with_attempts'),
    ('rl_curriculum.curriculum261_r17_calibration', 'generate_fit_bank_r17'),
    ('rl_curriculum.curriculum261_r6_calibration', 'generate_fit_bank_r6'),
    ('rl_curriculum.curriculum261_r17_calibration', 'run_c2_matched_corpus_r17'),
    ('rl_curriculum.curriculum261_r17_calibration', 'run_c2_independent_corpus_r17'),
    ('rl_curriculum.curriculum261_r17_calibration', 'run_c2_semantic_corpus_r17'),
    ('rl_curriculum.curriculum261_r17_design', 'run_design_stage_r17'),
    ('rl_curriculum.curriculum261_r17_cue_contract', 'run_cue_contract_audit'),
    ('rl_curriculum.curriculum261_r17_registry', 'mark_design_data_started'),
    ('r17_v2_c13_profile', 'write_preclaim_receipt'),
    ('r17_v2_c13_profile', 'consume_production_claim'),
    ('r17_v2_c13_profile', 'persist_final_plan'),
)
OBSERVED = (
    ('rl_curriculum.curriculum261_r17_calibration', 'fit_preprocessor_v2_from_bank_r17'),
    ('rl_curriculum.curriculum261_r4_pairs', 'evaluate_pair_corpus_r4'),
    ('rl_curriculum.curriculum261_r4_pairs', 'rung_report_r4'),
    ('rl_curriculum.curriculum261_r17_reference', 'reference_equivalence_run_r17'),
    ('rl_curriculum.curriculum261_r17_cue_eval', 'semantic_cue_gate'),
    ('rl_curriculum.curriculum261_r17_noise_replay', 'trace_corpus'),
    ('rl_curriculum.curriculum261_r17_cue_eval', 'candidate_cue_semantics'),
    ('rl_curriculum.curriculum261_r17_design', '_evaluate_candidate_matched_r17'),
    ('rl_curriculum.curriculum261_r17_c2_consumer', 'consume'),
    ('rl_curriculum.evaluator', 'run_policy_episode'),
)


def source_identity():
    result = {}
    for name, module in list(sys.modules.items()):
        if not (name.startswith(('rl_curriculum.', 'rl_platform.', 'r17_'))
                or name in ('rl_curriculum', 'rl_platform')):
            continue
        path = getattr(module, '__file__', None)
        if path and path.endswith('.py'):
            p = Path(path).absolute()
            result[name] = {'file': str(p), 'sha256': hashlib.sha256(regular_bytes(p)).hexdigest()}
    result['r17_c2_native_rehearsal'] = {'file': str(Path(__file__).absolute()),
        'sha256': hashlib.sha256(regular_bytes(Path(__file__))).hexdigest()}
    return result


class NativeCallAudit:
    """Observe actual function code objects; no monkeypatching of the native tail."""
    def __init__(self, *, read_only=False):
        self.read_only = read_only
        self.counts = {}
        self._codes = {}

    def __enter__(self):
        need(sys.getprofile() is None, 'another profiler is active')
        for blocked, specs in ((True, BLOCKED), (False, OBSERVED)):
            for name, symbol in specs:
                obj = importlib.import_module(name)
                for part in symbol.split('.'):
                    obj = getattr(obj, part)  # Missing sentinel is a failure, never ignored.
                key = name + '.' + symbol
                code = getattr(obj, '__code__', None)
                need(code is not None, 'sentinel is not Python code: ' + key)
                self.counts[key] = 0
                self._codes.setdefault(code, []).append((key, blocked or
                    (self.read_only and symbol != 'consume')))
        self.before = source_identity()
        sys.setprofile(self._profile)
        return self

    def _profile(self, frame, event, arg):
        if event != 'call':
            return
        for key, blocked in self._codes.get(frame.f_code, ()):
            self.counts[key] += 1
            if blocked:
                raise RuntimeError('native engineering call boundary violated: ' + key)

    def __exit__(self, *exc):
        sys.setprofile(None)
        self.after = source_identity()
        for name, identity in self.before.items():
            need(self.after.get(name) == identity, 'imported source drift: ' + name)

    def result(self):
        return {'blocked': {m+'.'+s: self.counts[m+'.'+s] for m,s in BLOCKED},
                'native_calls': {m+'.'+s: self.counts[m+'.'+s] for m,s in OBSERVED},
                'source_before': self.before, 'source_after': self.after}


def _write(root, name, value):
    return write_new(root / name, canonical(value) + b'\n')


def _tests_path() -> None:
    """Make the fixed test fixtures importable when run as a script.

    The monitored entry normalizes PYTHONPATH to src only, so the fixtures
    directory is inserted here exactly like r17_c2_consumer_rehearsal._fixtures.
    """
    root = Path(__file__).resolve().parent.parent / 'tests' / 'route_c_stage2_6_1'
    if (root / 'r17_c2_consumer_fixtures.py').is_file() and str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _audit_fixture():
    # Reuse only the explicitly synthetic upstream audit. It has no raw audit
    # episodes. All native sample/evaluation results below are computed afresh.
    _tests_path()
    from r17_c2_consumer_fixtures import make_packet
    return copy.deepcopy(make_packet()['audit'])


def exercise(root: Path, *, full: bool) -> dict:
    from rl_curriculum import curriculum261_r17_c2_native as native
    from rl_curriculum import curriculum261_r17_c2_consumer as consumer
    from rl_curriculum.curriculum261_r17_c2_native_inputs import (
        disjoint_corpora, load_corpus, raw_sample_fingerprint,
    )
    _tests_path()
    from r17_c2_native_fixtures import make_corpus, spec_for
    root.mkdir(parents=True, exist_ok=False)
    scale = {'design': 40 if full else 2, 'semantic': 160 if full else 2,
             'independent': 20 if full else 2, 'fit': 2,
             'matched': 20 if full else 2}
    audit_node = _audit_fixture()
    _, floor = consumer.audit_gate(audit_node)
    plan = {'format': 'R17C2NativeFixturePlan-v1', 'synthetic': True,
            'business_statistics': 'NOT_RUN', 'formal_qualification': 'NOT_ISSUED',
            'launch_authorized': False, 'scale': scale,
            'fixed_design': consumer.fixed_design(), 'audit': audit_node,
            'audit_provenance': 'existing synthetic REPORT fixture; raw audit NOT rebuilt',
            'fixture_source_sha256': hashlib.sha256(regular_bytes(Path(inspect.getfile(make_corpus)))).hexdigest(),
            'calibration_views': [10,15,20] if full else [],
            'no_selection_policy': 'historical/n10 engineering control only; no design selection fallback'}
    plan_sha = _write(root, 'plan.json', plan)  # Never rewritten after results.
    inputs = []
    seen_contents = {}

    def materialize(split, role, cid, n):
        spec = spec_for(split, role, cid, n)
        corpus = make_corpus(spec, native.engineering_pack(cid, floor))
        rel = f'inputs/{cid}/{split}/{role}.json.gz'
        sha = corpus.save(root/rel)
        seal = corpus.seal
        del corpus
        gc.collect()
        loaded = load_corpus(root/rel, sha, spec)
        need(loaded.seal == seal, 'saved/loaded sample seal')
        contents = {raw_sample_fingerprint(rec.episodes[side])
                    for rec in loaded.records() for side in ('A','B')}
        for key, previous in seen_contents.items():
            if key != (split, role):
                need(not contents & previous, 'reused raw data across partition/role')
        seen_contents.setdefault((split, role), set()).update(contents)
        inputs.append({'path': rel, 'sha256': sha, 'seal': seal, 'spec': spec.document()})
        return loaded

    packet = {'format': consumer.FORMAT, 'synthetic': True,
              'upstream_episode_provenance_verified': False,
              'fixed_design': consumer.fixed_design(), 'audit': audit_node,
              'design': {'matched': {}, 'semantic': {}, 'independent': {}}, 'calibration': {}}
    # Each candidate uses actual native design/statistical code. A negative
    # dedicated gate must not be disguised by substituting fake scalar reports.
    for cid in consumer.CANDIDATES:
        pack = native.engineering_pack(cid, floor)
        packet['design']['matched'][cid] = {}
        packet['design']['semantic'][cid] = {}
        for split in consumer.SPLITS:
            m = materialize(split, 'design_matched', cid, scale['design'])
            r = native.design_matched(m, pack)
            packet['design']['matched'][cid][split] = consumer.wrap_report(
                'design_matched', 'design', split, cid, m.spec.namespace, r)
            sem = materialize(split, 'design_semantic', cid, scale['semantic'])
            disjoint_corpora(m, sem)
            r = native.semantic(sem, pack)
            packet['design']['semantic'][cid][split] = consumer.wrap_report(
                'semantic', 'design', split, cid, sem.spec.namespace, r)
            del m, sem
            gc.collect()
        ind = materialize('both', 'design_independent', cid, scale['independent'])
        r = native.independent(ind, pack, None)
        packet['design']['independent'][cid] = consumer.wrap_report(
            'independent', 'design', 'both', cid, ind.spec.namespace, r)
        del ind
    selection = None
    if full:
        design = consumer.select_design(packet, [])
        selection = design['selection']
    else:
        try:
            consumer.select_design(packet, [])
        except consumer.InputError:
            design = {'status': 'SMALL_PROFILE_REJECTED_AS_REQUIRED', 'selection': None}
        else:
            raise AssertionError('tiny native samples accepted as fixed-scale consumer inputs')
    cid = selection['candidate_id'] if selection else 'historical'
    n = selection['n_blocks'] if selection else (10 if full else 2)
    pack = native.engineering_pack(cid, floor)
    session = native.FitSession()
    checkpoints, comparisons, outcomes = {}, {}, {}
    fit_corpora = []
    packet['calibration'][cid] = {}
    for split in consumer.SPLITS:
        fit = materialize(split, 'fit', cid, scale['fit'])
        for other in fit_corpora:
            disjoint_corpora(other, fit)
        fit_corpora.append(fit)
        frozen = session.fit(fit, pack)
        checkpoint = frozen.save(root/f'v2/{split}.json')
        checkpoints[split] = checkpoint
        _write(root, f'v2/{split}.checkpoint.json', checkpoint)
        frozen = native.FrozenV2.load(root/f'v2/{split}.json', checkpoint, fit, pack)
        # Real refit calls on exposed fitted handles must reject even same data.
        for target in (frozen, frozen.native.inner):
            try:
                target.fit(fit.records())
            except native.SampleError:
                pass
            else:
                raise AssertionError('actual frozen refit was not refused')
        m = materialize(split, 'calibration_matched', cid, scale['matched'])
        if full:
            m = m.prefix(n)
        sem = materialize(split, 'calibration_semantic', cid, scale['semantic'])
        ind = materialize(split, 'calibration_independent', cid, scale['independent'])
        disjoint_corpora(*fit_corpora, m, sem, ind)
        reports, comparison = native.calibration_reports(m, sem, ind, pack, frozen)
        need(comparison['pass'] is True, 'native canonical/scaled equivalence failed')
        comparisons[split] = comparison
        packet['calibration'][cid][split] = reports
        if full:
            control_selection = {'candidate_id': cid, 'n_blocks': n}
            outcomes[split] = consumer.calibration_split(reports, split, control_selection, floor)
        else:
            try:
                consumer.calibration_split(reports, split, {'candidate_id': cid,'n_blocks':2}, floor)
            except consumer.InputError:
                outcomes[split] = {'fixed_scale_rejection': True}
            else:
                raise AssertionError('tiny calibration mislabeled as full-scale')
        del m, sem, ind, frozen
        gc.collect()
    if full:
        result = native.consume_complete(packet)
        result['engineering_calibration_control'] = {
            'is_design_selection': selection is not None, 'candidate': cid, 'n': n,
            'strict_and': all(outcomes[s]['pass'] for s in consumer.SPLITS), 'splits': outcomes}
    else:
        result = {'format': native.FORMAT, 'engineering_only': True,
                  'business_statistics': 'NOT_RUN', 'formal_qualification': 'NOT_ISSUED',
                  'launch_authorized': False, 'small_profile_consumer_rejection': True}
    result.update(plan_sha256=plan_sha, design=design, canonical=comparisons,
                  checkpoints=checkpoints, audit_raw_rebuilt=False,
                  producer_provenance_verified=False)
    packet_sha = save_document(root/'packet.json.gz', packet)
    _write(root, 'inputs.json', inputs)
    _write(root, 'result.json', result)
    return {'packet_sha256': packet_sha, 'full': full, 'result': result}


def index(root: Path):
    files = {}
    for p in sorted(root.rglob('*')):
        need(not p.is_symlink(), 'symlink in native evidence')
        mode = p.lstat().st_mode
        need(stat.S_ISDIR(mode) or stat.S_ISREG(mode), 'non-regular native evidence member')
        if stat.S_ISREG(mode) and p != root / 'bundle_index.json':
            rel = p.relative_to(root).as_posix()
            raw = regular_bytes(p)
            files[rel] = {'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    return files


def run(root: Path, *, full: bool):
    started = time.time()
    try:
        with NativeCallAudit() as audit:
            outcome = exercise(root, full=full)
        calls = audit.result()
        need(all(type(n) is int and n == 0 for n in calls['blocked'].values()), 'blocked call occurred')
        for key, n in calls['native_calls'].items():
            if key.endswith('.consume') and not full:
                continue
            need(n > 0, 'native component not actually executed: ' + key)
        fitkey = 'rl_curriculum.curriculum261_r17_calibration.fit_preprocessor_v2_from_bank_r17'
        need(calls['native_calls'][fitkey] == 2, 'not exactly one V2 fit per partition')
        _write(root, 'calls.json', calls)
        _write(root, 'execution.json', {'argv':sys.argv, 'cwd':os.getcwd(), 'python':sys.executable,
                    'started_unix':started, 'ended_unix':time.time(), 'ok':True,
                    'full': full, 'packet_sha256':outcome['packet_sha256']})
        manifest = {'format':'R17C2NativeBundleIndex-v1', 'files':index(root)}
        anchor = _write(root, 'bundle_index.json', manifest)
        return {'ok':True,'bundle_index_sha256':anchor,'packet_sha256':outcome['packet_sha256'],
                'business_statistics':'NOT_RUN','formal_qualification':'NOT_ISSUED',
                'launch_authorized':False}
    except BaseException:
        if root.exists() and not (root/'failure.txt').exists():
            write_new(root/'failure.txt', traceback.format_exc().encode())
        raise


def verify(root: Path, anchor: str):
    raw = regular_bytes(root/'bundle_index.json')
    need(hashlib.sha256(raw).hexdigest() == anchor, 'external bundle index anchor mismatch')
    manifest = parse_json(raw)
    need(manifest['format'] == 'R17C2NativeBundleIndex-v1' and index(root) == manifest['files'],
         'native evidence membership/bytes mismatch')
    execution = parse_json(regular_bytes(root/'execution.json'))
    calls = parse_json(regular_bytes(root/'calls.json'))
    need(execution.get('ok') is True and type(execution.get('full')) is bool, 'incomplete native execution')
    expected_observed = {m+'.'+s for m,s in OBSERVED}
    need(set(calls['native_calls']) == expected_observed, 'recorded native call membership')
    for key, count in calls['native_calls'].items():
        need(type(count) is int and (count > 0 or (key.endswith('.consume') and not execution['full'])),
             'native component was not executed: ' + key)
    need(calls['native_calls']['rl_curriculum.curriculum261_r17_calibration.fit_preprocessor_v2_from_bank_r17'] == 2,
         'recorded native fit count')
    need(all(calls['source_after'].get(k) == v for k, v in calls['source_before'].items()),
         'recorded source drift')
    required = {m+'.'+s for m,s in BLOCKED}
    need(set(calls['blocked']) == required and all(type(n) is int and n == 0 for n in calls['blocked'].values()),
         'recorded sentinel set/count mismatch')
    # Bind the recorded source closure to the actual current installed bytes.
    for module, identity in calls['source_after'].items():
        loaded = importlib.import_module(module)
        need(str(Path(loaded.__file__).absolute()) == identity['file']
             and hashlib.sha256(regular_bytes(Path(loaded.__file__))).hexdigest() == identity['sha256'],
             'reader source closure mismatch: ' + module)
    packet = load_document(root/'packet.json.gz', execution['packet_sha256'])
    before = index(root)
    with NativeCallAudit(read_only=True) as audit:
        from rl_curriculum.curriculum261_r17_c2_native import consume_complete
        if execution['full']:
            result = consume_complete(packet)
            saved = parse_json(regular_bytes(root/'result.json'))
            need(canonical(result['consumer']) == canonical(saved['consumer']), 'consumer cold result mismatch')
            from rl_curriculum import curriculum261_r17_c2_consumer as consumer
            ctrl = saved['engineering_calibration_control']
            _, floor = consumer.audit_gate(packet['audit'])
            choice = {'candidate_id': ctrl['candidate'], 'n_blocks': ctrl['n']}
            actual = {s: consumer.calibration_split(packet['calibration'][ctrl['candidate']][s], s, choice, floor)
                      for s in consumer.SPLITS}
            need(canonical(actual) == canonical(ctrl['splits'])
                 and all(actual[s]['pass'] for s in consumer.SPLITS) == ctrl['strict_and'],
                 'cold engineering-control result mismatch')
        else:
            from rl_curriculum.curriculum261_r17_c2_consumer import consume, InputError
            try:
                consume(packet)
            except InputError:
                result = {'small_profile_rejected': True}
            else:
                raise AssertionError('tiny packet passed fixed-scale cold consumer')
    need(index(root) == before, 'cold reader wrote evidence')
    return {'ok':True,'scope':'native-evidence-and-report-reconsumption',
            'sample_reexecution':False,'audit_raw_rebuilt':False,
            'calls':audit.result(),'business_statistics':'NOT_RUN',
            'formal_qualification':'NOT_ISSUED','launch_authorized':False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for command in ('probe','rehearse'):
        q = sub.add_parser(command)
        q.add_argument('--out', type=Path, required=True)
    q = sub.add_parser('verify')
    q.add_argument('--bundle', type=Path, required=True)
    q.add_argument('--expected-index-sha256', required=True)
    args = p.parse_args()
    if args.command == 'verify':
        result = verify(args.bundle, args.expected_index_sha256)
    else:
        result = run(args.out, full=args.command == 'rehearse')
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == '__main__':
    main()
