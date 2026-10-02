#!/usr/bin/env python3
"""RouteC_FormalLaunch_Preparation_v1 准备目录证据生成(测试域)。

在准备工作目录内构建隔离测试域沙盒(明确 TEST 标记),走真实
CLI 入口产生原件:草案计划、A/B 预检、正式 authority 签发链、
A 哨兵 launch handoff、B 计划冻结+11 坐标锁。零业务生成、零
fit、零 optimizer、零模型加载;真实部署配置/许可/exposure/
生产锁账本零写入(前后快照对照)。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DEPLOY_TREE = Path("/home/cryptorl/projects/crypto_rl")
RUNNER = DEPLOY_TREE / "stage2_6_1_runner"
PREP = Path(sys.argv[1])
FREEZE_SHA = "1" * 40  # TEST-ONLY 假 SHA(证据标注;真实批准绑 Commit A)

sys.path.insert(0, str(DEPLOY_TREE / "src"))

from rl_curriculum.curriculum261_qprod_coordinate import (  # noqa: E402
    qprod_coordinate_code_identity)
from rl_curriculum.curriculum261_qprod_formal import (  # noqa: E402
    QPROD_FORMAL_LEVEL_A_ITERATION_ID,
    QPROD_FORMAL_LEVEL_B_ITERATION_ID, formal_approval_digest,
    formal_coordinate_manifest)
from rl_curriculum.curriculum261_qprod_formal_levela import (  # noqa: E402
    build_formal_level_a_plan, formal_level_a_input_scope)
from rl_curriculum.curriculum261_qprod_plan import (  # noqa: E402
    research_plan_digest)


def sh(*args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [sys.executable, *args], capture_output=True, text=True)
    return proc


def write(rel: str, content: str) -> None:
    path = PREP / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def snapshot(root: Path) -> dict:
    out = {}
    if not root.exists():
        return {"exists": False}
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            import hashlib
            files[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()[:16]
    return {"exists": True, "files": files}


def main() -> int:
    # 保护状态前快照(真实部署根;证据动作前采集)
    prot_paths = [
        DEPLOY_TREE / "artifacts" / "route_c_stage2_6_1_repair17",
        DEPLOY_TREE / "artifacts" / "route_c_stage2_6_1_repair18",
        DEPLOY_TREE / "artifacts" / "route_c_stage2_6_1_repair19",
        DEPLOY_TREE / "qprod_deploy_config.json",
    ]
    before = {str(p): snapshot(p) for p in prot_paths}
    write("evidence/protected_paths_before.json",
          json.dumps(before, ensure_ascii=False, indent=2))

    sandbox = PREP / "sandbox"
    deploy = sandbox / "deploy"
    formal = deploy / "formal"
    a_art = formal / QPROD_FORMAL_LEVEL_A_ITERATION_ID / "artifacts" / (
        "chain")
    a_state = formal / QPROD_FORMAL_LEVEL_A_ITERATION_ID / "artifacts" / (
        "route_c_stage2_6_1_repair17") / "state"
    b_art = formal / QPROD_FORMAL_LEVEL_B_ITERATION_ID / "artifacts"
    b_state = formal / QPROD_FORMAL_LEVEL_B_ITERATION_ID / "state"
    authority = formal / "authority"
    authority.mkdir(parents=True, exist_ok=True)
    (deploy / "qprod_deploy_config.json").write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1",
        "mode": "formal_ready",
        "note": "TEST-ONLY sandbox deploy config(准备目录隔离;"
                "非生产部署配置)",
        "formal_roots": {
            QPROD_FORMAL_LEVEL_A_ITERATION_ID: {
                "artifact_root": str(a_art),
                "state_root": str(a_state),
                "authority_dir": str(authority),
            },
            QPROD_FORMAL_LEVEL_B_ITERATION_ID: {
                "artifact_root": str(b_art),
                "state_root": str(b_state),
                "authority_dir": str(authority),
            },
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    ident = qprod_coordinate_code_identity()

    # ---- 草案计划(A pre-Commit-A 信息草案 + B 草案) ----------
    r = sh(str(RUNNER / "qprod_formal_level_a_entry.py"),
           "draft-plan", "--prep-dir", str(PREP / "drafts"),
           "--stop-after", "qualify")
    write("evidence/draft_plan_a_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr
    r = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
           "draft-plan", "--prep-dir", str(PREP / "drafts"))
    write("evidence/draft_plan_b_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr

    # ---- 预检(沙盒 + 生产缺失两态;重复预检身份) -------------
    r1 = sh(str(RUNNER / "qprod_formal_level_a_entry.py"),
            "preflight", "--deploy-root", str(deploy))
    r2 = sh(str(RUNNER / "qprod_formal_level_a_entry.py"),
            "preflight", "--deploy-root", str(deploy))
    write("evidence/preflight_a_run1.json", r1.stdout)
    write("evidence/preflight_a_run2.json", r2.stdout)
    id1 = json.loads(r1.stdout)["content_identity"]
    id2 = json.loads(r2.stdout)["content_identity"]
    assert id1 == id2, "repeat preflight identity drift"
    r = sh(str(RUNNER / "qprod_formal_level_a_entry.py"), "preflight",
           "--deploy-root", str(PREP / "not_a_deploy"))
    write("evidence/preflight_a_absent_deploy.json", r.stdout)
    b1 = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
            "preflight", "--deploy-root", str(deploy))
    b2 = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
            "preflight", "--deploy-root", str(deploy))
    write("evidence/preflight_b_run1.json", b1.stdout)
    write("evidence/preflight_b_run2.json", b2.stdout)
    assert (json.loads(b1.stdout)["content_identity"]
            == json.loads(b2.stdout)["content_identity"])

    # ---- authority 签发链(TEST 批准绑定 TEST SHA) ------------
    r = sh(str(RUNNER / "qprod_formal_authority.py"), "init", "--dir",
           str(authority))
    write("evidence/authority_init_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr
    a_payload = build_formal_level_a_plan(
        code_freeze_sha=FREEZE_SHA, code_identity=ident,
        authorized_stop_after="qualify", model_update_authorized=False)
    approval_a = {
        "format": "cur261-qprod-formal-approval-v1",
        "approval_id": "qfa-test-sandbox-a",
        "task_level": "level_a",
        "iteration_id": QPROD_FORMAL_LEVEL_A_ITERATION_ID,
        "approved": {
            "research_plan_digest": research_plan_digest(a_payload),
            "code_freeze_sha": FREEZE_SHA,
            "artifact_root": str(a_art),
            "state_root": str(a_state),
            "authority_dir": str(authority),
            "namespaces": list(formal_level_a_input_scope()),
            "coordinate_ids": [],
            "quota": a_payload["quota"],
            "authorized_stop_after": "qualify",
            "model_update_authorized": False,
        },
        "approval_source": {
            "kind": "user_direct_approval",
            "statement_digest": "test-statement-sha256-sandbox-a",
            "received_utc": "2026-10-02T00:00:00Z",
        },
    }
    approval_a["approval_digest"] = formal_approval_digest(approval_a)
    ap_path = sandbox / "approval_a_in.json"
    ap_path.write_text(json.dumps(approval_a, ensure_ascii=False),
                       encoding="utf-8")
    r = sh(str(RUNNER / "qprod_formal_authority.py"),
           "record-approval", "--dir", str(authority),
           "--approval-json", str(ap_path))
    write("evidence/record_approval_a_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr
    r = sh(str(RUNNER / "qprod_formal_authority.py"), "issue-permit",
           "--dir", str(authority), "--deploy-root", str(deploy),
           "--task-level", "level_a")
    write("evidence/issue_permit_a_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr
    # 无批准反例:level_b 未记录批准 → 拒签
    r = sh(str(RUNNER / "qprod_formal_authority.py"), "issue-permit",
           "--dir", str(authority), "--deploy-root", str(deploy),
           "--task-level", "level_b")
    write("evidence/issue_permit_b_without_approval_stdout.json",
          r.stdout + r.stderr)
    assert r.returncode == 96

    # ---- A 哨兵 launch(链执行器边界前诚实停止) ----------------
    admission_dir = a_state.parent.parent.parent
    admission_dir.mkdir(parents=True, exist_ok=True)
    (admission_dir / ".r17_formal_admission.json").write_text(
        json.dumps({"admission_id": "adm-test-sandbox-a",
                    "commit_a_sha": FREEZE_SHA,
                    "note": "TEST-ONLY minimal admission shape;"
                            "真实 substance 由 r17_admission_issue "
                            "对 Commit A 签发"}),
        encoding="utf-8")
    r = sh(str(RUNNER / "qprod_formal_level_a_entry.py"), "launch",
           "--deploy-root", str(deploy),
           "--project-dir", str(DEPLOY_TREE),
           "--code-freeze-sha", FREEZE_SHA,
           "--stop-after", "qualify", "--sentinel-before-chain")
    write("evidence/launch_a_sentinel_stdout.json", r.stdout + r.stderr)
    assert r.returncode == 0, r.stderr + r.stdout
    handoff = json.loads(
        (a_art / "qprod_formal_launch_handoff.json").read_text(
            encoding="utf-8"))
    write("evidence/launch_a_handoff.json",
          json.dumps(handoff, ensure_ascii=False, indent=2))
    journal = (a_state / "qprod_run_journal.jsonl").read_text(
        encoding="utf-8")
    write("evidence/launch_a_session_journal.jsonl", journal)
    # 反例:同根重放(一轮一次被接受运行) → 96
    r = sh(str(RUNNER / "qprod_formal_level_a_entry.py"), "launch",
           "--deploy-root", str(deploy),
           "--project-dir", str(DEPLOY_TREE),
           "--code-freeze-sha", FREEZE_SHA,
           "--stop-after", "qualify", "--sentinel-before-chain")
    write("evidence/launch_a_replay_refused_stdout.json",
          r.stdout + r.stderr)
    assert r.returncode == 96

    # ---- B:批准+签发+冻结+11 坐标锁(零生成) -----------------
    from rl_curriculum.curriculum261_qprod_formal import (
        build_formal_level_b_plan,
    )
    b_payload = build_formal_level_b_plan(
        code_freeze_sha=FREEZE_SHA, code_identity=ident)
    ns = sorted(
        n for c in formal_coordinate_manifest()
        for n in (c["model_namespace"], c["validation_namespace"]))
    approval_b = {
        "format": "cur261-qprod-formal-approval-v1",
        "approval_id": "qfa-test-sandbox-b",
        "task_level": "level_b",
        "iteration_id": QPROD_FORMAL_LEVEL_B_ITERATION_ID,
        "approved": {
            "research_plan_digest": research_plan_digest(b_payload),
            "code_freeze_sha": FREEZE_SHA,
            "artifact_root": str(b_art),
            "state_root": str(b_state),
            "authority_dir": str(authority),
            "namespaces": ns,
            "coordinate_ids": [c["coordinate_id"] for c in
                               formal_coordinate_manifest()],
            "quota": b_payload["quota"],
            "authorized_stop_after": None,
            "model_update_authorized": False,
        },
        "approval_source": {
            "kind": "user_direct_approval",
            "statement_digest": "test-statement-sha256-sandbox-b",
            "received_utc": "2026-10-02T00:00:00Z",
        },
    }
    approval_b["approval_digest"] = formal_approval_digest(approval_b)
    apb = sandbox / "approval_b_in.json"
    apb.write_text(json.dumps(approval_b, ensure_ascii=False),
                   encoding="utf-8")
    r = sh(str(RUNNER / "qprod_formal_authority.py"),
           "record-approval", "--dir", str(authority),
           "--approval-json", str(apb))
    write("evidence/record_approval_b_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr
    r = sh(str(RUNNER / "qprod_formal_authority.py"), "issue-permit",
           "--dir", str(authority), "--deploy-root", str(deploy),
           "--task-level", "level_b")
    write("evidence/issue_permit_b_stdout.json", r.stdout)
    assert r.returncode == 0, r.stderr
    r = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
           "plan-freeze", "--deploy-root", str(deploy),
           "--code-freeze-sha", FREEZE_SHA)
    write("evidence/plan_freeze_b_stdout.json", r.stdout + r.stderr)
    assert r.returncode == 0, r.stderr
    r = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
           "lock-coordinates", "--deploy-root", str(deploy),
           "--code-freeze-sha", FREEZE_SHA)
    write("evidence/lock_coordinates_b_stdout.json", r.stdout + r.stderr)
    assert r.returncode == 0, r.stderr
    r = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
           "consume-permit", "--deploy-root", str(deploy),
           "--code-freeze-sha", FREEZE_SHA)
    write("evidence/consume_permit_b_stdout.json", r.stdout + r.stderr)
    assert r.returncode == 0, r.stderr
    # B run-coordinate 反例:无原生预算文件 → 零叶拒绝
    r = sh(str(RUNNER / "qprod_formal_level_b_entry.py"),
           "run-coordinate", "--deploy-root", str(deploy),
           "--code-freeze-sha", FREEZE_SHA, "--coordinate-id", "c01")
    write("evidence/run_coordinate_b_no_budget_refused.json",
          r.stdout + r.stderr)
    assert r.returncode == 96

    # ---- 保护状态前后对照(真实部署根零写) --------------------
    after = {str(p): snapshot(p) for p in prot_paths}
    write("evidence/protected_paths_after.json",
          json.dumps(after, ensure_ascii=False, indent=2))
    drift = {p: (before.get(p), after.get(p))
             for p in after if before.get(p) != after.get(p)}
    write("evidence/protected_paths_drift.json",
          json.dumps({"drift": drift,
                      "zero_write": not drift}, ensure_ascii=False,
                     indent=2))
    # ---- B/A 哨兵正例原件(pytest 真实 harness 输出) -----------
    pytest = str(Path("/home/cryptorl/miniforge3/envs/"
                      "freqtrade-rl/bin/python"))
    proc = subprocess.run(
        [pytest, "-m", "pytest",
         "tests/route_c_stage2_6_1/test_curriculum261_qprod_"
         "formal_launch.py::TestFormalLevelBRunCoordinate::"
         "test_runs_to_real_audit_core_with_sentinel_leaf",
         "tests/route_c_stage2_6_1/test_curriculum261_qprod_"
         "formal_launch.py::TestFormalLevelALaunch::"
         "test_sentinel_stops_at_chain_executor_boundary",
         "-v", "--no-header", "-p", "no:cacheprovider"],
        cwd=str(DEPLOY_TREE), capture_output=True, text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin"})
    write("evidence/sentinel_positive_pytest.txt",
          proc.stdout + proc.stderr)
    summary = {
        "prep_dir": str(PREP),
        "status": "EVIDENCE_GENERATED_TEST_DOMAIN",
        "protected_zero_write": not drift,
        "a_handoff_sentinel": handoff.get("sentinel"),
        "preflight_a_identity": id1,
        "preflight_b_identity": json.loads(b1.stdout)[
            "content_identity"],
    }
    write("evidence/EVIDENCE_SUMMARY.json",
          json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
