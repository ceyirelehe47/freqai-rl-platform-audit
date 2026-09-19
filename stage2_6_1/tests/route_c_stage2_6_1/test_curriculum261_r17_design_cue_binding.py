# -*- coding: utf-8 -*-
"""R17 §15b 候选级 dedicated cue 语义统一的行为级防回归。

锚:外部审查 RouteC_R18_Report_Review_4a5d2fd §4.1 + GOAL.md
"cue recall/precision/noncue FP/payoff false-cue 的正式绑定来自原
dedicated 合同;matched/independent 点指标只诊断,结构检查仍真实执行"。

证明的行为(全部为真实执行路径,非源码字符串检查):
1. matched 40-block candidate corpus 的 cue 点指标仅诊断——将其
   置为全 FAIL/最优,资格判定输入(semantics_pass / per_formal_
   block_count)与 maximin 排序逐位不变;
2. 四类 cue rate metric 对资格与排序的影响唯一来自候选级
   dedicated semantic 结果(_selection_view_r17 路由):dedicated
   gate FAIL ⇒ 不合格;dedicated 候选界值变差 ⇒ maximin 分严格
   下降;
3. 候选级 dedicated namespace 的派生/文件名/corpus role 显式规则
   fail-closed(未注册 candidate 不落入任何映射)。
"""

from __future__ import annotations

import copy
import json

import pytest

from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r6_tape import (
    generate_matched_block_with_attempts,
)
from rl_curriculum.curriculum261_r17_design import (
    _evaluate_candidate_matched_r17,
    _maximin_score_r17,
    _qualified_at_n,
    _selection_view_r17,
    candidate_semantic_namespace_r17,
    semantic_artifact_filename_r17,
    semantic_corpus_role_r17,
    write_semantic_artifact_r17,
)
from rl_curriculum.curriculum261_r17_param_pack import r17_candidate_grid

RUNGS = ("D0", "D1", "D2", "D3")
CID = "c2l_historical_control"
NS = "preplan_smoke_r17"
N_BLOCKS = 6


def _thresholds() -> dict:
    return dict(family_specs()[FAMILY_C2].reference_defaults)


def _raw_eval_result() -> dict:
    ladder = r17_candidate_grid()[CID]
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace=NS, block_index=i) for i in range(N_BLOCKS)]
    return _evaluate_candidate_matched_r17(
        CID, ladder, NS, _thresholds(), blocks=blocks, n_blocks=N_BLOCKS)


def _dedicated(pass_: bool, prec: float = 0.95, fc: float = 0.02) -> dict:
    """候选级 dedicated semantic 摘要(与 run_c2_semantic_corpus_r17
    报告经 inner 流程归档后的形状一致:candidate 字段 = 完整
    candidate_cue_semantics 结果块,非 candidate id 字符串)。"""
    per_rung = {}
    for rung in RUNGS:
        sides = {}
        for side in ("A", "B"):
            sides[side] = {
                "cue_precision": {"bound": prec, "min": 0.85,
                                  "pass": pass_},
                "payoff_false_cue": {"bound": fc, "max": 0.06,
                                     "pass": pass_},
            }
        per_rung[rung] = {"sides": sides, "pass": pass_}
    candidate_block = {
        "candidate": CID,
        "cluster_unit": "matched_block",
        "pass": pass_,
        "per_rung": per_rung,
    }
    return {
        "namespace": f"cue_semantic_design_main_r17__{CID}",
        "pass": pass_,
        "shared_pass": pass_,
        "candidate_pass": pass_,
        "candidate": candidate_block,
    }


class TestMatchedCueDiagnosticsAreDiagnosticOnly:
    """matched 40-block cue 点指标不得影响资格与排序(行为不变性)。"""

    def test_artifact_declares_diagnostic_only(self):
        raw = _raw_eval_result()
        assert raw["semantics"]["cue_point_metrics_binding"] is False
        assert raw["semantics"]["cue_point_metrics_diagnostic_only"] \
            is True
        assert raw["semantics"]["formal_binding_source"] == (
            "candidate_dedicated_160_block_semantic_corpus")
        # 诊断数据仍真实计算并报告(不是删除)
        assert set(raw["semantics"][
            "candidate_cue_semantics_r17_cluster_aware"]["per_rung"]
        ) == set(RUNGS)

    def test_failing_matched_cue_does_not_change_qualification_inputs(
            self, monkeypatch):
        from rl_curriculum import curriculum261_r17_design as design
        raw = _raw_eval_result()

        def failing_cue_semantics(blocks, candidate_id, thresholds=None):
            out = copy.deepcopy(raw["semantics"][
                "candidate_cue_semantics_r17_cluster_aware"])
            out["pass"] = False
            for per_rung in out["per_rung"].values():
                per_rung["pass"] = False
                for side in per_rung["sides"].values():
                    side["pass"] = False
                    side["cue_precision"]["bound"] = 0.0
                    side["payoff_false_cue"]["bound"] = 1.0
            return out

        monkeypatch.setattr(
            design, "candidate_cue_semantics", failing_cue_semantics)
        perturbed = _raw_eval_result()
        monkeypatch.undo()

        assert perturbed["semantics_pass"] == raw["semantics_pass"]
        assert (perturbed["per_formal_block_count"]
                == raw["per_formal_block_count"])
        assert perturbed["density_pass"] == raw["density_pass"]

    def test_matched_cue_values_do_not_change_maximin_or_views(self):
        raw_good = _raw_eval_result()
        raw_bad = copy.deepcopy(raw_good)
        for per_rung in raw_bad["semantics"][
                "candidate_cue_semantics_r17_cluster_aware"][
                "per_rung"].values():
            for side in per_rung["sides"].values():
                side["cue_precision"]["bound"] = 0.0
                side["payoff_false_cue"]["bound"] = 1.0

        ded = _dedicated(True)
        view_good = _selection_view_r17(raw_good, ded)
        view_bad = _selection_view_r17(raw_bad, ded)
        for n in ("10", "15", "20"):
            assert _qualified_at_n(
                [view_good, view_good], int(n)) == _qualified_at_n(
                [view_bad, view_bad], int(n))
        for n in (10, 15, 20):
            assert _maximin_score_r17(
                [view_good, view_good], n) == _maximin_score_r17(
                [view_bad, view_bad], n)


