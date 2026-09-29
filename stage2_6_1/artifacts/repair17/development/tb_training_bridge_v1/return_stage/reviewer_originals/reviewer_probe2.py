#!/usr/bin/env python
"""Reviewer independent probe part 2: V01/V02/V03/M01(cold-read)/I04/N01.
Zero native generation, zero optimizer steps (no learn calls)."""
import json, shutil, sys
from pathlib import Path
import numpy as np

ROOT = Path('/mnt/f/trading/tmp_reviewer_tb_v1/work')
RESULTS = []
def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond)))
    print(('PASS' if cond else 'FAIL'), '|', name, ('| ' + str(detail)) if detail else '')

from rl_curriculum.ppo262_qualified_input import QualifiedInputError, load_qualified_input
from rl_curriculum.ppo262_eng_fixture import build_eng_fixture, synthetic_ohlcv, ENG_FIT_FIXTURE_SPECS
from rl_curriculum.curriculum261_production_obs import attach_production_features

fx1 = build_eng_fixture(ROOT/'fx1', variant='v1_r2_reference', verbose=False)
fx2 = build_eng_fixture(ROOT/'fx2', variant='v2_perturbed', verbose=False)
def load(out, scope='engineering', **kw):
    return load_qualified_input(out['qualification_dir'],
        authorization_path=out['authorization_path'], expected_scope=scope, **kw)
def rej(out, scope='engineering', **kw):
    try:
        load(out, scope, **kw); return None
    except QualifiedInputError as e:
        return e.report

# D. V01: bundle identity, zero refit at consumption, forged fit manifest
from rl_curriculum.curriculum261_r4_preprocessing import FitManifestEntry, RouteCPreprocessorV2
env_path1 = Path(fx1['qualification_dir'])/'preprocessor_envelope.json'
pA = RouteCPreprocessorV2.load_envelope(env_path1)
pB = RouteCPreprocessorV2.load_envelope(env_path1)
df = attach_production_features(synthetic_ohlcv(ENG_FIT_FIXTURE_SPECS[0]))
t1, t2 = pA.transform_episode_df(df), pB.transform_episode_df(df)
check('D1 frozen bundle reload identical transform', t1.equals(t2)
      and pA.bundle_hash == pB.bundle_hash == fx1['preprocessor_bundle_hash'])
other = attach_production_features(synthetic_ohlcv({**ENG_FIT_FIXTURE_SPECS[0], 'start': 777.0}))
pA.transform_episode_df(other)
check('D2 eval-data change does not refit nor alter bundle identity',
      pA.bundle_hash == fx1['preprocessor_bundle_hash'])
forged_entries = [FitManifestEntry(namespace=e.namespace, family=e.family, rung=e.rung,
    pair_index=e.pair_index, side=e.side, episode_hash=e.episode_hash + '-x',
    feature_matrix_hash=e.feature_matrix_hash, generator_identity=e.generator_identity)
    for e in pA.entries]
forged = RouteCPreprocessorV2(pA.inner, forged_entries, pA.namespace)
check('D3 same scaler params + different fit manifest => different bundle identity',
      forged.parameter_state_hash == pA.parameter_state_hash
      and forged.bundle_hash != pA.bundle_hash)
swap = ROOT/'bundleswap'; shutil.copytree(fx1['qualification_dir'], swap)
forged.serialize_envelope(swap/'preprocessor_envelope.json')
rep = rej({'qualification_dir': swap, 'authorization_path': fx1['authorization_path']})
check('D4 wrong-bound bundle rejected at load (plan binds original)',
      rep is not None and any('bundle' in p for p in rep['problems']))

# E. V02: SB3 sees V2 outer space; no clip; invalid rejected
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_banks import EpisodeKey, LoadedEpisode
from rl_curriculum.curriculum261_api import episode_content_hash
def loaded_ep(k, family='c1_opportunity', variant='A', bars=96, start=100.0):
    from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode
    d = attach_production_features(synthetic_ohlcv({
        'start': start * (1.0 + 0.2 * k), 'drift': 0.0003,
        'amp': 0.0025, 'period': 40.0, 'phase': 0.7 * k,
        'wick': 0.0015, 'bars': bars}))
    ep = GeneratedEpisode(
        spec=EpisodeSpec(family='eng_synthetic', params={'fixture_k': k},
                         seed=9000 + k, split='train', timeframe='15m'),
        df=d, hidden=d.iloc[:0].copy(), family_version='eng-synth-v0',
        timeframe='15m', is_null=False,
        generator_fingerprint='reviewer-probe-v1')
    return LoadedEpisode(key=EpisodeKey('ppo_eng_bank_262e', family, 'D1', k, variant),
                         episode=ep, content_hash=episode_content_hash(ep))
preproc = RouteCPreprocessorV2.load_envelope(env_path1)
bank = [loaded_ep(0), loaded_ep(1, family='c2_context')]
env = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
lo, hi = env.observation_space.low, env.observation_space.high
check('E1 V2 outer space 9d: features unbounded, position [0,1]',
      env.observation_space.shape == (9,)
      and np.all(np.isneginf(lo[:-1])) and np.all(np.isposinf(hi[:-1]))
      and lo[-1] == 0.0 and hi[-1] == 1.0)
from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
from rl_curriculum.ppo262_eng_profile import PPO262E_SMOKE_CONFIG
model = build_diagnosed_ppo(dict(PPO262E_SMOKE_CONFIG), 262501, env)
check('E2 SB3 model observation_space is the same V2 outer space',
      np.array_equal(model.observation_space.low, lo)
      and np.array_equal(model.observation_space.high, hi))
