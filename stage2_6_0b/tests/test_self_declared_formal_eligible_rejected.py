"""工作包 G1:训练侧自行填写 formal_eligible 不再有效。"""

from __future__ import annotations

import json
from pathlib import Path

from rl_curriculum.attestation import formal_eligibility_from_attestation
from rl_curriculum.checkpoints import is_formal_eligible


def test_sidecar_self_declaration_alone_is_false(attested_checkpoint):
    """sidecar 自声明 formal_eligible=true(无 attestation)-> 资格 false。"""
    sidecar = dict(attested_checkpoint["sidecar"])
    sidecar["formal_eligible"] = True
    sidecar["self_declared_formal_eligible"] = True
    # is_formal_eligible(sidecar) 恒 False(自声明被忽略)
    assert is_formal_eligible(sidecar) is False


def test_sidecar_self_declared_ignored_with_attestation(attested_checkpoint,
                                                        mock_trusted_issuer,
                                                        tmp_path):
    ck = Path(attested_checkpoint["checkpoint"])
    sidecar = json.loads(Path(str(ck) + ".rl_manifest.json").read_text())
    sidecar["formal_eligible"] = True
    (tmp_path / "declared.zip").write_bytes(ck.read_bytes())
    (tmp_path / "declared.zip.rl_manifest.json").write_text(
        json.dumps(sidecar))
    out = formal_eligibility_from_attestation(
        checkpoint_path=str(tmp_path / "declared.zip"),
        sidecar_manifest=sidecar, trusted=mock_trusted_issuer,
        training_manifest_sha256=(
            attested_checkpoint["training_manifest_sha256"]),
        charter_hash=attested_checkpoint["charter_hash"],
        observation_schema_hash=attested_checkpoint["sidecar"]
        ["observation_schema_hash"],
        attestation_path=str(ck) + ".rl_attestation.json")
    assert out["formal_eligible"] is False
    assert "sidecar" in out.get("reason", "") or \
        out.get("reason") is not None


def test_missing_attestation_is_not_eligible(attested_checkpoint,
                                             mock_trusted_issuer, tmp_path):
    ck = attested_checkpoint["checkpoint"]
    out = formal_eligibility_from_attestation(
        checkpoint_path=ck, sidecar_manifest=attested_checkpoint["sidecar"],
        trusted=mock_trusted_issuer,
        training_manifest_sha256=(
            attested_checkpoint["training_manifest_sha256"]),
        charter_hash=attested_checkpoint["charter_hash"],
        observation_schema_hash=attested_checkpoint["sidecar"]
        ["observation_schema_hash"],
        attestation_path=str(tmp_path / "missing.json"))
    assert out["formal_eligible"] is False
    assert out["format_compatible"] is True


def test_v2_sidecar_cannot_become_eligible(tmp_path, schema):
    """2.6.0a 的 v2 sidecar 即使写 formal_eligible=true 也恒 false,
    且必须明确报出版本不兼容(工作包 I)。"""
    manifest = {
        "schema": "checkpoint-manifest-v2",
        "checkpoint_sha256": "0" * 64,
        "spec_versions": {},
        "charter_hash": "c-x",
        "formal_eligible": True,
        "observation_schema_hash": "o-x",
        "observation_feature_names": ["a"],
        "observation_dim": 1,
        "observation_window_size": 1,
        "observation_dtype": "float32",
        "observation_normalization_pipeline_hash": "identity-v1",
    }
    assert is_formal_eligible(manifest) is False
