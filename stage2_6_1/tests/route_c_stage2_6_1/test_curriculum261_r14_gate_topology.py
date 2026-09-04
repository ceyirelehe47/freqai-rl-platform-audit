# -*- coding: utf-8 -*-
"""R14 §五:gate topology 权威注册表回归测试。

四项合同回归(§五):
1. point-estimate diagnostic 从 PASS 改为 FAIL,不得改变总 verdict;
2. dedicated semantic binding gate 从 PASS 改为 FAIL,必须改变总 verdict;
3. local cue independence 或 context observability FAIL,必须改变总
   verdict;
4. plan、final、report 对每个 gate 的 binding status 完全一致。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r14_gate_topology import (
    R14_CUE_SEMANTIC_BINDING_SOURCE,
    R14_GATE_REGISTRY,
    R14_GATE_TOPOLOGY_VERSION,
    R14_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS,
    r14_binding_status,
    r14_cue_semantic_binding_uniqueness,
    r14_gate_topology_digest,
    r14_gate_topology_payload,
    r14_overridden_strict_gate_rule_text,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "rl_curriculum"

#: final qualification verdict 级 bool checks 的完整键集(与
#: _execute_final_core_inner_r14 的 checks dict 一致;两处同步锁定)。
EXPECTED_FINAL_BOOL_CHECKS = {
    "preprocessing_survival_8_of_8",
    "preprocessing_envelope_reload",
    "production_numerical_equivalence",
    "observation_space_v2",
    "adversarial_out_of_range",
    "reference_equivalence_all",
    "reference_equivalence_canonical_full",
    "routing_final_bundle_verified",
    "reproducibility_all",
    "matched_block_reproducibility",
    "latent_isolation",
    "fresh_seed_disjoint",
    "c1_strict_pass",
    "c3_strict_pass",
    "c2_matched_strict_pass",
    "c2_independent_marginal_pass",
    "c2_dedicated_semantic_corpus_pass",
    "semantic_block_count_consistent",
    "c2_density_pass",
    "c2_local_cue_independence_pass",
    "c2_context_observability_pass",
    "conditioning_gate",
    "supervised_gate",
    "block_contract_identity",
    "cue_semantic_contract_identity",
    "selected_block_count_consistent",
    "gate_topology_digest_consistent",
}


class TestRegistryTopology:
    def test_version_and_unique_cue_binding_source(self):
        assert R14_GATE_TOPOLOGY_VERSION == "GateTopologyReconciliation-v1"
        uniq = r14_cue_semantic_binding_uniqueness()
        assert uniq["pass"] is True
        assert list(uniq["binding_sources_for_cue_semantics"]) == [
            R14_CUE_SEMANTIC_BINDING_SOURCE]

    def test_point_diagnostics_entry_is_non_binding(self):
        entry = R14_GATE_REGISTRY["c2_matched_cue_point_diagnostics"]
        assert entry["binding"] is False
        assert entry["diagnostic_only"] is True
        assert entry["binding_gate"] is False
        assert entry["thresholds"] == {
            "cue_recall_min": 0.95,
            "cue_precision_min": 0.85,
            "non_cue_false_positive_max": 0.01,
            "payoff_bar_false_cue_max": 0.06,
        }

    def test_thresholds_frozen(self):
        assert R14_MATCHED_POINT_DIAGNOSTIC_THRESHOLDS == {
            "cue_recall_min": 0.95,
            "cue_precision_min": 0.85,
            "non_cue_false_positive_max": 0.01,
            "payoff_bar_false_cue_max": 0.06,
        }

    def test_registry_covers_all_final_bool_checks(self):
        """final checks 的每个 bool 键都在注册表登记为 binding(§四-5:
        所有 verdict 级 check 从同一权威来源取得 binding status)。"""
        registered_binding = {
            k for k, v in R14_GATE_REGISTRY.items() if v["binding"]}
        for name in EXPECTED_FINAL_BOOL_CHECKS:
            assert name in R14_GATE_REGISTRY, (
                f"final check '{name}' 未在 gate registry 注册")
            assert r14_binding_status(name)["binding"] is True

    def test_binding_status_fail_closed_on_unknown(self):
        with pytest.raises(RuntimeError, match="未在 R14 gate topology"):
            r14_binding_status("nonexistent_check_name")

    def test_dedicated_semantic_is_only_cue_binding(self):
        entry = R14_GATE_REGISTRY["c2_dedicated_semantic_corpus_pass"]
        assert entry["binding"] is True
        assert entry["authoritative_source"] == (
            R14_CUE_SEMANTIC_BINDING_SOURCE)
        assert entry["semantic_blocks_per_corpus"] == 160

    def test_matched_and_marginal_responsibilities_declared(self):
        matched = R14_GATE_REGISTRY["c2_matched_strict_pass"]
        assert "local_cue_independence" in matched["responsibilities"]
        assert "context_observability" in matched["responsibilities"]
        assert "cue_point_estimate" not in matched["responsibilities"]
        marginal = R14_GATE_REGISTRY["c2_independent_marginal_pass"]
        assert marginal["authoritative_source"] == (
            "independent_marginal_corpus")


def _make_gate_evidence(point_pass: bool,
                        dedicated_pass: bool,
                        local_cue_pass: bool = True,
                        context_pass: bool = True):
    """最小化构造 _build_gate_evidence_r14 的输入并调用真实实现。"""
    from rl_curriculum.curriculum261_r14_final import (
        _build_gate_evidence_r14,
    )

    checks = {name: True for name in EXPECTED_FINAL_BOOL_CHECKS}
    checks["c2_dedicated_semantic_corpus_pass"] = dedicated_pass
    checks["c2_local_cue_independence_pass"] = local_cue_pass
    checks["c2_context_observability_pass"] = context_pass
    semantics = {
        "local_cue_independence": {"pass": local_cue_pass},
        "context_observability": {"pass": context_pass},
        "cue_payoff_separation": {"pass": point_pass,
                                  "point_recall": 0.94},
    }
    matched_point_diag = {
        "diagnostic_only": True, "binding_gate": False,
        "source": "matched_ladder_point_estimates",
        "results": semantics["cue_payoff_separation"],
        "note": "test",
    }
    evidence = _build_gate_evidence_r14(
        checks=checks,
        conditions={"c1_opportunity": {"pass": True},
                    "c3_cost": {"pass": True},
                    "c2_context": {"pass": True}},
        semantic={"pass": dedicated_pass, "n_blocks": 160},
        semantics=semantics,
        matched_point_diag=matched_point_diag,
        density={"pass": True},
        c2_marginal={"guard": {"pass": True}},
        pack={"digest": "r14pk-test"},
        plan_digest="r14qp-test",
        supervised={"pass": True},
        conditioning={"pass": True},
        reference_report={"pass": True, "n_episodes": 4,
                          "canonical_scaled_full_equality": True,
                          "legacy_action_diffs_total": 0,
                          "unexplained_mismatches": 0},
        fresh={"pass": True}, latent={"pass": True}, repro=[],
        topology_digest_ok=True)
    return checks, evidence


def _verdict_from_checks(checks: dict) -> bool:
    """复刻 final 的 verdict 聚合(all bool checks)。"""
    return bool(all(v for v in checks.values() if isinstance(v, bool)))


class TestVerdictTopologyRegression:
    """§五 四项合同回归。"""

    def test_point_diagnostic_fail_does_not_change_verdict(self):
        # 点估计诊断 FAIL(如 R13 的 0.948571 < 0.95),其余全过
        checks, evidence = _make_gate_evidence(point_pass=False,
                                               dedicated_pass=True)
        assert _verdict_from_checks(checks) is True
        # 诊断失败不计入 failed_binding_checks
        assert evidence["failed_binding_checks"] == []
        diag = evidence["gates"]["c2_matched_cue_point_diagnostics"]
        assert diag["binding"] is False
        assert diag["diagnostic_only"] is True
        assert diag["failed"] is True
        assert diag["diagnostic_verdict_neutral"] is True

    def test_dedicated_semantic_fail_changes_verdict(self):
        checks, evidence = _make_gate_evidence(point_pass=True,
                                               dedicated_pass=False)
        assert _verdict_from_checks(checks) is False
        assert evidence["failed_binding_checks"] == [
            "c2_dedicated_semantic_corpus_pass"]
        gate = evidence["gates"]["c2_dedicated_semantic_corpus_pass"]
        assert gate["binding"] is True

    def test_local_cue_fail_changes_verdict(self):
        checks, evidence = _make_gate_evidence(
            point_pass=True, dedicated_pass=True, local_cue_pass=False)
        assert _verdict_from_checks(checks) is False
        assert "c2_local_cue_independence_pass" in (
            evidence["failed_binding_checks"])

    def test_context_observability_fail_changes_verdict(self):
        checks, evidence = _make_gate_evidence(
            point_pass=True, dedicated_pass=True, context_pass=False)
        assert _verdict_from_checks(checks) is False
        assert "c2_context_observability_pass" in (
            evidence["failed_binding_checks"])

    def test_binding_status_consistent_across_plan_final_report(self):
        """plan/final/report 的 binding status 来自同一注册表(§四-5)。

        - payload(进 plan)的 binding/diagnostic 清单 == 注册表;
        - gate_evidence(进 final result)每 gate 的 binding 字段 ==
          注册表条目(上面 _make_gate_evidence 已调用真实实现);
        - report 读取 final result(同 artifact)。
        """
        payload = r14_gate_topology_payload()
        registry_binding = sorted(
            k for k, v in R14_GATE_REGISTRY.items() if v["binding"])
        registry_diagnostic = sorted(
            k for k, v in R14_GATE_REGISTRY.items() if not v["binding"])
        assert payload["binding_checks"] == registry_binding
        assert payload["diagnostic_only_checks"] == registry_diagnostic
        checks, evidence = _make_gate_evidence(point_pass=True,
                                               dedicated_pass=True)
        for name, gate in evidence["gates"].items():
            status = r14_binding_status(name)
            assert gate["binding"] == status["binding"]
            assert gate["diagnostic_only"] == status["diagnostic_only"]
        # plan 顶层与 statistics_rule 同一 digest(final 一致性检查读取)
        assert payload["cue_semantic_binding_source"] == (
            R14_CUE_SEMANTIC_BINDING_SOURCE)


class TestFinalSourceContract:
    """final 源码级拓扑断言(实现与注册表同步)。"""

    def test_final_no_c2_semantics_pass_binding(self):
        text = (SRC / "curriculum261_r14_final.py").read_text(
            encoding="utf-8")
        assert '"c2_semantics_pass"' not in text
        assert '"c2_local_cue_independence_pass"' in text
        assert '"c2_context_observability_pass"' in text
        assert '"c2_dedicated_semantic_corpus_pass"' in text
        assert '"gate_topology_digest_consistent"' in text
        assert "c2_matched_cue_point_diagnostics" in text

    def test_r13_final_binding_line_absent_in_r14(self):
        """R13 的三诊断 AND 绑定(c2_semantics_pass = all(semantics
        三项 pass),点估计 gate 随之 binding)在 R14 不得复现。"""
        text = (SRC / "curriculum261_r14_final.py").read_text(
            encoding="utf-8")
        assert 'v["pass"] for v in semantics.values()' not in text

    def test_plan_overrides_r6_old_topology_text(self):
        text = (SRC / "curriculum261_r14_plan.py").read_text(
            encoding="utf-8")
        assert "r14_overridden_strict_gate_rule_text()" in text
        assert "gate_topology_digest" in text
        overrides = r14_overridden_strict_gate_rule_text()
        assert "diagnostic_only" in overrides["c2_matched"]
        assert "cue/payoff 点估计分离检查仅 diagnostic_only" in (
            overrides["c2_matched"])
        # R6 字典被覆盖而非修改共享模块
        r6 = (SRC / "curriculum261_r6_pairs.py").read_text(
            encoding="utf-8")
        assert "cue/payoff separation" in r6  # R6 历史不变

    def test_digest_is_deterministic_and_prefixed(self):
        d1 = r14_gate_topology_digest()
        d2 = r14_gate_topology_digest(r14_gate_topology_payload())
        assert d1 == d2
        assert d1.startswith("r14gt-")


class TestR13CalibrationDelegationHonored:
    def test_calibration_delegation_note_exists(self):
        text = (SRC / "curriculum261_r14_calibration.py").read_text(
            encoding="utf-8")
        assert "cue_semantics_delegated_note" in text
        assert "run_c2_diagnostics_r14" in text
        # 定位文字保持诊断对照
        assert "诊断对照" in text

    def test_cue_eval_independent_point_gate_floor_is_0_90(self):
        """independent marginal 的点估计灾难护栏保持 0.90(非 0.95)。"""
        text = (SRC / "curriculum261_r14_cue_eval.py").read_text(
            encoding="utf-8")
        assert "point_recall_ge_absolute_floor" in text
        assert "diagnostic_only" in text
