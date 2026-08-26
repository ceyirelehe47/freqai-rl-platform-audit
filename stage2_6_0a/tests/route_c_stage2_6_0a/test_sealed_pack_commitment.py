"""工作包 E/M:密封考试承诺构建与逐项验证(篡改矩阵)。"""

from __future__ import annotations

import copy
import json

import pytest

from rl_curriculum.exam_pack import materialize_pack
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.mock_sealed_exam import build_mock_commitment
from rl_curriculum.probe_charter import (
    audit_probe_charter,
    probe_observation_schema,
)
from rl_curriculum.sealed_exam import (
    SealedExamError,
    verify_sealed_commitment,
)
from rl_curriculum.verdict_spec import probe_course_verdict_spec
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def _build(gen_a):
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_platform.versions import spec_versions

    charter = audit_probe_charter()
    schema = probe_observation_schema()
    cfg = EvalConfig(fee=0.001)
    pack = ExamPack(
        name="commit_t", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 48}, 1,
                        "train", timeframe="15m"),
            EpisodeSpec("probe_null_sign", {"episode_bars": 48}, 2,
                        "null_control", timeframe="15m"),
        ],
        timeframe="15m",
    )
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg)
    return pack, charter, schema, cfg, commitment


def _verify(pack, charter, schema, cfg, commitment, **kw):
    return verify_sealed_commitment(
        commitment, pack=pack, charter=charter, schema=schema,
        registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
        verdict_spec=kw.pop("verdict_spec", probe_course_verdict_spec()),
        **kw)


def test_valid_commitment_verifies(gen_a):
    pack, charter, schema, cfg, c = _build(gen_a)
    report = _verify(pack, charter, schema, cfg, c)
    assert report["pass"]
    assert all(report["checks"].values())


def test_commitment_hash_stable_and_json_roundtrip(gen_a):
    pack, charter, schema, cfg, c = _build(gen_a)
    h = c.commitment_hash()
    assert h.startswith("sc-")
    from rl_curriculum.sealed_exam import SealedExamCommitment

    c2 = SealedExamCommitment.from_json(c.to_json())
    assert c2.commitment_hash() == h
    _verify(pack, charter, schema, cfg, c2)


# ---------------------------------------------------------------- 篡改矩阵
def test_pack_seed_tamper_rejected(gen_a):
    pack, charter, schema, cfg, c = _build(gen_a)
    pack.episodes[0] = type(pack.episodes[0])(
        pack.episodes[0].family, {"episode_bars": 48}, 999,
        pack.episodes[0].split, timeframe="15m")
    with pytest.raises(SealedExamError, match="pack hash"):
        _verify(pack, charter, schema, cfg, c)


def test_fee_tamper_rejected(gen_a):
    from rl_curriculum.evaluator import EvalConfig

    pack, charter, schema, _cfg, c = _build(gen_a)
    tampered_cfg = EvalConfig(fee=0.002)
    with pytest.raises(SealedExamError, match="EvalConfig"):
        _verify(pack, charter, schema, tampered_cfg, c)


def test_observation_order_tamper_rejected(gen_a):
    pack, charter, _schema, cfg, c = _build(gen_a)
    from rl_curriculum.observation_schema import FeatureSpec, ObservationSchema

    old = probe_observation_schema()
    reordered = ObservationSchema(
        schema_version=old.schema_version,
        features=tuple(
            [old.features[1], old.features[0]] + list(old.features[2:])),
        window_size=old.window_size, dtype=old.dtype,
        account_slots=old.account_slots,
        includes_cost_context=old.includes_cost_context,
        normalization_method=old.normalization_method,
        normalization_pipeline_hash=old.normalization_pipeline_hash,
        nuisance_fill=old.nuisance_fill)
    with pytest.raises(SealedExamError, match="observation schema hash"):
        _verify(pack, charter, reordered, cfg, c)


