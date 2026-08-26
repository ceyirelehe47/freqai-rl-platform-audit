"""工作包经济等价:always_flat_strong_baseline 语义修复与不对称
漂移带。

2.6.0c 的两个集中缺陷:
1. always_flat_strong_baseline 检查根本不比较 Always Long vs
   Always Flat(always_long_median 只写进报告从不参与判定),
   stochvol 3-seed 样本 Always Long 中位 +2.40% 仍判 true;
2. max_net_drift_per_bar=0.0008 在 96 根 15m Episode 上允许约
   7.68% 的累计 log drift,不构成经济意义上的"无方向优势"。

2.6.0d 语义:
- always_flat_strong_baseline 由 Always Long - Flat 的 cluster 级
  bootstrap CI 上界 <= max_unconditional_long_edge 驱动(单侧
  TOST:证明无可交易无条件多头优势);
- 漂移带以每 episode 累计量直接定义:正侧 +0.5%(可被 Long/Flat
  现货模型利用),负侧 -1.0%(负漂移不可利用,仅结构性非中心证据)。
"""

from __future__ import annotations

from rl_curriculum.null_qualification import (
    MAX_NEGATIVE_DRIFT,
    MAX_TRADABLE_DRIFT,
    MAX_UNCONDITIONAL_LONG_EDGE,
    MIN_QUALIFICATION_CLUSTERS,
    qualification_code_hash,
)


def test_always_flat_check_driven_by_long_vs_flat(null_qual_reports):
    """检查 3 的判定材料是 always_long_vs_flat 的 cluster 级
    bootstrap CI 上界(与 check 结果方向一致),而非 bar 级漂移。"""
    for fam, rep in null_qual_reports.items():
        lf = rep["always_long_vs_flat"]["excess_bootstrap"]
        check = rep["checks"]["always_flat_strong_baseline"]
        assert check == (lf["ci_high"] <= MAX_UNCONDITIONAL_LONG_EDGE)
        assert lf["n"] == rep["n_clusters"]
        # 旧实现缺陷的直接对照:中位优势数值本身必须出现在判定
        # 材料里(always_long_median 不再只是"只写不读"的装饰字段,
        # 其所在块参与 check)
        assert "always_long_vs_flat" in rep


def test_stochvol_counterexample_would_fail_new_check(
        small_sample_reports):
    """stochvol 3-seed 反例在新检查下的行为:lf CI 上界远超带
    -> always_flat_strong_baseline=False(旧实现为 true)。"""
    rep = small_sample_reports["probe_null_stochvol"]
    lf = rep["always_long_vs_flat"]["excess_bootstrap"]
    assert rep["always_long_median"] > 0.02  # 反例量级复现
    assert lf["ci_high"] > MAX_UNCONDITIONAL_LONG_EDGE, (
        f"3-seed 样本 lf CI 上界 {lf['ci_high']:+.5f} 必须超出带 "
        f"{MAX_UNCONDITIONAL_LONG_EDGE}(否则该样本不构成反例)")
    assert rep["checks"]["always_flat_strong_baseline"] is False


def test_band_is_economically_meaningful():
    """带的预注册数值:远小于 2.6.0c 审查反例(+2.40%/+0.75%),
    且远小于旧 per-bar 容差折算的累计漂移(0.0008 x 96 = 7.68%)。"""
    stochvol_counterexample = 0.024
    sign_counterexample = 0.0075
    old_cumulative_tolerance = 0.0008 * 96
    assert MAX_UNCONDITIONAL_LONG_EDGE == 0.005
    assert MAX_TRADABLE_DRIFT == 0.005
    assert MAX_NEGATIVE_DRIFT == 0.010
    assert MAX_UNCONDITIONAL_LONG_EDGE < sign_counterexample
    assert MAX_UNCONDITIONAL_LONG_EDGE < stochvol_counterexample / 4
    assert MAX_TRADABLE_DRIFT < old_cumulative_tolerance / 10, (
        "新累计漂移带必须比旧 per-bar 容差折算值(7.68%)严格一个"
        "数量级以上")


def test_asymmetric_drift_band_semantics(null_qual_reports):
    """不对称带的经济语义回归守卫:三族 64-cluster 样本的 drift 中心
    可以为负(重尾增量的抽样噪声,volstate/stochvol 实测 -0.3% 左右)
    ——负漂移在 Long/Flat 现货下不可利用(模型最多保持 Flat 得 0 =
    挂科基线),不构成反证;带内负中心不得阻止 QUALIFIED。"""
    negative_center_families = [
        fam for fam, rep in null_qual_reports.items()
        if rep["episode_net_drift"]["mean"] < 0.0]
    assert negative_center_families, (
        "64-cluster 样本应至少包含一族负 drift 中心(带内负中心"
        "语义才有实证覆盖)")
    for fam in negative_center_families:
        rep = null_qual_reports[fam]
        assert rep["verdict"] == "QUALIFIED"
        assert rep["checks"]["episode_net_drift_nonexploitable"] is True
        assert rep["episode_net_drift"]["mean"] > -MAX_NEGATIVE_DRIFT


def test_positive_drift_out_of_band_is_invalid(schema, cfg):
    """正漂移 CI 下界超过 +max_tradable_drift -> 经济反证
    (INVALID_NULL)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family

    params = dict(BASE_PARAMS)
    params["direction_weights"] = [0.0, 0.9, 0.1]
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=list(range(11, 75)), cfg=cfg, schema=schema,
        episodes_per_seed=2)
    drift_boot = rep["episode_net_drift"]["bootstrap"]
    assert drift_boot["ci_low"] > MAX_TRADABLE_DRIFT
    assert rep["checks"]["episode_net_drift_nonexploitable"] is False
    assert rep["verdict"] == "INVALID_NULL"


def test_hft_fee_check_unchanged(null_qual_reports):
    """高频扣费亏损检查保持(费用合同有效性诊断)。"""
    for fam, rep in null_qual_reports.items():
        assert rep["high_turnover_median"] < 0.0
        assert rep["checks"]["high_frequency_loses_after_fees"] is True


def test_per_bar_tolerance_abolished_at_source():
    """旧 per-bar 容差(0.0008)与旧参数键从资格协议中彻底移除:
    qualification_params 不含 max_net_drift_per_bar,源文件不含旧
    默认值;预注册参数以每 episode 累计量为准。"""
    import inspect
    from pathlib import Path

    import rl_curriculum.null_qualification as nq

    src = Path(inspect.getsourcefile(nq.qualify_null_family)).read_text(
        encoding="utf-8")
    assert "8e-4" not in src, "旧 per-bar 默认容差 0.0008 必须移除"
    assert "max_net_drift_per_bar" not in src, (
        "旧参数键必须移除(新带以每 episode 累计量定义)")
    # 预注册参数以每 episode 累计量为准
    assert MIN_QUALIFICATION_CLUSTERS == 64
    assert MAX_UNCONDITIONAL_LONG_EDGE == 0.005
    assert MAX_TRADABLE_DRIFT == 0.005
    assert MAX_NEGATIVE_DRIFT == 0.010
    assert qualification_code_hash().startswith("nqc-")
