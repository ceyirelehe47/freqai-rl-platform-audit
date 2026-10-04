"""RouteC_FormalLaunch_Preparation_v1:正式启动适配隔离验证。

覆盖(验收矩阵 F02-F09 相关面):
- 正式 namespace 休眠定义(22 名、与工程/开发空间不相交、seed
  派生可达);
- 计划结构校验按 profile 分支(formal 500/1e6;不可互相冒充);
- 坐标锁 namespace 白名单按 profile 分支;
- 批准原件/正式许可绑定校验(错层/错候/错计划/错根/错范围/
  错额度/工程许可冒充全拒);
- Level A launch:门禁全部先于受控副作用;哨兵在权威链执行器
  调用边界前诚实停止(零步骤执行);停止边界与模型更新授权
  一致性;权威执行器 postcondition(资格 FAIL ⇒ smoke 不启动);
  有界排程 not_run_steps;
- Level B:11 坐标清单零生成预检(重复预检身份不变、零副作用);
  坐标锁 formal 预算;run-coordinate 到真实审计核心边界(哨兵
  叶替换,锁/许可/账本/失败收口全真);
- 部署配置 fail closed(env 重定向/非 formal_ready/保护根)。

测试域 authority/批准/许可均带 test 标记,只写隔离 tmp 目录;
不触真实部署/许可/exposure/生成。
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
    CURRICULUM261_R25_DEV_NAMESPACES,
    CURRICULUM261_SEED_NAMESPACES,
)
from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_plan import (
    freeze_research_plan, research_plan_digest,
    research_plan_structure_problems,
)
from rl_curriculum.curriculum261_qprod_permit import (
    permit_digest, validate_permit,
)
from rl_curriculum.curriculum261_qprod_coordinate import (
    FORMAL_BLOCKS_PER_CORPUS, FORMAL_MC_EVENTS,
    lock_coordinate_audit_plan, qprod_coordinate_code_identity,
)
from rl_curriculum.curriculum261_qprod_formal import (
    QPROD_FORMAL_APPROVAL_FORMAT, QPROD_FORMAL_LEVEL_A_ITERATION_ID,
    QPROD_FORMAL_LEVEL_B_ITERATION_ID, build_formal_context,
    build_formal_level_b_plan, formal_approval_digest,
    formal_coordinate_manifest, formal_level_b_quota,
    load_formal_approval, preflight_formal_level_b,
    validate_formal_approval, validate_formal_permit,
)
from rl_curriculum.curriculum261_qprod_formal_levela import (
    QPROD_FORMAL_STOP_CHOICES, FormalLaunchRefused,
    bound_workflow_plan_r17, build_formal_level_a_plan,
    launch_formal_level_a, preflight_formal_level_a,
)

FREEZE_SHA = "1" * 40
AUTHORITY_ID = "test-formal-authority-001"


# ------------------------------------------------ 沙盒部署 --------
def _make_deploy(tmp_path: Path, *, mode: str = "formal_ready",
                 level: str = "level_a",
                 state_tail: str = "route_c_stage2_6_1_repair17",
                 ) -> tuple[Path, Path, Path, Path]:
    """测试域沙盒部署(明确标记 test;不触生产)。"""
    deploy = tmp_path / "deploy"
    formal = deploy / "formal"
    if level == "level_a":
        art = formal / QPROD_FORMAL_LEVEL_A_ITERATION_ID / (
            "artifacts") / "chain"
        state = formal / QPROD_FORMAL_LEVEL_A_ITERATION_ID / (
            "artifacts") / state_tail / "state"
        iteration = QPROD_FORMAL_LEVEL_A_ITERATION_ID
    else:
        art = formal / QPROD_FORMAL_LEVEL_B_ITERATION_ID / "artifacts"
        state = formal / QPROD_FORMAL_LEVEL_B_ITERATION_ID / "state"
        iteration = QPROD_FORMAL_LEVEL_B_ITERATION_ID
    authority = formal / "authority"
    authority.mkdir(parents=True, exist_ok=True)
    (authority / "authority_identity.json").write_text(json.dumps({
        "format": "cur261-qprod-authority-identity-v1",
        "authority_id": AUTHORITY_ID,
        "kind": "formal_admission_authority",
        "note": "TEST-ONLY formal authority(隔离测试域)",
    }, ensure_ascii=False), encoding="utf-8")
    (deploy / "qprod_deploy_config.json").write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1",
        "mode": mode,
        "formal_roots": {
            iteration: {
                "artifact_root": str(art),
                "state_root": str(state),
                "authority_dir": str(authority),
            },
        },
    }, ensure_ascii=False), encoding="utf-8")
    return deploy, art, state, authority


def _b_namespaces() -> list[str]:
    return sorted(
        ns for c in formal_coordinate_manifest()
        for ns in (c["model_namespace"], c["validation_namespace"]))


def _approval_payload(*, level: str, digest: str, art: Path,
                      state: Path, authority: Path,
                      namespaces, coordinate_ids, quota,
                      stop=None, model_update=False,
                      sha: str = FREEZE_SHA) -> dict:
    approval = {
        "format": QPROD_FORMAL_APPROVAL_FORMAT,
        "approval_id": "qfa-test-0001",
        "task_level": level,
        "iteration_id": (
            QPROD_FORMAL_LEVEL_A_ITERATION_ID if level == "level_a"
            else QPROD_FORMAL_LEVEL_B_ITERATION_ID),
        "approved": {
            "research_plan_digest": digest,
            "code_freeze_sha": sha,
            "artifact_root": str(art),
            "state_root": str(state),
            "authority_dir": str(authority),
            "namespaces": list(namespaces),
            "coordinate_ids": list(coordinate_ids),
            "quota": dict(quota),
            "authorized_stop_after": stop,
            "model_update_authorized": model_update,
        },
        "approval_source": {
            "kind": "user_direct_approval",
            "statement_digest": "test-statement-sha256-"
                                "61d3f2c0aa11",
            "received_utc": "2026-10-02T00:00:00Z",
        },
    }
    approval["approval_digest"] = formal_approval_digest(approval)
    return approval


def _write_formal_permit(authority: Path, ctx, approval: dict,
                         **over) -> Path:
    approved = approval["approved"]
    permit = {
        "format": "cur261-qprod-permit-v1",
        "permit_id": "qppm-formal-test-0001",
        "task_level": ctx.level,
        "iteration_id": ctx.iteration_id,
        "code_freeze_sha": ctx.code_freeze_sha,
        "artifact_root": str(ctx.artifact_root),
        "state_root": str(ctx.state_root),
        "preregistered_input_scope": {
            "namespaces": list(approved["namespaces"]),
            "coordinate_ids": list(approved["coordinate_ids"]),
        },
        "quota": dict(approved["quota"]),
        "issuer": {
            "kind": "formal_admission_authority",
            "authority_id": AUTHORITY_ID,
            "approval_id": approval["approval_id"],
        },
        "research_plan_digest": approved["research_plan_digest"],
        "approval_digest": approval["approval_digest"],
        "authorized_stop_after": approved["authorized_stop_after"],
        "model_update_authorized": bool(
            approved["model_update_authorized"]),
        "issued_utc": "2026-10-02T00:00:00Z",
    }
    permit.update(over)
    permit["permit_digest"] = permit_digest(permit)
    path = authority / f"qprod_permit_{ctx.level}_"
    path = Path(str(path) + f"{ctx.iteration_id}.json")
    path.write_text(json.dumps(permit, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _setup_a(tmp_path: Path, *, stop="qualify", model_update=False,
             approval_over=None, admission=True):
    deploy, art, state, authority = _make_deploy(
        tmp_path, level="level_a")
    payload = build_formal_level_a_plan(
        code_freeze_sha=FREEZE_SHA,
        code_identity=qprod_coordinate_code_identity(),
        authorized_stop_after=stop,
        model_update_authorized=model_update)
    digest = research_plan_digest(payload)
    from rl_curriculum.curriculum261_qprod_formal_levela import (
        formal_level_a_input_scope,
    )
    approval = _approval_payload(
        level="level_a", digest=digest, art=art, state=state,
        authority=authority,
        namespaces=formal_level_a_input_scope(), coordinate_ids=[],
        quota=payload["quota"], stop=stop,
        model_update=model_update)
    if approval_over:
        approval["approved"].update(approval_over)
        approval["approval_digest"] = formal_approval_digest(approval)
    (authority / "qprod_formal_approval_level_a_"
     f"{QPROD_FORMAL_LEVEL_A_ITERATION_ID}.json").write_text(
        json.dumps(approval, ensure_ascii=False), encoding="utf-8")
    ctx = build_formal_context(
        deploy, level="level_a",
        iteration_id=QPROD_FORMAL_LEVEL_A_ITERATION_ID,
        code_freeze_sha=FREEZE_SHA, research_plan_digest=digest,
        approval_digest=approval["approval_digest"])
    _write_formal_permit(authority, ctx, approval)
    if admission:
        admission_dir = state.parent.parent.parent
        admission_dir.mkdir(parents=True, exist_ok=True)
        (admission_dir / ".r17_formal_admission.json").write_text(
            json.dumps({"admission_id": "adm-test-1",
                        "commit_a_sha": FREEZE_SHA}),
            encoding="utf-8")
    # A2-R2 §A3 新契约:launch 在消费许可前按钉死 sha 重查实际
    # 目标两件 + project_dir 须有 stage2_6_1_runner(链子进程入口)。
    # 沙箱按固定 Git 源安装钉死 provenance(FBAB v1 错装事故的
    # 消费前兜底;真实源读取,repo 不可达则跳过本组)。
    import os as _os
    _repo = _os.environ.get("A2R2_TEST_REPO")
    if not _repo:
        for _cand in ("/mnt/f/trading/freqai-rl-audit",
                      "F:/trading/freqai-rl-audit"):
            if Path(_cand, ".git").exists():
                _repo = _cand
                break
    if _repo is None:
        pytest.skip("钉死源 Git 仓库不可达(A2R2_TEST_REPO)")
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source,
    )
    install_to_target(art, read_pinned_source(Path(_repo)))
    (tmp_path / "project" / "stage2_6_1_runner").mkdir(
        parents=True, exist_ok=True)
    return deploy, art, state, authority, payload, digest, ctx


def _tree_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*")}


# ------------------------------------------------ namespace -------
class TestFormalNamespaces:
    def test_dormant_formal_namespaces_defined_and_disjoint(self):
        assert len(CURRICULUM261_QPROD_FORMAL_NAMESPACES) == 22
        assert not set(CURRICULUM261_QPROD_FORMAL_NAMESPACES) & set(
            CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)
        assert not set(CURRICULUM261_QPROD_FORMAL_NAMESPACES) & set(
            CURRICULUM261_R25_DEV_NAMESPACES)

    def test_seed_derivation_reachable_but_unconsumed(self):
        # 休眠=名字可派生(链可达);无正式许可/坐标锁时生成入口
        # 仍拒绝(由 permit/coordinate 层测试覆盖)。
        assert set(CURRICULUM261_QPROD_FORMAL_NAMESPACES) <= set(
            CURRICULUM261_SEED_NAMESPACES)
        from rl_curriculum.curriculum261_r6_tape import (
            derive261_block_seed,
        )
        s = derive261_block_seed(
            "cue_qprod_formal_v1_c01_model", 0, 0)
        assert isinstance(s, int) and s != 0


# ------------------------------------------------ 计划结构 --------
class TestPlanStructureProfileBranch:
    def _b_payload(self, profile, blocks, mc):
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        payload["profile"] = profile
        payload["rules"]["audit_budgets"] = {
            "blocks_per_corpus": blocks, "mc_events": mc,
            "episodes_per_block": 8}
        return payload

    def test_formal_budgets_accepted(self):
        payload = self._b_payload("formal", 500, 1_000_000)
        assert research_plan_structure_problems(payload) == []

    def test_engineering_scale_cannot_masquerade_as_formal(self):
        problems = research_plan_structure_problems(
            self._b_payload("formal", 2, 4096))
        assert any("blocks_per_corpus" in p for p in problems)

    def test_formal_scale_cannot_downgrade_engineering(self):
        problems = research_plan_structure_problems(
            self._b_payload("engineering", 500, 1_000_000))
        assert any("blocks_per_corpus" in p for p in problems)

    def test_unknown_profile_rejected(self):
        problems = research_plan_structure_problems(
            self._b_payload("other", 500, 1_000_000))
        assert any("profile" in p for p in problems)

    def test_builder_output_is_structurally_clean(self):
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        assert research_plan_structure_problems(payload) == []
        assert payload["quota"] == formal_level_b_quota()


# ------------------------------------------------ 坐标锁 ----------
class TestCoordinateLockProfileBranch:
    def test_formal_namespace_locks_with_formal_budgets(
            self, tmp_path):
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        state = tmp_path / "state"
        freeze_research_plan(state, payload)
        from rl_curriculum.curriculum261_qprod_plan import (
            load_research_plan,
        )
        plan = load_research_plan(state)
        coord_dir = tmp_path / "coord_c01"
        coord_dir.mkdir()
        path, digest = lock_coordinate_audit_plan(
            coord_dir, coordinate=plan["coordinate_manifest"][0],
            research_plan=plan)
        cap = json.loads(path.read_text(encoding="utf-8"))
        assert digest.startswith("qcap-")
        assert cap["profile"] == "formal"
        assert cap["budgets"]["blocks_per_corpus"] == (
            FORMAL_BLOCKS_PER_CORPUS)
        assert cap["budgets"]["mc_events"] == FORMAL_MC_EVENTS
        assert cap["budgets"]["engineering_only"] is False

    def test_engineering_plan_rejects_formal_namespace(
            self, tmp_path):
        payload = {
            "format": "cur261-qprod-research-plan-v1",
            "level": "level_b",
            "iteration_id": "i1", "profile": "engineering",
            "code_freeze_sha": FREEZE_SHA,
            "coordinate_manifest": [{
                **dict(formal_coordinate_manifest()[0]),
                # 工程预算值(与 profile 一致),只保留正式 namespace
                # ——隔离"工程计划不接受正式 namespace"这一拒绝面。
                "blocks_per_corpus": 2, "mc_events": 4096,
            }],
            "rules": {
                "p0_fixed_reference": 0.9504,
                "p0_source_label": "t", "delta_definition":
                    "P0 - recall(validation)",
                "margin": 0.003, "alpha": 0.05, "r_analysis": 1.5,
                "planned_k": 11,
                "audit_budgets": {"blocks_per_corpus": 2,
                                  "mc_events": 4096,
                                  "episodes_per_block": 8}},
            "quota": {"max_leaf_calls_total": 640},
            "code_identity": qprod_coordinate_code_identity(),
            "stop_mode": "collect_all_k",
        }
        state = tmp_path / "state"
        freeze_research_plan(state, payload)
        from rl_curriculum.curriculum261_qprod_plan import (
            load_research_plan,
        )
        plan = load_research_plan(state)
        coord_dir = tmp_path / "coord_c01"
        coord_dir.mkdir()
        with pytest.raises(QProdContextError, match="未注册"):
            lock_coordinate_audit_plan(
                coord_dir, coordinate=plan["coordinate_manifest"][0],
                research_plan=plan)


# ------------------------------------------------ 部署配置 --------
class TestDeployConfigFailClosed:
    def test_env_redirect_refused(self, tmp_path, monkeypatch):
        from rl_curriculum.curriculum261_qprod_formal import (
            _read_formal_roots,
        )
        deploy, *_ = _make_deploy(tmp_path)
        monkeypatch.setenv("CURRICULUM261_QPROD_ART_ROOT",
                           str(tmp_path / "elsewhere"))
        with pytest.raises(QProdContextError, match="环境重定向"):
            _read_formal_roots(
                deploy, level="level_a",
                iteration_id=QPROD_FORMAL_LEVEL_A_ITERATION_ID)

    def test_not_formal_ready_refused(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_formal import (
            _read_formal_roots,
        )
        deploy, *_ = _make_deploy(tmp_path, mode="sandbox")
        with pytest.raises(QProdContextError, match="formal_ready"):
            _read_formal_roots(
                deploy, level="level_a",
                iteration_id=QPROD_FORMAL_LEVEL_A_ITERATION_ID)

    def test_missing_config_fail_closed(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_formal import (
            _read_formal_roots,
        )
        with pytest.raises(QProdContextError):
            _read_formal_roots(
                tmp_path / "empty", level="level_a",
                iteration_id=QPROD_FORMAL_LEVEL_A_ITERATION_ID)

    def test_authority_inside_roots_refused(self, tmp_path):
        from rl_curriculum.curriculum261_qprod_formal import (
            _read_formal_roots,
        )
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        cfg_path = deploy / "qprod_deploy_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        entry = cfg["formal_roots"][QPROD_FORMAL_LEVEL_B_ITERATION_ID]
        entry["authority_dir"] = str(state / "nested" / "authority")
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        with pytest.raises(QProdContextError, match="自授权"):
            _read_formal_roots(
                deploy, level="level_b",
                iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID)


# ------------------------------------------------ 许可/批准 -------
class TestFormalPermitBinding:
    def _ctx(self, tmp_path):
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        digest = research_plan_digest(payload)
        approval = _approval_payload(
            level="level_b", digest=digest, art=art, state=state,
            authority=authority, namespaces=_b_namespaces(),
            coordinate_ids=[c["coordinate_id"] for c in
                            formal_coordinate_manifest()],
            quota=payload["quota"])
        (authority / "qprod_formal_approval_level_b_"
         f"{QPROD_FORMAL_LEVEL_B_ITERATION_ID}.json").write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        ctx = build_formal_context(
            deploy, level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
            code_freeze_sha=FREEZE_SHA, research_plan_digest=digest,
            approval_digest=approval["approval_digest"])
        return ctx, approval, payload

    def test_valid_formal_permit_passes(self, tmp_path):
        ctx, approval, _payload = self._ctx(tmp_path)
        path = _write_formal_permit(ctx.authority_dir, ctx, approval)
        permit = validate_formal_permit(path, context=ctx)
        assert permit["issuer"]["kind"] == (
            "formal_admission_authority")

    def test_engineering_permit_cannot_serve_formal(self, tmp_path):
        ctx, approval, _payload = self._ctx(tmp_path)
        path = _write_formal_permit(
            ctx.authority_dir, ctx, approval,
            issuer={"kind": "engineering_test_authority",
                    "authority_id": AUTHORITY_ID})
        with pytest.raises(QProdContextError, match="不匹配"):
            validate_formal_permit(path, context=ctx)

    def test_formal_permit_cannot_serve_engineering(self, tmp_path):
        ctx, approval, _payload = self._ctx(tmp_path)
        path = _write_formal_permit(ctx.authority_dir, ctx, approval)
        # 同根同迭代的工程上下文消费正式许可:profile 绑定拒绝
        # (工程面不采正式签发来源)。
        eng_ctx = type(ctx)(
            **{f: getattr(ctx, f) for f in (
                "level", "iteration_id", "artifact_root", "state_root",
                "code_freeze_sha", "plan_identity", "permit_path",
                "authority_dir")},
            profile="engineering")
        with pytest.raises(QProdContextError, match="不匹配"):
            validate_permit(path, context=eng_ctx)

    def test_wrong_plan_digest_binding_refused(self, tmp_path):
        ctx, approval, _payload = self._ctx(tmp_path)
        path = _write_formal_permit(
            ctx.authority_dir, ctx, approval,
            research_plan_digest="qbpl-wrong")
        with pytest.raises(QProdContextError, match="错计划"):
            validate_formal_permit(path, context=ctx)

    @pytest.mark.parametrize("over,match", [
        ({"code_freeze_sha": "2" * 40}, "候"),
        ({"research_plan_digest": "qbpl-other"}, "计划"),
        ({"state_root": "/tmp/other-state"}, "根"),
        ({"artifact_root": "/tmp/other-art"}, "根"),
        ({"quota": {"max_leaf_calls_per_coordinate": 999999,
                    "max_successful_episodes_total": 999999,
                    "mc_events_per_coordinate": 10 ** 7,
                    "max_native_executions": 99}}, "额度"),
        ({"namespaces": ["cue_qprod_formal_v1_c01_model"]}, "范围"),
    ])
    def test_approval_wrong_binding_refused(self, tmp_path, over,
                                            match):
        """批准绑定逐项校验:错候选/计划/根/额度/范围全拒
        (validate_formal_approval 是 launch 门禁的绑定校验面)。"""
        ctx, approval, payload = self._ctx(tmp_path)
        approval["approved"].update(over)
        approval["approval_digest"] = formal_approval_digest(approval)
        with pytest.raises(QProdContextError, match=match):
            validate_formal_approval(
                approval, level="level_b",
                iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
                artifact_root=ctx.artifact_root,
                state_root=ctx.state_root,
                authority_dir=ctx.authority_dir,
                code_freeze_sha=FREEZE_SHA,
                research_plan_digest=research_plan_digest(payload),
                namespaces=_b_namespaces(),
                coordinate_ids=[c["coordinate_id"] for c in
                                formal_coordinate_manifest()],
                quota=payload["quota"])

    def test_tampered_approval_digest_refused(self, tmp_path):
        ctx, approval, _payload = self._ctx(tmp_path)
        approval["approval_digest"] = "qfap-tampered"
        (ctx.authority_dir / "qprod_formal_approval_level_b_"
         f"{QPROD_FORMAL_LEVEL_B_ITERATION_ID}.json").write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        path = _write_formal_permit(ctx.authority_dir, ctx, approval)
        with pytest.raises(QProdContextError, match="批准"):
            validate_formal_permit(path, context=ctx)


# ------------------------------------------------ Level A --------
class TestFormalLevelALaunch:
    def test_sentinel_stops_at_chain_executor_boundary(self, tmp_path,
                                                       monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        (deploy, art, state, authority, payload, digest, ctx) = (
            _setup_a(tmp_path, stop="qualify", model_update=False))
        before = _tree_files(tmp_path)
        result = launch_formal_level_a(
            deploy_root=deploy, project_dir=tmp_path / "project",
            code_freeze_sha=FREEZE_SHA,
            code_identity=payload["code_identity"],
            authorized_stop_after="qualify",
            model_update_authorized=False,
            sentinel_before_chain=True)
        assert result["sentinel_stopped"] is True
        handoff = json.loads(
            (art / "qprod_formal_launch_handoff.json").read_text(
                encoding="utf-8"))
        # 真实业务入口解析:停止边界=qualify ⇒ _chain-bounded 子模块
        assert "curriculum261_qprod_formal_levela" in " ".join(
            handoff["argv"])
        assert handoff["sentinel"]["steps_executed"] == 0
        assert handoff["env_identity"][
            "CURRICULUM261_R17_DEPLOYED_STATE_ROOT"] == str(state)
        assert "CURRICULUM261_R17_STATE_ROOT" in handoff[
            "env_identity"]["stripped"]
        # run-plan 已冻结且 digest 与批准一致
        frozen = json.loads(
            (state / "qprod_research_plan.json").read_text(
                encoding="utf-8"))
        assert frozen["research_plan_digest"] == digest
        # 会话 journal:获取+许可消费+诚实中断+释放;无终态 PASS
        journal = [
            json.loads(ln) for ln in
            (state / "qprod_run_journal.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        events = [e["event"] for e in journal]
        assert events == ["session_acquired", "permit_consumed",
                          "interruption_recorded", "session_released"]
        # 零业务执行:链产物不存在
        assert not (art / "r17_bootstrap_accepted.json").exists()
        assert not (art / "r17_workflow_plan_formal.json").exists()
        assert not (art / "r17_chain_result.json").exists()

    def test_full_chain_argv_uses_authoritative_chain_run(
            self, tmp_path, monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        (deploy, art, state, authority, payload, digest, ctx) = (
            _setup_a(tmp_path, stop="verify-formal-logs",
                     model_update=True))
        result = launch_formal_level_a(
            deploy_root=deploy, project_dir=tmp_path / "project",
            code_freeze_sha=FREEZE_SHA,
            code_identity=payload["code_identity"],
            authorized_stop_after="verify-formal-logs",
            model_update_authorized=True,
            sentinel_before_chain=True)
        handoff = json.loads(
            (art / "qprod_formal_launch_handoff.json").read_text(
                encoding="utf-8"))
        argv = " ".join(handoff["argv"])
        assert "curriculum261_r17_cli" in argv
        assert "chain-run" in argv

    def test_no_approval_refused_before_any_side_effect(
            self, tmp_path, monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority, payload, digest, ctx = (
            _setup_a(tmp_path))
        (authority / "qprod_formal_approval_level_a_"
         f"{QPROD_FORMAL_LEVEL_A_ITERATION_ID}.json").unlink()
        # A2-R2 新契约:沙箱预装钉死 provenance(见 _setup_a),
        # 整树移除以保持"拒绝前零受控副作用"前提(非空 rmdir 改
        # rmtree;移除的是 fixture 预装面,不是 launch 写入)。
        import shutil as _shutil
        _shutil.rmtree(art) if art.exists() else None
        with pytest.raises(FormalLaunchRefused, match="批准"):
            launch_formal_level_a(
                deploy_root=deploy, project_dir=tmp_path / "project",
                code_freeze_sha=FREEZE_SHA,
                code_identity=payload["code_identity"],
                authorized_stop_after="qualify",
                model_update_authorized=False)
        # 零受控副作用:正式根未创建、无 journal、无计划冻结
        assert not (state / "qprod_run_journal.jsonl").exists()
        assert not (state / "qprod_research_plan.json").exists()
        assert not art.exists()

    def test_no_admission_refused(self, tmp_path, monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority, payload, digest, ctx = (
            _setup_a(tmp_path, admission=False))
        with pytest.raises(FormalLaunchRefused, match="admission"):
            launch_formal_level_a(
                deploy_root=deploy, project_dir=tmp_path / "project",
                code_freeze_sha=FREEZE_SHA,
                code_identity=payload["code_identity"],
                authorized_stop_after="qualify",
                model_update_authorized=False)
        assert not (state / "qprod_run_journal.jsonl").exists()

    def test_pseudo_freeze_sha_refused(self, tmp_path, monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority, payload, digest, ctx = (
            _setup_a(tmp_path))
        with pytest.raises(FormalLaunchRefused, match="commit"):
            launch_formal_level_a(
                deploy_root=deploy, project_dir=tmp_path / "project",
                code_freeze_sha="qprod-eng-deadbeef",
                code_identity=payload["code_identity"],
                authorized_stop_after="qualify",
                model_update_authorized=False)

    def test_stale_state_refused_before_writes(self, tmp_path,
                                               monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority, payload, digest, ctx = (
            _setup_a(tmp_path))
        state.mkdir(parents=True, exist_ok=True)
        (state / "qprod_run_journal.jsonl").write_text(
            json.dumps({"event": "session_acquired"}) + "\n",
            encoding="utf-8")
        with pytest.raises(FormalLaunchRefused, match="非新鲜"):
            launch_formal_level_a(
                deploy_root=deploy, project_dir=tmp_path / "project",
                code_freeze_sha=FREEZE_SHA,
                code_identity=payload["code_identity"],
                authorized_stop_after="qualify",
                model_update_authorized=False)

    def test_stop_full_chain_requires_model_update(self):
        with pytest.raises(QProdContextError, match="smoke"):
            build_formal_level_a_plan(
                code_freeze_sha=FREEZE_SHA,
                code_identity=qprod_coordinate_code_identity(),
                authorized_stop_after="verify-formal-logs",
                model_update_authorized=False)

    def test_stop_qualify_rejects_model_update_flag(self):
        with pytest.raises(QProdContextError, match="不一致"):
            build_formal_level_a_plan(
                code_freeze_sha=FREEZE_SHA,
                code_identity=qprod_coordinate_code_identity(),
                authorized_stop_after="qualify",
                model_update_authorized=True)

    def test_approval_stop_boundary_must_match(self, tmp_path,
                                               monkeypatch):
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT",
                    "CURRICULUM261_R17_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        # 批准 stop=qualify,请求按完整链:拒绝
        deploy, art, state, authority, payload, digest, ctx = (
            _setup_a(tmp_path, stop="qualify"))
        with pytest.raises((FormalLaunchRefused, QProdContextError)):
            launch_formal_level_a(
                deploy_root=deploy, project_dir=tmp_path / "project",
                code_freeze_sha=FREEZE_SHA,
                code_identity=payload["code_identity"],
                authorized_stop_after="verify-formal-logs",
                model_update_authorized=True,
                sentinel_before_chain=True)

    def test_smoke_blocked_when_qualification_fail_or_missing(
            self, tmp_path, monkeypatch):
        """F09:权威执行器 postcondition——资格 FAIL/缺件 ⇒ smoke
        步零 subprocess 拒绝(real executor,真前置判定)。"""
        from rl_curriculum.curriculum261_r17_execgov import (
            R17ChainSession,
        )
        from rl_curriculum.curriculum261_r17_workflow import (
            build_workflow_plan_r17, execute_workflow_chain_r17,
        )
        out_dir = tmp_path / "chain_out"
        for verdict in ("FAIL", None):
            tag = verdict or "missing"
            monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                               str(tmp_path / f"r17state_{tag}"))
            out = out_dir / tag
            plan = build_workflow_plan_r17(
                "formal", out_dir=str(out),
                freeze_sha=FREEZE_SHA)
            plan["steps"] = [s for s in plan["steps"]
                             if s["name"] == "smoke"]
            if verdict:
                out.mkdir(parents=True, exist_ok=True)
                (out / "qualification_result.json").write_text(
                    json.dumps({"verdict": verdict}),
                    encoding="utf-8")
            session = R17ChainSession.acquire({
                "mode": "test", "out_dir": str(out)})
            result = execute_workflow_chain_r17(
                plan, session=session,
                log_dir=tmp_path / "logs" / tag)
            session.release()
            rec = result["records"][0]
            assert rec["step"] == "smoke"
            assert rec["rc"] == 2
            assert rec["effective_result"] == "failed"
            assert not (out / "ppo_256step_smoke.json").exists()

    def test_bounded_plan_marks_not_run_steps(self):
        from rl_curriculum.curriculum261_r17_workflow import (
            build_workflow_plan_r17,
        )
        plan = build_workflow_plan_r17(
            "formal", out_dir="/tmp/x", freeze_sha=FREEZE_SHA)
        bounded = bound_workflow_plan_r17(json.loads(json.dumps(
            plan)), "qualify")
        names = [s["name"] for s in bounded["steps"]]
        assert names[-1] == "verify-formal-logs"
        assert "qualify" in names
        assert "smoke" not in names
        assert bounded["not_run_steps"] == [
            "smoke", "full-cold", "report-read"]
        verify = bounded["steps"][-1]
        assert verify["argv"][
            verify["argv"].index("--stopped-at") + 1] == "qualify"


# ------------------------------------------------ Level B --------
class TestFormalLevelBPreflight:
    def test_manifest_walk_zero_generation_repeatable(self,
                                                      tmp_path):
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        r1 = preflight_formal_level_b(
            deploy, code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        assert r1["deployment_ok"] is True
        assert r1["plan_structure_problems"] == []
        assert r1["quota_covers_needs"] is True
        assert len(r1["coordinates"]) == 11
        assert all(c["namespace_ok"] for c in r1["coordinates"])
        assert r1["status"] == "PREPARED_PENDING_USER_APPROVAL"
        # 范围取自计划而非报告:坐标集合与权威清单一致
        assert [c["coordinate_id"] for c in r1["coordinates"]] == [
            c["coordinate_id"] for c in formal_coordinate_manifest()]
        r2 = preflight_formal_level_b(
            deploy, code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        assert r1["content_identity"] == r2["content_identity"]

    def test_preflight_zero_side_effects(self, tmp_path):
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        before = _tree_files(tmp_path)
        preflight_formal_level_b(
            deploy, code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        preflight_formal_level_a(
            deploy, code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        assert _tree_files(tmp_path) == before

    def test_preflight_without_config_reports_not_deployed(
            self, tmp_path):
        r = preflight_formal_level_b(
            tmp_path / "empty", code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        assert r["deployment_ok"] is False
        assert any("deployment" in f for f in r["findings"])
        assert r["status"] == "FINDINGS_PRESENT"


class TestFormalLevelBRunCoordinate:
    def test_runs_to_real_audit_core_with_sentinel_leaf(
            self, tmp_path, monkeypatch):
        """F03 正例:真实锁/许可/账本/失败收口 + 叶哨兵停止。"""
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT"):
            monkeypatch.delenv(var, raising=False)
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        digest = research_plan_digest(payload)
        approval = _approval_payload(
            level="level_b", digest=digest, art=art, state=state,
            authority=authority, namespaces=_b_namespaces(),
            coordinate_ids=[c["coordinate_id"] for c in
                            formal_coordinate_manifest()],
            quota=payload["quota"])
        (authority / "qprod_formal_approval_level_b_"
         f"{QPROD_FORMAL_LEVEL_B_ITERATION_ID}.json").write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        ctx = build_formal_context(
            deploy, level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
            code_freeze_sha=FREEZE_SHA, research_plan_digest=digest,
            approval_digest=approval["approval_digest"])
        _write_formal_permit(authority, ctx, approval)
        # 受控写:冻结计划 + 锁 c01 + 消费许可 + 原生预算
        from rl_curriculum.curriculum261_qprod_context import (
            harden_root,
        )
        from rl_curriculum.curriculum261_qprod_permit import (
            consume_permit,
        )
        harden_root(state, label="state_root", create=True)
        harden_root(art, label="artifact_root", create=True)
        freeze_research_plan(state, payload)
        from rl_curriculum.curriculum261_qprod_plan import (
            load_research_plan,
        )
        plan = load_research_plan(state)
        coord = plan["coordinate_manifest"][0]
        coord_dir = art / coord["artifact_subdir"]
        coord_dir.mkdir(parents=True)
        lock_coordinate_audit_plan(
            coord_dir, coordinate=coord, research_plan=plan)
        consume_permit(ctx.permit_path, context=ctx)
        (state / "qprod_native_budget.json").write_text(json.dumps(
            {"max_runs": 11, "consumed_runs": 0}), encoding="utf-8")
        # 叶哨兵:替换昂贵生成叶(测试允许的叶层);锁/许可/账本/
        # 失败收口保持真实实现。
        import rl_curriculum.curriculum261_r6_tape as tape_mod
        from rl_curriculum.curriculum261_r6_tape import (
            derive261_block_seed,
        )
        captured: list[dict] = []

        class SentinelStop(BaseException):
            pass

        def sentinel_once(ladder, seed, ns):
            captured.append({"fn": "generate_matched_block_once",
                             "seed": int(seed), "ns": ns})
            raise SentinelStop("boundary sentinel")

        monkeypatch.setattr(
            tape_mod, "generate_matched_block_once", sentinel_once)
        from rl_curriculum.curriculum261_qprod_coordinate import (
            run_coordinate_audit_locked,
        )
        from rl_curriculum.curriculum261_qprod_permit import (
            LivePermitToken, load_permit,
        )
        permit = load_permit(ctx.permit_path)
        live = LivePermitToken(
            permit, {"consumed_via": "consume-permit"})
        with pytest.raises(SentinelStop):
            run_coordinate_audit_locked(
                ctx, live, "c01", coord_dir=coord_dir,
                ledger_path=art.parent / "qprod_quota_ledger.jsonl")
        # 真实核心已到达 formal 参数:namespace 与 block 0 seed
        assert captured[0]["ns"] == "cue_qprod_formal_v1_c01_model"
        assert captured[0]["seed"] == derive261_block_seed(
            "cue_qprod_formal_v1_c01_model", 0, 0)
        # 诚实中断标记 + 账本行;无 seal、无审计报告原件
        assert (coord_dir / "qprod_coordinate_interrupted.json"
                ).is_file()
        assert not (coord_dir / "qprod_coordinate_seal.json").exists()
        assert not (coord_dir / "cue_contract_audit.json").exists()
        ledger_lines = [
            json.loads(ln) for ln in
            (art.parent / "qprod_quota_ledger.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        actions = [l["action"] for l in ledger_lines]
        assert "start" in actions
        assert "interrupted" in actions

    def test_insufficient_positive_quota_refused_before_generation(
            self, tmp_path):
        """F08:正数但不足额度 ⇒ 动作前拒绝(错误更小正数不被
        忽略)。"""
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        from rl_curriculum.curriculum261_qprod_context import (
            harden_root,
        )
        harden_root(state, label="state_root", create=True)
        harden_root(art, label="artifact_root", create=True)
        freeze_research_plan(state, payload)
        from rl_curriculum.curriculum261_qprod_plan import (
            load_research_plan,
        )
        plan = load_research_plan(state)
        coord = plan["coordinate_manifest"][0]
        coord_dir = art / coord["artifact_subdir"]
        coord_dir.mkdir(parents=True)
        lock_coordinate_audit_plan(
            coord_dir, coordinate=coord, research_plan=plan)

        class _FakePermit:
            permit = {
                "task_level": "level_b",
                "preregistered_input_scope": {
                    "namespaces": _b_namespaces()},
                "quota": {
                    "max_leaf_calls_per_coordinate": 5,
                    "max_successful_episodes_total": 8000,
                    "mc_events_per_coordinate": 999_999,
                    "max_native_executions": 11},
            }

            @property
            def quota(self):
                return dict(self.permit["quota"])

        from rl_curriculum.curriculum261_qprod_coordinate import (
            run_coordinate_audit_locked,
        )
        ctx = build_formal_context(
            deploy, level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
            code_freeze_sha=FREEZE_SHA,
            research_plan_digest=plan["research_plan_digest"],
            approval_digest="qfap-x")
        with pytest.raises(QProdContextError,
                           match="不足以覆盖需求"):
            run_coordinate_audit_locked(
                ctx, _FakePermit(), "c01", coord_dir=coord_dir,
                ledger_path=tmp_path / "ledger.jsonl")
        refusal = json.loads(
            (art / "refusal_c01.json").read_text(encoding="utf-8"))
        assert refusal["leaf_calls_snapshot"][
            "leaf_calls_total"] == 0


# ------------------------------------------------ authority CLI --
def _find_runner_dir() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parents[2] / "stage2_6_1_runner",
                 here.parents[2] / "runner",
                 here.parents[2] / "stage2_6_1" / "runner"):
        if (cand / "qprod_formal_authority.py").is_file():
            return cand
    return here.parents[2] / "runner"


class TestFormalAuthorityCli:
    def test_issue_requires_approval_and_binds_it(self, tmp_path):
        runner = _find_runner_dir() / "qprod_formal_authority.py"
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        authority = tmp_path / "authority_ops"
        # 权威根换到操作员目录(测试域)
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        digest = research_plan_digest(payload)
        cfg_path = deploy / "qprod_deploy_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        entry = cfg["formal_roots"][QPROD_FORMAL_LEVEL_B_ITERATION_ID]
        entry["authority_dir"] = str(authority)
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(runner), "init", "--dir",
             str(authority)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        # 无批准:拒签(rc=96)
        r = subprocess.run(
            [sys.executable, str(runner), "issue-permit", "--dir",
             str(authority), "--deploy-root", str(deploy),
             "--task-level", "level_b"], capture_output=True,
            text=True)
        assert r.returncode == 96
        assert "批准" in r.stdout
        approval = _approval_payload(
            level="level_b", digest=digest, art=art, state=state,
            authority=authority, namespaces=_b_namespaces(),
            coordinate_ids=[c["coordinate_id"] for c in
                            formal_coordinate_manifest()],
            quota=payload["quota"])
        approval_path = tmp_path / "approval_in.json"
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(runner), "record-approval", "--dir",
             str(authority), "--approval-json", str(approval_path)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        r = subprocess.run(
            [sys.executable, str(runner), "issue-permit", "--dir",
             str(authority), "--deploy-root", str(deploy),
             "--task-level", "level_b"], capture_output=True,
            text=True)
        assert r.returncode == 0, r.stderr
        permit = json.loads(r.stdout)
        permit_doc = json.loads(
            Path(permit["permit_path"]).read_text(encoding="utf-8"))
        assert permit_doc["issuer"]["kind"] == (
            "formal_admission_authority")
        assert permit_doc["approval_digest"] == approval[
            "approval_digest"]
        # 重复签发:create-only 拒绝
        r = subprocess.run(
            [sys.executable, str(runner), "issue-permit", "--dir",
             str(authority), "--deploy-root", str(deploy),
             "--task-level", "level_b"], capture_output=True,
            text=True)
        assert r.returncode == 1

    def test_tampered_approval_rejected(self, tmp_path):
        runner = _find_runner_dir() / "qprod_formal_authority.py"
        deploy, art, state, authority = _make_deploy(
            tmp_path, level="level_b")
        authority = tmp_path / "authority_ops"
        cfg_path = deploy / "qprod_deploy_config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["formal_roots"][QPROD_FORMAL_LEVEL_B_ITERATION_ID][
            "authority_dir"] = str(authority)
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(runner), "init", "--dir",
             str(authority)], capture_output=True, text=True)
        payload = build_formal_level_b_plan(
            code_freeze_sha=FREEZE_SHA,
            code_identity=qprod_coordinate_code_identity())
        approval = _approval_payload(
            level="level_b",
            digest=research_plan_digest(payload), art=art,
            state=state, authority=authority,
            namespaces=_b_namespaces(),
            coordinate_ids=[c["coordinate_id"] for c in
                            formal_coordinate_manifest()],
            quota=payload["quota"])
        approval["approved"]["quota"] = {
            "max_leaf_calls_per_coordinate": 10 ** 9,
            "max_successful_episodes_total": 10 ** 9,
            "mc_events_per_coordinate": 10 ** 9,
            "max_native_executions": 10 ** 9}
        approval_path = tmp_path / "approval_in.json"
        approval_path.write_text(
            json.dumps(approval, ensure_ascii=False),
            encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(runner), "record-approval", "--dir",
             str(authority), "--approval-json", str(approval_path)],
            capture_output=True, text=True)
        assert r.returncode == 1
        assert "digest" in r.stdout
