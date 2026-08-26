"""协议升级(null-qualification-v3)与 2.6.0c 实现的保留守卫。

v3 升级通道:
- format 常量 + 报告键集合 + qualification_code_hash(文件字节)
  三重失效——旧 v1/v2 报告不得被新执行器自动接受;
- 语义未变的协议不升级(checkpoint manifest v3 / training
  attestation v1 / sealed-exam-commitment-v3 / runtime manifest v1
  保持——Null 资格语义变化由 nqc-/nq-/format 双通道覆盖)。

2.6.0c 必须完整保留(任务书第四节):
- issuer 信任根(正式 issuer 唯一来自承诺;context 只是副本);
- candidate runtime 逐文件绑定;
- 反作弊复制闭环(动态 seed 门槛,无硬编码截断,无永真断言模式);
- Null 报告内容绑定(bool-only 拒绝)。
"""

from __future__ import annotations

import copy
import inspect

import pytest

from rl_curriculum.null_qualification import (
    _DEPRECATED_NULL_FORMATS,
    build_null_qualification_bindings,
    qualification_report_hash,
    verify_null_qualification_bindings,
)


def _verify_kwargs():
    from tests.route_c_stage2_6_0b.test_invalid_null_rejected import (
        _verify_kwargs as kwargs,
    )

    return kwargs()


def test_null_format_is_v3():
    from rl_curriculum.null_qualification import NULL_QUALIFICATION_FORMAT

    assert NULL_QUALIFICATION_FORMAT == "null-qualification-v3"
    assert "null-qualification-v2" in _DEPRECATED_NULL_FORMATS
    assert "null-qualification-v1" in _DEPRECATED_NULL_FORMATS


