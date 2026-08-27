"""工作包 G5:smoke 模型伪装正式模型 -> 拒绝。"""

from __future__ import annotations

import pytest

from conftest import MOCK_TRAINING_RUNNER_HASH
from rl_curriculum.attestation import (
    AttestationError,
    TrustedIssuerConfig,
    _sha256_file,
    load_attestation,
    payload_hash,
    verify_attestation,
    write_attestation,
)


def test_smoke_attestation_rejected_when_formal_disallowed(
        attested_checkpoint, mock_issuer_keypair):
    ck = attested_checkpoint["checkpoint"]
    doc = load_attestation(ck + ".rl_attestation.json")
    payload = dict(doc["payload"])
    payload["is_smoke"] = True
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        smoke_doc = write_attestation(f.name, mock_issuer_keypair, payload)
    trusted = TrustedIssuerConfig.from_keypair(
        mock_issuer_keypair,
        required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=False)
    with pytest.raises(AttestationError, match="smoke"):
        verify_attestation(
            smoke_doc, trusted=trusted, checkpoint_path=ck,
            sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
            training_manifest_sha256=(
                attested_checkpoint["training_manifest_sha256"]),
            charter_hash=attested_checkpoint["charter_hash"],
            observation_schema_hash=attested_checkpoint["sidecar"]
            ["observation_schema_hash"])


def test_smoke_allowed_only_with_explicit_policy(attested_checkpoint,
                                                 mock_issuer_keypair):
    """allow_smoke=true 的受信配置接受 smoke attestation(策略显式开启)。
    本阶段 mock 配置默认禁止 smoke。"""
    ck = attested_checkpoint["checkpoint"]
    doc = load_attestation(ck + ".rl_attestation.json")
    payload = dict(doc["payload"])
    payload["is_smoke"] = True
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        smoke_doc = write_attestation(f.name, mock_issuer_keypair, payload)
    trusted = TrustedIssuerConfig.from_keypair(
        mock_issuer_keypair,
        required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=True)
    report = verify_attestation(
        smoke_doc, trusted=trusted, checkpoint_path=ck,
        sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
        training_manifest_sha256=(
            attested_checkpoint["training_manifest_sha256"]),
        charter_hash=attested_checkpoint["charter_hash"],
        observation_schema_hash=attested_checkpoint["sidecar"]
        ["observation_schema_hash"])
    assert report["pass"]
    assert report["checks"]["smoke_policy"]


def test_formal_evaluation_disallowed_flag(attested_checkpoint,
                                           mock_issuer_keypair):
    """attestation 声明 allow_formal_evaluation=false -> 拒绝正式资格。"""
    ck = attested_checkpoint["checkpoint"]
    doc = load_attestation(ck + ".rl_attestation.json")
    payload = dict(doc["payload"])
    payload["allow_formal_evaluation"] = False
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        no_formal_doc = write_attestation(f.name, mock_issuer_keypair,
                                          payload)
    trusted = TrustedIssuerConfig.from_keypair(
        mock_issuer_keypair,
        required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH)
    with pytest.raises(AttestationError, match="未允许该 checkpoint 进入正式评估"):
        verify_attestation(
            no_formal_doc, trusted=trusted, checkpoint_path=ck,
            sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
            training_manifest_sha256=(
                attested_checkpoint["training_manifest_sha256"]),
            charter_hash=attested_checkpoint["charter_hash"],
            observation_schema_hash=attested_checkpoint["sidecar"]
            ["observation_schema_hash"])
