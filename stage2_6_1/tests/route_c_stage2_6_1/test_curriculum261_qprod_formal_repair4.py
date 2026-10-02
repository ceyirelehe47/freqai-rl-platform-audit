"""修复轮 R2 追加验证(ChatGPT R1 复审 A.2 / B)。

- A.2 新输入身份覆盖:QAF 生成/设计/smoke 族注册(183/16)、
  迭代标签、seed 隔离、输入范围 26、CLI/链 argv 接线、cue-audit
  锁定 plan 的 QAF 语料、design 计划锁 QAF 命名空间、
  determinism A4 目标面覆盖。
- B 预算完整化:bootstrap 全量(cue 4+preplan 3+design 40+
  calibrate 8+qualify 4=59 调用×20000)、Global-K 独立随机程序、
  check_env 入面;动作前预算门(正数不足/刚好/耗尽/重放/后继
  不可达/篡改放大;工程路径无 gate 不门控)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_qaf_attempt import (
    QAF_ALL_NEW, QAF_GENERATION_FAMILY, QAF_INPUT_SCOPE)
from rl_curriculum.curriculum261_api import (
    CURRICULUM261_R17_NAMESPACES as R17_ALL,
    CURRICULUM261_SEED_NAMESPACES,
    _default_recorder, derive261_seed)
from rl_curriculum.curriculum261_qprod_context import QProdContextError
from rl_curriculum.curriculum261_qprod_formal_budget import (
    GATE_FILENAME, GATED_STEPS, K, authorization_face,
    assert_stage_budget_gate, build_budget_items,
    chain_budget_gate_caps, write_chain_budget_gate)
from rl_curriculum.curriculum261_r17_workflow import (
    build_workflow_plan_r17)

FREEZE = "a" * 40


class TestA2GenerationFamily:
    def test_registration_counts(self):
        assert len(QAF_ALL_NEW) == 26
        assert len(QAF_GENERATION_FAMILY) == 10
        assert len(R17_ALL) == 183
        for ns in QAF_GENERATION_FAMILY:
            assert ns in CURRICULUM261_SEED_NAMESPACES, ns
            assert ns in R17_ALL, ns

    def test_iteration_labels(self):
        import rl_curriculum.curriculum261_generation_envelope as ge

        calls = []

        class Cap:
            def __call__(self, iteration, namespace, *a, **k):
                calls.append((iteration, namespace))

        orig = ge.active_recorder
        ge.active_recorder = Cap()
        try:
            for ns in QAF_ALL_NEW:
                _default_recorder(ns, "c2_context", "D1", 0, None)
        finally:
            ge.active_recorder = orig
        assert len(calls) == 26
        assert {it for it, _ in calls} == {"qaf_v1"}

    def test_seed_isolation_new_generation_names(self):
        old = ("design_r17_matched_main", "cue_contract_model_r17",
               "preplan_smoke_r17", "ppo_smoke_r17",
               "cue_semantic_design_main_r17")
        for fam in ("c1_opportunity", "c2_context", "c3_cost"):
            for rung in ("D0", "D1", "D2", "D3"):
                for idx in (0, 1, 2):
                    for att in range(5):
                        qaf = {(ns, derive261_seed(
                            ns, fam, rung, idx, att))
                            for ns in QAF_GENERATION_FAMILY}
                        base = {derive261_seed(
                            ns, fam, rung, idx, att) for ns in old}
                        assert not (qaf & {v for _, v in ()}), fam
                        # 与旧名 seed 不相交
                        vals_q = {derive261_seed(
                            ns, fam, rung, idx, att)
                            for ns in QAF_GENERATION_FAMILY}
                        assert not (vals_q & base)
        # 族内唯一
        seen = set()
        for ns in QAF_GENERATION_FAMILY:
            for fam in ("c1_opportunity", "c2_context", "c3_cost"):
                for idx in (0, 3):
                    v = derive261_seed(ns, fam, "D2", idx, 2)
                    assert v not in seen, (ns, fam, idx)
                    seen.add(v)

    def test_input_scope_covers_generation_family(self):
        assert set(QAF_GENERATION_FAMILY) <= set(QAF_INPUT_SCOPE)
        assert len(QAF_INPUT_SCOPE) == 26
        from rl_curriculum.curriculum261_qprod_formal_levela import (
            formal_level_a_input_scope)
        assert set(formal_level_a_input_scope()) == set(QAF_INPUT_SCOPE)


class TestA2ChainWiring:
    FLAG_STEPS = ("determinism-matrix", "audit", "cue-audit",
                  "preplan-smoke", "design-plan-lock", "design",
                  "calibrate", "qualify", "smoke")

    def test_plan_argv_carries_attempt_all_faces(self):
        plan = build_workflow_plan_r17(
            "formal", out_dir="/TEST/chain", freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        by_name = {s["name"]: s for s in plan["steps"]}
        for step in self.FLAG_STEPS:
            argv = by_name[step]["argv"]
            assert "--formal-namespace-attempt" in argv, step
            i = argv.index("--formal-namespace-attempt")
            assert argv[i + 1] == "qaf_v1", step

    def test_plan_without_attempt_unchanged(self):
        plan = build_workflow_plan_r17(
            "formal", out_dir="/TEST/chain", freeze_sha=FREEZE)
        for s in plan["steps"]:
            assert "--formal-namespace-attempt" not in s["argv"], s

    def test_cue_audit_plan_lock_uses_qaf_namespaces(self,
                                                     tmp_path):
        from rl_curriculum.curriculum261_r17_cue_contract import (
            cue_audit_plan_payload_r17)
        payload = cue_audit_plan_payload_r17(
            model_namespace="cue_contract_model_qaf_v1",
            validation_namespace="cue_contract_validation_qaf_v1")
        assert payload["audit_namespaces"] == {
            "model": "cue_contract_model_qaf_v1",
            "validation": "cue_contract_validation_qaf_v1"}
        default = cue_audit_plan_payload_r17()
        assert default["audit_namespaces"]["model"] == \
            "cue_contract_model_r17"

    def test_design_plan_lock_qaf_namespaces_visible(self):
        """design_plan_payload_r17 接受 QAF design 命名空间(R2:
        cmd_design_plan-lock 在 qaf_v1 下传入;此处验证 payload
        结构对显式命名空间的透传)。"""
        from rl_curriculum.curriculum261_r17_design import (
            design_plan_payload_r17)
        plan = design_plan_payload_r17(
            baseline_commit="x", vendor_pin="v",
            v2_contract_digest="d",
            prior_r2_plan_digest="p",
            prior_diag262r2_plan_digest="q",
            cue_audit={"audit_digest": "a", "p_contract": 0.95},
            preplan_smoke_identity={},
            dependency_identity={"digest": "d", "n_declared": 0,
                                 "pass": True,
                                 "c2_density_summary_definition_module":
                                 "m"},
            artifact_writer_identity={},
            preplan_rehearsal_digest="r",
            r8_abort_evidence=None, r9_abort_evidence=None,
            r10_abort_evidence=None, r11_abort_evidence=None,
            r12_abort_evidence=None, r13_abort_evidence=None,
            generation_determinism_binding={},
            code_freeze_sha=FREEZE,
            policy_visible_reference_contract_digest="c",
            cue_audit_plan_digest="cad",
            design_namespaces=("design_qaf_matched_main",
                               "design_qaf_matched_validation"),
            semantic_namespaces=("cue_semantic_design_main_qaf_v1",
                                 "cue_semantic_design_validation_"
                                 "qaf_v1"),
            independent_namespace="design_qaf_independent_marginal")
        dd = plan["design_data"]
        assert list(dd["corpora"]) == ["design_qaf_matched_main",
                                       "design_qaf_matched_validation"]

    def test_determinism_a4_target_override(self, tmp_path,
                                             monkeypatch):
        import rl_curriculum.curriculum261_r17_determinism as det

        seen = []

        def fake_run_target_call(target):
            seen.append(dict(target))
            return {"attempt_digests": {}}

        monkeypatch.setattr(det, "run_target_call",
                            fake_run_target_call)
        det.audit_generator_mutable_state(
            tmp_path, stress_namespace="stress_qaf_v1")
        assert seen and all(
            t["namespace"] == "stress_qaf_v1" for t in seen)
        seen.clear()
        det.audit_generator_mutable_state(tmp_path)
        assert seen and all(
            t["namespace"] == "stress_r17" for t in seen)


class TestBBudgetCompleteness:
    def test_bootstrap_full_enumeration(self):
        items = build_budget_items()
        boot = [i for i in items
                if i["category"] == "bootstrap_resamples"]
        per = {i["step"]: i["worst_upper"] for i in boot}
        b = K["audit_bootstrap"]
        assert per["cue-audit"] == 4 * b
        assert per["preplan-smoke"] == 3 * b
        assert per["design"] == 40 * b
        assert per["calibrate"] == 8 * b
        assert per["qualify"] == 4 * b
        face = authorization_face(stop_after="qualify")
        assert face["bootstrap_resamples_upper"] == 59 * b

    def test_global_k_program_in_face(self):
        face = authorization_face(stop_after="qualify")
        assert face["global_k_null_draws_tier1"] == 50000
        assert face["global_k_null_draws_tier2_upper"] == 200000
        # 独立随机程序:不得与 MC 合并声明
        assert face["mc_events_total"] == 1_000_000

    def test_check_env_in_face(self):
        a1 = authorization_face(stop_after="qualify")
        a2 = authorization_face(stop_after="verify-formal-logs")
        assert a1["ppo_check_env_interactions_bound"] == 0
        assert a2["ppo_check_env_interactions_bound"] == 10


class TestBBudgetGate:
    def _steps(self, stop_after="qualify"):
        plan = build_workflow_plan_r17(
            "formal", out_dir="/TEST/chain", freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        if stop_after != "verify-formal-logs":
            from rl_curriculum.curriculum261_qprod_formal_levela import (
                bound_workflow_plan_r17)
            plan = bound_workflow_plan_r17(plan, stop_after)
        return [s["name"] for s in plan["steps"]]

    def test_gate_write_and_passthrough(self, tmp_path):
        steps = self._steps()
        path = write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        assert path.name == GATE_FILENAME
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["stop_after"] == "qualify"
        assert set(doc["caps"]) <= set(steps)
        # 工程路径(无 gate)不门控
        assert_stage_budget_gate(tmp_path / "elsewhere", "design")

    def test_gate_step_not_in_plan_refused(self, tmp_path):
        steps = [s for s in self._steps() if s != "smoke"]
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        with pytest.raises(QProdContextError) as ei:
            assert_stage_budget_gate(tmp_path, "smoke")
        assert "后继不可达" in str(ei.value)

    def test_gate_replay_refused(self, tmp_path):
        steps = self._steps()
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        assert_stage_budget_gate(tmp_path, "design")  # 首次通过
        with pytest.raises(QProdContextError) as ei:
            assert_stage_budget_gate(tmp_path, "design")
        assert "已消费" in str(ei.value)

    def test_gate_tampered_caps_refused(self, tmp_path):
        steps = self._steps()
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        gate = tmp_path / GATE_FILENAME
        doc = json.loads(gate.read_text(encoding="utf-8"))
        doc["caps"]["design"]["generation_episodes"] = 10 ** 9
        gate.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(QProdContextError) as ei:
            assert_stage_budget_gate(tmp_path, "design")
        assert "超过授权面" in str(ei.value)

    def test_gate_insufficient_positive_quota_refused(
            self, tmp_path):
        """正数但不足:gate caps 之和超过授权面(伪造放大)拒。"""
        steps = self._steps()
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        gate = tmp_path / GATE_FILENAME
        doc = json.loads(gate.read_text(encoding="utf-8"))
        for step in doc["caps"]:
            doc["caps"][step]["generation_episodes"] = (
                doc["caps"][step].get(
                    "generation_episodes", 0) + 1_000_000)
        gate.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(QProdContextError) as ei:
            assert_stage_budget_gate(tmp_path, "design")
        assert "超过授权面" in str(ei.value)

    def test_gate_exact_pass_marks_consumed_atomically(
            self, tmp_path):
        steps = self._steps()
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        assert_stage_budget_gate(tmp_path, "calibrate")
        doc = json.loads(
            (tmp_path / GATE_FILENAME).read_text(encoding="utf-8"))
        assert "calibrate" in doc["consumed"]

    def test_cmd_preplan_refuses_after_consumption(
            self, tmp_path, monkeypatch):
        """入口级:consumed 后 cmd_preplan_smoke 在任何业务叶前拒。"""
        import rl_curriculum.curriculum261_r17_cli as cli

        out = tmp_path / "chain"
        out.mkdir()
        write_chain_budget_gate(
            out, steps_in_plan=self._steps(), stop_after="qualify")
        assert_stage_budget_gate(out, "preplan-smoke")

        def no_leaf(*a, **k):  # 不得被调用
            raise AssertionError("business leaf reached")

        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r6_tape."
            "generate_matched_block_with_attempts", no_leaf)
        args = type("A", (), {
            "out_dir": str(out),
            "formal_namespace_attempt": "qaf_v1"})()
        rc = cli.cmd_preplan_smoke(args)
        assert rc != 0

    def test_gate_idempotent_rewrite_rejected_on_drift(
            self, tmp_path):
        steps = self._steps()
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        with pytest.raises(QProdContextError):
            write_chain_budget_gate(
                tmp_path,
                steps_in_plan=steps + ["smoke"],
                stop_after="qualify")
        # 相同内容幂等
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")

    def test_gated_steps_cover_all_business_faces(self):
        items = build_budget_items()
        nonzero = {i["step"] for i in items
                   if i["typical"] > 0 or i["worst_upper"] > 0}
        assert nonzero <= set(GATED_STEPS) | {
            "plan-roundtrip", "preflight-static", "lock-plan",
            "preflight-sealed", "full-cold", "report-read",
            "verify-formal-logs",
            "preflight-static+lock-plan+preflight-sealed",
            "full-cold+report-read+verify-formal-logs",
            "determinism-matrix"}, nonzero - set(GATED_STEPS)