def test_generator_code_tamper_rejected(gen_a):
    pack, charter, schema, cfg, c = _build(gen_a)
    c2 = copy.deepcopy(c)
    fam = pack.episodes[0].family
    c2.generator_bindings[fam]["code_hash"] = "m-tampered"
    with pytest.raises(SealedExamError, match="生成器代码哈希"):
        _verify(pack, charter, schema, cfg, c2)


def test_generator_version_tamper_rejected(gen_a):
    pack, charter, schema, cfg, c = _build(gen_a)
    c2 = copy.deepcopy(c)
    fam = pack.episodes[0].family
    c2.generator_bindings[fam]["family_version"] = "probe-A-v999"
    with pytest.raises(SealedExamError, match="版本不匹配"):
        _verify(pack, charter, schema, cfg, c2)


def test_evaluator_code_tamper_rejected(gen_a):
    pack, charter, schema, cfg, c = _build(gen_a)
    with pytest.raises(SealedExamError, match="evaluator 代码哈希"):
        _verify(pack, charter, schema, cfg, c, evaluator_hash="e-tampered")


def test_verdict_threshold_tamper_rejected(gen_a):
    from rl_curriculum.verdict_spec import CourseVerdictSpec

    pack, charter, schema, cfg, c = _build(gen_a)
    changed = CourseVerdictSpec(
        version=probe_course_verdict_spec().version,
        seed_pass_ratio_min=0.99)  # 阈值变化 -> 新判定器哈希
    with pytest.raises(SealedExamError, match="判定器哈希"):
        _verify(pack, charter, schema, cfg, c, verdict_spec=changed)


def test_charter_tamper_rejected(gen_a):
    pack, _charter, schema, cfg, c = _build(gen_a)
    tampered = copy.deepcopy(audit_probe_charter())
    tampered["fee"] = 0.002
    with pytest.raises(SealedExamError, match="charter hash"):
        _verify(pack, tampered, schema, cfg, c)


def test_unbound_family_rejected(gen_a):
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_platform.versions import spec_versions
    from rl_curriculum.charter import charter_hash

    pack, charter, schema, cfg, c = _build(gen_a)
    # 用受限注册表重建承诺:只绑定 probe_segmented_drift
    limited = {"probe_segmented_drift":
               DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]}
    c = build_mock_commitment(
        pack=ExamPack(
            name="c2", version="v1", visibility="mock_hidden",
            charter_hash=charter_hash(charter),
            spec_versions=spec_versions(),
            episodes=[EpisodeSpec("probe_segmented_drift",
                                  {"episode_bars": 48}, 1, "train",
                                  timeframe="15m")],
            timeframe="15m"),
        charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg,
        registry=limited)
    pack2 = ExamPack(
        name="commit_t2", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter), spec_versions=spec_versions(),
        episodes=[EpisodeSpec("probe_smooth_latent_drift",
                              {"episode_bars": 48}, 7, "family_holdout",
                              timeframe="15m")],
        timeframe="15m")
    with pytest.raises(SealedExamError, match="未绑定"):
        _verify(pack2, charter, schema, cfg, c)


def test_checkpoint_requirements_verified(gen_a, formal_checkpoint):
    from rl_curriculum.checkpoints import (
        load_checkpoint_manifest,
        sha256_file,
    )
    from rl_curriculum.sealed_exam import verify_checkpoint_requirements

    pack, charter, schema, cfg, c = _build(gen_a)
    c.checkpoint_requirements["checkpoint_sha256"] = sha256_file(
        formal_checkpoint)
    manifest = load_checkpoint_manifest(formal_checkpoint)
    rep = verify_checkpoint_requirements(
        c, manifest, checkpoint_sha256=sha256_file(formal_checkpoint))
    assert rep["pass"]
    # 换一个 checkpoint(SHA 不符)-> 拒绝
    with pytest.raises(SealedExamError, match="SHA-256"):
        verify_checkpoint_requirements(
            c, manifest, checkpoint_sha256="deadbeef")
