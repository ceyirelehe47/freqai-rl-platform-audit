"""Real V2/evaluator/statistics adapters over explicitly supplied synthetic samples.

No production generator, claim, plan lock, namespace registration or training.
Report assembly delegates every numerical decision to existing R4/R6/R17 code.
"""
from __future__ import annotations

import copy
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r17_c2_native_codec import (
    SampleError, canonical, digest, need, parse_json, regular_bytes, write_new,
)
from rl_curriculum.curriculum261_r17_c2_native_inputs import (
    CANDIDATES, FAMILIES, RUNGS, ExplicitCorpus, disjoint_corpora,
)

FORMAT = 'R17C2NativeEngineeringResult-v1'


def engineering_pack(candidate: str, recall_floor: float) -> dict:
    from rl_curriculum.curriculum261_r17_c2_launch_prep import next_calibration_candidates
    from rl_curriculum.curriculum261_r6_param_pack import R4_SELECTED_C1_D3, R4_SELECTED_C3_D3
    need(candidate in CANDIDATES, 'undeclared candidate')
    need(type(recall_floor) in (int, float) and 0 <= recall_floor <= 1, 'recall floor')
    return {'synthetic': True, 'formal_pack_created': False,
            'selected_c2_candidate': candidate,
            'c2_ladder': copy.deepcopy(next_calibration_candidates()[candidate]),
            'd3_overrides': {'c1_opportunity': copy.deepcopy(R4_SELECTED_C1_D3),
                             'c3_cost': copy.deepcopy(R4_SELECTED_C3_D3)},
            'recall_floor': float(recall_floor)}


def pack_identity(pack: dict) -> str:
    need(pack == engineering_pack(pack['selected_c2_candidate'], pack['recall_floor']),
         'engineering pack drift or extra fields')
    return 'fixture-c2pk-' + digest(pack)


def check_parameters(corpus: ExplicitCorpus, pack: dict) -> None:
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r17_param_pack import r17_family_rung_params
    pack_identity(pack)
    need(corpus.spec.candidate == pack['selected_c2_candidate'], 'corpus/pack candidate mismatch')
    for rec in corpus.records():
        params = dict(r17_family_rung_params(rec.family, pack)[rec.rung])
        params['cur261_rung'] = rec.rung
        gen = family_specs()[rec.family].generator
        for side in ('A', 'B'):
            expected = gen.base_params(dict(params), side)
            need(canonical(rec.episodes[side].spec.params) == canonical(expected),
                 'sample/pack full parameter mismatch')
    if corpus.spec.blocks:
        need(corpus.ladder == pack['c2_ladder'], 'block ladder/pack mismatch')


class FrozenInner:
    """Delegates unchanged arithmetic; all exposed fitting routes reject refit."""
    __slots__ = ('__inner',)

    def __init__(self, inner: Any):
        need(inner.fitted is True, 'unfitted inner')
        object.__setattr__(self, '_FrozenInner__inner', inner)

    def __setattr__(self, name, value):
        raise SampleError('frozen preprocessor cannot be reassigned')

    def fit(self, *args, **kwargs):
        raise SampleError('refit is forbidden, including identical fit data')

    def fit_transform(self, *args, **kwargs):
        raise SampleError('fit_transform is forbidden after freeze')

    def build_and_fit(self, *args, **kwargs):
        raise SampleError('build_and_fit is forbidden on a frozen handle')

    @property
    def fitted(self):
        return self.__inner.fitted

    @property
    def retained_columns(self):
        return list(self.__inner.retained_columns)

    def fitted_state(self):
        return self.__inner.fitted_state()

    def state_hash(self):
        return self.__inner.state_hash()

    def identity(self):
        return self.__inner.identity()

    def transform(self, df):
        return self.__inner.transform(df)

    def transform_episode_df(self, df):
        return self.__inner.transform_episode_df(df)

    def inverse_features(self, values):
        return self.__inner.inverse_features(values)


def v2_identity(v2: Any) -> dict:
    return {'namespace': v2.namespace, 'parameter_state_hash': v2.parameter_state_hash,
            'fit_manifest_multiset_hash': v2.manifest_multiset_hash,
            'preprocessor_bundle_hash': v2.bundle_hash}


