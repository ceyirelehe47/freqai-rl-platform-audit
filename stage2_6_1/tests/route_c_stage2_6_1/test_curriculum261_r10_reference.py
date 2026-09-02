# -*- coding: utf-8 -*-
"""R10 §29 Reference Equivalence 测试:float64 roundtrip / float32
runtime roundtrip / policy reset / stateful policy / threshold-near
cases / 详细 mismatch / canonicalization 分支 / 0 unexplained。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_r6_param_pack import (
    r6_family_rung_params,
)

from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
)
from rl_curriculum.curriculum261_r10_reference import (
    POLICY_VISIBLE_REFERENCE_CONTRACT,
    SUPERVISED_LABEL_CONTRACT,
    canonical_episode,
    canonicalize_feature_matrix,
    float64_math_path_check,
    policy_visible_reference_contract_digest,
    policy_visible_reference_contract_payload,
    policy_visible_reference_contract_payload_static,
    policy_visible_reference_contract_static_digest,
    runtime_projection_path_stats,
)


def _fit_small_preproc():
    """真实 vendor pipeline 的小 fit(3 families × D0..D3 × 1 pair)。"""
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        RouteCPreprocessor,
    )

    records = [generate_pair(f, r, 0, namespace="reference_diagnostic_main_r10")
               for f in ("c1_opportunity", "c2_context", "c3_cost")
               for r in ("D0", "D1", "D2", "D3")]
    fit_df = fit_matrix_from_records(records)
    return RouteCPreprocessor.build_and_fit(fit_df), records


@pytest.fixture(scope="module")
def fitted():
    return _fit_small_preproc()


def test_float64_math_path_roundtrip_strict(fitted):
    preproc, records = fitted
    raw = np.concatenate([
        rec.episodes[s].df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(
            dtype=np.float64)
        for rec in records for s in ("A", "B")], axis=0)
    report = float64_math_path_check(raw, preproc)
    assert report["pass"], report
    assert report["max_abs_reconstruction_error"] <= 1e-14


def test_runtime_projection_deviation_within_float32_bound(fitted):
    preproc, records = fitted
    raw = np.concatenate([
        rec.episodes[s].df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(
            dtype=np.float64)
        for rec in records for s in ("A", "B")], axis=0)
    stats = runtime_projection_path_stats(raw, preproc)
    assert stats["all_within_float32_bound"], stats
    assert stats["max_abs_projection_deviation"] < 1e-7


def test_canonical_equals_wrapped_inverse_bitwise(fitted):
    """Branch B 核心:canonical = inverse(float32(transform(raw))) 与
    wrapped policy 的逆变换逐步 bitwise 相同。"""
    preproc, records = fitted
    from rl_curriculum.curriculum261_r3_obs import scaled_episode
    from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG, RAW_SCHEMA
    from rl_curriculum.curriculum261_r6_param_pack import \
        r6_family_rung_params
    from rl_curriculum.curriculum261_r3_obs import wrap_policy_set
    from rl_curriculum.evaluator import run_policy_episode

    rec = records[0]
    ep = rec.episodes["A"]
    thresholds = dict(family_specs()[rec.family].reference_defaults)
    rung_params = dict(
        r6_family_rung_params(rec.family, {})[rec.rung])
    rung_params["cur261_rung"] = rec.rung
    raw_set = build_policy_set(rec.family, rung_params, thresholds)
    wrapped = wrap_policy_set(raw_set, preproc)
    canon_ep = canonical_episode(ep, preproc)
    scaled_ep = scaled_episode(ep, preproc)
    # raw policy on canonical vs wrapped policy on scaled:逐位一致
    r_canon = run_policy_episode(
        raw_set["reference"], canon_ep, EVAL_CFG, RAW_SCHEMA,
        return_actions=True)
    r_scl = run_policy_episode(
        wrapped["reference"], scaled_ep, EVAL_CFG,
        r4_observation_schema(preproc), return_actions=True)
    assert list(r_canon[1]) == list(r_scl[1])
    assert float(r_canon[0].net_return) == float(r_scl[0].net_return)


def test_reference_equivalence_run_canonical_full(fitted):
    """正式口径(canonical vs scaled)在真实语料上 100% 相等 + legacy
    差异全部由 float32 边界解释(0 unexplained)。"""
    from rl_curriculum.curriculum261_r10_reference import (
        reference_equivalence_run_r10,
    )

    preproc, records = fitted
    report = reference_equivalence_run_r10(
        records, preproc, {}, eval_namespace="reference_diagnostic_main_r10",
        detailed=True)
    assert report["float64_math_path"]["pass"]
    assert report["canonical_scaled_full_equality"] is True
    assert report["unexplained_mismatches"] == 0
    assert report["pass"] is True
    # 每条 mismatch(如果有)都携带 §10.2 全字段
    for m in report["mismatches"]:
        assert {"family", "rung", "pair", "side", "policy", "timestep",
                "raw_action", "wrapped_action", "raw_net_return",
                "wrapped_net_return", "raw_obs_float32",
                "inverse_obs_float64",
                "per_feature_reconstruction_error", "position",
                "policy_conditions", "decision_margin_to_threshold",
                "explainable_by_float32_boundary", "bundle_hash",
                "policy_state"} <= set(m)
        assert m["explainable_by_float32_boundary"] is True


def test_canonical_episode_keeps_prices_untouched(fitted):
    """§11 硬边界:canonical episode 的价格列保持原始市场数据。"""
    preproc, records = fitted
    ep = records[0].episodes["A"]
    canon = canonical_episode(ep, preproc)
    price_cols = [c for c in ep.df.columns
                  if c not in PRODUCTION_FEATURE_COLUMNS]
    for c in price_cols:
        assert ep.df[c].tolist() == canon.df[c].tolist()
    # 特征列确实被 canonical 化(至少值域/ dtype 保持 float64)
    assert str(canon.df[list(PRODUCTION_FEATURE_COLUMNS)[0]].dtype) \
        == "float64"


def test_canonicalize_matches_definition(fitted):
    preproc, records = fitted
    raw = records[0].episodes["A"].df[
        list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(dtype=np.float64)
    canon = canonicalize_feature_matrix(raw, preproc)
    t64 = preproc.transform(records[0].episodes["A"].df[
        list(PRODUCTION_FEATURE_COLUMNS)]).to_numpy(dtype=np.float64)
    expected = preproc.inverse_features(
        t64.astype(np.float32).astype(np.float64))
    assert np.array_equal(canon, expected)


def test_policy_state_reset_semantics(fitted):
    """§10.3:同一 policy 对象重复 episode_instance/reset 后决策一致
    (无跨 episode 状态泄漏)。"""
    preproc, records = fitted
    from rl_curriculum.curriculum261_qualification import build_policy_set
    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG, RAW_SCHEMA

    rec = records[0]
    thresholds = dict(family_specs()[rec.family].reference_defaults)
    pol_set = build_policy_set(
        rec.family,
        dict(r6_family_rung_params(rec.family, {})[rec.rung],
             cur261_rung=rec.rung), thresholds)
    ref = pol_set["reference"]
    canon = canonical_episode(rec.episodes["A"], preproc)
    acts1 = []
    for pol in [ref]:
        r = run_policy_episode_safe(pol, canon, EVAL_CFG, RAW_SCHEMA)
        acts1 = r
    # 第二次(同一对象,重新 instance/reset)
    r2 = run_policy_episode_safe(ref, canon, EVAL_CFG, RAW_SCHEMA)
    assert acts1 == r2


def run_policy_episode_safe(pol, ep, cfg, schema):
    from rl_curriculum.evaluator import run_policy_episode

    r = run_policy_episode(pol, ep, cfg, schema, return_actions=True)
    return list(r[1])


def test_threshold_near_synthetic_mismatch_explainable(fitted):
    """决策边界附近的合成翻转必须被分类器判为 float32 边界可解释。"""
    from rl_curriculum.curriculum261_r10_reference import (
        _float32_explainable,
    )

    thr = {"ma_dev_thr": 0.0105}
    obs_a = np.array([0.0105 + 1e-9] * 8 + [0.0], dtype=np.float32)
    obs_b = np.array([0.0105 - 1e-9] * 8 + [0.0], dtype=np.float32)
    ok, margin = _float32_explainable(obs_a, obs_b, thr)
    assert ok, "阈值 1e-9 邻域内的差异必须落在 float32 量化界内"
    assert margin < 1e-6
    # 远离边界的大差异必须不可解释(unexplained -> FAIL)
    obs_far = np.array([0.9] * 8 + [0.0], dtype=np.float64)
    ok_far, _ = _float32_explainable(obs_a.astype(np.float64), obs_far, thr)
    assert ok_far is False


def test_contract_payloads_and_digests():
    payload = policy_visible_reference_contract_payload_static()
    assert payload["contract"] == POLICY_VISIBLE_REFERENCE_CONTRACT
    assert payload["no_raw_side_channel"] is True
    d = policy_visible_reference_contract_static_digest()
    assert d.startswith("r10pv-") and len(d) == 6 + 64
    # bundle 级 payload 含绑定字段
    class _V2:
        namespace = "preplan_fit_main_r10"
        bundle_hash = "x" * 16
        parameter_state_hash = "y" * 16

    p2 = policy_visible_reference_contract_payload(_V2())
    assert p2["bound_to_bundle"]["bundle_hash"] == "x" * 16
    d2 = policy_visible_reference_contract_digest(p2)
    assert d2.startswith("r10pv-")
    assert SUPERVISED_LABEL_CONTRACT == \
        "PolicyVisibleSupervisedLabel-v1"
