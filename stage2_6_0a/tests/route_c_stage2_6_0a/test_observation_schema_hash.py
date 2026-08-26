"""工作包 B:observation schema 哈希稳定性与语义敏感性。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.observation_schema import (
    FeatureSpec,
    ObservationSchema,
    ObservationSchemaError,
    ObservationSchemaMismatchError,
)
from rl_curriculum.probe_charter import probe_observation_schema


def _schema(**kw):
    base = dict(
        features=(
            FeatureSpec("a", "close_of_bar_t", 1, False, "g1"),
            FeatureSpec("b", "close_of_bar_t", 2, False, "g2"),
            FeatureSpec("n0", "close_of_bar_t", 1, True, "nuisance"),
        ),
        schema_version="t-v1", window_size=1,
    )
    base.update(kw)
    return ObservationSchema(**base)


def test_schema_hash_stable_and_prefixed():
    s = _schema()
    h1 = s.schema_hash()
    assert h1.startswith("o-")
    assert _schema().schema_hash() == h1  # 同构造同哈希
    assert json.loads(s.canonical())["format"] == "course-observation-schema-v1"


def test_feature_order_changes_hash():
    reordered = _schema(features=(
        FeatureSpec("b", "close_of_bar_t", 2, False, "g2"),
        FeatureSpec("a", "close_of_bar_t", 1, False, "g1"),
        FeatureSpec("n0", "close_of_bar_t", 1, True, "nuisance"),
    ))
    assert reordered.schema_hash() != _schema().schema_hash()


def test_window_dtype_nuisance_count_change_hash():
    base = _schema().schema_hash()
    assert _schema(window_size=2).schema_hash() != base
    assert _schema(dtype="float64").schema_hash() != base
    fewer = _schema(features=(
        FeatureSpec("a", "close_of_bar_t", 1, False, "g1"),
        FeatureSpec("b", "close_of_bar_t", 2, False, "g2"),
        FeatureSpec("n0", "close_of_bar_t", 1, True, "nuisance"),
        FeatureSpec("n1", "close_of_bar_t", 1, True, "nuisance"),
    ))
    assert fewer.schema_hash() != base
    assert _schema(normalization_pipeline_hash="zscore-v9").schema_hash() != base


def test_same_semantics_rejects_same_dim_different_order():
    """总维度相同但特征顺序不同 -> 拒绝(语义错位)。"""
    a = _schema()
    b = ObservationSchema(
        schema_version="t-v1",
        features=(
            FeatureSpec("b", "close_of_bar_t", 2, False, "g2"),
            FeatureSpec("a", "close_of_bar_t", 1, False, "g1"),
            FeatureSpec("n0", "close_of_bar_t", 1, True, "nuisance"),
        ), window_size=1)
    assert a.observation_dim == b.observation_dim  # 维度相同
    with pytest.raises(ObservationSchemaMismatchError, match="有序特征名不同"):
        a.assert_same_semantics(b, context="test")


def test_same_semantics_other_rejections():
    a = _schema()
    with pytest.raises(ObservationSchemaMismatchError, match="window_size"):
        a.assert_same_semantics(_schema(window_size=2))
    with pytest.raises(ObservationSchemaMismatchError, match="dtype"):
        a.assert_same_semantics(_schema(dtype="float64"))
    with pytest.raises(ObservationSchemaMismatchError, match="pipeline"):
        a.assert_same_semantics(
            _schema(normalization_pipeline_hash="other-v1"))
    with pytest.raises(ObservationSchemaMismatchError, match="nuisance"):
        a.assert_same_semantics(_schema(features=(
            FeatureSpec("a", "close_of_bar_t", 1, False, "g1"),
            FeatureSpec("b", "close_of_bar_t", 2, False, "g2"),
            FeatureSpec("n0", "close_of_bar_t", 1, True, "nuisance"),
            FeatureSpec("n1", "close_of_bar_t", 1, True, "nuisance"),
        )))
    with pytest.raises(ObservationSchemaMismatchError, match="账户"):
        a.assert_same_semantics(_schema(account_slots=("pos", "cash")))


def test_observation_array_guard():
    s = probe_observation_schema()
    good = __import__("numpy").zeros(s.observation_shape(),
                                     dtype=__import__("numpy").float32)
    s.assert_observation_array(good)
    with pytest.raises(ObservationSchemaMismatchError, match="shape"):
        s.assert_observation_array(__import__("numpy").zeros(3,
                                     dtype=__import__("numpy").float32))
    with pytest.raises(ObservationSchemaMismatchError, match="dtype"):
        s.assert_observation_array(
            __import__("numpy").zeros(s.observation_shape(),
                                      dtype=__import__("numpy").float64))


def test_schema_construction_validation():
    with pytest.raises(ObservationSchemaError):
        ObservationSchema(schema_version="", features=(
            FeatureSpec("a", "close_of_bar_t", 1),), window_size=1)
    with pytest.raises(ObservationSchemaError):
        ObservationSchema(schema_version="v", features=(), window_size=1)
    with pytest.raises(ObservationSchemaError):
        _schema(window_size=0)
    with pytest.raises(ObservationSchemaError, match="重复"):
        _schema(features=(FeatureSpec("a", "close_of_bar_t", 1),
                          FeatureSpec("a", "close_of_bar_t", 1)))


def test_probe_schema_manifest_fields():
    s = probe_observation_schema()
    payload = s.canonical_payload()
    for key in ("format", "schema_version", "features", "window_size",
                "dtype", "account_slots", "includes_cost_context",
                "normalization_method", "normalization_pipeline_hash",
                "nuisance_fill", "nuisance_slot_count", "observation_dim"):
        assert key in payload
    assert payload["observation_dim"] == 9
    assert payload["nuisance_slot_count"] == 3
    # 特征因果可用时点声明齐备(K1)
    assert all(f["available_at"] == "close_of_bar_t"
               for f in payload["features"])
    assert all("max_history_bars" in f and "signal_group" in f
               for f in payload["features"])
