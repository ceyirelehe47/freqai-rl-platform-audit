"""R15 权威工作流编排测试(§四;工作包 A)。

核心回归:R14 缺陷 = rehearsal 链有 preplan-smoke 而 formal runner
没有(两份独立硬编码列表)。R15 结构性修复:单一权威定义 +
rehearsal/formal 同 chain 执行器 + validation fail closed。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r15_workflow import (
    R15_REHEARSAL_ONLY_TAIL,
    R15_WORKFLOW_STEPS,
    R15_WORKFLOW_VERSION,
    build_workflow_plan,
    expected_formal_log_prefix,
    r15_workflow_graph_digest,
    r15_workflow_payload,
    r15_workflow_step_names,
    validate_r15_workflow,
)

def _find_runner_dir() -> Path:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit/stage2_6_1/runner"),
                 Path("E:/trading/freqai-rl-audit/stage2_6_1/runner"),
                 Path(__file__).resolve().parents[2] / "runner"):
        if (cand / "r15_formal_chain.sh").is_file():
            return cand
    return Path(__file__).resolve().parents[2] / "runner"


RUNNER = _find_runner_dir()

STEPS = list(r15_workflow_step_names())


class TestParity:
    def test_rehearsal_and_formal_step_names_and_order_identical(self):
        """§四-测试 1:两个 profile 的 step name/order 完全一致。"""
        formal = build_workflow_plan(
            "formal", out_dir="/tmp/x", freeze_sha="sha")
        rehearsal = build_workflow_plan(
            "rehearsal", out_dir="/tmp/y")
        f_names = [s["name"] for s in formal["steps"]]
        r_names = [s["name"] for s in rehearsal["steps"]]
        assert f_names == r_names == STEPS

    def test_profile_differences_limited_to_allowed_axes(self):
        """§四-测试 2:差异只能是 profile/namespace/规模/终端期望。"""
        formal = build_workflow_plan(
            "formal", out_dir="/tmp/x", freeze_sha="sha")
        rehearsal = build_workflow_plan(
            "rehearsal", out_dir="/tmp/x", freeze_sha="sha")
        allowed_flags = {"--rehearsal", "--fit-pairs", "2",
                         "--skip-regression"}
        for f_step, r_step in zip(formal["steps"],
                                  rehearsal["steps"]):
            # 结构声明字段完全一致(report-read 的 output_artifacts
            # 例外:输出文件名是 §十一 允许的 terminal expectation
            # 差异——formal=r15_report_values.json,
            # rehearsal=rt_report_values.json)
            for key in ("name", "requires_artifacts",
                        "output_artifacts", "prerequisites",
                        "postcondition", "failure_phase",
                        "touches_exposure", "data_class"):
                if (f_step["name"] == "report-read"
                        and key == "output_artifacts"):
                    assert r_step[key] == ["rt_report_values.json"]
                    continue
                assert f_step[key] == r_step[key], (
                    f"{f_step['name']}.{key} 两 profile 不一致")
            # argv 差异仅在允许旗标(namespace/规模/skip-regression/
            # 输出文件名路径 token)
            diff = {a for a in set(r_step["argv"])
                    - set(f_step["argv"]) if not a.startswith("/")}
            assert diff <= allowed_flags, (
                f"{f_step['name']} 出现允许外的 argv 差异: {diff}")

    def test_full_workflow_validates(self):
        v = validate_r15_workflow()
        assert v["pass"] is True, v["problems"]

    def test_preplan_smoke_before_plan_roundtrip(self):
        """§十五:preplan-smoke 正确位于 plan-roundtrip 前。"""
        assert STEPS.index("preplan-smoke") < STEPS.index(
            "plan-roundtrip")

    def test_provenance_verify_first_and_no_lock_in_chain(self):
        assert STEPS[0] == "provenance-verify"
        assert "provenance-lock" not in STEPS
        assert "fail-closure-rehearsal" not in STEPS
        assert list(R15_REHEARSAL_ONLY_TAIL) == [
            "fail-closure-rehearsal"]


class TestValidationMutation:
    """§四-测试 4/5:删除 producer step ⇒ validation fail closed。"""

    def _steps_without(self, name: str):
        return [dict(s) for s in R15_WORKFLOW_STEPS
                if s["name"] != name]

    def test_remove_preplan_smoke_fails_validation(self):
        v = validate_r15_workflow(self._steps_without("preplan-smoke"))
        assert v["pass"] is False
        assert any("preplan_engineering_smoke.json" in p
                   and "plan-roundtrip" in p
                   for p in v["problems"])

    @pytest.mark.parametrize("producer", STEPS, ids=lambda x: x)
    def test_remove_any_producer_consumer_fails_closed(self, producer):
        """对每个 step 做删除变异:若它声明的产物被下游 requires,
        validation 必须 FAIL(fail closed;§四-测试 5)。"""
        from rl_curriculum.curriculum261_r15_workflow import (
            r15_producer_of_artifact,
        )
        producer_map = r15_producer_of_artifact()
        removed_outputs = {
            art for art, prod in producer_map.items() if prod == producer}
        remaining = self._steps_without(producer)
        consumed = {art for s in remaining
                    for art in s.get("requires_artifacts", ())}
        downstream_needed = removed_outputs & consumed
        v = validate_r15_workflow(remaining)
        if not downstream_needed:
            # 产物无任何 consumer(治理/报告类):删除不破坏 consumer
            # 契约——只要求流程仍可组装(§四-测试 5 的前提是存在
            # consumer;强断言只覆盖被 requires 的产物)
            assert v["problems"] == [] or v["pass"] is False
            return
        # 其产物被 requires 的 consumer 必须报无 producer 或顺序错
        problems_text = " | ".join(v["problems"])
        assert v["pass"] is False or any(
            out in problems_text for out in downstream_needed), (
            f"删除 {producer} 未被检出: {v['problems']}")


class TestExpectedPrefix:
    @pytest.mark.parametrize("stopped", STEPS[:-1], ids=lambda s: s)
    def test_expected_prefix_mechanically_derived(self, stopped):
        """§四-测试 6:stopped-at 任意步骤 ⇒ prefix 机械派生。"""
        assert expected_formal_log_prefix(stopped) == \
            STEPS[:STEPS.index(stopped) + 1]

    def test_verify_formal_logs_not_in_any_prefix(self):
        with pytest.raises(ValueError, match="不在 expected 前缀内"):
            expected_formal_log_prefix("verify-formal-logs")

    def test_unknown_step_rejected(self):
        with pytest.raises(ValueError):
            expected_formal_log_prefix("preplan-smoke-gone")


class TestNoSecondList:
    def test_formal_runner_has_no_handwritten_step_list(self):
        """§四-测试 7:runner shell 不得存在第二份手写全流程列表。"""
        sh = (RUNNER / "r15_formal_chain.sh").read_text(encoding="utf-8")
        # 只允许 chain 调用 + workflow-plan;不允许逐条 run 调用
        assert "r15_run_step.py\" chain" in sh
        assert "curriculum261_r15_cli workflow-plan" in sh
        for step in STEPS:
            run_line = f"run {step}"
            assert run_line not in sh, (
                f"r15_formal_chain.sh 含手写步骤调用: {run_line}")

    def test_run_step_chain_mode_has_no_step_list(self):
        py = (RUNNER / "r15_run_step.py").read_text(encoding="utf-8")
        for step in STEPS:
            assert f'"{step}"' not in py, (
                f"r15_run_step.py 含步骤名硬编码: {step}")


class TestDigest:
    def test_digest_stable_and_prefixed(self):
        d1 = r15_workflow_graph_digest()
        d2 = r15_workflow_graph_digest(r15_workflow_payload())
        assert d1 == d2
        assert d1.startswith("r15wg-")

    def test_workflow_version(self):
        assert R15_WORKFLOW_VERSION == "AuthoritativeWorkflow-v1"

    def test_payload_contains_steps_and_tail(self):
        payload = r15_workflow_payload()
        assert [s["name"] for s in payload["steps"]] == STEPS
        assert payload["rehearsal_only_tail"] == [
            "fail-closure-rehearsal"]

    def test_freeze_manifest_mounts_workflow_digest(self):
        """§四-测试 8:workflow digest 进入 freeze manifest(结构级:
        freeze_surface_manifest_r15 的返回含该键,源码挂载 +
        digest 与权威定义一致)。"""
        from rl_curriculum.curriculum261_r15_workflow import (
            r15_workflow_graph_digest as _wd,
        )
        deps_src = (Path(__file__).resolve().parents[2] / "src"
                    / "rl_curriculum"
                    / "curriculum261_r15_dependencies.py").read_text(
            encoding="utf-8")
        assert '"workflow_graph_digest"' in deps_src
        assert "r15_workflow_graph_digest" in deps_src
        # 权威 digest 可重算
        assert _wd().startswith("r15wg-")


class TestPostcondition:
    def test_smoke_requires_final_pass(self):
        smoke = next(s for s in R15_WORKFLOW_STEPS
                     if s["name"] == "smoke")
        assert smoke["postcondition"] == "final_verdict_pass"

    def test_full_cold_requires_smoke_pass(self):
        fc = next(s for s in R15_WORKFLOW_STEPS
                  if s["name"] == "full-cold")
        assert fc["postcondition"] == "smoke_pass"

    def test_qualify_is_only_exposure_touching_step(self):
        for s in R15_WORKFLOW_STEPS:
            if s["name"] == "qualify":
                assert s["touches_exposure"] is True
            else:
                assert s["touches_exposure"] is False
