"""工作包 B/F:归一化 pipeline 哈希守卫(scaler 被替换即拒绝)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.observation_schema import (
    FeatureSpec,
    ObservationSchema,
    ObservationSchemaMismatchError,
)


def _schema(**kw):
    base = dict(
        features=(
            FeatureSpec("a", "close_of_bar_t", 1, False, "g1"),
            FeatureSpec("b", "close_of_bar_t", 2, False, "g2"),
        ),
        schema_version="t-v1", window_size=1,
        normalization_method="identity", normalization_pipeline_hash="identity-v1",
    )
    base.update(kw)
    return ObservationSchema(**base)


def test_replaced_scaler_rejected():
    a = _schema()
    b = _schema(normalization_pipeline_hash="zscore-fit-2026")
    assert a.observation_dim == b.observation_dim
    with pytest.raises(ObservationSchemaMismatchError, match="pipeline"):
        a.assert_same_semantics(b)


def test_replaced_method_rejected():
    with pytest.raises(ObservationSchemaMismatchError, match="归一化方法"):
        _schema().assert_same_semantics(
            _schema(normalization_method="zscore",
                    normalization_pipeline_hash="zscore-fit-2026"))


def test_sidecar_binding_rejects_pipeline_change():
    s = _schema()
    sidecar = s.sidecar_binding()
    s.assert_sidecar_binding(sidecar, context="ok")
    bad = dict(sidecar)
    bad["observation_normalization_pipeline_hash"] = "other-v2"
    with pytest.raises(ObservationSchemaMismatchError, match="pipeline"):
        s.assert_sidecar_binding(bad, context="tampered")


def test_sidecar_binding_requires_all_fields():
    s = _schema()
    sidecar = s.sidecar_binding()
    for field in list(sidecar):
        partial = {k: v for k, v in sidecar.items() if k != field}
        with pytest.raises(ObservationSchemaMismatchError, match="缺少"):
            s.assert_sidecar_binding(partial)


def test_checkpoint_observation_binding_roundtrip(formal_checkpoint, schema):
    """v2 sidecar 的 observation 绑定与 schema 完全一致(可加载)。"""
    from rl_curriculum.checkpoints import load_checkpoint_manifest

    manifest = load_checkpoint_manifest(formal_checkpoint)
    schema.assert_sidecar_binding(manifest, context="formal checkpoint")
    # 篡改有序特征名(维度不变)-> 拒绝
    bad = dict(manifest)
    names = list(bad["observation_feature_names"])
    bad["observation_feature_names"] = [names[1], names[0]] + names[2:]
    with pytest.raises(ObservationSchemaMismatchError, match="有序特征名"):
        schema.assert_sidecar_binding(bad, context="tampered order")
    # 篡改维度
    bad2 = dict(manifest)
    bad2["observation_dim"] = bad2["observation_dim"] + 1
    with pytest.raises(ObservationSchemaMismatchError, match="维度"):
        schema.assert_sidecar_binding(bad2, context="tampered dim")
