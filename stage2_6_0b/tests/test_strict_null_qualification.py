"""工作包 H3/H5:三种严格 Null 均通过自身资格审查。"""

from __future__ import annotations

import pytest


def test_all_three_strict_nulls_qualified(null_qual_reports):
    assert set(null_qual_reports) == {
        "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"}
    for fam, rep in null_qual_reports.items():
        assert rep["pass"], f"{fam} 未通过资格审查: {rep['reasons']}"
        checks = rep["checks"]
        assert checks["oracle_no_stable_directional_edge"]
        assert checks["rule_no_stable_excess"]
        assert checks["always_flat_strong_baseline"]
        assert checks["high_frequency_loses_after_fees"]
        assert checks["multi_seed_coverage"]
        assert rep["distinct_seeds"] >= 3
        assert rep["n_episodes_tested"] >= 3


def test_oracle_has_no_edge_on_strict_nulls(null_qual_reports):
    for fam, rep in null_qual_reports.items():
        boot = rep["oracle"]["excess_bootstrap"]
        assert boot["ci_low"] <= 0.0, (
            f"{fam}: Oracle 保留稳定方向优势(CI low={boot['ci_low']})")


def test_rule_trend_has_no_excess(null_qual_reports):
    for fam, rep in null_qual_reports.items():
        boot = rep["rule_trend"]["excess_bootstrap"]
        assert boot["ci_low"] <= 0.0, (
            f"{fam}: RuleTrend 保留稳定正超额(CI low={boot['ci_low']})")


def test_high_frequency_loses_after_fees(null_qual_reports):
    for fam, rep in null_qual_reports.items():
        assert rep["high_turnover_median"] < 0.0


def test_stochvol_independence_documented():
    """第三族与前两族实现机制不同(独立构造,非源轨迹变换)。"""
    from rl_curriculum.generators import _NULL_META_DOC

    doc = _NULL_META_DOC["probe_null_stochvol"]
    assert "不依赖 probe A 源轨迹" in doc["independence"]
    assert "马尔可夫" in doc["preserves"]
    assert "iid" in doc["destroys"]


def test_qualification_bindings_enter_commitment(sealed_exam_env):
    commitment = sealed_exam_env["commitment"]
    bindings = commitment.null_qualification_bindings
    for fam in sealed_exam_env["verdict_spec"].required_null_families:
        assert fam in bindings
        assert bindings[fam]["qualification_pass"] is True
        assert bindings[fam]["report_hash"].startswith("nq-")
    assert commitment.null_qualification_code_hash.startswith("nqc-")
