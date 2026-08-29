"""工作包 G:training attestation 签名/绑定/篡改矩阵。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rl_curriculum.attestation import (
    AttestationError,
    TrustedIssuerConfig,
    _sha256_file,
    build_attestation_payload,
    formal_eligibility_from_attestation,
    load_attestation,
    payload_hash,
    verify_attestation,
    write_attestation,
)


def _verify(attested_checkpoint, trusted, *, ckpt=None, sidecar_sha=None,
            tm_sha=None, charter=None, schema_h=None):
    ck = ckpt or attested_checkpoint["checkpoint"]
    return verify_attestation(
        load_attestation(str(Path(ck).with_name(
            Path(ck).name + ".rl_attestation.json"))),
        trusted=trusted, checkpoint_path=ck,
        sidecar_sha256=sidecar_sha or _sha256_file(
            str(Path(ck).with_name(Path(ck).name + ".rl_manifest.json"))),
        training_manifest_sha256=(
            tm_sha or attested_checkpoint["training_manifest_sha256"]),
        charter_hash=charter or attested_checkpoint["charter_hash"],
        observation_schema_hash=(
            schema_h or attested_checkpoint["sidecar"]
            ["observation_schema_hash"]))


def test_valid_mock_attestation_passes(attested_checkpoint,
                                       mock_trusted_issuer):
    report = _verify(attested_checkpoint, mock_trusted_issuer)
    assert report["pass"]
    assert report["checks"]["signature_valid"]
    assert report["checks"]["training_runner_trusted"]


def test_self_signed_attestation_rejected(attested_checkpoint, schema,
                                          mock_trusted_issuer):
    """非受信方自签名的 attestation -> 拒绝。"""
    rogue = __import__("rl_curriculum.attestation", fromlist=["Ed25519KeyPair"]
                       ).Ed25519KeyPair.generate("rogue-issuer")
    doc = load_attestation(str(Path(attested_checkpoint["checkpoint"])
                               .with_name(Path(
                                   attested_checkpoint["checkpoint"]).name
                               + ".rl_attestation.json")))
    rogue_doc = dict(doc)
    rogue_doc["signature"] = rogue.sign(doc["payload"]).hex()
    rogue_doc["public_key_pem"] = rogue.public_pem.decode()
    rogue_doc["key_fingerprint"] = rogue.fingerprint
    with pytest.raises(AttestationError, match="签名验证失败"):
        verify_attestation(
            rogue_doc, trusted=mock_trusted_issuer,
            checkpoint_path=attested_checkpoint["checkpoint"],
            sidecar_sha256=_sha256_file(
                str(Path(attested_checkpoint["checkpoint"]).with_name(
                    Path(attested_checkpoint["checkpoint"]).name
                    + ".rl_manifest.json"))),
            training_manifest_sha256=(
                attested_checkpoint["training_manifest_sha256"]),
            charter_hash=attested_checkpoint["charter_hash"],
            observation_schema_hash=schema.schema_hash())


def test_untrusted_issuer_key_rejected(attested_checkpoint, schema):
    """未受信公钥签发(issuer 配置不同)-> 拒绝。"""
    other_kp = __import__("rl_curriculum.attestation", fromlist=["Ed25519KeyPair"]
                          ).Ed25519KeyPair.generate("other-issuer")
    other_trusted = TrustedIssuerConfig.from_keypair(
        other_kp, required_training_runner_hash="mock-runner-" + "b" * 60)
    with pytest.raises(AttestationError):
        _verify(attested_checkpoint, other_trusted)


def test_checkpoint_replacement_rejected(attested_checkpoint, tmp_path,
                                         mock_trusted_issuer):
    """同一 attestation 绑定其他 checkpoint -> 拒绝。"""
    ck = Path(attested_checkpoint["checkpoint"])
    swapped = tmp_path / "swapped.zip"
    swapped.write_bytes(ck.read_bytes() + b"\x00tampered")
    (swapped.with_name(swapped.name + ".rl_manifest.json")).write_text(
        Path(str(ck) + ".rl_manifest.json").read_text())
    (swapped.with_name(swapped.name + ".rl_attestation.json")).write_text(
        Path(str(ck) + ".rl_attestation.json").read_text())
    with pytest.raises(AttestationError, match="checkpoint"):
        _verify(attested_checkpoint, mock_trusted_issuer, ckpt=str(swapped))


def test_sidecar_modification_rejected(attested_checkpoint, tmp_path,
                                       mock_trusted_issuer):
    ck = Path(attested_checkpoint["checkpoint"])
    sidecar = json.loads(Path(str(ck) + ".rl_manifest.json").read_text())
    sidecar["checkpoint_name"] = "tampered"
    tampered_sha = hashlib.sha256(
        json.dumps(sidecar).encode()).hexdigest()
    with pytest.raises(AttestationError, match="sidecar"):
        _verify(attested_checkpoint, mock_trusted_issuer,
                sidecar_sha=tampered_sha)


def test_training_manifest_tamper_rejected(attested_checkpoint,
                                           mock_trusted_issuer):
    with pytest.raises(AttestationError, match="manifest"):
        _verify(attested_checkpoint, mock_trusted_issuer,
                tm_sha="f" * 64)


def test_charter_or_schema_change_rejected(attested_checkpoint,
                                           mock_trusted_issuer):
    with pytest.raises(AttestationError, match="章程"):
        _verify(attested_checkpoint, mock_trusted_issuer,
                charter="c-different")
    with pytest.raises(AttestationError, match="observation"):
        _verify(attested_checkpoint, mock_trusted_issuer,
                schema_h="o-different")


def test_wrong_training_runner_rejected(attested_checkpoint,
                                        mock_issuer_keypair):
    wrong_runner = TrustedIssuerConfig.from_keypair(
        mock_issuer_keypair, required_training_runner_hash="other-runner")
    with pytest.raises(AttestationError, match="runner"):
        _verify(attested_checkpoint, wrong_runner)


def test_payload_tampering_rejected(attested_checkpoint, tmp_path,
                                    mock_trusted_issuer):
    """载荷被改(重算 payload_hash 也无效:签名不再匹配)。"""
    doc = load_attestation(attested_checkpoint["checkpoint"]
                           + ".rl_attestation.json")
    doc["payload"]["is_smoke"] = True
    doc["payload_hash"] = payload_hash(doc["payload"])
    path = tmp_path / "tampered_attestation.json"
    path.write_text(json.dumps(doc))
    # load_attestation 通过(payload_hash 一致),但签名验证失败
    with pytest.raises(AttestationError, match="签名"):
        verify_attestation(
            load_attestation(str(path)), trusted=mock_trusted_issuer,
            checkpoint_path=attested_checkpoint["checkpoint"],
            sidecar_sha256=_sha256_file(
                attested_checkpoint["checkpoint"] + ".rl_manifest.json"),
            training_manifest_sha256=(
                attested_checkpoint["training_manifest_sha256"]),
            charter_hash=attested_checkpoint["charter_hash"],
            observation_schema_hash=attested_checkpoint["sidecar"]
            ["observation_schema_hash"])


def test_formal_eligibility_requires_attestation(attested_checkpoint,
                                                 mock_trusted_issuer):
    out = formal_eligibility_from_attestation(
        checkpoint_path=attested_checkpoint["checkpoint"],
        sidecar_manifest=attested_checkpoint["sidecar"],
        trusted=mock_trusted_issuer,
        training_manifest_sha256=(
            attested_checkpoint["training_manifest_sha256"]),
        charter_hash=attested_checkpoint["charter_hash"],
        observation_schema_hash=attested_checkpoint["sidecar"]
        ["observation_schema_hash"])
    assert out["formal_eligible"] is True
    assert out["format_compatible"] is True
