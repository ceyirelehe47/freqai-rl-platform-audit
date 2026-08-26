"""工作包 A3/A4 + D4:经济 margin 只来自资格规范,单侧上置信界
非优越性检验,禁止"不显著=等价"。

- margin = 一次完整往返摩擦,按 EvalConfig 精确计算
  (1-(1-fee)^2*(1-slippage)^2 = 0.001999,不写死常数);
- 三个差值(AlwaysLong/Oracle/ObservableRule 相对 Flat)+ HighTurnover
  全部使用"中心 <= margin 且单侧置信上界 <= margin"(HFT 容差 0);
- 生成器参数通道(null_qual_max_net_drift_per_bar)与 per-bar 容差
  废除;margin 绑定 Episode 真实时长(96 x 15m = 24h);
- D4 经济优势场景:Rule 优势 / HFT 稳定正收益 / 小幅固定正漂移。
"""

from __future__ import annotations

import inspect

from rl_curriculum.null_qualification import qualify_null_family
from rl_curriculum.null_qualification_spec import (
    MIN_QUALIFICATION_CLUSTERS,
    build_spec_payload,
    episode_duration_hours,
    null_qualification_spec_hash,
    qualification_seeds,
    round_trip_friction,
    verify_spec_payload,
)


def test_margin_is_exact_round_trip_friction(cfg):
    """A4 硬要求:margin 按冻结环境实际乘法成本精确计算(fee=0.001、
    slippage=0 时 = 0.001999,不是写死的 0.002)。"""
    margin = round_trip_friction(cfg)
    assert margin == 1 - (1 - 0.001) ** 2
    assert abs(margin - 0.001999) < 1e-15
    assert margin < 0.002  # 精确值严格小于名义 0.002
    # margin 按 Episode 真实时间定义(96 x 15m = 24h)
    assert episode_duration_hours(96, "15m") == 24.0


def test_margin_below_both_review_counterexamples(cfg):
    """margin(0.001999)远小于两个审查反例(+2.40% / +0.75%)与旧
    per-bar 容差折算值(0.0008 x 96 = 7.68%)。"""
    m = round_trip_friction(cfg)
    assert m < 0.0075 < 0.024  # sign 反例 < stochvol 反例
    assert m < 0.0008 * 96 / 10


def test_all_differences_use_upper_bound_test(null_qual_reports):
    """A3:四个差值块都记录中心/CI 上界,检查由两者共同驱动;不使用
    p-value 或 CI 包含零。"""
    m = null_qual_reports["probe_null_sign"]["margin"]["value"]
    for fam, rep in null_qual_reports.items():
        assert rep["margin"]["value"] == m
        for block, check_name in (
            ("always_long_vs_flat", "always_flat_strong_baseline"),
            ("oracle", "oracle_no_tradable_edge"),
            ("rule_trend", "rule_no_tradable_edge"),
            ("high_turnover_vs_flat", "high_frequency_loses_after_fees"),
        ):
            b = rep[block]
            tol = m if "high_turnover" not in block else 0.0
            assert rep["checks"][check_name] == (
                b["mean"] <= tol and b["bootstrap"]["ci_high"] <= tol)


def test_spec_binds_everything_and_hash_stable(cfg):
    """A4:spec 绑定 EvalConfig/fee/slippage/price tick/真实时长/
    timeframe/置信度/比较策略/聚合方式;哈希确定。"""
    spec = build_spec_payload(cfg, timeframe="15m", episode_bars=96)
    assert verify_spec_payload(spec) == []
    assert spec["margin_derivation"]["fee"] == 0.001
    assert spec["margin_derivation"]["slippage_bps"] == 0.0
    assert spec["margin_derivation"]["price_tick"] == 0.0
    assert spec["episode_duration_hours"] == 24.0
    assert spec["statistical_protocol"]["confidence_level"] == 0.95
    assert spec["statistical_protocol"]["bootstrap_iters"] == 2000
    assert spec["statistical_protocol"]["bootstrap_seed"] == 20260826
    assert set(spec["comparison_strategies"]) == {
        "oracle", "observable_rule", "always_long", "high_turnover"}
    assert spec["cluster_aggregation"] == "per-seed-mean-episode-v1"
    assert null_qualification_spec_hash(spec).startswith("nqs-")
    assert null_qualification_spec_hash(
        build_spec_payload(cfg, timeframe="15m", episode_bars=96)
    ) == null_qualification_spec_hash(spec)


