"""RouteC_FormalLaunch_Preparation_v1 修复轮隔离验证(R1/R2/R3)。

ChatGPT 独立审查(0383d6cc,REVIEW.md §3-§5)三项阻断的修复验收:
- R1/F06:新 A 输入身份(QAF 族)建立并接通真实消费者;旧空间
  成对隔离;新身份确定性正例(同算法新命名空间)。
- R2/F02/F08/F09:分项预算真实有界(算术自洽;16000 废弃);
  learn/rollout/optimizer.step/验证步/save-load 逐类计量;A1/A2
  授权面分开;A1 的 PPO 面恒 0 由有界排程保证;消费点映射齐备。
- R3/F08:B 原生预算持久预占(异常/KeyboardInterrupt 不漏记、
  跨进程不可恢复、同坐标不双记);技术中断后继门(与合法统计
  负结果分开;collect_all_k 语义保留)。

本文件同时把 ChatGPT independent_component_probes.py 的成对探针
改写为期望**正确行为**的测试(旧候选错误行为原件保留在任务包
goal_incoming/RouteC_FLP_v1_IndependentReview_0383d6cc/)。
零业务消耗:叶层哨兵/计数替换;锁/许可/账本/门/收口为真实实现。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
    CURRICULUM261_QPROD_FORMAL_NAMESPACES,
    CURRICULUM261_R17_FORMAL_NAMESPACES,
    CURRICULUM261_R17_NAMESPACES,
    CURRICULUM261_SEED_NAMESPACES, _derive261_seed_raw,
    derive261_seed,
)
from rl_curriculum.curriculum261_qaf_attempt import (
    QAF_CALIBRATION_FAMILY, QAF_C2_INDEPENDENT_QUALIFICATION,
    QAF_FIT_QUALIFICATION, QAF_FORMAL_FOUR, QAF_INPUT_SCOPE,
    QAF_QUALIFICATION, QAF_SEMANTIC_QUALIFICATION,
)
from rl_curriculum.curriculum261_qprod_context import QProdContextError
from rl_curriculum.curriculum261_qprod_coordinate import (
    QPROD_COORDINATE_SEAL_NAME, assert_no_technical_interruption,
    check_native_budget, mark_native_completed,
    qprod_coordinate_code_identity, reserve_native_execution,
)
from rl_curriculum.curriculum261_qprod_formal import (
    QPROD_FORMAL_LEVEL_A_ITERATION_ID,
)
from rl_curriculum.curriculum261_qprod_formal_levela import (
    bound_workflow_plan_r17, build_formal_level_a_plan,
    formal_level_a_input_scope,
)
from rl_curriculum.curriculum261_qprod_formal_budget import (
    K, authorization_face, build_budget_items,
)
from rl_curriculum.curriculum261_r17_orchestrator import (
    formal_holdout_profile_r17, formal_main_profile_r17,
)
from rl_curriculum.curriculum261_r17_workflow import (
    build_workflow_plan_r17,
)
from rl_curriculum.curriculum261_qprod_plan import research_plan_digest

FREEZE = "3" * 40
FAMS = ("c1_opportunity", "c2_context", "c3_cost")
RUNGS = ("D0", "D1", "D2", "D3")


# ================= R1:新 A 输入身份 =================
class TestR1NewInputIdentity:
    def test_scope_is_qaf_only(self):
        scope = formal_level_a_input_scope()
        assert set(scope) == set(QAF_INPUT_SCOPE)
        assert len(scope) == 16
        # 不含任何旧正式/工程/B 名(ChatGPT 复现的 12 个旧名全拒)
        for old in ("qualification_r17", "qualification_r18",
                    "qualification_r19", "preprocess_fit_qualification"
                    "_r19", "cue_semantic_qualification_r17"):
            assert old not in scope
        # QAF 四件套按 R17 静态资格面注册(继承 final corpus 锁),
        # 但不得引入任何 R17/R18/R19 时代名:
        assert not set(scope) & (
            set(CURRICULUM261_R17_FORMAL_NAMESPACES)
            - set(QAF_FORMAL_FOUR))
        assert not set(scope) & set(
            CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
        assert not set(scope) & set(
            CURRICULUM261_QPROD_FORMAL_NAMESPACES)

    def test_qaf_registered_and_derivable(self):
        import rl_curriculum.curriculum261_r17_registry as reg
        align = reg.verify_r17_registry_alignment()
        assert align["api_namespaces_match"] and align[
            "api_formal_match"] and align["unique"]
        for ns in QAF_INPUT_SCOPE:
            assert ns in CURRICULUM261_SEED_NAMESPACES
            assert ns in CURRICULUM261_R17_NAMESPACES
        for ns in QAF_FORMAL_FOUR:
            assert ns in CURRICULUM261_R17_FORMAL_NAMESPACES

    def test_pairwise_seed_isolation_vs_all_old_spaces(self):
        """A/B/历史空间成对隔离:同一确定性算法,新命名空间 ⇒
        全网格 seed 不同(新身份正例=正常复用算法+全新身份)。"""
        old_counterparts = tuple(
            set(CURRICULUM261_R17_FORMAL_NAMESPACES)
            - set(QAF_FORMAL_FOUR)) + (
            "calibration_r19", "supervised_main_r19",
            "cue_semantic_calibration_r19",
            "c2_independent_calibration_r19",
            "preprocess_fit_calibration_r19", "fresh_holdout_r19",
            "stress_r19",
        ) + tuple(CURRICULUM261_QPROD_ENGINEERING_NAMESPACES[:2]) \
            + tuple(CURRICULUM261_QPROD_FORMAL_NAMESPACES[:2])
        for qaf in QAF_INPUT_SCOPE:
            for old in old_counterparts:
                for fam in FAMS[:2]:
                    for rung in RUNGS[:2]:
                        assert _derive261_seed_raw(
                            qaf, fam, rung, 0, 0) != _derive261_seed_raw(
                            old, fam, rung, 0, 0), (qaf, old)

    def test_qaf_seed_grid_deterministic_and_attempt_varying(self):
        s00 = _derive261_seed_raw(QAF_QUALIFICATION, "c2_context", "D1", 0, 0)
        assert s00 == _derive261_seed_raw(
            QAF_QUALIFICATION, "c2_context", "D1", 0, 0)
        assert s00 != _derive261_seed_raw(
            QAF_QUALIFICATION, "c2_context", "D1", 0, 1)

    def test_old_names_in_approval_scope_refused(self, tmp_path,
                                                 monkeypatch):
        """旧空间混入新 A 反例:批准 scope 含任一旧名=错范围拒绝。"""
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                               / "tests" / "route_c_stage2_6_1"))
        from test_curriculum261_qprod_formal_launch import (
            _make_deploy, _approval_payload, _setup_a,
        )
        deploy, art, state, authority, payload, digest, ctx = _setup_a(
            tmp_path)
        # 篡改批准:scope 混入旧 R17 正式名(其余绑定保持正确)
        approval_path = authority / (
            f"qprod_formal_approval_level_a_"
            f"{QPROD_FORMAL_LEVEL_A_ITERATION_ID}.json")
        approval = json.loads(approval_path.read_text(
            encoding="utf-8"))
        approval["approved"]["namespaces"] = list(
            formal_level_a_input_scope())[:15] + [
            "qualification_r17"]
        approval["approval_digest"] = _recompute_approval_digest(
            approval)
        approval_path.write_text(json.dumps(approval),
                                 encoding="utf-8")
        from rl_curriculum.curriculum261_qprod_formal import (
            build_formal_context, validate_formal_permit,
        )
        from test_curriculum261_qprod_formal_launch import (
            _write_formal_permit,
        )
        ctx2 = build_formal_context(
            deploy, level="level_a",
            iteration_id=QPROD_FORMAL_LEVEL_A_ITERATION_ID,
            code_freeze_sha=ctx.code_freeze_sha,
            research_plan_digest=digest,
            approval_digest=approval["approval_digest"])
        _write_formal_permit(authority, ctx2, approval)
        with pytest.raises(QProdContextError, match="范围"):
            validate_formal_permit(ctx2.permit_path, context=ctx2)


def _recompute_approval_digest(approval: dict) -> str:
    from rl_curriculum.curriculum261_qprod_formal import (
        formal_approval_digest,
    )
    return formal_approval_digest(approval)


# ============ R1:真实消费者接通(非 argv 展示) ============
class TestR1RealConsumerThreading:
    def test_plan_builder_injects_attempt_flag_into_calibrate_qualify(
            self):
        plan = build_workflow_plan_r17(
            "formal", out_dir="/tmp/x", freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        assert plan["formal_namespace_attempt"] == "qaf_v1"
        for name in ("calibrate", "qualify"):
            step = next(s for s in plan["steps"] if s["name"] == name)
            argv = step["argv"]
            i = argv.index("--formal-namespace-attempt")
            assert argv[i + 1] == "qaf_v1"
        for name in ("audit", "cue-audit", "design", "smoke"):
            step = next(s for s in plan["steps"] if s["name"] == name)
            assert "--formal-namespace-attempt" not in step["argv"]

    def test_plan_builder_default_unchanged(self):
        plan = build_workflow_plan_r17(
            "formal", out_dir="/tmp/x", freeze_sha=FREEZE)
        assert plan["formal_namespace_attempt"] is None
        for step in plan["steps"]:
            assert "--formal-namespace-attempt" not in step["argv"]
        with pytest.raises(ValueError):
            build_workflow_plan_r17(
                "formal", out_dir="/tmp/x", freeze_sha=FREEZE,
                formal_attempt="bogus")

    def test_rehearsal_plan_never_gets_attempt(self):
        plan = build_workflow_plan_r17(
            "rehearsal", out_dir="/tmp/x", freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        for step in plan["steps"]:
            assert "--formal-namespace-attempt" not in step["argv"]

    def test_calibrate_profile_qaf_and_legacy(self):
        main = formal_main_profile_r17(20, attempt="qaf_v1")
        hold = formal_holdout_profile_r17(20, attempt="qaf_v1")
        from rl_curriculum.curriculum261_qaf_attempt import (
            QAF_C13_MAIN, QAF_C13_HOLDOUT, QAF_SEMANTIC_MAIN,
            QAF_SUPERVISED_MAIN,
        )
        assert main.c13_eval_namespace == QAF_C13_MAIN
        assert main.semantic_namespace == QAF_SEMANTIC_MAIN
        assert main.supervised_namespace == QAF_SUPERVISED_MAIN
        assert hold.c13_eval_namespace == QAF_C13_HOLDOUT
        # legacy 缺省字节不变(R19)
        from rl_curriculum.curriculum261_r19_attempt import (
            R19_C13_MAIN,
        )
        assert formal_main_profile_r17(
            20).c13_eval_namespace == R19_C13_MAIN
        with pytest.raises(ValueError):
            formal_main_profile_r17(20, attempt="bogus")

    def test_qualify_core_kwargs_qaf_and_legacy(self):
        from rl_curriculum.curriculum261_r17_final import (
            formal_attempt_core_kwargs,
        )
        plan = {"final_sample_counts": {"c2_matched_blocks": 20}}
        kw, src = formal_attempt_core_kwargs("qaf_v1", plan)
        assert src == "qaf_v1"
        assert kw["final_namespace"] == QAF_QUALIFICATION
        assert kw["fit_namespace"] == QAF_FIT_QUALIFICATION
        assert kw["independent_namespace"] == (
            QAF_C2_INDEPENDENT_QUALIFICATION)
        assert kw["semantic_namespace_override"] == (
            QAF_SEMANTIC_QUALIFICATION)
        assert kw["profile_name"] == "formal_final_qaf_v1"
        assert kw["c2_blocks"] == 20
        # legacy 缺省=R18(既有行为不变)
        from rl_curriculum.curriculum261_r18_attempt import (
            R18_QUALIFICATION,
        )
        kw0, src0 = formal_attempt_core_kwargs(None, plan)
        assert src0 == "r18" and kw0["final_namespace"] == (
            R18_QUALIFICATION)
        with pytest.raises(RuntimeError):
            formal_attempt_core_kwargs("bogus", plan)

    def test_bounded_plan_keeps_attempt_and_excludes_smoke(self):
        plan = build_workflow_plan_r17(
            "formal", out_dir="/tmp/x", freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        bounded = bound_workflow_plan_r17(plan, "qualify")
        cal = next(s for s in bounded["steps"]
                   if s["name"] == "calibrate")
        assert cal["argv"][cal["argv"].index(
            "--formal-namespace-attempt") + 1] == "qaf_v1"
        qual = next(s for s in bounded["steps"]
                    if s["name"] == "qualify")
        assert qual["argv"][qual["argv"].index(
            "--formal-namespace-attempt") + 1] == "qaf_v1"
        assert "smoke" not in [s["name"] for s in bounded["steps"]]
        assert bounded["not_run_steps"] == [
            "smoke", "full-cold", "report-read"]

    def test_launch_handoff_carries_attempt_flag(self, tmp_path,
                                                 monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                               / "tests" / "route_c_stage2_6_1"))
        from test_curriculum261_qprod_formal_launch import _setup_a
        from rl_curriculum.curriculum261_qprod_formal_levela import (
            launch_formal_level_a,
        )
        (deploy, art, state, authority, payload, digest,
         ctx) = _setup_a(tmp_path)
        result = launch_formal_level_a(
            deploy_root=deploy, project_dir=tmp_path / "project",
            code_freeze_sha=ctx.code_freeze_sha,
            code_identity=payload["code_identity"],
            authorized_stop_after="qualify",
            model_update_authorized=False,
            sentinel_before_chain=True)
        handoff = json.loads(
            (art / "qprod_formal_launch_handoff.json").read_text(
                encoding="utf-8"))
        argv = handoff["argv"]
        i = argv.index("--formal-namespace-attempt")
        assert argv[i + 1] == "qaf_v1"

    def test_plan_input_scope_documented_in_payload(self):
        payload = build_formal_level_a_plan(
            code_freeze_sha=FREEZE,
            code_identity=qprod_coordinate_code_identity(),
            authorized_stop_after="qualify",
            model_update_authorized=False)
        digest = research_plan_digest(payload)
        assert digest.startswith("qbpl-")
        scope = formal_level_a_input_scope()
        # run_scope 记录输入范围(批准 scope 绑定的同一集合)
        assert payload["run_scope"]["entry"]


# ================= R2:预算与计量 =================
class TestR2BudgetMetering:
    def test_items_arithmetic_self_consistent(self):
        items = build_budget_items()
        assert items, "分项非空"
        cats = {i["category"] for i in items}
        for needed in ("generation_episodes", "v2_preprocessor_fits",
                       "supervised_mlp_fits", "mc_events",
                       "bootstrap_resamples"):
            assert needed in cats
        for i in items:
            assert i["typical"] <= i["worst_upper"], i
            assert i["formula"] and i["consumer"] and i["metering"], i

    def test_no_legacy_16000_or_one_optimizer_claim(self):
        face1 = authorization_face(stop_after="qualify")
        face2 = authorization_face(stop_after="verify-formal-logs")
        for face in (face1, face2):
            assert face["generation_episodes_typical"] != 16000
            # 分项和==面值(算术自洽,修复 16000<分项和 的矛盾)
            assert face["authorization_cap_generation_episodes"] >= \
                face["generation_episodes_typical"]

    def test_a1_face_zero_ppo_and_bounded_schedule(self):
        face = authorization_face(stop_after="qualify")
        assert face["ppo_learn_calls"] == 0
        assert face["ppo_optimizer_steps_upper"] == 0
        assert face["ppo_rollout_env_steps"] == 0
        assert face["ppo_validation_env_steps"] == 0
        assert face["model_save_load_pairs"] == 0
        # A1 仍含监督拟合(不以"无模型更新"含糊监督面)
        assert face["supervised_mlp_fits"] == 54 + 27 + 4
        assert face["v2_preprocessor_fits"] == 5 + 2 + 1  # 无 smoke
        # 物理保证:有界排程不含 smoke
        plan = build_workflow_plan_r17(
            "formal", out_dir="/tmp/x", freeze_sha=FREEZE,
            formal_attempt="qaf_v1")
        bounded = bound_workflow_plan_r17(plan, "qualify")
        assert "smoke" in bounded["not_run_steps"]

    def test_a2_face_itemized_ppo_metering(self):
        face = authorization_face(stop_after="verify-formal-logs")
        assert face["ppo_learn_calls"] == 1
        assert face["ppo_rollout_env_steps"] == 256
        # SB3 默认 n_epochs=10 × ceil(256/64)=4 minibatch = 40
        assert face["ppo_optimizer_steps_upper"] == 10 * (256 // 64)
        assert face["ppo_optimizer_steps_upper"] == 40
        assert face["ppo_validation_env_steps"] == 50
        assert face["model_save_load_pairs"] == 1
        # smoke 生成 = bank 144 + pair 2(cmd_smoke 不传 envelope)
        smoke_eps = [i for i in build_budget_items()
                     if i["step"] == "smoke"
                     and i["category"] == "generation_episodes"][0]
        bank = 3 * 4 * K["bank_pairs_per_rung"] * 2
        assert smoke_eps["typical"] == bank + 2 == 146
        assert face["v2_preprocessor_fits"] == 5 + 2 + 1 + 1  # +smoke

    def test_derived_from_live_constants(self):
        assert K["bank_pairs_per_rung"] == 6
        assert K["max_attempts"] == 5
        assert K["mlp_epochs_default"] == 20
        assert K["audit_blocks"] == 500
        assert K["audit_mc_events"] == 1_000_000
        assert K["c2_blocks_max"] == 20
        assert K["n_candidates"] == 3

    def test_plan_quota_equals_authorization_face(self):
        for stop, mu in (("qualify", False),
                         ("verify-formal-logs", True)):
            payload = build_formal_level_a_plan(
                code_freeze_sha=FREEZE,
                code_identity=qprod_coordinate_code_identity(),
                authorized_stop_after=stop,
                model_update_authorized=mu)
            face = authorization_face(stop_after=stop)
            q = payload["quota"]
            assert q["max_successful_episodes_total"] == face[
                "authorization_cap_generation_episodes"]
            assert q["ppo_optimizer_steps_upper"] == face[
                "ppo_optimizer_steps_upper"]
            assert q["supervised_mlp_fits"] == face[
                "supervised_mlp_fits"]
            assert q["v2_preprocessor_fits"] == face[
                "v2_preprocessor_fits"]
            assert payload["run_scope"]["budget"]["stop_after"] == stop
            assert payload["run_scope"]["budget_items"]

    def test_consumption_points_mapped(self):
        items = build_budget_items()
        for i in items:
            if i["typical"] > 0 or i["worst_upper"] > 0:
                assert i["consumer"] != "-"
        # 关键类别消费点点名真实函数
        joined = " ".join(i["consumer"] for i in items)
        for fn in ("_run_cue_contract_audit_core",
                   "run_design_stage_r17",
                   "orchestrate_calibration_stage_r17",
                   "execute_final_core_r17", "PPO.learn",
                   "train_supervised_mlp"):
            assert fn in joined, fn


# ================= R3:原生计账与后继控制 =================
def _budget_file(tmp_path: Path, mx: int, started: dict | None = None):
    p = tmp_path / "qprod_native_budget.json"
    p.write_text(json.dumps({
        "max_runs": mx, "consumed_runs": len(started or {}),
        "started": started or {}}), encoding="utf-8")
    return p


class TestR3ReserveSemantics:
    def test_reserve_before_action_persists(self, tmp_path):
        bp = _budget_file(tmp_path, 1)
        r = reserve_native_execution(bp, coordinate_id="c01")
        assert r["remaining_after"] == 0
        doc = json.loads(bp.read_text(encoding="utf-8"))
        assert "c01" in doc["started"]

    def test_same_coordinate_no_double_record(self, tmp_path):
        bp = _budget_file(tmp_path, 11)
        reserve_native_execution(bp, coordinate_id="c01")
        with pytest.raises(QProdContextError, match="不双记"):
            reserve_native_execution(bp, coordinate_id="c01")
        doc = json.loads(bp.read_text(encoding="utf-8"))
        assert list(doc["started"]) == ["c01"]

    def test_exhausted_refused_before_action(self, tmp_path):
        bp = _budget_file(tmp_path, 1, started={"c01": {"x": 1}})
        with pytest.raises(QProdContextError, match="耗尽"):
            reserve_native_execution(bp, coordinate_id="c02")

    def test_missing_file_refused(self, tmp_path):
        with pytest.raises(QProdContextError, match="缺失"):
            reserve_native_execution(
                tmp_path / "none.json", coordinate_id="c01")

    def test_smaller_positive_balance_not_crossable(self, tmp_path):
        # ChatGPT 余额控制:max=11,started 10 → 第 11 个可,第 12
        # 类坐标(清单外)不可——剩余额度按 started 计,不可穿越。
        started = {f"c{i:02d}": {"x": 1} for i in range(1, 11)}
        bp = _budget_file(tmp_path, 11, started=started)
        r = reserve_native_execution(bp, coordinate_id="c11")
        assert r["remaining_after"] == 0
        with pytest.raises(QProdContextError, match="耗尽"):
            reserve_native_execution(bp, coordinate_id="c01b")

    def test_cross_process_persistence(self, tmp_path):
        bp = _budget_file(tmp_path, 1)
        reserve_native_execution(bp, coordinate_id="c01")
        # 新进程读同一文件:已消费,不可恢复
        code = (
            "import sys,json;"
            f"p={json.dumps(str(bp))};"
            "doc=json.load(open(p));"
            "print(json.dumps({'started': sorted(doc['started'])}))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True,
            text=True)
        assert json.loads(out.stdout)["started"] == ["c01"]

    def test_mark_completed_observational_only(self, tmp_path):
        bp = _budget_file(tmp_path, 2)
        reserve_native_execution(bp, coordinate_id="c01")
        mark_native_completed(bp, coordinate_id="c01")
        doc = json.loads(bp.read_text(encoding="utf-8"))
        assert doc["completed"] == {"c01": doc["completed"]["c01"]}
        # 额度判定仍只看 started;max=2 下 c02 仍可预占
        r2 = reserve_native_execution(bp, coordinate_id="c02")
        assert r2["remaining_after"] == 0


class TestR3TechnicalInterruptionGate:
    def _manifest(self):
        return [{"coordinate_id": f"c{i:02d}",
                 "artifact_subdir": f"coord_c{i:02d}"} for i in
                range(1, 4)]

    def test_interrupted_without_seal_blocks_next(self, tmp_path):
        root = tmp_path / "artifacts"
        d = root / "coord_c01"
        d.mkdir(parents=True)
        (d / "qprod_coordinate_interrupted.json").write_text(
            "{}", encoding="utf-8")
        with pytest.raises(QProdContextError, match="技术中断"):
            assert_no_technical_interruption(root, self._manifest())

    def test_valid_negative_allows_collect_all_k(self, tmp_path):
        root = tmp_path / "artifacts"
        d = root / "coord_c01"
        d.mkdir(parents=True)
        (d / "qprod_coordinate_interrupted.json").unlink(
            missing_ok=True)
        (d / QPROD_COORDINATE_SEAL_NAME).write_text(
            json.dumps({"summary": {"audit_pass": False}}),
            encoding="utf-8")
        assert_no_technical_interruption(root, self._manifest())

    def test_clean_root_allows(self, tmp_path):
        root = tmp_path / "artifacts"
        root.mkdir()
        assert_no_technical_interruption(root, self._manifest())


# ===== R3:入口成对探针(ChatGPT probe 的期望正确行为改写) =====
class TestR3EntryPairProbes:
    """成对对照:进入后异常/KeyboardInterrupt/正常/缺失/耗尽/
    同坐标/下一坐标/重复。叶哨兵替换 run_coordinate_audit_locked;
    预算/门/许可校验为真实实现。"""

    def _full_b_env(self, tmp_path, mx, monkeypatch):
        """搭 B 沙盒:配置/批准/许可/冻结/锁/预算 + 消费许可。"""
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]
                               / "tests" / "route_c_stage2_6_1"))
        from test_curriculum261_qprod_formal_launch import (
            _make_deploy, _approval_payload, _b_namespaces,
            _write_formal_permit,
        )
        from rl_curriculum.curriculum261_qprod_formal import (
            QPROD_FORMAL_LEVEL_B_ITERATION_ID,
            build_formal_context, build_formal_level_b_plan,
        )
        from rl_curriculum.curriculum261_qprod_plan import (
            freeze_research_plan,
        )
        from rl_curriculum.curriculum261_qprod_permit import (
            consume_permit,
        )
        from rl_curriculum.curriculum261_qprod_coordinate import (
            lock_coordinate_audit_plan,
        )
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE,
            code_identity=qprod_coordinate_code_identity())
        digest = research_plan_digest(payload)
        approval = _approval_payload(
            level="level_b", digest=digest, art=art, state=state,
            authority=authority, namespaces=_b_namespaces(),
            coordinate_ids=[c["coordinate_id"] for c in
                            payload["coordinate_manifest"]],
            quota=payload["quota"], sha=FREEZE)
        (authority / "qprod_formal_approval_level_b_"
         f"{QPROD_FORMAL_LEVEL_B_ITERATION_ID}.json").write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        ctx = build_formal_context(
            deploy, level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
            code_freeze_sha=FREEZE, research_plan_digest=digest,
            approval_digest=approval["approval_digest"])
        _write_formal_permit(authority, ctx, approval)
        from rl_curriculum.curriculum261_qprod_context import (
            harden_root,
        )
        harden_root(state, label="state_root", create=True)
        harden_root(art, label="artifact_root", create=True)
        freeze_research_plan(state, payload)
        consume_permit(ctx.permit_path, context=ctx)
        budget = state / "qprod_native_budget.json"
        budget.write_text(json.dumps(
            {"max_runs": mx, "consumed_runs": 0, "started": {}}),
            encoding="utf-8")
        base = Path(__file__).resolve().parents[2]
        for cand in (base / "stage2_6_1_runner",
                     base / "runner",
                     base / "stage2_6_1" / "runner"):
            if (cand / "qprod_formal_level_b_entry.py").is_file():
                runner = cand / "qprod_formal_level_b_entry.py"
                break
        else:
            raise FileNotFoundError("runner 入口未找到")
        return {
            "runner": runner, "deploy": deploy, "art": art,
            "state": state, "ctx": ctx, "payload": payload,
            "budget": budget,
        }

    def _run_entry(self, env, monkeypatch, coordinate_id,
                   fake_core):
        """直接调 cmd_run_coordinate(经 runner import),叶=哨兵。"""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "qprod_formal_level_b_entry_test",
            env["runner"])
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(
            mod, "run_coordinate_audit_locked", fake_core)
        args = type("A", (), {
            "deploy_root": str(env["deploy"]),
            "code_freeze_sha": FREEZE,
            "coordinate_id": coordinate_id})()
        captured = {}

        def run():
            captured["rc"] = mod.cmd_run_coordinate(args)
        return run, captured

    def test_pair_exception_then_next_refused(self, tmp_path,
                                              monkeypatch):
        """ChatGPT R3 复现对 1:max=1,c01 进入后异常,c02 必须
        在动作前被拒(旧候选错误地放行)。"""
        env = self._full_b_env(tmp_path, mx=1, monkeypatch=monkeypatch)

        def core_exc(*a, **k):
            raise RuntimeError("boom mid-run")

        run1, cap1 = self._run_entry(
            env, monkeypatch, "c01", core_exc)
        with pytest.raises(RuntimeError, match="boom"):
            run1()
        doc = json.loads(env["budget"].read_text(encoding="utf-8"))
        assert "c01" in doc["started"]  # 预占保留(不漏记)
        run2, cap2 = self._run_entry(
            env, monkeypatch, "c02", core_exc)
        run2()
        assert cap2["rc"] == 96  # 动作前拒(旧候选=0 放行)

    def test_pair_keyboard_interrupt_persists(self, tmp_path,
                                              monkeypatch):
        env = self._full_b_env(tmp_path, mx=2, monkeypatch=monkeypatch)

        def core_ki(*a, **k):
            raise KeyboardInterrupt

        run1, _ = self._run_entry(env, monkeypatch, "c01", core_ki)
        with pytest.raises(KeyboardInterrupt):
            run1()
        doc = json.loads(env["budget"].read_text(encoding="utf-8"))
        assert "c01" in doc["started"]  # KI 不回收额度

    def test_pair_success_then_next_allowed_with_budget(
            self, tmp_path, monkeypatch):
        env = self._full_b_env(tmp_path, mx=2, monkeypatch=monkeypatch)

        def core_ok(ctx, live, cid, coord_dir=None, ledger_path=None):
            d = Path(coord_dir)
            d.mkdir(parents=True, exist_ok=True)
            (d / QPROD_COORDINATE_SEAL_NAME).write_text(
                json.dumps({"coordinate_id": cid, "summary": {
                    "audit_pass": False, "recall_validation": 0.5,
                    "se_validation": 0.01, "p_contract_local": 0.5}}),
                encoding="utf-8")
            return {"seal": {"coordinate_id": cid, "summary": {
                "audit_pass": False, "recall_validation": 0.5,
                "se_validation": 0.01, "p_contract_local": 0.5}},
                "generation": {"episode_leaf_calls": 8000}}

        run1, cap1 = self._run_entry(
            env, monkeypatch, "c01", core_ok)
        run1()
        assert cap1["rc"] == 0
        doc = json.loads(env["budget"].read_text(encoding="utf-8"))
        assert doc["completed"].get("c01")
        # 合法负结果(seal 在场,audit_pass=False)+ 额度剩余 ⇒
        # 下一坐标放行(collect_all_k 保留)
        run2, cap2 = self._run_entry(
            env, monkeypatch, "c02", core_ok)
        run2()
        assert cap2["rc"] == 0

    def test_pair_success_exhausts_then_refused(self, tmp_path,
                                                monkeypatch):
        env = self._full_b_env(tmp_path, mx=1, monkeypatch=monkeypatch)

        def core_ok(ctx, live, cid, coord_dir=None, ledger_path=None):
            d = Path(coord_dir)
            d.mkdir(parents=True, exist_ok=True)
            (d / QPROD_COORDINATE_SEAL_NAME).write_text(
                json.dumps({"coordinate_id": cid, "summary": {
                    "audit_pass": False, "recall_validation": 0.5,
                    "se_validation": 0.01, "p_contract_local": 0.5}}),
                encoding="utf-8")
            return {"seal": {"coordinate_id": cid, "summary": {
                "audit_pass": False, "recall_validation": 0.5,
                "se_validation": 0.01, "p_contract_local": 0.5}},
                "generation": {"episode_leaf_calls": 8000}}

        run1, _ = self._run_entry(env, monkeypatch, "c01", core_ok)
        run1()
        run2, cap2 = self._run_entry(env, monkeypatch, "c02", core_ok)
        run2()
        assert cap2["rc"] == 96  # ChatGPT 正常对照行为保持

    def test_technical_interruption_blocks_next_despite_budget(
            self, tmp_path, monkeypatch):
        env = self._full_b_env(tmp_path, mx=11, monkeypatch=monkeypatch)

        def core_interrupted(*a, **k):
            d = Path(k.get("coord_dir"))
            d.mkdir(parents=True, exist_ok=True)
            (d / "qprod_coordinate_interrupted.json").write_text(
                json.dumps({"reason": "technical"}), encoding="utf-8")
            raise RuntimeError("technical interruption")

        run1, _ = self._run_entry(
            env, monkeypatch, "c01", core_interrupted)
        with pytest.raises(RuntimeError):
            run1()
        run2, cap2 = self._run_entry(
            env, monkeypatch, "c02", core_interrupted)
        run2()
        # 额度尚余 10,但技术中断态阻塞后续坐标
        assert cap2["rc"] == 96

    def test_missing_budget_refused_before_core(self, tmp_path,
                                                monkeypatch):
        env = self._full_b_env(tmp_path, mx=1, monkeypatch=monkeypatch)
        env["budget"].unlink()
        called = {"n": 0}

        def core(*a, **k):
            called["n"] += 1
            return {"seal": {}, "generation": {}}

        run, cap = self._run_entry(env, monkeypatch, "c01", core)
        run()
        assert cap["rc"] == 96 and called["n"] == 0  # 零叶调用

    def test_same_coordinate_repeat_refused(self, tmp_path,
                                            monkeypatch):
        env = self._full_b_env(tmp_path, mx=11, monkeypatch=monkeypatch)
        # 需要先锁坐标?run-coordinate 需在计划清单——c01 已在。
        # 第一次异常后同坐标重试:started 已有 c01 ⇒ 预占拒绝。
        def core_exc(*a, **k):
            raise RuntimeError("boom")

        run1, _ = self._run_entry(env, monkeypatch, "c01", core_exc)
        with pytest.raises(RuntimeError):
            run1()
        run2, cap2 = self._run_entry(env, monkeypatch, "c01", core_exc)
        run2()
        assert cap2["rc"] == 96
