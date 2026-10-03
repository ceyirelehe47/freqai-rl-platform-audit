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

    def test_determinism_a4_target_override(self, tmp_path):
        """子进程隔离:真实 audit_generator_mutable_state 的完整
        A4 序列会加载 torch/MLP 并留驻线程池,污染同进程后续
        supervisor 掩码面测试(r21 全收集实测 rc=7 干扰);本测试
        在子进程内以真实函数+真实命名空间覆盖运行,父进程只断言
        观测结果。"""
        import subprocess
        import sys as _sys

        child = tmp_path / "a4_probe.py"
        out_dir = tmp_path / "a4out"
        child.write_text(
            "import json, sys\n"
            "sys.path.insert(0, 'src')\n"
            "import rl_curriculum.curriculum261_r17_determinism "
            "as det\n"
            "seen = []\n"
            "orig = det.run_target_call\n"
            "def fake(target):\n"
            "    seen.append(dict(target))\n"
            "    return {'attempt_digests': {}}\n"
            "det.run_target_call = fake\n"
            "det.audit_generator_mutable_state(\n"
            "    sys.argv[1], stress_namespace=sys.argv[2] or None)\n"
            "det.run_target_call = orig\n"
            "print(json.dumps([t.get('namespace') for t in seen]))\n",
            encoding="utf-8")
        r = subprocess.run(
            [_sys.executable, str(child), str(out_dir),
             "stress_qaf_v1"],
            capture_output=True, text=True, timeout=600, cwd=str(
                Path(__file__).resolve().parents[2]))
        assert r.returncode == 0, r.stderr[-800:]
        ns_list = json.loads(r.stdout.strip().splitlines()[-1])
        assert ns_list and all(n == "stress_qaf_v1" for n in ns_list)
        out_dir2 = tmp_path / "a4out2"
        r2 = subprocess.run(
            [_sys.executable, str(child), str(out_dir2), ""],
            capture_output=True, text=True, timeout=600, cwd=str(
                Path(__file__).resolve().parents[2]))
        assert r2.returncode == 0, r2.stderr[-800:]
        ns_list2 = json.loads(r2.stdout.strip().splitlines()[-1])
        assert ns_list2 and all(n == "stress_r17" for n in ns_list2)


class TestBBudgetCompleteness:
    def test_bootstrap_full_enumeration(self):
        items = build_budget_items()
        boot = [i for i in items
                if i["category"] == "bootstrap_resamples"]
        per = {i["step"]: i["worst_upper"] for i in boot}
        b = K["audit_bootstrap"]
        # counter 探针实测口径(reviewer gate1_r6 B-1):
        # candidate_cue_semantics=16 次/调用(rung4×side2×2 统计)、
        # independent_cue_semantics=18、preflight matched probe=34
        assert per["cue-audit"] == 4 * b
        assert per["preplan-smoke"] == 3 * b
        assert per["design"] == 226 * b
        assert per["calibrate"] == 72 * b
        assert per["qualify"] == 36 * b
        assert per["preflight-static"] == 34 * b
        face = authorization_face(stop_after="qualify")
        assert face["bootstrap_resamples_upper"] == 375 * b

    def test_global_k_program_in_face(self):
        face = authorization_face(stop_after="qualify")
        assert face["global_k_null_draws_tier1"] == 50000
        assert face["global_k_null_draws_tier2_upper"] == 200000
        # 独立随机程序:不得与 MC 合并声明
        assert face["mc_events_total"] == 1_000_000

    def test_check_env_in_face(self):
        a1 = authorization_face(stop_after="qualify")
        a2 = authorization_face(stop_after="verify-formal-logs")
        # A1 含 preflight-static 内嵌 smoke(×1);A2 = 内嵌+step-14
        assert a1["ppo_check_env_interactions_bound"] == 10
        assert a2["ppo_check_env_interactions_bound"] == 20

    def test_preflight_static_honest_in_a1_face(self):
        """B-2:preflight-static 内嵌 256 步 PPO plumbing smoke
        如实入面(A1 不再声称 PPO 恒 0;R12 起冻结存在)。"""
        a1 = authorization_face(stop_after="qualify")
        a2 = authorization_face(stop_after="verify-formal-logs")
        assert a1["ppo_learn_calls"] == 1
        assert a1["ppo_rollout_env_steps"] == 256
        assert a1["ppo_optimizer_steps_upper"] == 40
        assert a1["ppo_validation_env_steps"] == 50
        assert a1["model_save_load_pairs"] == 1
        assert a2["ppo_learn_calls"] == 2
        assert a2["ppo_rollout_env_steps"] == 512
        assert a2["ppo_optimizer_steps_upper"] == 80
        # A1/A2 面含 preflight-static episodes(+162 typ)
        assert a1["generation_episodes_typical"] == 28636 + 162
        assert a2["generation_episodes_typical"] == 28782 + 162
        assert a1["authorization_cap_generation_episodes"] \
            == 112804 + 226
        assert a2["authorization_cap_generation_episodes"] \
            == 112950 + 226
        items = build_budget_items()
        pf = [i for i in items if i["step"] == "preflight-static"]
        assert {i["category"] for i in pf} >= {
            "generation_episodes", "v2_preprocessor_fits",
            "ppo_learn_calls", "ppo_rollout_env_steps",
            "ppo_optimizer_steps_upper", "ppo_validation_env_steps",
            "ppo_check_env_interactions_bound", "model_save_load",
            "bootstrap_resamples"}
        eps = next(i for i in pf if i["category"] ==
                   "generation_episodes")
        assert eps["typical"] == 146 + 16
        assert eps["worst_upper"] == 146 + 80


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
            "plan-roundtrip", "lock-plan", "preflight-sealed",
            "full-cold", "report-read", "verify-formal-logs",
            "lock-plan+preflight-sealed",
            "full-cold+report-read+verify-formal-logs",
            "determinism-matrix"}, nonzero - set(GATED_STEPS)
