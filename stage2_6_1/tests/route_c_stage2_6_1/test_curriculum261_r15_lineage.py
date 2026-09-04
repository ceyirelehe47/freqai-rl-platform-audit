"""R15 传递性 cue metric binding lineage 测试(§六;工作包 B)。

R14 隐藏双绑定的机械回归:independent_cue_semantics.pass 曾含
point recall ≥ 0.90 与 noncue FP UCB ≤ 0.01 并被 AND 进
marginal guard → final verdict。R15 拆分 structural(binding)与
cue_point_diagnostics(diagnostic_only/verdict-neutral)。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import rl_curriculum.curriculum261_r15_calibration as r15cal
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_r15_gate_topology import (
    R15_CUE_SEMANTIC_BINDING_SOURCE,
    R15_GATE_REGISTRY,
    r15_binding_lineage,
    r15_cue_semantic_binding_uniqueness,
    r15_gate_topology_digest,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "rl_curriculum"
RUNGS = ("D0", "D1", "D2", "D3")

#: 诊断 pass 的可控开关(测试内闭包)
_DIAG_STATE = {"pass": True}


def _fake_cue(records, candidate_id, thresholds=None,
              recall_floor_value=0.0):
    """合成 v2 结构的 independent cue 语义(diag pass 可控)。"""
    diag_pass = _DIAG_STATE["pass"]
    return {
        "format": "cur261-r15-independent-cue-semantics-v2",
        "candidate": candidate_id,
        "structural": {
            "checks": {"canonical_consistency": True},
            "binding_leaf_checks": ["canonical_consistency"],
            "pass": True,
        },
        "cue_point_diagnostics": {
            "diagnostic_only": True,
            "binding_gate": False,
            "verdict_neutral": True,
            "checks": {
                "point_recall_ge_absolute_floor": diag_pass,
                "noncue_fp_ucb_le_max": diag_pass,
            },
            "pass": diag_pass,
        },
        "pass": True,
    }


def _base_all_true():
    return {
        "format": "cur261-r6-c2-marginal-guard-v1",
        "mean_ordering_ok": True,
        "d3_mean_positive": True,
        "fixed_baseline_means_positive": True,
        "integrity_unity": True,
        "oracle_positive": True,
        "density_pass": True,
        "semantics_pass": True,
        "pass": True,
    }


def _run_guard(monkeypatch, *, base=None, diag_pass=True,
               local=True, context=True):
    _DIAG_STATE["pass"] = diag_pass
    monkeypatch.setattr(r15cal, "independent_cue_semantics", _fake_cue)
    # c2_marginal_guard_conditions 在 guard 内函数内 import(r6_pairs)
    import rl_curriculum.curriculum261_r6_pairs as r6pairs

    monkeypatch.setattr(
        r6pairs, "c2_marginal_guard_conditions",
        lambda *a, **k: base if base is not None else _base_all_true())
    monkeypatch.setattr(r15cal, "c2_density_summary",
                        lambda rows, r: {"pass": True})
    monkeypatch.setattr(r15cal, "density_gate_r5",
                        lambda d: {"pass": True})
    monkeypatch.setattr(r15cal, "_reference_long_label_rate",
                        lambda *a, **k: 0.0)
    monkeypatch.setattr(
        r15cal, "r15_family_rung_params",
        lambda fam, pack: {r: {} for r in RUNGS})
    monkeypatch.setattr(
        r15cal, "family_specs",
        lambda: {FAMILY_C2: SimpleNamespace(
            reference_defaults={"cue_thr": 0.0})})
    import rl_curriculum.curriculum261_qualification as qual

    monkeypatch.setattr(
        qual, "check_c2_local_cue_independence",
        lambda records: {"pass": local, "binding_leaf_checks": [
            "local_cue_independence"]})
    monkeypatch.setattr(
        qual, "check_c2_context_observability",
        lambda records: {"pass": context, "binding_leaf_checks": [
            "context_observability"]})
    indep = {
        "report": {"by_rung": {r: {"episodes": []} for r in RUNGS}},
        "records": [],
        "seed_namespace": "lineage_test_ns",
        "pairs_per_rung": 2,
    }
    return r15cal.c2_independent_marginal_guard_r15(
        indep, {"selected_c2_candidate": "selected"}, 0.93)


class TestVerdictNeutralDiagnostics:
    """§六 A/B:independent cue 点诊断 FAIL ⇒ binding/verdict 不变。"""

    def test_A_point_recall_zero_diagnostic_fail_binding_unchanged(
            self, monkeypatch):
        g_pass = _run_guard(monkeypatch, diag_pass=True)
        g_fail = _run_guard(monkeypatch, diag_pass=False)
        # 诊断 pass 翻转...
        assert g_pass["independent_cue_point_diagnostics"]["pass"] \
            is True
        assert g_fail["independent_cue_point_diagnostics"]["pass"] \
            is False
        assert g_fail["independent_cue_point_diagnostics"][
            "checks"]["point_recall_ge_absolute_floor"] is False
        # ...binding result 与 final binding check 不变
        assert g_pass["guard"]["pass"] is g_fail["guard"]["pass"] is True
        assert (g_pass["guard"]["binding_leaf_checks"]
                == g_fail["guard"]["binding_leaf_checks"])
        assert g_fail["guard"]["cue_point_metrics_binding"] is False
        assert g_fail["guard"][
            "cue_point_metrics_diagnostic_only"] is True

    def test_B_noncue_fp_exceeded_diagnostic_fail_binding_unchanged(
            self, monkeypatch):
        g = _run_guard(monkeypatch, diag_pass=False)
        assert g["guard"]["pass"] is True
        assert g["independent_cue_point_diagnostics"]["pass"] is False

    def test_final_check_source_references_guard_pass_only(self):
        """final 的 c2_independent_marginal_pass 唯一来源 =
        guard.pass(源码级;§六 A 的 final 层证明)。"""
        final_src = (SRC / "curriculum261_r15_final.py").read_text(
            encoding="utf-8")
        assert 'marginal_pass = bool(c2_marginal["guard"]["pass"])' \
            in final_src
        assert '"c2_independent_marginal_pass": marginal_pass' \
            in final_src

    def test_cue_eval_v2_structure_diagnostic_only(self):
        """真实 independent_cue_semantics 输出:cue 点指标仅在
        cue_point_diagnostics(诊断),顶层 pass=structural。"""
        import inspect

        from rl_curriculum.curriculum261_r15_cue_eval import (
            independent_cue_semantics,
        )
        src = inspect.getsource(independent_cue_semantics)
        assert '"cue_point_diagnostics": {' in src
        assert '"binding_leaf_checks": sorted(structural_checks)' in src
        assert '"pass": structural_pass' in src
        # structural(binding)区不含 cue 点指标;点指标仅在
        # diagnostic_checks(诊断)区
        assert 'point_recall_ge_absolute_floor": bool(' in src
        struct_block = src[src.index("structural_checks = {"):
                           src.index("diagnostic_checks = {")]
        assert "point_recall" not in struct_block
        assert "noncue" not in struct_block


class TestDedicatedAndStructuralBinding:
    """§六 C/D:dedicated FAIL ⇒ final FAIL;structural leaf FAIL
    ⇒ final FAIL。"""

    def test_C_dedicated_fail_sinks_final(self):
        """dedicated semantic corpus FAIL ⇒ c2_dedicated_*
        =False ⇒ final verdict FAIL(checks AND 语义)。"""
        checks = {"c2_dedicated_semantic_corpus_pass": False,
                  "other": True}
        verdict_pass = all(
            v for v in checks.values() if isinstance(v, bool))
        assert verdict_pass is False

    @pytest.mark.parametrize("leaf", [
        "mean_ordering_ok", "d3_mean_positive",
        "fixed_baseline_means_positive", "integrity_unity",
        "oracle_positive", "density_pass",
    ], ids=lambda x: x)
    def test_D_base_structural_leaf_fail_sinks_guard(
            self, monkeypatch, leaf):
        base = _base_all_true()
        base[leaf] = False
        base["pass"] = False
        g = _run_guard(monkeypatch, base=base)
        assert g["guard"]["pass"] is False
        assert leaf in g["guard"]["binding_leaf_checks"]

    def test_D_local_cue_fail_sinks_guard(self, monkeypatch):
        g = _run_guard(monkeypatch, local=False)
        assert g["guard"]["pass"] is False

    def test_D_context_fail_sinks_guard(self, monkeypatch):
        g = _run_guard(monkeypatch, context=False)
        assert g["guard"]["pass"] is False

    def test_D_canonical_consistency_fail_sinks_guard(
            self, monkeypatch):
        _DIAG_STATE["pass"] = True
        monkeypatch.setattr(r15cal, "independent_cue_semantics",
                            _fake_cue)
        import rl_curriculum.curriculum261_r6_pairs as r6pairs

        monkeypatch.setattr(
            r6pairs, "c2_marginal_guard_conditions",
            lambda *a, **k: _base_all_true())
        monkeypatch.setattr(r15cal, "c2_density_summary",
                            lambda rows, r: {"pass": True})
        monkeypatch.setattr(r15cal, "density_gate_r5",
                            lambda d: {"pass": True})
        monkeypatch.setattr(r15cal, "_reference_long_label_rate",
                            lambda *a, **k: 0.0)
        monkeypatch.setattr(
            r15cal, "r15_family_rung_params",
            lambda fam, pack: {r: {} for r in RUNGS})
        monkeypatch.setattr(
            r15cal, "family_specs",
            lambda: {FAMILY_C2: SimpleNamespace(
                reference_defaults={"cue_thr": 0.0})})
        import rl_curriculum.curriculum261_qualification as qual

        monkeypatch.setattr(
            qual, "check_c2_local_cue_independence",
            lambda records: {"pass": True})
        monkeypatch.setattr(
            qual, "check_c2_context_observability",
            lambda records: {"pass": True})

        def cue_struct_fail(records, cid, thr=None, **k):
            out = _fake_cue(records, cid, thr, **k)
            out["structural"] = {
                "checks": {"canonical_consistency": False},
                "binding_leaf_checks": ["canonical_consistency"],
                "pass": False}
            out["pass"] = False
            return out

        monkeypatch.setattr(r15cal, "independent_cue_semantics",
                            cue_struct_fail)
        indep = {
            "report": {"by_rung": {r: {"episodes": []}
                                   for r in RUNGS}},
            "records": [], "seed_namespace": "ns", "pairs_per_rung": 2}
        g = r15cal.c2_independent_marginal_guard_r15(
            indep, {"selected_c2_candidate": "s"}, 0.93)
        assert g["guard"]["pass"] is False


class TestLineageAudit:
    """§六 E/F:隐藏未声明 leaf ⇒ FAIL;缺声明 ⇒ fail closed。"""

    def _guard_output(self, monkeypatch):
        return _run_guard(monkeypatch, diag_pass=True)

    def test_E_hidden_undeclared_cue_recall_leaf_fails(self,
                                                       monkeypatch):
        g = self._guard_output(monkeypatch)
        tampered = dict(g["guard"])
        tampered["binding_leaf_checks"] = list(
            g["guard"]["binding_leaf_checks"]) + ["cue_recall"]
        result = r15_binding_lineage({
            "c2_independent_marginal_pass": tampered})
        assert result["pass"] is False
        assert any("cue_recall" in p for p in result["problems"])

    def test_E_declared_but_missing_self_report_fails_for_cue(
            self):
        """cue metric binding 条目无自报 ⇒ fail closed。"""
        result = r15_binding_lineage({
            "c2_dedicated_semantic_corpus_pass": {
                "pass": True}})  # 无 binding_leaf_checks
        assert result["pass"] is False
        assert result["entries"][
            "c2_dedicated_semantic_corpus_pass"]["status"] == "FAIL"

    def test_E_match_passes_for_real_guard(self, monkeypatch):
        g = self._guard_output(monkeypatch)
        result = r15_binding_lineage({
            "c2_independent_marginal_pass": g["guard"]})
        entry = result["entries"]["c2_independent_marginal_pass"]
        assert entry["status"] == "match", result["problems"]
        # 该条目单独 pass 不代表全局(cue dedicated 需要自报)
        assert result["entries"][
            "c2_dedicated_semantic_corpus_pass"]["status"] == "FAIL"

    def test_F_missing_leaf_declaration_fails_closed(self, monkeypatch):
        import rl_curriculum.curriculum261_r15_gate_topology as gt

        broken = {k: dict(v) for k, v in R15_GATE_REGISTRY.items()}
        del broken["c2_matched_strict_pass"]["leaf_metrics"]
        broken["c2_matched_strict_pass"]["leaf_metrics"] = ()
        monkeypatch.setattr(gt, "R15_GATE_REGISTRY", broken)
        result = gt.r15_binding_lineage({})
        assert result["pass"] is False
        assert any("声明 leaf_metrics 为空" in p
                   for p in result["problems"])

    def test_F_registry_constructor_rejects_empty_leaves(self):
        from rl_curriculum.curriculum261_r15_gate_topology import (
            _binding,
        )
        with pytest.raises(RuntimeError, match="缺 leaf_metrics"):
            _binding("x", "src", "rule", leaf_metrics=())

    def test_F_registry_constructor_requires_metric_scope_key(self):
        """binding 条目没有 metric_scope 键 ⇒ 构造期(校验期)拒绝
        (R14 optional 缺省 fail-open 的修复)。"""
        import rl_curriculum.curriculum261_r15_gate_topology as gt
        from rl_curriculum.curriculum261_r15_gate_topology import (
            _binding,
        )

        entry = _binding("y", "src", "rule",
                         leaf_metrics=("y",))
        del entry["metric_scope"]
        broken = dict(gt.R15_GATE_REGISTRY)
        broken["y"] = entry
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(gt, "R15_GATE_REGISTRY", broken)
        try:
            with pytest.raises(RuntimeError,
                               match="缺 metric_scope"):
                gt._validate_registry()
        finally:
            monkeypatch.undo()


class TestCrossLayerConsistency:
    """§六 G:plan/final/gate_evidence/report 的 source/binding 一致。"""

    def test_gate_evidence_declared_leaves_match_registry(
            self, monkeypatch):
        g = _run_guard(monkeypatch)
        from rl_curriculum.curriculum261_r15_final import (
            _build_gate_evidence_r15,
        )
        checks = {k: True for k in (
            k for k, v in R15_GATE_REGISTRY.items() if v["binding"])}
        checks["binding_lineage_consistent"] = True
        evidence = _build_gate_evidence_r15(
            checks=checks,
            conditions={"c1_opportunity": {"pass": True},
                        "c3_cost": {"pass": True},
                        "c2_context": {"pass": True,
                                       "binding_leaf_checks": [
                                           "a", "b", "c", "d", "e",
                                           "f"]}},
            semantic={"pass": True,
                      "binding_leaf_checks": sorted(
                          R15_GATE_REGISTRY[
                              "c2_dedicated_semantic_corpus_pass"][
                              "leaf_metrics"])},
            semantics={"local_cue_independence": {"pass": True},
                       "context_observability": {"pass": True}},
            matched_point_diag={"results": {"pass": True}},
            density={"pass": True},
            c2_marginal=g,
            pack={"digest": "r15pk-x"},
            plan_digest="r15qp-x",
            supervised={"pass": True},
            conditioning={"pass": True},
            reference_report={"pass": True, "n_episodes": 1,
                              "canonical_scaled_full_equality": True,
                              "legacy_action_diffs_total": 0,
                              "unexplained_mismatches": 0},
            fresh={"pass": True}, latent={"pass": True},
            repro=None, topology_digest_ok=True,
            binding_lineage=r15_binding_lineage({
                "c2_independent_marginal_pass": g["guard"],
                "c2_dedicated_semantic_corpus_pass": {
                    "binding_leaf_checks": sorted(
                        R15_GATE_REGISTRY[
                            "c2_dedicated_semantic_corpus_pass"][
                            "leaf_metrics"])},
                "c2_matched_strict_pass": {
                    "binding_leaf_checks": sorted(
                        R15_GATE_REGISTRY[
                            "c2_matched_strict_pass"][
                            "leaf_metrics"])},
            }))
        for name in ("c2_independent_marginal_pass",
                     "c2_dedicated_semantic_corpus_pass",
                     "c2_matched_strict_pass"):
            declared = evidence["gates"][name][
                "declared_leaf_metrics"]
            assert sorted(R15_GATE_REGISTRY[name]["leaf_metrics"]) \
                == sorted(declared), name

    def test_plan_and_registry_digest_consistent(self):
        """plan 携带 gate_topology_digest(源码级)+ 注册表 digest 稳定。"""
        plan_src = (SRC / "curriculum261_r15_plan.py").read_text(
            encoding="utf-8")
        assert "gate_topology_digest" in plan_src
        assert r15_gate_topology_digest() == \
            r15_gate_topology_digest()

    def test_uniqueness_single_source(self):
        u = r15_cue_semantic_binding_uniqueness()
        assert u["pass"] is True
        assert list(u["binding_sources_for_cue_semantics"]) == [
            R15_CUE_SEMANTIC_BINDING_SOURCE]