def test_generator_param_margin_channel_abolished():
    """A4:生成器参数通道与旧 per-bar 默认容差从判定代码删除
    (检查 qualify_null_family 函数体;模块 docstring 的历史说明
    不构成通道)。"""
    body = inspect.getsource(qualify_null_family)
    assert "null_qual_max_net_drift_per_bar" not in body
    assert ("8e" + "-4") not in body
    assert ("max_net_drift" + "_per_bar") not in body


def test_rule_advantage_pseudo_null_is_invalid(schema, cfg):
    """D4:ObservableRule 优势超 margin 的伪 Null -> INVALID_NULL。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family

    params = dict(BASE_PARAMS)
    params["direction_weights"] = [0.0, 0.9, 0.1]
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=list(range(11, 75)), cfg=cfg, schema=schema,
        episodes_per_seed=2)
    assert not rep["checks"]["rule_no_tradable_edge"]
    assert rep["rule_trend"]["bootstrap"]["ci_low"] > rep["margin"]["value"]
    assert rep["verdict"] == "INVALID_NULL"


def test_hft_positive_return_pseudo_null_is_invalid(schema, cfg):
    """D4:HighTurnover 稳定正收益(费用合同失效的市场)-> INVALID_NULL
    (构造每 bar 漂移远超往返摩擦的单边市场,HFT 交替仓位吃漂移)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.null_qualification import qualify_null_family

    params = {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[1, 60.0, 96]],  # 每根 bar +60bps 单边上行
    }
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=list(range(11, 23)), cfg=cfg, schema=schema,
        episodes_per_seed=2)
    assert not rep["checks"]["high_frequency_loses_after_fees"], (
        f"单边大漂移市场 HFT 应有稳定正收益(实际中心 "
        f"{rep['high_turnover_vs_flat']['mean']:+.4f})")
    assert rep["high_turnover_vs_flat"]["bootstrap"]["ci_low"] > 0.0
    assert rep["verdict"] == "INVALID_NULL"


def test_small_fixed_drift_pseudo_null_not_qualified(schema, cfg):
    """D4:小幅固定正漂移伪 Null(每 bar +3bps,Episode 累计 0.29%
    = 1.44 x margin 的多头优势)不得 QUALIFIED(经济等价未证明)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.null_qualification import qualify_null_family

    params = {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[1, 3.0, 96]],  # 每根 bar +3bps
    }
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=qualification_seeds(MIN_QUALIFICATION_CLUSTERS), cfg=cfg,
        schema=schema, episodes_per_seed=8)
    drift_edge = 96 * 3.0e-4  # 0.0288 = 1.44 x margin
    assert drift_edge > rep["margin"]["value"]
    assert rep["verdict"] != "QUALIFIED", (
        f"多头优势 {drift_edge:.4f}(> margin {rep['margin']['value']:.4f})"
        f"的伪 Null 不得 QUALIFIED,实际 {rep['verdict']}")


def test_zero_drift_with_trend_predictability_is_invalid(schema, cfg):
    """D4:净漂移近零但方向可预测(趋势结构)的伪 Null -> INVALID_NULL
    (Oracle/Rule 有优势,AlwaysLong 无优势)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family

    params = dict(BASE_PARAMS)
    params["direction_weights"] = [0.5, 0.5, 0.0]  # 只涨跌两态,无平
    params["drift_bps_range"] = [24.0, 24.0]       # 对称幅度
    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=qualification_seeds(MIN_QUALIFICATION_CLUSTERS), cfg=cfg,
        schema=schema, episodes_per_seed=8)
    assert not rep["checks"]["oracle_no_tradable_edge"]
    assert rep["verdict"] == "INVALID_NULL"
