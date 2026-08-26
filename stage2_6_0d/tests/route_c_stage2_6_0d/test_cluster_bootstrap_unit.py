"""工作包 A2 + D2:独立统计单位必须是 seed / Episode cluster。

- bootstrap n == distinct independent clusters(四差值块 + 漂移诊断,
  family 与 pack 两级);
- 3 seed x 96 bar = 288 根 bar 时 bootstrap n == 3(不是 288);
- antithetic pack:原始 Episode 数 6 / 独立 cluster 3 / n == 3;
- 报告记录原始 Episode 数 / cluster 数 / distinct seed 数 / 聚合
  规则 / bootstrap 实际 n(A2 五要素)。
"""

from __future__ import annotations

from rl_curriculum.null_qualification import (
    BOOTSTRAP_UNIT,
    CLUSTER_AGGREGATION,
    MIN_QUALIFICATION_CLUSTERS,
    NULL_REPORT_REQUIRED_KEYS,
    build_null_qualification_bindings,
    qualification_report_hash,
    qualify_null_family,
    verify_null_qualification_bindings,
)

ALL_BLOCKS = ("oracle", "rule_trend", "always_long_vs_flat",
              "high_turnover_vs_flat", "episode_net_drift")
BOOT_KEY = {"episode_net_drift": "bootstrap"}


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


def test_bootstrap_n_equals_distinct_clusters(null_qual_reports):
    """任务书 A2 断言:bootstrap n == distinct independent clusters。"""
    for fam, rep in null_qual_reports.items():
        n = rep["n_clusters"]
        assert n == rep["distinct_seeds"] == MIN_QUALIFICATION_CLUSTERS
        assert n == len(set(rep["seeds"]))
        for block in ALL_BLOCKS:
            boot = rep[block][BOOT_KEY.get(block, "bootstrap")]
            cv = rep[block]["cluster_values"]
            assert boot["n"] == n, (
                f"{fam}.{block} bootstrap n={boot['n']} != cluster 数"
                f"{n}(统计单位被退化)")
            assert isinstance(cv, list) and len(cv) == n


def test_288_bars_bootstrap_n_is_three(small_sample_reports):
    """D2:3 seed x 96 bar = 288 根 bar 的样本,bootstrap n == 3。"""
    for fam, rep in small_sample_reports.items():
        assert rep["n_episodes_tested"] == 3
        assert rep["episodes_per_seed"] == 1
        assert rep["n_clusters"] == 3
        # 288 根 bar 不是样本数(2.6.0c 的 bar 级 bootstrap 已废除)
        total_bars = rep["n_episodes_tested"] * 96
        assert total_bars == 288
        for block in ("always_long_vs_flat", "oracle", "rule_trend",
                      "high_turnover_vs_flat"):
            assert rep[block]["bootstrap"]["n"] == 3
            assert rep[block]["bootstrap"]["n"] != total_bars


def test_antithetic_pack_six_episodes_three_clusters(schema, cfg):
    """D2(pack):每 seed 两个 antithetic Episode -> 原始 Episode 数 6 /
    独立 cluster 3 / bootstrap n == 3。"""
    from null_qual_cache import null_episode_specs
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    specs = null_episode_specs(families=("probe_null_stochvol",))
    # 只取前 3 个 pair(6 episodes)
    pair_specs = []
    seen_seeds = set()
    for s in specs:
        if len(seen_seeds) < 3 or s.seed in seen_seeds:
            pair_specs.append(s)
            seen_seeds.add(s.seed)
        if len(pair_specs) == 6:
            break
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    eps = [R[s.family].generate(dict(s.params), s.seed, split=s.split,
                                timeframe=s.timeframe) for s in pair_specs]
    spec = build_spec_for_pack(cfg, timeframe="15m", episode_bars=96)
    rep = validate_null_pack(
        {"probe_null_stochvol": eps}, cfg=cfg, schema=schema, spec=spec)
    fam_block = rep["per_family"]["probe_null_stochvol"]
    assert fam_block["n_episodes"] == 6
    assert fam_block["n_clusters"] == 3
    assert fam_block["blocks"]["long"]["bootstrap_n"] == 3


def test_nine_episodes_one_seed_is_one_cluster(schema, cfg):
    """同 seed 的 9 个关联 Episode 只构成 1 个 cluster。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    rep = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=dict(BASE_PARAMS),
        timeframe="15m", seeds=[777], cfg=cfg, schema=schema,
        episodes_per_seed=9)
    assert rep["n_episodes_tested"] == 9
    assert rep["n_clusters"] == 1
    assert rep["distinct_seeds"] == 1
    for block in ALL_BLOCKS:
        assert rep[block][BOOT_KEY.get(block, "bootstrap")]["n"] == 1
        assert len(rep[block]["cluster_values"]) == 1


def test_cluster_counts_recorded_in_report(null_qual_reports):
    """A2:报告必须记录五要素。"""
    for fam, rep in null_qual_reports.items():
        assert rep["n_episodes_tested"] == (
            rep["n_clusters"] * rep["episodes_per_seed"])
        assert rep["cluster_aggregation"] == CLUSTER_AGGREGATION
        assert rep["bootstrap_unit"] == BOOTSTRAP_UNIT
        assert rep["episode_duration_hours"] == 24.0  # 96 x 15m
        assert rep["level"] == "family"


def test_no_bar_level_bootstrap_remains(null_qual_reports):
    """v2 的 bar 级统计键不存在于 v3 报告 schema。"""
    v2_only_keys = {"net_drift_per_bar_bootstrap", "max_net_drift_per_bar"}
    assert not (v2_only_keys & set(NULL_REPORT_REQUIRED_KEYS))
    for rep in null_qual_reports.values():
        assert not (v2_only_keys & set(rep))


def test_cluster_unit_tamper_rejected_by_verify(null_qual_reports):
    """统计单位对账:伪造 bootstrap 单位/cluster 数/cluster_values
    长度/聚合规则的报告即使重算 hash 也被 verify 拒绝。"""
    import copy

    base = build_null_qualification_bindings(null_qual_reports)

    def _verify_with(mutation):
        bindings = copy.deepcopy(base)
        payload = bindings["probe_null_sign"]["report_payload"]
        mutation(payload)
        bindings["probe_null_sign"]["report_hash"] = \
            qualification_report_hash(payload)
        return verify_null_qualification_bindings(
            bindings, required_families=sorted(null_qual_reports),
            **_null_verify_kwargs())

    r1 = _verify_with(
        lambda p: p.__setitem__("bootstrap_unit", "bar"))
    assert not r1["pass"]
    assert any("bootstrap 单位" in p for p in r1["problems"])

    r2 = _verify_with(lambda p: p.__setitem__("n_clusters", 63))
    assert not r2["pass"]

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

    r5 = _verify_with(
        lambda p: p.__setitem__("seeds_namespace_conform", False))
    assert not r5["pass"]
    assert any("namespace" in p for p in r5["problems"])


def test_report_deterministic_across_runs(null_qual_reports, schema, cfg):
    """资格报告完全确定:两次独立生成同一配置 -> 报告 hash 相同。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification_spec import qualification_seeds

    again = qualify_null_family(
        R["probe_null_stochvol"], params=dict(BASE_PARAMS), timeframe="15m",
        seeds=qualification_seeds(MIN_QUALIFICATION_CLUSTERS), cfg=cfg,
        schema=schema,
        power_analysis_ref=null_qual_reports[
            "probe_null_stochvol"]["power_analysis_ref"])
    assert qualification_report_hash(again) == qualification_report_hash(
        null_qual_reports["probe_null_stochvol"])
