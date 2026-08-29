"""工作包 F:checkpoint 与 observation schema 绑定。"""

from __future__ import annotations

import json
import shutil

from rl_curriculum.checkpoints import save_checkpoint_manifest
from rl_curriculum.observation_schema import (
    FeatureSpec,
    ObservationSchema,
)
from tests.route_c_stage2_6_0a.conftest import run_cli


def _alt_schema(base):
    """同维度但特征顺序不同的 schema(语义错位)。"""
    return ObservationSchema(
        schema_version=base.schema_version,
        features=tuple(
            [base.features[1], base.features[0]] + list(base.features[2:])),
        window_size=base.window_size, dtype=base.dtype,
        account_slots=base.account_slots,
        includes_cost_context=base.includes_cost_context,
        normalization_method=base.normalization_method,
        normalization_pipeline_hash=base.normalization_pipeline_hash,
        nuisance_fill=base.nuisance_fill)


def test_observation_hash_mismatch_rejected(sealed_exam_env, tmp_path):
    ckpt = tmp_path / "other_schema.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(
        ckpt, checkpoint_name="other_schema",
        charter_hash=sealed_exam_env["commitment"].charter_hash,
        observation_schema=_alt_schema(sealed_exam_env["schema"]))
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5
    out = json.loads((sealed_exam_env["tmp"] / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_window_size_mismatch_rejected(sealed_exam_env, tmp_path):
    base = sealed_exam_env["schema"]
    wider = ObservationSchema(
        schema_version=base.schema_version, features=base.features,
        window_size=2, dtype=base.dtype, account_slots=base.account_slots,
        includes_cost_context=base.includes_cost_context,
        normalization_method=base.normalization_method,
        normalization_pipeline_hash=base.normalization_pipeline_hash,
        nuisance_fill=base.nuisance_fill)
    ckpt = tmp_path / "w2.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(
        ckpt, checkpoint_name="w2",
        charter_hash=sealed_exam_env["commitment"].charter_hash,
        observation_schema=wider)
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5


def test_scaling_pipeline_mismatch_rejected(sealed_exam_env, tmp_path):
    base = sealed_exam_env["schema"]
    scaled = ObservationSchema(
        schema_version=base.schema_version, features=base.features,
        window_size=base.window_size, dtype=base.dtype,
        account_slots=base.account_slots,
        includes_cost_context=base.includes_cost_context,
        normalization_method="zscore",
        normalization_pipeline_hash="zscore-fit-v9",
        nuisance_fill=base.nuisance_fill)
    ckpt = tmp_path / "zscore.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(
        ckpt, checkpoint_name="zscore",
        charter_hash=sealed_exam_env["commitment"].charter_hash,
        observation_schema=scaled)
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5


def test_candidate_adapter_validates_observation_shape(formal_checkpoint,
                                                        schema):
    """SB3 候选 act 对 shape 错位 fail closed(不吞错继续给分)。"""
    import numpy as np
    import pytest

    from rl_curriculum.charter import charter_hash
    from rl_curriculum.policies import SB3CheckpointPolicy
    from rl_curriculum.probe_charter import audit_probe_charter

    pol = SB3CheckpointPolicy(
        formal_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=schema.schema_hash(),
        schema=schema)
    pol.act(np.zeros(schema.observation_dim, dtype=np.float32))
    with pytest.raises(Exception, match="shape"):
        pol.act(np.zeros(3, dtype=np.float32))