class FrozenV2:
    def __init__(self, v2: Any, fit_corpus: ExplicitCorpus, pack: dict):
        need(fit_corpus.spec.role == 'fit', 'fit-role corpus required')
        self._fit = fit_corpus
        self._pack_id = pack_identity(pack)
        self.split = fit_corpus.spec.split
        self.candidate = fit_corpus.spec.candidate
        self.native = v2
        if not isinstance(v2.inner, FrozenInner):
            v2.inner = FrozenInner(v2.inner)
        self._identity = v2_identity(v2)
        self._manifest = copy.deepcopy(v2.manifest_document())
        self.check()

    @classmethod
    def fit_once(cls, fit_corpus: ExplicitCorpus, pack: dict) -> 'FrozenV2':
        from rl_curriculum.curriculum261_r17_calibration import fit_preprocessor_v2_from_bank_r17
        check_parameters(fit_corpus, pack)
        need(fit_corpus.spec.role == 'fit' and fit_corpus.spec.split in ('main', 'validation'), 'fit role/split')
        # Explicit nonempty complete C1/C2/C3 x D0-D3 records; no None fallback.
        records = fit_corpus.records()
        v2, manifest = fit_preprocessor_v2_from_bank_r17(
            fit_corpus.spec.namespace, pack, records=records,
            pairs_per_rung=fit_corpus.spec.count, parameter_pack_identity=pack_identity(pack))
        need(manifest['n_pairs'] == len(records) and manifest['integrity_all_ok'] is True,
             'native fit manifest does not match input')
        fit_corpus.check()
        return cls(v2, fit_corpus, pack)

    def fit(self, *args, **kwargs):
        raise SampleError('this split has already been fitted')

    def check(self) -> None:
        from rl_curriculum.curriculum261_r4_preprocessing import build_fit_manifest_entries, fit_manifest_multiset_hash
        self._fit.check()
        need(isinstance(self.native.inner, FrozenInner), 'frozen inner replaced')
        need(v2_identity(self.native) == self._identity, 'actual V2 object identity drift')
        need(self.native.manifest_document() == self._manifest, 'V2 manifest drift')
        need(self.native.namespace == self._fit.spec.namespace, 'fit namespace drift')
        entries = build_fit_manifest_entries(self._fit.records(), self._fit.spec.namespace, self._pack_id)
        need(fit_manifest_multiset_hash(entries) == self.native.manifest_multiset_hash,
             'actual V2 fit-member binding mismatch')
        need(self.native.verify()['pass'] is True, 'native V2 verification failed')

    def for_eval(self, corpus: ExplicitCorpus, pack: dict):
        self.check()
        check_parameters(corpus, pack)
        need(corpus.spec.role != 'fit' and corpus.spec.split == self.split
             and corpus.spec.candidate == self.candidate and pack_identity(pack) == self._pack_id,
             'cross-split/candidate V2 use or evaluation of fit bank')
        disjoint_corpora(self._fit, corpus)
        return self.native

    def save(self, path: Path) -> dict:
        self.check()
        with tempfile.TemporaryDirectory(prefix='c2_native_v2_') as td:
            temp = Path(td) / 'v2.json'
            self.native.serialize_envelope(temp)
            raw = regular_bytes(temp)
        sha = write_new(path, raw)
        return {'format': 'R17C2FrozenV2Checkpoint-v1', 'synthetic': True,
                'split': self.split, 'candidate': self.candidate,
                'fit_corpus_seal': self._fit.seal, 'pack_identity': self._pack_id,
                'identity': copy.deepcopy(self._identity), 'envelope_sha256': sha}

    @classmethod
    def load(cls, path: Path, checkpoint: dict, fit_corpus: ExplicitCorpus, pack: dict) -> 'FrozenV2':
        from rl_curriculum.curriculum261_r4_preprocessing import RouteCPreprocessorV2
        need(checkpoint.get('format') == 'R17C2FrozenV2Checkpoint-v1'
             and checkpoint.get('synthetic') is True
             and checkpoint['fit_corpus_seal'] == fit_corpus.seal
             and checkpoint['pack_identity'] == pack_identity(pack)
             and checkpoint['split'] == fit_corpus.spec.split
             and checkpoint['candidate'] == fit_corpus.spec.candidate, 'checkpoint/input binding')
        raw = regular_bytes(path)
        need(hashlib.sha256(raw).hexdigest() == checkpoint['envelope_sha256'], 'V2 file anchor mismatch')
        expected = parse_json(raw)
        # Native loader reads a private immutable copy of the already checked bytes.
        with tempfile.TemporaryDirectory(prefix='c2_native_reload_') as td:
            p = Path(td) / 'v2.json'
            write_new(p, raw)
            v2 = RouteCPreprocessorV2.load_envelope(p)
        need(v2_identity(v2) == checkpoint['identity'], 'loaded V2 identity mismatch')
        need(canonical(v2.envelope()) == canonical(expected), 'V2 envelope structure/identity mismatch')
        return cls(v2, fit_corpus, pack)


