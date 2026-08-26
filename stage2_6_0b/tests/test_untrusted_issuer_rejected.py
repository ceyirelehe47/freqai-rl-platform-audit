"""工作包 G5:不受信 issuer 签发的 attestation 被拒绝。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import MOCK_TRAINING_RUNNER_HASH
from rl_curriculum.attestation import (
    AttestationError,
    TrustedIssuerConfig,
    _sha256_file,
    load_attestation,
    verify_attestation,
)


def _full_verify(attested_checkpoint, trusted):
    ck = attested_checkpoint["checkpoint"]
    return verify_attestation(
        load_attestation(ck + ".rl_attestation.json"),
        trusted=trusted, checkpoint_path=ck,
        sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
        training_manifest_sha256=(
            attested_checkpoint["training_manifest_sha256"]),
        charter_hash=attested_checkpoint["charter_hash"],
        observation_schema_hash=attested_checkpoint["sidecar"]
        ["observation_schema_hash"])


def test_untrusted_issuer_rejected(attested_checkpoint):
    rogue = __import__("rl_curriculum.attestation", fromlist=["Ed25519KeyPair"]
                       ).Ed25519KeyPair.generate("rogue")
    rogue_trusted = TrustedIssuerConfig.from_keypair(
        rogue, required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH)
    with pytest.raises(AttestationError):
        _full_verify(attested_checkpoint, rogue_trusted)


def test_attestation_protocol_version_gated(attested_checkpoint, tmp_path):
    doc = load_attestation(attested_checkpoint["checkpoint"]
                           + ".rl_attestation.json")
    doc["payload"]["protocol"] = "training-attestation-v0"
    path = tmp_path / "old.json"
    path.write_text(json.dumps(doc))
    with pytest.raises(AttestationError, match="协议"):
        load_attestation(str(path))


def test_signature_verification_uses_trusted_key_only(attested_checkpoint,
                                                       mock_trusted_issuer):
    """签名在受信公钥下验证通过(正例,确保上面拒绝不是误伤)。"""
    report = _full_verify(attested_checkpoint, mock_trusted_issuer)
    assert report["pass"]
