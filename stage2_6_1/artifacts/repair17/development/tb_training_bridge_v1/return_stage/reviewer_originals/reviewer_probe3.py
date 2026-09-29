#!/usr/bin/env python
"""Reviewer probe 3: K01 real-generator-boundary with v2 pack (abort before
generation, zero native episodes) + M01 cold-read wrong-binding/tamper rejects
using own untrained checkpoint (zero optimizer steps)."""
import json, shutil
from pathlib import Path
import numpy as np

ROOT = Path('/mnt/f/trading/tmp_reviewer_tb_v1/work')
RESULTS = []
def check(name, cond, detail=''):
    RESULTS.append((name, bool(cond)))
    print(('PASS' if cond else 'FAIL'), '|', name, ('| ' + str(detail)) if detail else '')

from rl_curriculum.ppo262_qualified_input import load_qualified_input
from rl_curriculum.ppo262_eng_fixture import build_eng_fixture, synthetic_ohlcv
from rl_curriculum.curriculum261_production_obs import attach_production_features
from rl_curriculum.ppo262_eng_profile import QuotaLedger, generate_eng_bank
from rl_curriculum.ppo262_banks import generate262_bank, EpisodeKey, LoadedEpisode
from rl_curriculum.curriculum261_api import episode_content_hash
from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode

fx1 = build_eng_fixture(ROOT/'fx1', variant='v1_r2_reference', verbose=False)
fx2 = build_eng_fixture(ROOT/'fx2', variant='v2_perturbed', verbose=False)
qi2 = load_qualified_input(fx2['qualification_dir'],
    authorization_path=fx2['authorization_path'], expected_scope='engineering')

class _Abort(Exception):
    def __init__(self, recs): self.recs = recs

def aborted(runner):
    recs = []
    def rec(family, rung, side, params):
        recs.append({'family': family, 'rung': rung, 'side': side, 'params': dict(params)})
        raise _Abort(recs)
    try:
        runner(rec)
    except _Abort as a:
        return {r['family']: r for r in a.recs}
    return {}

# I. K01: v2 pack reaches real generator boundary; generation never starts
led = QuotaLedger(ROOT/'probe_ledger.jsonl')
bridge_recs = aborted(lambda r: generate_eng_bank(qi2, led, param_recorder=r))
check('I1 bridge staged order reaches c1 first with v2 pack value at generator boundary',
      set(bridge_recs) == {'c1_opportunity'}
      and bridge_recs['c1_opportunity']['params']['opp_drift_bps'] == 45.0
      and bridge_recs['c1_opportunity']['params']['cur261_rung'] == 'D1')
rung = qi2.rung_params()
exp = {'c1_opportunity': ('opp_drift_bps', 45.0), 'c2_context': ('alpha_bps', 50.0),
       'c3_cost': ('cue_rate', 0.20)}
ok_all = True
for fam, (key, val) in exp.items():
    recs = aborted(lambda r: generate262_bank(
        [EpisodeKey('ppo_eng_bank_262e', fam, 'D1', 0, 'A')],
        locked_plan_rung_params=rung, param_recorder=r))
    ok_all = ok_all and recs[fam]['params'][key] == val
check('I2 all three families: generator-boundary params == selected v2 pack (not R2)',
      ok_all and exp['c3_cost'][1] == 0.20)
s = led.sums()
check('I3 abort-before-generation consumes zero episodes (own ledger)',
      s['bank_episode_success'] == 0 and s['bank_replays'] >= 0,
      json.dumps(s))

# J. M01: own untrained checkpoint + cold read positives/negatives
def loaded_ep(k, family='c1_opportunity', variant='A', bars=96, start=100.0):
    d = attach_production_features(synthetic_ohlcv({'start': start*(1.0+0.2*k), 'drift': 0.0003,
        'amp': 0.0025, 'period': 40.0, 'phase': 0.7*k, 'wick': 0.0015, 'bars': bars}))
    ep = GeneratedEpisode(spec=EpisodeSpec(family='eng_synthetic', params={'fixture_k': k},
        seed=9000+k, split='train', timeframe='15m'), df=d, hidden=d.iloc[:0].copy(),
        family_version='eng-synth-v0', timeframe='15m', is_null=False,
        generator_fingerprint='reviewer-probe-v1')
    return LoadedEpisode(key=EpisodeKey('ppo_eng_bank_262e', family, 'D1', k, variant),
                         episode=ep, content_hash=episode_content_hash(ep))

from rl_curriculum.curriculum261_r4_preprocessing import RouteCPreprocessorV2
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
from rl_curriculum.ppo262_eng_profile import (PPO262E_SMOKE_CONFIG,
    collect_frozen_probe, cold_read_checkpoint, engineering_manifest)
from rl_curriculum.ppo262_train import save_model_with_manifest

preproc = RouteCPreprocessorV2.load_envelope(Path(fx1['qualification_dir'])/'preprocessor_envelope.json')
bank = [loaded_ep(0), loaded_ep(1, family='c2_context')]
env = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
model = build_diagnosed_ppo(dict(PPO262E_SMOKE_CONFIG), 262501, env)
qi1 = load_qualified_input(fx1['qualification_dir'],
    authorization_path=fx1['authorization_path'], expected_scope='engineering')
ckpt = ROOT/'ckpt'
manifest = engineering_manifest(qi1, bank=bank, steps=0, updates=0,
    config=PPO262E_SMOKE_CONFIG, model_seed=262501)
saved = save_model_with_manifest(model, ckpt/'eng_ppo_smoke_256', manifest=manifest)
pr = collect_frozen_probe(preproc, bank, model, bundle_hash=qi1.bundle_hash)
(ckpt/'eng_frozen_probe.json').write_text(json.dumps(pr), encoding='utf-8')

rpos = cold_read_checkpoint(fx1['qualification_dir'], fx1['authorization_path'],
                            ckpt, ROOT/'cr_pos', expected_profile='ppo262_engineering_v1')
check('J1 own checkpoint cold read positive (actions bitwise, atol<=1e-9)',
      rpos['pass'] and rpos['deterministic_actions_match']
      and rpos['action_probability_max_abs_diff'] <= 1e-9)
try:
    cold_read_checkpoint(fx2['qualification_dir'], fx2['authorization_path'], ckpt, ROOT/'cr_neg1')
    wrong_ok = False
except Exception as ex:
    rp = getattr(ex, 'report', {})
    wrong_ok = any('manifest' in p and 'digest' in p for p in rp.get('problems', []))
check('J2 cold read with wrong input binding rejected before prediction',
      wrong_ok)
tam = ROOT/'ckpt_tampered'; shutil.copytree(ckpt, tam)
zp = tam/'eng_ppo_smoke_256.zip'
zp.write_bytes(zp.read_bytes() + b'\x00tamper')
try:
    cold_read_checkpoint(fx1['qualification_dir'], fx1['authorization_path'], tam, ROOT/'cr_neg2')
    tam_ok = False
except Exception as ex:
    rp = getattr(ex, 'report', {})
    tam_ok = any('模型文件字节' in p or 'model_sha' in p for p in rp.get('problems', []))
check('J3 tampered checkpoint bytes rejected (not just file presence)',
      tam_ok)
print('PART3_DONE', sum(1 for _, ok in RESULTS if ok), '/', len(RESULTS))
