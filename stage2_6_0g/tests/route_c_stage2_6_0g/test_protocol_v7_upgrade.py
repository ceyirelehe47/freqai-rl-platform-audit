"""协议升级:sealed-exam-commitment-v7 / CLI v8 / builder manifest v3 /
builder-runner-protocol-v1 / 篡改矩阵与旧材料拒绝。"""

from __future__ import annotations

import json

import pytest


def test_protocol_constants():
    from rl_curriculum.builder_identity import (
        BUILDER_MANIFEST_FORMAT,
        BUILDER_PROTOCOL,
    )
    from rl_curriculum.builder_provenance import (
        BUILD_REQUEST_FORMAT,
        BUILDER_RUNNER_PROTOCOL,
    )
    from rl_curriculum.formal_exam import EXAM_CLI_VERSION
    from rl_curriculum.sealed_exam import SEALED_EXAM_PROTOCOL

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v7"
    assert EXAM_CLI_VERSION == "hidden-exam-cli-v8"
    assert BUILDER_MANIFEST_FORMAT == "null-pack-builder-manifest-v3"
    assert BUILDER_PROTOCOL == "null-pack-builder-protocol-v3"
    assert BUILDER_RUNNER_PROTOCOL == "builder-runner-protocol-v1"
    assert BUILD_REQUEST_FORMAT == "builder-build-request-v1"


def test_v6_commitment_rejected(sealed_exam_env):
    """v6 材料(npb- 只证文件存在,无产物来源绑定)不得被 v7 接受。"""
    from rl_curriculum.sealed_exam import (
        SEALED_EXAM_PROTOCOL,
        SealedExamCommitment,
        SealedExamError,
    )

    text = sealed_exam_env["commitment"].to_json()
    for old in ("sealed-exam-commitment-v6", "sealed-exam-commitment-v5"):
        with pytest.raises(SealedExamError, match="已弃用|协议版本"):
            SealedExamCommitment.from_json(
                text.replace(SEALED_EXAM_PROTOCOL, old))


def test_missing_request_rejected(sealed_exam_env):
    """缺 builder_build_request/nbr- 的承诺 -> from_json 拒绝。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload.pop("builder_build_request")
    payload.pop("builder_build_request_hash")
    with pytest.raises(SealedExamError, match="nbr-"):
        SealedExamCommitment.from_json(json.dumps(payload))


def test_request_tamper_rejected(sealed_exam_env):
    """请求 payload 被改写(pair 数 32 -> 16)-> nbr- 对账失败。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["builder_build_request"]["pair_count_per_family"] = 16
    with pytest.raises(SealedExamError, match="nbr- 哈希不一致"):
        SealedExamCommitment.from_json(json.dumps(payload))


def test_request_with_candidate_field_rejected(sealed_exam_env):
    """承诺里的请求注入候选字段(candidate_score) -> 黑名单拒绝。

    哈希用手工 canonical 构造(绕过 frozen_build_request_hash 的
    合法性检查,模拟攻击者自签一致哈希)。"""
    import hashlib

    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["builder_build_request"]["candidate_score"] = 0.9
    canonical = json.dumps(
        payload["builder_build_request"], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload["builder_build_request_hash"] = (
        "nbr-" + hashlib.sha256(canonical).hexdigest())
    with pytest.raises(SealedExamError, match="禁止字段"):
        SealedExamCommitment.from_json(json.dumps(payload))


def test_verify_recomputes_request(sealed_exam_env, duration_contract):
    """verify 12d:Provider 重新派生的请求哈希与承诺对账(静态层)。"""
    env = sealed_exam_env
    from rl_curriculum.sealed_exam import verify_sealed_commitment

    report = verify_sealed_commitment(
        env["commitment"], pack=env["pack"], charter=env["charter"],
        schema=env["schema"], registry=env["registry"],
        eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
        sandbox_profile=env["profile"],
        builder_identity=env["provider"].builder_identity(),
        duration_contract=duration_contract)
    assert report["pass"], report["problems"][:3]
    assert report["checks"]["builder_build_request_hash"] is True


def test_verify_request_mismatch_detected(sealed_exam_env,
                                          private_builder_a,
                                          duration_contract):
    """承诺(mock builder 签)用私有 Provider verify -> 12d 拒绝
    (请求哈希与 identity 派生不一致;在 npb 对账之外的第二道闸)。"""
    env = sealed_exam_env
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    with pytest.raises(SealedExamError):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"],
            verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"],
            builder_identity=private_builder_a.builder_identity(),
            duration_contract=duration_contract)


def test_roundtrip_preserves_request(sealed_exam_env):
    """v7 承诺 to_json/from_json roundtrip 保留请求与哈希。"""
    from rl_curriculum.sealed_exam import SealedExamCommitment

    c = sealed_exam_env["commitment"]
    c2 = SealedExamCommitment.from_json(c.to_json())
    assert c2.builder_build_request == c.builder_build_request
    assert c2.builder_build_request_hash == c.builder_build_request_hash
    assert c2.commitment_hash() == c.commitment_hash()
