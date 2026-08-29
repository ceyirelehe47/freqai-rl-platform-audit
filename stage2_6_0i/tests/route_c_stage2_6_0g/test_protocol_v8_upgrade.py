"""阶段 2.6.0g 收尾:协议升级断言(v8/manifest-v4/runner-v2/evidence-v1)。

旧版本材料(v7 承诺/manifest-v3/runner-protocol-v1)必须被显式拒绝;
新承诺必须绑定 Builder Run Evidence 摘要(bre-)与 mode。
"""

from __future__ import annotations

import json

import pytest


def test_protocol_constants_upgraded():
    from rl_curriculum.builder_identity import (
        _DEPRECATED_BUILDER_MANIFEST_FORMATS,
        BUILDER_MANIFEST_FORMAT,
    )
    from rl_curriculum.builder_evidence import (
        BUILDER_RUN_EVIDENCE_FORMAT,
    )
    from rl_curriculum.builder_provenance import (
        BUILD_REQUEST_FORMAT,
        BUILD_RESULT_FORMAT,
        BUILDER_RUNNER_PROTOCOL,
    )
    from rl_curriculum.formal_exam import EXAM_CLI_VERSION
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS,
        SEALED_EXAM_PROTOCOL,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v10"
    assert "sealed-exam-commitment-v9" in _DEPRECATED_PROTOCOLS
    assert "sealed-exam-commitment-v7" in _DEPRECATED_PROTOCOLS
    assert BUILDER_MANIFEST_FORMAT == "null-pack-builder-manifest-v5"
    assert _DEPRECATED_BUILDER_MANIFEST_FORMATS == (
        "null-pack-builder-manifest-v1",
        "null-pack-builder-manifest-v2",
         "null-pack-builder-manifest-v3",
         "null-pack-builder-manifest-v4")
    assert BUILDER_RUNNER_PROTOCOL == "builder-runner-protocol-v3"
    assert BUILD_REQUEST_FORMAT == "builder-build-request-v3"
    assert BUILD_RESULT_FORMAT == "builder-build-result-v3"
    assert BUILDER_RUN_EVIDENCE_FORMAT == "builder-run-evidence-v3"
    assert EXAM_CLI_VERSION == "hidden-exam-cli-v11"


def test_v7_commitment_rejected(sealed_exam_env):
    from rl_curriculum.sealed_exam import SealedExamError

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["protocol_version"] = "sealed-exam-commitment-v7"
    with pytest.raises(SealedExamError, match="v7"):
        json.dumps(payload) and _load(payload)


def _load(payload):
    from rl_curriculum.sealed_exam import SealedExamCommitment

    return SealedExamCommitment.from_json(json.dumps(payload))


def test_manifest_v3_rejected():
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        canonical_builder_manifest_hash,
    )

    with pytest.raises(BuilderIdentityError, match="v4|null-pack"):
        canonical_builder_manifest_hash(
            {"format": "null-pack-builder-manifest-v3"})


def test_commitment_binds_run_evidence(sealed_exam_env):
    ev = sealed_exam_env["commitment"].builder_run_evidence
    assert str(ev.get("evidence_hash") or "").startswith("bre-")
    assert ev.get("mode") == "mock_payload_assembly"
    assert ev.get("deterministic") is True
    assert ev.get("run_status") == "ok"
    assert ev.get("deterministic_input_hash") == "edi-public-assembly"
    assert ev.get("runtime_bundle_hash") == "rbm-public-assembly"
    assert ev.get("thread_policy") == "in_process_public_assembly"
    assert len(ev.get("runs") or []) == 2
    assert str(ev.get("output_pack_hash") or "") == \
        sealed_exam_env["commitment"].pack_hash


def test_commitment_without_evidence_rejected(sealed_exam_env):
    from rl_curriculum.sealed_exam import SealedExamError

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload.pop("builder_run_evidence")
    with pytest.raises(SealedExamError, match="Run Evidence"):
        _load(payload)


def test_commitment_evidence_mode_tamper_rejected(sealed_exam_env):
    from rl_curriculum.sealed_exam import SealedExamError

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["builder_run_evidence"]["mode"] = "builder_execution"
    with pytest.raises(SealedExamError, match="mode"):
        _load(payload)


def test_commitment_deterministic_flag_tamper_rejected(sealed_exam_env):
    from rl_curriculum.sealed_exam import SealedExamError

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["builder_run_evidence"]["deterministic"] = "true"
    with pytest.raises(SealedExamError, match="deterministic"):
        _load(payload)


def test_request_with_candidate_field_rejected(sealed_exam_env):
    """v2 白名单:候选字段(即使自签一致哈希)必须被拒绝。"""
    import hashlib

    from rl_curriculum.sealed_exam import SealedExamError

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["builder_build_request"]["candidate_score"] = 0.9
    canonical = json.dumps(
        payload["builder_build_request"], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload["builder_build_request_hash"] = (
        "nbr-" + hashlib.sha256(canonical).hexdigest())
    with pytest.raises(SealedExamError, match="candidate_score|未注册"):
        _load(payload)


def test_v8_roundtrip_preserves_evidence(sealed_exam_env):
    commitment = sealed_exam_env["commitment"]
    reloaded = _load(json.loads(commitment.to_json()))
    assert reloaded.builder_run_evidence == commitment.builder_run_evidence
    assert reloaded.commitment_hash() == commitment.commitment_hash()
