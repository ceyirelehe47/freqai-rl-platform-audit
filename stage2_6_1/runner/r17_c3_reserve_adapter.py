"""Thin adapter to unchanged production C3 generator/recorder/evaluator.

Only imported by the real RUN path. The batch verifier remains standard-library
only and cannot generate episodes. No exception based on PnL becomes a rejection.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys

from r17_c3_reserve_batch import (Generated, PARAMS, DEFAULTS, NAMESPACES,
                                 FAMILY, require, file_meta)


def ensure_imports():
    # Published repo: runner/../src. Deployed project: already on PYTHONPATH.
    try:
        import rl_curriculum.curriculum261_api  # noqa: F401
    except ModuleNotFoundError as exc:
        if exc.name not in ('rl_curriculum', 'rl_curriculum.curriculum261_api'):
            raise
        src = Path(__file__).resolve().parent.parent / 'src'
        if not src.is_dir():
            raise
        sys.path.insert(0, str(src))


def verify_sources() -> dict:
    ensure_imports()
    from r17_c3_reserve_source_lock import SOURCE_SHA256
    actual = {}
    for name, expected in SOURCE_SHA256.items():
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        got = file_meta(path)['sha256']
        require(got == expected, f'actual imported source drift: {name} ({path})')
        actual[name] = {'path': str(path), 'sha256': got}
    return actual


class RealC3Backend:
    def __init__(self):
        ensure_imports()
        from rl_curriculum import curriculum261_api as api
        from rl_curriculum import curriculum261_pairs as pairs
        from rl_curriculum import curriculum261_generation_envelope as env
        from rl_curriculum import curriculum261_qualification as qualification
        from rl_curriculum import curriculum261_r17_registry as registry
        self.api, self.pairs, self.env, self.qualification = api, pairs, env, qualification
        self.spec = pairs.family_specs()[FAMILY]
        require(api.CURRICULUM261_MAX_ATTEMPTS == 5, 'per-pair attempt contract changed')
        require(self.spec.generator.family_version == 'cur261-c3-v4', 'generator version changed')
        require(self.spec.rung_params == PARAMS and self.spec.reference_defaults == DEFAULTS,
                'C3 parameters/reference defaults changed')
        for ns in NAMESPACES.values():
            require(ns in api.CURRICULUM261_R17_NAMESPACES and ns in registry.R17_ALL_NAMESPACES,
                    'engineering namespaces not installed')
            require(ns not in api.CURRICULUM261_R17_FORMAL_NAMESPACES, 'engineering namespace became formal')
        self.source_identity = verify_sources()

    def describe(self):
        return {'kind': 'real_c3', 'generator': self.env.generator_identity(self.spec.generator),
                'sources': self.source_identity, 'interpreter': sys.version,
                'evaluation': 'existing evaluate_pair_corpus / production observations / frozen Route C env',
                'normalization_fit': 'not performed; not a training qualification'}

    def generate(self, q, observe):
        api, pairs, env = self.api, self.pairs, self.env
        # Exactly the same parameter expansion as generate_pair(); explicit recorder.
        params = {**self.spec.rung_params[q.rung], 'cur261_rung': q.rung}
        class Recorder(env.EnvelopeRecorder):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.failures = []
            def record(self, event, payload):
                try:
                    super().record(event, payload)
                    if event == 'attempt':
                        observe('attempt', self.attempt_envelopes[-1])
                except Exception as exc:
                    # Upstream intentionally swallows recorder errors. Preserve and fail
                    # the batch after this pair; never let them authorize a reserve.
                    self.failures.append(f'{type(exc).__name__}: {str(exc)[:1000]}')
                    raise
        rec = Recorder(iteration='r17', namespace=q.coordinate['namespace'], family=FAMILY,
                       rung=q.rung, pair_index=q.index, rung_params=params)
        observe('call', rec.call_envelope)
        try:
            episodes, log = api.generate_pair_with_attempts(
                self.spec.generator, params, namespace=q.coordinate['namespace'],
                family=FAMILY, rung=q.rung, pair_index=q.index,
                structural_validator=pairs.pair_acceptance_contract(FAMILY), recorder=rec)
        except api.PairGenerationError as exc:
            log = exc.attempt_log
            if log is None:
                raise RuntimeError('PairGenerationError missing attempt log') from exc
            proof = {'coordinate': q.coordinate, 'status': 'structural_rejected',
                     'call_envelope': rec.call_envelope, 'attempt_envelopes': rec.attempt_envelopes,
                     'attempt_log': log.canonical(), 'episode_hashes': {},
                     'recorder_errors': rec.failures, 'error': str(exc)}
            return Generated(json.loads(env.canonical_json(proof)))
        # All other exceptions propagate. No catch-and-resample.
        pair = pairs.PairRecord(family=FAMILY, rung=q.rung, pair_index=q.index,
                                episodes=episodes, attempt_log=log)
        pair.integrity = pairs.compute_pair_integrity(pair)
        pair.integrity_ok = pair.integrity['pass']
        proof = {'coordinate': q.coordinate, 'status': 'accepted',
                 'call_envelope': rec.call_envelope, 'attempt_envelopes': rec.attempt_envelopes,
                 'attempt_log': log.canonical(), 'episode_hashes': dict(log.episode_hashes),
                 'integrity': pair.integrity, 'recorder_errors': rec.failures}
        return Generated(json.loads(env.canonical_json(proof)), pair)

    def evaluate(self, q, pair):
        require(pair.family == FAMILY and pair.rung == q.rung and pair.pair_index == q.index,
                'in-memory pair identity mismatch')
        require(pair.integrity_ok is True, 'cannot evaluate integrity-failed pair')
        before = {s: self.api.episode_content_hash(pair.episodes[s]) for s in ('A', 'B')}
        require(before == pair.attempt_log.episode_hashes, 'episode changed after selection')
        ev = self.qualification.evaluate_pair_corpus(
            [pair], FAMILY, dict(self.spec.rung_params[q.rung]), dict(self.spec.reference_defaults))
        require(before == {s: self.api.episode_content_hash(pair.episodes[s]) for s in ('A', 'B')},
                'evaluation mutated its generation input')
        return json.loads(self.env.canonical_json(ev))
