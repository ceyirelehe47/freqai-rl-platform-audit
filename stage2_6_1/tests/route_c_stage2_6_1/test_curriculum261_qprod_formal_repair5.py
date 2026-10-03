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

import hashlib
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
from _flp_seal_fixture import build_valid_coordinate  # noqa: E402

PLAN_D = "qbpl-" + "a" * 64
MODEL_NS = "cue_qprod_formal_v1_c01_model"
VALID_NS = "cue_qprod_formal_v1_c01_validation"

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
    """R4 修复 C:13 状态矩阵(ChatGPT R3 终验 §4.3 对偶)。

    正例=真实构建/发布路径的完整负结果夹具;无效状态全部
    不得构成可信终态(load_terminal_seal=None → 后继门拒绝)。
    """

    def _build(self, tmp_path, cid="c01"):
        return build_valid_coordinate(
            tmp_path, f"coord_{cid}", coordinate_id=cid,
            plan_digest=PLAN_D, model_ns=MODEL_NS,
            validation_ns=VALID_NS)

    def _valid(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        d = self._build(tmp_path)
        coord = {"coordinate_id": "c01",
                 "model_namespace": MODEL_NS,
                 "validation_namespace": VALID_NS}
        return d, load_terminal_seal(
            d, coordinate_id="c01", research_plan_digest=PLAN_D,
            coordinate=coord)

    def test_intact_negative_result_is_terminal(self, tmp_path):
        d, seal = self._valid(tmp_path)
        assert seal is not None
        assert seal["summary"]["audit_pass"] is False

    @pytest.mark.parametrize("content", ["", '{"format":', "{}",
                                         "not json"])
    def test_empty_truncated_invalid(self, tmp_path, content):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        d = self._build(tmp_path)
        (d / "qprod_coordinate_seal.json").write_text(
            content, encoding="utf-8")
        assert load_terminal_seal(
            d, coordinate_id="c01",
            research_plan_digest=PLAN_D) is None

    def test_wrong_binding_invalid(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        d = self._build(tmp_path)
        assert load_terminal_seal(
            d, coordinate_id="c02") is None
        assert load_terminal_seal(
            d, research_plan_digest="qbpl-" + "e" * 64) is None

    # ---- ChatGPT R3 §4.3 剩余八种无效状态(R4 全部拒绝) ----
    def _seal_json(self, d):
        return json.loads(
            (d / "qprod_coordinate_seal.json").read_text(
                encoding="utf-8"))

    def _write_seal(self, d, seal):
        (d / "qprod_coordinate_seal.json").write_text(
            json.dumps(seal), encoding="utf-8")

    def _none(self, d):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            load_terminal_seal,
        )
        coord = {"coordinate_id": "c01",
                 "model_namespace": MODEL_NS,
                 "validation_namespace": VALID_NS}
        return load_terminal_seal(
            d, coordinate_id="c01", research_plan_digest=PLAN_D,
            coordinate=coord)

    def test_member_deleted_invalid(self, tmp_path):
        d = self._build(tmp_path)
        (d / "cue_contract_audit.json").unlink()
        assert self._none(d) is None

    def test_trace_bytes_corrupted_invalid(self, tmp_path):
        d = self._build(tmp_path)
        with open(d / "cue_event_trace.jsonl", "ab") as fh:
            fh.write(b"corruption\n")
        assert self._none(d) is None

    def test_seal_qcap_digest_wrong_bound_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        seal["coordinate_audit_plan_digest"] = "qcap-" + "f" * 64
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_seal_audit_digest_wrong_bound_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        seal["audit_digest"] = "r15ca-" + "f" * 64
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_member_set_subset_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        seal["members_sha256"].pop("qprod_block_seed_log.jsonl")
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_member_set_extra_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        seal["members_sha256"]["extra_member.bin"] = "0" * 64
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_member_value_not_digest_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        seal["members_sha256"]["cue_event_trace.jsonl"] = "not-a-digest"
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_member_pointing_to_nonexistent_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        seal["members_sha256"]["ghost_member.json"] = (
            hashlib.sha256(b"x").hexdigest())
        # 保持集合恰好必需?否——把真成员换成幽灵名(集合仍错)
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_report_digest_recompute_mismatch_invalid(self, tmp_path):
        d = self._build(tmp_path)
        rp = json.loads(
            (d / "cue_contract_audit.json").read_text(encoding="utf-8"))
        rp["p_contract"] = 0.99  # 改动核心字段,audit_digest 不再自洽
        (d / "cue_contract_audit.json").write_text(
            json.dumps(rp), encoding="utf-8")
        # 同步 seal 成员摘要(隔离「复算不一致」这一维度)
        seal = self._seal_json(d)
        seal["members_sha256"]["cue_contract_audit.json"] = (
            hashlib.sha256(
                (d / "cue_contract_audit.json").read_bytes()).hexdigest())
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_summary_missing_invalid(self, tmp_path):
        d = self._build(tmp_path)
        seal = self._seal_json(d)
        del seal["summary"]
        self._write_seal(d, seal)
        assert self._none(d) is None

    def test_corrupted_member_plus_interrupted_invalid(self, tmp_path):
        """损坏 trace + interrupted 标记:无效 seal 不得覆盖中断。"""
        d = self._build(tmp_path)
        (d / "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        with open(d / "cue_event_trace.jsonl", "ab") as fh:
            fh.write(b"corruption\n")
        assert self._none(d) is None

    # ---- 门级行为(真实 manifest/账本形态) ----
    def _started_ledger(self, tmp_path, started=("c01",)):
        bp = tmp_path / "qprod_native_budget.json"
        bp.write_text(json.dumps({
            "max_runs": 11, "consumed_runs": 0,
            "started": {c: "2026-10-03T00:00:00Z"
                        for c in started}}), encoding="utf-8")
        return bp

    def _manifest(self):
        return [{"coordinate_id": "c01",
                 "artifact_subdir": "coord_c01",
                 "model_namespace": MODEL_NS,
                 "validation_namespace": VALID_NS}]

    @pytest.mark.parametrize("damage", ["", '{"format":'])
    def test_dangling_started_with_partial_seal_refused(
            self, tmp_path, damage):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_dangling_started,
        )
        bp = self._started_ledger(tmp_path)
        d = self._build(tmp_path)
        (d / "qprod_coordinate_seal.json").write_text(
            damage, encoding="utf-8")
        with pytest.raises(QProdContextError) as ei:
            assert_no_dangling_started(
                bp, tmp_path, self._manifest(),
                research_plan_digest=PLAN_D)
        assert "无有效 seal" in str(ei.value)

    @pytest.mark.parametrize("damage", [
        "member_deleted", "trace_corrupted", "seal_qcap_unbound",
        "seal_audit_unbound", "member_subset", "member_extra",
    ])
    def test_dangling_started_with_invalid_seal_refused(
            self, tmp_path, damage):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_dangling_started,
        )
        bp = self._started_ledger(tmp_path)
        d = self._build(tmp_path)
        if damage == "member_deleted":
            (d / "cue_contract_audit.json").unlink()
        elif damage == "trace_corrupted":
            with open(d / "cue_event_trace.jsonl", "ab") as fh:
                fh.write(b"x")
        elif damage == "seal_qcap_unbound":
            seal = self._seal_json(d)
            seal["coordinate_audit_plan_digest"] = "qcap-" + "f" * 64
            self._write_seal(d, seal)
        elif damage == "seal_audit_unbound":
            seal = self._seal_json(d)
            seal["audit_digest"] = "r15ca-" + "f" * 64
            self._write_seal(d, seal)
        elif damage == "member_subset":
            seal = self._seal_json(d)
            seal["members_sha256"].pop("qprod_block_seed_log.jsonl")
            self._write_seal(d, seal)
        elif damage == "member_extra":
            seal = self._seal_json(d)
            seal["members_sha256"]["extra.bin"] = "0" * 64
            self._write_seal(d, seal)
        with pytest.raises(QProdContextError) as ei:
            assert_no_dangling_started(
                bp, tmp_path, self._manifest(),
                research_plan_digest=PLAN_D)
        assert "无有效 seal" in str(ei.value)

    def test_valid_seal_negative_result_continues(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_dangling_started,
            assert_no_technical_interruption,
        )
        bp = self._started_ledger(tmp_path)
        self._build(tmp_path)
        assert_no_dangling_started(
            bp, tmp_path, self._manifest(),
            research_plan_digest=PLAN_D)  # 不拒(collect_all_k)
        assert_no_technical_interruption(
            tmp_path, self._manifest(),
            research_plan_digest=PLAN_D)

    def test_interrupted_with_empty_seal_refused(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_technical_interruption,
        )
        d = self._build(tmp_path)
        (d / "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        (d / "qprod_coordinate_seal.json").write_text(
            "", encoding="utf-8")
        with pytest.raises(QProdContextError) as ei:
            assert_no_technical_interruption(
                tmp_path, self._manifest(),
                research_plan_digest=PLAN_D)
        assert "无有效 seal" in str(ei.value)

    def test_interrupted_with_corrupted_members_refused(self, tmp_path):
        """interrupted + 成员损坏:无效 seal 不得覆盖中断标记。"""
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_technical_interruption,
        )
        d = self._build(tmp_path)
        (d / "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        with open(d / "cue_event_trace.jsonl", "ab") as fh:
            fh.write(b"corruption")
        with pytest.raises(QProdContextError) as ei:
            assert_no_technical_interruption(
                tmp_path, self._manifest(),
                research_plan_digest=PLAN_D)
        assert "无有效 seal" in str(ei.value)

    def test_interrupted_with_valid_seal_continues(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            assert_no_technical_interruption,
        )
        d = self._build(tmp_path)
        (d / "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        # 有效 seal 在场:interrupted 属旧标记,负结果按
        # collect_all_k 继续(与 R3 修复 C 语义一致)
        assert_no_technical_interruption(
            tmp_path, self._manifest(),
            research_plan_digest=PLAN_D)

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
            publish_coordinate_seal(d, {"format": "x"})
        monkeypatch.setattr(os, "replace", real_replace)
        # 崩溃后:seal 正文不可见;tmp 残件不构成终态
        assert not (d / "qprod_coordinate_seal.json").exists()
        assert load_terminal_seal(d, coordinate_id="c01") is None
        # 对照:同一发布函数无故障时一次性可见且完整
        d2 = self._build(tmp_path)
        assert load_terminal_seal(
            d2, coordinate_id="c01",
            research_plan_digest=PLAN_D) is not None


class TestCWiringThroughRealRunner:
    """ChatGPT R4 要求的接线反例:真实 cmd_run_coordinate →
    真实额度/后继门 → 真实 wrapper(run_coordinate_audit_locked)
    → c02 审计核心调用边界哨兵。c01 以真实构建/发布路径生成
    完整负结果夹具后施加损坏;c02 必须在核心边界前被拒
    (零核心调用、零新预占)。"""

    def test_member_deleted_blocks_next_at_core_boundary(
            self, tmp_path, monkeypatch):
        self._run_pair(tmp_path, monkeypatch, "member_deleted")

    def test_trace_corrupted_blocks_next_at_core_boundary(
            self, tmp_path, monkeypatch):
        self._run_pair(tmp_path, monkeypatch, "trace_corrupted")

    def test_intact_allows_next_to_core_boundary(
            self, tmp_path, monkeypatch):
        self._run_pair(tmp_path, monkeypatch, None)

    def _run_pair(self, tmp_path, monkeypatch, damage):
        import importlib.util
        from _flp_seal_fixture import build_valid_coordinate
        from rl_curriculum.curriculum261_qprod_coordinate import (
            QPROD_COORDINATE_SEAL_NAME,
        )
        base = Path(__file__).resolve().parents[2]
        for cand in (base / "stage2_6_1_runner", base / "runner",
                     base / "stage2_6_1" / "runner"):
            if (cand / "qprod_formal_level_b_entry.py").is_file():
                runner = cand / "qprod_formal_level_b_entry.py"
                break
        else:
            raise FileNotFoundError("runner 入口未找到")
        # 最小 formal 上下文:直接驱动 runner 模块的
        # cmd_run_coordinate 依赖 _gated_roots_and_permit;此处
        # 用与 repair.py 相同的 TEST 部署沙盒(env fixture)。
        # —— 为避免复制整套夹具,借用 repair.py 的构建器:
        import test_curriculum261_qprod_formal_repair as rp

        env = rp.TestR3EntryPairProbes()._full_b_env(
            tmp_path, mx=11, monkeypatch=monkeypatch)
        plan_digest = rp.research_plan_digest(env["payload"])

        core_calls = []

        c01 = next(c for c in env["payload"]["coordinate_manifest"]
                   if c["coordinate_id"] == "c01")

        def fake_core(ctx, live, cid, coord_dir=None, ledger_path=None):
            core_calls.append(cid)
            if cid == "c01":
                d = build_valid_coordinate(
                    Path(coord_dir).parent, Path(coord_dir).name,
                    coordinate_id=cid, plan_digest=plan_digest,
                    model_ns=c01["model_namespace"],
                    validation_ns=c01["validation_namespace"])
                return {"seal": json.loads(
                    (d / QPROD_COORDINATE_SEAL_NAME).read_text(
                        encoding="utf-8")),
                    "generation": {"episode_leaf_calls": 16}}
            raise BaseException("CORE-BOUNDARY-SENTINEL")

        spec = importlib.util.spec_from_file_location(
            "qprod_formal_level_b_entry_r4", runner)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(
            mod, "run_coordinate_audit_locked", fake_core)

        args = type("A", (), {
            "deploy_root": str(env["deploy"]),
            "code_freeze_sha": rp.FREEZE,
            "coordinate_id": "c01"})()
        rc1 = mod.cmd_run_coordinate(args)
        assert rc1 == 0
        # 损坏 c01 状态(隔离在 artifacts 目录内)
        c1 = env["art"] / "coord_c01"
        if damage == "member_deleted":
            (c1 / "cue_contract_audit.json").unlink()
        elif damage == "trace_corrupted":
            with open(c1 / "cue_event_trace.jsonl", "ab") as fh:
                fh.write(b"corruption\n")
        args2 = type("A", (), {
            "deploy_root": str(env["deploy"]),
            "code_freeze_sha": rp.FREEZE,
            "coordinate_id": "c02"})()
        if damage is None:
            with pytest.raises(BaseException) as ei:
                mod.cmd_run_coordinate(args2)
            assert "CORE-BOUNDARY-SENTINEL" in str(ei.value)
            assert core_calls == ["c01", "c02"]  # 正例到达核心边界
        else:
            rc2 = mod.cmd_run_coordinate(args2)
            assert rc2 == 96
            assert core_calls == ["c01"]  # 零新增业务调用
            doc = json.loads(
                env["budget"].read_text(encoding="utf-8"))
            assert "c02" not in (doc.get("started") or {})
