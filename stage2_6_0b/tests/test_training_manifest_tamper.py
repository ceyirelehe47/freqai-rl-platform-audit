"""工作包 G5:training manifest 篡改 / 夸大预算 -> 拒绝。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rl_curriculum.attestation import (
    AttestationError,
    _sha256_file,
    load_attestation,
    verify_attestation,
)


def _verify_with_tm(attested_checkpoint, trusted, tm_sha):
    ck = attested_checkpoint["checkpoint"]
    return verify_attestation(
        load_attestation(ck + ".rl_attestation.json"),
        trusted=trusted, checkpoint_path=ck,
        sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
        training_manifest_sha256=tm_sha,
        charter_hash=attested_checkpoint["charter_hash"],
        observation_schema_hash=attested_checkpoint["sidecar"]
        ["observation_schema_hash"])


def test_inflated_budget_rejected(attested_checkpoint, mock_trusted_issuer):
    tm = json.loads(Path(
        attested_checkpoint["training_manifest_path"]).read_text())
    tm["steps"] = 99999999  # 夸大训练预算
    tampered = hashlib.sha256(
        json.dumps(tm, sort_keys=True).encode()).hexdigest()
    with pytest.raises(AttestationError, match="manifest"):
        _verify_with_tm(attested_checkpoint, mock_trusted_issuer, tampered)


def test_manifest_replaced_by_other_content(attested_checkpoint,
                                            mock_trusted_issuer):
    other = hashlib.sha256(b"completely-different-manifest").hexdigest()
    with pytest.raises(AttestationError, match="manifest"):
        _verify_with_tm(attested_checkpoint, mock_trusted_issuer, other)


def test_manifest_hash_roundtrip(attested_checkpoint):
    """合法 manifest 的哈希与 sidecar 记录一致(正例)。"""
    ck = attested_checkpoint["checkpoint"]
    sidecar = json.loads(
        Path(ck + ".rl_manifest.json").read_text(encoding="utf-8"))
    assert sidecar["training_manifest_sha256"] == \
        attested_checkpoint["training_manifest_sha256"]


def test_runner_identity_in_manifest(attested_checkpoint):
    tm = attested_checkpoint["training_manifest"]
    from conftest import MOCK_TRAINING_RUNNER_HASH

    assert tm["runner_hash"] == MOCK_TRAINING_RUNNER_HASH
