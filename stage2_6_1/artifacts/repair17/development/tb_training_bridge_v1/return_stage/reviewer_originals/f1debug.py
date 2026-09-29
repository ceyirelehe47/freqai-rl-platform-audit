import sys
from pathlib import Path
import numpy as np
ROOT = Path('/mnt/f/trading/tmp_reviewer_tb_v1/work')
from rl_curriculum.ppo262_eng_fixture import build_eng_fixture, synthetic_ohlcv
from rl_curriculum.curriculum261_production_obs import attach_production_features
from rl_curriculum.curriculum261_r4_preprocessing import RouteCPreprocessorV2
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_banks import EpisodeKey, LoadedEpisode
from rl_curriculum.curriculum261_api import episode_content_hash
from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode

fx1 = build_eng_fixture(ROOT/'fx1', variant='v1_r2_reference', verbose=False)
preproc = RouteCPreprocessorV2.load_envelope(Path(fx1['qualification_dir'])/'preprocessor_envelope.json')
def loaded_ep(k, family='c1_opportunity', variant='A', bars=96, start=100.0):
    d = attach_production_features(synthetic_ohlcv({'start': start*(1.0+0.2*k), 'drift': 0.0003,
        'amp': 0.0025, 'period': 40.0, 'phase': 0.7*k, 'wick': 0.0015, 'bars': bars}))
    ep = GeneratedEpisode(spec=EpisodeSpec(family='eng_synthetic', params={'fixture_k': k},
        seed=9000+k, split='train', timeframe='15m'), df=d, hidden=d.iloc[:0].copy(),
        family_version='eng-synth-v0', timeframe='15m', is_null=False,
        generator_fingerprint='reviewer-probe-v1')
    return LoadedEpisode(key=EpisodeKey('ppo_eng_bank_262e', family, 'D1', k, variant),
                         episode=ep, content_hash=episode_content_hash(ep))
bank = [loaded_ep(0), loaded_ep(1, family='c2_context')]
env_a = CurriculumMultiEpisodeEnv(bank)
env_b = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
oa, _ = env_a.reset(seed=99); ob, _ = env_b.reset(seed=99)
print('reset obs equal:', np.array_equal(oa, ob))
for t in range(6):
    act = 1 if (t % 5) else 0
    ra_, ta, tra, _, ia = env_a.step(act)
    rb_, tb, trb, _, ib = env_b.step(act)
    print(f't={t} act={act} r_a={ra_!r} r_b={rb_!r} eq={np.allclose(ra_, rb_)}')
    print('   keys_a:', sorted(ia.keys()))
    for k in sorted(set(ia) | set(ib)):
        va, vb = ia.get(k), ib.get(k)
        if isinstance(va, float) and isinstance(vb, float):
            if not np.allclose(va, vb):
                print(f'   DIFF {k}: {va!r} vs {vb!r}')
        elif va != vb:
            print(f'   DIFF {k}: {va!r} vs {vb!r}')
    if ta or tra: break
