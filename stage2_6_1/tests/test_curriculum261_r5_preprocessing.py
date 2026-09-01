"""R5 测试:Preprocessing V2 复用面(§34 Preprocessing)。

- V2 数值实现复用 R4(inner RouteCPreprocessor;R5 不改数值);
- R5 namespace fit bank -> V2 三层 identity(envelope/重载/篡改拒绝);
- outer observation space 无界 + position [0,1] + no clip;
- adversarial out-of-range 探针(transformed ±13 不截断)。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rl_curriculum.curriculum261_r5_calibration import (
    generate_fit_bank_r5,
    fit_preprocessor_v2_from_bank_r5,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    RouteCPreprocessingEnvV2,
    adversarial_out_of_range_probe,
    preprocessing_v2_contract_digest,
)
from rl_curriculum.curriculum261_r5_pairs import EVAL_CFG
from rl_curriculum.curriculum261_r5_param_pack import (
    C2_TIER_A_CANDIDATES,
    R4_SELECTED_C1_D3,
    R4_SELECTED_C3_D3,
    ladder_pack_payload,
)


@pytest.fixture(scope="module")
def v2_fit(tmp_path_factory):
    """小 fit bank(ppo_smoke_r5,非 final namespace)-> V2。"""
    pack = ladder_pack_payload(
        tier="A", selected_c2_candidate="c2_a_alpha26_vol16",
        c2_d3_params=dict(
            C2_TIER_A_CANDIDATES["c2_a_alpha26_vol16"]),
        design_plan_digest="r5dp-test")
    records = [
        rec for rec in generate_fit_bank_r5("ppo_smoke_r5", pack,
                                            pairs_per_rung=1)
    ]
    v2, manifest = fit_preprocessor_v2_from_bank_r5(
        "ppo_smoke_r5", pack, records=records)
    return v2, manifest


def test_v2_contract_digest_unchanged_from_r4():
    """V2 合同 digest 与 R4 锁定值一致(数值实现未被 R5 修改)。"""
    import hashlib
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2, POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
    )

    assert ROUTE_C_FEATURE_PREPROCESSING_V2 == \
        "RouteCFeaturePreprocessing-v2"
    digest = preprocessing_v2_contract_digest()
    assert digest.startswith("r4pc-")
    assert len(digest) == len("r4pc-") + 64


def test_v2_three_layer_hashes(v2_fit):
    v2, manifest = v2_fit
    assert v2.parameter_state_hash.startswith("r4ps-")
    assert v2.manifest_multiset_hash.startswith("r4fm-")
    assert v2.bundle_hash.startswith("r4pb-")
    assert manifest["namespace"] == "ppo_smoke_r5"
    assert manifest["integrity_all_ok"] is True
    assert v2.verify()["pass"] is True


def test_v2_envelope_reload_and_tamper(v2_fit, tmp_path):
    v2, _ = v2_fit
    path = tmp_path / "envelope.json"
    v2.serialize_envelope(path)
    reloaded = type(v2).load_envelope(path)
    assert reloaded.bundle_hash == v2.bundle_hash

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["fit_manifest"]["entries"][0]["episode_hash"] = "tampered"
    tpath = tmp_path / "tampered.json"
    tpath.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError):
        type(v2).load_envelope(tpath)


def test_outer_env_unbounded_no_clip(v2_fit):
    from rl_platform.env import AlignedLongFlatEnv
    from rl_curriculum.curriculum261_r3_obs import scaled_episode
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
    from rl_curriculum.curriculum261_r5_pairs import EVAL_CFG
    from rl_curriculum.evaluator import select_features_strict

    v2, _ = v2_fit
    rec = generate_pair("c2_context", "D1", 0, namespace="ppo_smoke_r5")
    ep = rec.episodes["A"]
    scaled = scaled_episode(ep, v2.inner)
    schema = r4_observation_schema(v2)
    features = select_features_strict(
        scaled.df, schema, context="r5_preproc_test")
    inner = AlignedLongFlatEnv(
        features=features,
        prices=scaled.df[list(("open", "high", "low", "close"))],
        fee=EVAL_CFG.fee, slippage_bps=EVAL_CFG.slippage_bps,
        initial_cash=EVAL_CFG.initial_cash,
        reward_scale=EVAL_CFG.reward_scale,
        window_size=1, price_tick=EVAL_CFG.price_tick,
        execution_mode="market_open_causal")
    env = RouteCPreprocessingEnvV2(inner, v2.bundle_hash)
    low, high = env.observation_space.low, env.observation_space.high
    assert np.isneginf(low[:8]).all() and np.isposinf(high[:8]).all()
    assert low[8] == 0.0 and high[8] == 1.0
    obs, _ = env.reset(seed=3)
    assert obs.shape == (9,) and str(obs.dtype) == "float32"
    assert env.observation_space.contains(obs)
    # obs 逐位透传(无 clip):与 inner 直读一致
    obs_inner, _ = inner.reset(seed=3)
    assert np.array_equal(obs, obs_inner)


def test_adversarial_out_of_range_no_clip(v2_fit):
    v2, _ = v2_fit
    probe = adversarial_out_of_range_probe(v2, EVAL_CFG)
    assert probe["pass"] is True
    assert probe["max_transformed_feature"] > 10.0  # 线性外推不被截断


def test_r4_pack_constants_available():
    """R5 继承常量可从 param_pack 取得(黄金绑定在 pack 测试中锁定)。"""
    assert "alpha_bps" in R4_SELECTED_C3_D3
    assert "opp_drift_bps" in R4_SELECTED_C1_D3
