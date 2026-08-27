"""工作包 N:固定维度 SB3 checkpoint 真实执行全部 G4 考试(允许挂科)。"""

from __future__ import annotations

import numpy as np

from rl_curriculum.charter import charter_hash
from rl_curriculum.observation_schema import ObservationSchemaError
from rl_curriculum.policies import SB3CheckpointPolicy
from rl_curriculum.probe_charter import audit_probe_charter
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS

SMALL = {"episode_bars": 64, "drift_bps_range": [18.0, 30.0],
         "vol_bps_range": [20.0, 32.0]}


def _cand(formal_checkpoint, schema):
    return SB3CheckpointPolicy(
        formal_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=schema.schema_hash(),
        schema=schema)


def _eps(gen_a, seeds=(141, 142, 143)):
    return [gen_a.generate(dict(SMALL), seed=s, timeframe="15m")
            for s in seeds]


def test_sb3_runs_all_g4_exams(formal_checkpoint, gen_a, cfg, schema):
    """全部 G4 考试真实支持 SB3 固定维度模型:每项都产出判定,
    不因维度/接口崩溃;checkpoint 可以挂科。"""
    from rl_curriculum.counterfactual import (
        test_common_prefix_future_suffix,
        test_cost_monotonicity,
        test_episode_length_invariance,
        test_initial_price_invariance,
        test_nuisance_slot_injection,
        test_nuisance_slot_shuffle,
        test_null_control,
        test_price_scale_invariance,
        test_regime_order_randomization,
        test_signal_ablation,
        test_time_shift_invariance,
        test_trend_direction_mirror,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    cand = _cand(formal_checkpoint, schema)
    eps = _eps(gen_a)
    base = eps[0]
    gen_a_r = DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]
    nulls = {
        fam: [DEFAULT_GENERATOR_REGISTRY[fam].generate(
            dict(SMALL), seed=s, split="null_control", timeframe="15m")
            for s in (144, 145)]
        for fam in ("probe_null_sign", "probe_null_block",
                    "probe_null_volstate")
    }
    results = {
        "common_prefix": test_common_prefix_future_suffix(
            gen_a_r, cand, base, cfg, schema),
        "price_scale": test_price_scale_invariance(cand, base, cfg, schema),
        "initial_price": test_initial_price_invariance(
            gen_a_r, cand, base, cfg, schema),
        "episode_length": test_episode_length_invariance(
            gen_a_r, cand, base, cfg, schema),
        "time_shift": test_time_shift_invariance(cand, base, cfg, schema),
        "regime_order": test_regime_order_randomization(
            gen_a_r, cand, base, cfg, schema),
        "nuisance_injection": test_nuisance_slot_injection(
            cand, eps, cfg, schema),
        "nuisance_shuffle": test_nuisance_slot_shuffle(
            cand, eps, cfg, schema),
        "signal_ablation": test_signal_ablation(
            cand, eps, cfg, schema, signal_group="trend"),
        "trend_mirror": test_trend_direction_mirror(cand, eps, cfg, schema),
        "cost_monotonicity": test_cost_monotonicity(
            cand, base, cfg, schema),
        "null_control": test_null_control(cand, nulls, cfg, schema),
    }
    # 全部考试真实执行(每项都有明确 pass/fail,不抛异常)
    for name, r in results.items():
        assert r is not None and isinstance(r.pass_, bool), name
    # nuisance 考试 shape 恒定
    assert results["nuisance_injection"].extra[
        "observation_shape"] == [schema.observation_dim]


def test_sb3_obs_dim_constant_across_exams(formal_checkpoint, gen_a, cfg,
                                           schema):
    """所有考试中 SB3 候选的 observation 维度恒等于 schema 维度。"""
    from rl_curriculum.evaluator import run_observation_episode

    cand = _cand(formal_checkpoint, schema)
    dims = set()
    for ep in _eps(gen_a, seeds=(146,)):
        r, a, obs = run_observation_episode(
            cand, ep, cfg, schema, return_actions=True,
            return_observations=True)
        dims |= {o.shape[0] for o in obs}
    assert dims == {schema.observation_dim}


def test_sb3_extra_column_does_not_change_shape(formal_checkpoint, gen_a,
                                                cfg, schema):
    """评估器不因新增列改变 observation shape:额外列直接 EXAM_INVALID
    (EvaluationError),绝不静默扩维。"""
    import pytest

    from rl_curriculum.evaluator import (
        EvaluationError,
        run_observation_episode,
    )

    cand = _cand(formal_checkpoint, schema)
    ep = gen_a.generate(dict(SMALL), seed=147, timeframe="15m")
    ep.df["extra_col"] = np.zeros(len(ep.df))
    with pytest.raises((EvaluationError, ObservationSchemaError)):
        run_observation_episode(cand, ep, cfg, schema)
