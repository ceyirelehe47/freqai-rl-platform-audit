"""P7:mock 构建辅助函数的隐式 Mock Provider fallback 已删除(源码级)。

- build_mock_commitment(builder_provider=None) 显式 ValueError;
- _validate_pack_ephemeral(builder_identity=None) 显式失败;
- 源码中不存在隐式构造分支(inspect.getsource 断言)。
"""

from __future__ import annotations

import inspect

import pytest


def test_build_mock_commitment_none_rejected(sealed_exam_env):
    """builder_provider=None -> 显式 ValueError(无内部 fallback)。"""
    from rl_curriculum.mock_sealed_exam import build_mock_commitment

    env = sealed_exam_env
    with pytest.raises(ValueError, match="必须显式传入 builder_provider"):
        build_mock_commitment(
            pack=env["pack"], charter=env["charter"], schema=env["schema"],
            verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
            trusted_issuer=env["trusted_issuer"],
            null_qualification_bindings=_bindings(env),
            power_analysis_report=env["power_report"],
            pack_validity_report=env["pack_validity_report"],
            builder_provider=None)


def _bindings(env):
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    return build_null_qualification_bindings(env["null_qual_reports"])


def test_validate_pack_ephemeral_none_rejected(sealed_exam_env):
    """_validate_pack_ephemeral 缺 builder 身份 -> 显式失败。"""
    from rl_curriculum.mock_sealed_exam import _validate_pack_ephemeral

    env = sealed_exam_env
    with pytest.raises(ValueError, match="缺少 builder 身份|fallback"):
        _validate_pack_ephemeral(
            env["pack"], env["eval_config"], env["schema"],
            builder_identity=None)


def test_no_implicit_fallback_in_source():
    """源码级断言:两个辅助函数的源码不含隐式 Mock 构造分支。"""
    import rl_curriculum.mock_sealed_exam as mse

    src_commit = inspect.getsource(mse.build_mock_commitment)
    assert "builder_provider is None" in src_commit
    assert "builder_provider = MockBuilderIdentityProvider()" \
        not in src_commit
    assert "else MockBuilderIdentityProvider" not in src_commit

    src_validate = inspect.getsource(mse._validate_pack_ephemeral)
    assert "else MockBuilderIdentityProvider" not in src_validate
    assert "if builder_identity is not None" not in src_validate


def test_explicit_mock_provider_still_works(sealed_exam_env):
    """显式传入 Mock Provider 的公开 mock 流程不受影响。"""
    env = sealed_exam_env
    from rl_curriculum.builder_identity import (
        MockBuilderIdentityProvider,
    )

    provider = MockBuilderIdentityProvider()
    assert (env["commitment"].pack_builder_code_hash
            == provider.builder_identity().manifest_hash)
