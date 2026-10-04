# -*- coding: utf-8 -*-
"""QAFv2 终验收口测试(RouteC_QAFv2_ReviewClosure_v1)。

RC04(PG05)确定性并发:同一一次性资源的两个并发请求恰一个推进;
败者在相应写入前被拒(O_EXCL 原子 create-only;authority 侧
check→write TOCTOU 已修)。并发释放经测试侧 go-barrier 包装,
被调进程是真实 runner 命令行,无生产逻辑替身。

RC05(PG06/07/09)连续真实工作流前缀:真实守卫安装→真实守卫
签发链(init→record-approval→issue-permit→prereg→admission)
→admission 闸门→唯一链会话→真实 plan 构建+真实
bound_workflow_plan_r17(生产 _chain-bounded 同一冻结函数)→
真实 execute_workflow_chain_r17:步 1 provenance-verify 子进程
读取安装目标并产出结果;下一科学叶 determinism-matrix 不在
排程(NOT_RUN);verify-formal-logs 只读收口。停止边界值是测试
注入的唯一差异(生产允许边界=qualify/verify-formal-logs;截断
机制本身为生产冻结函数)。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))
_SRC = _TESTS_DIR.parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF_V2_FAMILY)
from test_curriculum261_qaf_v2_preissue_guard import (  # noqa: E402
    GUARD_REPO_CANDIDATES, _guard_repo, _project_tree_root,
    _runner_dir, _sandbox_v2_payload_digest, _write_deploy_config,
)

PY = sys.executable


def _authority_runner() -> Path:
    return _runner_dir() / "qprod_formal_authority.py"


def _approval_path(domain) -> Path:
    """复用 preissue_guard 的 v2 沙箱批准构造(同 digest 绑定)。"""
    plan, digest = _sandbox_v2_payload_digest(domain)
    from rl_curriculum.curriculum261_qprod_formal import (
        formal_approval_digest,
    )
    approval = {
        "format": "cur261-qprod-formal-approval-v1",
        "approval_id": "rc-closure-test-approval",
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
            "quota": dict(plan["quota"]),
            "authorized_stop_after": "verify-formal-logs",
            "model_update_authorized": True,
        },
        "approval_source": {
            "kind": "user_direct_approval",
            "statement_digest": (
                "rc04-concurrent-wiring-test-only-not-production"),
            "note": ("TEST-DOMAIN-ONLY closure wiring approval "
                     "(isolated sandbox; not a production "
                     "authorization)"),
        },
    }
    approval["approval_digest"] = formal_approval_digest(approval)
    path = domain["base"] / "approval_rc.json"
    path.write_text(json.dumps(approval, ensure_ascii=False,
                               indent=1), encoding="utf-8")
    return path


def _issue_permit_argv(domain, permit_id: str) -> list[str]:
    return [PY, str(_authority_runner()), "issue-permit",
            "--dir", str(domain["authority"]),
            "--task-level", "level_a", "--attempt", "qaf_v2",
            "--repo", str(_guard_repo()),
            "--deploy-root", str(domain["deploy"]),
            "--project-dir", str(_project_tree_root()),
            "--permit-id", permit_id]


def _wrapped(argv: list[str], go_file: Path) -> list[str]:
    """测试侧 go-barrier 包装:等 go 文件出现后执行真实 argv。"""
    return [PY, "-c",
            "import subprocess, sys, time, pathlib\n"
            f"go = pathlib.Path({str(go_file)!r})\n"
            "while not go.exists():\n"
            "    time.sleep(0.005)\n"
            f"raise SystemExit(subprocess.call({argv!r}))\n"]


def _concurrent_pair(argv_a, argv_b, base: Path):
    go = base / "go.marker"
    procs = [subprocess.Popen(_wrapped(a, go), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
             for a in (argv_a, argv_b)]
    time.sleep(0.05)
    go.parent.mkdir(parents=True, exist_ok=True)
    go.write_text("go", encoding="utf-8")
    outs = [p.communicate(timeout=300) for p in procs]
    return [(p.returncode, o[0], o[1]) for p, o in zip(procs, outs)]


# ------------------------------------------------------------------
# RC04 确定性并发(隔离沙箱;真实 runner 命令)
# ------------------------------------------------------------------

def _make_rc_domain(base: Path, label: str) -> dict:
    from r17_admission_substance_test_support import (
        git_repo_with_candidate, run_executor, record_path,
        sync_deploy_surface,
    )
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, read_pinned_source,
    )
    repo, commit_a, _parent = git_repo_with_candidate(base)
    deploy = base / "deploy"
    sync_deploy_surface(repo, commit_a, deploy)
    run_dir, summary, rc = run_executor(
        base / "run", repo, commit_a, deploy, expect_rc=(0,))
    assert rc == 0 and summary.get("ok"), summary
    cfg = _write_deploy_config(deploy)
    art = Path(cfg["formal_roots"]["qprod_a_formal_v2"]
               ["artifact_root"])
    install_to_target(art, read_pinned_source(_guard_repo()))
    domain = {
        "label": label,
        "base": base, "repo": repo, "commit_a": commit_a,
        "deploy": deploy, "record": record_path(run_dir),
        "art": art,
        "state": Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                      ["state_root"]),
        "authority": Path(cfg["formal_roots"]["qprod_a_formal_v2"]
                          ["authority_dir"]),
    }
    # 真实 authority init(顺序;并发面由各测试单独证)
    r = subprocess.run(
        [PY, str(_authority_runner()), "init",
         "--dir", str(domain["authority"])],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return domain


@pytest.fixture(scope="module")
def rc_domain(tmp_path_factory):
    return _make_rc_domain(
        tmp_path_factory.mktemp("rc_closure_domain"), "rc-c04")


@pytest.fixture(scope="module")
def rc05_domain(tmp_path_factory):
    """RC05 独立一次性资源域(permit 与 RC04 域分离)。"""
    return _make_rc_domain(
        tmp_path_factory.mktemp("rc_closure_prefix"), "rc-c05")


class TestConcurrentOneShot:
    def test_concurrent_permit_issue_single_writer(self, rc_domain):
        d = rc_domain
        approval = _approval_path(d)
        # 先按真实流程 record-approval(顺序前置;permit 是并发对象)
        r = subprocess.run(
            [PY, str(_authority_runner()), "record-approval",
             "--dir", str(d["authority"]),
             "--approval-json", str(approval)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        argv = _issue_permit_argv(d, "rc-permit-c01")
        (rc1, out1, _), (rc2, out2, _) = _concurrent_pair(
            argv, list(argv), d["base"] / "c01")
        permits = list(d["authority"].glob(
            "qprod_permit_level_a_qprod_a_formal_v2.json"))
        assert len(permits) == 1, "并发后恰一份许可文件"
        winners = [rc for rc in (rc1, rc2) if rc == 0]
        assert len(winners) == 1, (rc1, rc2, out1, out2)
        loser_out = out2 if rc1 == 0 else out1
        assert "已存在" in loser_out or "already" in loser_out
        # 许可内容可解析且 digest 自洽(未被半写覆盖)
        doc = json.loads(permits[0].read_text(encoding="utf-8"))
        assert doc["permit_id"] == "rc-permit-c01"

    def test_concurrent_record_approval_single_writer(
            self, rc_domain):
        d = rc_domain
        approval = _approval_path(d)
        argv = [PY, str(_authority_runner()), "record-approval",
                "--dir", str(d["authority"]),
                "--approval-json", str(approval)]
        # 独立 authority 目录避免与 module 域冲突
        adir = d["base"] / "auth_rc02"
        adir.mkdir(parents=True, exist_ok=True)
        argv = [a if a != str(d["authority"]) else str(adir)
                for a in argv]
        (rc1, out1, _), (rc2, out2, _) = _concurrent_pair(
            argv, list(argv), d["base"] / "c02")
        files = list(adir.glob("*.json"))
        assert len(files) == 1, "并发后恰一份批准原件"
        winners = [rc for rc in (rc1, rc2) if rc == 0]
        assert len(winners) == 1, (rc1, rc2, out1, out2)

    def test_concurrent_init_single_identity(self, tmp_path):
        adir = tmp_path / "auth_c03"
        argv = [PY, str(_authority_runner()), "init",
                "--dir", str(adir)]
        (rc1, out1, err1), (rc2, out2, err2) = _concurrent_pair(
            argv, list(argv), tmp_path / "c03")
        idents = list(adir.glob("authority_identity.json"))
        assert len(idents) == 1
        doc = json.loads(idents[0].read_text(encoding="utf-8"))
        assert doc["kind"] == "formal_admission_authority"
        # 并发胜者 rc0;败者按在场正式身份分类为 rc0(already-
        # initialized,含 concurrent-loser 标记)或 rc1(异物);
        # 不允许崩溃/非零以外的脏状态。
        for rc, out in ((rc1, out1), (rc2, out2)):
            assert rc in (0, 1), (rc, out)
        already = sum(1 for rc, out in ((rc1, out1), (rc2, out2))
                      if rc == 0 and "already-initialized" in out)
        assert already in (1, 2), (rc1, rc2, out1, out2)
        # RC gate1 F2:败者不得以崩溃收场(分类拒绝,无回溯)
        for out, err in ((out1, err1), (out2, err2)):
            assert "Traceback" not in (out or "") + (err or ""), out

    def test_concurrent_admission_issue_single_writer(
            self, rc_domain, tmp_path):
        d = rc_domain
        plan = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        prereg = tmp_path / "prereg_c04.json"
        prereg.write_text(json.dumps({
            "admission_id": "rc-c04-concurrent-admission",
            "iteration": "qprod_a_formal_v2",
            "plan_digest": plan,
            "plan_digest_method": "git_tree_digest",
            "authorization": (
                "test-harness:RC04 并发单写(隔离沙箱;非正式授权)"),
            "regression_evidence": str(d["record"]),
            "deploy_state_root": str(d["state"]),
            "formal_attempt": "qaf_v2",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        runner = _runner_dir() / "r17_admission_issue.py"
        argv = [PY, str(runner), "--repo", str(d["repo"]),
                "--deploy-root", str(d["deploy"]),
                "--state-root", str(d["state"]),
                "--commit-a", d["commit_a"],
                "--preregistration", str(prereg),
                "--project-dir", str(_project_tree_root()),
                "--guard-repo", str(_guard_repo())]
        (rc1, out1, err1), (rc2, out2, err2) = _concurrent_pair(
            argv, list(argv), d["base"] / "c04")
        adm = d["deploy"] / ".r17_formal_admission.json"
        assert adm.is_file(), "恰一份 admission 落盘"
        winners = [rc for rc in (rc1, rc2) if rc == 0]
        assert len(winners) == 1, (rc1, rc2, out1, out2, err1, err2)
        log = d["deploy"] / "r17_admission_issued.jsonl"
        if log.is_file():
            ids = [json.loads(line)["admission_id"]
                   for line in log.read_text(encoding="utf-8")
                   .splitlines() if line.strip()]
            assert ids.count("rc-c04-concurrent-admission") == 1, ids


class TestExecuteBindingGate:
    """RC gate1 F1 回归:execute 首个一次性写前核清批准↔参数。"""

    def _execute(self, d, approval_file, code_sha, plan_digest):
        runner = _runner_dir()
        return subprocess.run(
            [PY, str(runner / "qaf_v2_operator_entry.py"), "execute",
             "--repo", str(d["repo"]),
             "--guard-repo", str(_guard_repo()),
             "--deploy-root", str(d["deploy"]),
             "--project-dir", str(_project_tree_root()),
             "--approval-json", str(approval_file),
             "--regression-evidence", str(d["record"]),
             "--admission-id", "rc-f1-binding-test",
             "--authorization", "test-harness:F1 binding gate",
             "--plan-digest", plan_digest,
             "--plan-digest-method", "git_tree_digest",
             "--code-freeze-sha", code_sha,
             "--stop-after", "verify-formal-logs", "--model-update",
             "--attempt", "qaf_v2", "--test-domain"],
            capture_output=True, text=True)

    def test_mismatch_refused_before_first_one_shot(
            self, tmp_path_factory):
        d = _make_rc_domain(
            tmp_path_factory.mktemp("rc_f1_domain"), "rc-f1")
        approval = _approval_path(d)
        plan = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True,
            check=True).stdout.strip()
        parent = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^"],
            capture_output=True, text=True,
            check=True).stdout.strip()
        parent_tree = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             parent + "^{tree}"],
            capture_output=True, text=True,
            check=True).stdout.strip()
        # 域构造含 authority init(合法既有件);execute 的任何
        # 一次性写都不得发生:记录在场文件集,两次拒绝后不变。
        adir = d["authority"]
        before = sorted(str(p.relative_to(adir))
                        for p in adir.rglob("*") if p.is_file())
        # (a) 冻结 SHA 不符(批准绑 commit_a;调用传 parent)
        proc = self._execute(d, approval, parent, parent_tree)
        assert proc.returncode == 96, proc.stdout
        assert "绑定核验失败" in proc.stdout, proc.stdout
        # (b) tree digest 与 --plan-digest 不符
        proc2 = self._execute(d, approval, d["commit_a"], "0" * 40)
        assert proc2.returncode == 96, proc2.stdout
        assert "重算不一致" in proc2.stdout, proc2.stdout
        # 零一次性写:authority 文件集不变;admission 不落盘
        after = sorted(str(p.relative_to(adir))
                       for p in adir.rglob("*") if p.is_file())
        assert after == before, (before, after)
        assert not (d["deploy"]
                    / ".r17_formal_admission.json").exists()
        assert not (d["state"] / "r17_admission_issuance.log.jsonl"
                    ).exists()


# ------------------------------------------------------------------
# RC05 连续真实工作流前缀(隔离域;科学叶不执行)
# ------------------------------------------------------------------

class TestContinuousWorkflowPrefix:
    def test_entry_to_step1_to_science_leaf_boundary(
            self, rc05_domain, tmp_path):
        d = rc05_domain
        # 1) 真实守卫签发链(独立域,一次性资源与 RC04 分离)。
        adir = d["authority"]
        approval = _approval_path(d)
        for step in (
            [PY, str(_authority_runner()), "init", "--dir", str(adir)],
            [PY, str(_authority_runner()), "record-approval",
             "--dir", str(adir), "--approval-json", str(approval)],
        ):
            r = subprocess.run(step, capture_output=True, text=True)
            assert r.returncode == 0, r.stdout + r.stderr
        r = subprocess.run(
            [PY, str(_authority_runner()), "issue-permit",
             "--dir", str(adir), "--task-level", "level_a",
             "--attempt", "qaf_v2", "--repo", str(_guard_repo()),
             "--deploy-root", str(d["deploy"]),
             "--project-dir", str(_project_tree_root()),
             "--permit-id", "rc-permit-c05"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        summary = json.loads(r.stdout.splitlines()[-1])
        permit = json.loads(
            Path(summary["permit_path"]).read_text(encoding="utf-8"))
        assert permit["iteration_id"] == "qprod_a_formal_v2"
        # 2) prereg + 真实 admission 签发(守卫内建)
        plan = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True, check=True).stdout.strip()
        prereg = tmp_path / "prereg_rc05.json"
        prereg.write_text(json.dumps({
            "admission_id": "rc-c05-continuous-prefix",
            "iteration": "qprod_a_formal_v2",
            "plan_digest": plan, "plan_digest_method": "git_tree_digest",
            "authorization": ("test-harness:RC05 连续前缀(隔离沙箱;"
                              "非正式授权;科学叶截停)"),
            "regression_evidence": str(d["record"]),
            "deploy_state_root": str(d["state"]),
            "formal_attempt": "qaf_v2",
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        r = subprocess.run(
            [PY, str(_runner_dir() / "r17_admission_issue.py"),
             "--repo", str(d["repo"]), "--deploy-root", str(d["deploy"]),
             "--state-root", str(d["state"]),
             "--commit-a", d["commit_a"],
             "--preregistration", str(prereg),
             "--project-dir", str(_project_tree_root()),
             "--guard-repo", str(_guard_repo())],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        # 3) 连续派发:admission 闸门→会话→真实 plan+bound→执行器
        # 会话/预算门经 registry 解析状态根:工程 env 动态读取
        # (R17_STATE_ROOT);正式子进程由 launch 构造 deployed 绑定
        # (import 期常量)。测试进程此前已 import registry,故用
        # 动态工程 env 指向同一隔离 state 根(仅测试域)。
        os.environ["CURRICULUM261_R17_DEPLOYED_STATE_ROOT"] = str(
            d["state"])
        os.environ["CURRICULUM261_R17_STATE_ROOT"] = str(d["state"])
        for var in ("CURRICULUM261_QPROD_ART_ROOT",
                    "CURRICULUM261_QPROD_STATE_ROOT"):
            os.environ.pop(var, None)
        try:
            from rl_curriculum.curriculum261_r17_admission import (
                enforce_formal_admission,
            )
            from rl_curriculum.curriculum261_r17_execgov import (
                R17ChainSession,
            )
            from rl_curriculum.curriculum261_r17_workflow import (
                build_workflow_plan_r17, execute_workflow_chain_r17,
            )
            from rl_curriculum.curriculum261_qprod_formal_levela import (
                bound_workflow_plan_r17,
            )
            from rl_curriculum.curriculum261_qprod_formal_budget \
                import write_chain_budget_gate
            reason = enforce_formal_admission(
                state_root=d["state"], freeze_sha=d["commit_a"],
                release_repo=str(d["repo"]))
            assert reason is None, reason
            # 链 out_dir=权威 A artifact 根(RC02:链读取的实际
            # 目标;requires_artifacts 就地消费安装件)
            chain_out = d["art"]
            binding = {
                "mode": "formal", "freeze_sha": d["commit_a"],
                "state_root": str(d["state"]),
                "out_dir": str(chain_out),
                "argv": ["rc-closure-test",
                         "bounded-prefix(provenance-verify)"],
                "authorized_stop_after": "provenance-verify",
            }
            session = R17ChainSession.acquire(binding)
            plan_doc = build_workflow_plan_r17(
                profile="formal", out_dir=str(chain_out),
                freeze_sha=d["commit_a"], formal_attempt="qaf_v2")
            plan_doc = bound_workflow_plan_r17(
                plan_doc, "provenance-verify")
            assert "determinism-matrix" in plan_doc["not_run_steps"]
            write_chain_budget_gate(
                chain_out, stop_after="provenance-verify",
                steps_in_plan=[s["name"] for s in plan_doc["steps"]])
            result = execute_workflow_chain_r17(
                plan_doc, session=session,
                log_dir=chain_out.parent / (chain_out.name + "_logs"))
            assert result["ok"], result
            # 步 1 真实产物:读取安装目标的 provenance 复核报告
            verify = json.loads(
                (chain_out / "gate_topology_provenance_verify.json")
                .read_text(encoding="utf-8"))
            assert verify["pass"] is True, verify
            assert verify["stored_digest"].startswith(
                "r17gtrec-3112e5deb863a")
            assert verify["recomputed_digest"] == verify["stored_digest"]
            # 下一科学叶未执行:无 determinism 工程产物目录/事件
            assert not (chain_out / "determinism").exists()
            manifest_lines = [
                json.loads(x) for x in (
                    d["art"] / "r17_formal_log_manifest.jsonl"
                ).read_text(encoding="utf-8").splitlines() if x.strip()]
            names = [e.get("step") or e.get("name")
                     for e in manifest_lines]
            assert "determinism-matrix" not in names, names
            # 只读收口步在排程且产出验证报告
            assert (chain_out
                    / "r17_formal_log_verification.json").is_file()
            session.release(summary=(
                "RC05 continuous prefix stopped at "
                "provenance-verify;science leaves NOT_RUN"))
        finally:
            os.environ.pop("CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                           None)
            os.environ.pop("CURRICULUM261_R17_STATE_ROOT", None)


# ------------------------------------------------------------------
# ReviewClosure 修复轮(RCF-01/02/03;ChatGPT 独立终验 FAIL 项)
# ------------------------------------------------------------------

class TestRCF01Paths:
    """RCF-01:prepare/installer/验证报告写前路径硬化。"""

    def _prepare(self, deploy: Path, *, extra_cfg=None):
        runner = _runner_dir()
        return subprocess.run(
            [PY, str(runner / "qaf_v2_operator_entry.py"), "prepare",
             "--repo", str(_guard_repo()), "--deploy-root", str(deploy),
             "--project-dir", str(_project_tree_root()),
             "--attempt", "qaf_v2"],
            capture_output=True, text=True)

    def _config(self, deploy: Path, artifact_root) -> None:
        deploy.mkdir(parents=True, exist_ok=True)
        state = deploy / "artifacts/route_c_stage2_6_1_repair17/state"
        cfg = {
            "format": "cur261-qprod-deploy-config-v1",
            "mode": "formal_ready",
            "formal_roots": {"qprod_a_formal_v2": {
                "artifact_root": str(artifact_root),
                "state_root": str(state),
                "authority_dir": str(deploy / "authority"),
            }},
        }
        (deploy / "qprod_deploy_config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=1),
            encoding="utf-8")

    def _snap(self, root: Path) -> dict:
        if not root.exists():
            return {"exists": False}
        return {"exists": True, "entries": sorted(
            p.name for p in root.rglob("*"))}

    def test_positive_new_dir_and_idempotent(self, tmp_path):
        deploy = tmp_path / "deploy"
        art = tmp_path / "fresh_art"
        self._config(deploy, art)
        r1 = self._prepare(deploy)
        assert r1.returncode == 0, r1.stdout + r1.stderr
        assert (art / "gate_topology_reconciliation.json").is_file()
        mtime = (art / "gate_topology_reconciliation.json"
                 ).stat().st_mtime_ns
        r2 = self._prepare(deploy)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert (art / "gate_topology_reconciliation.json"
                ).stat().st_mtime_ns == mtime
        assert (art / "gate_topology_provenance_verify.json").is_file()

    def test_protected_dir_refused_pre_write(self, tmp_path):
        tree = _project_tree_root()
        prot = tree / "artifacts/route_c_stage2_6_1_repair17/rcf01"
        prot.mkdir(parents=True, exist_ok=True)
        before = self._snap(prot)
        deploy = tmp_path / "deploy_p"
        self._config(deploy, prot)
        r = self._prepare(deploy)
        assert r.returncode != 0
        assert "受保护历史根" in (r.stdout + r.stderr)
        assert self._snap(prot) == before, "拒绝后保护面字节/成员不变"

    def test_symlink_to_protected_refused(self, tmp_path):
        tree = _project_tree_root()
        prot = tree / "artifacts/route_c_stage2_6_1_repair17/rcf01s"
        prot.mkdir(parents=True, exist_ok=True)
        link = tmp_path / "alias_art"
        link.symlink_to(prot, target_is_directory=True)
        before = self._snap(prot)
        deploy = tmp_path / "deploy_l"
        self._config(deploy, link)
        r = self._prepare(deploy)
        assert r.returncode != 0
        assert "受保护历史根" in (r.stdout + r.stderr)
        assert self._snap(prot) == before

    def test_relative_target_refused(self, tmp_path):
        deploy = tmp_path / "deploy_rel"
        self._config(deploy, "relative_art_root")
        cwd_snap = self._snap(tmp_path)
        r = self._prepare(deploy)
        assert r.returncode != 0
        assert "绝对路径" in (r.stdout + r.stderr)
        assert not (tmp_path / "relative_art_root").exists()

    def test_allow_replace_broken_mixed_dir_refused(self, tmp_path):
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            install_to_target, read_pinned_source,
        )
        art = tmp_path / "mixed_art"
        install_to_target(art, read_pinned_source(_guard_repo()))
        (art / "historical_evidence.json").write_text(
            '{"keep": true}', encoding="utf-8")
        (art / "gate_topology_reconciliation.json").write_text("{}")
        with pytest.raises(Exception, match="两件之外的文件"):
            install_to_target(
                art, read_pinned_source(_guard_repo()),
                allow_replace_broken=True)
        assert json.loads(
            (art / "historical_evidence.json").read_text(
                encoding="utf-8")) == {"keep": True}


class TestRCF02StateMatrix:
    """RCF-02:首签发前核清实际使用对象与已有一次性状态。"""

    def _execute(self, d, approval_file, evidence, **over):
        runner = _runner_dir()
        argv = [PY, str(runner / "qaf_v2_operator_entry.py"),
                "execute",
                "--repo", str(d["repo"]),
                "--guard-repo", str(_guard_repo()),
                "--deploy-root", str(d["deploy"]),
                "--project-dir", str(_project_tree_root()),
                "--approval-json", str(approval_file),
                "--regression-evidence", str(evidence),
                "--admission-id", "rcf02-test",
                "--authorization", "test-harness:RCF02",
                "--plan-digest", over.get(
                    "plan_digest", d["tree"]),
                "--plan-digest-method", "git_tree_digest",
                "--code-freeze-sha", over.get(
                    "code_sha", d["commit_a"]),
                "--stop-after", "verify-formal-logs",
                "--model-update", "--attempt", "qaf_v2",
                "--test-domain"]
        return subprocess.run(argv, capture_output=True, text=True)

    def _domain_with_tree(self, tmp_path_factory):
        d = _make_rc_domain(
            tmp_path_factory.mktemp("rcf02"), "rcf02")
        d["tree"] = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True,
            check=True).stdout.strip()
        return d

    def test_stored_approval_mismatch_refused_zero_write(
            self, tmp_path_factory):
        d = self._domain_with_tree(tmp_path_factory)
        # 已存批准绑定旧候选(上一 PG 身份)
        old = json.loads(
            _approval_path(d).read_text(encoding="utf-8"))
        old["approved"]["code_freeze_sha"] = "0" * 40
        old.pop("approval_digest", None)
        from rl_curriculum.curriculum261_qprod_formal import (
            formal_approval_digest,
        )
        old["approval_digest"] = formal_approval_digest(old)
        adir = d["authority"]
        adir.mkdir(parents=True, exist_ok=True)
        (adir / ("qprod_formal_approval_level_a_qprod_a_formal_v2"
                 ".json")).write_text(
            json.dumps(old, ensure_ascii=False, indent=1),
            encoding="utf-8")
        before = sorted(str(p.relative_to(adir))
                        for p in adir.rglob("*") if p.is_file())
        proc = self._execute(d, _approval_path(d), d["record"])
        assert proc.returncode == 96, proc.stdout
        assert "digest" in proc.stdout and "不一致" in proc.stdout
        after = sorted(str(p.relative_to(adir))
                       for p in adir.rglob("*") if p.is_file())
        assert after == before

    def test_evidence_missing_and_wrong_candidate_refused(
            self, tmp_path_factory):
        d = self._domain_with_tree(tmp_path_factory)
        missing = d["base"] / "nope.json"
        proc = self._execute(d, _approval_path(d), missing)
        assert proc.returncode == 96
        assert "不可读" in proc.stdout
        rec = json.loads(
            Path(d["record"]).read_text(encoding="utf-8"))
        rec["commit_a_sha"] = "1" * 40
        wrong = d["base"] / "wrong_commit_record.json"
        wrong.write_text(json.dumps(rec, ensure_ascii=False),
                         encoding="utf-8")
        proc2 = self._execute(d, _approval_path(d), wrong)
        assert proc2.returncode == 96, proc2.stdout
        assert "record 绑定候选" in proc2.stdout
        assert not list(d["authority"].glob("qprod_permit_*"))

    def test_existing_permit_and_admission_refused_pre_write(
            self, tmp_path_factory):
        d = self._domain_with_tree(tmp_path_factory)
        adir = d["authority"]
        (adir / ("qprod_permit_level_a_qprod_a_formal_v2.json")
         ).write_text('{"format": "stub"}', encoding="utf-8")
        proc = self._execute(d, _approval_path(d), d["record"])
        assert proc.returncode == 4
        assert "许可已在场" in proc.stdout
        (adir / ("qprod_permit_level_a_qprod_a_formal_v2.json")
         ).unlink()
        (d["deploy"] / ".r17_formal_admission.json").write_text(
            '{"format": "cur261-r17-formal-admission-v1"}',
            encoding="utf-8")
        proc2 = self._execute(d, _approval_path(d), d["record"])
        assert proc2.returncode == 4
        assert "admission 已签发" in proc2.stdout
        assert not list(adir.glob("qprod_permit_*"))

    def test_real_issuance_log_refused_pre_write(
            self, tmp_path_factory):
        d = self._domain_with_tree(tmp_path_factory)
        # 真实签发日志在 deploy 根(准入文件不在场=中断/回执缺失
        # 形态)→ 首个一次性写前拒绝,不重签准入
        (d["deploy"] / "r17_admission_issued.jsonl").write_text(
            json.dumps({"admission_id": "prior-test",
                        "commit_a_sha": d["commit_a"]}) + "\n",
            encoding="utf-8")
        adir = d["authority"]
        before = sorted(str(p.relative_to(adir))
                        for p in adir.rglob("*") if p.is_file())
        proc = self._execute(d, _approval_path(d), d["record"])
        assert proc.returncode == 4, proc.stdout
        assert "签发日志在场" in proc.stdout
        after = sorted(str(p.relative_to(adir))
                       for p in adir.rglob("*") if p.is_file())
        assert after == before
        assert not (d["deploy"]
                    / ".r17_formal_admission.json").exists()

    def test_leaf_sentinel_without_test_domain_zero_write(
            self, tmp_path_factory):
        d = self._domain_with_tree(tmp_path_factory)
        runner = _runner_dir()
        proc = subprocess.run(
            [PY, str(runner / "qaf_v2_operator_entry.py"), "execute",
             "--repo", str(d["repo"]),
             "--guard-repo", str(_guard_repo()),
             "--deploy-root", str(d["deploy"]),
             "--project-dir", str(_project_tree_root()),
             "--approval-json", str(_approval_path(d)),
             "--regression-evidence", str(d["record"]),
             "--admission-id", "rcf02-leafnodomain",
             "--authorization", "test-harness",
             "--plan-digest", d["tree"],
             "--plan-digest-method", "git_tree_digest",
             "--code-freeze-sha", d["commit_a"],
             "--stop-after", "verify-formal-logs",
             "--model-update", "--attempt", "qaf_v2",
             "--leaf-sentinel", "determinism-matrix"],
            capture_output=True, text=True)
        assert proc.returncode == 96, proc.stdout
        assert "--leaf-sentinel 仅限 --test-domain" in proc.stdout
        assert '"one_shot_writes": 0' in proc.stdout
        adir = d["authority"]
        assert not list(adir.glob("qprod_permit_*"))
        assert not (d["deploy"]
                    / ".r17_formal_admission.json").exists()
        assert not (d["deploy"]
                    / "r17_admission_issued.jsonl").exists()

    def test_post_permit_refusal_reports_one_shot_write(
            self, tmp_path_factory):
        d = self._domain_with_tree(tmp_path_factory)
        # 部署面字节漂移(追加注释):preissue 门与全部首写前预检
        # 均不比对部署树;admission substance 深核部署面 → permit
        # 落盘后 admission 拒绝 → 该调用计数必须如实=1
        cand = sorted((Path(d["deploy"]) / "src" / "rl_curriculum")
                      .glob("*.py"))
        assert cand, "沙箱部署树 src 面异常"
        probe = cand[0]
        original = probe.read_bytes()
        try:
            probe.write_bytes(original + b"\n# drift\n")
            proc = self._execute(d, _approval_path(d), d["record"])
        finally:
            probe.write_bytes(original)
        assert proc.returncode == 96, proc.stdout
        assert '"one_shot_writes": 1' in proc.stdout, proc.stdout
        assert list(d["authority"].glob("qprod_permit_*"))


class TestRCF03ContinuousLeafBoundary:
    """RCF-03:operator 全链真实排程到下一科学叶首昂贵调用边界。"""

    def test_execute_to_determinism_leaf_sentinel(
            self, tmp_path_factory):
        d = _make_rc_domain(
            tmp_path_factory.mktemp("rcf03"), "rcf03")
        tree = subprocess.run(
            ["git", "-C", str(d["repo"]), "rev-parse",
             d["commit_a"] + "^{tree}"],
            capture_output=True, text=True,
            check=True).stdout.strip()
        approval = _approval_path(d)
        runner = _runner_dir()
        env = dict(os.environ)
        # 沙箱 release repo:launch/chain 的 admission 闸门按
        # R17_RELEASE_REPO 解析候选 git 对象(默认指向生产仓库)
        env["R17_RELEASE_REPO"] = str(d["repo"])
        proc = subprocess.run(
            [PY, str(runner / "qaf_v2_operator_entry.py"), "execute",
             "--repo", str(d["repo"]),
             "--guard-repo", str(_guard_repo()),
             "--deploy-root", str(d["deploy"]),
             "--project-dir", str(_project_tree_root()),
             "--approval-json", str(approval),
             "--regression-evidence", str(d["record"]),
             "--admission-id", "rcf03-continuous",
             "--authorization", "test-harness:RCF03 连续前缀",
             "--plan-digest", tree,
             "--plan-digest-method", "git_tree_digest",
             "--code-freeze-sha", d["commit_a"],
             "--stop-after", "verify-formal-logs",
             "--model-update", "--attempt", "qaf_v2",
             "--test-domain", "--leaf-sentinel",
             "determinism-matrix"],
            capture_output=True, text=True, timeout=600, env=env)
        out = proc.stdout
        # 全链真实:init/record/permit/admission 各一次
        assert (d["authority"] / "authority_identity.json").is_file()
        assert list(d["authority"].glob(
            "qprod_formal_approval_*"))
        assert len(list(d["authority"].glob(
            "qprod_permit_*"))) == 1
        assert (d["deploy"] / ".r17_formal_admission.json").is_file()
        # 步 1 真实产物(读安装目标)
        verify = d["art"] / "gate_topology_provenance_verify.json"
        assert verify.is_file(), out[-2000:]
        # 步 2 到达首个昂贵科学调用边界,恰一次,科学零执行
        marker = d["art"] / "leaf_sentinel_marker.json"
        assert marker.is_file(), out[-2000:]
        mdoc = json.loads(marker.read_text(encoding="utf-8"))
        assert mdoc["step"] == "determinism-matrix"
        assert mdoc["science_executed"] is False
        assert not (d["art"] / "determinism"
                    / "generation_determinism_contract.json").exists()
        # manifest 含步1与步2事件(连续同一路径)
        manifest = d["art"] / "r17_formal_log_manifest.jsonl"
        assert manifest.is_file()
        steps = [json.loads(x).get("step")
                 for x in manifest.read_text(encoding="utf-8")
                 .splitlines() if x.strip()]
        assert "provenance-verify" in steps and \
               "determinism-matrix" in steps, steps
        # 链诚实失败于步 3 前置(科学未跑);整体非成功
        assert proc.returncode != 0
        result = d["art"] / "r17_chain_result.json"
        assert result.is_file()
        cdoc = json.loads(result.read_text(encoding="utf-8"))
        assert cdoc["ok"] is False
        assert cdoc["failed_step"] in ("audit",
                                       "determinism-matrix"), cdoc
