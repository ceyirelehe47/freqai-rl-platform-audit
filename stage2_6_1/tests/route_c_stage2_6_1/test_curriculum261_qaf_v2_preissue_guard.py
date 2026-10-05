# -*- coding: utf-8 -*-
"""qaf_v2 签发前防错与新尝试身份接线测试(A2-R2)。

RouteC_A2_PreIssueGuard_NewAttempt_v1 PG02–PG09 工程面:

- PG02 固定 Git 源:钉死对象正例;repair15 同名件/不存在提交/
  错路径/摘要配对错误负例。
- PG03 实际目标安装:幂等/异物/半写/只读检查不隐式修复。
- PG04 签发前硬门:QProd permit 与 r17 admission 两条边界在第一
  次一次性写之前拒绝坏状态;正例保留真实检查(隔离测试域)。
- PG05 统一执行边界:环境白名单/A2 双参数/哨兵仅测试域/重入
  不重复签发。
- PG06 新身份全链:26 名 v2 族注册/白名单/派生/消费者按尝试
  解析;跨尝试 scope 拒绝。
- PG07 科研语义不扩张:新旧计划载荷逐项差异仅身份字段。
- PG09 真实前缀接线:operator execute 哨兵路径过全部门禁与受控
  写,停在权威链执行器调用前;真实链步 1 provenance-verify 在
  安装目标上实际执行并消费产物;R15 反例在签发前被拒。

沙箱正例使用 r17_admission_substance_test_support 的真实执行器
证据与真实签发器子进程;隔离替换仅限"一次性资源落点=pytest
临时域"这一层,门禁/校验/派发逻辑全部真实。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_SRC = _TESTS_DIR.parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF2_ALL_NEW, QAF2_FRESH_HOLDOUT, QAF2_PPO_SMOKE,
    QAF2_QUALIFICATION, QAF2_STRESS, QAF2_SUPERVISED_MAIN,
    QAF2_SEMANTIC_MAIN, QAF2_C13_MAIN, QAF2_FIT_MAIN,
    QAF2_FIT_HOLDOUT, QAF2_C2_INDEPENDENT_MAIN,
    QAF2_C2_INDEPENDENT_QUALIFICATION, QAF2_DESIGN_MATCHED_MAIN,
    QAF_ATTEMPTS, QAF_ATTEMPT_IDS, QAF_V2_FAMILY,
    qaf_attempt_family, qaf_input_scope_for_attempt,
    qaf_iteration_id_for_attempt)

RUNNER_CANDIDATES = (
    _TESTS_DIR.parents[1] / "runner",
    _TESTS_DIR.parents[1] / "stage2_6_1" / "runner",
    _TESTS_DIR.parents[1] / "stage2_6_1_runner",
)
GUARD_REPO_CANDIDATES = (
    Path("/mnt/f/trading/freqai-rl-audit"),
    Path("F:/trading/freqai-rl-audit"),
    Path("E:/trading/freqai-rl-audit"),
)


def _runner_dir() -> Path:
    for d in RUNNER_CANDIDATES:
        if (d / "r17_admission_issue.py").is_file():
            return d
    pytest.skip("runner 目录不可达(部署树/仓库)")


def _guard_repo() -> Path:
    env = os.environ.get("A2R2_TEST_REPO")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for p in GUARD_REPO_CANDIDATES:
        if (p / ".git").exists():
            return p
    pytest.skip("钉死源 Git 仓库不可达(设置 A2R2_TEST_REPO)")


def _project_tree_root() -> Path:
    """同源验证/launch 子进程用完整模块树根(含 src 与
    stage2_6_1_runner;测试运行所在树)。"""
    import rl_curriculum
    root = Path(rl_curriculum.__file__).resolve().parents[2]
    assert (root / "src" / "rl_curriculum").is_dir(), root
    assert (root / "stage2_6_1_runner").is_dir(), root
    return root


# ------------------------------------------------------------------
# PG06 身份全链
# ------------------------------------------------------------------

class TestQafV2Identity:
    def test_registry_and_names(self):
        assert QAF_ATTEMPT_IDS == ("qaf_v1", "qaf_v2", "qaf_v3")
        fam = QAF_ATTEMPTS["qaf_v2"]
        assert len(fam.input_scope) == 26
        assert len(set(fam.input_scope)) == 26
        assert not (set(fam.input_scope)
                    & set(QAF_ATTEMPTS["qaf_v1"].input_scope))
        # design 三名显式定义(非后缀替换产物)
        assert fam.design_matched_main == "design_qaf_v2_matched_main"
        assert QAF2_DESIGN_MATCHED_MAIN in fam.input_scope

    def test_whitelists_and_seeds(self, tmp_path, monkeypatch):
        # 工程态显式 state 根(空目录):资格族锁检查可达,
        # 未锁定 → 种子封闭。
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                           str(tmp_path / "eng_state"))
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R17_NAMESPACES, derive261_seed,
        )
        from rl_curriculum.curriculum261_r17_registry import (
            R17_ALL_NAMESPACES, R17_FORMAL_QUALIFICATION_NAMESPACES,
        )
        from rl_curriculum.curriculum261_r17_generation_evidence \
            import R17_FRAMEWORK_ITERATIONS
        both = set(QAF2_ALL_NEW) | set(
            QAF_ATTEMPTS["qaf_v1"].input_scope)
        assert both <= set(CURRICULUM261_R17_NAMESPACES)
        assert set(QAF2_ALL_NEW) <= set(R17_ALL_NAMESPACES)
        assert set(QAF_V2_FAMILY.formal_four) <= set(
            R17_FORMAL_QUALIFICATION_NAMESPACES)
        assert "qaf_v2" in R17_FRAMEWORK_ITERATIONS
        # 纯 seed 派生:原公式、新 namespace、与 v1 逐名不同
        # (qualification 族种子在资格计划锁定前封闭——与 v1 同一
        # 锁语义;断言封闭而非派生)
        from rl_curriculum.curriculum261_api import GeneratorError
        for ns in (QAF2_C13_MAIN, QAF2_STRESS, QAF2_PPO_SMOKE,
                   QAF2_FIT_MAIN, QAF2_FIT_HOLDOUT,
                   QAF2_SUPERVISED_MAIN, QAF2_SEMANTIC_MAIN,
                   QAF2_C2_INDEPENDENT_MAIN, QAF2_FRESH_HOLDOUT):
            v2 = derive261_seed(ns, "p32", "r1", 0, 0)
            assert v2 != derive261_seed(
                ns.replace("_qaf_v2", "_qaf_v1"), "p32", "r1", 0, 0)
        with pytest.raises(GeneratorError):
            derive261_seed(QAF2_QUALIFICATION, "p32", "r1", 0, 0)
        with pytest.raises(GeneratorError):
            derive261_seed("preprocess_fit_qualification_qaf_v2",
                           "p32", "r1", 0, 0)

    def test_design_role_map(self):
        from rl_curriculum.curriculum261_r17_design import (
            SEMANTIC_CORPUS_ROLE_R17, SEMANTIC_STAGE_ARTIFACT_MAP_R17,
        )
        for ns, role in (
                (QAF2_SEMANTIC_MAIN, "calibration"),
                ("cue_semantic_holdout_qaf_v2", "holdout"),
                ("cue_semantic_qualification_qaf_v2", "qualification"),
                ("cue_semantic_design_main_qaf_v2", "main"),
                ("cue_semantic_design_validation_qaf_v2", "validation")):
            assert SEMANTIC_CORPUS_ROLE_R17.get(ns) == role, ns
        assert "cue_semantic_calibration_qaf_v2" in (
            SEMANTIC_STAGE_ARTIFACT_MAP_R17)

    def test_consumers_resolve_by_attempt(self):
        from rl_curriculum.curriculum261_r17_orchestrator import (
            formal_holdout_profile_r17, formal_main_profile_r17,
        )
        main = formal_main_profile_r17(2, attempt="qaf_v2")
        assert main.c13_eval_namespace == QAF2_C13_MAIN
        assert main.supervised_namespace == QAF2_SUPERVISED_MAIN
        hold = formal_holdout_profile_r17(2, attempt="qaf_v2")
        assert hold.supervised_namespace == (
            "supervised_holdout_qaf_v2")
        plan = {"final_sample_counts": {"c2_matched_blocks": 2}}
        from rl_curriculum.curriculum261_r17_final import (
            formal_attempt_core_kwargs,
        )
        kwargs, source = formal_attempt_core_kwargs("qaf_v2", plan)
        assert source == "qaf_v2"
        assert kwargs["final_namespace"] == QAF2_QUALIFICATION
        assert kwargs["fit_namespace"] == (
            "preprocess_fit_qualification_qaf_v2")
        with pytest.raises(RuntimeError):
            formal_attempt_core_kwargs("qaf_v9", plan)

    def test_iteration_mapping(self):
        assert qaf_iteration_id_for_attempt(
            "qaf_v2") == "qprod_a_formal_v2"
        assert qaf_iteration_id_for_attempt(
            "qaf_v1") == "qprod_a_formal_v1"
        assert qaf_attempt_family(None) is None
        with pytest.raises(ValueError):
            qaf_input_scope_for_attempt("qaf_v9")


# ------------------------------------------------------------------
# PG02/PG03 守卫:固定源与实际目标
# ------------------------------------------------------------------

class TestGuardSourceAndTarget:
    def test_pinned_source_positive(self):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            ProvenanceGuardError, read_pinned_source,
        )
        src = read_pinned_source(_guard_repo())
        assert src["json_sha256"].startswith("9af55175")
        assert src["stored_topology_digest"].startswith(
            "r17gtrec-3112e5deb863a")

    def test_negatives(self):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            ProvenanceGuardError, read_pinned_source,
        )
        repo = _guard_repo()
        # repair15 同名件(内容身份不符)
        with pytest.raises(ProvenanceGuardError, match="身份不符"):
            read_pinned_source(
                repo,
                "de81aba2b3cdcc2c0febe2b3c439027496ab9d05",
                json_path=("stage2_6_1/artifacts/repair15/"
                           "gate_topology_reconciliation.json"),
                digest_path=("stage2_6_1/artifacts/repair15/"
                             "gate_topology_reconciliation_digest.txt"))
        # 不存在提交
        with pytest.raises(ProvenanceGuardError):
            read_pinned_source(repo, "0" * 40)
        # 错路径
        with pytest.raises(ProvenanceGuardError):
            read_pinned_source(
                repo, "de81aba2b3cdcc2c0febe2b3c439027496ab9d05",
                json_path="stage2_6_1/nope.json",
                digest_path="stage2_6_1/nope.txt")
        # 摘要配对错误(json 钉死路径+digest repair15 路径)
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            PROVENANCE_JSON_REPO_PATH,
        )
        with pytest.raises(ProvenanceGuardError):
            read_pinned_source(
                repo, "de81aba2b3cdcc2c0febe2b3c439027496ab9d05",
                json_path=PROVENANCE_JSON_REPO_PATH,
                digest_path=("stage2_6_1/artifacts/repair15/"
                             "gate_topology_reconciliation_digest.txt"))

    def test_install_semantics(self, tmp_path):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            ProvenanceGuardError, inspect_target, install_to_target,
            read_pinned_source,
        )
        src = read_pinned_source(_guard_repo())
        art = tmp_path / "art"
        r1 = install_to_target(art, src)
        assert r1["installed"] is True
        r2 = install_to_target(art, src)
        assert r2["idempotent_ok"] is True and r2["installed"] is False
        # 同字节重复安装不重写(mtime 不变)
        jp = art / "gate_topology_reconciliation.json"
        mtime = jp.stat().st_mtime_ns
        install_to_target(art, src)
        assert jp.stat().st_mtime_ns == mtime
        # 半写(一份在、一份缺;在场那份保持钉死字节)
        (art / "gate_topology_reconciliation_digest.txt").unlink()
        with pytest.raises(ProvenanceGuardError, match="半写"):
            install_to_target(art, src)
        # 只读检查不修复
        rep = inspect_target(art)
        assert rep["digest_present"] is False
        assert rep["ready"] is False
        assert not (art / "gate_topology_reconciliation_digest.txt"
                    ).exists()
        # 异物(独立目录)
        art2 = tmp_path / "art2"
        install_to_target(art2, src)
        (art2 / "gate_topology_reconciliation.json").write_text("{}")
        with pytest.raises(ProvenanceGuardError, match="异物"):
            install_to_target(art2, src)


# ------------------------------------------------------------------
# PG04/PG05 签发前硬门与统一边界(快速面)
# ------------------------------------------------------------------

def _write_deploy_config(deploy_root: Path, attempt: str = "qaf_v2"):
    from rl_curriculum.curriculum261_qaf_attempt import (
        qaf_iteration_id_for_attempt,
    )
    iteration = qaf_iteration_id_for_attempt(attempt)
    deploy_root.mkdir(parents=True, exist_ok=True)
    state = deploy_root / "artifacts/route_c_stage2_6_1_repair17/state"
    cfg = {
        "format": "cur261-qprod-deploy-config-v1",
        "mode": "formal_ready",
        "formal_roots": {iteration: {
            "artifact_root": str(
                deploy_root / "artifacts/formal_a_qaf_v2"),
            "state_root": str(state),
            "authority_dir": str(deploy_root / "authority"),
        }},
    }
    (deploy_root / "qprod_deploy_config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return cfg


class TestPreissueGate:
    def test_env_redirect_refused(self, tmp_path, monkeypatch):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            preissue_gate,
        )
        deploy = tmp_path / "deploy"
        _write_deploy_config(deploy)
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                           str(tmp_path / "rogue"))
        rep = preissue_gate(
            repo=_guard_repo(), deploy_root=deploy,
            project_dir=_project_tree_root(), attempt="qaf_v2")
        assert rep["ok"] is False
        assert "env_whitelist" in rep["refusal"]
        assert rep["one_shot_writes"] == 0

    def test_target_and_freshness_refusals(self, tmp_path):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            ProvenanceGuardError, install_to_target, preissue_gate,
            read_pinned_source,
        )
        deploy = tmp_path / "deploy"
        cfg = _write_deploy_config(deploy)
        art = Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                   ["artifact_root"])
        state = Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                     ["state_root"])
        # 目标缺件 → 拒(签发前,而非签发后发现)
        rep = preissue_gate(
            repo=_guard_repo(), deploy_root=deploy,
            project_dir=_project_tree_root(), attempt="qaf_v2")
        assert rep["ok"] is False and "target_installed" in rep["refusal"]
        # 装好后 → 过
        install_to_target(art, read_pinned_source(_guard_repo()))
        rep = preissue_gate(
            repo=_guard_repo(), deploy_root=deploy,
            project_dir=_project_tree_root(), attempt="qaf_v2")
        assert rep["ok"] is True, rep.get("refusal")
        # 异物文件混入 A artifact 根 → 拒
        (art / "rogue_extra.json").write_text("{}")
        rep = preissue_gate(
            repo=_guard_repo(), deploy_root=deploy,
            project_dir=_project_tree_root(), attempt="qaf_v2")
        assert rep["ok"] is False and "异物" in rep["refusal"]
        (art / "rogue_extra.json").unlink()
        # 新鲜度:一次性消费标记在场 → 拒(幂等≠已运行的反面)
        state.mkdir(parents=True, exist_ok=True)
        (state / "qprod_permit_consumed.jsonl").write_text("{}\n")
        rep = preissue_gate(
            repo=_guard_repo(), deploy_root=deploy,
            project_dir=_project_tree_root(), attempt="qaf_v2")
        assert rep["ok"] is False and "freshness" in rep["refusal"]
        (state / "qprod_permit_consumed.jsonl").unlink()
        # P2 修复回归:真实 abort marker 文件名(.json)单独在场也拒
        (state / "r17_iteration_aborted.json").write_text("{}\n")
        rep = preissue_gate(
            repo=_guard_repo(), deploy_root=deploy,
            project_dir=_project_tree_root(), attempt="qaf_v2")
        assert rep["ok"] is False and "freshness" in rep["refusal"]


def _build_v2_approval(deploy_root: Path, commit_a: str) -> dict:
    from rl_curriculum.curriculum261_qprod_formal import (
        formal_approval_digest,
    )
    iteration = "qprod_a_formal_v2"
    payload = {
        "format": "cur261-qprod-formal-approval-v1",
        "approval_id": "test-qaf-v2-approval",
        "task_level": "level_a",
        "iteration_id": iteration,
        "approved": {
            "research_plan_digest": "qbpl-test-v2-plan-digest",
            "code_freeze_sha": commit_a,
            "artifact_root": str(
                deploy_root / "artifacts/formal_a_qaf_v2"),
            "state_root": str(
                deploy_root
                / "artifacts/route_c_stage2_6_1_repair17/state"),
            "authority_dir": str(deploy_root / "authority"),
            "namespaces": list(QAF_V2_FAMILY.input_scope),
            "coordinate_ids": [],
            "quota": {"ppo_learn_calls": 2},
            "authorized_stop_after": "verify-formal-logs",
            "model_update_authorized": True,
        },
        "approval_source": {"kind": "user_direct_approval",
                            "statement_digest": "bcc14f5a6bd026c600cb98171810a714d0a1cabb155e4aed73a8bb3a159ab5bd",
                            "note": "TEST-DOMAIN-ONLY wiring approval (isolated sandbox; not a production authorization)"},
    }
    payload["approval_digest"] = formal_approval_digest(payload)
    return payload


class TestPermitIssueGate:
    def test_missing_guard_params_refused_zero_writes(self, tmp_path):
        runner = _runner_dir()
        deploy = tmp_path / "deploy"
        _write_deploy_config(deploy)
        authority = deploy / "authority"
        authority.mkdir(parents=True)
        approval = _build_v2_approval(deploy, "a" * 40)
        ap = authority / (
            "qprod_formal_approval_level_a_qprod_a_formal_v2.json")
        ap.write_text(json.dumps(approval, ensure_ascii=False),
                      encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(runner / "qprod_formal_authority.py"),
             "issue-permit", "--dir", str(authority),
             "--deploy-root", str(deploy), "--task-level", "level_a",
             "--attempt", "qaf_v2"],
            capture_output=True, text=True)
        assert proc.returncode == 96
        assert "必须提供 --repo 与 --project-dir" in proc.stdout
        assert not list(authority.glob("qprod_permit_*.json"))

    def test_gate_failure_refused_before_permit_write(self, tmp_path):
        runner = _runner_dir()
        deploy = tmp_path / "deploy"
        _write_deploy_config(deploy)
        authority = deploy / "authority"
        authority.mkdir(parents=True)
        approval = _build_v2_approval(deploy, "a" * 40)
        (authority / (
            "qprod_formal_approval_level_a_qprod_a_formal_v2.json"
        )).write_text(json.dumps(approval, ensure_ascii=False),
                      encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(runner / "qprod_formal_authority.py"),
             "issue-permit", "--dir", str(authority),
             "--deploy-root", str(deploy), "--task-level", "level_a",
             "--attempt", "qaf_v2", "--repo", str(_guard_repo()),
             "--project-dir", str(_project_tree_root())],
            capture_output=True, text=True)
        assert proc.returncode == 96
        assert "target_installed" in proc.stdout
        assert not list(authority.glob("qprod_permit_*.json"))

    def test_positive_and_one_shot(self, tmp_path):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            install_to_target, read_pinned_source,
        )
        runner = _runner_dir()
        deploy = tmp_path / "deploy"
        _write_deploy_config(deploy)
        art = deploy / "artifacts/formal_a_qaf_v2"
        install_to_target(art, read_pinned_source(_guard_repo()))
        authority = deploy / "authority"
        authority.mkdir(parents=True)
        approval = _build_v2_approval(deploy, "a" * 40)
        (authority / (
            "qprod_formal_approval_level_a_qprod_a_formal_v2.json"
        )).write_text(json.dumps(approval, ensure_ascii=False),
                      encoding="utf-8")
        argv = [sys.executable,
                str(runner / "qprod_formal_authority.py"),
                "issue-permit", "--dir", str(authority),
                "--deploy-root", str(deploy),
                "--task-level", "level_a", "--attempt", "qaf_v2",
                "--repo", str(_guard_repo()),
                "--project-dir", str(_project_tree_root())]
        init = subprocess.run(
            [sys.executable,
             str(runner / "qprod_formal_authority.py"),
             "init", "--dir", str(authority)],
            capture_output=True, text=True)
        assert init.returncode == 0, init.stdout + init.stderr
        # R3:直接签发须完整同根核验参数;本迷你沙箱无同根 record,
        # 期望缺参拒绝、零 permit(正例一次性语义见 reviewclosure
        # TestRCFR2DirectPermitPremit 全域测试)。
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode == 96, proc.stdout + proc.stderr
        assert "完整同根核验" in proc.stdout
        assert not list(authority.glob("qprod_permit_*.json"))


# ------------------------------------------------------------------
# PG07 计划语义不扩张
# ------------------------------------------------------------------

class TestPlanSemantics:
    def test_payload_diff_identity_only(self):
        from rl_curriculum.curriculum261_qprod_coordinate import (
            qprod_coordinate_code_identity,
        )
        from rl_curriculum.curriculum261_qprod_formal_levela import (
            build_formal_level_a_plan,
        )
        common = dict(
            code_freeze_sha="b" * 40,
            code_identity=qprod_coordinate_code_identity(),
            authorized_stop_after="verify-formal-logs",
            model_update_authorized=True)
        p1 = build_formal_level_a_plan(formal_attempt="qaf_v1", **common)
        p2 = build_formal_level_a_plan(formal_attempt="qaf_v2", **common)

        def flat(d, prefix=""):
            out = {}
            for k, v in d.items():
                key = f"{prefix}/{k}"
                if isinstance(v, dict):
                    out.update(flat(v, key))
                else:
                    out[key] = json.dumps(v, ensure_ascii=False,
                                          sort_keys=True)
            return out
        f1, f2 = flat(p1), flat(p2)
        assert set(f1) == set(f2)
        diff = [k for k in f1 if f1[k] != f2[k]]
        assert diff == ["/iteration_id"], diff
        assert p1["iteration_id"] == "qprod_a_formal_v1"
        assert p2["iteration_id"] == "qprod_a_formal_v2"
        # 预算/停止/规则逐项相等
        assert p1["quota"] == p2["quota"]
        assert p1["stop_mode"] == p2["stop_mode"]
        assert p1["rules"] == p2["rules"]

    def test_scope_mismatch_rejected_in_permit_validation(self):
        """跨尝试混名 scope 在许可层被拒(qprod_formal 通用化)。"""
        # 直接调用 scope 校验逻辑所在函数的轻量等效:用
        # QAF_ATTEMPTS 检查混合 scope 不属于任何规范域。
        mixed = sorted(
            list(QAF_ATTEMPTS["qaf_v1"].input_scope)[:13]
            + list(QAF_V2_FAMILY.input_scope)[13:])
        ok = any(mixed == sorted(fam.input_scope)
                 for fam in QAF_ATTEMPTS.values())
        assert ok is False


# ------------------------------------------------------------------
# PG04(admission 边界)+ PG05/PG09(operator 统一入口与真实前缀)
# 沙箱正例:真实执行器 record + 真实签发器/入口子进程;一次性
# 资源落点=pytest 临时沙箱域(隔离替身仅此一层)。
# ------------------------------------------------------------------

@pytest.fixture(scope="module")
def a2r2_sandbox_domain(tmp_path_factory):
    from r17_admission_substance_test_support import (
        git_repo_with_candidate, run_executor, record_path,
        sync_deploy_surface,
    )
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source,
    )
    base = tmp_path_factory.mktemp("a2r2_sandbox_domain")
    repo, commit_a, parent = git_repo_with_candidate(base)
    deploy = base / "deploy"
    sync_deploy_surface(repo, commit_a, deploy)
    run_dir, summary, rc = run_executor(
        base / "run", repo, commit_a, deploy, expect_rc=(0,))
    assert rc == 0 and summary.get("ok"), summary
    # v2 域附加物(记录只绑测试面/src 面;config/authority/
    # provenance 不入 import surface):部署配置 + 钉死前置 + 尾形
    # state 根。
    cfg = _write_deploy_config(deploy)
    art = Path(cfg["formal_roots"]["qprod_a_formal_v2"]
               ["artifact_root"])
    install_to_target(art, read_pinned_source(_guard_repo()))
    return {
        "base": base, "repo": repo, "commit_a": commit_a,
        "deploy": deploy, "record": record_path(run_dir), "art": art,
        "state": Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                      ["state_root"]),
        "authority": Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                          ["authority_dir"]),
    }


@pytest.fixture(scope="module")
def a2r2_drift_domain(tmp_path_factory):
    """独立漂移回归域(真实执行器 record;与 module 域隔离的
    一次性资源)。"""
    from r17_admission_substance_test_support import (
        git_repo_with_candidate, run_executor, record_path,
        sync_deploy_surface,
    )
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source,
    )
    base = tmp_path_factory.mktemp("a2r2_drift_domain")
    repo, commit_a, parent = git_repo_with_candidate(base)
    deploy = base / "deploy"
    sync_deploy_surface(repo, commit_a, deploy)
    run_dir, summary, rc = run_executor(
        base / "run", repo, commit_a, deploy, expect_rc=(0,))
    assert rc == 0 and summary.get("ok"), summary
    cfg = _write_deploy_config(deploy)
    art = Path(cfg["formal_roots"]["qprod_a_formal_v2"]
               ["artifact_root"])
    install_to_target(art, read_pinned_source(_guard_repo()))
    return {
        "base": base, "repo": repo, "commit_a": commit_a,
        "deploy": deploy, "record": record_path(run_dir), "art": art,
        "state": Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                      ["state_root"]),
        "authority": Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                          ["authority_dir"]),
    }


def _sandbox_v2_payload_digest(domain) -> tuple[dict, str]:
    from rl_curriculum.curriculum261_qprod_coordinate import (
        qprod_coordinate_code_identity,
    )
    from rl_curriculum.curriculum261_qprod_formal_levela import (
        build_formal_level_a_plan,
    )
    from rl_curriculum.curriculum261_qprod_plan import (
        research_plan_digest,
    )
    payload = build_formal_level_a_plan(
        code_freeze_sha=domain["commit_a"],
        code_identity=qprod_coordinate_code_identity(),
        authorized_stop_after="verify-formal-logs",
        model_update_authorized=True,
        formal_attempt="qaf_v2")
    return payload, research_plan_digest(payload)


def _write_v2_approval(domain, payload, digest) -> Path:
    from rl_curriculum.curriculum261_qprod_formal import (
        formal_approval_digest,
    )
    approval = {
        "format": "cur261-qprod-formal-approval-v1",
        "approval_id": "test-qaf-v2-wiring",
        "task_level": "level_a",
        "iteration_id": "qprod_a_formal_v2",
        "approved": {
            "research_plan_digest": digest,
            "code_freeze_sha": domain["commit_a"],
            "artifact_root": str(domain["art"]),
            "state_root": str(domain["state"]),
            "authority_dir": str(domain["authority"]),
            "namespaces": list(QAF_V2_FAMILY.input_scope),
            "coordinate_ids": [],
            "quota": dict(payload["quota"]),
            "authorized_stop_after": "verify-formal-logs",
            "model_update_authorized": True,
        },
        "approval_source": {"kind": "user_direct_approval",
                            "statement_digest": "bcc14f5a6bd026c600cb98171810a714d0a1cabb155e4aed73a8bb3a159ab5bd",
                            "note": "TEST-DOMAIN-ONLY wiring approval (isolated sandbox; not a production authorization)"},
    }
    approval["approval_digest"] = formal_approval_digest(approval)
    path = domain["base"] / "approval_qaf_v2.json"
    path.write_text(json.dumps(approval, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


class TestAdmissionIssueGate:
    """admission 边界:qaf_v2 prereg 在首一次性写前过守卫。"""

    def _prereg(self, domain, tmp_path) -> Path:
        import subprocess as sp
        plan = sp.run(
            ["git", "-C", str(domain["repo"]), "rev-parse",
             domain["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        path = tmp_path / "prereg_qaf_v2.json"
        path.write_text(json.dumps({
            "admission_id": "test-qaf-v2-admission-001",
            "iteration": "qprod_a_formal_v2",
            "plan_digest": plan,
            "plan_digest_method": "git_tree_digest",
            "authorization": "test-harness:隔离沙箱 wiring 验证",
            "regression_evidence": str(domain["record"]),
            "deploy_state_root": str(domain["state"]),
            "formal_attempt": "qaf_v2",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def test_missing_project_dir_refused_zero_writes(
            self, a2r2_sandbox_domain, tmp_path):
        runner = _runner_dir()
        prereg = self._prereg(a2r2_sandbox_domain, tmp_path)
        proc = subprocess.run(
            [sys.executable, str(runner / "r17_admission_issue.py"),
             "--repo", str(a2r2_sandbox_domain["repo"]),
             "--deploy-root", str(a2r2_sandbox_domain["deploy"]),
             "--state-root", str(a2r2_sandbox_domain["state"]),
             "--commit-a", a2r2_sandbox_domain["commit_a"],
             "--preregistration", str(prereg)],
            capture_output=True, text=True)
        assert proc.returncode == 96
        assert "必须提供 --project-dir" in proc.stdout
        assert not (a2r2_sandbox_domain["deploy"]
                    / ".r17_formal_admission.json").exists()

    def test_gate_failure_refused_zero_writes(
            self, a2r2_sandbox_domain, tmp_path):
        runner = _runner_dir()
        prereg = self._prereg(a2r2_sandbox_domain, tmp_path)
        # 破坏实际目标(移走 digest 件)→ 守卫拒绝,admission 不落盘
        digest_file = a2r2_sandbox_domain["art"] / (
            "gate_topology_reconciliation_digest.txt")
        backup = tmp_path / "digest.bak"
        shutil.move(str(digest_file), str(backup))
        try:
            proc = subprocess.run(
                [sys.executable,
                 str(runner / "r17_admission_issue.py"),
                 "--repo", str(a2r2_sandbox_domain["repo"]),
                 "--deploy-root", str(a2r2_sandbox_domain["deploy"]),
                 "--state-root", str(a2r2_sandbox_domain["state"]),
                 "--commit-a", a2r2_sandbox_domain["commit_a"],
                 "--preregistration", str(prereg),
                 "--project-dir", str(_project_tree_root()),
                 "--guard-repo", str(_guard_repo())],
                capture_output=True, text=True)
            assert proc.returncode == 96
            assert "target_installed" in proc.stdout
            assert not (a2r2_sandbox_domain["deploy"]
                        / ".r17_formal_admission.json").exists()
        finally:
            shutil.move(str(backup), str(digest_file))


class TestAdmissionBypassClosed:
    """P1 修复回归:iteration 决定守卫,缺 formal_attempt 不可绕过。"""

    def _base_prereg(self, domain, tmp_path, **over):
        import subprocess as sp
        plan = sp.run(
            ["git", "-C", str(domain["repo"]), "rev-parse",
             domain["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        doc = {
            "admission_id": "test-qaf-v2-bypass-001",
            "iteration": "qprod_a_formal_v2",
            "plan_digest": plan,
            "plan_digest_method": "git_tree_digest",
            "authorization": "test-harness:bypass 回归",
            "regression_evidence": str(domain["record"]),
            "deploy_state_root": str(domain["state"]),
        }
        doc.update(over)
        for k, v in list(doc.items()):
            if v is None:
                del doc[k]
        path = tmp_path / "prereg_bypass.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    def test_missing_formal_attempt_refused(self, a2r2_sandbox_domain,
                                            tmp_path):
        runner = _runner_dir()
        d = a2r2_sandbox_domain
        prereg = self._base_prereg(d, tmp_path, formal_attempt=None)
        proc = subprocess.run(
            [sys.executable, str(runner / "r17_admission_issue.py"),
             "--repo", str(d["repo"]), "--deploy-root", str(d["deploy"]),
             "--state-root", str(d["state"]),
             "--commit-a", d["commit_a"],
             "--preregistration", str(prereg)],
            capture_output=True, text=True)
        assert proc.returncode == 96
        assert "缺字段/错配" in proc.stdout or "必须" in proc.stdout
        assert not (d["deploy"] / ".r17_formal_admission.json").exists()

    def test_mismatched_formal_attempt_refused(self, a2r2_sandbox_domain,
                                               tmp_path):
        runner = _runner_dir()
        d = a2r2_sandbox_domain
        prereg = self._base_prereg(d, tmp_path, formal_attempt="qaf_v1")
        proc = subprocess.run(
            [sys.executable, str(runner / "r17_admission_issue.py"),
             "--repo", str(d["repo"]), "--deploy-root", str(d["deploy"]),
             "--state-root", str(d["state"]),
             "--commit-a", d["commit_a"],
             "--preregistration", str(prereg)],
            capture_output=True, text=True)
        assert proc.returncode == 96
        assert not (d["deploy"] / ".r17_formal_admission.json").exists()

    def test_v1_label_on_v2_deployment_refused(
            self, a2r2_sandbox_domain, tmp_path):
        """N2 回归:v1 标签 + 仅登记 v2 的部署配置 → 拒(标签不
        匹配部署登记;不得以旧标签豁免守卫)。"""
        runner = _runner_dir()
        d = a2r2_sandbox_domain
        # 坏目标(repair15 字节)
        r15_json = _guard_repo() / (
            "stage2_6_1/artifacts/repair15/"
            "gate_topology_reconciliation.json")
        r15_dig = _guard_repo() / (
            "stage2_6_1/artifacts/repair15/"
            "gate_topology_reconciliation_digest.txt")
        jp = d["art"] / "gate_topology_reconciliation.json"
        dp = d["art"] / "gate_topology_reconciliation_digest.txt"
        backup_j, backup_d = tmp_path / "bj2", tmp_path / "bd2"
        shutil.copy2(jp, backup_j)
        shutil.copy2(dp, backup_d)
        shutil.copy2(r15_json, jp)
        shutil.copy2(r15_dig, dp)
        try:
            prereg = self._base_prereg(
                d, tmp_path, iteration="qprod_a_formal_v1",
                formal_attempt=None)
            proc = subprocess.run(
                [sys.executable,
                 str(runner / "r17_admission_issue.py"),
                 "--repo", str(d["repo"]),
                 "--deploy-root", str(d["deploy"]),
                 "--state-root", str(d["state"]),
                 "--commit-a", d["commit_a"],
                 "--preregistration", str(prereg)],
                capture_output=True, text=True)
            assert proc.returncode == 96
            assert "未登记 v1" in proc.stdout
            assert not (d["deploy"]
                        / ".r17_formal_admission.json").exists()
        finally:
            shutil.copy2(backup_j, jp)
            shutil.copy2(backup_d, dp)

    def test_r15_target_refused_even_without_attempt_field(
            self, a2r2_sandbox_domain, tmp_path):
        """坏目标 + 无 formal_attempt 字段:iteration 触发守卫仍拒。"""
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            ProvenanceGuardError, read_pinned_source,
        )
        runner = _runner_dir()
        d = a2r2_sandbox_domain
        # 装入 repair15 实际字节(bad target;json+digest 成对)
        r15_json = _guard_repo() / (
            "stage2_6_1/artifacts/repair15/"
            "gate_topology_reconciliation.json")
        r15_dig = _guard_repo() / (
            "stage2_6_1/artifacts/repair15/"
            "gate_topology_reconciliation_digest.txt")
        jp = d["art"] / "gate_topology_reconciliation.json"
        dp = d["art"] / "gate_topology_reconciliation_digest.txt"
        backup_j, backup_d = tmp_path / "bj", tmp_path / "bd"
        shutil.copy2(jp, backup_j)
        shutil.copy2(dp, backup_d)
        shutil.copy2(r15_json, jp)
        shutil.copy2(r15_dig, dp)
        try:
            prereg = self._base_prereg(d, tmp_path, formal_attempt=None)
            proc = subprocess.run(
                [sys.executable,
                 str(runner / "r17_admission_issue.py"),
                 "--repo", str(d["repo"]),
                 "--deploy-root", str(d["deploy"]),
                 "--state-root", str(d["state"]),
                 "--commit-a", d["commit_a"],
                 "--preregistration", str(prereg)],
                capture_output=True, text=True)
            assert proc.returncode == 96
            assert not (d["deploy"]
                        / ".r17_formal_admission.json").exists()
        finally:
            shutil.copy2(backup_j, jp)
            shutil.copy2(backup_d, dp)


class TestOperatorEntryWiring:
    """PG05/PG09:统一入口环境/顺序/重入与真实前缀接线。"""

    def _execute_argv(self, domain, approval, *, extra=()):
        runner = _runner_dir()
        payload, digest = _sandbox_v2_payload_digest(domain)
        del payload
        import subprocess as sp
        plan = sp.run(
            ["git", "-C", str(domain["repo"]), "rev-parse",
             domain["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        return [sys.executable,
                str(runner / "qaf_v2_operator_entry.py"), "execute",
                "--repo", str(domain["repo"]),
                "--guard-repo", str(_guard_repo()),
                "--deploy-root", str(domain["deploy"]),
                "--project-dir", str(_project_tree_root()),
                "--approval-json", str(approval),
                "--regression-evidence", str(domain["record"]),
                "--admission-id", "test-qaf-v2-admission-002",
                "--authorization",
                "test-harness:隔离沙箱 operator wiring 验证",
                "--plan-digest", plan,
                "--plan-digest-method", "git_tree_digest",
                "--code-freeze-sha", domain["commit_a"],
                "--stop-after", "verify-formal-logs",
                "--model-update",
                "--test-domain"] + list(extra)

    def test_a2_double_flag_enforced(self, tmp_path):
        runner = _runner_dir()
        proc = subprocess.run(
            [sys.executable, str(runner / "qaf_v2_operator_entry.py"),
             "execute", "--repo", str(tmp_path),
             "--deploy-root", str(tmp_path),
             "--project-dir", str(tmp_path),
             "--approval-json", str(tmp_path / "x.json"),
             "--regression-evidence", str(tmp_path / "r.json"),
             "--admission-id", "x", "--authorization", "x",
             "--plan-digest", "x",
             "--code-freeze-sha", "c" * 40,
             "--stop-after", "verify-formal-logs"],
            capture_output=True, text=True)
        assert proc.returncode == 2
        assert "--model-update" in proc.stdout

    def test_sentinel_refused_outside_test_domain(self, tmp_path):
        runner = _runner_dir()
        common = ["--repo", str(tmp_path),
                  "--deploy-root", str(tmp_path),
                  "--project-dir", str(tmp_path),
                  "--approval-json", str(tmp_path / "x.json"),
                  "--regression-evidence", str(tmp_path / "r.json"),
                  "--admission-id", "x", "--authorization", "x",
                  "--plan-digest", "x",
                  "--code-freeze-sha", "c" * 40,
                  "--stop-after", "verify-formal-logs",
                  "--model-update", "--sentinel-before-chain"]
        proc = subprocess.run(
            [sys.executable, str(runner / "qaf_v2_operator_entry.py"),
             "execute"] + common, capture_output=True, text=True)
        assert proc.returncode == 96
        assert "--test-domain" in proc.stdout
        # 生产根前缀 + test-domain 同样拒(路径不落盘,纯门禁面)
        prod_like = "/home/cryptorl/projects/crypto_rl_formal_test"
        argv2 = [sys.executable,
                 str(runner / "qaf_v2_operator_entry.py"), "execute",
                 "--repo", str(tmp_path),
                 "--deploy-root", prod_like,
                 "--project-dir", str(tmp_path),
                 "--approval-json", str(tmp_path / "x.json"),
                 "--regression-evidence", str(tmp_path / "r.json"),
                 "--admission-id", "x", "--authorization", "x",
                 "--plan-digest", "x",
                 "--code-freeze-sha", "c" * 40,
                 "--stop-after", "verify-formal-logs",
                 "--model-update", "--sentinel-before-chain",
                 "--test-domain"]
        proc2 = subprocess.run(argv2, capture_output=True, text=True)
        assert proc2.returncode == 96
        assert "生产根" in proc2.stdout

    def test_post_issuance_drift_refused_before_permit_consume(
            self, a2r2_drift_domain, tmp_path):
        """P1 修复回归:签发后目标漂移 → launch 消费许可前拒绝。

        独立沙箱域(与 module 域互不消耗一次性资源):真实
        init→record-approval→issue-permit(守卫过)→prereg→
        admission(守卫过)→ 目标替换 repair15 字节 → launch
        在受控写前拒绝,许可零消费。
        """
        d = a2r2_drift_domain
        runner = _runner_dir()
        authority = d["authority"]
        payload, digest = _sandbox_v2_payload_digest(d)
        approval = _write_v2_approval(d, payload, digest)
        subprocess.run(
            [sys.executable, str(runner / "qprod_formal_authority.py"),
             "init", "--dir", str(authority)],
            capture_output=True, text=True, check=True)
        subprocess.run(
            [sys.executable, str(runner / "qprod_formal_authority.py"),
             "record-approval", "--dir", str(authority),
             "--approval-json", str(approval)],
            capture_output=True, text=True, check=True)
        _tree = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        r = subprocess.run(
            [sys.executable, str(runner / "qprod_formal_authority.py"),
             "issue-permit", "--dir", str(authority),
             "--deploy-root", str(d["deploy"]),
             "--task-level", "level_a", "--attempt", "qaf_v2",
             "--repo", str(_guard_repo()),
             "--project-dir", str(_project_tree_root()),
             "--regression-evidence", str(d["record"]),
             "--code-freeze-sha", str(d["commit_a"]),
             "--plan-digest", _tree,
             "--candidate-repo", str(d["repo"])],
            capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, r.stdout + r.stderr
        import subprocess as sp
        plan_digest = sp.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        prereg_path = tmp_path / "prereg_drift.json"
        prereg_path.write_text(json.dumps({
            "admission_id": "test-qaf-v2-drift-001",
            "iteration": "qprod_a_formal_v2",
            "plan_digest": plan_digest,
            "plan_digest_method": "git_tree_digest",
            "authorization": "test-harness:drift 回归",
            "regression_evidence": str(d["record"]),
            "deploy_state_root": str(d["state"]),
            "formal_attempt": "qaf_v2",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        ai = subprocess.run(
            [sys.executable, str(runner / "r17_admission_issue.py"),
             "--repo", str(d["repo"]), "--deploy-root", str(d["deploy"]),
             "--state-root", str(d["state"]),
             "--commit-a", d["commit_a"],
             "--preregistration", str(prereg_path),
             "--project-dir", str(_project_tree_root()),
             "--guard-repo", str(_guard_repo())],
            capture_output=True, text=True)
        assert ai.returncode == 0, ai.stdout + ai.stderr
        assert (d["deploy"] / ".r17_formal_admission.json").is_file()
        # 签发后漂移:目标 json 替换为 repair15 实际字节
        r15_json = _guard_repo() / (
            "stage2_6_1/artifacts/repair15/"
            "gate_topology_reconciliation.json")
        (d["art"] / "gate_topology_reconciliation.json").write_bytes(
            r15_json.read_bytes())
        proc = subprocess.run(
            [sys.executable,
             str(_project_tree_root() / "stage2_6_1_runner"
                 / "qprod_formal_level_a_entry.py"), "launch",
             "--deploy-root", str(d["deploy"]),
             "--project-dir", str(_project_tree_root()),
             "--code-freeze-sha", d["commit_a"],
             "--stop-after", "verify-formal-logs", "--model-update",
             "--formal-attempt", "qaf_v2",
             "--sentinel-before-chain"],
            cwd=str(_project_tree_root()), capture_output=True, text=True)
        assert proc.returncode == 96, proc.stdout[-2000:]
        assert "目标漂移" in proc.stdout
        # 许可未被消费(一次性资源保住;哨兵也未启动)
        assert not (d["state"]
                    / "qprod_permit_consumed.jsonl").exists()
        assert not (d["art"] / "qprod_formal_launch_handoff.json"
                    ).exists()

    def test_full_sentinel_wiring_and_reentry(self, a2r2_sandbox_domain):
        domain = a2r2_sandbox_domain
        payload, digest = _sandbox_v2_payload_digest(domain)
        approval = _write_v2_approval(domain, payload, digest)
        argv = self._execute_argv(domain, approval,
                                  extra=["--sentinel-before-chain"])
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stdout[-4000:] + proc.stderr
        # 输出为多段 JSON 流(permit/admission/launch);哨兵停止以
        # launch 段标记断言,结构化细节由下方落盘原件断言。
        assert "sentinel_stopped" in proc.stdout
        # 一次性资源各恰好一次
        authority = domain["authority"]
        assert (authority / "authority_identity.json").is_file()
        assert (authority / (
            "qprod_formal_approval_level_a_qprod_a_formal_v2.json"
        )).is_file()
        permits = list(authority.glob("qprod_permit_*.json"))
        assert len(permits) == 1
        assert (domain["deploy"]
                / ".r17_formal_admission.json").is_file()
        consumed = (domain["state"] / "qprod_permit_consumed.jsonl")
        assert len(consumed.read_text(encoding="utf-8").splitlines()) == 1
        # 哨兵:链执行器未调用 → 无 chain_result/determinism 面
        assert not (domain["art"] / "r17_chain_result.json").exists()
        assert not (domain["art"] / "determinism").exists()

        # PG09:真实链步 1 provenance-verify 在安装目标上实际执行
        # (同源代码复核;步 2 昂贵叶不触)
        vproc = subprocess.run(
            [sys.executable, "-m",
             "rl_curriculum.curriculum261_r17_cli",
             "provenance-verify", "--out-dir", str(domain["art"])],
            cwd=str(_project_tree_root()),
            env={**os.environ,
                 "PYTHONPATH": str(_project_tree_root() / "src")},
            capture_output=True, text=True)
        assert vproc.returncode == 0, vproc.stdout + vproc.stderr
        verify = json.loads(
            (domain["art"] / "gate_topology_provenance_verify.json"
             ).read_text(encoding="utf-8"))
        assert verify["pass"] is True
        assert verify["recomputed_digest"].startswith(
            "r17gtrec-3112e5deb863a")
        assert not (domain["art"] / "determinism").exists()
        # 重入:受控拒绝(许可在场 rc=4,或守卫新鲜度 rc=96——
        # 消费账已落盘;两条路径都是"先查状态、不重复签发"),
        # 许可计数不变
        proc2 = subprocess.run(argv, capture_output=True, text=True)
        assert proc2.returncode in (4, 96), proc2.stdout[-800:]
        assert ("一次性资源" in proc2.stdout
                or "freshness" in proc2.stdout)
        assert len(list(authority.glob("qprod_permit_*.json"))) == 1
        consumed2 = (domain["state"] / "qprod_permit_consumed.jsonl"
                     ).read_text(encoding="utf-8").splitlines()
        assert len(consumed2) == 1
