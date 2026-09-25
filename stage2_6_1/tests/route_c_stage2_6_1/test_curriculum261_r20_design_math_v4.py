# -*- coding: utf-8 -*-
"""R20 设计数学 v4 测试(C01-C06;经项目实际入口,design-only)。

针对 stage2_6_1/report/r20_design_calc_v4.py(实际主分析入口)与
r20_design_calc_v4.json(机读原件):方向贯通、固定 r_analysis 进入
实际 CI、r_true 仅情景变量、最低K 同一实现复算、互斥分类与不足
坐标不决、真实边界声明。纯 stdlib + pytest;不触项目数据/生成器。
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
SCRIPT_PATH = REPORT_DIR / "r20_design_calc_v4.py"
JSON_PATH = REPORT_DIR / "r20_design_calc_v4.json"
MD_PATH = REPORT_DIR / "route_c_stage2_6_1_r20_research_design_v4.md"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "r20_design_calc_v4", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _load_module()

# ---- 验收常量(与任务包 reference 对齐;独立于被测代码硬编码) ----
VALID_SE = 0.0019410552950364546
MARGIN = 0.003
S_RAW_K11 = 0.0005852501919062291
S_ANALYSIS_K11 = 0.0008778752878593437
CI_HALF_K11 = 0.0014439763512465087
#: C02/C03:固定 r_analysis=1.5、K=11、只变 r_true 的锚点数值
POWER_ZERO = {1.0: 0.9921564766, 1.25: 0.9665787471,
              1.5: 0.9236864590, 2.0: 0.8162728170}
FALSE_EQUIV_AT_BOUNDARY = {1.0: 0.0068071842, 1.25: 0.0242008592,
                           1.5: 0.0499998948, 2.0: 0.1086188651}
UNADJUSTED_CONTROL = 0.13641489925413858
MATCHED_MIN_K = {1.0: 5, 1.25: 8, 1.5: 11}
FIXED_ANALYSIS_MIN_K = {1.0: 8, 1.25: 9, 1.5: 11}


# =====================================================================
# C01:delta=analytic−recall 的方向贯通(实际分类与输出入口)
# =====================================================================
class TestDirectionThroughRealEntry:
    def test_positive_margin_means_recall_low(self):
        """delta>0 重要超界:实测 recall 低;行动文字必含
        '偏低'(且'高估'),不得出现反向表述。"""
        ses = [VALID_SE] * 11
        out = M.classify_primary(0.0045, ses)
        assert out["magnitude"] == "beyond_positive_margin"
        assert out["direction"] == "positive"
        assert "偏低" in out["action"]
        assert "高估" in out["action"]
        assert "偏高" not in out["action"].split("，")[0]

    def test_negative_margin_means_recall_high(self):
        ses = [VALID_SE] * 11
        out = M.classify_primary(-0.0045, ses)
        assert out["magnitude"] == "beyond_negative_margin"
        assert out["direction"] == "negative"
        assert "偏高" in out["action"]
        assert "低估" in out["action"]

    def test_action_mapping_json_and_cases_consistent(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        mapping = doc["F_action_classification"]["action_mapping"]
        assert mapping == M.ACTION_MAPPING
        assert "偏低" in mapping["beyond_positive_margin"]
        assert "偏高" in mapping["beyond_negative_margin"]
        cases = doc["F_action_classification"]["cases"]
        assert cases["beyond_positive"]["magnitude"] == \
            "beyond_positive_margin"
        assert "偏低" in cases["beyond_positive"]["action"]
        assert "偏高" in cases["beyond_negative"]["action"]

    def test_direction_convention_declared(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        convention = doc["inputs"]["direction_convention"]
        assert "delta = p_analytic - recall(validation)" in convention
        assert "低于" in convention and "高估" in convention


# =====================================================================
# C02:r_analysis=1.5 实际进入 CI(不只是规划表)
# =====================================================================
class TestFixedAnalysisFactorInActualCi:
    def test_k11_scale_numbers(self):
        ses = [VALID_SE] * 11
        out = M.classify_primary(0.0, ses)
        assert math.isclose(out["s_raw"], S_RAW_K11, rel_tol=1e-12)
        assert math.isclose(out["s_analysis"], S_ANALYSIS_K11,
                            rel_tol=1e-12)
        half = (out["upper90"] - out["lower90"]) / 2.0
        assert math.isclose(half, CI_HALF_K11, rel_tol=1e-12)
        assert math.isclose(out["s_analysis"], 1.5 * out["s_raw"],
                            rel_tol=1e-15)

    def test_guard_case_same_inputs_r1_vs_r15(self):
        """同输入:乘 1.5 前拟议界内;乘 1.5 后上端越过 0.003 ⇒
        不决。防止规划乘 1.5、报告漏乘(或反之)。"""
        r1 = M.classify_primary(0.0015, [VALID_SE] * 8, r_analysis=1.0)
        r15 = M.classify_primary(0.0015, [VALID_SE] * 8, r_analysis=1.5)
        assert r1["magnitude"] == "within_equivalence_bounds"
        assert math.isclose(r1["lower90"],
                            0.00037119176088350756, rel_tol=1e-12)
        assert math.isclose(r1["upper90"],
                            0.0026288082391164925, rel_tol=1e-12)
        assert r15["magnitude"] == "inconclusive"
        assert r15["upper90"] > MARGIN

    def test_multiplier_changes_ci_k_changes_se_not_multiplier(self):
        """改变区间倍率 ≠ 改变 K:倍率线性放大半宽;K 通过
        S_raw=sqrt(sum)/K 缩小。两者数值上不可互相冒充。"""
        ses = [VALID_SE] * 11
        base = M.analysis_ci(0.0, ses, r_analysis=1.0)
        wide = M.analysis_ci(0.0, ses, r_analysis=1.5)
        base_half = (base[1] - base[0]) / 2.0
        wide_half = (wide[1] - wide[0]) / 2.0
        assert math.isclose(wide_half, 1.5 * base_half, rel_tol=1e-15)
        fewer = M.analysis_ci(0.0, [VALID_SE] * 5, r_analysis=1.0)
        fewer_half = (fewer[1] - fewer[0]) / 2.0
        assert math.isclose(fewer_half, base_half * math.sqrt(11.0 / 5.0),
                            rel_tol=1e-12)

    def test_json_carries_primary_rule_and_guard(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        rule = doc["L1_primary_analysis_rule"]
        assert rule["r_analysis"] == 1.5
        assert "S_analysis = r_analysis*S_raw" in rule["formula"]
        guard = rule["guard_case_k8_same_inputs"]
        assert guard["r_analysis_1"]["magnitude"] == \
            "within_equivalence_bounds"
        assert guard["r_analysis_1_5"]["magnitude"] == "inconclusive"
        assert "负对照" in rule["r_analysis_one_role"]


# =====================================================================
# C03:true 尺度与 analysis 尺度分开;情景表固定 analysis=1.5
# =====================================================================
class TestScenarioTableFixedAnalysis:
    def test_all_rows_fix_analysis_at_1_5(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        rows = doc["L2_fixed_analysis_scenarios"]["rows"]
        assert [row["r_true"] for row in rows] == [1.0, 1.25, 1.5, 2.0]
        for row in rows:
            assert row["r_analysis"] == 1.5
            assert row["K"] == 11
            assert math.isclose(row["power_zero"],
                                POWER_ZERO[row["r_true"]],
                                rel_tol=1e-7)
            assert math.isclose(
                row["false_equivalence_at_boundary"],
                FALSE_EQUIV_AT_BOUNDARY[row["r_true"]], rel_tol=1e-7)

    def test_negative_control_unadjusted_only(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        control = doc["L2_fixed_analysis_scenarios"][
            "unadjusted_negative_control"]
        assert control["r_analysis"] == 1.0
        assert control["r_true"] == 1.5
        assert math.isclose(
            control["false_equivalence_at_positive_boundary"],
            UNADJUSTED_CONTROL, rel_tol=1e-7)
        # 主案表内不出现 r_analysis=1 的行动行
        for row in doc["L2_fixed_analysis_scenarios"]["rows"]:
            assert row["r_analysis"] != 1.0

    def test_recomputed_values_match_functions(self):
        for r_true, power in POWER_ZERO.items():
            got = M.equivalence_probability(
                0.0, MARGIN, 11, r_true * VALID_SE, 1.5 * VALID_SE)
            assert math.isclose(got, power, rel_tol=1e-7)
        for r_true, prob in FALSE_EQUIV_AT_BOUNDARY.items():
            got = M.equivalence_probability(
                MARGIN, MARGIN, 11, r_true * VALID_SE, 1.5 * VALID_SE)
            assert math.isclose(got, prob, rel_tol=1e-7)

    def test_near_zero_power_disclosed_below_target(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        rows = doc["L2_fixed_analysis_scenarios"]["rows"]
        for row in rows:
            if row["r_true"] >= 1.25:
                assert row["power_near_zero_0.0005"] < 0.93


# =====================================================================
# C04:最低K 同一实现复算;matched 5/8/11 保留;K−1 断言
# =====================================================================
class TestMinimumKSameImplementation:
    @pytest.mark.parametrize("rho,k_min", sorted(MATCHED_MIN_K.items()))
    def test_matched_scale_min_k_retained(self, rho, k_min):
        s = rho * VALID_SE
        assert M.minimum_k(s, MARGIN) == k_min
        assert M.zero_bias_power(MARGIN, k_min, s) >= 0.90
        assert M.zero_bias_power(MARGIN, k_min - 1, s) < 0.90

    @pytest.mark.parametrize("r_true,k_min",
                             sorted(FIXED_ANALYSIS_MIN_K.items()))
    def test_fixed_analysis_min_k(self, r_true, k_min):
        assert M.minimum_k_fixed_analysis(
            MARGIN, VALID_SE, r_true) == k_min
        at = M.equivalence_probability(
            0.0, MARGIN, k_min, r_true * VALID_SE, 1.5 * VALID_SE)
        below = M.equivalence_probability(
            0.0, MARGIN, k_min - 1, r_true * VALID_SE, 1.5 * VALID_SE)
        assert at >= 0.90 and below < 0.90

    def test_recommended_k11_worst_case(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        rec = doc["K_recompute_under_primary_rule"]["recommended"]
        assert rec["K"] == 11
        assert math.isclose(rec["power_at_K_zero_bias_worst_case"],
                            0.9236864590, rel_tol=1e-7)
        assert rec["power_at_K_minus_one_worst_case"] < 0.90

    def test_search_uses_fixed_policy_not_matched(self):
        """r_true=1 时固定规则 K=8,matched 规则 K=5:搜索策略确实
        按固定 r_analysis,而非随情景把区间改成 r_true。"""
        assert M.minimum_k_fixed_analysis(
            MARGIN, VALID_SE, 1.0) != M.minimum_k(VALID_SE, MARGIN)
        assert M.minimum_k_fixed_analysis(
            MARGIN, VALID_SE, 1.5) == M.minimum_k(1.5 * VALID_SE, MARGIN)


# =====================================================================
# C05:互斥分类、非零方向界内、触界/跨界/缺数据不决、不足坐标
# =====================================================================
class TestClassificationRulesV4:
    def test_within_bounds_allows_nonzero_direction(self):
        out = M.classify_primary(0.0015, [VALID_SE] * 11)
        assert out["magnitude"] == "within_equivalence_bounds"
        assert out["direction"] == "positive"

    def test_touching_straddling_missing_inconclusive(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        cases = doc["F_action_classification"]["cases"]
        for name in ("touching_bound", "straddling_bound",
                     "missing_data"):
            assert cases[name]["magnitude"] == "inconclusive"
        assert M.classify_result(
            0.0010, 0.0030, MARGIN)["magnitude"] == "inconclusive"

    def test_insufficient_coordinates_no_full_k_inference(self):
        out = M.classify_primary(0.0045, [VALID_SE] * 5, planned_k=11)
        assert out["k_coordinates"] == 5
        assert out["magnitude"] == "inconclusive"
        assert out["not_resolved_reason"] == "insufficient_coordinates"
        full = M.classify_primary(0.0045, [VALID_SE] * 11, planned_k=11)
        assert full["magnitude"] == "beyond_positive_margin"

    def test_mutually_exclusive_classes(self):
        verdicts = [
            M.classify_result(lo, up, MARGIN)
            for lo, up in ((0.0005, 0.0025), (0.0031, 0.0040),
                           (-0.0050, -0.0035), (0.0010, 0.0030),
                           (None, None), (-0.001, 0.004))]
        magnitudes = [v["magnitude"] for v in verdicts]
        assert set(magnitudes) == set(M.MAGNITUDE_CLASSES)
        assert magnitudes.count("inconclusive") == 3


# =====================================================================
# C06:边界声明与单一待审提案
# =====================================================================
class TestBoundariesAndProposal:
    def test_safety_factor_not_proof_of_bound(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        status = doc["L1_primary_analysis_rule"]["r_analysis_status"]
        assert "不是真实误差上界的证明" in status
        assert "抽样前固定" in status

    def test_condition_model_limits_present(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        limits = doc["I_proposal_pending_review"]["limits_and_boundaries"]
        joined = "".join(limits)
        assert "条件模型" in joined
        assert "经验保证" in joined or "非真实生成器经验保证" in joined
        assert "只加一次" in joined
        assert "不能直接沿用" in joined

    def test_single_pending_decision(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        proposal = doc["I_proposal_pending_review"]
        assert "PENDING_REVIEW" in proposal["status"]
        assert "不批准任何新抽样" in proposal["status"]
        assert "r_analysis" in proposal["single_pending_decision"]

    def test_md_states_rule_numbers_and_pending(self):
        text = MD_PATH.read_text(encoding="utf-8")
        assert "r_analysis=1.5" in text
        assert "5/8/11" in text
        assert "0.0499998948" in text
        assert "0.1364148993" in text
        assert "待审" in text
        assert "不批准任何新抽样" in text

    def test_v3_originals_untouched_as_history(self):
        """v3 脚本/JSON/提案保留为历史(不覆盖);v4 是现行入口。"""
        assert (REPORT_DIR / "r20_design_calc_v3.py").is_file()
        assert (REPORT_DIR / "r20_design_calc_v3.json").is_file()
        assert (REPORT_DIR / "route_c_stage2_6_1_r20_research_design_v3.md"
                ).is_file()


# =====================================================================
# 交叉一致:JSON 原件 ↔ 公式重算;非法输入
# =====================================================================
class TestCrossConsistencyV4:
    def test_json_matches_recomputation(self):
        doc = json.loads(JSON_PATH.read_text(encoding="utf-8"))
        assert doc["format"] == "r20-design-calc-v4"
        assert doc["inputs"]["valid_se"] == VALID_SE
        assert doc["inputs"]["valid_se_status"].startswith("READ-ONLY")
        worked = doc["L1_primary_analysis_rule"]["worked_example_k11"]
        recomputed = M.classify_primary(0.0015, [VALID_SE] * 11)
        for key in ("s_raw", "s_analysis", "lower90", "upper90"):
            assert math.isclose(worked[key], recomputed[key],
                                rel_tol=1e-12)
        for row in doc["A_min_k_matched_scale_retained"]["rows"]:
            if row["margin"] == MARGIN:
                assert row["min_K_power90_at_zero"] == \
                    MATCHED_MIN_K[row["rho"]]

    def test_mc_coherence_deterministic_and_within_tolerance(self):
        rows = M.mc_coherence(reps=20_000)
        assert all(row["within_five_mc_se"] for row in rows)
        again = M.mc_coherence(reps=20_000)
        assert rows == again

    @pytest.mark.parametrize("bad", [
        ("r", 0.0), ("r", -1.0), ("r", float("inf")),
    ])
    def test_invalid_analysis_factor(self, bad):
        with pytest.raises(ValueError):
            M.analysis_se([VALID_SE] * 11, bad[1])

    def test_invalid_inputs(self):
        with pytest.raises(ValueError):
            M.aggregate_raw_se([])
        with pytest.raises(ValueError):
            M.aggregate_raw_se([0.001, -0.001])
        with pytest.raises(ValueError):
            M.classify_result(0.002, 0.001, MARGIN)
        with pytest.raises(ValueError):
            M.classify_result(0.0001, 0.0002, -0.003)
        with pytest.raises(ValueError):
            M.minimum_k_fixed_analysis(MARGIN, VALID_SE, 1.5,
                                       max_k=1)
