"""工作包 M:evaluator 代码哈希绑定(评估器被替换即 EXAM_INVALID)。
阶段 2.6.0b 更新:verify_sealed_commitment 新增 sandbox_profile 必给
参数(不给即报 sandbox 错误),本文件验证调用补齐该参数。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.sealed_exam import SealedExamError, verify_sealed_commitment
from tests.route_c_stage2_6_0a.conftest import run_cli


def _verify(env, evaluator_hash=None):
    return verify_sealed_commitment(
        env["commitment"], pack=env["pack"], charter=env["charter"],
        schema=env["schema"],
        registry=__import__("rl_curriculum.generators", fromlist=["x"])
        .DEFAULT_GENERATOR_REGISTRY,
        eval_config=env["eval_config"],
        verdict_spec=__import__("rl_curriculum.verdict_spec", fromlist=["x"])
        .probe_course_verdict_spec(),
        evaluator_hash=evaluator_hash,
        sandbox_profile=env["profile"],
    **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs())


def test_evaluator_hash_binding(sealed_exam_env):
    report = _verify(sealed_exam_env)
    assert report["checks"]["evaluator_code_hash"] is True
    assert report["checks"]["sandbox_profile_hash"] is True


def test_evaluator_hash_tamper_rejected_unit(sealed_exam_env):
    with pytest.raises(SealedExamError, match="evaluator 代码哈希"):
        _verify(sealed_exam_env, evaluator_hash="e-tampered")


def test_evaluator_hash_tamper_rejected_cli(sealed_exam_env):
    tmp = sealed_exam_env["tmp"]
    data = json.loads((tmp / "commitment.json").read_text())
    data["evaluator_code_hash"] = "e-tampered"
    (tmp / "commitment.json").write_text(json.dumps(data, ensure_ascii=False))
    rc = run_cli(sealed_exam_env, "out.json")
    assert rc == 5
    out = json.loads((tmp / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_evaluator_code_hash_covers_package():
    """evaluator 哈希覆盖 rl_curriculum 全包(任何评估文件变化即失效)。"""
    import rl_curriculum
    from pathlib import Path

    from rl_curriculum.evaluator import evaluator_code_hash

    root = Path(rl_curriculum.__file__).parent
    n_py = len(list(root.rglob("*.py")))
    assert n_py >= 15
    assert evaluator_code_hash().startswith("e-")
    assert evaluator_code_hash(package_dir=root) == evaluator_code_hash()
