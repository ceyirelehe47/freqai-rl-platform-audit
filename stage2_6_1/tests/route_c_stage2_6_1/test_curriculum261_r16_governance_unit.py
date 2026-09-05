# -*- coding: utf-8 -*-
"""R16 namespace/守卫/workflow/fail-closure 单元测试(§7/§8/§9/§10)。

(原 test_curriculum261_r16_governance.py 的单元部分;因后续分支
上下文测试文件同名覆盖而以本名重建,内容与最初版本一致。)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_R16_FORMAL_NAMESPACES,
    GeneratorError,
    derive261_seed,
)


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    root = tmp_path / "r16_state"
    root.mkdir()
    monkeypatch.setenv("CURRICULUM261_R16_STATE_ROOT", str(root))
    monkeypatch.delenv("CURRICULUM261_R16_EXECUTOR_TOKEN", raising=False)
    return root


class TestNamespaceIsolation:
    def test_name_isolation_static(self):
        from rl_curriculum.curriculum261_r16_namespaces import (
            verify_r16_namespace_name_isolation,
        )

        r = verify_r16_namespace_name_isolation()
        assert r["pass"], r
        assert not r["historical_iteration_overlap"]

    def test_no_historical_iteration_suffix(self):
        """正式四件套只以 _r16 结尾(不携带任何历史迭代后缀)。"""
        for ns in CURRICULUM261_R16_FORMAL_NAMESPACES:
            assert ns.endswith("_r16")
            for num in range(0, 16):
                assert not ns.endswith(f"_r{num}")

    def test_numeric_collision_requires_grant(self, state_root):
        """§7.2:数值碰撞抽检必须在授权窗口内;无授权即拒绝。"""
        from rl_curriculum.curriculum261_r16_namespaces import (
            verify_r16_namespace_collision_within_grant,
        )

        r = verify_r16_namespace_collision_within_grant()
        assert not r["pass"]
        assert all(not c.get("authorized_derivation")
                   for c in r["checked"])

    def test_r16_namespaces_not_colliding_with_r15(self):
        """R16 与 R15 namespace 的 seed 数值不相交(哈希域隔离)。"""
        seeds_r16 = {derive261_seed("calibration_r16", "c1", "rung0",
                                    i, 0) for i in range(50)}
        seeds_r15 = {derive261_seed("calibration_r15", "c1", "rung0",
                                    i, 0) for i in range(50)}
        assert not (seeds_r16 & seeds_r15)


class TestApiGuard:
    def test_formal_namespace_rejected_without_unlock(self, state_root):
        for ns in CURRICULUM261_R16_FORMAL_NAMESPACES:
            with pytest.raises(GeneratorError, match="plan 完整锁定"):
                derive261_seed(ns, "c1", "rung0", 0, 0)

    def test_engineering_namespace_free(self, state_root):
        assert derive261_seed("calibration_r16", "c1", "rung0", 0, 0) > 0
        assert derive261_seed("rt3_qualification_r16", "c1", "rung0",
                              0, 0) > 0

    def test_unknown_namespace_rejected(self, state_root):
        with pytest.raises(GeneratorError):
            derive261_seed("qualification_r99", "c1", "rung0", 0, 0)


class TestWorkflow:
    def test_validate_passes_and_17_steps(self):
        from rl_curriculum.curriculum261_r16_workflow import (
            r16_workflow_step_names,
            validate_r16_workflow,
        )

        v = validate_r16_workflow()
        assert v["pass"], v["problems"]
        assert len(r16_workflow_step_names()) == 17
        assert r16_workflow_step_names()[0] == "provenance-verify"
        assert r16_workflow_step_names()[-1] == "verify-formal-logs"

    def test_removed_producer_fails_validation(self):
        from rl_curriculum.curriculum261_r16_workflow import (
            R16_WORKFLOW_STEPS,
            validate_r16_workflow,
        )

        # 删除 preplan-smoke(producer)⇒ plan-roundtrip 的 requires
        # 必须变成无 producer(机械保证;R14 缺陷回归)
        steps = [s for s in R16_WORKFLOW_STEPS
                 if s["name"] != "preplan-smoke"]
        v = validate_r16_workflow(steps)
        assert not v["pass"]
        assert any("无 producer" in p for p in v["problems"])

    def test_cycle_rejected(self):
        from rl_curriculum.curriculum261_r16_workflow import (
            R16_WORKFLOW_STEPS,
            validate_r16_workflow,
        )

        steps = [dict(s) for s in R16_WORKFLOW_STEPS]
        # 制造后向 prerequisite(qualify 依赖 verify-formal-logs)
        for s in steps:
            if s["name"] == "qualify":
                s["prerequisites"] = ["verify-formal-logs"]
        v = validate_r16_workflow(steps)
        assert not v["pass"]

    def test_graph_digest_stable_prefix(self):
        from rl_curriculum.curriculum261_r16_workflow import (
            r16_workflow_graph_digest,
        )

        assert r16_workflow_graph_digest().startswith("r16wg-")

    def test_plan_expansion_placeholders(self, tmp_path):
        from rl_curriculum.curriculum261_r16_workflow import (
            build_workflow_plan_r16,
        )

        plan = build_workflow_plan_r16(
            "formal", out_dir=str(tmp_path), freeze_sha="abc123")
        assert plan["profile"] == "formal"
        argv_all = [a for s in plan["steps"] for a in s["argv"]]
        assert not any("{out_dir}" in a or "{freeze_sha}" in a
                       for a in argv_all)
        # qualify 步保持 touches_exposure
        q = [s for s in plan["steps"] if s["name"] == "qualify"][0]
        assert q["touches_exposure"] is True

    def test_rehearsal_profile_only_declared_diffs(self, tmp_path):
        from rl_curriculum.curriculum261_r16_workflow import (
            build_workflow_plan_r16,
        )

        f = build_workflow_plan_r16(
            "formal", out_dir=str(tmp_path))
        r = build_workflow_plan_r16(
            "rehearsal", out_dir=str(tmp_path))
        assert ([s["name"] for s in f["steps"]]
                == [s["name"] for s in r["steps"]])
        for sf, sr in zip(f["steps"], r["steps"]):
            assert sf["cli_command"] == sr["cli_command"]
            assert sf["prerequisites"] == sr["prerequisites"]


class TestFailClosure:
    def test_bootstrap_closure_shape(self, tmp_path):
        from rl_curriculum.curriculum261_r16_fail_closure import (
            build_phase_accurate_fail_closure_r16,
        )

        c = build_phase_accurate_fail_closure_r16(
            tmp_path, failed_step="bootstrap", reason="CRLF")
        assert c["failure_phase"] == "bootstrap"
        assert c["executed_prefix"] == []
        assert c["next_step_not_executed"] == "provenance-verify"
        assert c["exposure_state"] == "not_exposed"
        # §8.4 反例回归:provenance-verify 不能写成已执行失败;
        # 全部证据 not_started
        assert all(v == "not_started"
                   for v in c["evidence_states"].values())
        assert "provenance-verify" in c["report_wording"]

    def test_qualify_subphase_from_journal(self, tmp_path, monkeypatch):
        from rl_curriculum.curriculum261_r16_execgov import (
            R16FormalSession,
        )
        from rl_curriculum.curriculum261_r16_fail_closure import (
            qualification_failure_subphase_r16,
        )

        monkeypatch.setenv("CURRICULUM261_R16_STATE_ROOT",
                           str(tmp_path / "st"))
        s = R16FormalSession.acquire(binding={"t": 1})
        phase, ok = qualification_failure_subphase_r16(tmp_path)
        assert phase == "qualification-pre-exposure" and ok
        s.record_exposure_started("d1")
        phase, ok = qualification_failure_subphase_r16(tmp_path)
        assert phase == "qualification-exposed-running" and ok
        s.commit_qualification_terminal("crashed", "d1")
        phase, ok = qualification_failure_subphase_r16(tmp_path)
        assert phase == "qualification-terminal" and ok
        s.release()

    def test_phase_accurate_evidence_states(self, tmp_path):
        from rl_curriculum.curriculum261_r16_fail_closure import (
            ABSENT_DUE_TO_FAILURE_PHASE,
            NOT_STARTED,
            PRESENT,
            build_phase_accurate_fail_closure_r16,
        )

        # design 步失败:design_plan(present)但 calibration
        # (not_started)
        (tmp_path / "r16_design_plan.json").write_text(
            "{}", encoding="utf-8")
        c = build_phase_accurate_fail_closure_r16(
            tmp_path, failed_step="design", reason="x")
        assert c["evidence_states"]["design_plan_state"] == PRESENT
        assert c["evidence_states"]["calibration_state"] == NOT_STARTED
        # calibrate 步失败:design_data present;qualification plan
        # not_started
        (tmp_path / "r16_parameter_pack.json").write_text(
            "{}", encoding="utf-8")
        c2 = build_phase_accurate_fail_closure_r16(
            tmp_path, failed_step="calibrate", reason="x")
        assert c2["evidence_states"]["design_data_state"] == PRESENT
        assert (c2["evidence_states"]["qualification_plan"]
                == NOT_STARTED)
        # qualify 步失败(pre-exposure):result absent_due_to_failure
        c3 = build_phase_accurate_fail_closure_r16(
            tmp_path, failed_step="qualify", reason="x")
        assert (c3["evidence_states"]["qualification_result"]
                == ABSENT_DUE_TO_FAILURE_PHASE)
        assert c3["exposure_state"] == "not_exposed"


class TestRtProfileContract:
    """§7.2:rehearsal 不能接受 formal namespace;formal 不能接受
    缩小 profile(在 workflow/CLI 层的结构保证)。"""

    def test_rt_profile_uses_rt3_namespaces(self):
        from rl_curriculum.curriculum261_r16_final import (
            R16_RT_FINAL_PROFILE,
        )

        for key in ("final_namespace", "fit_namespace",
                    "independent_namespace", "semantic_namespace"):
            assert R16_RT_FINAL_PROFILE[key].startswith("rt3_"), key
            assert R16_RT_FINAL_PROFILE[key].endswith("_r16")

    def test_rt_profile_smaller_than_formal(self):
        from rl_curriculum.curriculum261_r16_final import (
            R16_RT_FINAL_PROFILE,
        )

        assert R16_RT_FINAL_PROFILE["semantic_block_count"] < 160
        assert R16_RT_FINAL_PROFILE["c13_pairs_per_rung"] < 10


class TestReaderPurity:
    """§8.5/§10:终态 reader 只读;缺文件不生成。"""

    def test_reader_no_state_change(self, state_root, tmp_path):
        from rl_curriculum.curriculum261_r16_execgov import (
            R16FormalSession,
            journal_entries,
        )
        from rl_curriculum.curriculum261_r16_fail_closure import (
            build_phase_accurate_fail_closure_r16,
        )

        s = R16FormalSession.acquire(binding={"t": "reader"})
        s.record_exposure_started("d1")
        s.issue_generation_grant()
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "d1")
        s.release()
        before = journal_entries()
        # 终态后的 closure 构建是只读组装
        closure = build_phase_accurate_fail_closure_r16(
            state_root, failed_step="smoke", reason="reader test")
        after = journal_entries()
        assert before == after
        assert closure["exposure_state"] == "exposed_terminal"
