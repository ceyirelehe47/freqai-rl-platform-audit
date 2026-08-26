"""工作包 A2:独立统计单位必须是 seed / Episode cluster。

2.6.0c 的问题:bootstrap 把多个 Episode 内的数百根 bar 当作独立
样本(Null 刻意保留波动聚集,bar 不是独立统计单位)。

2.6.0d 语义:每个 seed 先聚合其全部关联 Episode(派生 seed =
seed + 1000*k)——cluster 值为算术平均(per-seed-mean-episode-v1)
——bootstrap 的抽样单位是 cluster;报告记录原始 Episode 数、
cluster 数、distinct seed 数、cluster 聚合规则与 bootstrap 实际 n。
"""

from __future__ import annotations

import copy

from rl_curriculum.null_qualification import (
    CLUSTER_AGGREGATION,
    BOOTSTRAP_UNIT,
    NULL_REPORT_REQUIRED_KEYS,
    MIN_QUALIFICATION_CLUSTERS,
    build_null_qualification_bindings,
    qualification_report_hash,
    qualify_null_family,
    verify_null_qualification_bindings,
)

ALL_BLOCKS = (
    ("oracle", "excess_bootstrap", "cluster_values"),
    ("rule_trend", "excess_bootstrap", "cluster_values"),
    ("always_long_vs_flat", "excess_bootstrap", "cluster_values"),
    ("episode_net_drift", "bootstrap", "cluster_values"),
)


def test_bootstrap_n_equals_distinct_clusters(null_qual_reports):
    """任务书 A2 断言:bootstrap n == distinct independent clusters
    (全部四个统计块的 n/cluster 数都必须等于独立 cluster 数)。"""
    for fam, rep in null_qual_reports.items():
        n = rep["n_clusters"]
        assert n == rep["distinct_seeds"] == MIN_QUALIFICATION_CLUSTERS
        assert n == len(set(rep["seeds"]))
        for block, boot_key, cv_key in ALL_BLOCKS:
            boot = rep[block][boot_key]
            cv = rep[block][cv_key]
            assert boot["n"] == n, (
                f"{fam}.{block} bootstrap n={boot['n']} != cluster 数"
                f"{n}(统计单位被退化)")
            assert isinstance(cv, list) and len(cv) == n


