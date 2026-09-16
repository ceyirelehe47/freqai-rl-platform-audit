"""Hand-assembled engineering samples, NOT a market generator execution.

Only this approved input boundary fabricates data. Downstream V2, production
features, policy evaluation, semantic/noise replay and statistics stay native.
The schedules below are fixed before observing any return; never retry to pass.
"""
from __future__ import annotations

import hashlib
import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_r17_c2_native_inputs import (
    CorpusSpec, ExplicitCorpus, FAMILIES, RUNGS,
)


def fixture_seed(namespace: str, family: str, rung: str, index: int) -> int:
    text = f'R17C2NativeFixture-v1|{namespace}|{family}|{rung}|{index}'
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], 'big')


def spec_for(split: str, role: str, candidate: str, count: int) -> CorpusSpec:
    # Matched/semantic design candidates share the predetermined block schedule.
    # The candidate is separately bound by the full params and CorpusSpec.
    return CorpusSpec(f'fixture_c2_native_{split}_{role}_v1', split, role, candidate, count)


def _frame(rets, seed, up=None, dn=None):
    from rl_curriculum.curriculum261_production_obs import attach_production_features
    rets = np.asarray(rets, dtype=np.float64).copy()
    rets[0] = 0.0
    close = np.exp(np.cumsum(rets))
    opening = np.r_[1.0, close[:-1]]
    t = np.arange(len(close), dtype=float)
    if up is None:
        up = .003 + .001 * np.sin(t * .71) ** 2
        dn = .003 + .001 * np.cos(t * .37) ** 2
    volume = 100 + 7 * np.sin(t * .31 + (seed % 100003) * .001)
    df = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=len(t), freq='15min', tz='UTC'),
                       'open': opening, 'high': np.maximum(opening, close) * np.exp(up),
                       'low': np.minimum(opening, close) * np.exp(-dn),
                       'close': close, 'volume': volume})
    return attach_production_features(df)