def _parts(pack):
    from rl_curriculum.curriculum261_pairs import family_specs
    return pack['c2_ladder'], dict(family_specs()['c2_context'].reference_defaults)


def matched(corpus: ExplicitCorpus, pack: dict, frozen: FrozenV2 | None) -> tuple[dict, dict]:
    from rl_curriculum.curriculum261_r4_pairs import evaluate_pair_corpus_r4
    from rl_curriculum.curriculum261_r6_pairs import build_c2_block_evidence_table, c2_matched_conditions
    from rl_curriculum.curriculum261_r6_tape import block_attempt_statistics, matched_block_corpus_summary
    from rl_curriculum.curriculum261_r17_calibration import c2_matched_conditions_r17
    check_parameters(corpus, pack)
    need(corpus.spec.role in ('design_matched', 'calibration_matched'), 'matched role')
    need((frozen is None) == (corpus.spec.role == 'design_matched'), 'raw design/scaled calibration boundary')
    v2 = None if frozen is None else frozen.for_eval(corpus, pack)
    ladder, thresholds = _parts(pack)
    records = corpus.records()
    ev = evaluate_pair_corpus_r4(records, 'c2_context', ladder, thresholds,
                                  preproc=v2, corpus=corpus.spec.namespace)
    table = build_c2_block_evidence_table(ev['pair_table'], corpus.items, corpus.spec.namespace)
    report = {'seed_namespace': corpus.spec.namespace, 'n_blocks': corpus.spec.count,
              'block_corpus_summary': matched_block_corpus_summary(corpus.items),
              'block_attempt_stats': block_attempt_statistics(corpus.items),
              'block_table': table, 'pair_table': ev['pair_table'], 'episodes': ev['episodes'],
              'matched_conditions': c2_matched_conditions(table), 'blocks': corpus.items}
    conditions = c2_matched_conditions_r17(report, pack)
    corpus.check()
    if frozen is not None:
        frozen.check()
    return report, conditions


def independent(corpus: ExplicitCorpus, pack: dict, frozen: FrozenV2 | None) -> dict:
    from rl_curriculum.curriculum261_r4_pairs import rung_report_r4
    from rl_curriculum.curriculum261_r17_calibration import c2_independent_marginal_guard_r17
    check_parameters(corpus, pack)
    need(corpus.spec.role in ('design_independent', 'calibration_independent'), 'independent role')
    need((frozen is None) == (corpus.spec.role == 'design_independent'), 'independent raw/scaled boundary')
    v2 = None if frozen is None else frozen.for_eval(corpus, pack)
    ladder, thresholds = _parts(pack)
    records = corpus.records()
    report = rung_report_r4(records, 'c2_context', ladder, thresholds,
                           preproc=v2, corpus=corpus.spec.namespace)
    native = {'seed_namespace': corpus.spec.namespace, 'pairs_per_rung': corpus.spec.count,
              'report': report, 'records': records}
    conditions = c2_independent_marginal_guard_r17(native, pack, pack['recall_floor'])
    corpus.check()
    if frozen is not None:
        frozen.check()
    return {'report': report, 'conditions': conditions}


