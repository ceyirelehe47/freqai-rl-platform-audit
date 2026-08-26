"""工作包 A1:Null 资格的显式三态结论。

2.6.0c 的问题:资格判定只有单一布尔 pass——把"没有显著发现正
收益"错误解释为"已证明不存在经济上可交易的优势";当前 3-seed
资格样本(统计功效不足)仍得到 PASS。

2.6.0d 语义:
- QUALIFIED:结构、经济等价、统计功效与实际 pack 全部成立;
- INVALID_NULL:发现可交易漂移、Oracle/规则优势、结构性预测关系
  或其他明确反证;
- INSUFFICIENT_EVIDENCE:样本数或统计功效不足,不能证明等价;
  不得进入正式考试,不得被自动转换为 PASS。

任务书反例(必须不再 QUALIFIED):
- probe_null_stochvol 3-seed:Always Flat 中位 0,Always Long 中位
  约 +2.40%,仍被旧实现判 always_flat_strong_baseline=true;
- probe_null_sign 3-seed:Always Long 中位约 +0.75%,同样 PASS。
"""

from __future__ import annotations

from rl_curriculum.null_qualification import (
    NULL_VERDICTS,
    qualify_null_family,
)


def test_three_state_verdict_constants():
    assert NULL_VERDICTS == (
        "QUALIFIED", "INVALID_NULL", "INSUFFICIENT_EVIDENCE")


def test_small_sample_reports_are_insufficient_evidence(
        small_sample_reports):
    """任务书硬性要求:当前 3-seed 资格报告必须不再得到 QUALIFIED。"""
    for fam, rep in small_sample_reports.items():
        assert rep["verdict"] == "INSUFFICIENT_EVIDENCE", (
            f"{fam} 3-seed 样本三态结论应为 INSUFFICIENT_EVIDENCE"
            f"(统计功效不足),实际 {rep['verdict']};reasons="
            f"{rep['reasons']}")
        assert rep["pass"] is False
        assert rep["checks"]["multi_seed_coverage"] is False


def test_stochvol_counterexample_no_longer_qualified(small_sample_reports):
    """stochvol 3-seed 反例:Always Long 中位约 +2.40% 且 Always Flat
    中位为 0,旧实现仍判 always_flat_strong_baseline=true 并整体
    PASS——新协议下必须不是 QUALIFIED。"""
    rep = small_sample_reports["probe_null_stochvol"]
    assert rep["always_flat_median"] == 0.0
    assert rep["always_long_median"] > 0.02, (
        f"应复现审查反例量级(Always Long 中位 ~+2.40%),实际 "
        f"{rep['always_long_median']:+.5f}")
    assert rep["verdict"] != "QUALIFIED"
    assert rep["pass"] is False


def test_sign_counterexample_no_longer_qualified(small_sample_reports):
    """sign 3-seed 反例:Always Long 中位约 +0.75% 仍 PASS。"""
    rep = small_sample_reports["probe_null_sign"]
    assert rep["always_long_median"] > 0.007, (
        f"应复现审查反例量级(Always Long 中位 ~+0.75%),实际 "
        f"{rep['always_long_median']:+.5f}")
    assert rep["verdict"] != "QUALIFIED"
    assert rep["pass"] is False


def test_insufficient_evidence_cannot_enter_exam(small_sample_reports,
                                                 schema, cfg):
    """INSUFFICIENT_EVIDENCE 报告进入承诺 -> verify 拒绝。"""
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        verify_null_qualification_bindings,
    )
    from tests.route_c_stage2_6_0b.test_invalid_null_rejected import (
        _verify_kwargs,
    )

    bindings = build_null_qualification_bindings(small_sample_reports)
    report = verify_null_qualification_bindings(
        bindings, required_families=sorted(small_sample_reports),
        **_verify_kwargs())
    assert not report["pass"]
    assert any("INSUFFICIENT" in p or "cluster 数不足" in p
               for p in report["problems"])


def test_insufficient_not_auto_converted_to_pass(small_sample_reports):
    """不存在 INSUFFICIENT -> PASS 的自动转换通道:报告的 pass 别名
    必须严格等于 (verdict == QUALIFIED)。"""
    for rep in small_sample_reports.values():
        assert rep["pass"] == (rep["verdict"] == "QUALIFIED")
        assert rep["pass"] is False


def test_drifting_pseudo_null_is_invalid_null(schema, cfg):
    """发现可交易漂移 -> INVALID_NULL(direction_weights 偏置的伪
    Null,64 cluster 样本:无条件多头优势 CI 下界远超带)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    params = dict(BASE_PARAMS)
    params["direction_weights"] = [0.0, 0.85, 0.15]
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=list(range(11, 75)), cfg=cfg, schema=schema,
        episodes_per_seed=2)
    assert rep["verdict"] == "INVALID_NULL", rep["reasons"]
    assert rep["pass"] is False
    assert any("经济反证" in r or "可交易" in r for r in rep["reasons"])


def test_structural_pseudo_null_is_invalid_null(schema, cfg):
    """Oracle 稳定方向优势(结构性预测关系)-> INVALID_NULL。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=dict(BASE_PARAMS),
        timeframe="15m", seeds=[101, 102, 103, 104, 105, 106],
        cfg=cfg, schema=schema, episodes_per_seed=2)
    assert rep["verdict"] == "INVALID_NULL"
    assert not rep["checks"]["oracle_no_stable_directional_edge"]


def test_full_sample_strict_nulls_qualified(null_qual_reports):
    """充足功效(64 cluster x 8 episodes)下三族严格 Null 均
    QUALIFIED——mock 正式链路的资格来源。"""
    for fam, rep in null_qual_reports.items():
        assert rep["verdict"] == "QUALIFIED", (
            f"{fam} 应达 QUALIFIED: {rep['reasons']}")
        assert rep["pass"] is True
        assert all(rep["checks"].values()), rep["checks"]


def test_verdict_rules_are_check_consistent(null_qual_reports,
                                            small_sample_reports):
    """三态推导与 checks 的一致性:QUALIFIED <=> 六项 checks 全真;
    反证检查失败(结构)时 verdict 不得是 QUALIFIED。"""
    for reports in (null_qual_reports, small_sample_reports):
        for rep in reports.values():
            all_checks = all(rep["checks"].values())
            assert (rep["verdict"] == "QUALIFIED") == all_checks, (
                f"三态结论 {rep['verdict']} 与 checks {rep['checks']} "
                f"不一致")
