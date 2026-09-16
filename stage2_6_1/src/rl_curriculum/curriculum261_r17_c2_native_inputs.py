"""Explicit, immutable-by-revalidation sample boundary for C2 engineering.

Only fixture_c2_native_* inputs are accepted. No generator, namespace registry,
production plan or claim is called. Persisted content is NOT generator proof.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_r17_c2_native_codec import (
    FORMAT, SampleError, canonical, decode_frame, digest, encode_frame, exact,
    integer, load_document, need, save_document,
)

FAMILIES = ('c1_opportunity', 'c2_context', 'c3_cost')
RUNGS = ('D0', 'D1', 'D2', 'D3')
CANDIDATES = ('historical', 'conservative', 'midpoint')
ROLES = ('fit', 'design_matched', 'design_semantic', 'design_independent',
         'calibration_matched', 'calibration_semantic', 'calibration_independent')
PREFIX = 'fixture_c2_native_'


@dataclass(frozen=True)
class CorpusSpec:
    namespace: str
    split: str
    role: str
    candidate: str
    count: int  # blocks, or pairs PER family/rung

    def check(self) -> None:
        import re
        need(type(self.namespace) is str and len(self.namespace) < 180
             and re.fullmatch(r'fixture_c2_native_[a-z0-9_]+', self.namespace) is not None,
             'only explicit fixture_c2_native namespaces are allowed')
        need(self.split in ('main', 'validation', 'both'), 'split')
        need(self.role in ROLES and self.candidate in CANDIDATES, 'role/candidate')
        need(self.split != 'both' or self.role == 'design_independent', 'both split role')
        integer(self.count, 1 if self.role == 'fit' else 2, 160, 'corpus count')
        need('_' + self.split + '_' in self.namespace, 'namespace split binding')
        need('_' + self.role + '_' in self.namespace, 'namespace role binding')

    @property
    def blocks(self) -> bool:
        return self.role.endswith(('matched', 'semantic'))

    def document(self) -> dict:
        self.check()
        return dict(namespace=self.namespace, split=self.split, role=self.role,
                    candidate=self.candidate, count=self.count)


def _native():
    from rl_curriculum import curriculum261_api as a
    from rl_curriculum import curriculum261_pairs as p
    from rl_curriculum import curriculum261_r6_tape as t
    from rl_curriculum import generator_api as g
    return a, p, t, g


def _episode_doc(ep: Any) -> dict:
    from rl_curriculum.curriculum261_api import episode_content_hash
    need(ep.meta.get('synthetic') is True and ep.meta.get('native_fixture_version') == 1,
         'sample is not an explicit engineering fixture')
    need(ep.spec.split == 'synthetic_engineering', 'episode split cannot claim production')
    need(ep.timeframe == ep.spec.timeframe == '15m', 'timeframe')
    integer(ep.spec.seed, 0, 2**64 - 1, 'episode seed')
    need(type(ep.is_null) is bool, 'is_null bool')
    need(type(ep.family_version) is str and bool(ep.family_version), 'family version')
    need(type(ep.generator_fingerprint) is str
         and ep.generator_fingerprint.startswith('fixture:'), 'fixture producer identity')
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS, assert_production_observation_binding,
        production_observation_schema,
    )
    need(tuple(ep.declared_feature_columns) == tuple(PRODUCTION_FEATURE_COLUMNS),
         'declared production feature whitelist')
    need(not (set(ep.hidden.columns) & set(PRODUCTION_FEATURE_COLUMNS)), 'hidden/observation column overlap')
    need(len(ep.df) == len(ep.hidden) == 288, '288 bars and hidden alignment required')
    need(ep.df.index.equals(ep.hidden.index), 'hidden/data index mismatch')
    import re
    _m = re.fullmatch(r'datetime64\[(ns|us|ms|s), UTC\]', str(ep.df['date'].dtype)) if 'date' in ep.df else None
    need(_m is not None, 'UTC ns/us/ms/s dates required')
    # pandas 3 emits datetime64[us] for pd.date_range; keep the 15-minute bar
    # spacing check in the column's native resolution.
    _step = 900 * {'ns': 10**9, 'us': 10**6, 'ms': 10**3, 's': 1}[_m.group(1)]
    dates = ep.df['date'].array.asi8
    need(bool(np.all(np.diff(dates) == _step)), 'time continuity')
    expected = ('date', 'open', 'high', 'low', 'close', 'volume', *PRODUCTION_FEATURE_COLUMNS)
    need(tuple(ep.df.columns) == expected, 'production data column order')
    o, h, l, c = (ep.df[k].to_numpy(dtype=np.float64) for k in ('open', 'high', 'low', 'close'))
    need(bool(np.all(l > 0) and np.all(h >= np.maximum(o, c))
              and np.all(l <= np.minimum(o, c))
              and np.array_equal(o[1:], c[:-1])
              and np.all(ep.df['volume'].to_numpy() >= 0)), 'OHLCV continuity/geometry')
    # This executes the actual RouteCStrategy feature function, not a local formula.
    assert_production_observation_binding(production_observation_schema(), ep.df)
    body = {'spec': {'family': ep.spec.family, 'params': copy.deepcopy(ep.spec.params),
                     'seed': ep.spec.seed, 'split': ep.spec.split, 'timeframe': ep.spec.timeframe},
            'df': encode_frame(ep.df), 'hidden': encode_frame(ep.hidden),
            'family_version': ep.family_version, 'timeframe': ep.timeframe,
            'is_null': ep.is_null, 'generator_fingerprint': ep.generator_fingerprint,
            'meta': copy.deepcopy(ep.meta),
            'declared_feature_columns': list(ep.declared_feature_columns),
            'episode_content_hash': episode_content_hash(ep)}
    canonical(body)  # Reject unsupported or nonfinite metadata before writing.
    return body


def _decode_episode(doc: dict) -> Any:
    exact(doc, ('spec', 'df', 'hidden', 'family_version', 'timeframe', 'is_null',
                'generator_fingerprint', 'meta', 'declared_feature_columns',
                'episode_content_hash'), 'episode')
    exact(doc['spec'], ('family', 'params', 'seed', 'split', 'timeframe'), 'episode spec')
    _, _, _, g = _native()
    ep = g.GeneratedEpisode(
        spec=g.EpisodeSpec(**doc['spec']), df=decode_frame(doc['df']),
        hidden=decode_frame(doc['hidden']), family_version=doc['family_version'],
        timeframe=doc['timeframe'], is_null=doc['is_null'],
        generator_fingerprint=doc['generator_fingerprint'], meta=copy.deepcopy(doc['meta']),
        declared_feature_columns=tuple(doc['declared_feature_columns']))
    need(_episode_doc(ep) == doc, 'episode content/structure hash mismatch')
    return ep


def _attempts(log: Any, *, label: str) -> None:
    need(log.max_attempts == 5 and type(log.max_attempts) is int, label + ' max attempts')
    need(1 <= len(log.attempts) <= 5, label + ' attempts length')
    selected = integer(log.selected_attempt, 0, 4, label + ' selected attempt')
    need(selected == len(log.attempts) - 1, label + ' first-pass terminal')
    for i, a in enumerate(log.attempts):
        need(type(a.index) is int and a.index == i and type(a.accepted) is bool
             and type(a.reason) is str, label + ' attempt metadata')
        need((a.accepted and a.reason == '') if i == selected
             else (not a.accepted and bool(a.reason)), label + ' first-pass ordering')
    # Engineering fixtures have no producer retry history to invent.
    need(selected == 0, label + ' v1 fixture must be explicitly assembled once')


def _pair_doc(rec: Any, spec: CorpusSpec, index: int, rung: str, family: str) -> dict:
    a, p, _, _ = _native()
    need((rec.family, rec.rung, rec.pair_index) == (family, rung, index)
         and type(rec.pair_index) is int, 'pair coordinates')
    log = rec.attempt_log
    _attempts(log, label='pair')
    need(type(log.pair_index) is int, 'pair log index must be integer')
    need((log.family, log.rung, log.pair_index, log.seed_namespace)
         == (family, rung, index, spec.namespace), 'attempt coordinate/namespace')
    exact(rec.episodes, ('A', 'B'), 'pair sides')
    exact(log.episode_hashes, ('A', 'B'), 'logged episode hashes')
    episodes = {}
    for side in ('A', 'B'):
        ep = rec.episodes[side]
        need(ep.family_version == p.family_specs()[family].generator.family_version, 'family implementation identity')
        need(ep.spec.family == family and ep.spec.params.get('cur261_rung') == rung
             and ep.spec.params.get('pair_variant') == side, 'episode family/rung/side binding')
        episodes[side] = _episode_doc(ep)
        need(log.episode_hashes[side] == episodes[side]['episode_content_hash'], 'logged ce hash')
    need(rec.episodes['A'].spec.seed == rec.episodes['B'].spec.seed, 'pair seed mismatch')
    actual = p.compute_pair_integrity(rec)
    need(type(rec.integrity_ok) is bool and rec.integrity_ok is True
         and actual['pass'] is True, 'accepted fixture fails native pair integrity')
    need(rec.integrity.get('pass') is True, 'pair integrity projection')
    return {'family': family, 'rung': rung, 'pair_index': index,
            'attempt_log': log.canonical(), 'episodes': episodes,
            'integrity_pass': True}


def _decode_pair(doc: dict) -> Any:
    exact(doc, ('family', 'rung', 'pair_index', 'attempt_log', 'episodes', 'integrity_pass'), 'pair')
    a, p, _, _ = _native()
    log = doc['attempt_log']
    exact(log, ('format', 'family', 'rung', 'pair_index', 'seed_namespace', 'max_attempts',
                'attempts', 'selected_attempt', 'output_episode_hashes'), 'pair log')
    need(log['format'] == a.CURRICULUM261_ATTEMPT_LOG_FORMAT, 'pair log format')
    need(doc['integrity_pass'] is True, 'unaccepted sample')
    attempt_log = a.EpisodeAttemptLog(
        family=log['family'], rung=log['rung'], pair_index=log['pair_index'],
        seed_namespace=log['seed_namespace'], max_attempts=log['max_attempts'],
        attempts=[a.AttemptRecord(**row) for row in log['attempts']],
        selected_attempt=log['selected_attempt'], episode_hashes=copy.deepcopy(log['output_episode_hashes']))
    rec = p.PairRecord(doc['family'], doc['rung'], doc['pair_index'],
                       {s: _decode_episode(doc['episodes'][s]) for s in ('A', 'B')}, attempt_log)
    rec.integrity = p.compute_pair_integrity(rec)
    rec.integrity_ok = bool(rec.integrity['pass'])
    return rec


def explicit_trace_arguments(blocks: list, seeds: dict[int, int]) -> list:
    """The ONLY new seed-input branch used by the unchanged semantic mathematics."""
    need(type(seeds) is dict and blocks, 'explicit seed mapping required')
    ids = [integer(b.block_index, 0, 159, 'block index') for b in blocks]
    need(len(ids) == len(set(ids)) and set(seeds) == set(ids)
         and all(type(k) is int for k in seeds), 'explicit seed membership mismatch')
    out = []
    for b in blocks:
        seed = integer(seeds[b.block_index], 0, 2**64-1, 'explicit block seed')
        need(b.attempt_log.seed_namespace.startswith(PREFIX), 'explicit seeds are fixture-only')
        for rung in RUNGS:
            for side in ('A', 'B'):
                ep = b.episodes[rung][side]
                need(ep.spec.seed == seed and ep.meta.get('synthetic') is True
                     and ep.spec.split == 'synthetic_engineering', 'explicit seed/spec binding')
        out.append((b.block_index, seed, b.episodes))
    return out


class ExplicitCorpus:
    """A sealed engineering sample set. Mutating native objects invalidates it."""
    def __init__(self, spec: CorpusSpec, items: list, ladder: dict | None = None):
        spec.check()
        self.spec = spec
        self.items = list(items)
        self.ladder = copy.deepcopy(ladder)
        self._seal = digest(self.document())

    def document(self) -> dict:
        spec = self.spec
        spec.check()
        families = FAMILIES if spec.role == 'fit' else ('c2_context',)
        expected = {(f, r, i) for f in families for r in RUNGS for i in range(spec.count)}
        if spec.blocks:
            need(len(self.items) == spec.count and self.ladder is not None, 'block count/ladder')
            _, _, t, _ = _native()
            rows = []
            ids = [b.block_index for b in self.items]
            need(ids == list(range(spec.count)), 'block order/membership')
            for b in self.items:
                _attempts(b.attempt_log, label='block')
                need(type(b.attempt_log.block_index) is int, 'block log index must be integer')
                need(b.attempt_log.block_index == b.block_index
                     and b.attempt_log.seed_namespace == spec.namespace, 'block log identity')
                exact(b.episodes, RUNGS, 'block episode rungs')
                exact(b.pair_records, RUNGS, 'block pair rungs')
                pairs = []
                for r in RUNGS:
                    rec = b.pair_records[r]
                    for s in ('A', 'B'):
                        need(rec.episodes[s] is b.episodes[r][s], 'block/pair object alias mismatch')
                        need(b.attempt_log.rung_episode_hashes[r][s]
                             == rec.attempt_log.episode_hashes[s], 'block/rung hash linkage')
                    pairs.append(_pair_doc(rec, spec, b.block_index, r, 'c2_context'))
                cross = t.verify_cross_rung_matching(b.episodes, self.ladder)
                need(cross == [] and b.cross_rung_integrity.get('pass') is True
                     and b.cross_rung_integrity.get('issues') == cross,
                     'native cross-rung integrity: ' + str(cross))
                tape = t.shared_tape_digest(b.episodes)
                need(tape == b.shared_tape_digest == b.attempt_log.shared_tape_digest,
                     'shared tape content digest')
                seeds = {b.block_index: b.episodes['D0']['A'].spec.seed}
                explicit_trace_arguments([b], seeds)
                rows.append({'block_index': b.block_index, 'seed': seeds[b.block_index],
                             'shared_tape_digest': tape, 'pairs': pairs})
        else:
            need(self.ladder is None, 'pair corpus cannot carry block ladder')
            need(len(self.items) == len(expected), 'pair corpus cardinality')
            seen = set()
            rows = []
            for rec in self.items:
                key = (rec.family, rec.rung, rec.pair_index)
                need(key in expected and key not in seen, 'duplicate/missing/foreign pair')
                seen.add(key)
                rows.append(_pair_doc(rec, spec, rec.pair_index, rec.rung, rec.family))
            need(seen == expected, 'incomplete pair membership')
            if spec.role != 'fit':
                need([(r.family, r.rung, r.pair_index) for r in self.items] == sorted(expected),
                     'evaluation member order changed')
            rows.sort(key=lambda r: (r['family'], r['rung'], r['pair_index']))
        records = ([b.pair_records[r] for b in self.items for r in RUNGS] if spec.blocks else self.items)
        fingerprints = [raw_sample_fingerprint(rec.episodes[side]) for rec in records for side in ('A', 'B')]
        need(len(fingerprints) == len(set(fingerprints)), 'duplicate raw samples under relabeled coordinates')
        return {'format': FORMAT, 'synthetic': True, 'producer_provenance_verified': False,
                'spec': spec.document(), 'ladder': self.ladder, 'items': rows}

    @property
    def seal(self) -> str:
        return self._seal

    def check(self) -> None:
        need(digest(self.document()) == self._seal, 'in-memory sample mutation')

    def records(self) -> list:
        self.check()
        return ([b.pair_records[r] for b in self.items for r in RUNGS]
                if self.spec.blocks else list(self.items))

    def seeds(self) -> dict[int, int]:
        need(self.spec.blocks, 'blocks required for seeds')
        return {b.block_index: b.episodes['D0']['A'].spec.seed for b in self.items}

    def save(self, path: Path) -> str:
        self.check()
        return save_document(path, self.document())

    def prefix(self, count: int) -> 'ExplicitCorpus':
        """Only preregistered n views, never outcome-dependent reordering."""
        self.check()
        need(self.spec.role == 'calibration_matched' and count in (10, 15, 20)
             and count <= self.spec.count, 'invalid predeclared calibration view')
        s = self.spec
        return ExplicitCorpus(CorpusSpec(s.namespace, s.split, s.role, s.candidate, count),
                              self.items[:count], self.ladder)


def load_corpus(path: Path, expected_sha256: str, expected_spec: CorpusSpec) -> ExplicitCorpus:
    doc = load_document(path, expected_sha256)
    exact(doc, ('format', 'synthetic', 'producer_provenance_verified', 'spec', 'ladder', 'items'), 'corpus')
    need(doc['format'] == FORMAT and doc['synthetic'] is True
         and doc['producer_provenance_verified'] is False, 'engineering-only corpus')
    need(doc['spec'] == expected_spec.document(), 'external corpus identity mismatch')
    items = []
    if expected_spec.blocks:
        a, _, t, _ = _native()
        for row in doc['items']:
            exact(row, ('block_index', 'seed', 'shared_tape_digest', 'pairs'), 'block')
            pairs = [_decode_pair(p) for p in row['pairs']]
            need(len(pairs) == 4 and [p.rung for p in pairs] == list(RUNGS), 'block pair membership')
            records = {p.rung: p for p in pairs}
            episodes = {r: records[r].episodes for r in RUNGS}
            need(all(episodes[r][s].spec.seed == row['seed'] for r in RUNGS for s in ('A','B')),
                 'persisted block seed mismatch')
            log = t.MatchedBlockAttemptLog(row['block_index'], expected_spec.namespace,
                    attempts=[t.BlockAttemptRecord(0, True)], selected_attempt=0,
                    rung_episode_hashes={r: records[r].attempt_log.episode_hashes for r in RUNGS},
                    shared_tape_digest=row['shared_tape_digest'])
            cross = t.verify_cross_rung_matching(episodes, doc['ladder'])
            items.append(t.MatchedBlock(row['block_index'], episodes, records, log,
                          row['shared_tape_digest'], {'pass': not cross, 'issues': cross}))
    else:
        items = [_decode_pair(row) for row in doc['items']]
    corpus = ExplicitCorpus(expected_spec, items, doc['ladder'])
    need(corpus.document() == doc, 'native sample round-trip mismatch')
    return corpus


def disjoint_corpora(*corpora: ExplicitCorpus) -> None:
    """Reject reuse even after changing seed/spec labels: bind raw frame bytes."""
    seen = set()
    for corpus in corpora:
        corpus.check()
        local = set()
        for rec in corpus.records():
            for side in ('A', 'B'):
                ep = rec.episodes[side]
                key = raw_sample_fingerprint(ep)
                need(key not in seen, 'fit/eval or split sample reuse')
                local.add(key)
        seen.update(local)


def raw_sample_fingerprint(ep: Any) -> str:
    # Do not let a new seed, namespace, date or index disguise reused samples.
    return digest({'numeric': encode_frame(ep.df.drop(columns=['date']).reset_index(drop=True)),
                   'hidden': encode_frame(ep.hidden.reset_index(drop=True))})