def test_deprecated_v2_report_rejected(null_qual_reports):
    """v2 格式报告(即使重算 hash 保持自洽)必须被新执行器拒绝。"""
    bindings = build_null_qualification_bindings(null_qual_reports)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["format"] = "null-qualification-v2"
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(null_qual_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("已弃用" in p for p in report["problems"])


def test_deprecated_v1_report_rejected(null_qual_reports):
    bindings = build_null_qualification_bindings(null_qual_reports)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["format"] = "null-qualification-v1"
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(null_qual_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("已弃用" in p for p in report["problems"])


def test_v2_schema_payload_rejected_by_key_set():
    """v2 的 24 键 schema(payload 键集合不同)在键集合对账层拒绝。"""
    v2_payload = {
        "format": "null-qualification-v2", "family": "x",
        "family_version": "v", "timeframe": "15m", "seeds": [1],
        "episodes_per_seed": 1, "n_episodes_tested": 1,
        "distinct_seeds": 1, "pass": True,
    }
    bindings = {"probe_null_sign": {
        "family_version": "v", "qualification_pass": True,
        "report_hash": qualification_report_hash(v2_payload),
        "report_payload": v2_payload}}
    report = verify_null_qualification_bindings(
        bindings, required_families=["probe_null_sign"],
        **_verify_kwargs())
    assert not report["pass"]
    assert any("键集合不符" in p for p in report["problems"])


def test_insufficient_verdict_rejected_even_if_hash_consistent(
        small_sample_reports):
    """verdict=INSUFFICIENT_EVIDENCE 且 hash 自洽的报告被明确拒绝
    (不得自动转换)。"""
    bindings = build_null_qualification_bindings(small_sample_reports)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(small_sample_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("只有 QUALIFIED 才能进入" in p
               for p in report["problems"])


def test_invalid_null_verdict_rejected(small_sample_reports):
    bindings = build_null_qualification_bindings(small_sample_reports)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["verdict"] = "INVALID_NULL"
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(small_sample_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("INVALID_NULL" in p for p in report["problems"])


def test_illegal_verdict_value_rejected(null_qual_reports):
    bindings = build_null_qualification_bindings(null_qual_reports)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["verdict"] = "PASS"  # 非法三态值
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(null_qual_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("合法三态" in p for p in report["problems"])


def test_pass_true_with_non_qualified_verdict_rejected(
        small_sample_reports):
    """pass=True + verdict=INSUFFICIENT_EVIDENCE 的自相矛盾报告被拒。"""
    bindings = build_null_qualification_bindings(small_sample_reports)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["pass"] = True  # 伪造
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(small_sample_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("pass 与三态" in p for p in report["problems"])


def test_qualification_params_tamper_rejected(null_qual_reports):
    """预注册参数被改(如放宽带值)且重算 hash -> 对账层拒绝。"""
    bindings = build_null_qualification_bindings(null_qual_reports)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["qualification_params"]["max_unconditional_long_edge"] = 0.9
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(null_qual_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("预注册参数" in p for p in report["problems"])


def test_sealed_exam_protocol_not_bumped(sealed_exam_env):
    """Null 资格语义变化由 nqc-/nq-/format 通道失效;承诺结构未变,
    SEALED_EXAM_PROTOCOL 保持 v3(不为资格语义单独升版)。"""
    from rl_curriculum.mock_sealed_exam import CONTEXT_FORMAT
    from rl_curriculum.sealed_exam import SEALED_EXAM_PROTOCOL

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v3"
    assert CONTEXT_FORMAT == "sealed-exam-context-v3"


def test_frozen_contracts_unchanged():
    """六项冻结合同 spec 版本保持不变(2.6.0d 不得触碰冻结合同)。"""
    from rl_platform.versions import CHECKPOINT_REQUIRED_VERSIONS

    frozen = CHECKPOINT_REQUIRED_VERSIONS
    assert frozen["env_core_version"] == "RouteCEnvCore-v1.0.0"
    assert frozen["observation_spec_version"] == "ObservationSpec-v1"
    assert frozen["action_spec_version"] == "BinaryLongFlatAction-v1"
    assert frozen["reward_spec_version"] == "NetLogEquityReward-v1"
    assert frozen["execution_contract_version"] == \
        "MarketOpenCausalExecution-v1"
    assert frozen["terminal_liquidation_version"] == "TerminalLiquidation-v1"


# ------------------------------------------------ 2.6.0c 行为保留守卫
def test_issuer_trust_root_still_commitment_only():
    """run_sealed_exam 签名不存在 trusted_issuer/issuer 覆盖参数
    (2.6.0c 工作包 A 的 API 面不得回退)。"""
    import rl_curriculum.formal_exam as fe

    sig = inspect.signature(fe.run_sealed_exam)
    for banned in ("trusted_issuer", "issuer", "issuer_payload"):
        assert banned not in sig.parameters, (
            f"run_sealed_exam 不得重新出现 issuer 覆盖参数 {banned!r}")


def test_no_replication_hardcoded_two_episodes():
    """反作弊复制不得恢复 replication_eps[:2] 硬编码截断
    (与 2.6.0c 守卫同款正则,不误伤说明性注释)。"""
    import re
    from pathlib import Path

    import rl_curriculum.formal_exam as fe

    src = Path(fe.__file__).read_text(encoding="utf-8")
    assert not re.search(r"replication_eps\[:\d+\]", src), (
        "formal_exam 不得恢复硬编码截取复制样本")


def test_no_always_true_assertions():
    """不得出现永真断言模式(反作弊与资格模块)。"""
    import rl_curriculum.counterfactual as cf
    import rl_curriculum.null_qualification as nq

    tautology = "or" + " True"
    for mod in (cf, nq):
        src = inspect.getsource(mod)
        assert tautology not in src, (
            f"{mod.__name__} 含 {tautology!r} 永真断言")


def test_commitment_still_binds_runtime_and_real_reports(
        sealed_exam_env):
    """承诺继续绑定候选运行时 manifest 与真实 Null 报告(2.6.0c
    工作包 B/D 的绑定面不得弱化)。"""
    from rl_curriculum.sandbox import (
        compute_runtime_manifest,
        runtime_tree_hash,
    )

    c = sealed_exam_env["commitment"]
    assert c.candidate_runtime_hash == runtime_tree_hash(
        c.candidate_runtime_manifest)
    assert c.candidate_runtime_manifest == compute_runtime_manifest()
    for fam in sealed_exam_env["verdict_spec"].required_null_families:
        bound = c.null_qualification_bindings[fam]
        assert bound["report_payload"]["format"] == \
            "null-qualification-v3"
        assert bound["report_payload"]["verdict"] == "QUALIFIED"
        assert bound["qualification_pass"] is True
        # bool-only 通道仍然不存在
        assert set(bound) == {
            "family_version", "qualification_pass", "report_hash",
            "report_payload"}


def test_bool_only_binding_still_rejected(null_qual_reports):
    bindings = build_null_qualification_bindings(null_qual_reports)
    tampered = copy.deepcopy(bindings)
    tampered["probe_null_sign"] = {"qualification_pass": True}
    report = verify_null_qualification_bindings(
        tampered, required_families=sorted(null_qual_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("bool-only" in p for p in report["problems"])
