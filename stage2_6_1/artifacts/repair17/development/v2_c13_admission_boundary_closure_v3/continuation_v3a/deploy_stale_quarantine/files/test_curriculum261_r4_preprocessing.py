"""R4 测试:Preprocessing V2 合同(无界空间/manifest/bundle)(§33)。

- outer feature bounds ±inf、position [0,1]、float32;
- transformed value > 10 / < -10 仍被 outer space 接受,不 clip
  (wrapper 输出与 bare inner 逐位相等);
- SB3(check_env 与 PPO model)看到的是 outer 无界空间;
- manifest multiset hash 行序不变;不同 multiset 不同 hash;
  parameter state 相同但 manifest 不同 -> bundle 不同;
- manifest 篡改 / parameter state 篡改 -> verification FAIL;
- reload 后 bundle identity 不变;staged/mixed 同 multiset 同 bundle。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_RUNGS,
)
from rl_curriculum.curriculum261_pairs import generate_pair
from rl_curriculum.curriculum261_r3_calibration import (
    fit_matrix_from_records,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    RouteCPreprocessor,
)
from rl_curriculum.curriculum261_r4_param_pack import (
    C1_D3_CANDIDATES,
    C3_D3_CANDIDATES,
)
from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG, _synthetic_probe_df
from rl_curriculum.curriculum261_r4_preprocessing import (
    OBSERVATION_SPACE_SEMANTICS_V2,
    RouteCPreprocessingEnvV2,
    RouteCPreprocessorV2,
    adversarial_out_of_range_probe,
    build_fit_manifest_entries,
    fit_manifest_multiset_hash,
    parameter_state_hash,
    validate_observation_space_v2,
)

_OVERRIDE = {
    "c1_opportunity": {"D3": dict(C1_D3_CANDIDATES["c1_b_edge_up2"])},
    "c3_cost": {"D3": dict(C3_D3_CANDIDATES["c3_c_alpha_strong"])},
}


@pytest.fixture(scope="module")
def fitted_v2(tmp_path_factory):
    records = [
        generate_pair(f, r, 0, namespace="preprocess_fit_design_r4",
                      rung_params_override=_OVERRIDE)
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    entries = build_fit_manifest_entries(
        records, "preprocess_fit_design_r4", "r4pk-test")
    inner = RouteCPreprocessor.build_and_fit(
        fit_matrix_from_records(records))
    v2 = RouteCPreprocessorV2(inner, entries, "preprocess_fit_design_r4")
    env_path = tmp_path_factory.mktemp("envelope") / "e.json"
    v2.serialize_envelope(env_path)
    return v2, records, env_path


# ---------------------------------------------------------- 空间合同
def test_observation_space_unbounded_features_position_01(fitted_v2):
    v2, records, _ = fitted_v2
    scaled = v2.transform_episode_df(records[0].episodes["A"].df)
    env = _build_env(v2, scaled)
    sp = env.observation_space
    assert sp.shape == (9,)
    assert str(sp.dtype) == "float32"
    assert np.all(np.isinf(sp.low[:8])) and sp.low[-1] == 0.0
    assert np.all(np.isinf(sp.high[:8])) and sp.high[-1] == 1.0


def test_extreme_values_accepted_not_clipped(fitted_v2):
    v2, _, _ = fitted_v2
    adv = adversarial_out_of_range_probe(v2, EVAL_CFG)
    assert adv["pass"] is True
    assert adv["max_transformed_feature"] > 10.0
    assert adv["min_transformed_feature"] < -10.0
    assert adv["validation"]["wrapper_pass_through_bitwise"] is True
    # 合成 ±13 探针同样通过
    scaled = v2.transform_episode_df(
        _synthetic_probe_df(v2.inner.fitted_state()))
    rep = validate_observation_space_v2(
        [scaled], [scaled], EVAL_CFG, [11], context="test_extreme")
    assert rep["pass"] is True


def test_real_episodes_finite_and_position_identity(fitted_v2):
    v2, records, _ = fitted_v2
    dfs = [v2.transform_episode_df(r.episodes[s].df)
           for r in records[:4] for s in ("A", "B")]
    rep = validate_observation_space_v2(
        dfs, dfs, EVAL_CFG,
        [int(r.episodes[s].spec.seed) for r in records[:4]
         for s in ("A", "B")], context="test_real")
    assert rep["pass"] is True
    assert rep["position_slot_valid"] is True


def test_sb3_sees_outer_space(fitted_v2):
    """check_env 与 PPO model 构建看到的必须是 outer 无界空间。"""
    pytest.importorskip("stable_baselines3")
    from stable_baselines3 import PPO
    from stable_baselines3.common.env_checker import check_env

    v2, records, _ = fitted_v2
    scaled = v2.transform_episode_df(records[0].episodes["A"].df)
    env = _build_env(v2, scaled)
    check_env(env, warn=True)  # 不 raise 即接受无界空间
    model = PPO("MlpPolicy", env, n_steps=64, batch_size=64, seed=3,
                policy_kwargs=dict(net_arch=[16, 16]), verbose=0)
    model.learn(total_timesteps=64)
    assert np.all(np.isinf(model.observation_space.low[:8]))
    assert model.observation_space.low[-1] == 0.0
    assert model.observation_space.high[-1] == 1.0
    obs, _ = env.reset(seed=7)
    assert env.observation_space.contains(obs)
    assert float(obs[-1]) in (0.0, 1.0)


def _build_env(v2, scaled_df):
    from rl_curriculum.curriculum261_r4_preprocessing import build_v2_env

    return build_v2_env(v2, scaled_df, EVAL_CFG)


# ------------------------------------------------------- manifest/bundle
def test_manifest_order_invariant_multiset_hash(fitted_v2):
    v2, _, _ = fitted_v2
    entries = list(v2.entries)
    rng = np.random.default_rng(42)
    order = rng.permutation(len(entries))
    assert fit_manifest_multiset_hash(
        [entries[i] for i in order]) == v2.manifest_multiset_hash


def test_different_multiset_different_hash(fitted_v2):
    v2, _, _ = fitted_v2
    entries = list(v2.entries)
    assert fit_manifest_multiset_hash(
        entries + [entries[0]]) != v2.manifest_multiset_hash
    assert fit_manifest_multiset_hash(
        entries[:-1]) != v2.manifest_multiset_hash


def test_same_params_different_manifest_different_bundle(fitted_v2):
    v2, _, _ = fitted_v2
    # 重复一个 episode(其值已在 bank 内:min/max 不变 ->
    # param hash 不变),manifest 变 -> bundle 变
    entries_dup = list(v2.entries) + [v2.entries[0]]
    v2_dup = RouteCPreprocessorV2(
        v2.inner, entries_dup, v2.namespace)
    assert v2_dup.parameter_state_hash == v2.parameter_state_hash
    assert v2_dup.bundle_hash != v2.bundle_hash


def test_manifest_tamper_rejected(fitted_v2, tmp_path):
    import json

    v2, _, env_path = fitted_v2
    raw = json.loads(env_path.read_text(encoding="utf-8"))
    raw["fit_manifest"]["entries"][0]["episode_hash"] = "ce-tampered"
    p = tmp_path / "t1.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError):
        RouteCPreprocessorV2.load_envelope(p)


def test_parameter_state_tamper_rejected(fitted_v2, tmp_path):
    import json

    v2, _, env_path = fitted_v2
    raw = json.loads(env_path.read_text(encoding="utf-8"))
    raw["parameter_state"]["scaler"]["scale_"][0] += 1e-9
    p = tmp_path / "t2.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(RuntimeError):
        RouteCPreprocessorV2.load_envelope(p)


def test_reload_identity_unchanged(fitted_v2):
    v2, _, env_path = fitted_v2
    re = RouteCPreprocessorV2.load_envelope(env_path)
    assert re.bundle_hash == v2.bundle_hash
    assert re.parameter_state_hash == v2.parameter_state_hash
    assert re.manifest_multiset_hash == v2.manifest_multiset_hash
    assert re.verify()["pass"] is True


def test_staged_mixed_same_bundle(fitted_v2):
    """shuffled rows -> 同 param hash;manifest 不变 -> 同 bundle。"""
    v2, records, _ = fitted_v2
    fit_df = fit_matrix_from_records(records)
    rng = np.random.default_rng(99)
    inner_shuffled = RouteCPreprocessor.build_and_fit(
        fit_df.iloc[rng.permutation(len(fit_df))])
    v2_shuffled = RouteCPreprocessorV2(
        inner_shuffled, v2.entries, v2.namespace)
    assert v2_shuffled.parameter_state_hash == v2.parameter_state_hash
    assert v2_shuffled.bundle_hash == v2.bundle_hash


def test_parameter_state_hash_excludes_n_samples(fitted_v2):
    """n_samples_seen 不是 transform 参数:同 min/max 下不改变 V2
    param hash(§9A 字段表)。"""
    import copy

    v2, _, _ = fitted_v2
    state = v2.inner.fitted_state()
    state2 = copy.deepcopy(state)
    state2["scaler"]["n_samples_seen_"] = int(
        state2["scaler"]["n_samples_seen_"]) + 288
    assert parameter_state_hash(state) == parameter_state_hash(state2)


def test_semantics_declared(fitted_v2):
    sem = OBSERVATION_SPACE_SEMANTICS_V2
    assert sem["clip_by_pipeline"] is False
    assert sem["clip_by_wrapper"] is False
    assert sem["feature_dimensions"] == "(-inf, +inf) per feature dim"
    assert sem["position_dimension"] == "[0, 1]"
