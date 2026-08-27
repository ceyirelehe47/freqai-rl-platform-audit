"""工作包 C/I:沙箱 profile 绑定(profile 哈希进入 sealed commitment)。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.sandbox import (
    MAX_RESPONSE_LINE_BYTES,
    SandboxProfile,
    default_sandbox_profile,
)


def test_profile_hash_is_stable_and_content_sensitive():
    p1 = default_sandbox_profile()
    p2 = default_sandbox_profile()
    assert p1.profile_hash() == p2.profile_hash()
    p3 = SandboxProfile(
        read_exec_dirs=p1.read_exec_dirs,
        read_only_dirs=p1.read_only_dirs,
        read_write_dirs=p1.read_write_dirs,
        rlimits={**p1.rlimits, "cpu_seconds": 99})
    assert p1.profile_hash() != p3.profile_hash()
    p4 = SandboxProfile(
        read_exec_dirs=("some", "other", "dirs"),
        read_only_dirs=p1.read_only_dirs,
        read_write_dirs=p1.read_write_dirs,
        rlimits=dict(p1.rlimits))
    assert p1.profile_hash() != p4.profile_hash()


def test_profile_payload_covers_all_limits():
    p = default_sandbox_profile()
    payload = p.canonical_payload()
    for key in ("read_exec_dirs", "read_only_dirs", "read_write_dirs",
                "rlimits", "step_timeout_seconds",
                "greeting_timeout_seconds", "max_response_line_bytes"):
        assert key in payload
    assert payload["max_response_line_bytes"] == MAX_RESPONSE_LINE_BYTES


def test_commitment_rejects_profile_mismatch(sealed_exam_env):
    """profile 变化 -> 承诺校验失败(EXAM_INVALID)。"""
    from rl_curriculum.sandbox import SandboxProfile
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    other = SandboxProfile(
        read_exec_dirs=env["profile"].read_exec_dirs,
        read_only_dirs=env["profile"].read_only_dirs,
        read_write_dirs=env["profile"].read_write_dirs,
        rlimits={**env["profile"].rlimits, "nofile": 999})
    with pytest.raises(SealedExamError, match="sandbox"):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"],
            verdict_spec=env["verdict_spec"], sandbox_profile=other,
            **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs())


def test_commitment_requires_profile(sealed_exam_env):
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    with pytest.raises(SealedExamError, match="sandbox"):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"],
            verdict_spec=env["verdict_spec"], sandbox_profile=None,
            **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs())


def test_v1_commitment_rejected_with_explicit_version_error():
    """工作包 I + 2.6.0c E:v1/v2 承诺不得被 v3 执行器自动接受。"""
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS,
        SEALED_EXAM_PROTOCOL,
        SealedExamCommitment,
        SealedExamError,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v8"
    assert "sealed-exam-commitment-v1" in _DEPRECATED_PROTOCOLS
    assert "sealed-exam-commitment-v2" in _DEPRECATED_PROTOCOLS
    assert "sealed-exam-commitment-v3" in _DEPRECATED_PROTOCOLS
    payload = json.loads(sealed_exam_env_commitment_json())
    for old in ("sealed-exam-commitment-v1", "sealed-exam-commitment-v2"):
        payload["protocol_version"] = old
        with pytest.raises(SealedExamError, match="版本不兼容|弃用|不得被"):
            SealedExamCommitment.from_json(json.dumps(payload))


def sealed_exam_env_commitment_json() -> str:
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import (
        BASE_PARAMS,
        build_mock_commitment,
        build_mock_hidden_pack,
        default_eval_config,
    )
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualify_null_family,
    )
    from rl_curriculum.probe_charter import (
        audit_probe_charter,
        probe_observation_schema,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
    from rl_curriculum.attestation import Ed25519KeyPair, TrustedIssuerConfig

    kp = Ed25519KeyPair.generate("mock-issuer")
    schema = probe_observation_schema()
    cfg = default_eval_config()
    # 阶段 2.6.0d:v4 承诺绑定完整资格链(功效 + pack validity)
    from null_qual_cache import build_commitment_null_materials

    pack = build_mock_hidden_pack()
    materials = build_commitment_null_materials(pack, schema, cfg)
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        pack=pack, charter=audit_probe_charter(),
        schema=schema,
        verdict_spec=probe_course_verdict_spec(),
        eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=TrustedIssuerConfig.from_keypair(
            kp, required_training_runner_hash="mock-runner"),
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    return commitment.to_json()