class TestDedicatedGateBindsQualificationAndRanking:
    """四类 cue rate metric 的资格/排序影响唯一来自候选级 dedicated。"""

    def test_dedicated_fail_disqualifies_even_if_matched_passes(self):
        raw = _raw_eval_result()
        # 结构语义人为置真:本测试验证接线(绑定来源),不验证统计
        raw_ok = copy.deepcopy(raw)
        raw_ok["semantics"]["local_cue_independence"]["pass"] = True
        raw_ok["semantics"]["context_observability"]["pass"] = True

        view_pass = _selection_view_r17(raw_ok, _dedicated(True))
        view_fail = _selection_view_r17(raw_ok, _dedicated(False))
        assert view_pass["semantics_pass"] is True
        assert view_fail["semantics_pass"] is False
        for n in (10, 15, 20):
            assert _qualified_at_n([view_pass, view_pass], n) in (
                True, False)  # 结构/功率面不受本测试控制
            assert _qualified_at_n([view_fail, view_fail], n) is False

    def test_dedicated_bounds_drive_maximin_strictly(self):
        raw = _raw_eval_result()
        view_good = _selection_view_r17(raw, _dedicated(
            True, prec=0.95, fc=0.02))
        view_bad = _selection_view_r17(raw, _dedicated(
            True, prec=0.86, fc=0.059))
        for n in (10, 15, 20):
            assert _maximin_score_r17(
                [view_good, view_good], n) > _maximin_score_r17(
                [view_bad, view_bad], n)

    def test_view_cue_key_carries_dedicated_data_not_matched(self):
        raw = _raw_eval_result()
        ded = _dedicated(True, prec=0.91, fc=0.03)
        view = _selection_view_r17(raw, ded)
        assert view["semantics"][
            "candidate_cue_semantics_r17_cluster_aware"] == ded["candidate"]
        # raw 原件不被视图构造改动(matched 诊断保留在 raw)
        assert raw["semantics"][
            "candidate_cue_semantics_r17_cluster_aware"] != ded["candidate"]


class TestCandidateNamespaceExplicitMapping:
    """候选级 namespace 派生/文件名/role 的显式规则与 fail-closed。"""

    def test_derivation_and_filename(self):
        ns = candidate_semantic_namespace_r17(
            "cue_semantic_design_main_r17", "c2l_midpoint")
        assert ns == "cue_semantic_design_main_r17__c2l_midpoint"
        assert semantic_artifact_filename_r17(ns) == (
            "semantic_design_main__c2l_midpoint.json")
        assert semantic_corpus_role_r17(ns) == "main_candidate"

    def test_unregistered_candidate_fails_closed(self):
        bogus = "cue_semantic_design_main_r17__c2l_unknown"
        with pytest.raises(RuntimeError):
            semantic_artifact_filename_r17(bogus)
        with pytest.raises(RuntimeError):
            semantic_corpus_role_r17(bogus)
    def test_writer_stamps_role_and_exclusive_create(self, tmp_path):
        ns = candidate_semantic_namespace_r17(
            "cue_semantic_design_main_r17", CID)
        path = write_semantic_artifact_r17(
            tmp_path, ns, {"payload": 1}, "r17dp-test")
        assert path.name == f"semantic_design_main__{CID}.json"
        back = json.loads(path.read_text(encoding="utf-8"))
        assert back["namespace"] == ns
        assert back["corpus_role"] == "main_candidate"
        assert back["design_plan_digest"] == "r17dp-test"
        with pytest.raises(FileExistsError):
            write_semantic_artifact_r17(
                tmp_path, ns, {"payload": 2}, "r17dp-test")
