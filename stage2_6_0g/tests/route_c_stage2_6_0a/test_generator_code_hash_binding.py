"""工作包 M:generator 实现指纹绑定(实现被替换即 EXAM_INVALID)。
阶段 2.6.0b 更新:generator_bindings 迁至 rl_curriculum.generator_binding,
逐族 {family_version, implementation_hash(gi-), manifest_hash} 取代共享
generators.py 哈希(code_hash);CLI 级篡改断言同步改为 implementation_hash。"""

from __future__ import annotations

import copy
import json

import pytest

from rl_curriculum.generator_binding import generator_bindings
from rl_curriculum.sealed_exam import (
    SealedExamError,
    module_code_hash,
    verify_sealed_commitment,
)
from tests.route_c_stage2_6_0a.conftest import run_cli


def test_bindings_cover_all_registered_families():
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    b = generator_bindings(DEFAULT_GENERATOR_REGISTRY)
    assert set(b) == set(DEFAULT_GENERATOR_REGISTRY)
    for fam, binding in b.items():
        assert binding["family_version"]
        # 逐族真实实现指纹(类源码/模块/MRO/依赖/资源),gi- 前缀
        assert binding["implementation_hash"].startswith("gi-")
        assert len(binding["manifest_hash"]) == 64
        assert binding["manifest"]["family"] == fam
    # 修改无关生成器不影响目标族绑定(逐族独立,非共享模块哈希)
    assert b["probe_segmented_drift"] != b["probe_null_sign"]


def test_module_code_hash_changes_with_content():
    import rl_curriculum.generators as gm

    h = module_code_hash(gm)
    assert h.startswith("m-")
    assert module_code_hash(gm) == h  # 稳定


def test_generator_code_tamper_rejected_unit(sealed_exam_env):
    c = copy.deepcopy(sealed_exam_env["commitment"])
    c.generator_bindings["probe_segmented_drift"][
        "implementation_hash"] = "gi-bad"
    with pytest.raises(SealedExamError, match="实现哈希不匹配"):
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
            sandbox_profile=sealed_exam_env["profile"],
        )


def test_generator_code_tamper_rejected_cli(sealed_exam_env):
    """CLI 级:承诺中的生成器实现哈希被替换 -> EXAM_INVALID。"""
    tmp = sealed_exam_env["tmp"]
    data = json.loads((tmp / "commitment.json").read_text())
    data["generator_bindings"]["probe_null_sign"][
        "implementation_hash"] = "gi-bad"
    (tmp / "commitment.json").write_text(json.dumps(data, ensure_ascii=False))
    rc = run_cli(sealed_exam_env, "out.json")
    assert rc == 5


def test_family_not_resolved_by_string_alone(sealed_exam_env):
    """考试包引用的族不能仅凭 family 字符串解析:注册表缺族即失败。"""
    from rl_curriculum.exam_pack import ExamPackError, materialize_pack

    pack = sealed_exam_env["pack"]
    pack_family = next(
        e.family for e in pack.episodes
        if e.family != "probe_segmented_drift")
    limited_registry = {
        k: v for k, v in __import__("rl_curriculum.generators",
                                    fromlist=["x"])
        .DEFAULT_GENERATOR_REGISTRY.items()
        if k != pack_family
    }
    with pytest.raises(ExamPackError, match="未注册生成器族"):
        materialize_pack(pack, limited_registry)
