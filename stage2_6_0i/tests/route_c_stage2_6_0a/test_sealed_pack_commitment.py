"""工作包 E/M:密封考试承诺构建与逐项验证(篡改矩阵)。
阶段 2.6.0b 更新:承诺 v2 必须绑定 trusted_issuer 与 sandbox profile
(build/verify 双侧);generator_bindings 由共享 code_hash 改为逐族
{family_version, implementation_hash, manifest_hash};checkpoint 要求
改为 attestation 驱动(缺 attestation_report 即拒绝)。"""

from __future__ import annotations

import copy
import json

import pytest

from rl_curriculum.exam_pack import materialize_pack
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
from rl_curriculum.mock_sealed_exam import build_mock_commitment
from rl_curriculum.builder_identity import MockBuilderIdentityProvider
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

_NULL_BINDINGS_CACHE: dict | None = None


def _null_bindings():
    """2.6.0c D + 2.6.0d 适配:承诺必须绑定真实 Null 资格报告;阶段
    2.6.0d 起报告为 v3 三态协议(64 seed cluster x 8 episodes),
    经共享确定性磁盘缓存生成(module 级 + 磁盘级双层缓存)。"""
    global _NULL_BINDINGS_CACHE
    if _NULL_BINDINGS_CACHE is None:
        import sys as _sys
        from pathlib import Path as _P

        _tests = _P(__file__).resolve().parents[1]
        if str(_tests) not in _sys.path:
            _sys.path.insert(0, str(_tests))
        from null_qual_cache import cached_null_qual_reports
        from rl_curriculum.evaluator import EvalConfig as _EC
        from rl_curriculum.null_qualification import (
            build_null_qualification_bindings,
        )

        _NULL_BINDINGS_CACHE = build_null_qualification_bindings(
            cached_null_qual_reports(
                probe_observation_schema(), _EC(fee=0.001)))
    return _NULL_BINDINGS_CACHE


_NULL_MATERIALS_CACHE: dict | None = None


def _materials(pack, schema, cfg):
    """v4 承诺材料(模块缓存;pack 固定 -> pack validity 确定)。"""
    global _NULL_MATERIALS_CACHE
    if _NULL_MATERIALS_CACHE is None:
        import sys as _sys
        from pathlib import Path as _P

        _tests = _P(__file__).resolve().parents[1]
        if str(_tests) not in _sys.path:
            _sys.path.insert(0, str(_tests))
        from null_qual_cache import build_commitment_null_materials

        _NULL_MATERIALS_CACHE = build_commitment_null_materials(
            pack, schema, cfg)
    return _NULL_MATERIALS_CACHE


def _build(gen_a, sandbox_profile, mock_trusted_issuer):
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_platform.versions import spec_versions

    import sys as _sys
    from pathlib import Path as _P

    _tests = _P(__file__).resolve().parents[1]
    if str(_tests) not in _sys.path:
        _sys.path.insert(0, str(_tests))
    from null_qual_cache import null_episode_specs

    charter = audit_probe_charter()
    schema = probe_observation_schema()
    cfg = EvalConfig(fee=0.001)
    # 阶段 2.6.0d:严格 Null 是考试包组成部分(每族 32 antithetic
    # pair cluster,BASE_PARAMS 与资格规范 episode_bars 一致)
    pack = ExamPack(
        name="commit_t", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 48}, 1,
                        "train", timeframe="15m"),
        ] + list(null_episode_specs()),
        timeframe="15m",
    )
    materials = _materials(pack, schema, cfg)
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        pack=pack, charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg,
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    return pack, charter, schema, cfg, commitment


def _verify(pack, charter, schema, cfg, commitment, sandbox_profile, **kw):
    return verify_sealed_commitment(
        commitment, pack=pack, charter=charter, schema=schema,
        registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
        verdict_spec=kw.pop("verdict_spec", probe_course_verdict_spec()),
        sandbox_profile=sandbox_profile,
        **{**__import__('compat_stage2_6_0f', fromlist=[
            'verify_kwargs']).verify_kwargs(), **kw})


def test_valid_commitment_verifies(gen_a, sandbox_profile,
                                   mock_trusted_issuer):
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    report = _verify(pack, charter, schema, cfg, c, sandbox_profile)
    assert report["pass"]
    assert all(report["checks"].values())


