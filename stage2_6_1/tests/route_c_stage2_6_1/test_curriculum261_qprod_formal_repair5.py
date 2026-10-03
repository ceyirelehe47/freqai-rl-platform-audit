# -*- coding: utf-8 -*-
"""FLP v1 修复轮 R3(ChatGPT R2 复审 7abe9262 FAIL 三工作面)。

A-1 A1 授权语义统一(内嵌 preflight-static PPO 自检 smoke 显式
    入授权面;不再宣称「PPO 面恒 0」);
A-2 正式绑定下静态预检自检根隔离(engineering_probe_scope 成对
    换绑;正式守卫零改动;正式根零接触);
B-1 A2 chain-run 预算门接线 + 正式上下文缺门 fail closed;
B-2 gate 分项数值与冻结授权派生值逐项精确一致;
C   seal 可信完整终态(load_terminal_seal)+ 原子发布。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rl_curriculum.curriculum261_qprod_context import (  # noqa: E402
    QProdContextError,
)
from rl_curriculum.curriculum261_qprod_formal_budget import (  # noqa: E402
    GATE_FILENAME, assert_stage_budget_gate,
    authorization_face, chain_budget_gate_caps,
    write_chain_budget_gate,
)
from rl_curriculum.curriculum261_qprod_formal_levela import (  # noqa: E402
    build_formal_level_a_plan,
)
from rl_curriculum.curriculum261_r17_workflow import (  # noqa: E402
    build_workflow_plan_r17,
)

FREEZE = "f" * 40
CODE_ID = {"modules_sha256": {"curriculum261_api.py": "0" * 64}}


def _steps(stop_after="qualify"):
    plan = build_workflow_plan_r17(
        "formal", out_dir="/TEST/chain", freeze_sha=FREEZE,
        formal_attempt="qaf_v1")
    if stop_after != "verify-formal-logs":
        from rl_curriculum.curriculum261_qprod_formal_levela import (
            bound_workflow_plan_r17,
        )
        plan = bound_workflow_plan_r17(plan, stop_after)
    return [s["name"] for s in plan["steps"]]


# --------------------------------------------------------------- A-1
class TestA1AuthorizationSemantics:
    def test_a1_embedded_smoke_declared_and_authorized(self):
        plan = build_formal_level_a_plan(
            code_freeze_sha=FREEZE, code_identity=CODE_ID,
            authorized_stop_after="qualify",
            model_update_authorized=False)
        emb = plan["run_scope"]["embedded_preflight_smoke"]
        assert emb["authorized"] is True
        assert emb["step"] == "preflight-static"
        assert emb["ppo"] == {
            "learn_calls": 1, "rollout_env_steps": 256,
            "optimizer_steps_upper": 40,
            "validation_env_steps_upper": 50,
            "check_env_interactions_upper": 10,
            "model_save_load_pairs": 1,
        }
        # A1:第 14 步资格后验收 smoke 未授权
        assert plan["rules"]["post_qualification_smoke_authorized"] \
            is False
        assert "PPO 面恒 0 由有界排程" not in \
            plan["rules"]["smoke_policy"]
        assert "不再宣称" in plan["rules"]["smoke_policy"]
        # 授权面包含内嵌 smoke 的 PPO 计量(与 face 一致)
        face = authorization_face(stop_after="qualify")
        assert face["ppo_learn_calls"] == emb["ppo"]["learn_calls"]
        assert face["ppo_rollout_env_steps"] \
            == emb["ppo"]["rollout_env_steps"]

    def test_a2_post_qualification_smoke_authorized(self):
        plan = build_formal_level_a_plan(
            code_freeze_sha=FREEZE, code_identity=CODE_ID,
            authorized_stop_after="verify-formal-logs",
            model_update_authorized=True)
        assert plan["rules"]["post_qualification_smoke_authorized"] \
            is True
        assert plan["run_scope"]["embedded_preflight_smoke"][
            "authorized"] is True

    def test_inconsistent_flags_still_refused(self):
        with pytest.raises(QProdContextError):
            build_formal_level_a_plan(
                code_freeze_sha=FREEZE, code_identity=CODE_ID,
                authorized_stop_after="qualify",
                model_update_authorized=True)
        with pytest.raises(QProdContextError):
            build_formal_level_a_plan(
                code_freeze_sha=FREEZE, code_identity=CODE_ID,
                authorized_stop_after="verify-formal-logs",
                model_update_authorized=False)


# --------------------------------------------------------------- A-2
class TestA2EngineeringProbeScope:
    def test_scope_pairs_binding_and_restores(self, tmp_path,
                                              monkeypatch):
        import rl_curriculum.curriculum261_r17_execgov as gov

        formal_root = tmp_path / "formal_state"
        formal_root.mkdir()
        probe_root = tmp_path / "probe_state"
        probe_root.mkdir()
        monkeypatch.setattr(gov, "R17_DEPLOYED_STATE_ROOT",
                            str(formal_root))
        monkeypatch.delenv("CURRICULUM261_R17_STATE_ROOT",
                           raising=False)
        with gov.engineering_probe_scope(probe_root):
            # 域内:绑定与 state root 成对指向 probe 根
            assert gov.R17_DEPLOYED_STATE_ROOT == str(probe_root)
            assert os.environ["CURRICULUM261_R17_STATE_ROOT"] \
                == str(probe_root)
            probe = gov.R17ChainSession.acquire(
                binding={"probe": "r3-test"})
            probe.release()
        # 域外:绑定恢复;probe 根会话已释放
        assert gov.R17_DEPLOYED_STATE_ROOT == str(formal_root)
        # 正式根零接触(probe 会话的 journal/lock 都在 probe 根)
        assert list(formal_root.iterdir()) == []

    def test_scope_rejects_formal_root_and_nesting(
            self, tmp_path, monkeypatch):
        import rl_curriculum.curriculum261_r17_execgov as gov

        formal_root = tmp_path / "formal"
        formal_root.mkdir()
        monkeypatch.setattr(gov, "R17_DEPLOYED_STATE_ROOT",
                            str(formal_root))
        with pytest.raises(gov.R17OwnershipError):
            with gov.engineering_probe_scope(formal_root):
                pass
        probe_root = tmp_path / "p1"
        probe_root.mkdir()
        with gov.engineering_probe_scope(probe_root):
            with pytest.raises(gov.R17OwnershipError):
                with gov.engineering_probe_scope(tmp_path / "p2"):
                    pass

    def test_scope_non_probe_binding_refused(self, tmp_path,
                                             monkeypatch):
        import rl_curriculum.curriculum261_r17_execgov as gov

        probe_root = tmp_path / "probe"
        probe_root.mkdir()
        monkeypatch.setattr(gov, "R17_DEPLOYED_STATE_ROOT",
                            str(tmp_path / "formal"))
        with gov.engineering_probe_scope(probe_root):
            with pytest.raises(gov.R17OwnershipError):
                gov.R17ChainSession.acquire(
                    binding={"mode": "formal"})  # 无 probe 标记

    def test_preflight_static_selfcheck_passes_under_formal_binding(
            self, tmp_path, monkeypatch):
        """真实 run_prelock_static_preflight_r17(昂贵叶替身)在
        正式部署绑定在场时自检可完成——旧实现此处必然
        R17OwnershipError(A-2 反例),修复后隔离域内真实
        acquire/journal/exposure 机制原样运行。"""
        import rl_curriculum.curriculum261_r17_execgov as gov
        import rl_curriculum.curriculum261_r17_preflight as pf

        formal_root = tmp_path / "formal_state"
        formal_root.mkdir()
        monkeypatch.setattr(gov, "R17_DEPLOYED_STATE_ROOT",
                            str(formal_root))
        monkeypatch.delenv("CURRICULUM261_R17_STATE_ROOT",
                           raising=False)
        import rl_curriculum.curriculum261_r17_smoke as smoke_mod
        monkeypatch.setattr(
            smoke_mod, "run_ppo_smoke_r17",
            lambda **kw: {"pass": True, "checks": {
                "observation_space_unbounded": True}})
        monkeypatch.setattr(
            pf, "_matched_generator_probe_r17",
            lambda **kw: True)
        out = pf.run_prelock_static_preflight_r17(
            tmp_path / "pfout", vendor_pin="0" * 64,
            smoke_namespace="ppo_smoke_qaf_v1")
        assert out["checks"]["marker_atomic_exclusive"] is True
        assert out["checks"]["concurrent_final_lock_rejected"] is True
        # 正式根零接触
        assert list(formal_root.iterdir()) == []


# --------------------------------------------------------------- B-1
class TestB1ChainRunGateWiring:
    def test_missing_gate_formal_context_fail_closed(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                           "/TEST/formal-state")
        with pytest.raises(QProdContextError) as ei:
            assert_stage_budget_gate(tmp_path, "design")
        assert "fail closed" in str(ei.value)
        monkeypatch.delenv("CURRICULUM261_R17_DEPLOYED_STATE_ROOT")
        # 工程上下文(无部署绑定)保持既有不门控语义
        assert_stage_budget_gate(tmp_path, "design") is None

    def test_chain_run_formal_writes_gate_before_executor(
            self, tmp_path, monkeypatch):
        """真实 cmd_chain_run formal 分支:admission/session/
        executor 边界替身,plan 构建/gate 写入为原函数——执行器
        派发时 gate 必须已在场(A2 与 A1 同一预算门义务)。"""
        import rl_curriculum.curriculum261_r17_cli as cli

        observed = {}

        class _Session:
            def release(self, summary=""):
                pass

            def record_iteration_aborted(self, reason=""):
                pass

        def _fake_execute(plan, *, session=None, log_dir=None):
            gate = Path(plan["out_dir"]) / GATE_FILENAME \
                if isinstance(plan, dict) else None
            observed["gate_at_dispatch"] = bool(
                gate and gate.is_file())
            observed["steps"] = [s["name"] for s in plan["steps"]]
            return {"ok": True, "failed_step": None,
                    "failure_reason": ""}

        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r17_admission."
            "enforce_formal_admission", lambda **kw: None)
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r17_execgov."
            "R17ChainSession.acquire",
            classmethod(lambda cls, binding: _Session()))
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r17_workflow."
            "execute_workflow_chain_r17", _fake_execute)
        monkeypatch.setattr(cli, "_storage_used_gb", lambda: 0.0)
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                           str(tmp_path / "state"))

        import argparse as _ap

        args = _ap.Namespace(
            out_dir=str(tmp_path / "chain"), rehearsal=False,
            freeze_sha=FREEZE,
            formal_namespace_attempt="qaf_v1")
        rc = cli.cmd_chain_run(args)
        assert rc == 0
        assert observed["gate_at_dispatch"] is True
        gate_doc = json.loads(
            (tmp_path / "chain" / GATE_FILENAME).read_text(
                encoding="utf-8"))
        assert gate_doc["stop_after"] == "verify-formal-logs"
        # gate caps 与冻结预算项派生值一致(B-2 同口径)
        assert gate_doc["caps"] == chain_budget_gate_caps(
            observed["steps"])


# --------------------------------------------------------------- B-2
class TestB2ExactCapsControls:
    def _gate(self, tmp_path):
        steps = _steps()
        write_chain_budget_gate(
            tmp_path, steps_in_plan=steps, stop_after="qualify")
        return steps

    @staticmethod
    def _mutate(tmp_path, step, key, value):
        path = tmp_path / GATE_FILENAME
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["caps"][step][key] = value
        path.write_text(json.dumps(doc), encoding="utf-8")

    def test_correct_caps_pass(self, tmp_path):
        self._gate(tmp_path)
        assert_stage_budget_gate(tmp_path, "design")

    def test_positive_but_insufficient_refused(self, tmp_path):
        self._gate(tmp_path)
        # 正数但低于该步真实需求(1 < design 所需)
        self._mutate(tmp_path, "design", "generation_episodes", 1)
        with pytest.raises(QProdContextError) as ei:
            assert_stage_budget_gate(tmp_path, "design")
        assert "逐项精确" in str(ei.value)

    def test_bootstrap_positive_insufficient_refused(self, tmp_path):
        self._gate(tmp_path)
        self._mutate(tmp_path, "cue-audit", "bootstrap_resamples", 1)
        with pytest.raises(QProdContextError):
            assert_stage_budget_gate(tmp_path, "cue-audit")

    def test_zero_optimizer_refused(self, tmp_path):
        self._gate(tmp_path)
        for st in ("preflight-static",):
            if GATE_FILENAME and st:
                pass
        steps = _steps()
        if "preflight-static" not in json.loads(
                (tmp_path / GATE_FILENAME).read_text(
                    encoding="utf-8"))["caps"]:
            pytest.skip("preflight-static 不在本停止边界")
        self._mutate(tmp_path, "preflight-static",
                     "ppo_optimizer_steps_upper", 0)
        with pytest.raises(QProdContextError):
            assert_stage_budget_gate(tmp_path, "preflight-static")

    def test_bootstrap_amplified_refused(self, tmp_path):
        self._gate(tmp_path)
        self._mutate(tmp_path, "cue-audit", "bootstrap_resamples",
                     10**12)
        with pytest.raises(QProdContextError):
            assert_stage_budget_gate(tmp_path, "cue-audit")

    def test_category_drift_refused(self, tmp_path):
        self._gate(tmp_path)
        path = tmp_path / GATE_FILENAME
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["caps"]["design"]["bogus_category"] = 5
        path.write_text(json.dumps(doc), encoding="utf-8")
        with pytest.raises(QProdContextError):
            assert_stage_budget_gate(tmp_path, "design")


# --------------------------------------------------------------- C
def _valid_seal(coordinate_id="c01", plan_digest="qbpl-" + "a" * 64):
    return {
        "format": "cur261-qprod-coordinate-seal-v1",
        "coordinate_id": coordinate_id,
        "research_plan_digest": plan_digest,
        "coordinate_audit_plan_digest": "qcap-" + "b" * 64,
        "audit_digest": "sha256-" + "c" * 64,
        "members_sha256": {"cue_contract_audit.json": "d" * 64},
        "summary": {"audit_pass": False},
        "generation": {},
    }


class TestCSealTerminalEvidence:
    def _write(self, d, obj):
        d.mkdir(parents=True, exist_ok=True)
        (d / "qprod_coordinate_seal.json").write_text(
            obj if isinstance(obj, str) else json.dumps(obj),
            encoding="utf-8")

    def test_valid_seal_is_terminal(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        self._write(tmp_path, _valid_seal())
        assert load_terminal_seal(
            tmp_path, coordinate_id="c01",
            research_plan_digest="qbpl-" + "a" * 64) is not None

    @pytest.mark.parametrize("content", ["", '{"format":', "{}",
                                         "not json"])
    def test_empty_truncated_invalid(self, tmp_path, content):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        self._write(tmp_path, content)
        assert load_terminal_seal(tmp_path, coordinate_id="c01") \
            is None

    def test_wrong_binding_invalid(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        self._write(tmp_path, _valid_seal())
        assert load_terminal_seal(
            tmp_path, coordinate_id="c02") is None
        assert load_terminal_seal(
            tmp_path, research_plan_digest="qbpl-" + "e" * 64) is None

    def _started_ledger(self, tmp_path, started=("c01",)):
        bp = tmp_path / "qprod_native_budget.json"
        bp.write_text(json.dumps({
            "max_runs": 11, "consumed_runs": 0,
            "started": {c: "2026-10-03T00:00:00Z"
                        for c in started}}), encoding="utf-8")
        return bp

    def _manifest(self):
        return [{"coordinate_id": "c01",
                 "artifact_subdir": "coord_c01"}]

    @pytest.mark.parametrize("seal", ["", '{"format":'])
    def test_dangling_started_with_partial_seal_refused(
            self, tmp_path, seal):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_dangling_started,
        )
        bp = self._started_ledger(tmp_path)
        self._write(tmp_path / "coord_c01", seal)
        with pytest.raises(QProdContextError) as ei:
            assert_no_dangling_started(
                bp, tmp_path, self._manifest(),
                research_plan_digest="qbpl-" + "a" * 64)
        assert "无有效 seal" in str(ei.value)

    def test_valid_seal_negative_result_continues(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_dangling_started,
            assert_no_technical_interruption,
        )
        bp = self._started_ledger(tmp_path)
        self._write(tmp_path / "coord_c01", _valid_seal())
        assert_no_dangling_started(
            bp, tmp_path, self._manifest(),
            research_plan_digest="qbpl-" + "a" * 64)  # 不拒
        assert_no_technical_interruption(
            tmp_path, self._manifest(),
            research_plan_digest="qbpl-" + "a" * 64)

    def test_interrupted_with_empty_seal_refused(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_technical_interruption,
        )
        (tmp_path / "coord_c01").mkdir(parents=True)
        (tmp_path / "coord_c01" /
         "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        self._write(tmp_path / "coord_c01", "")
        with pytest.raises(QProdContextError) as ei:
            assert_no_technical_interruption(
                tmp_path, self._manifest(),
                research_plan_digest="qbpl-" + "a" * 64)
        assert "无有效 seal" in str(ei.value)

    def test_interrupted_with_valid_seal_continues(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_technical_interruption,
        )
        (tmp_path / "coord_c01").mkdir(parents=True)
        (tmp_path / "coord_c01" /
         "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        self._write(tmp_path / "coord_c01", _valid_seal())
        # 有效 seal 在场:interrupted 属旧标记,负结果按
        # collect_all_k 继续(与 R3 修复 C 语义一致)
        assert_no_technical_interruption(
            tmp_path, self._manifest(),
            research_plan_digest="qbpl-" + "a" * 64)

    def test_producer_publish_failure_leaves_no_visible_seal(
            self, tmp_path, monkeypatch):
        """真实封存写路径(publish_coordinate_seal)故障注入:
        replace 前崩溃 → seal 不可见(tmp 残件不是终态),
        load_terminal_seal 判 None(下一坐标被后继门拒绝)。"""
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal, publish_coordinate_seal,
        )

        real_replace = os.replace

        def _boom(a, b):
            if str(b).endswith("qprod_coordinate_seal.json"):
                raise OSError("disk died mid-publish")
            return real_replace(a, b)

        monkeypatch.setattr(os, "replace", _boom)
        d = tmp_path / "coord_c01"
        d.mkdir(parents=True)
        with pytest.raises(OSError):
            publish_coordinate_seal(d, _valid_seal())
        monkeypatch.setattr(os, "replace", real_replace)
        # 崩溃后:seal 正文不可见;tmp 残件不构成终态
        assert not (d / "qprod_coordinate_seal.json").exists()
        assert load_terminal_seal(d, coordinate_id="c01") is None
        # 对照:同一发布函数无故障时一次性可见且完整
        publish_coordinate_seal(d, _valid_seal())
        assert load_terminal_seal(
            d, coordinate_id="c01",
            research_plan_digest="qbpl-" + "a" * 64) is not None
