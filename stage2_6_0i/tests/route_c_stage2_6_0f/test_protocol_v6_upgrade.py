"""工作包 D2:协议升级矩阵(v6 承诺 / manifest v2 / validity v3 /
CLI v7)与旧材料拒绝。

- sealed-exam-commitment-v5 及更早版本被 v6 执行器显式拒绝;
- null-pack-builder-manifest-v1 材料被拒绝;
- null-pack-validity-v2 报告被拒绝;
- 缺 Builder Identity Provider 的正式调用被拒绝;
- 缺全局 Null duration contract 的承诺被拒绝;
- 语义未变的协议不无理由升级。
"""

from __future__ import annotations

import json

import pytest


def test_sealed_protocol_is_v6_and_v5_deprecated():
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS,
        SEALED_EXAM_PROTOCOL,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v10"
    for old in ("sealed-exam-commitment-v1", "sealed-exam-commitment-v2",
                "sealed-exam-commitment-v3", "sealed-exam-commitment-v4",
                "sealed-exam-commitment-v5"):
        assert old in _DEPRECATED_PROTOCOLS


def test_cli_is_v7():
    import rl_curriculum.formal_exam as fe
    import rl_curriculum.hidden_exam_cli as cli

    assert fe.EXAM_CLI_VERSION == "hidden-exam-cli-v11"
    assert cli.CLI_VERSION == fe.EXAM_CLI_VERSION


def test_builder_manifest_is_v2_and_v1_deprecated():
    from rl_curriculum.builder_identity import (
        _DEPRECATED_BUILDER_MANIFEST_FORMATS,
        BUILDER_MANIFEST_FORMAT,
    )

    # 阶段 2.6.0g:manifest v3 为当前(v2 纯字符串入口声明已弃用)
    assert BUILDER_MANIFEST_FORMAT == "null-pack-builder-manifest-v5"
    assert _DEPRECATED_BUILDER_MANIFEST_FORMATS == (
        "null-pack-builder-manifest-v1",
        "null-pack-builder-manifest-v2",
        "null-pack-builder-manifest-v3",
        "null-pack-builder-manifest-v4",
)


def test_pack_validity_is_v3_and_v2_deprecated():
    from rl_curriculum.null_pack_validation import (
        _DEPRECATED_PACK_FORMATS,
        PACK_VALIDITY_FORMAT,
    )

    assert PACK_VALIDITY_FORMAT == "null-pack-validity-v3"
    assert "null-pack-validity-v2" in _DEPRECATED_PACK_FORMATS


def test_duration_contract_format_is_v1():
    from rl_curriculum.null_duration_contract import (
        NULL_DURATION_CONTRACT_FORMAT,
    )

    assert NULL_DURATION_CONTRACT_FORMAT == "null-duration-contract-v1"


def test_v5_commitment_rejected(sealed_exam_env):
    """v5 承诺(旧协议)被 from_json 显式拒绝,不得自动迁移。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    data = json.loads(sealed_exam_env["commitment"].to_json())
    data["protocol_version"] = "sealed-exam-commitment-v5"
    with pytest.raises(SealedExamError, match="已弃用"):
        SealedExamCommitment.from_json(json.dumps(data))
    data["protocol_version"] = "sealed-exam-commitment-v4"
    with pytest.raises(SealedExamError, match="已弃用"):
        SealedExamCommitment.from_json(json.dumps(data))


def test_commitment_missing_duration_contract_rejected(sealed_exam_env):
    """缺全局 Null duration contract 的承诺被拒绝(v6 必填字段)。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    data = json.loads(sealed_exam_env["commitment"].to_json())
    data.pop("null_duration_contract")
    data.pop("null_duration_contract_hash")
    with pytest.raises(SealedExamError, match="duration contract"):
        SealedExamCommitment.from_json(json.dumps(data))