def _c2_components(pack, seed, params, side):
    from rl_curriculum.curriculum261_r17_noise_replay import replay_block_noise
    from rl_curriculum.curriculum261_c2 import _wick_log_plan
    n = 288
    t = np.arange(n)
    cue = np.zeros(n, dtype=np.int64)
    positions = np.arange(3, n-2, 6)
    cue[positions] = np.where(np.arange(len(positions)) % 2 == 0, 1, -1)
    s = np.where((t // 24) % 2 == 0, 1, -1).astype(np.int64)
    w = np.where((t // 42) % 2 == 0, 1, -1).astype(np.int64)
    eps, _, _ = replay_block_noise(pack['c2_ladder'], seed)
    gate = s if side == 'A' else w
    active = np.r_[0, (cue[:-1] != 0).astype(np.int64)]
    payoff = np.r_[0, gate[:-1] * cue[:-1]]
    rets = eps + cue * float(params['pulse_bps']) * 1e-4 + payoff * float(params['alpha_bps']) * 1e-4
    hidden = pd.DataFrame({'cue_dir': cue, 'wick_dir_state': s, 'wick_width_state': w,
                           'payoff_active': active, 'payoff_dir': payoff,
                           'active_gate_is_dir': np.full(n, int(side == 'A'), dtype=np.int64)})
    up, dn = _wick_log_plan(n, s, w, params, seed)
    return _frame(rets, seed, up, dn), hidden


def _other_components(family, seed, params, side):
    n = 288
    t = np.arange(n)
    rng = np.random.default_rng(seed)
    # This is a deliberately fixed toy corpus, not the production stochastic law.
    from rl_curriculum.curriculum261_api import paired_noise
    eps = float(params['vol_bps']) * 1e-4 * paired_noise(rng, n)
    if family == 'c1_opportunity':
        states = np.tile(np.array([1,2,1,0], dtype=np.int64), 3)[t // 24]
        drift = (np.where(states == 2, params['opp_drift_bps'],
                          np.where(states == 0, -params['opp_drift_bps'], 0.))
                 if side == 'A' else np.zeros(n))
        hidden = pd.DataFrame({'seg_index': (t//24).astype(np.int64), 'seg_state': states,
                               'regime_drift_bps': np.asarray(drift, dtype=np.float64),
                               'bars_to_seg_end': (23-t%24).astype(np.int64)})
        return _frame(eps + drift * 1e-4, seed), hidden
    from rl_curriculum.curriculum261_c3 import FRICTION_BPS, C3_PULSE_K_BPS
    signal = np.zeros(n, dtype=np.int64)
    pos = np.arange(4, n-2, 6)
    signal[pos] = np.where(np.arange(len(pos)) % 2 == 0, 1, -1)
    strength = np.zeros(n, dtype=np.float64)
    strength[pos] = np.resize(np.array([.4,.7,1.2,1.5]), len(pos))
    gross = np.where(signal != 0, float(params['alpha_bps']) * strength
                      * int(params['payoff_bars']) if side == 'A' else 5., 0.)
    hidden = pd.DataFrame({'sig_dir': signal, 'sig_strength': strength,
                           'sig_gross_bps': gross, 'above_cost': (gross > FRICTION_BPS).astype(np.int64),
                           'distractor_flag': np.zeros(n, dtype=np.int64)})
    rets = eps + signal * strength * C3_PULSE_K_BPS * 1e-4
    rets[1:] += signal[:-1] * gross[:-1] * 1e-4
    return _frame(rets, seed), hidden


def make_pair(spec: CorpusSpec, pack: dict, family: str, rung: str,
              index: int, *, seed: int | None = None):
    from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode
    from rl_curriculum.curriculum261_api import EpisodeAttemptLog, AttemptRecord, episode_content_hash
    from rl_curriculum.curriculum261_pairs import PairRecord, family_specs, compute_pair_integrity
    from rl_curriculum.curriculum261_r17_param_pack import r17_family_rung_params
    from rl_curriculum.curriculum261_production_obs import PRODUCTION_FEATURE_COLUMNS
    seed = fixture_seed(spec.namespace, family, rung, index) if seed is None else seed
    gen = family_specs()[family].generator
    base = dict(r17_family_rung_params(family, pack)[rung])
    base['cur261_rung'] = rung
    episodes = {}
    for side in ('A', 'B'):
        params = gen.base_params(dict(base), side)
        df, hidden = (_c2_components(pack, seed, params, side) if family == 'c2_context'
                      else _other_components(family, seed, params, side))
        episodes[side] = GeneratedEpisode(
            spec=EpisodeSpec(family, params, seed, 'synthetic_engineering', '15m'),
            df=df, hidden=hidden, family_version=gen.family_version, timeframe='15m', is_null=False,
            generator_fingerprint='fixture:R17C2Native-v1',
            meta={'synthetic': True, 'native_fixture_version': 1,
                  'producer_executed': False, 'schedule': 'fixed-toy-v1'},
            declared_feature_columns=tuple(PRODUCTION_FEATURE_COLUMNS))
    log = EpisodeAttemptLog(family, rung, index, spec.namespace,
            attempts=[AttemptRecord(0, True)], selected_attempt=0,
            episode_hashes={s: episode_content_hash(ep) for s, ep in episodes.items()})
    rec = PairRecord(family, rung, index, episodes, log)
    rec.integrity = compute_pair_integrity(rec)
    rec.integrity_ok = bool(rec.integrity['pass'])
    if not rec.integrity_ok:
        raise AssertionError(f'fixed native fixture structural failure: {family}/{rung}/{index}: {rec.integrity}')
    return rec


def make_corpus(spec: CorpusSpec, pack: dict) -> ExplicitCorpus:
    spec.check()
    if not spec.blocks:
        families = FAMILIES if spec.role == 'fit' else ('c2_context',)
        return ExplicitCorpus(spec, [make_pair(spec, pack, f, r, i)
               for f in families for r in RUNGS for i in range(spec.count)])
    from rl_curriculum.curriculum261_r6_tape import (
        MatchedBlock, MatchedBlockAttemptLog, BlockAttemptRecord,
        verify_cross_rung_matching, shared_tape_digest,
    )
    blocks = []
    for i in range(spec.count):
        seed = fixture_seed(spec.namespace, 'c2_context', 'matched_block', i)
        pairs = {r: make_pair(spec, pack, 'c2_context', r, i, seed=seed) for r in RUNGS}
        eps = {r: pairs[r].episodes for r in RUNGS}
        tape = shared_tape_digest(eps)
        cross = verify_cross_rung_matching(eps, pack['c2_ladder'])
        log = MatchedBlockAttemptLog(i, spec.namespace,
                  attempts=[BlockAttemptRecord(0, True)], selected_attempt=0,
                  rung_episode_hashes={r: pairs[r].attempt_log.episode_hashes for r in RUNGS},
                  shared_tape_digest=tape)
        blocks.append(MatchedBlock(i, eps, pairs, log, tape, {'pass': not cross, 'issues': cross}))
    return ExplicitCorpus(spec, blocks, pack['c2_ladder'])
