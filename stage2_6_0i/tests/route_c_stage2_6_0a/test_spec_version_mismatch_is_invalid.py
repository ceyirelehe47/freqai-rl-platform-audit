"""工作包 E/M:规范版本不匹配 -> EXAM_INVALID。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.sealed_exam import SealedExamError, verify_sealed_commitment
from tests.route_c_stage2_6_0a.conftest import run_cli


def test_spec_versions_tamper_rejected_at_unit_level(sealed_exam_env):
    c = sealed_exam_env["commitment"]
    c.spec_versions["env_core_version"] = "RouteCEnvCore-v0.9.9"
    with pytest.raises(SealedExamError, match="spec versions"):
        verify_sealed_commitment(
            c, pack=sealed_exam_env["pack"],
            charter=sealed_exam_env["charter"],
            schema=sealed_exam_env["schema"],
            registry=__import__("rl_curriculum.generators", fromlist=["x"])
            .DEFAULT_GENERATOR_REGISTRY,
            eval_config=sealed_exam_env["eval_config"],
            **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs(),
            verdict_spec=__import__("rl_curriculum.verdict_spec",
                                    fromlist=["x"])
            .probe_course_verdict_spec(),
        )


def test_missing_spec_version_rejected(sealed_exam_env):
    c = sealed_exam_env["commitment"]
    del c.spec_versions["terminal_liquidation_version"]
    with pytest.raises(SealedExamError, match="spec versions"):
        verify_sealed_commitment(
            c, pack=sealed_exam_env["pack"],
            charter=sealed_exam_env["charter"],
            schema=sealed_exam_env["schema"],
            registry=__import__("rl_curriculum.generators", fromlist=["x"])
            .DEFAULT_GENERATOR_REGISTRY,
            eval_config=sealed_exam_env["eval_config"],
            **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs(),
            verdict_spec=__import__("rl_curriculum.verdict_spec",
                                    fromlist=["x"])
            .probe_course_verdict_spec(),
        )


def test_spec_versions_tamper_rejected_at_cli_level(sealed_exam_env):
    """CLI:承诺中 spec versions 被改 -> EXAM_INVALID。"""
    tmp = sealed_exam_env["tmp"]
    data = json.loads((tmp / "commitment.json").read_text())
    data["spec_versions"]["env_core_version"] = "RouteCEnvCore-v0.9.9"
    (tmp / "commitment.json").write_text(json.dumps(data, ensure_ascii=False))
    rc = run_cli(sealed_exam_env, "out.json")
    assert rc == 5
    out = json.loads((tmp / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_frozen_env_core_unchanged():
    """RouteCEnvCore-v1.0.0 冻结未被本阶段修改(PASS 条件 1)。"""
    from rl_platform.versions import ENV_CORE_VERSION, CHECKPOINT_REQUIRED_VERSIONS

    assert ENV_CORE_VERSION == "RouteCEnvCore-v1.0.0"
    assert CHECKPOINT_REQUIRED_VERSIONS["env_core_version"] == \
        "RouteCEnvCore-v1.0.0"