def semantic(corpus: ExplicitCorpus, pack: dict) -> dict:
    from rl_curriculum.curriculum261_r17_cue_eval import semantic_cue_gate, candidate_cue_semantics
    from rl_curriculum.curriculum261_r6_tape import block_attempt_statistics, matched_block_corpus_summary
    check_parameters(corpus, pack)
    need(corpus.spec.role in ('design_semantic', 'calibration_semantic'), 'dedicated semantic role')
    ladder, thresholds = _parts(pack)
    shared = semantic_cue_gate(corpus.items, ladder, thresholds,
               recall_floor_value=pack['recall_floor'], label='native-fixture@' + corpus.spec.namespace,
               explicit_block_seeds=corpus.seeds())
    candidate = candidate_cue_semantics(corpus.items, corpus.spec.candidate, thresholds)
    shared['block_attempt_stats'] = block_attempt_statistics(corpus.items)
    shared['block_corpus_summary'] = matched_block_corpus_summary(corpus.items)
    report = {'format': 'cur261-r17-semantic-corpus-v1', 'namespace': corpus.spec.namespace,
              'ladder': corpus.spec.candidate, 'n_blocks': corpus.spec.count,
              'semantic_blocks_per_corpus_expected': 160, 'n_semantic_episodes': 8 * corpus.spec.count,
              'shared': shared, 'candidate': candidate,
              'binding_leaf_checks': sorted([f'dedicated_{k}' for k in shared['checks']] + [
                  'dedicated_candidate_cue_precision_lcb', 'dedicated_candidate_payoff_false_cue_ucb']),
              'pass': bool(shared['pass'] and candidate['pass'])}
    corpus.check()
    return report


def design_matched(corpus: ExplicitCorpus, pack: dict) -> dict:
    from rl_curriculum.curriculum261_r17_design import _evaluate_candidate_matched_r17
    check_parameters(corpus, pack)
    need(corpus.spec.role == 'design_matched', 'design matched role')
    ladder, thresholds = _parts(pack)
    # The native R17 design function ALREADY supports blocks=. Always supply it.
    report = _evaluate_candidate_matched_r17(corpus.spec.candidate, ladder,
        corpus.spec.namespace, thresholds, blocks=corpus.items, n_blocks=corpus.spec.count)
    corpus.check()
    return report


def canonical_comparison(corpus: ExplicitCorpus, pack: dict, frozen: FrozenV2) -> dict:
    from rl_curriculum.curriculum261_r17_reference import reference_equivalence_run_r17
    v2 = frozen.for_eval(corpus, pack)
    result = reference_equivalence_run_r17(corpus.records(), v2, pack,
                eval_namespace=corpus.spec.namespace, expected_bundle_hash=v2.bundle_hash,
                detailed=True)
    corpus.check()
    frozen.check()
    need(result['n_episodes'] == 2 * len(corpus.records()), 'canonical membership count')
    return result


def calibration_reports(matched_corpus: ExplicitCorpus, semantic_corpus: ExplicitCorpus,
                        independent_corpus: ExplicitCorpus, pack: dict, frozen: FrozenV2) -> tuple[dict, dict]:
    from rl_curriculum import curriculum261_r17_c2_consumer as consumer
    disjoint_corpora(frozen._fit, matched_corpus, semantic_corpus, independent_corpus)
    s = matched_corpus.spec
    need((semantic_corpus.spec.split, independent_corpus.spec.split) == (s.split, s.split),
         'calibration split mismatch')
    raw, conditions = matched(matched_corpus, pack, frozen)
    sem = semantic(semantic_corpus, pack)
    indep = independent(independent_corpus, pack, frozen)
    wrap = lambda kind, corpus, payload: consumer.wrap_report(
        kind, 'calibration', s.split, s.candidate, corpus.spec.namespace, payload)
    data = {'matched': wrap('matched', matched_corpus,
                {k: v for k, v in raw.items() if k != 'blocks'}),
            'matched_conditions': conditions,
            'semantic': wrap('semantic', semantic_corpus, sem),
            'independent': wrap('independent', independent_corpus, indep)}
    comparison = canonical_comparison(matched_corpus, pack, frozen)
    return data, comparison


def consume_complete(packet: dict) -> dict:
    """Use the existing fixed-scale consumer; never coerce tiny reports to full size."""
    from rl_curriculum.curriculum261_r17_c2_consumer import consume
    outcome = consume(packet)
    return {'format': FORMAT, 'engineering_only': True,
            'producer_provenance_verified': False, 'audit_raw_rebuilt': False,
            'business_statistics': 'NOT_RUN', 'formal_qualification': 'NOT_ISSUED',
            'launch_authorized': False, 'consumer': outcome}


class FitSession:
    """One attempted fit per partition. A failed fit also consumes the slot."""
    def __init__(self):
        self._attempted = set()

    def fit(self, corpus: ExplicitCorpus, pack: dict) -> FrozenV2:
        split = corpus.spec.split
        need(split in ('main', 'validation') and split not in self._attempted,
             'partition already fitted/attempted')
        self._attempted.add(split)
        return FrozenV2.fit_once(corpus, pack)
