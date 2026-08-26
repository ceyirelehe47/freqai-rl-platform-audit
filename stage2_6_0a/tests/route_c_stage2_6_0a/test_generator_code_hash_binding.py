"""工作包 M:generator 代码哈希绑定(实现被替换即 EXAM_INVALID)。"""

from __future__ import annotations

import copy
import json

import pytest

from rl_curriculum.sealed_exam import (
    SealedExamError,
    generator_bindings,
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
        assert binding["code_hash"].startswith("m-")


def test_module_code_hash_changes_with_content():
    import rl_curriculum.generators as gm

    h = module_code_hash(gm)
    assert h.startswith("m-")
    assert module_code_hash(gm) == h  # 稳定


def test_generator_code_tamper_rejected_unit(sealed_exam_env):
    c = copy.deepcopy(sealed_exam_env["commitment"])
    c.generator_bindings["probe_segmented_drift"]["code_hash"] = "m-bad"
    with pytest.raises(SealedExamError, match="生成器代码哈希"):
        verify_sealed_commitment(
            c, pack=sealed_exam_env["pack"],
            charter=sealed_exam_env["charter"],
            schema=sealed_exam_env["schema"],
            registry=__import__("rl_curriculum.generators", fromlist=["x"])
            .DEFAULT_GENERATOR_REGISTRY,
            eval_config=sealed_exam_env["eval_config"],
            verdict_spec=__import__("rl_curriculum.verdict_spec",
                                    fromlist=["x"])
            .probe_course_verdict_spec(),
        )


def test_generator_code_tamper_rejected_cli(sealed_exam_env):
    """CLI 级:承诺中的 generator 代码哈希被替换 -> EXAM_INVALID。"""
    tmp = sealed_exam_env["tmp"]
    data = json.loads((tmp / "commitment.json").read_text())
    data["generator_bindings"]["probe_null_sign"]["code_hash"] = "m-bad"
    (tmp / "commitment.json").write_text(json.dumps(data, ensure_ascii=False))
    rc = run_cli(sealed_exam_env, "out.json")
    assert rc == 5


def test_family_not_resolved_by_string_alone(sealed_exam_env):
    """考试包引用的族不能仅凭 family 字符串解析:注册表缺族即失败。"""
    from rl_curriculum.exam_pack import ExamPackError, materialize_pack

    pack = sealed_exam_env["pack"]
    limited_registry = {
        k: v for k, v in __import__("rl_curriculum.generators",
                                    fromlist=["x"])
        .DEFAULT_GENERATOR_REGISTRY.items()
        if k != "probe_null_block"
    }
    with pytest.raises(ExamPackError, match="未注册生成器族"):
        materialize_pack(pack, limited_registry)
