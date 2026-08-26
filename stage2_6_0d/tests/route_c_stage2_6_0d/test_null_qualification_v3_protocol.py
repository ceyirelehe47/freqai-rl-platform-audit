"""工作包 C/E + D8:协议升级(null-qualification-v3 / sealed v4 /
CLI v5)与全链路绑定对账。

- 旧 v1/v2 Null 报告与 v3 承诺均不得被新执行器自动接受;
- 承诺绑定 qualification spec hash / 功效分析 / pack 构建算法 /
  pack validity(nqs-/npa-/npac-/npv-/npb-),任一内容变化使旧
  承诺失效(D8);
- 报告必须携带完整统计证据(C1 清单);
- 2.6.0c 实现保留守卫(issuer/runtime/反作弊)。
"""

from __future__ import annotations

import copy
import inspect
import re
from pathlib import Path

import pytest

from rl_curriculum.null_qualification import (
    _DEPRECATED_NULL_FORMATS,
    build_null_qualification_bindings,
    qualification_report_hash,
    verify_null_qualification_bindings,
)


def _null_verify_kwargs(spec_hash=None, power_ref=None):
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema

    kw = {
        "generator_bindings": generator_bindings(dict(R)),
        "observation_schema_hash": probe_observation_schema().schema_hash(),
        "eval_config_manifest": default_eval_config().manifest(),
        "timeframe": "15m",
    }
    if spec_hash:
        kw["qualification_spec_hash"] = spec_hash
    if power_ref:
        kw["power_analysis_ref"] = power_ref
    return kw


def test_null_format_is_v3_and_deprecated_listed():
    from rl_curriculum.null_qualification import NULL_QUALIFICATION_FORMAT

    assert NULL_QUALIFICATION_FORMAT == "null-qualification-v3"
    assert "null-qualification-v2" in _DEPRECATED_NULL_FORMATS
    assert "null-qualification-v1" in _DEPRECATED_NULL_FORMATS


def test_sealed_protocol_is_v4_and_v3_deprecated():
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS,
        SEALED_EXAM_PROTOCOL,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v4"
    assert "sealed-exam-commitment-v3" in _DEPRECATED_PROTOCOLS


def test_cli_version_is_v5():
    import rl_curriculum.formal_exam as fe
    import rl_curriculum.hidden_exam_cli as cli

    assert fe.EXAM_CLI_VERSION == "hidden-exam-cli-v5"
    assert cli.CLI_VERSION == fe.EXAM_CLI_VERSION


def test_v3_commitment_rejected_by_v4_executor(sealed_exam_env):
    """2.6.0c 的 v3 承诺(缺 spec/power/pack 绑定)被显式拒绝。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    v3_json = sealed_exam_env["commitment"].to_json().replace(
        "sealed-exam-commitment-v4", "sealed-exam-commitment-v3")
    with pytest.raises(SealedExamError, match="已弃用|v3 缺少"):
        SealedExamCommitment.from_json(v3_json)


def test_commitment_missing_new_fields_rejected(sealed_exam_env):
    """缺 spec hash / power / pack validity / builder hash 任一字段
    -> from_json 显式报错(不静默补默认值)。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    data = sealed_exam_env["commitment"].to_json()
    for key, match in (
        ("null_qualification_spec_hash", "spec 哈希|spec_hash|nqs"),
        ("null_power_analysis", "功效分析"),
        ("pack_validity", "pack-level validity"),
        ("pack_builder_code_hash", "pack 构建算法"),
    ):
        import json as _json

        payload = _json.loads(data)
        payload.pop(key, None)
        with pytest.raises(SealedExamError, match=match):
            SealedExamCommitment.from_json(_json.dumps(payload))


def test_commitment_binds_full_null_chain(sealed_exam_env):
    """C2:承诺绑定 spec hash / 功效分析(hash+代码+摘要)/构建算法
    hash / pack validity(hash+pack_hash+摘要)。"""
    from rl_curriculum.null_power_analysis import (
        power_analysis_code_hash,
    )
    from rl_curriculum.null_pack_validation import (
        pack_builder_code_hash,
    )

    c = sealed_exam_env["commitment"]
    assert c.null_qualification_spec_hash.startswith("nqs-")
    pa = c.null_power_analysis
    assert pa["report_hash"].startswith("npa-")
    assert pa["code_hash"] == power_analysis_code_hash()
    assert pa["public_summary"]["targets_met"] is True
    assert c.pack_builder_code_hash == pack_builder_code_hash()
    pv = c.pack_validity
    assert pv["report_hash"].startswith("npv-")
    assert pv["pack_hash"] == sealed_exam_env["pack"].pack_hash()
    assert pv["public_summary"]["verdict"] == "PACK_VALID"


