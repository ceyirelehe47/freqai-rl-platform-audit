"""R3 预处理合同测试:production 等价 / fit 隔离 / 统一 scaler /
observation 合同(§34)。"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from rl_curriculum.curriculum261_pairs import generate_pair
from rl_curriculum.curriculum261_r3_calibration import (
    fit_matrix_from_records,
    fit_preprocessor_from_bank,
    generate_fit_bank,
)
from rl_curriculum.curriculum261_r3_namespaces import (
    CURRICULUM261_R3_NAMESPACES,
    verify_r3_namespace_isolation,
)
from rl_curriculum.curriculum261_r3_obs import (
    PreprocessingAwarePolicy,
    scaled_episode,
    validate_observation_containment,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    PRODUCTION_FEATURE_COLUMNS,
    ROUTE_C_FEATURE_PREPROCESSING_VERSION,
    RouteCPreprocessor,
    build_vendor_feature_pipeline,
    numerical_equivalence_report,
    preprocessing_contract_digest,
    production_preprocessing_audit,
)
from rl_curriculum.curriculum261_api import derive261_seed
from rl_curriculum.curriculum261_qualification import build_policy_set
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r3_calibration import EVAL_CFG, RAW_SCHEMA


@pytest.fixture(scope="module")
def small_bank():
    """1 pair/rung 的小型 fit bank(快速测试用)。"""
    return generate_fit_bank("preprocess_fit_calibration_r3",
                             pairs_per_rung=1)


@pytest.fixture(scope="module")
def fitted(small_bank):
    return RouteCPreprocessor.build_and_fit(
        fit_matrix_from_records(small_bank))


def _eval_frame(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    return pd.DataFrame(
        rng.normal(size=(n, 8)) * [0.02, 0.03, 0.01, 0.02, 0.1, 0.1,
                                   0.1, 0.1]
        + [0, 0, 0, 0, 1, 1, 1, 1],
        columns=list(PRODUCTION_FEATURE_COLUMNS))


# ---------------------------------------------------------- production 等价
def test_vendor_pipeline_steps_match_expected():
    audit = production_preprocessing_audit()
    assert audit["pipeline_built_from_steps"] == [
        ("const", "VarianceThreshold"), ("scaler", "SKLearnWrapper")]
    assert audit["scaler"]["clips_out_of_train_range"] is False
    assert audit["rl_config"]["drop_ohlc_from_features"] is False
    assert audit["feature_parameters"][
        "principal_component_analysis"] is False


def test_numerical_equivalence_full(small_bank):
    fit_df = fit_matrix_from_records(small_bank)
    rep = numerical_equivalence_report(fit_df, _eval_frame())
    assert rep["pass"] is True, json.dumps(rep["checks"], default=str)
    checks = rep["checks"]
    assert checks["train_transform_bitwise_equal"]
    assert checks["eval_transform_bitwise_equal"]
    assert checks["retained_mask_equal"]
    assert checks["reload_train_bitwise_equal"]
    assert checks["reload_state_hash_equal"]
    assert checks["shuffled_rows_same_state_hash"]
    assert checks["out_of_range_linear_extrapolation"]
    assert checks["float_dtype"]


def test_out_of_train_range_not_clipped(fitted):
    """production scaler 不 clip:eval 超出 train min/max 线性外推。"""
    beyond = pd.DataFrame(
        {c: [5.0] for c in PRODUCTION_FEATURE_COLUMNS})
    out = fitted.transform(beyond).to_numpy()
    assert float(out.max()) > 1.0


def test_zero_variance_column_removed_by_vendor():
    """vendor VarianceThreshold(threshold=0) 只删常数列(独立探测)。"""
    vendor = build_vendor_feature_pipeline()
    df = pd.DataFrame({
        "%-ret-1": [1.0, 2.0, 3.0, 4.0],
        "%-ret-4": [1.0, 2.0, 3.0, 4.0],
        "%-vol-24": [1.0, 2.0, 3.0, 4.0],
        "%-price-ma-ratio": [1.0, 2.0, 3.0, 4.0],
        "%-raw_open": [1.0, 2.0, 3.0, 4.0],
        "%-raw_high": [1.0, 2.0, 3.0, 4.0],
        "%-raw_low": [1.0, 2.0, 3.0, 4.0],
        "%-constant": [7.0, 7.0, 7.0, 7.0],
    })
    out, _, _ = vendor.fit_transform(df)
    assert "%-constant" not in list(out.columns)
    assert len(out.columns) == 7


# ------------------------------------------------------------- fit 隔离
def test_transform_does_not_mutate_fit_state(fitted):
    before = fitted.state_hash()
    fitted.transform(_eval_frame(50))
    assert fitted.state_hash() == before


def test_position_not_participating_in_fit(fitted):
    state = fitted.fitted_state()
    assert len(state["input_columns"]) == 8
    assert state["position_slot"]["participates_in_fit"] is False
    assert state["position_slot"]["scaled"] is False
    assert state["position_slot"]["index"] == 8


def test_row_order_invariance(fitted, small_bank):
    fit_df = fit_matrix_from_records(small_bank)
    rng = np.random.default_rng(99)
    perm = rng.permutation(len(fit_df))
    alt = RouteCPreprocessor.build_and_fit(fit_df.iloc[perm])
    assert alt.state_hash() == fitted.state_hash()
    assert np.array_equal(
        alt.transform(fit_df).to_numpy(),
        fitted.transform(fit_df).to_numpy())


def test_feature_survival_8_of_8(fitted):
    assert fitted.retained_columns == list(PRODUCTION_FEATURE_COLUMNS)


def test_fit_rejects_extra_columns(fitted):
    bad = _eval_frame(10)
    bad["%-latent_probe"] = 1.0
    with pytest.raises(RuntimeError):
        fitted.fit(bad)


# ------------------------------------------------------------ 统一 scaler
def test_single_preprocessor_shared_across_families(small_bank):
    """C1/C2/C3 共享一个 preprocessor:同一 fit corpus -> 同一 state。"""
    p1 = RouteCPreprocessor.build_and_fit(
        fit_matrix_from_records(small_bank))
    p2 = RouteCPreprocessor.build_and_fit(
        fit_matrix_from_records(small_bank))
    assert p1.state_hash() == p2.state_hash()


def test_staged_mixed_same_multiset_same_state(small_bank):
    """staged(按 family 分组拼接)与 mixed(行交错)同 multiset 同 state。"""
    fit_df = fit_matrix_from_records(small_bank)
    rng = np.random.default_rng(7)
    staged = fit_df
    mixed = fit_df.iloc[rng.permutation(len(fit_df))]
    s1 = RouteCPreprocessor.build_and_fit(staged).state_hash()
    s2 = RouteCPreprocessor.build_and_fit(mixed).state_hash()
    assert s1 == s2


# ---------------------------------------------------------- observation
def test_observation_dim_9_position_last(fitted, small_bank):
    rec = small_bank[0]
    ep = rec.episodes["A"]
    scaled = scaled_episode(ep, fitted)
    feats = scaled.df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy()
    assert feats.shape[1] == 8
    from rl_platform.env import AlignedLongFlatEnv

    env = AlignedLongFlatEnv(
        features=scaled.df[list(PRODUCTION_FEATURE_COLUMNS)],
        prices=scaled.df[["open", "close"]],
        fee=0.001, window_size=1, execution_mode="market_open_causal")
    obs, _ = env.reset(seed=1)
    assert obs.shape == (9,)
    assert obs.dtype == np.float32
    assert float(obs[-1]) in (0.0, 1.0)  # position slot 恒 0/1


def test_position_identity_unscaled(fitted, small_bank):
    """position slot 不被 MinMax 缩放:恒 0/1 原值。"""
    from rl_platform.env import AlignedLongFlatEnv

    rec = small_bank[0]
    scaled = scaled_episode(rec.episodes["A"], fitted)
    env = AlignedLongFlatEnv(
        features=scaled.df[list(PRODUCTION_FEATURE_COLUMNS)],
        prices=scaled.df[["open", "close"]],
        fee=0.001, window_size=1, execution_mode="market_open_causal")
    obs, _ = env.reset(seed=1)
    obs2, _, _, _, _ = env.step(1)
    assert float(obs[-1]) == 0.0
    assert float(obs2[-1]) == 1.0  # 原值,非缩放值


def test_observation_containment_and_no_nan(fitted, small_bank):
    from rl_curriculum.generator_api import PRICE_COLUMNS

    recs = small_bank[:3]
    dfs = [r.episodes[s].df for r in recs for s in ("A", "B")]
    rep = validate_observation_containment(
        [fitted.transform_episode_df(d) for d in dfs],
        [d[list(PRICE_COLUMNS)] for d in dfs], EVAL_CFG,
        [int(r.episodes[s].spec.seed) for r in recs for s in ("A", "B")])
    assert rep["pass"] is True, rep["violations"]
    assert rep["position_slot_valid"] is True


# ------------------------------------------------------- serialization
def test_serialize_reload_new_process_equivalence(fitted, tmp_path):
    p = tmp_path / "state.json"
    fitted.serialize(p)
    reloaded = RouteCPreprocessor.load(p)
    ev = _eval_frame(80)
    assert np.array_equal(
        fitted.transform(ev).to_numpy(),
        reloaded.transform(ev).to_numpy())
    assert reloaded.state_hash() == fitted.state_hash()
    state = json.loads(p.read_text(encoding="utf-8"))
    assert state["contract_version"] == \
        ROUTE_C_FEATURE_PREPROCESSING_VERSION


def test_inverse_transform_precise(fitted):
    ev = _eval_frame(100)
    t = fitted.transform(ev).to_numpy()
    back = fitted.inverse_features(t)
    assert np.allclose(back, ev.to_numpy(), rtol=0, atol=1e-12)


def test_identity_binding(fitted):
    ident = fitted.identity()
    assert ident["contract_version"] == \
        ROUTE_C_FEATURE_PREPROCESSING_VERSION
    assert ident["state_hash"] == fitted.state_hash()
    assert ident["observation_dim"] == 9
    assert len(ident["retained_columns"]) == 8
    assert preprocessing_contract_digest().startswith("r3pc-")


# ------------------------------------------------------------- namespace
def test_r3_namespace_isolation():
    rep = verify_r3_namespace_isolation()
    assert rep["pass"] is True
    assert rep["name_space_disjoint"] is True


def test_r3_namespaces_derivable_others_guarded():
    assert derive261_seed("calibration_r3", "c1_opportunity", "D0", 0, 0)
    assert derive261_seed("preprocess_fit_calibration_r3",
                          "c1_opportunity", "D0", 0, 0)
    with pytest.raises(Exception):
        derive261_seed("qualification_r3", "c1_opportunity", "D0", 0, 0)
    with pytest.raises(Exception):
        derive261_seed("preprocess_fit_qualification_r3",
                       "c1_opportunity", "D0", 0, 0)
