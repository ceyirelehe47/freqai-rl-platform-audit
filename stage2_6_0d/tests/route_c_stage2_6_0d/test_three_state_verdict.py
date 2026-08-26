"""工作包 A1 + D1/D3:三态结论与"不显著不等于等价"。

2.6.0d 语义:QUALIFIED / INVALID_NULL / INSUFFICIENT_EVIDENCE;
INSUFFICIENT 不得进入正式考试,不得被自动转换为 PASS;3-seed 报告
必须不再 QUALIFIED(任务书硬要求);stochvol +2.40% / sign +0.75%
反例复现并触发经济优势检查失败(D1)。
"""

from __future__ import annotations

from rl_curriculum.null_qualification import NULL_VERDICTS


def _null_verify_kwargs():
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema

    return {
        "generator_bindings": generator_bindings(dict(R)),
        "observation_schema_hash": probe_observation_schema().schema_hash(),
        "eval_config_manifest": default_eval_config().manifest(),
        "timeframe": "15m",
    }


def test_three_state_verdict_constants():
    assert NULL_VERDICTS == (
        "QUALIFIED", "INVALID_NULL", "INSUFFICIENT_EVIDENCE")


def test_small_sample_reports_not_qualified(small_sample_reports):
    """任务书硬性要求:当前 3-seed 资格报告必须不再得到 QUALIFIED。
    D1:至少 INSUFFICIENT_EVIDENCE;stochvol 的 +2.40% 样本恰好构成
    经济反证(CI 下界 > margin)时升级为 INVALID_NULL——两种结论都
    满足"不再 QUALIFIED",反证优先是更强的正确判定。"""
    for fam, rep in small_sample_reports.items():
        assert rep["verdict"] in ("INSUFFICIENT_EVIDENCE", "INVALID_NULL")
        assert rep["verdict"] != "QUALIFIED"
        assert rep["pass"] is False
        assert rep["checks"]["multi_seed_coverage"] is False
    assert small_sample_reports["probe_null_stochvol"][
        "verdict"] == "INVALID_NULL", (
        "stochvol 3-seed(+2.40% 样本)的 lf CI 下界超 margin,应触发"
        "经济反证(D1:额外触发经济优势失败)")
    assert small_sample_reports["probe_null_sign"][
        "verdict"] == "INSUFFICIENT_EVIDENCE"


def test_stochvol_counterexample_triggers_economic_failure(
        small_sample_reports):
    """D1:stochvol 3-seed 反例(Always Long 中位 ~+2.40%)复现,且
    额外触发经济优势失败(always_flat_strong_baseline=False)。"""
    rep = small_sample_reports["probe_null_stochvol"]
    assert rep["always_flat_median"] == 0.0
    assert rep["always_long_median"] > 0.02, (
        f"应复现审查反例量级(~+2.40%),实际 "
        f"{rep['always_long_median']:+.5f}")
    lf = rep["always_long_vs_flat"]["bootstrap"]
    assert lf["ci_high"] > rep["margin"]["value"], (
        "3-seed 样本 lf CI 上界必须超出 margin(该样本构成反例)")
    assert rep["checks"]["always_flat_strong_baseline"] is False
    assert rep["verdict"] != "QUALIFIED"


def test_sign_counterexample_triggers_economic_failure(
        small_sample_reports):
    """D1:sign 3-seed 反例(~+0.75%)复现且不再 QUALIFIED。"""
    rep = small_sample_reports["probe_null_sign"]
    assert rep["always_long_median"] > 0.007
    assert rep["checks"]["always_flat_strong_baseline"] is False
    assert rep["verdict"] != "QUALIFIED"
    assert rep["pass"] is False


def test_insufficient_evidence_cannot_enter_exam(small_sample_reports):
    """INSUFFICIENT 报告进入承诺 -> verify 拒绝(旧 3-seed 证据作为
    旧证据输入新 verifier 的处置;D1)。"""
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        verify_null_qualification_bindings,
    )

    bindings = build_null_qualification_bindings(small_sample_reports)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(small_sample_reports),
        **_null_verify_kwargs())
    assert not report["pass"]
    assert any("INSUFFICIENT" in p or "cluster 数不足" in p
               for p in report["problems"])


def test_insufficient_not_auto_converted_to_pass(small_sample_reports):
    """不存在 INSUFFICIENT -> PASS 的自动转换通道(D1)。"""
    for rep in small_sample_reports.values():
        assert rep["pass"] == (rep["verdict"] == "QUALIFIED")
        assert rep["pass"] is False


def test_drifting_pseudo_null_is_invalid_null(schema, cfg):
    """D4:Always Long 优势 >> 往返摩擦 -> INVALID_NULL。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family

    params = dict(BASE_PARAMS)
    params["direction_weights"] = [0.0, 0.85, 0.15]
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=list(range(11, 75)), cfg=cfg, schema=schema,
        episodes_per_seed=2)
    assert rep["verdict"] == "INVALID_NULL", rep["reasons"]
    assert rep["pass"] is False
    assert rep["checks"]["always_flat_strong_baseline"] is False


def test_structural_pseudo_null_is_invalid_null(schema, cfg):
    """D4:Oracle/规则优势(结构性预测关系)-> INVALID_NULL。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family

    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=dict(BASE_PARAMS),
        timeframe="15m", seeds=[101, 102, 103, 104, 105, 106],
        cfg=cfg, schema=schema, episodes_per_seed=2)
    assert rep["verdict"] == "INVALID_NULL"
    assert not rep["checks"]["oracle_no_tradable_edge"]
    assert not rep["checks"]["rule_no_tradable_edge"], (
        "方向可预测的伪 Null 上 RuleTrend 也必须有优势")


def test_full_sample_strict_nulls_qualified(null_qual_reports):
    """D5:充足功效(64 cluster x 16 ep)下三族真实 QUALIFIED。"""
    for fam, rep in null_qual_reports.items():
        assert rep["verdict"] == "QUALIFIED", (
            f"{fam} 应达 QUALIFIED: {rep['reasons']}")
        assert rep["pass"] is True
        assert all(rep["checks"].values()), rep["checks"]


def test_verdict_rules_are_check_consistent(null_qual_reports,
                                            small_sample_reports):
    """三态推导与 checks 的一致性(QUALIFIED <=> checks 全真)。"""
    for reports in (null_qual_reports, small_sample_reports):
        for rep in reports.values():
            all_checks = all(rep["checks"].values())
            assert (rep["verdict"] == "QUALIFIED") == all_checks