def test_commitment_hash_stable_and_json_roundtrip(gen_a, sandbox_profile,
                                                   mock_trusted_issuer):
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    h = c.commitment_hash()
    assert h.startswith("sc-")
    from rl_curriculum.sealed_exam import SealedExamCommitment

    c2 = SealedExamCommitment.from_json(c.to_json())
    assert c2.commitment_hash() == h
    _verify(pack, charter, schema, cfg, c2, sandbox_profile)


def test_missing_sandbox_profile_rejected(gen_a, sandbox_profile,
                                          mock_trusted_issuer):
    """不给 sandbox profile -> 沙箱检查直接失败(fail closed)。"""
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    with pytest.raises(SealedExamError, match="sandbox profile"):
        verify_sealed_commitment(
            c, pack=pack, charter=charter, schema=schema,
            registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
            verdict_spec=probe_course_verdict_spec(), **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs())


def test_missing_trusted_issuer_rejected(gen_a, sandbox_profile):
    """v2 承诺必须绑定受信训练签发方(缺 issuer 即构建失败)。"""
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_platform.versions import spec_versions

    charter = audit_probe_charter()
    schema = probe_observation_schema()
    pack = ExamPack(
        name="commit_no_issuer", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[EpisodeSpec("probe_segmented_drift", {"episode_bars": 48},
                              1, "train", timeframe="15m")],
        timeframe="15m",
    )
    with pytest.raises(ValueError, match="trusted_issuer"):
        build_mock_commitment(
            builder_provider=MockBuilderIdentityProvider(),
            pack=pack, charter=charter, schema=schema,
            verdict_spec=probe_course_verdict_spec(),
            eval_config=EvalConfig(fee=0.001),
            sandbox_profile=sandbox_profile)


def test_v1_commitment_rejected_by_v2_executor():
    """v1 承诺(缺沙箱/attestation/严格 Null 绑定)不得被 v2 执行器接受。"""
    from rl_curriculum.sealed_exam import (
        SEALED_EXAM_PROTOCOL,
        SealedExamCommitment,
    )

    # 2.6.0f 适配:v6 承诺必须携带自洽的全局 duration contract
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash as _ndc_hash,
    )
    # 2.6.0g 适配:v7 承诺必须携带自洽的 builder 冻结构建请求(nbr-)
    from rl_curriculum.builder_provenance import (
        frozen_build_request_hash as _nbr_hash,
    )

    _dc = {
        "format": "null-duration-contract-v1",
        "timeframe": "15m",
        "bar_duration_seconds": 900,
        "resolved_bars": 96,
        "resolved_duration_seconds": 86400,
        "resolved_duration_hours": 24.0,
        "resolution_rules_version": "rps-" + "0" * 60,
        "n_null_episodes": 1,
        "episodes_per_family": {},
    }
    _br = {
        "format": "builder-build-request-v3",
        "runner_protocol": "builder-runner-protocol-v3",
        "mode": "builder_execution",
        "builder_protocol": "null-pack-builder-protocol-v3",
        "builder_manifest_hash": "npb-" + "0" * 64,
        "pack_name": "x",
        "pack_version": "x",
        "pack_timeframe": "15m",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 32,
        "max_attempts": 8,
        "attempt_policy": {"policy": "first_pass", "max_attempts": 8},
        "params_spec": {"episode_bars": 96},
        "timeframe": "15m",
        "resolved_bars": 96,
        "resolved_duration_hours": 24.0,
        "duration_contract_hash": "ndc-" + "0" * 64,
    }

    # 2.6.0c E 适配:v3 承诺必须携带 runtime manifest/hash 才能通过
    # from_json(roundtrip);版本替换后再拒绝
    v1 = SealedExamCommitment.from_json(SealedExamCommitment(
        pack_hash="p-x", charter_hash="c-x",
        observation_schema_hash="o-x", spec_versions={},
        generator_bindings={}, evaluator_code_hash="e-x",
        counterfactual_code_hash="m-x", verdict_spec_hash="v-x",
        eval_config={},
        candidate_runtime_manifest={
            "format": "candidate-runtime-manifest-v1",
            "runtime_package_version": "placeholder",
            "worker_protocol": "candidate-worker-v2",
            "files": {"__init__.py": "0" * 64}},
        candidate_runtime_hash="rt-" + "0" * 64,
        null_qualification_spec_hash="nqs-" + "0" * 64,
        null_power_analysis={
            "report_hash": "npa-" + "0" * 64,
            "code_hash": "npac-" + "0" * 64,
            "scenario_spec_hash": "npss-" + "0" * 64,
            "public_summary": {"targets_met": True,
                                "required_scenario_count": 54}},
        pack_builder_code_hash="npb-" + "0" * 64,
        null_duration_contract=_dc,
        null_duration_contract_hash=_ndc_hash(_dc),
        builder_build_request=_br,
        builder_build_request_hash=_nbr_hash(_br),
        builder_run_evidence={
            "evidence_hash": "bre-" + "0" * 64,
            "mode": "builder_execution",
            "output_pack_hash": "p-x",
            "deterministic": True,
            "deterministic_input_hash": "edi-" + "0" * 64,
            "runtime_bundle_hash": "rbm-" + "0" * 64,
            "thread_policy": "threads_forbidden_clone_denied",
            "access_summary_hash": "acs-" + "0" * 64,
            "process_tree_policy": "single_builder_process",
            "child_process_count": 0,
            "exec_count": 0,
            "runner_isolation": "isolated_process",
        },
        builder_attempt_policy={"policy": "first_pass",
                                "max_attempts": 8},
        pack_validity={
            "report_hash": "npv-" + "0" * 64,
            "pack_hash": "p-x",
            "public_summary": {"verdict": "PACK_VALID"}}).to_json())
    for old_version in ("sealed-exam-commitment-v1",
                        "sealed-exam-commitment-v2"):
        text = v1.to_json().replace(SEALED_EXAM_PROTOCOL, old_version)
        with pytest.raises(SealedExamError, match="已弃用|协议版本"):
            SealedExamCommitment.from_json(text)


