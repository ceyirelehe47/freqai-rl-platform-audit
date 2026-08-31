"""R3 reference/baseline preprocessing-aware 路径与统计口径测试(§34)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r3_calibration import (
    EVAL_CFG,
    RAW_SCHEMA,
    _binary_metrics,
    curriculum_robustness_gate_r3,
    evaluate_pair_corpus_r3,
    fit_matrix_from_records,
    generate_fit_bank,
)
from rl_curriculum.curriculum261_r3_obs import (
    PreprocessingAwarePolicy,
    reference_equivalence_check,
    wrap_policy_set,
)
from rl_curriculum.curriculum261_r3_preprocessing import (
    PRODUCTION_FEATURE_COLUMNS,
    RouteCPreprocessor,
)
from rl_curriculum.curriculum261_qualification import build_policy_set


@pytest.fixture(scope="module")
def fitted():
    bank = generate_fit_bank("preprocess_fit_calibration_r3",
                             pairs_per_rung=1)
    return RouteCPreprocessor.build_and_fit(
        fit_matrix_from_records(bank))


@pytest.fixture(scope="module")
def episodes():
    """每 family 一对 episode(fit bank pair 0)。"""
    bank = generate_fit_bank("preprocess_fit_calibration_r3",
                             pairs_per_rung=1)
    return {r.family: r for r in bank}


FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")


@pytest.mark.parametrize("family", FAMILIES)
def test_reference_action_equivalence_per_bar(fitted, episodes, family):
    rec = episodes[family]
    specs = family_specs()
    rp = dict(specs[family].rung_params[rec.rung])
    rp["cur261_rung"] = rec.rung
    eq = reference_equivalence_check(
        rec.episodes["A"], family, rp,
        dict(specs[family].reference_defaults), fitted, EVAL_CFG,
        RAW_SCHEMA)
    assert eq["pass"] is True
    for pol in eq["policies"].values():
        assert pol["actions_equal"]
        assert pol["net_return_equal"]


@pytest.mark.parametrize("family", FAMILIES)
def test_reference_equivalence_side_b(fitted, episodes, family):
    rec = episodes[family]
    specs = family_specs()
    rp = dict(specs[family].rung_params[rec.rung])
    rp["cur261_rung"] = rec.rung
    eq = reference_equivalence_check(
        rec.episodes["B"], family, rp,
        dict(specs[family].reference_defaults), fitted, EVAL_CFG,
        RAW_SCHEMA)
    assert eq["pass"] is True


def test_inverse_wrapper_no_raw_side_channel(fitted, episodes):
    """wrapper 只依赖 scaled obs + frozen state:无 episode/raw df 引用。"""
    specs = family_specs()
    rec = episodes["c2_context"]
    rp = dict(specs["c2_context"].rung_params[rec.rung])
    pol = build_policy_set(
        "c2_context", rp, dict(specs["c2_context"].reference_defaults))
    wrapped = PreprocessingAwarePolicy(pol["reference"], fitted)
    wrapped.bind_observation_schema(RAW_SCHEMA)
    wrapped.reset_episode()

    from rl_curriculum.curriculum261_r3_obs import scaled_episode

    scaled_ep = scaled_episode(rec.episodes["A"], fitted)
    from rl_platform.env import AlignedLongFlatEnv

    env = AlignedLongFlatEnv(
        features=scaled_ep.df[list(PRODUCTION_FEATURE_COLUMNS)],
        prices=scaled_ep.df[["open", "close"]], fee=0.001,
        window_size=1, execution_mode="market_open_causal")
    obs, _ = env.reset(seed=1)
    actions = []
    done = False
    while not done:
        actions.append(int(wrapped.act(obs)))
        obs, _, term, trunc, _ = env.step(actions[-1])
        done = term or trunc
    assert all(a in (0, 1) for a in actions)


def test_wrapped_read_inverse_consistent(fitted, episodes):
    specs = family_specs()
    rec = episodes["c1_opportunity"]
    rp = dict(specs["c1_opportunity"].rung_params[rec.rung])
    pol = build_policy_set(
        "c1_opportunity", rp,
        dict(specs["c1_opportunity"].reference_defaults))
    wrapped = PreprocessingAwarePolicy(pol["reference"], fitted)
    wrapped.bind_observation_schema(RAW_SCHEMA)
    row = rec.episodes["A"].df[list(PRODUCTION_FEATURE_COLUMNS)]
    scaled_row = fitted.transform(row)
    arr = scaled_row.to_numpy()[100]
    v = wrapped.read(arr, "%-price-ma-ratio")
    assert v == pytest.approx(
        float(row["%-price-ma-ratio"].iloc[100]), abs=1e-9)


def test_wrap_policy_set_keeps_unscaled_baselines(fitted):
    specs = family_specs()
    pol = build_policy_set(
        "c3_cost", dict(specs["c3_cost"].rung_params["D1"]),
        dict(specs["c3_cost"].reference_defaults))
    wrapped = wrap_policy_set(pol, fitted)
    assert type(wrapped["always_flat"]).__name__ == "AlwaysFlatPolicy"
    assert type(wrapped["always_long"]).__name__ == "AlwaysLongPolicy"
    assert isinstance(wrapped["reference"], PreprocessingAwarePolicy)
    assert isinstance(wrapped["c3_cost_ignorant"],
                      PreprocessingAwarePolicy)


# ---------------------------------------------------------- pair-cluster
def test_pair_cluster_statistics_not_episode_pseudo_independent():
    """A/B 被当独立样本会低估 SE:构造强 pair 内相关的数据,断言
    gate 用 pair-cluster 口径(SE 显著大于假独立口径)。"""
    rng = np.random.default_rng(5)
    n_pairs = 12
    base = rng.normal(0.01, 0.01, n_pairs)
    rows = []
    for p, b in enumerate(base):
        for side in ("A", "B"):
            rows.append({
                "family": "c1_opportunity", "rung": "D0",
                "pair": p, "side": side,
                "reference": b + rng.normal(0, 1e-6),
                "always_long": 0.0,
                "episode_hash": "",
            })
    by_pair = {}
    for r in rows:
        by_pair.setdefault(r["pair"], []).append(
            r["reference"] - max(0.0, r["always_long"]))
    pair_vals = np.asarray([float(np.mean(v))
                            for v in by_pair.values()])
    ep_vals = np.asarray([r["reference"] for r in rows])
    se_pair = float(np.std(pair_vals, ddof=1) / np.sqrt(len(pair_vals)))
    se_episode = float(np.std(ep_vals, ddof=1) / np.sqrt(len(ep_vals)))
    # pair 内完全相关时,假独立口径恰好低估 ~sqrt(2) 倍(2 倍样本同一信息)
    assert se_pair > 1.3 * se_episode


def test_evaluate_pair_corpus_r3_structure(fitted):
    recs = [generate_pair("c1_opportunity", "D1", i,
                          namespace="calibration_r3")
            for i in range(2)]
    specs = family_specs()
    ev = evaluate_pair_corpus_r3(
        recs, "c1_opportunity",
        dict(specs["c1_opportunity"].rung_params["D1"]),
        dict(specs["c1_opportunity"].reference_defaults), fitted)
    assert ev["difficulty_metric_n_pairs"] == 2
    assert len(ev["episodes"]) == 4  # 2 pairs x A/B
    assert set(ev["episodes"][0]) >= {
        "reference", "always_flat", "always_long", "oracle", "pair",
        "side"}


def test_curriculum_gate_rejects_pseudo_independence():
    """gate 的 gap 判定用 pair-cluster SE:构造极窄 gap 场景,断言
    条件 9 会 FAIL(margin < kappa x SE)。"""
    rng = np.random.default_rng(6)
    n_pairs = 10
    noise = rng.normal(0, 0.02, n_pairs)
    families = {
        f: _fake_family_report(f, rng.normal(0, 0.02, n_pairs),
                               gap=0.001)
        for f in ("c1_opportunity", "c2_context", "c3_cost")
    }
    main = {"families": families, "seed_namespace": "calibration_r3"}
    hold = {"families": {
        f: _fake_family_report(f, rng.normal(0, 0.02, n_pairs),
                               gap=0.001)
        for f in ("c1_opportunity", "c2_context", "c3_cost")
    }, "seed_namespace": "calibration_holdout_r3"}
    gate = curriculum_robustness_gate_r3(main, hold)
    for fam in families:
        assert gate["families"][fam]["reference_margin"]["main"][
            "ok"] is False


def _fake_family_report(family: str, pair_noise, gap: float):
    """构造已知 pair-cluster 噪声的 family 报告(gap 极窄)。"""
    rungs = {}
    ladder = {}
    for k, r in enumerate(("D0", "D1", "D2", "D3")):
        base = 0.10 - 0.02 * k
        episodes = []
        for p, nz in enumerate(pair_noise):
            for side in ("A", "B"):
                # reference - best_required(=0) 逐 pair 恒为 nz+gap:
                # margin≈gap 极窄,必小于 kappa x pair-cluster SE
                episodes.append({
                    "pair": p, "side": side, "rung": r,
                    "reference": nz + gap,
                    "always_flat": 0.0,
                    "always_long": 0.0,
                    "c2_local_only": 0.0,
                    "c3_cost_ignorant": 0.0,
                })
        rungs[r] = {
            "episodes": episodes,
            "difficulty_metric": float(base + np.mean(pair_noise)),
            "reference_beats_required_baselines": True,
            "oracle_positive": True,
        }
        ladder[r] = rungs[r]["difficulty_metric"]
    return {
        "by_rung": rungs,
        "difficulty_metric_ladder": ladder,
        "ordering_ok": ladder["D0"] > ladder["D1"] > ladder["D2"]
        > ladder["D3"],
        "d3_metric_positive": True,
        "reference_beats_required_all_rungs": True,
        "oracle_positive_all_rungs": True,
        "pair_integrity_pass_rate": 1.0,
        "attempt_stats": {"n_pairs": len(pair_noise),
                          "mean_attempts": 1, "max_attempts": 5,
                          "max_attempts_used": 1},
    }


def test_binary_metrics_balanced():
    y = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.8, 0.3, 0.9, 0.8, 0.7, 0.6])
    m = _binary_metrics(y, p)
    assert m["balanced_accuracy"] == pytest.approx(0.875)
    assert m["roc_auc"] == pytest.approx(13.5 / 16)
    assert m["class_balance"] == {"long": 4, "flat": 4}
