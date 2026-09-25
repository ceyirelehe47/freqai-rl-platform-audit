# -*- coding: utf-8 -*-
"""R20 设计数学 v3 纯数学测试(不触项目数据/生成器;仅 stdlib + pytest)。

被测对象:stage2_6_1/report/r20_design_calc_v3.py(design-only)。
覆盖验收矩阵 RouteC_EffectiveCollection_TOSTClosure_NextGoal_v1 的
C01–C07 数学底线:最低K公式、[0,1]裁剪、空接受区间、K-1 验证、
两张分开的功效/假等效表、异方差聚合SE反例、共享锚只加一次、
bootstrap 数值误差口径、互斥行动分类 + 方向分离、blocks 推导、
JSON/提案交叉一致与固定种子 MC 自洽。

全部确定性(固定常数 + NormalDist);Windows pytest 8.4.2 与
WSL pytest 9.1.1 均可独立运行本文件。
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from statistics import NormalDist

import pytest

N = NormalDist()

REPORT_DIR = Path(__file__).resolve().parents[2] / "report"
SCRIPT_PATH = REPORT_DIR / "r20_design_calc_v3.py"
JSON_PATH = REPORT_DIR / "r20_design_calc_v3.json"
MD_PATH = REPORT_DIR / "route_c_stage2_6_1_r20_research_design_v3.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("r20_design_calc_v3", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load_module()

# ---- 验收常量(与任务包 reference 对齐;独立于被测代码硬编码) ----
VALID_SE = 0.0019410552950364546
MARGIN = 0.003
# C01:rho=1.00/1.25/1.50 时零偏差90%最低K 与对应功效
C01 = {
    1.0: (5, 0.929875, 0.851892, 0.993601),
    1.25: (8, 0.936021, 0.896148, 0.936021),
    1.5: (11, 0.923686, 0.893354, 0.795725),
}
# C04(b):K=8、真偏差=+Delta、分析SE不修正时的假等效概率
C04_UNADJUSTED = {1.0: 0.04999999999936777,
                  1.25: 0.09410666745056218,
                  1.5: 0.13641379282587873}


# =====================================================================
# C01/C02:功效公式、最低K与K-1验证
# =====================================================================
class TestPowerAndMinimumK:
    def test_c01_minimum_k_and_powers(self):
        for rho, (k_exp, p_k, p_km1, p_k8) in C01.items():
            s = rho * VALID_SE
            k = M.minimum_k(s, MARGIN)
            assert k == k_exp
            assert M.zero_bias_power(MARGIN, k, s) == pytest.approx(p_k, rel=1e-6)
            assert M.zero_bias_power(MARGIN, k - 1, s) == pytest.approx(
                p_km1, rel=1e-6)
            assert M.zero_bias_power(MARGIN, 8, s) == pytest.approx(
                p_k8, rel=1e-6)

    def test_contract_formula_directly(self):
        for k in (1, 4, 5, 8, 11, 20):
            for rho in (1.0, 1.25, 1.5):
                s = rho * VALID_SE
                expected = max(0.0, 2.0 * N.cdf(
                    MARGIN * math.sqrt(k) / s - N.inv_cdf(0.95)) - 1.0)
                assert M.zero_bias_power(MARGIN, k, s) == pytest.approx(
                    expected, abs=1e-14)

    def test_same_power_function_general_agrees(self):
        # 最低K搜索所用函数与一般概率函数是同一功效函数
        for k in (1, 2, 5, 8, 11, 17):
            for rho in (1.0, 1.25, 1.5):
                s = rho * VALID_SE
                assert M.zero_bias_power(MARGIN, k, s) == pytest.approx(
                    M.equivalence_probability(0.0, MARGIN, k, s), abs=1e-12)

    def test_min_k_upward_search_proves_all_predecessors(self):
        for margin in (0.002, 0.003, 0.004):
            for rho in (1.0, 1.25, 1.5):
                s = rho * VALID_SE
                k = M.minimum_k(s, margin)
                assert M.zero_bias_power(margin, k, s) >= 0.90
                for j in range(1, k):  # 自 K=1 逐点验证,无稀疏表跳过
                    assert M.zero_bias_power(margin, j, s) < 0.90

    def test_power_clipped_to_unit_interval(self):
        for delta in (-0.03, -0.003, 0.0, 0.003, 0.03):
            for k in (1, 5, 15):
                p = M.equivalence_probability(delta, MARGIN, k, 0.002)
                assert 0.0 <= p <= 1.0

    def test_empty_acceptance_region_is_zero(self):
        assert M.equivalence_probability(0.0, 0.00001, 1, 0.002) == 0.0
        assert M.zero_bias_power(0.00001, 1, 0.002) == 0.0
        # lo == hi 的临界(margin 恰等于 z*s/sqrt(K))同样为空
        s_critical = MARGIN * math.sqrt(4) / M.critical_z()
        assert M.equivalence_probability(0.0, MARGIN, 4, s_critical) == 0.0

    def test_symmetry_in_delta(self):
        for d in (0.001, 0.002, 0.003, 0.01):
            assert M.equivalence_probability(d, MARGIN, 8, 0.002) == (
                pytest.approx(
                    M.equivalence_probability(-d, MARGIN, 8, 0.002), abs=1e-14))

    def test_required_ratio_is_z95_plus_z95(self):
        required = M.critical_z() + N.inv_cdf(0.95)
        assert required == pytest.approx(3.289707253902943, rel=1e-12)
        # v2 错比值 z95+z90 在连续边界只对应 80%,不是 90%
        old = M.critical_z() + N.inv_cdf(0.90)
        assert old == pytest.approx(2.9264051924960723, rel=1e-12)
        assert 2.0 * N.cdf(old - M.critical_z()) - 1.0 == pytest.approx(0.8)

    def test_boundary_alpha_controlled_with_correct_se(self):
        for k in (4, 8, 11, 15):
            p = M.equivalence_probability(MARGIN, MARGIN, k, VALID_SE)
            assert p <= 0.05 + 1e-12
            assert p == pytest.approx(0.05, abs=1e-5)
        # K=1 接受区间为空 → 0
        assert M.equivalence_probability(MARGIN, MARGIN, 1, VALID_SE) == 0.0

    def test_power_monotone_nondecreasing_in_k(self):
        prev = 0.0
        for k in range(1, 21):
            p = M.zero_bias_power(MARGIN, k, VALID_SE)
            assert p >= prev - 1e-15
            prev = p


# =====================================================================
# C04:两张分开的表(修正分析SE的功效 / 不修正的假等效)
# =====================================================================
class TestTwoSeparateTables:
    def test_c04_false_equivalence_unadjusted(self):
        for rho, expected in C04_UNADJUSTED.items():
            p = M.equivalence_probability(MARGIN, MARGIN, 8,
                                          rho * VALID_SE, VALID_SE)
            assert p == pytest.approx(expected, rel=1e-9)
        # 随 rho 单调恶化
        ps = [M.equivalence_probability(MARGIN, MARGIN, 8, r * VALID_SE,
                                        VALID_SE) for r in (1.0, 1.25, 1.5)]
        assert ps[0] < ps[1] < ps[2]

    def test_c04_tables_separate_in_json(self):
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        b = data["B_power_scenarios_corrected_analysis_se"]
        c = data["C_false_equivalence_unadjusted_analysis_se"]
        assert all(r["analysis_se_corrected"] is True for r in b["rows"])
        assert all(r["analysis_se_corrected"] is False for r in c["rows"])
        # 两表口径不同:B rho 同调双侧;C 真实SE放大而分析SE保持原值
        assert b["se_model"].startswith("s_analysis = s_true")
        assert c["definition"].startswith("P(z-CI built with ORIGINAL SE")

    def test_b_table_scenario_coverage(self):
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        rows = data["B_power_scenarios_corrected_analysis_se"]["rows"]
        deltas = sorted({r["delta_true"] for r in rows})
        assert deltas == sorted([0.0, 0.0005, 0.003, -0.003, 0.005])
        # 界外情形:正确SE下真偏差=+0.005 时几乎不可能误判等效
        for r in rows:
            if r["delta_true"] == 0.005:
                assert r["power_at_K11_recommended"] < 1e-4


# =====================================================================
# C03:聚合SE模型(异方差反例、共享锚、相关、bootstrap 误差口径)
# =====================================================================
class TestAggregateSeModel:
    def test_heteroscedastic_counterexample(self):
        ses = [0.001, 0.003]
        correct = M.aggregate_se_independent(ses)
        wrong = (sum(ses) / len(ses)) / math.sqrt(len(ses))
        assert correct == pytest.approx(0.0015811388300841897, rel=1e-9)
        assert wrong == pytest.approx(0.001414213562373095, rel=1e-9)
        assert correct > wrong  # mean/sqrt(K) 系统性低估

    def test_equal_se_special_case(self):
        s = 0.002
        for k in (2, 5, 8, 11):
            assert M.aggregate_se_independent([s] * k) == pytest.approx(
                s / math.sqrt(k), rel=1e-12)

    def test_anchor_enters_once(self):
        assert M.aggregate_se_with_anchor([0.001, 0.003], 0.001) == (
            pytest.approx(0.0018708286933869708, rel=1e-9))
        # 锚不随K缩小:K 增大聚合SE趋近锚本身但永不低于
        anchor = 0.001
        s = 0.002
        for k in (1, 11, 100, 1000):
            agg = M.aggregate_se_with_anchor([s] * k, anchor)
            assert agg >= anchor
            if k == 1000:
                assert agg < anchor * 1.01

    def test_anchor_breakeven_flips_power(self):
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        dd = data["D_aggregate_se_model"]
        rows = {r["shared_anchor_se"]: r for r in
                dd["anchor_sensitivity_at_recommended_design"]}
        assert rows[0.0]["power_at_zero"] > 0.90
        assert rows[0.0002]["power_at_zero"] > 0.90
        assert rows[0.0005]["power_at_zero"] < 0.90  # 锚淹没K的收敛收益
        breakeven = dd["breakeven_shared_anchor_se_for_90pct_at_K11_rho1p5"]
        assert 0.0002 < breakeven < 0.0003
        agg = M.aggregate_se_with_anchor(
            [1.5 * VALID_SE] * 11, breakeven)
        power = max(0.0, 2.0 * N.cdf(MARGIN / agg - M.critical_z()) - 1.0)
        assert power == pytest.approx(0.90, rel=1e-6)

    def test_correlation_formula(self):
        s, k = 0.002, 11
        assert M.aggregate_se_equal_correlated(s, k, 0.0) == pytest.approx(
            s / math.sqrt(k), rel=1e-12)
        # rho_c=0.1, K=11:放大因子 sqrt(1+10*0.1)=sqrt(2)
        assert M.aggregate_se_equal_correlated(s, k, 0.1) == pytest.approx(
            s * math.sqrt(2.0 / 11.0), rel=1e-12)
        with pytest.raises(ValueError):
            M.aggregate_se_equal_correlated(s, k, 1.5)  # 超出PSD上界1

    def test_bootstrap_error_scope_stated(self):
        # 1/sqrt(2*20000)=0.005 只是重抽样数值误差,不覆盖统计不确定性
        assert 1.0 / math.sqrt(2.0 * 20000) == pytest.approx(0.005, rel=1e-12)
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        e = data["E_bootstrap_numerical_error"]
        assert e["resampling_relative_error_bound"] == pytest.approx(
            0.005, rel=1e-12)
        assert e["of_what"].startswith("该 0.5%")
        assert len(e["not_covered"]) >= 3
        joined = "".join(e["not_covered"])
        assert "统计不确定性" in joined
        assert "跨坐标" in joined


# =====================================================================
# C05:互斥行动分类 + 方向分离
# =====================================================================
class TestClassification:
    def test_worked_example(self):
        half = M.critical_z() * VALID_SE / math.sqrt(8)
        lower, upper = 0.0015 - half, 0.0015 + half
        assert lower == pytest.approx(0.00037119176088350756, rel=1e-9)
        assert upper == pytest.approx(0.0026288082391164925, rel=1e-9)
        got = M.classify_result(lower, upper, MARGIN)
        assert got == {"magnitude": "within_equivalence_bounds",
                       "direction": "positive"}
        # 不触发"超重要界→必须校准"
        assert "校准" not in M.ACTION_MAPPING[got["magnitude"]]
        assert "校准" in M.ACTION_MAPPING["beyond_positive_margin"]
        assert "校准" in M.ACTION_MAPPING["beyond_negative_margin"]

    def test_all_cases(self):
        assert M.classify_result(0.0005, 0.0025, MARGIN) == {
            "magnitude": "within_equivalence_bounds", "direction": "positive"}
        assert M.classify_result(0.0031, 0.0040, MARGIN) == {
            "magnitude": "beyond_positive_margin", "direction": "positive"}
        assert M.classify_result(-0.0050, -0.0035, MARGIN) == {
            "magnitude": "beyond_negative_margin", "direction": "negative"}
        # 触界(上界恰等于+Delta / 下界恰等于-Delta)保守归不决
        assert M.classify_result(0.0010, 0.0030, MARGIN)["magnitude"] == (
            "inconclusive")
        assert M.classify_result(-0.0030, -0.0010, MARGIN)["magnitude"] == (
            "inconclusive")
        # 跨界
        assert M.classify_result(0.0020, 0.0040, MARGIN)["magnitude"] == (
            "inconclusive")
        assert M.classify_result(-0.0040, 0.0010, MARGIN)["magnitude"] == (
            "inconclusive")
        # 缺数据
        assert M.classify_result(None, None, MARGIN) == {
            "magnitude": "inconclusive", "direction": "not_resolved"}
        assert M.classify_result(None, 0.002, MARGIN)["direction"] == (
            "not_resolved")

    def test_direction_labels_separate(self):
        assert M.classify_result(-0.0025, -0.0010, MARGIN)["direction"] == (
            "negative")
        assert M.classify_result(-0.0010, 0.0025, MARGIN)["direction"] == (
            "not_resolved")
        # 区间触零保守归 not_resolved
        assert M.classify_result(0.0, 0.0025, MARGIN)["direction"] == (
            "not_resolved")

    def test_classes_mutually_exclusive(self):
        valid = set(M.MAGNITUDE_CLASSES)
        assert len(valid) == 4
        for lo in (-0.006, -0.003, -0.001, 0.0, 0.001, 0.003, 0.006):
            for hi in (-0.005, -0.002, 0.0, 0.002, 0.005):
                if lo > hi:
                    continue
                got = M.classify_result(lo, hi, MARGIN)
                assert got["magnitude"] in valid

    def test_invalid_interval_rejected(self):
        with pytest.raises(ValueError):
            M.classify_result(0.002, 0.001, MARGIN)


# =====================================================================
# C06:blocks/坐标尺度、设计汇总一致性
# =====================================================================
class TestBlocksAndDesign:
    def test_blocks_to_offset_rho(self):
        assert M.blocks_to_offset_rho(1.0) == 500
        assert M.blocks_to_offset_rho(1.25) == 782  # ceil(500*1.5625)
        assert M.blocks_to_offset_rho(1.5) == 1125  # 500*2.25

    def test_se_scaling_from_anchor(self):
        assert M.se_at_blocks(500) == pytest.approx(VALID_SE, rel=1e-15)
        assert M.se_at_blocks(2000) == pytest.approx(VALID_SE / 2, rel=1e-12)
        assert M.se_at_blocks(125) == pytest.approx(2 * VALID_SE, rel=1e-12)

    def test_k_times_b_invariance(self):
        r11 = MARGIN * math.sqrt(11) / M.se_at_blocks(500)
        r5 = MARGIN * math.sqrt(5) / M.se_at_blocks(1100)
        r10 = MARGIN * math.sqrt(10) / M.se_at_blocks(550)
        assert r11 == pytest.approx(r5, rel=1e-12)
        assert r11 == pytest.approx(r10, rel=1e-12)

    def test_design_summary_consistency(self):
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        kd = data["I_recommended_design"]["K_derivation"]
        assert kd["K"] == 11
        s = 1.5 * VALID_SE
        assert kd["power_at_K"] == pytest.approx(
            M.zero_bias_power(MARGIN, 11, s), rel=1e-12)
        assert kd["power_at_K_minus_one"] == pytest.approx(
            M.zero_bias_power(MARGIN, 10, s), rel=1e-12)
        assert kd["power_at_K_minus_one"] < 0.90 <= kd["power_at_K"]
        alt = data["I_recommended_design"]["alternative_single"]
        assert alt["K_at_rho1p25"] == M.minimum_k(1.25 * VALID_SE, 0.002)
        assert alt["K_at_rho1p5"] == M.minimum_k(1.5 * VALID_SE, 0.002)
        assert data["I_recommended_design"]["design_targets"][
            "margin_status"].startswith("待审开发界限")

    def test_scenario_deltas_pre_stated(self):
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        inputs = data["inputs"]
        assert inputs["delta_scenarios_pre_stated"] == [
            0.0, 0.0005, 0.003, -0.003, 0.005]
        assert inputs["near_zero_delta_pre_stated"] == 0.0005
        assert inputs["beyond_delta_pre_stated"] == 0.005
        assert inputs["valid_se"] == VALID_SE
        assert inputs["valid_se_status"].startswith("READ-ONLY")


# =====================================================================
# 交叉一致:JSON 原件 ↔ 公式重算;提案 ↔ JSON 逐字引用
# =====================================================================
class TestCrossConsistency:
    def test_json_matches_recomputation(self):
        data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        for r in data["A_min_k_and_zero_bias_power"]["rows"]:
            s = r["rho"] * VALID_SE
            assert r["min_K_power90_at_zero"] == M.minimum_k(s, r["margin"])
            assert r["power_at_min_K"] == pytest.approx(
                M.zero_bias_power(r["margin"], r["min_K_power90_at_zero"], s),
                rel=1e-12)
            assert r["power_at_K8"] == pytest.approx(
                M.zero_bias_power(r["margin"], 8, s), rel=1e-12)
        for r in data["C_false_equivalence_unadjusted_analysis_se"]["rows"]:
            assert r["false_equivalence_probability"] == pytest.approx(
                M.equivalence_probability(
                    MARGIN, MARGIN, r["K"], r["rho"] * VALID_SE, VALID_SE),
                rel=1e-12)
        we = data["F_action_classification"]["worked_example"]
        assert we["lower90"] == pytest.approx(0.00037119176088350756, rel=1e-9)
        assert we["upper90"] == pytest.approx(0.0026288082391164925, rel=1e-9)
        assert we["magnitude"] == "within_equivalence_bounds"
        ce = data["D_aggregate_se_model"]["counterexample"]
        assert ce["correct_mean_SE"] == pytest.approx(
            M.aggregate_se_independent(ce["coordinate_SEs"]), rel=1e-12)

    def test_md_quotes_json_values_verbatim(self):
        md = MD_PATH.read_text(encoding="utf-8")
        keys = [
            "0.9298751722715559", "0.9360214241815692",
            "0.9236864589708058", "0.8933540960149853",
            "0.795724852849675", "0.04999999999936777",
            "0.09410666745056223", "0.13641379282587868",
            "0.00037119176088350756", "0.0026288082391164925",
            "0.0015811388300841897", "0.001414213562373095",
        ]
        for value in keys:
            assert value in md, f"md missing verbatim JSON value {value}"
        assert "K=11" in md
        assert "待审开发界限" in md


# =====================================================================
# design-only MC 自洽(固定种子,确定性)
# =====================================================================
class TestMcCoherence:
    def test_mc_within_tolerance_and_deterministic(self):
        rows_a = M.mc_coherence(reps=20000)
        rows_b = M.mc_coherence(reps=20000)
        assert rows_a == rows_b  # 固定种子完全确定
        assert all(r["within_five_mc_se"] for r in rows_a)
        # 每行都记录了数值误差与次数(口径可审计)
        for r in rows_a:
            assert r["repetitions"] == 20000
            assert r["mc_standard_error"] > 0.0


# =====================================================================
# 非法输入
# =====================================================================
class TestInvalidInputs:
    @pytest.mark.parametrize("bad", [
        {"k": True}, {"k": 0}, {"k": 1.5},
        {"margin": -1.0}, {"delta": math.nan},
        {"true_single_se": 0.0}, {"analysis_single_se": -1.0},
        {"alpha": 0.5},
    ])
    def test_probability_inputs(self, bad):
        kwargs = dict(delta=0.0, margin=MARGIN, k=8, true_single_se=0.002)
        kwargs.update(bad)
        with pytest.raises(ValueError):
            M.equivalence_probability(**kwargs)

    @pytest.mark.parametrize("target", [0.0, 1.0, math.nan])
    def test_invalid_targets(self, target):
        with pytest.raises(ValueError):
            M.minimum_k(0.002, MARGIN, target)

    def test_bounded_search(self):
        with pytest.raises(ValueError):
            M.minimum_k(0.002, MARGIN, max_k=1)
