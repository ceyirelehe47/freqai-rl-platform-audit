"""阶段 2.6.0g 收尾:P7 无隐式 fallback(mock 通道语义保持)。"""

from __future__ import annotations

import pytest


def test_build_mock_commitment_requires_provider(mock_pack, schema, cfg,
                                                 null_qual_chain,
                                                 pack_validity_report):
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_identity import (
        MockBuilderIdentityProvider,
    )
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    keypair = Ed25519KeyPair.generate("mock-issuer-fallback")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash="mock-runner-" + "b" * 60,
        allow_smoke=False)
    kwargs = dict(
        pack=mock_pack, charter=audit_probe_charter(), schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=build_null_qualification_bindings(
            null_qual_chain["reports"]),
        power_analysis_report=null_qual_chain["power_report"],
        pack_validity_report=pack_validity_report,
    )
    with pytest.raises(ValueError, match="builder_provider"):
        build_mock_commitment(**kwargs)
    # 显式传入 Provider 成功(且执行 precommit 双跑)
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(), **kwargs)
    assert commitment.builder_run_evidence["deterministic"] is True


def test_validate_pack_ephemeral_requires_identity(mock_pack):
    from rl_curriculum.mock_sealed_exam import _validate_pack_ephemeral

    with pytest.raises(ValueError, match="builder 身份|Provider"):
        _validate_pack_ephemeral(
            mock_pack, None, None, builder_identity=None)


def test_mock_provider_run_mode_is_assembly(mock_provider):
    assert mock_provider.builder_run_mode() == "mock_payload_assembly"


def test_mock_request_carries_payload_and_mode(frozen_request):
    assert frozen_request["mode"] == "mock_payload_assembly"
    assert "mock_pack_payload" in frozen_request