def test_reports_carry_full_statistical_evidence(null_qual_chain):
    """C1:报告记录完整统计证据(协议/三态/绑定/spec/统计方法/时长/
    cluster/中心与上界/功效引用/level/失败原因)。"""
    chain = null_qual_chain
    for fam, rep in chain["reports"].items():
        assert rep["format"] == "null-qualification-v3"
        assert rep["level"] == "family"
        assert rep["verdict"] == "QUALIFIED"
        assert rep["qualification_spec_hash"] == chain["spec_hash"]
        assert rep["power_analysis_ref"] and rep["power_analysis_ref"][
            :4] == "npa-"
        assert rep["statistical_protocol"]["confidence_level"] == 0.95
        assert rep["statistical_protocol"]["bootstrap_seed"] == 20260826
        assert rep["episode_duration_hours"] == 24.0
        assert rep["margin"]["derivation"]["formula"] == \
            "1 - (1 - fee)^2 * (1 - slippage)^2"
        assert rep["seeds_namespace_conform"] is True
        for block in ("oracle", "rule_trend", "always_long_vs_flat",
                      "high_turnover_vs_flat"):
            b = rep[block]
            assert {"cluster_values", "mean", "bootstrap"} <= set(b)


def test_power_analysis_binding_and_targets(null_qual_chain):
    """A5:功效分析确定可复现且目标达成;32 cluster 不足被实证。"""
    from rl_curriculum.null_power_analysis import (
        run_power_analysis,
        power_analysis_report_hash,
    )

    power = null_qual_chain["power_report"]
    t = power["targets"]
    assert t["targets_met"] is True
    assert t["max_false_invalid_at_zero"] <= 0.05
    assert t["max_false_qualified_at_2x_margin"] <= 0.05
    assert t["min_rejection_power_at_1x_margin"] >= 0.80
    n32 = power["n32_sufficiency"]
    assert n32 is not None, "32-cluster 充分性证据必须被记录"
    # 固定预注册 seeds 不允许重选:即使 1xmargin 拒绝功效达标,
    # 零优势样本获得 QUALIFIED 的成功率不足 95% 时仍采用 64
    if n32["meets_targets_with_margin"]:
        assert n32["one_margin_rejection_power"] >= 0.80
        assert n32["zero_edge_qualified_rate"] >= 0.95
    else:
        assert (n32["one_margin_rejection_power"] < 0.80
                or (n32["zero_edge_qualified_rate"] is not None
                    and n32["zero_edge_qualified_rate"] < 0.95))
    # 确定性重跑 -> 同一报告 hash
    again = run_power_analysis(
        null_qual_chain["reports"],
        margin=null_qual_chain["spec"]["margin"])
    assert power_analysis_report_hash(again) == power_analysis_report_hash(
        power)


def test_d8_margin_change_invalidates_commitment(sealed_exam_env):
    """D8:执行器以不同 EvalConfig(不同 fee -> 不同 margin)验证承诺
    -> spec hash 重算不一致 -> 承诺失效。"""
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    wider_cfg = EvalConfig(fee=0.0005)  # 更低费用 -> 更小 margin
    with pytest.raises(SealedExamError) as exc_info:
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=wider_cfg, verdict_spec=env["verdict_spec"],
            sandbox_profile=default_sandbox_profile())
    msg = str(exc_info.value)
    assert "EvalConfig 不匹配" in msg  # 承诺的 fee 绑定生效
    assert "规范哈希不匹配" in msg, (
        "不同 fee -> 不同 margin -> spec 哈希不一致,必须失效(D8)")


def test_d8_confidence_bootstrap_change_invalidates():
    """D8:置信水平/bootstrap 规则/聚合/min cluster 变化 -> nqs- 变。"""
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.null_qualification_spec import (
        build_spec_payload,
        null_qualification_spec_hash,
    )

    cfg = default_eval_config()
    base = build_spec_payload(cfg, timeframe="15m", episode_bars=96)
    h1 = null_qualification_spec_hash(base)
    for mutate in (
        lambda s: s["statistical_protocol"].__setitem__(
            "confidence_level", 0.99),
        lambda s: s["statistical_protocol"].__setitem__(
            "bootstrap_iters", 5000),
        lambda s: s.__setitem__("cluster_aggregation", "other-v1"),
        lambda s: s.__setitem__("min_qualification_clusters", 32),
        lambda s: s["power_targets"].__setitem__(
            "min_rejection_power_at_1x_margin", 0.5),
        lambda s: s.__setitem__("episode_duration_hours", 12.0),
        lambda s: s.__setitem__("timeframe", "1h"),
    ):
        tampered = copy.deepcopy(base)
        mutate(tampered)
        assert null_qualification_spec_hash(tampered) != h1, mutate