# ---------------------------------------------------------------- 篡改矩阵
def test_pack_seed_tamper_rejected(gen_a, sandbox_profile,
                                   mock_trusted_issuer):
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    pack.episodes[0] = type(pack.episodes[0])(
        pack.episodes[0].family, {"episode_bars": 48}, 999,
        pack.episodes[0].split, timeframe="15m")
    with pytest.raises(SealedExamError, match="pack hash"):
        _verify(pack, charter, schema, cfg, c, sandbox_profile)


def test_fee_tamper_rejected(gen_a, sandbox_profile, mock_trusted_issuer):
    from rl_curriculum.evaluator import EvalConfig

    pack, charter, schema, _cfg, c = _build(gen_a, sandbox_profile,
                                            mock_trusted_issuer)
    tampered_cfg = EvalConfig(fee=0.002)
    with pytest.raises(SealedExamError, match="EvalConfig"):
        _verify(pack, charter, schema, tampered_cfg, c, sandbox_profile)


def test_observation_order_tamper_rejected(gen_a, sandbox_profile,
                                           mock_trusted_issuer):
    pack, charter, _schema, cfg, c = _build(gen_a, sandbox_profile,
                                            mock_trusted_issuer)
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
        _verify(pack, charter, reordered, cfg, c, sandbox_profile)


def test_generator_implementation_tamper_rejected(gen_a, sandbox_profile,
                                                  mock_trusted_issuer):
    """逐族实现指纹被替换 -> 该族校验失败(不再是共享 generators.py 哈希)。"""
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    fam = pack.episodes[0].family
    c2 = copy.deepcopy(c)
    c2.generator_bindings[fam]["implementation_hash"] = "gi-tampered"
    with pytest.raises(SealedExamError, match="实现哈希不匹配"):
        _verify(pack, charter, schema, cfg, c2, sandbox_profile)
    c3 = copy.deepcopy(c)
    c3.generator_bindings[fam]["manifest_hash"] = "0" * 64
    with pytest.raises(SealedExamError, match="manifest 哈希不匹配"):
        _verify(pack, charter, schema, cfg, c3, sandbox_profile)


def test_generator_version_tamper_rejected(gen_a, sandbox_profile,
                                           mock_trusted_issuer):
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    c2 = copy.deepcopy(c)
    fam = pack.episodes[0].family
    c2.generator_bindings[fam]["family_version"] = "probe-A-v999"
    with pytest.raises(SealedExamError, match="版本不匹配"):
        _verify(pack, charter, schema, cfg, c2, sandbox_profile)


def test_evaluator_code_tamper_rejected(gen_a, sandbox_profile,
                                        mock_trusted_issuer):
    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    with pytest.raises(SealedExamError, match="evaluator 代码哈希"):
        _verify(pack, charter, schema, cfg, c, sandbox_profile,
                evaluator_hash="e-tampered")


