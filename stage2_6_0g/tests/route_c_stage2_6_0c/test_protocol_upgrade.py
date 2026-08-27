"""阶段 2.6.0c 工作包 E:协议与密封承诺升级。

- 2.6.0b 的 v2 承诺不得被 v3 执行器自动接受;
- v2 context 不得进入 v4 执行器;
- 缺 runtime hash 的承诺拒绝;
- 旧 bool-only Null binding 拒绝(联动 D);
- 版本常量一致性(单一来源,不再两处重复定义)。
"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.sealed_exam import (
    _DEPRECATED_PROTOCOLS,
    SEALED_EXAM_PROTOCOL,
    SealedExamCommitment,
    SealedExamError,
)


def test_commitment_protocol_is_v3_with_v2_deprecated():
    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v8"
    assert "sealed-exam-commitment-v2" in _DEPRECATED_PROTOCOLS
    assert "sealed-exam-commitment-v1" in _DEPRECATED_PROTOCOLS


def test_v2_commitment_rejected_with_explicit_error(sealed_exam_env):
    payload = json.loads(sealed_exam_env["commitment"].to_json())
    payload["protocol_version"] = "sealed-exam-commitment-v2"
    with pytest.raises(SealedExamError,
                       match="已弃用|不得被 v4"):
        SealedExamCommitment.from_json(json.dumps(payload))


def test_v2_context_rejected(sealed_exam_env, tmp_path, schema,
                             sandbox_profile, mock_trusted_issuer):
    from rl_curriculum.mock_sealed_exam import (
        CONTEXT_FORMAT,
        load_exam_context,
        write_exam_context,
    )

    assert CONTEXT_FORMAT == "sealed-exam-context-v3"
    write_exam_context(tmp_path / "ctx.json", schema=schema,
                       sandbox_profile=sandbox_profile,
                       trusted_issuer=mock_trusted_issuer)
    data = json.loads((tmp_path / "ctx.json").read_text(encoding="utf-8"))
    data["format"] = "sealed-exam-context-v2"
    (tmp_path / "ctx_v2.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="v2 及更早|issuer 信任根"):
        load_exam_context(tmp_path / "ctx_v2.json")


def test_cli_version_constants_unified():
    """CLI 版本常量单一来源(v3 时代在两文件重复定义)。"""
    import rl_curriculum.formal_exam as fe
    import rl_curriculum.hidden_exam_cli as cli

    assert fe.EXAM_CLI_VERSION == "hidden-exam-cli-v9"
    assert cli.CLI_VERSION == fe.EXAM_CLI_VERSION


def test_verdict_spec_v3_freezes_seed_aggregation():
    from rl_curriculum.verdict_spec import (
        SUPPORTED_SEED_AGGREGATIONS,
        VERDICT_SPEC_FORMAT,
        probe_course_verdict_spec,
    )

    assert VERDICT_SPEC_FORMAT == "course-verdict-spec-v3"
    vs = probe_course_verdict_spec()
    assert vs.seed_aggregation == "per-seed-worst-variant-v1"
    assert vs.seed_aggregation in SUPPORTED_SEED_AGGREGATIONS
    # 聚合规则进入 canonical payload(被判定器哈希冻结)
    assert "seed_aggregation" in vs.canonical_payload()
    assert vs.canonical_payload()["seed_aggregation"] == \
        "per-seed-worst-variant-v1"


def test_antifreeze_spec_includes_seed_aggregation(sealed_exam_env):
    """承诺的 anticheat_replication_spec 双保险包含聚合规则。"""
    spec = sealed_exam_env["commitment"].anticheat_replication_spec
    assert spec["seed_aggregation"] == "per-seed-worst-variant-v1"
    assert spec["min_distinct_cheat_seeds"] == 3
    assert spec["min_failing_cheat_episodes"] == 3


def test_unsupported_seed_aggregation_rejected():
    from rl_curriculum.verdict_spec import (
        CourseVerdictSpec,
        VerdictSpecError,
    )

    with pytest.raises(VerdictSpecError, match="聚合规则"):
        CourseVerdictSpec(version="x", seed_aggregation="mean-of-best-cut")


def test_null_qualification_format_is_v3():
    """阶段 2.6.0d:Null 资格协议升级为 v3(三态结论/seed cluster 统计
    单位/经济等价单侧 TOST 带);v2(bar 级 bootstrap/单一布尔)弃用。"""
    from rl_curriculum.null_qualification import (
        NULL_QUALIFICATION_FORMAT,
    )

    assert NULL_QUALIFICATION_FORMAT == "null-qualification-v4"


def test_runtime_manifest_protocol_is_v1():
    from rl_curriculum.sandbox import (
        CANDIDATE_RUNTIME_MANIFEST_FORMAT,
    )

    assert CANDIDATE_RUNTIME_MANIFEST_FORMAT == \
        "candidate-runtime-manifest-v1"


def test_checkpoint_manifest_and_attestation_protocols_unchanged():
    """语义未变化:checkpoint manifest v3 与 training attestation v1
    不做无理由升级(任务书 E)。"""
    from rl_curriculum.attestation import ATTESTATION_PROTOCOL
    from rl_curriculum.checkpoints import _FORMAL_ELIGIBLE_SCHEMAS

    assert ATTESTATION_PROTOCOL == "training-attestation-v1"
    # checkpoint manifest 仍是 v3 正式资格 schema(未无理由升级)
    assert _FORMAL_ELIGIBLE_SCHEMAS == ("checkpoint-manifest-v3",)


def test_curriculum_infra_version_bumped():
    from rl_curriculum.versions import CURRICULUM_INFRA_VERSION

    assert CURRICULUM_INFRA_VERSION == "rl-curriculum-stage2_6_0c-v1"


def test_frozen_environment_contracts_untouched():
    """冻结交易环境合同未被修改(约束六)。"""
    from rl_platform.versions import (
        ACTION_SPEC_VERSION,
        ENV_CORE_VERSION,
        EXECUTION_CONTRACT_VERSION,
        OBSERVATION_SPEC_VERSION,
        REWARD_SPEC_VERSION,
        TERMINAL_LIQUIDATION_VERSION,
    )

    assert ENV_CORE_VERSION == "RouteCEnvCore-v1.0.0"
    assert OBSERVATION_SPEC_VERSION == "ObservationSpec-v1"
    assert ACTION_SPEC_VERSION == "BinaryLongFlatAction-v1"
    assert REWARD_SPEC_VERSION == "NetLogEquityReward-v1"
    assert EXECUTION_CONTRACT_VERSION == "MarketOpenCausalExecution-v1"
    assert TERMINAL_LIQUIDATION_VERSION == "TerminalLiquidation-v1"