def test_d8_spec_hash_mismatch_in_report_rejected(null_qual_reports):
    """报告引用的 spec hash 与承诺不一致 -> verify 拒绝。"""
    base = build_null_qualification_bindings(null_qual_reports)

    def _verify_with(mutation):
        bindings = copy.deepcopy(base)
        payload = bindings["probe_null_sign"]["report_payload"]
        mutation(payload)
        bindings["probe_null_sign"]["report_hash"] = \
            qualification_report_hash(payload)
        return verify_null_qualification_bindings(
            bindings, required_families=sorted(null_qual_reports),
            **_null_verify_kwargs(
                spec_hash="nqs-tampered",
                power_ref=bindings["probe_null_sign"]["report_payload"][
                    "power_analysis_ref"]))

    r = _verify_with(lambda p: None)  # hash 本就不同(承诺传假值)
    assert not r["pass"]
    assert any("spec hash" in p for p in r["problems"])

    r2 = _verify_with(
        lambda p: p.__setitem__("power_analysis_ref", "npa-forged"))
    assert not r2["pass"]
    assert any("power" in p for p in r2["problems"])


def test_frozen_contracts_unchanged():
    """六项冻结合同 spec 版本保持不变。"""
    from rl_platform.versions import CHECKPOINT_REQUIRED_VERSIONS as F

    assert F["env_core_version"] == "RouteCEnvCore-v1.0.0"
    assert F["observation_spec_version"] == "ObservationSpec-v1"
    assert F["action_spec_version"] == "BinaryLongFlatAction-v1"
    assert F["reward_spec_version"] == "NetLogEquityReward-v1"
    assert F["execution_contract_version"] == "MarketOpenCausalExecution-v1"
    assert F["terminal_liquidation_version"] == "TerminalLiquidation-v1"


def test_unchanged_protocols_not_bumped():
    """语义未变的协议不升级(checkpoint manifest v3 / attestation v1 /
    candidate runtime manifest v1 / context v3)。"""
    from rl_curriculum.checkpoints import MANIFEST_SCHEMA_VERSION
    from rl_curriculum.mock_sealed_exam import CONTEXT_FORMAT
    from rl_curriculum.sandbox import CANDIDATE_RUNTIME_MANIFEST_FORMAT
    from rl_curriculum import attestation

    assert MANIFEST_SCHEMA_VERSION == "checkpoint-manifest-v3"
    assert attestation.ATTESTATION_PROTOCOL == "training-attestation-v1"
    assert CANDIDATE_RUNTIME_MANIFEST_FORMAT == \
        "candidate-runtime-manifest-v1"
    assert CONTEXT_FORMAT == "sealed-exam-context-v3"


# ------------------------------------------------ 2.6.0c 行为保留守卫
def test_issuer_trust_root_still_commitment_only():
    import rl_curriculum.formal_exam as fe

    sig = inspect.signature(fe.run_sealed_exam)
    for banned in ("trusted_issuer", "issuer", "issuer_payload"):
        assert banned not in sig.parameters


def test_no_replication_hardcoded_two_episodes():
    import rl_curriculum.formal_exam as fe

    src = Path(fe.__file__).read_text(encoding="utf-8")
    assert not re.search(r"replication_eps\[:\d+\]", src)


def test_no_always_true_assertions():
    """不得出现永真断言模式(拼接构造避免静态扫描误报)。"""
    import rl_curriculum.counterfactual as cf
    import rl_curriculum.null_qualification as nq

    tautology = "or" + " True"
    for mod in (cf, nq):
        src = inspect.getsource(mod)
        assert tautology not in src


def test_commitment_still_binds_runtime_and_real_reports(
        sealed_exam_env):
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
        assert set(bound) == {
            "family_version", "qualification_pass", "report_hash",
            "report_payload"}


def test_bool_only_binding_still_rejected(null_qual_reports):
    tampered = build_null_qualification_bindings(null_qual_reports)
    tampered["probe_null_sign"] = {"qualification_pass": True}
    report = verify_null_qualification_bindings(
        tampered, required_families=sorted(null_qual_reports),
        **_null_verify_kwargs())
    assert not report["pass"]
    assert any("bool-only" in p for p in report["problems"])
