"""工作包 E:协议升级与旧材料拒绝(sealed v5 / nq v4 / power v2 /
pack v2 / builder manifest v1 / CLI v6)。

- v4 及更早承诺被 v5 执行器显式拒绝;
- null-qualification-v3 及更早、null-power-analysis-v1、
  null-pack-validity-v1 报告被拒绝;
- 只含 validator hash、没有真实 builder manifest 的承诺被拒绝;
- 使用旧错误 friction 公式的 qualification spec 被拒绝;
- 语义未变的协议(checkpoint-manifest-v3 / training-attestation-v1 /
  candidate-runtime-manifest-v1 / sealed-exam-context-v3 / 冻结合同)
  不升级。
"""

from __future__ import annotations

import json

import pytest


def test_sealed_protocol_is_v5_and_v4_deprecated():
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS,
        SEALED_EXAM_PROTOCOL,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v8"
    for old in ("sealed-exam-commitment-v1", "sealed-exam-commitment-v2",
                "sealed-exam-commitment-v3", "sealed-exam-commitment-v4",
                "sealed-exam-commitment-v5"):
        assert old in _DEPRECATED_PROTOCOLS


def test_cli_is_v7():
    import rl_curriculum.formal_exam as fe
    import rl_curriculum.hidden_exam_cli as cli

    assert fe.EXAM_CLI_VERSION == "hidden-exam-cli-v9"
    assert cli.CLI_VERSION == fe.EXAM_CLI_VERSION


def test_report_formats_and_deprecations():
    from rl_curriculum.null_pack_validation import (
        _DEPRECATED_PACK_FORMATS,
        PACK_VALIDITY_FORMAT,
    )
    from rl_curriculum.null_power_analysis import (
        _DEPRECATED_POWER_FORMATS,
        POWER_ANALYSIS_FORMAT,
    )
    from rl_curriculum.null_qualification import (
        _DEPRECATED_NULL_FORMATS,
        NULL_QUALIFICATION_FORMAT,
    )
    from rl_curriculum.null_qualification_spec import (
        _DEPRECATED_SPEC_FORMATS,
        SPEC_FORMAT,
    )

    assert NULL_QUALIFICATION_FORMAT == "null-qualification-v4"
    assert "null-qualification-v3" in _DEPRECATED_NULL_FORMATS
    assert SPEC_FORMAT == "null-qualification-spec-v2"
    assert "null-qualification-spec-v1" in _DEPRECATED_SPEC_FORMATS
    assert POWER_ANALYSIS_FORMAT == "null-power-analysis-v2"
    assert "null-power-analysis-v1" in _DEPRECATED_POWER_FORMATS
    assert PACK_VALIDITY_FORMAT == "null-pack-validity-v3"
    assert "null-pack-validity-v1" in _DEPRECATED_PACK_FORMATS
    assert "null-pack-validity-v2" in _DEPRECATED_PACK_FORMATS