def test_nine_episodes_one_seed_is_one_cluster(schema, cfg):
    """同一 seed 的 9 个关联 Episode 只构成 1 个 cluster(bootstrap
    n == 1,不得把 Episode 数冒充独立样本数)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=dict(BASE_PARAMS),
        timeframe="15m", seeds=[777], cfg=cfg, schema=schema,
        episodes_per_seed=9)
    assert rep["n_episodes_tested"] == 9
    assert rep["n_clusters"] == 1
    assert rep["distinct_seeds"] == 1
    for block, boot_key, cv_key in ALL_BLOCKS:
        assert rep[block][boot_key]["n"] == 1
        assert len(rep[block][cv_key]) == 1


def test_cluster_counts_recorded_in_report(null_qual_reports):
    """报告必须记录:原始 Episode 数 / cluster 数 / distinct seed 数 /
    cluster 聚合规则 / bootstrap 实际 n。"""
    for fam, rep in null_qual_reports.items():
        assert rep["n_episodes_tested"] == (
            rep["n_clusters"] * rep["episodes_per_seed"])
        assert rep["cluster_aggregation"] == CLUSTER_AGGREGATION
        assert rep["bootstrap_unit"] == BOOTSTRAP_UNIT
        assert rep["episodes_per_seed"] >= 1


def test_cluster_values_match_manual_aggregation(schema, cfg):
    """聚合规则 per-seed-mean-episode-v1 的实现正确性:2 seed x 2
    episode,用独立手工重算的 seed 内均值核对报告 cluster_values。"""
    import numpy as np
    from rl_curriculum.evaluator import run_policy_episode
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.policies import AlwaysFlatPolicy, AlwaysLongPolicy

    gen = ProbeSegmentedDriftGenerator()
    seeds = [501, 502]
    rep = qualify_null_family(
        gen, params=dict(BASE_PARAMS), timeframe="15m", seeds=seeds,
        cfg=cfg, schema=schema, episodes_per_seed=2)
    flat, long_ = AlwaysFlatPolicy(), AlwaysLongPolicy()
    manual = []
    for seed in seeds:
        vals = []
        for k in range(2):
            ep = gen.generate(
                dict(BASE_PARAMS), int(seed) + 1000 * k,
                split="null_control", timeframe="15m")
            vals.append(
                run_policy_episode(long_, ep, cfg, schema).net_return
                - run_policy_episode(flat, ep, cfg, schema).net_return)
        manual.append(float(np.mean(vals)))
    assert rep["always_long_vs_flat"]["cluster_values"] == manual


def test_bar_level_bootstrap_abolished(null_qual_reports):
    """v2 的 bar 级统计键(net_drift_per_bar_bootstrap /
    max_net_drift_per_bar)不再存在于 v3 报告 schema。"""
    v2_only_keys = {"net_drift_per_bar_bootstrap", "max_net_drift_per_bar",
                    "n_episodes_tested_bar_pool"}
    assert not (v2_only_keys & set(NULL_REPORT_REQUIRED_KEYS))
    for rep in null_qual_reports.values():
        assert not (v2_only_keys & set(rep))
        # episode 级 drift 聚合后的 bootstrap n 也不得等于 bar 总数
        n_bars = rep["n_episodes_tested"] * 96
        assert rep["episode_net_drift"]["bootstrap"]["n"] != n_bars


def test_cluster_unit_tamper_rejected_by_verify(null_qual_reports,
                                                schema, cfg):
    """统计单位对账:伪造 bootstrap 单位/cluster 数/cluster_values
    长度/聚合规则的报告即使重算 hash 也被 verify 拒绝。"""
    from tests.route_c_stage2_6_0b.test_invalid_null_rejected import (
        _verify_kwargs,
    )

    base = build_null_qualification_bindings(null_qual_reports)

    def _verify_with(mutation):
        bindings = copy.deepcopy(base)
        payload = bindings["probe_null_sign"]["report_payload"]
        mutation(payload)
        bindings["probe_null_sign"]["report_hash"] = \
            qualification_report_hash(payload)
        return verify_null_qualification_bindings(
            bindings, required_families=sorted(null_qual_reports),
            **_verify_kwargs())

    r1 = _verify_with(
        lambda p: p.__setitem__("bootstrap_unit", "bar"))
    assert not r1["pass"]
    assert any("bootstrap 单位" in p for p in r1["problems"])

    r2 = _verify_with(lambda p: p.__setitem__("n_clusters", 63))
    assert not r2["pass"]
    assert any("n_clusters" in p or "cluster 数不足" in p
               for p in r2["problems"])

    def _truncate(p):
        p["always_long_vs_flat"]["cluster_values"] = \
            p["always_long_vs_flat"]["cluster_values"][:32]

    r3 = _verify_with(_truncate)
    assert not r3["pass"]
    assert any("cluster 数" in p for p in r3["problems"])

    r4 = _verify_with(
        lambda p: p.__setitem__("cluster_aggregation",
                                "mean-of-all-episodes"))
    assert not r4["pass"]
    assert any("聚合规则" in p for p in r4["problems"])


def test_report_deterministic_across_runs(null_qual_reports, schema, cfg):
    """资格报告完全确定(seeded 生成器 + seeded bootstrap):两次独立
    生成同一配置 -> 报告 hash 相同(缓存与对账的前提)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    again = qualify_null_family(
        R["probe_null_stochvol"], params=dict(BASE_PARAMS), timeframe="15m",
        seeds=list(range(11, 75)), cfg=cfg, schema=schema,
        episodes_per_seed=8)
    assert qualification_report_hash(again) == qualification_report_hash(
        null_qual_reports["probe_null_stochvol"])