big = loaded_ep(0, bars=96, start=5_000_000.0)
env_big = CurriculumMultiEpisodeEnv([big], preprocessor=preproc)
obs_big, _ = env_big.reset(seed=5)
check('E3 far-out-of-range finite features not clipped',
      float(np.abs(obs_big[:-1]).max()) > 10.0 and np.isfinite(obs_big).all())
env_raw = CurriculumMultiEpisodeEnv(bank)
lraw = env_raw.observation_space.low
check('E4 default (no preprocessor) path unchanged: bounded legacy space',
      not np.all(np.isneginf(lraw[:-1])))
nan_ep = loaded_ep(0)
nan_ep.episode.df.loc[nan_ep.episode.df.index[10], '%-ret-1'] = np.nan
env_nan = CurriculumMultiEpisodeEnv([nan_ep], preprocessor=preproc)
raised = False; where = ''
try:
    env_nan.reset(seed=1)
    for t in range(15):
        env_nan.step(1)
except Exception as ex:
    raised = True; where = type(ex).__name__ + ':' + str(ex)[:60]
check('E5 non-finite observation rejected by contract', raised, where)


# F. V03: ledger invariance under scaling (own action pattern, 2 full episodes)
env_a = CurriculumMultiEpisodeEnv(bank)
env_b = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
oa, _ = env_a.reset(seed=99); ob, _ = env_b.reset(seed=99)
same = True; drift = ''; steps = 0; t = 0
while steps < 400:
    act = 1 if (t % 5) else 0
    oa, ra, ta, tr_a, ia = env_a.step(act)
    ob, rb, tb, tr_b, ib = env_b.step(act)
    steps += 1; t += 1
    if not (np.allclose(ra, rb) and ia.get('new_target_position') == ib.get('new_target_position')
            and np.allclose(ia.get('fee_paid', 0.0), ib.get('fee_paid', 0.0))
            and (ta, tr_a) == (tb, tr_b)):
        same = False; drift = f't={t}'; break
    if ta or tr_a:
        final_a = dict(ia); final_b = dict(ib)
        if not (np.allclose(final_a.get('btc', final_a.get('actual_position', 0)),
                            final_b.get('btc', final_b.get('actual_position'),)) and
                np.allclose(final_a.get('cash', 0), final_b.get('cash', 0))):
            same = False; drift = f'terminal mismatch t={t}'; break
        oa, _ = env_a.reset(); ob, _ = env_b.reset(); t = 0
        if env_a._cursor >= len(bank) and env_a.exhausted_cycles >= 1:
            break
check('F1 identical OHLCV+actions => identical fills/fees/rewards under scaling',
      same and steps >= 50, f'{steps} steps, {drift}')

# G. I04: R2 unchanged; golden seeds; new profile not R2
from rl_curriculum.curriculum261_api import qualification_r2_lock_marker
from rl_curriculum.ppo262_cli import _locked_rung_params
from rl_curriculum.ppo262_input_lock import R2_EXPECTED_PLAN_DIGEST
from rl_curriculum.curriculum261_plan import load_locked_plan
plan_r2, dig = load_locked_plan(qualification_r2_lock_marker().parent)
check('G1 R2 lock unchanged', dig == R2_EXPECTED_PLAN_DIGEST ==
      'qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99')
check('G2 official default rung params still served from R2',
      _locked_rung_params()['c1_opportunity'] == plan_r2['families']['c1_opportunity']['rung_params'])
from rl_curriculum.ppo262_namespaces import derive262_seed
check('G3 262 golden seed unchanged',
      derive262_seed('ppo_smoke_262', 'c1_opportunity', 'D1', 0, 0) == 2721149688598171913)
check('G4 new profile reads new input, not R2',
      load(fx2).rung_params()['c1_opportunity']['D1'] != _locked_rung_params()['c1_opportunity']['D1'])

# H. N01: planted same-seed probe across FULL 261 + 262 namespace surfaces
from rl_curriculum.curriculum261_api import CURRICULUM261_SEED_NAMESPACES
from rl_curriculum.ppo262_namespaces import _derive262_seed_raw, all_262_namespaces
fams = ('c1_opportunity', 'c2_context', 'c3_cost')
eng_seeds = {_derive262_seed_raw('ppo_eng_bank_262e', f, r, p, a)
             for f in fams for r in ('D0','D1','D2','D3') for p in range(60) for a in range(6)}
old262 = set(all_262_namespaces()) - {'ppo_eng_bank_262e'}
old_seeds = set()
for ns in old262:
    old_seeds |= {_derive262_seed_raw(ns, f, r, p, a)
                  for f in fams for r in ('D0','D1','D2','D3') for p in range(60) for a in range(6)}
from rl_curriculum.curriculum261_api import _derive261_seed_raw
n261 = 0
for ns in CURRICULUM261_SEED_NAMESPACES:
    n261 += 1
    old_seeds |= {_derive261_seed_raw(ns, f, r, p, a)
                  for f in fams for r in ('D0','D1','D2','D3') for p in range(60) for a in range(6)}
check('H1 planted-seed probe: eng namespace derivation disjoint from ALL 262+261 namespaces',
      not (eng_seeds & old_seeds), f'{len(eng_seeds)} eng vs {len(old_seeds)} old seeds over {len(old262)} 262 + {n261} 261 namespaces')
check('H2 eng namespace registered in 262 isolation enumeration',
      'ppo_eng_bank_262e' in all_262_namespaces())
check('H3 fit label namespace not in any seed namespace',
      'ppo_eng_fit_262e' not in set(CURRICULUM261_SEED_NAMESPACES)
      and 'ppo_eng_fit_262e' not in set(all_262_namespaces()))

print('PART2_DONE', sum(1 for _, ok in RESULTS if ok), '/', len(RESULTS))
