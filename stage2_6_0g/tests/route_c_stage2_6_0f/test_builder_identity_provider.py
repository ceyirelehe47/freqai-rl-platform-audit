"""工作包 A:正式 Builder Identity Provider 语义。

- formal API(verify_sealed_commitment / validate_null_pack /
  run_sealed_exam)的 builder 身份必填,缺失即 fail closed;
- 公开 mock 流程显式传入 MockBuilderIdentityProvider;
- Provider 不来自 context / pack / checkpoint / 候选;
- Provider package 完整性与 Candidate runtime 隔离。
"""

from __future__ import annotations

import json

import pytest


def test_formal_verifier_requires_builder_identity(sealed_exam_env,
                                                   duration_contract):
    """verify_sealed_commitment 缺 builder_identity -> SealedExamError
    (EXAM_INVALID;无 mock fallback)。"""
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    with pytest.raises(SealedExamError, match="Builder Identity"):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"],
            duration_contract=duration_contract)


def test_formal_verifier_requires_duration_contract(sealed_exam_env,
                                                    mock_identity):
    """verify_sealed_commitment 缺 duration_contract -> SealedExamError。"""
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    with pytest.raises(SealedExamError, match="duration contract"):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"],
            builder_identity=mock_identity)


def test_validate_null_pack_requires_identity_and_contract(
        mock_pack_materialized, schema, cfg, duration_contract,
        mock_identity):
    """validate_null_pack 缺 builder identity 或 duration contract ->
    fail closed(不存在无参默认 mock builder hash 通道)。"""
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    spec = build_spec_for_pack(
        cfg, timeframe=duration_contract["timeframe"],
        episode_bars=int(duration_contract["resolved_bars"]))
    with pytest.raises(Exception, match="Builder Identity|builder 身份"):
        validate_null_pack(
            mock_pack_materialized, cfg=cfg, schema=schema, spec=spec,
            duration_contract=duration_contract)
    with pytest.raises(Exception, match="duration contract"):
        validate_null_pack(
            mock_pack_materialized, cfg=cfg, schema=schema, spec=spec,
            builder_identity=mock_identity)


def test_no_default_mock_builder_hash_channel():
    """null_pack_validation 模块不再导出无参数 mock builder 哈希入口。"""
    import rl_curriculum.null_pack_validation as npv

    for gone in ("pack_builder_manifest", "pack_builder_manifest_hash",
                 "pack_builder_code_hash"):
        assert not hasattr(npv, gone), (
            f"{gone} 必须删除:无参数调用默认公开 mock builder 的通道"
            "不得保留(阶段 2.6.0f A2)")
    # provider_builder_manifest_hash(None) 走 require 守卫 fail closed
    from rl_curriculum.builder_identity import BuilderIdentityError
    from rl_curriculum.null_pack_validation import (
        provider_builder_manifest_hash,
    )

    with pytest.raises(BuilderIdentityError, match="缺少 Builder Identity"):
        provider_builder_manifest_hash(None)


def test_mock_provider_explicit_and_passes(sealed_exam_env,
                                           duration_contract, mock_identity):
    """mock Provider 显式传入 -> formal verify 完整通过。"""
    from rl_curriculum.sealed_exam import verify_sealed_commitment

    env = sealed_exam_env
    report = verify_sealed_commitment(
        env["commitment"], pack=env["pack"], charter=env["charter"],
        schema=env["schema"], registry=env["registry"],
        eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
        sandbox_profile=env["profile"],
        builder_identity=mock_identity,
        duration_contract=duration_contract)
    assert report["pass"]
    assert report["checks"]["pack_builder_code_hash"] is True


def test_context_cannot_supply_provider(sealed_exam_env):
    """sealed-exam-context-v3 没有 builder provider 信任根字段(A3):
    write/load context 的 payload 键集合固定,不含 provider。"""
    from rl_curriculum.mock_sealed_exam import (
        CONTEXT_FORMAT,
        load_exam_context,
        write_exam_context,
    )

    env = sealed_exam_env
    payload = write_exam_context(
        "/tmp/_ctx_2_6_0f.json", charter=env["charter"],
        schema=env["schema"], verdict_spec=env["verdict_spec"],
        eval_config=env["eval_config"], sandbox_profile=env["profile"])
    assert payload["format"] == CONTEXT_FORMAT == "sealed-exam-context-v3"
    allowed = {"format", "charter", "observation_schema", "verdict_spec",
               "eval_config", "sandbox_profile", "trusted_issuer"}
    assert set(payload) <= allowed, (
        "context 不得新增 Builder Provider 信任根字段")
    ctx = load_exam_context("/tmp/_ctx_2_6_0f.json")
    assert "builder_provider" not in ctx
    assert "builder_identity" not in ctx


def test_checkpoint_manifest_has_no_provider_field(sealed_exam_env):
    """checkpoint sidecar manifest 结构没有 builder provider 声明通道:
    Provider 不可由 checkpoint 覆盖(A3)。"""
    import inspect

    import rl_curriculum.checkpoints as ckpt_mod

    for fn_name in ("save_checkpoint_manifest", "load_checkpoint_manifest"):
        sig = inspect.signature(getattr(ckpt_mod, fn_name))
        assert not any("builder" in p or "provider" in p
                       for p in sig.parameters), (
            f"checkpoint {fn_name} 不得携带 builder/provider 通道")


def test_pack_payload_has_no_provider_field(mock_pack):
    """ExamPack canonical payload 不含 provider 声明(A3)。"""
    canon = json.loads(mock_pack.canonical())
    assert not any("provider" in k or "builder" in k for k in canon), (
        "pack 不得携带 builder/provider 信任字段")


def test_provider_manifest_hash_matches_commitment(sealed_exam_env):
    """承诺 npb- == Mock Provider 重算(评估环境中重新计算)。"""
    env = sealed_exam_env
    from compat_stage2_6_0f import mock_builder_identity

    identity = mock_builder_identity()
    assert env["commitment"].pack_builder_code_hash == identity.manifest_hash
    assert identity.manifest_hash.startswith("npb-")
    assert identity.format == "null-pack-builder-manifest-v4"
    assert identity.builder_protocol == "null-pack-builder-protocol-v3"


def test_v1_builder_manifest_format_rejected():
    """v1 格式(手工函数清单)的 manifest 不能产生 v2 身份(D2)。"""
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        canonical_builder_manifest_hash,
    )

    legacy = {"format": "null-pack-builder-manifest-v1"}
    with pytest.raises(BuilderIdentityError, match="v1|格式"):
        canonical_builder_manifest_hash(legacy)


def test_provider_not_in_candidate_runtime(mock_identity):
    """Provider/builder root 与候选运行时目录不相交;builder 身份不
    传入 Candidate sandbox(A1:候选不可读/不可覆盖/不可选择)。"""
    from rl_curriculum.builder_identity import (
        provider_runtime_isolation_report,
    )

    report = provider_runtime_isolation_report(mock_identity)
    assert report["disjoint"] is True
    # sandbox 启动器签名没有 builder/provider 参数(不进入沙箱)
    import inspect

    import rl_curriculum.sandbox as sandbox_mod

    sig = inspect.signature(sandbox_mod.SandboxedCandidate.__init__)
    assert not any("builder" in p or "provider" in p
                   for p in sig.parameters), (
        "SandboxedCandidate 不得接收 builder/provider(Provider 不进入 "
        "Candidate 沙箱)")
