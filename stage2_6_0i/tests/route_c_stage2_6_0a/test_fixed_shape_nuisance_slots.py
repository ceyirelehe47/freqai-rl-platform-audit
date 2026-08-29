"""工作包 I1/I4:固定维度 nuisance 槽位考试(shape 恒定)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.counterfactual import (
    _assert_same_observation_shape,
    test_nuisance_slot_injection,
    test_nuisance_slot_shuffle,
)
from rl_curriculum.observation_schema import \
    ObservationSchemaError  # noqa: F401
from rl_curriculum.evaluator import EvaluationError
from rl_curriculum.policies import RuleTrendPolicy
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def _eps(gen_a, seeds=(31, 32, 33)):
    return [gen_a.generate(dict(TRAIN_PARAMS), seed=s, timeframe="15m")
            for s in seeds]


def test_nuisance_injection_keeps_shape(gen_a, cfg, schema):
    eps = _eps(gen_a)
    r = test_nuisance_slot_injection(RuleTrendPolicy(), eps, cfg, schema)
    assert r.pass_
    assert r.extra["observation_shape"] == [schema.observation_dim]
    assert r.extra["nuisance_slots"] == list(schema.nuisance_feature_names)


def test_nuisance_shuffle_keeps_shape_and_market_features(gen_a, cfg, schema):
    eps = _eps(gen_a, seeds=(34, 35))
    r = test_nuisance_slot_shuffle(RuleTrendPolicy(), eps, cfg, schema)
    assert r.pass_
    # 正式市场特征未被触碰
    assert set(r.extra["market_features_untouched"]) == {
        "ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"}


def test_no_new_columns_in_variants(gen_a, cfg, schema):
    """变体 df 的列集合与原 Episode 完全相同(不新增列)。"""
    from rl_curriculum.counterfactual import _nuisance_variant_df

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=36, timeframe="15m")
    rng = np.random.default_rng(55)
    df_v = _nuisance_variant_df(
        ep, schema, transform=lambda arr, r: r.standard_normal(len(arr)),
        seed=55)
    assert list(df_v.columns) == list(ep.df.columns)
    # 只有 nuisance 槽位内容变化,市场特征逐位不变
    for col in ("ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio"):
        np.testing.assert_array_equal(df_v[col].to_numpy(),
                                      ep.df[col].to_numpy())
    # nuisance 槽位内容确实变化
    assert not np.allclose(df_v["nuisance_0"].to_numpy(),
                           ep.df["nuisance_0"].to_numpy())


def test_dimension_change_is_exam_invalid_not_model_failure(schema):
    """I4:维度变化映射 EXAM_INVALID(ValueError 由上游包装),不是挂科。"""
    schema_shape = (9,)
    base = [np.zeros(schema_shape, dtype=np.float32) for _ in range(3)]
    variant = [np.zeros((8,), dtype=np.float32) for _ in range(3)]
    with pytest.raises(ValueError, match="EXAM_INVALID"):
        _assert_same_observation_shape(
            schema, base, variant, test_name="t")
    # None 容忍(harness 路径)
    _assert_same_observation_shape(schema, None, variant, test_name="t")


def test_extra_column_variant_fails_closed_in_exams(gen_a, cfg, schema):
    """旧式"加列注入"在固定维度 schema 下直接 EXAM_INVALID(fail closed),
    不产生模型成绩。"""
    from rl_curriculum.counterfactual import _wrap
    from rl_curriculum.evaluator import run_observation_episode

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=37, timeframe="15m")
    df = ep.df.copy()
    df["noise_9"] = np.zeros(len(df))
    variant = _wrap(ep, df, None, "legacy_injection")
    with pytest.raises((EvaluationError, ObservationSchemaError)):
        run_observation_episode(RuleTrendPolicy(), variant, cfg, schema)


def test_sb3_candidate_runs_nuisance_exams_fixed_shape(formal_checkpoint,
                                                        gen_a, cfg, schema):
    """固定维度 SB3 候选真实执行 nuisance 考试(shape 不变,可挂科)。"""
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.policies import SB3CheckpointPolicy
    from rl_curriculum.probe_charter import audit_probe_charter

    cand = SB3CheckpointPolicy(
        formal_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=schema.schema_hash(),
        schema=schema)
    eps = _eps(gen_a, seeds=(38, 39))
    r1 = test_nuisance_slot_injection(cand, eps, cfg, schema)
    assert r1.extra["observation_shape"] == [schema.observation_dim]
    r2 = test_nuisance_slot_shuffle(cand, eps, cfg, schema)
    assert r2.extra["observation_shape"] == [schema.observation_dim]
