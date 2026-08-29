"""工作包 B1:评估器严格按 schema 有序 whitelist 选择特征。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.observation_schema import \
    ObservationSchemaError  # noqa: F401
from rl_curriculum.evaluator import (
    EvaluationError,
    select_features_strict,
)
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def test_select_features_uses_schema_order_not_df_order(gen_a, schema):
    """DataFrame 列序打乱:输入仍按 schema 顺序(逐位一致)。"""
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=21, split="train",
                        timeframe="15m")
    ref = select_features_strict(ep.df, schema)
    shuffled = ep.df[list(reversed(ep.df.columns))]
    got = select_features_strict(shuffled, schema)
    assert list(ref.columns) == list(schema.feature_names)
    np.testing.assert_array_equal(ref.to_numpy(), got.to_numpy())


def test_extra_column_fails_closed(gen_a, schema):
    """额外观察列(无论命名)fail closed,绝不静默加入。"""
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=22, split="train",
                        timeframe="15m")
    for name in ("factor_x", "signal_quality", "state_7", "useful_looking"):
        df = ep.df.copy()
        df[name] = 0.0
        with pytest.raises((EvaluationError, ObservationSchemaError)):
            select_features_strict(df, schema, context="extra")


def test_missing_column_fails_closed(gen_a, schema):
    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=23, split="train",
                        timeframe="15m")
    df = ep.df.drop(columns=["vol_24"])
    with pytest.raises((EvaluationError, ObservationSchemaError)):
        select_features_strict(df, schema)


def test_evaluation_with_extra_column_is_exam_invalid(gen_a, cfg, schema):
    """运行路径:额外列 -> EvaluationError(上游映射 EXAM_INVALID)。"""
    from rl_curriculum.evaluator import run_observation_episode
    from rl_curriculum.policies import AlwaysFlatPolicy

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=24, split="train",
                        timeframe="15m")
    ep.df["noise_9"] = 1.0
    with pytest.raises((EvaluationError, ObservationSchemaError)):
        run_observation_episode(AlwaysFlatPolicy(), ep, cfg, schema)


def test_price_columns_never_enter_observation(gen_a, schema):
    """价格列(open/high/low/close/volume/date)不是观察特征。"""
    from rl_curriculum.generator_api import PRICE_COLUMNS

    ep = gen_a.generate(dict(TRAIN_PARAMS), seed=25, split="train",
                        timeframe="15m")
    feats = select_features_strict(ep.df, schema)
    for col in PRICE_COLUMNS + ("date",):
        assert col not in feats.columns