def test_verdict_threshold_tamper_rejected(gen_a, sandbox_profile,
                                           mock_trusted_issuer):
    from rl_curriculum.verdict_spec import CourseVerdictSpec

    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    changed = CourseVerdictSpec(
        version=probe_course_verdict_spec().version,
        seed_pass_ratio_min=0.99)  # 阈值变化 -> 新判定器哈希
    with pytest.raises(SealedExamError, match="判定器哈希"):
        _verify(pack, charter, schema, cfg, c, sandbox_profile,
                verdict_spec=changed)


def test_charter_tamper_rejected(gen_a, sandbox_profile,
                                 mock_trusted_issuer):
    pack, _charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                            mock_trusted_issuer)
    tampered = copy.deepcopy(audit_probe_charter())
    tampered["fee"] = 0.002
    with pytest.raises(SealedExamError, match="charter hash"):
        _verify(pack, tampered, schema, cfg, c, sandbox_profile)


def test_unbound_family_rejected(gen_a, sandbox_profile,
                                 mock_trusted_issuer):
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_platform.versions import spec_versions
    from rl_curriculum.charter import charter_hash

    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    # 用受限注册表重建承诺:只绑定 probe_segmented_drift(null 三族
    # 材料按本 pack 就地计算,承诺结构完整;绑定面缺其它可交易族)
    from null_qual_cache import build_commitment_null_materials,         null_episode_specs

    limited = {"probe_segmented_drift":
               DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]}
    loc_pack = ExamPack(
        name="c2", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[EpisodeSpec("probe_segmented_drift",
                              {"episode_bars": 48}, 1, "train",
                              timeframe="15m")]
        + list(null_episode_specs()),
        timeframe="15m")
    loc_materials = build_commitment_null_materials(
        loc_pack, schema, cfg)
    c = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        pack=loc_pack,
        charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg,
        registry=limited, sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
        null_qualification_bindings=loc_materials["bindings"],
        power_analysis_report=loc_materials["power_analysis_report"],
        pack_validity_report=loc_materials["pack_validity_report"])
    pack2 = ExamPack(
        name="commit_t2", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter), spec_versions=spec_versions(),
        episodes=[EpisodeSpec("probe_smooth_latent_drift",
                              {"episode_bars": 48}, 7, "family_holdout",
                              timeframe="15m")],
        timeframe="15m")
    with pytest.raises(SealedExamError, match="未绑定"):
        _verify(pack2, charter, schema, cfg, c, sandbox_profile)


def test_checkpoint_requirements_verified(gen_a, sandbox_profile,
                                          mock_trusted_issuer,
                                          attested_checkpoint):
    """checkpoint 正式资格由受信 attestation 驱动(sidecar 自声明无效)。"""
    from pathlib import Path

    from rl_curriculum.attestation import (
        load_attestation,
        verify_attestation,
    )
    from rl_curriculum.checkpoints import (
        load_checkpoint_manifest,
        sha256_file,
    )
    from rl_curriculum.sealed_exam import verify_checkpoint_requirements

    pack, charter, schema, cfg, c = _build(gen_a, sandbox_profile,
                                           mock_trusted_issuer)
    ckpt = attested_checkpoint["checkpoint"]
    c.checkpoint_requirements["checkpoint_sha256"] = sha256_file(ckpt)
    manifest = load_checkpoint_manifest(ckpt)
    # 未提供通过验证的 attestation 报告 -> 拒绝(自声明 boolean 无效)
    with pytest.raises(SealedExamError, match="attestation"):
        verify_checkpoint_requirements(
            c, manifest, checkpoint_sha256=sha256_file(ckpt))
    att_doc = load_attestation(
        str(Path(str(ckpt) + ".rl_attestation.json")))
    att_report = verify_attestation(
        att_doc, trusted=attested_checkpoint["trusted_issuer"],
        checkpoint_path=ckpt,
        sidecar_sha256=sha256_file(str(ckpt) + ".rl_manifest.json"),
        training_manifest_sha256=attested_checkpoint[
            "training_manifest_sha256"],
        charter_hash=c.charter_hash,
        observation_schema_hash=c.observation_schema_hash)
    rep = verify_checkpoint_requirements(
        c, manifest, checkpoint_sha256=sha256_file(ckpt),
        attestation_report=att_report)
    assert rep["pass"]
    assert rep["checks"]["trusted_attestation"] is True
    # 换一个 checkpoint(SHA 不符)-> 拒绝
    with pytest.raises(SealedExamError, match="SHA-256"):
        verify_checkpoint_requirements(
            c, manifest, checkpoint_sha256="deadbeef",
            attestation_report=att_report)
