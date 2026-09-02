# -*- coding: utf-8 -*-
"""R10 §29 Delegation 测试:live signatures / keyword-only / AST 禁第三
位置参数 / CLI 显式 namespace / pairs_per_rung 类型与范围 / 错误位置
参数立即失败。"""

from __future__ import annotations

import inspect

import pytest


def test_supervised_wrapper_keyword_only():
    from rl_curriculum.curriculum261_r10_calibration import (
        supervised_learnability_run_r10,
    )

    sig = inspect.signature(supervised_learnability_run_r10)
    kwonly = {p.name for p in sig.parameters.values()
              if p.kind is inspect.Parameter.KEYWORD_ONLY}
    assert {"namespace", "pairs_per_rung", "train_pair_limit",
            "model_seeds", "training_config"} <= kwonly
    # 位置参数只有 preproc_v2 / pack(第三位置参数被签名层杜绝)
    positional = [p.name for p in sig.parameters.values()
                  if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    assert positional == ["preproc_v2", "pack"]


def test_positional_namespace_misrouting_fails_immediately():
    """R9 缺陷形态(第三位置参数传 namespace)必须 TypeError。"""
    from rl_curriculum.curriculum261_r10_calibration import (
        supervised_learnability_run_r10,
    )

    with pytest.raises(TypeError):
        # 故意按位置传第三个参数(namespace)——签名层拒绝
        supervised_learnability_run_r10(None, {}, "supervised_main_r10")


def test_r6_underlying_third_positional_is_pairs_per_rung():
    """核对结论固化:R6 实现第三位置参数是 pairs_per_rung(不是
    namespace)——R9 wrapper 的位置参数错传根因。"""
    from rl_curriculum.curriculum261_r6_calibration import (
        supervised_learnability_run_r6,
    )

    sig = inspect.signature(supervised_learnability_run_r6)
    positional = [p.name for p in sig.parameters.values()
                  if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                inspect.Parameter.POSITIONAL_OR_KEYWORD)]
    assert positional == ["preproc_v2", "pack", "pairs_per_rung",
                          "namespace", "train_pair_limit"]


def test_live_signature_audit_all_pass():
    from rl_curriculum.curriculum261_r10_delegation import (
        live_signature_audit_r10,
    )

    audit = live_signature_audit_r10()
    assert audit["all_pass"], [
        (e["use"], e["checks"]) for e in audit["entries"]
        if not e["checks"]["pass"]]
    # 覆盖 §7.3 的九类 runner
    uses = {e["use"] for e in audit["entries"]}
    assert {"supervised runner", "fit-bank builder", "preprocessor fit",
            "C1/C3 corpus runner", "C2 matched runner",
            "C2 independent runner", "semantic runner",
            "robustness builder", "final runner"} <= uses


def test_ast_delegation_checks_pass():
    from rl_curriculum.curriculum261_r10_delegation import (
        delegation_ast_checks_r10,
    )

    result = delegation_ast_checks_r10()
    assert result["pass"], result["violations"]


def test_ast_rejects_third_positional_delegate():
    """负向:同 R9 形态的委托(第三位置参数)必须被 AST 检查抓出。"""
    import ast as _ast

    from rl_curriculum.curriculum261_r10_delegation import (
        _ast_call_violations,
    )

    bad = _ast.parse(
        "supervised_learnability_run_r10(v2, pack, 'ns_x')")
    violations = _ast_call_violations(bad, "synthetic_bad.py")
    assert any("第三位置参数" in v for v in violations)
    assert any("缺少显式 namespace=" in v for v in violations)
    good = _ast.parse(
        "supervised_learnability_run_r10(\n"
        "    v2, pack, namespace='ns_x', pairs_per_rung=4)")
    assert _ast_call_violations(good, "synthetic_good.py") == []


def test_pairs_per_rung_type_and_range():
    from rl_curriculum.curriculum261_r10_calibration import (
        supervised_learnability_run_r10,
    )

    sig = inspect.signature(supervised_learnability_run_r10)
    assert sig.parameters["pairs_per_rung"].default == 10
    # 非 int 在数据集生成处 fail closed(generate_pair range());
    # 这里验证默认值为正整数
    assert isinstance(sig.parameters["pairs_per_rung"].default, int)
    assert sig.parameters["pairs_per_rung"].default > 0


def test_calibration_call_contract_payload():
    from rl_curriculum.curriculum261_r10_delegation import (
        calibration_call_contract_payload,
    )

    payload = calibration_call_contract_payload()
    assert payload["supervised_entrypoint"]["keyword_only"] == [
        "namespace", "pairs_per_rung", "train_pair_limit",
        "model_seeds", "training_config"]
    assert payload["label_contract"] == "PolicyVisibleSupervisedLabel-v1"
    assert payload["r9_defects_closed"]


def test_generator_stress_namespace_explicit_r10():
    """R9 潜伏缺陷修复:stress wrapper 的默认 namespace 必须是
    stress_r10(R6 默认 stress_r6 曾可被隐式复用)。"""
    from rl_curriculum.curriculum261_r10_calibration import (
        run_generator_stress_r10,
    )

    sig = inspect.signature(run_generator_stress_r10)
    assert sig.parameters["namespace"].default == "stress_r10"
    assert sig.parameters["namespace"].kind is \
        inspect.Parameter.KEYWORD_ONLY