def test_v4_commitment_rejected(sealed_exam_env):
    """v4 承诺(无 scenario_spec_hash 绑定/旧摘要结构)被 from_json
    显式拒绝。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    data = json.loads(sealed_exam_env["commitment"].to_json())
    data["protocol_version"] = "sealed-exam-commitment-v4"
    with pytest.raises(SealedExamError, match="已弃用"):
        SealedExamCommitment.from_json(json.dumps(data))


def test_v1_power_report_and_v1_pack_report_rejected(sealed_exam_env):
    """null-power-analysis-v1 / null-pack-validity-v1 语义材料不得进入
    v5 链路:builder 侧直接拒绝(mock 承诺构造 fail closed)。"""
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.null_power_analysis import power_analysis_report_hash
    from rl_curriculum.null_pack_validation import pack_validity_report_hash

    env = sealed_exam_env
    old_power = dict(env["power_report"])
    old_power["format"] = "null-power-analysis-v1"
    with pytest.raises(ValueError, match="null-power-analysis-v2"):
        build_mock_commitment(
            builder_provider=MockBuilderIdentityProvider(),
            pack=env["pack"], charter=env["charter"], schema=env["schema"],
            verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
            sandbox_profile=env["profile"], trusted_issuer=env["trusted_issuer"],
            null_qualification_bindings=env["materials"]["bindings"],
            power_analysis_report=old_power,
            pack_validity_report=env["materials"]["pack_validity_report"])
    old_pv = json.loads(json.dumps(env["materials"]["pack_validity_report"]))
    old_pv["format"] = "null-pack-validity-v2"
    with pytest.raises(ValueError, match="null-pack-validity-v3"):
        build_mock_commitment(
            builder_provider=MockBuilderIdentityProvider(),
            pack=env["pack"], charter=env["charter"], schema=env["schema"],
            verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
            sandbox_profile=env["profile"], trusted_issuer=env["trusted_issuer"],
            null_qualification_bindings=env["materials"]["bindings"],
            power_analysis_report=env["power_report"],
            pack_validity_report=old_pv)
    # 引用未使用的哈希函数避免 lint 误报(语义:两类报告哈希均可计算)
    assert power_analysis_report_hash(old_power).startswith("npa-")
    assert pack_validity_report_hash(old_pv).startswith("npv-")


def test_validator_only_binding_rejected(sealed_exam_env):
    """只含 validator 文件哈希、没有真实 builder manifest 的承诺被
    verify 层拒绝(12c:npb- 必须等于当前 builder manifest 哈希)。"""
    import hashlib
    from pathlib import Path

    from rl_curriculum import null_pack_validation as npv
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
        verify_sealed_commitment,
    )

    validator_file = Path(npv.__file__)
    legacy_npb = "npb-" + hashlib.sha256(
        validator_file.read_bytes()).hexdigest()
    assert legacy_npb.startswith("npb-")
    from compat_stage2_6_0f import verify_kwargs

    from rl_curriculum.builder_identity import (
        MockBuilderIdentityProvider,
    )

    current_npb = MockBuilderIdentityProvider().builder_identity(
    ).manifest_hash
    assert legacy_npb != current_npb

    env = sealed_exam_env
    data = json.loads(env["commitment"].to_json())
    data["pack_builder_code_hash"] = legacy_npb
    c = SealedExamCommitment.from_json(json.dumps(data))
    with pytest.raises(SealedExamError, match="manifest|构建算法"):
        verify_sealed_commitment(
            c, pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=default_sandbox_profile(), **verify_kwargs())


def test_old_friction_spec_rejected():
    """使用旧错误 friction 公式的 qualification spec 被拒绝(verify
    层公式/数值双对账)。"""
    import copy

    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.null_qualification_spec import (
        build_spec_payload,
        verify_spec_payload,
    )

    spec = build_spec_payload(
        default_eval_config(), timeframe="15m", episode_bars=96)
    legacy = copy.deepcopy(spec)
    legacy["margin"] = 1 - (1 - 0.001) ** 2  # 0.001999
    legacy["margin_derivation"]["formula"] = \
        "1 - (1 - fee)^2 * (1 - slippage)^2"
    problems = verify_spec_payload(legacy)
    assert problems
    assert any("旧错误公式" in p or "不一致" in p for p in problems)
    # v1 spec format 也被拒绝
    legacy2 = copy.deepcopy(spec)
    legacy2["format"] = "null-qualification-spec-v1"
    problems2 = verify_spec_payload(legacy2)
    assert any("spec format" in p for p in problems2)


def test_old_null_qualification_v3_report_rejected(null_qual_reports):
    """null-qualification-v3 报告(旧公式 derivation)被 v4 verify
    拒绝。"""
    import copy

    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualification_report_hash,
        verify_null_qualification_bindings,
    )
    from tests.route_c_stage2_6_0d.test_null_qualification_v3_protocol \
        import _null_verify_kwargs

    tampered = copy.deepcopy(null_qual_reports)
    for rep in tampered.values():
        rep["format"] = "null-qualification-v3"
    bindings = build_null_qualification_bindings(tampered)
    r = verify_null_qualification_bindings(
        bindings, required_families=sorted(tampered),
        **_null_verify_kwargs(
            spec_hash="nqs-" + "0" * 64,
            power_ref=bindings["probe_null_sign"]["report_payload"][
                "power_analysis_ref"]))
    assert not r["pass"]
    assert any("已弃用" in p for p in r["problems"])


def test_unchanged_protocols_not_bumped():
    """语义未变的协议不升级(E:checkpoint manifest v3 / attestation
    v1 / candidate runtime manifest v1 / context v3 / 冻结合同六项)。"""
    from rl_platform.versions import CHECKPOINT_REQUIRED_VERSIONS as F

    from rl_curriculum import attestation
    from rl_curriculum.checkpoints import MANIFEST_SCHEMA_VERSION
    from rl_curriculum.mock_sealed_exam import CONTEXT_FORMAT
    from rl_curriculum.sandbox import CANDIDATE_RUNTIME_MANIFEST_FORMAT

    assert MANIFEST_SCHEMA_VERSION == "checkpoint-manifest-v3"
    assert attestation.ATTESTATION_PROTOCOL == "training-attestation-v1"
    assert CANDIDATE_RUNTIME_MANIFEST_FORMAT == \
        "candidate-runtime-manifest-v1"
    assert CONTEXT_FORMAT == "sealed-exam-context-v3"
    assert F["env_core_version"] == "RouteCEnvCore-v1.0.0"
    assert F["observation_spec_version"] == "ObservationSpec-v1"
    assert F["action_spec_version"] == "BinaryLongFlatAction-v1"
    assert F["reward_spec_version"] == "NetLogEquityReward-v1"
    assert F["execution_contract_version"] == "MarketOpenCausalExecution-v1"
    assert F["terminal_liquidation_version"] == "TerminalLiquidation-v1"


def test_frozen_vendor_and_env_sources_untouched():
    """冻结交易环境与 Freqtrade 上游未被修改(源码级冒烟:关键合同
    常量与公式仍在)。"""
    from rl_platform.ledger import LongFlatLedger
    from rl_platform.market_execution import (
        EXECUTION_MODE,
        TICK_ROUNDING_VERSION,
    )

    assert EXECUTION_MODE == "market_open_causal"
    assert TICK_ROUNDING_VERSION == "side_aware_ceil_floor_v1"
    led = LongFlatLedger(initial_cash=100.0, fee=0.001,
                         slippage_bps=0.0, price_tick=0.0)
    led.apply_target(1, 100.0)
    led.apply_target(0, 100.0)
    # 冻结账本语义未变:买入 notional = 100/1.001,卖出同名义额;
    # 双边手续费 = 2 x notional x fee
    notional = 100.0 / 1.001
    assert abs(led.total_fees_paid - 2 * notional * 0.001) < 1e-9