def test_commitment_tampered_duration_payload_rejected(sealed_exam_env):
    """ndc- payload 与 hash 不一致 -> 拒绝。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    data = json.loads(sealed_exam_env["commitment"].to_json())
    data["null_duration_contract"]["resolved_bars"] = 48
    with pytest.raises(SealedExamError, match="不一致|不一致"):
        SealedExamCommitment.from_json(json.dumps(data))


def test_legacy_v1_builder_manifest_material_rejected():
    """仍通过默认 mock builder hash 验证的旧材料(v1 manifest)被
    拒绝:canonical 哈希入口只接受 v2 格式。"""
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        canonical_builder_manifest_hash,
    )

    legacy = {"format": "null-pack-builder-manifest-v1",
              "protocol": "null-pack-builder-protocol-v1",
              "builder_function": {"module": "x", "qualname": "y",
                                   "source_sha256": "0" * 64}}
    with pytest.raises(BuilderIdentityError):
        canonical_builder_manifest_hash(legacy)


def test_v2_pack_validity_report_rejected_by_builder(sealed_exam_env):
    """null-pack-validity-v2 报告不得进入 v6 承诺构建。"""
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    env = sealed_exam_env
    old_pv = json.loads(json.dumps(env["pack_validity_report"]))
    old_pv["format"] = "null-pack-validity-v2"
    with pytest.raises(ValueError, match="null-pack-validity-v3"):
        build_mock_commitment(
            builder_provider=MockBuilderIdentityProvider(),
            pack=env["pack"], charter=env["charter"], schema=env["schema"],
            verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
            sandbox_profile=env["profile"], trusted_issuer=env["trusted_issuer"],
            null_qualification_bindings=build_null_qualification_bindings(
                env["null_qual_reports"]),
            power_analysis_report=env["power_report"],
            pack_validity_report=old_pv)


def test_cli_requires_builder_provider(sealed_exam_env, tmp_path):
    """正式模式缺 --builder-provider -> CLI 直接拒绝(exit 2)。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    d = tmp_path / "no_provider_cli"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", str(d / "none.zip"),
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    assert rc == 2


def test_cli_private_provider_requires_root(sealed_exam_env, tmp_path):
    """private provider 缺 --builder-provider-root -> 拒绝(exit 2)。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    d = tmp_path / "no_root_cli"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", str(d / "none.zip"),
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    assert rc == 2


def test_unchanged_protocols_not_bumped():
    """语义未变的协议不升级(D2:friction v2 / spec v2 / power v2 /
    nq v4 / checkpoint v3 / attestation v1 / runtime v1 / context v3)。"""
    from rl_platform.versions import CHECKPOINT_REQUIRED_VERSIONS as F

    from rl_curriculum import attestation
    from rl_curriculum.checkpoints import MANIFEST_SCHEMA_VERSION
    from rl_curriculum.mock_sealed_exam import CONTEXT_FORMAT
    from rl_curriculum.null_friction import FRICTION_CONTRACT_FORMAT
    from rl_curriculum.null_power_analysis import POWER_ANALYSIS_FORMAT
    from rl_curriculum.null_qualification import NULL_QUALIFICATION_FORMAT
    from rl_curriculum.null_qualification_spec import SPEC_FORMAT
    from rl_curriculum.sandbox import CANDIDATE_RUNTIME_MANIFEST_FORMAT

    assert FRICTION_CONTRACT_FORMAT == "null-friction-contract-v2"
    assert SPEC_FORMAT == "null-qualification-spec-v2"
    assert POWER_ANALYSIS_FORMAT == "null-power-analysis-v2"
    assert NULL_QUALIFICATION_FORMAT == "null-qualification-v4"
    assert MANIFEST_SCHEMA_VERSION == "checkpoint-manifest-v3"
    assert attestation.ATTESTATION_PROTOCOL == "training-attestation-v1"
    assert CANDIDATE_RUNTIME_MANIFEST_FORMAT == \
        "candidate-runtime-manifest-v1"
    assert CONTEXT_FORMAT == "sealed-exam-context-v3"
    # 六项冻结合同
    assert F["env_core_version"] == "RouteCEnvCore-v1.0.0"
    assert F["observation_spec_version"] == "ObservationSpec-v1"
    assert F["action_spec_version"] == "BinaryLongFlatAction-v1"
    assert F["reward_spec_version"] == "NetLogEquityReward-v1"
    assert F["execution_contract_version"] == "MarketOpenCausalExecution-v1"
    assert F["terminal_liquidation_version"] == "TerminalLiquidation-v1"


def test_frozen_vendor_commit_unchanged():
    """vendor/freqtrade 固定提交未变。"""
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2] / "vendor" / "freqtrade"
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
        text=True, check=True).stdout.strip()
    assert head == "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
