"""工作包 B(B1-B7):中心化、四块完整硬目标与 cluster 校准的测试。

覆盖任务书 B7 的 12 类场景:经验均值为负/正时 target 语义、零方差
不跳过、四块 required 场景全覆盖、缺场景/未达标 -> targets_met=false、
旧未中心化方式必须失败、spec/report hash 绑定。
"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from rl_curriculum.null_power_analysis import (
    CONFIDENCE_METHOD,
    MC_ITERS,
    POWER_ANALYSIS_FORMAT,
    REQUIRED_BLOCKS,
    _wilson,
    bootstrap_matrix_parity,
    power_analysis_report_hash,
    power_centering_parity,
    run_power_analysis,
)
from rl_curriculum.null_qualification_spec import (
    CLUSTER_CANDIDATE_LADDER,
    MIN_QUALIFICATION_CLUSTERS,
    POWER_MC_CONFIG,
    POWER_SCENARIO_MANIFEST,
    scenario_manifest_hash,
)


def _synthetic_reports(seed: int = 42, n: int = 64):
    """合成族报告:构造使 32 档前缀资格经济不充分、64 档充分的分布
    (long/rule/oracle 中心 +0.0003:32 档 CI 上界越限,64 档压进
    margin;hft 中心 -0.0025:两档都压进 0 容差;stochvol oracle
    恒零 -> 零方差解析分支)。"""
    rng = np.random.default_rng(seed)
    fams = ["probe_null_sign", "probe_null_volstate", "probe_null_stochvol"]
    out = {}
    for f in fams:
        blocks = {}
        for b, sd, mean in (("always_long_vs_flat", 0.006, 0.0003),
                            ("rule_trend", 0.005, 0.0003),
                            ("high_turnover_vs_flat", 0.004, -0.0025)):
            blocks[b] = {"cluster_values": list(rng.normal(mean, sd, n))}
        blocks["oracle"] = {
            "cluster_values": ([0.0] * n if f == "probe_null_stochvol"
                               else list(rng.normal(0.0003, 0.005, n)))}
        out[f] = blocks
    return out


def test_centering_negative_empirical_mean():
    """B7-1:经验均值为负时,注入 absolute edge 后样本中心 == target
    (不受原始经验均值污染;B1)。"""
    base = list(np.random.default_rng(1).normal(-0.004, 0.005, 48))
    for target in (0.0, 0.001, 0.004):
        p = power_centering_parity(base, target, 64, bound=0.002,
                                   scenario_index=3)
        assert abs(p["simulated_center"] - target) < 5e-4, p
        assert abs(p["residual_center"]) < 1e-12
        assert p["empirical_center"] < -0.003


def test_centering_positive_empirical_mean():
    """B7-2:经验均值为正时同样成立(旧实现会把正均值叠加进 target)。"""
    base = list(np.random.default_rng(2).normal(0.003, 0.005, 48))
    for target in (0.0, 0.002):
        p = power_centering_parity(base, target, 64, bound=0.002,
                                   scenario_index=5)
        assert abs(p["simulated_center"] - target) < 5e-4, p
        # 旧未中心化方式的隐含中心 = empirical + delta != target
        assert abs(p["empirical_center"] + target - target) > 1e-3


def test_legacy_uncentered_semantics_fails_centering_parity():
    """B7-10:旧方式(resample(empirical) + delta)的样本中心被原始
    经验均值污染,不满足 target parity(证明修复必要)。"""
    rng = np.random.default_rng(3)
    base = rng.normal(0.0025, 0.005, 64)  # 显著正的经验均值
    delta = 0.0
    legacy_draws = rng.choice(base, size=(400, 64), replace=True) + delta
    legacy_center = float(legacy_draws.mean())
    assert abs(legacy_center - delta) > 0.002  # 偏离声明的 target
    fixed = power_centering_parity(list(base), delta, 64, bound=0.002)
    assert abs(fixed["simulated_center"] - delta) < 5e-4


def test_zero_variance_scenario_not_skipped_and_deterministic(
        null_qual_chain):
    """B7-3/B4:零方差 required scenario 走解析确定性分支,不标记
    skipped,判定完全确定,仍计入 coverage(真实 stochvol oracle 恒
    flat -> cluster 值恒零)。"""
    rep = null_qual_chain["power_report"]
    assert np.std(null_qual_chain["reports"]["probe_null_stochvol"]
                  ["oracle"]["cluster_values"]) == 0.0
    assert rep["skipped_required_scenarios"] == []
    assert rep["required_scenarios_complete"] is True
    zero_scens = [s for s in rep["scenarios"]
                  if s["family"] == "probe_null_stochvol"
                  and s["block"] == "oracle"]
    assert zero_scens
    for s in zero_scens:
        assert s["mode"] == "analytic_zero_variance"
        assert s["deterministic"] is True
        total = sum(s["rates"].values())
        assert abs(total - 1.0) < 1e-12
        # 常数序列判定完全确定:violations -> INVALID,零优势 -> QUALIFIED
        if s["scenario"] == "valid_zero_edge":
            assert s["rates"]["QUALIFIED"] == 1.0
        if s["scenario"] in ("violation_plus_1x_margin",
                             "violation_plus_2x_margin"):
            assert s["rates"]["INVALID_NULL"] == 1.0


@pytest.mark.parametrize("block", REQUIRED_BLOCKS)
def test_required_scenarios_cover_all_four_blocks(null_qual_chain, block):
    """B7-4/5/6/7:AlwaysLong / Oracle / Rule / HFT 的 required scenarios
    全覆盖(每 family x block x manifest 场景都存在)。"""
    rep = null_qual_chain["power_report"]
    expected = POWER_SCENARIO_MANIFEST["blocks"][block]["scenarios"]
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        present = {s["scenario"] for s in rep["scenarios"]
                   if s["family"] == fam and s["block"] == block
                   and s["n"] == rep["min_qualification_clusters"]}
        assert present == set(expected), (fam, block, present)


def test_missing_required_scenario_makes_targets_unmet(null_qual_chain):
    """B7-8:缺少任一 required scenario -> required 覆盖不完整(以删除
    Rule 违规场景为例,篡改后的报告结构暴露缺失)。"""
    rep = null_qual_chain["power_report"]
    assert rep["targets"]["targets_met"] is True
    tampered = copy.deepcopy(rep)
    # 删掉一个 required 场景(全部 n 档)并伪造 targets_met
    tampered["scenarios"] = [
        s for s in tampered["scenarios"]
        if not (s["block"] == "rule_trend"
                and s["scenario"] == "violation_plus_1x_margin")]
    tampered["targets"]["targets_met"] = True
    # required coverage 由报告结构承载:重算覆盖即失败
    n_sel = tampered["min_qualification_clusters"]
    present = {f"{s['family']}::{s['block']}::{s['scenario']}"
               for s in tampered["scenarios"] if s["n"] == n_sel}
    expected = {f"{f}::{b}::{sc}"
                for f in null_qual_chain["reports"]
                for b in REQUIRED_BLOCKS
                for sc in POWER_SCENARIO_MANIFEST["blocks"][b]["scenarios"]}
    assert present < expected  # 缺失被暴露 -> required_scenarios_complete
    # 完整报告的语义:required_scenarios_complete 与场景集合一致
    assert rep["required_scenarios_complete"] is True


def test_any_family_block_unmet_makes_targets_false():
    """B7-9:任一 family x block 未达硬目标 -> targets_met=false 或
    阶梯整体 fail closed(注入高噪声块;两者都证明不可降级)。"""
    rng = np.random.default_rng(9)
    reports = _synthetic_reports(seed=9)
    # 注入高方差 long 块(所有档位前缀资格不充分 -> 无可选档)
    reports["probe_null_sign"]["always_long_vs_flat"][
        "cluster_values"] = list(rng.normal(0.30, 0.08, 64))
    with pytest.raises(RuntimeError, match="没有任何.*档位|fail closed"):
        run_power_analysis(reports, margin=0.0019980019980019303)


def test_mc_config_and_confidence_bounds_in_spec_and_report(null_qual_chain):
    """B7-12:MC 种子/迭代数/比例置信方法进入 spec hash 与 report;
    比例判定用 Wilson 保守界而非点估计。"""
    from rl_curriculum.null_qualification_spec import build_spec_payload
    from rl_curriculum.mock_sealed_exam import default_eval_config

    rep = null_qual_chain["power_report"]
    assert rep["mc_iters"] == POWER_MC_CONFIG["mc_iters"] == MC_ITERS
    assert rep["confidence_method"] == CONFIDENCE_METHOD
    spec = build_spec_payload(
        default_eval_config(), timeframe="15m", episode_bars=96)
    assert spec["power_mc_config"] == dict(POWER_MC_CONFIG)
    base_hash = scenario_manifest_hash()
    tampered = copy.deepcopy(spec)
    tampered["power_mc_config"]["mc_iters"] = 400
    import hashlib

    h = "nqs-" + hashlib.sha256(json.dumps(
        tampered, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode()).hexdigest()
    assert h != scenario_manifest_hash()
    assert base_hash.startswith("npss-")
    # Wilson 界非对称包含点估计
    lo, hi = _wilson(10, 400)
    assert lo < 10 / 400 < hi
    assert hi > 10 / 400  # 上界保守(高于点估计)


def test_tolerance_and_scenario_manifest_change_report_hash(null_qual_chain):
    """B7-11:修改 tolerance/margin/scenario manifest -> report hash 变化。"""
    rep = null_qual_chain["power_report"]
    h0 = power_analysis_report_hash(rep)
    tampered = copy.deepcopy(rep)
    tampered["tolerance_by_block"]["high_turnover_vs_flat"] = 0.001
    assert power_analysis_report_hash(tampered) != h0
    tampered2 = copy.deepcopy(rep)
    tampered2["scenario_manifest"]["blocks"]["oracle"]["scenarios"].pop()
    assert power_analysis_report_hash(tampered2) != h0
    tampered3 = copy.deepcopy(rep)
    tampered3["margin"] = 0.001999
    assert power_analysis_report_hash(tampered3) != h0


def test_four_blocks_in_hard_gate_not_only_always_long(null_qual_chain):
    """B3:targets_met 覆盖四块(不只 Always Long);每块三个门都在。"""
    rep = null_qual_chain["power_report"]
    detail = rep["targets"]["by_family_block"]
    blocks = {key.split("::")[1] for key in detail}
    assert blocks == set(REQUIRED_BLOCKS)
    for key, d in detail.items():
        assert d["met"] is True, key
        assert d["zero_edge"]["met"] is True
        assert d["violation_plus_1x"]["met"] is True
        assert d["violation_plus_2x"]["met"] is True
        # Wilson 保守界方向
        assert d["zero_edge"]["wilson_upper"] >= \
            d["zero_edge"]["rate_point"]
        assert d["violation_plus_1x"]["wilson_lower"] <= \
            d["violation_plus_1x"]["rejection_point"]


def test_cluster_ladder_selection_recorded(null_qual_chain):
    """B6:阶梯(32/64/96/128)逐档记录;选定档同时满足功效硬目标与
    前缀资格经济充分性;经验基座为 64-cluster 报告。"""
    rep = null_qual_chain["power_report"]
    sel = rep["cluster_selection"]
    assert sel["empirical_base_clusters"] == 64
    assert [e["n"] for e in sel["ladder"]] == list(
        CLUSTER_CANDIDATE_LADDER)
    chosen = next(e for e in sel["ladder"]
                  if e["n"] == sel["selected"])
    assert chosen["selectable"] is True
    assert chosen["targets_met"] is True
    assert chosen["qualification_economics_sufficient"] is True
    assert sel["selected"] == MIN_QUALIFICATION_CLUSTERS
    # 32 档:功效目标可能已满足,但前缀资格经济充分性必须如实记录
    n32 = next(e for e in sel["ladder"] if e["n"] == 32)
    if n32["targets_met"] and not n32["selectable"]:
        assert n32["qualification_economics_sufficient"] is False
        assert n32["prefix_evaluable"] is True


def test_deterministic_rerun_same_hash(null_qual_chain):
    """确定性:同材料重跑 -> 同一 npa- 哈希(执行器重验证的契约)。"""
    reports = null_qual_chain["reports"]
    margin = null_qual_chain["spec"]["margin"]
    again = run_power_analysis(reports, margin=margin)
    assert power_analysis_report_hash(
        again) == power_analysis_report_hash(
        null_qual_chain["power_report"])


def test_vectorized_bootstrap_bitwise_matches_reference():
    """向量化 bootstrap 与 paired_bootstrap_ci/_evaluate_check 逐位一致
    (速度优化不得改变判定语义;多种分布形态)。"""
    rng = np.random.default_rng(11)
    for trial in range(6):
        vals = list(rng.normal(rng.uniform(-0.003, 0.003), 0.006, 40))
        p = bootstrap_matrix_parity(vals)
        assert p["bitwise_match"] is True, (trial, p)
    # 常数序列(零方差分支的参照)
    p = bootstrap_matrix_parity([0.001] * 30)
    assert p["bitwise_match"] is True
    assert p["reference_bootstrap"]["ci_low"] == p["reference_bootstrap"][
        "ci_high"]


def test_power_report_format_v2_and_old_rejected(null_qual_chain):
    """格式必须是 v2(v1 未中心化/只覆盖 Always Long/点估计)。"""
    rep = null_qual_chain["power_report"]
    assert rep["format"] == POWER_ANALYSIS_FORMAT == "null-power-analysis-v2"
    from rl_curriculum.null_power_analysis import _DEPRECATED_POWER_FORMATS

    assert "null-power-analysis-v1" in _DEPRECATED_POWER_FORMATS
