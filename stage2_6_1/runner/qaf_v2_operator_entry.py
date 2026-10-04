#!/usr/bin/env python3
"""QAF v2 操作员统一受控入口(A2-R2;RouteC_A2_PreIssueGuard_-
NewAttempt_v1)。

一条入口承载环境、顺序与重复请求,提供明确区分的行为:

- ``check``   只读状态面(环境白名单/部署配置/钉死源/实际目标/
              新鲜度);零写入、零签发。
- ``prepare`` 把钉死 Git 源 provenance 安装到**实际 A artifact 根**
              (幂等;异物/半写拒绝),随后以同源 verifier 复核。
              本轮允许(仅前置 provenance 与验证报告入新准备域)。
- ``execute`` 经批准的一次性执行路径(本轮禁止真实使用):真实
              批准原件 → authority init/record-approval → 签发前
              硬门 → issue-permit(守卫内建)→ prereg+admission
              签发(守卫内建)→ 一次性 A2 launch(P2 入口形态)
              → 收尾核对。重复请求/中断/回执缺失先查既有原件与
              消费状态,不盲目重试;一次性资源在场=拒绝重入。

环境合同:入口负责正确 cwd/解释器/PYTHONPATH 与环境白名单;操作
员不得手写 R17/QProd 根重定向变量(在场即拒)。真实根禁止
``--sentinel-before-chain``(哨兵只存在于隔离测试域,须显式
``--test-domain`` 且部署根不在生产根清单内)。

本入口不放宽任何既有守卫:根守卫、一次性拒绝、停止规则原样。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF_ATTEMPT_IDS, qaf_iteration_id_for_attempt)
from rl_curriculum.curriculum261_qaf_provenance_guard import (  # noqa: E402
    ProvenanceGuardError, freshness_check, inspect_target,
    preissue_gate, read_pinned_source)

#: 生产根前缀(哨兵与测试域不得触达;旧 P/D 事故现场+预选 P2/D2)。
PRODUCTION_ROOT_PREFIXES = (
    "/home/cryptorl/projects/crypto_rl",
)

_REDIRECT_ENV_VARS = (
    "CURRICULUM261_R17_STATE_ROOT", "CURRICULUM261_QPROD_ART_ROOT",
    "CURRICULUM261_QPROD_STATE_ROOT", "R17_STATE_ROOT", "R17_ART_ROOT",
)

ENTRY_FORMAT = "cur261-qaf-v2-operator-entry-v1"


def _env_violations() -> list[str]:
    return [v for v in _REDIRECT_ENV_VARS if os.environ.get(v)]


def _is_production_root(deploy_root: Path) -> bool:
    text = str(Path(deploy_root).resolve())
    return any(text.startswith(p) for p in PRODUCTION_ROOT_PREFIXES)


def _roots(deploy_root: Path, attempt: str) -> dict[str, str]:
    from rl_curriculum.curriculum261_qprod_context import (
        load_deploy_config,
    )
    iteration = qaf_iteration_id_for_attempt(attempt)
    cfg = load_deploy_config(Path(deploy_root))
    entry = (cfg.get("formal_roots") or {}).get(iteration)
    if not entry:
        raise ProvenanceGuardError(
            f"部署配置 formal_roots 缺 {iteration}(attempt={attempt})")
    return {"iteration": iteration, **{
        k: str(v) for k, v in entry.items()}}


def cmd_check(args: argparse.Namespace) -> int:
    out: dict = {"format": ENTRY_FORMAT, "cmd": "check",
                 "attempt": args.attempt,
                 "one_shot_writes": 0, "business_leaf_calls": 0}
    bad = _env_violations()
    out["env_whitelist_ok"] = not bad
    out["env_violations"] = bad
    try:
        roots = _roots(Path(args.deploy_root), args.attempt)
        out["deploy_roots"] = roots
    except (ProvenanceGuardError, Exception) as exc:  # noqa: BLE001
        out["deploy_roots"] = {"error": str(exc)}
        out["deploy_config_present"] = False
    else:
        out["deploy_config_present"] = True
        out["target"] = inspect_target(roots["artifact_root"])
        out["freshness"] = freshness_check(
            Path(roots["state_root"]))
    try:
        src = read_pinned_source(Path(args.repo))
        out["pinned_source_ok"] = True
        out["pinned_source"] = {
            "commit": src["commit"], "json_sha256": src["json_sha256"],
            "digest_sha256": src["digest_sha256"]}
    except ProvenanceGuardError as exc:
        out["pinned_source_ok"] = False
        out["pinned_source_error"] = str(exc)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    ok = (out["env_whitelist_ok"] and out.get("deploy_config_present")
          and out.get("pinned_source_ok"))
    return 0 if ok else 2


def cmd_prepare(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_qaf_provenance_guard import (
        install_to_target, run_same_source_verify,
    )
    bad = _env_violations()
    if bad:
        print(json.dumps({"refused": f"环境白名单违规 {bad}",
                          "one_shot_writes": 0},
                         ensure_ascii=False))
        return 96
    roots = _roots(Path(args.deploy_root), args.attempt)
    src = read_pinned_source(
        Path(args.repo),
        args.commit
        or __import__(
            "rl_curriculum.curriculum261_qaf_provenance_guard",
            fromlist=["PROVENANCE_SOURCE_COMMIT_DEFAULT"]
        ).PROVENANCE_SOURCE_COMMIT_DEFAULT)
    result = install_to_target(
        Path(roots["artifact_root"]), src,
        allow_replace_broken=args.allow_replace_broken)
    verify = run_same_source_verify(
        Path(args.project_dir), Path(roots["artifact_root"]))
    out = {"format": ENTRY_FORMAT, "cmd": "prepare",
           "attempt": args.attempt, "roots": roots,
           "install": result, "same_source_verify": verify,
           "one_shot_writes": 0, "business_leaf_calls": 0}
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0 if verify.get("ok") else 2


def cmd_execute(args: argparse.Namespace) -> int:
    """经批准的一次性执行(签发→launch;本轮禁止真实使用)。

    顺序:环境白名单 → preissue 硬门 → 批准原件 → authority
    init/record-approval → issue-permit → prereg → admission →
    launch(P2 形态)→ 收尾。每一步写前先查在场(create-only 跳过
    或拒绝),一次性资源在场=受控停下,不重复签发。
    """
    bad = _env_violations()
    if bad:
        print(json.dumps({
            "refused": f"环境白名单违规 {bad}(入口自装环境;"
                       f"操作员不得手写重定向)",
            "phase": "before_any_write", "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    if args.stop_after == "verify-formal-logs" \
            and not args.model_update:
        print(json.dumps({
            "refused": "A2 完整链含第 14 步 smoke(模型更新):必须"
                       "同时 --model-update(双参数口径一致)",
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 2
    if args.stop_after == "qualify" and args.model_update:
        print(json.dumps({
            "refused": "stop-after=qualify 与 --model-update 口径"
                       "不一致",
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 2
    deploy_root = Path(args.deploy_root)
    project_dir = Path(args.project_dir)
    repo = Path(args.repo)
    if args.sentinel_before_chain:
        if not args.test_domain:
            print(json.dumps({
                "refused": "真实根禁止 --sentinel-before-chain"
                           "(哨兵只存在于隔离测试域;须显式"
                           "--test-domain)",
                "one_shot_writes": 0,
            }, ensure_ascii=False))
            return 96
        if _is_production_root(deploy_root):
            print(json.dumps({
                "refused": f"部署根 {deploy_root} 属生产根清单,"
                           f"禁止哨兵试跑(一次性资格会被消耗)",
                "one_shot_writes": 0,
            }, ensure_ascii=False))
            return 96
    # 1) 签发前硬门(全只读;含目标安装/同源验证/新鲜度)
    try:
        gate = preissue_gate(
            repo=(Path(args.guard_repo) if args.guard_repo else repo),
            deploy_root=deploy_root,
            project_dir=project_dir, attempt=args.attempt)
    except ProvenanceGuardError as exc:
        print(json.dumps({"refused": f"签发前守卫拒绝: {exc}",
                          "one_shot_writes": 0},
                         ensure_ascii=False))
        return 96
    if not gate.get("ok"):
        print(json.dumps({
            "refused": "签发前守卫拒绝: " + str(gate.get("refusal")),
            "guard_report": gate.get("checks"),
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    roots = _roots(deploy_root, args.attempt)
    # RC03 修复(RC gate1 F1):首个一次性写之前核清批准原件与
    # 调用参数绑定(launch 同款只读校验;不得等 permit/admission
    # 落盘后才首次发现不符)。
    try:
        approval_doc = json.loads(
            Path(args.approval_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "refused": f"批准原件不可读/不可解析: {exc}",
            "phase": "before_first_one_shot",
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    from rl_curriculum.curriculum261_qaf_attempt import (
        qaf_input_scope_for_attempt,
    )
    from rl_curriculum.curriculum261_qprod_coordinate import (
        qprod_coordinate_code_identity,
    )
    from rl_curriculum.curriculum261_qprod_formal import (
        validate_formal_approval,
    )
    from rl_curriculum.curriculum261_qprod_formal_levela import (
        build_formal_level_a_plan,
    )
    from rl_curriculum.curriculum261_qprod_plan import (
        research_plan_digest,
    )
    tree_digest = subprocess.run(
        ["git", "-C", str(repo), "rev-parse",
         args.code_freeze_sha + "^{tree}"],
        capture_output=True, text=True)
    if tree_digest.returncode != 0 \
            or tree_digest.stdout.strip() != args.plan_digest:
        print(json.dumps({
            "refused": ("--plan-digest 与候选 Commit A tree digest "
                        "重算不一致(首签发前拒绝)"),
            "recomputed_tree": tree_digest.stdout.strip(),
            "claimed": args.plan_digest,
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    try:
        _payload = build_formal_level_a_plan(
            code_freeze_sha=args.code_freeze_sha,
            code_identity=qprod_coordinate_code_identity(),
            authorized_stop_after=args.stop_after,
            model_update_authorized=bool(args.model_update),
            formal_attempt=args.attempt)
        validate_formal_approval(
            approval_doc, level="level_a",
            iteration_id=qaf_iteration_id_for_attempt(args.attempt),
            artifact_root=Path(roots["artifact_root"]),
            state_root=Path(roots["state_root"]),
            authority_dir=Path(roots["authority_dir"]),
            code_freeze_sha=args.code_freeze_sha,
            research_plan_digest=research_plan_digest(_payload),
            namespaces=qaf_input_scope_for_attempt(args.attempt),
            coordinate_ids=[],
            quota=_payload["quota"],
            authorized_stop_after=args.stop_after,
            model_update_authorized=bool(args.model_update))
    except Exception as exc:  # noqa: BLE001 门禁统一拒绝面
        print(json.dumps({
            "refused": f"批准↔调用参数绑定核验失败: {exc}",
            "phase": "before_first_one_shot",
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    authority = Path(roots["authority_dir"])
    py = sys.executable
    here = Path(__file__).resolve().parent
    # ---- RCF-02(ReviewClosure 修复轮):首个一次性写之前核清
    # "实际将使用的对象"与已有一次性状态。所有检查只读、零写。
    one_shot_writes = 0
    permit_path = (authority / (
        f"qprod_permit_level_a_{roots['iteration']}.json"))
    approval_path = (authority / (
        f"qprod_formal_approval_level_a_{roots['iteration']}.json"))
    state_root = Path(roots["state_root"])
    if permit_path.exists():
        print(json.dumps({
            "refused": f"许可已在场 {permit_path}(一次性资源;先核实"
                       f"既有原件与消费状态,不重复签发)",
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 4
    admission_file = deploy_root / ".r17_formal_admission.json"
    consumed_log = state_root / "r17_admission_consumed.jsonl"
    issuance_log = state_root / "r17_admission_issuance.log.jsonl"
    if admission_file.exists() or consumed_log.exists() \
            or issuance_log.exists():
        print(json.dumps({
            "refused": ("admission 已签发/消费或签发日志在场(一次性"
                        "资源;受控停下先核清状态,不生成新 permit)"),
            "state": {
                "admission_file": admission_file.exists(),
                "consumed_log": consumed_log.exists(),
                "issuance_log": issuance_log.exists()},
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 4
    # 已存批准原件 = 签发实际读取对象;必须与刚校验的传入批准
    # 同 digest(不同名静默跳过 = 校验对象与使用对象分离)。
    if approval_path.is_file():
        from rl_curriculum.curriculum261_qprod_formal import (
            formal_approval_digest,
        )
        try:
            stored_approval = json.loads(
                approval_path.read_text(encoding="utf-8"))
            stored_digest = formal_approval_digest(stored_approval)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({
                "refused": f"已存批准原件不可读/不可解析: {exc}",
                "one_shot_writes": 0,
            }, ensure_ascii=False))
            return 96
        input_digest = approval_doc.get("approval_digest")
        if stored_digest != input_digest:
            print(json.dumps({
                "refused": ("authority 已存批准原件与传入批准 digest "
                            "不一致(签发读取已存原件;校验对象必须"
                            "=使用对象):停止,不覆盖不跳过"),
                "stored_approval_digest": stored_digest,
                "input_approval_digest": input_digest,
                "one_shot_writes": 0,
            }, ensure_ascii=False))
            return 96
    # 同根证据适用性只读预检(permit 写前;完整核验仍在 admission
    # issuer——时点前移,不是替代)。
    try:
        evidence_doc = json.loads(
            Path(args.regression_evidence).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(json.dumps({
            "refused": f"回归证据不可读/不可解析: {exc}",
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    evidence_problems: list[str] = []
    if evidence_doc.get("format") != (
            "cur261-r17-candidate-regression-evidence-v6"):
        evidence_problems.append("format 非 v6")
    if evidence_doc.get("commit_a_sha") != args.code_freeze_sha:
        bound = str(evidence_doc.get("commit_a_sha") or "?")[:12]
        evidence_problems.append(
            f"record 绑定候选 {bound} != 调用 "
            f"{args.code_freeze_sha[:12]}")
    _counts = evidence_doc.get("counts") or {}
    if _counts.get("failures") or _counts.get("errors"):
        evidence_problems.append(
            f"record 计数非零失败/错误: {_counts}")
    if evidence_problems:
        print(json.dumps({
            "refused": "同根回归证据适用性预检失败(首 permit 写前): "
                       + "; ".join(evidence_problems),
            "one_shot_writes": 0,
        }, ensure_ascii=False))
        return 96
    # 2) authority init(create-only;在场跳过)
    if not (authority / "authority_identity.json").is_file():
        r = subprocess.run(
            [py, str(here / "qprod_formal_authority.py"), "init",
             "--dir", str(authority)], capture_output=True, text=True)
        if r.returncode != 0:
            print(json.dumps({"refused": "authority init 失败:"
                                       + r.stdout + r.stderr,
                              "one_shot_writes": 0},
                             ensure_ascii=False))
            return 96
    # 3) record-approval(create-only;在场跳过)
    approval_path = (authority / (
        f"qprod_formal_approval_level_a_{roots['iteration']}.json"))
    if not approval_path.is_file():
        r = subprocess.run(
            [py, str(here / "qprod_formal_authority.py"),
             "record-approval", "--dir", str(authority),
             "--approval-json", str(Path(args.approval_json).resolve())],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(json.dumps({"refused": "record-approval 拒绝:"
                                       + r.stdout + r.stderr,
                              "one_shot_writes": 0},
                             ensure_ascii=False))
            return 96
    # 4) issue-permit(守卫内建;在场=受控停下不重签——RCF-02 预检
    # 已在首写前拒绝同场次重入;此处为防御性二次确认,零新写)
    if permit_path.is_file():
        print(json.dumps({
            "refused": f"许可已在场 {permit_path}(一次性资源;"
                       f"先核实既有原件与消费状态,不重复签发)",
            "one_shot_writes": one_shot_writes,
        }, ensure_ascii=False))
        return 4
    r = subprocess.run(
        [py, str(here / "qprod_formal_authority.py"), "issue-permit",
         "--dir", str(authority), "--deploy-root", str(deploy_root),
         "--task-level", "level_a", "--attempt", args.attempt,
         "--repo", str(args.guard_repo or repo),
         "--project-dir", str(project_dir)],
        capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(json.dumps({"refused": f"issue-permit rc={r.returncode}",
                          "one_shot_writes": one_shot_writes,
                          "stderr": r.stderr[-400:]},
                         ensure_ascii=False))
        return 96
    # permit 已落盘:此后任何拒绝的写计数如实为 1
    one_shot_writes = 1
    # 5) prereg + admission(守卫内建;RCF-02 预检已在首写前拒绝
    # 已签发/已消费状态;此处防御性二次确认)
    if (state_root / "r17_admission_consumed.jsonl").is_file() \
            or (deploy_root / ".r17_formal_admission.json").is_file():
        print(json.dumps({
            "refused": "admission 已签发/消费(一次性资源;受控"
                       "停下,不盲目重试)",
            "one_shot_writes": one_shot_writes,
        }, ensure_ascii=False))
        return 4
    prereg_path = authority / f"preregistration_{args.attempt}.json"
    prereg_path.write_text(json.dumps({
        "admission_id": args.admission_id,
        "iteration": roots["iteration"],
        "plan_digest": args.plan_digest,
        "authorization": args.authorization,
        "regression_evidence": str(
            Path(args.regression_evidence).resolve()),
        "plan_digest_method": args.plan_digest_method,
        "deploy_state_root": str(state_root),
        "formal_attempt": args.attempt,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    r = subprocess.run(
        [py, str(here / "r17_admission_issue.py"),
         "--repo", str(repo), "--deploy-root", str(deploy_root),
         "--state-root", str(state_root), "--commit-a",
         args.code_freeze_sha, "--preregistration", str(prereg_path),
         "--project-dir", str(project_dir),
         "--guard-repo", str(args.guard_repo or repo)],
        capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0:
        print(json.dumps({"refused": f"admission 签发 rc="
                                    f"{r.returncode}",
                          "one_shot_writes": one_shot_writes,
                          "stderr": r.stderr[-400:]},
                         ensure_ascii=False))
        return 96
    one_shot_writes = 2
    # 6) 一次性 launch(P2 入口形态;A2 双参数)
    launch_argv = [
        py, str(project_dir / "stage2_6_1_runner"
                / "qprod_formal_level_a_entry.py"), "launch",
        "--deploy-root", str(deploy_root),
        "--project-dir", str(project_dir),
        "--code-freeze-sha", args.code_freeze_sha,
        "--stop-after", args.stop_after,
        "--formal-attempt", args.attempt,
    ]
    if args.model_update:
        launch_argv.append("--model-update")
    if args.sentinel_before_chain:
        launch_argv.append("--sentinel-before-chain")
    if args.child_timeout:
        launch_argv += ["--child-timeout", str(args.child_timeout)]
    launch_env = dict(os.environ)
    if args.leaf_sentinel:
        if not args.test_domain:
            print(json.dumps({
                "refused": ("--leaf-sentinel 仅限 --test-domain "
                            "(科学叶哨兵只在隔离测试域)"),
                "one_shot_writes": one_shot_writes,
            }, ensure_ascii=False))
            return 96
        launch_env["CURRICULUM261_QAF_TEST_LEAF_SENTINEL"] = (
            args.leaf_sentinel)
    proc = subprocess.run(
        launch_argv, cwd=str(project_dir), capture_output=True,
        text=True, env=launch_env)
    print(proc.stdout[-8000:])
    if proc.stderr:
        print(proc.stderr[-2000:], file=sys.stderr)
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="qaf-v2-operator-entry", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_chk = sub.add_parser("check", help="只读状态面")
    p_chk.add_argument("--repo", required=True)
    p_chk.add_argument("--deploy-root", required=True)
    p_chk.add_argument("--attempt", default="qaf_v2",
                       choices=QAF_ATTEMPT_IDS)
    p_chk.set_defaults(fn=cmd_check)

    p_prep = sub.add_parser(
        "prepare", help="安装钉死 provenance 到实际目标+同源复核")
    p_prep.add_argument("--repo", required=True)
    p_prep.add_argument("--deploy-root", required=True)
    p_prep.add_argument("--project-dir", required=True)
    p_prep.add_argument("--commit", default="")
    p_prep.add_argument("--attempt", default="qaf_v2",
                        choices=QAF_ATTEMPT_IDS)
    p_prep.add_argument("--allow-replace-broken", action="store_true")
    p_prep.set_defaults(fn=cmd_prepare)

    p_exe = sub.add_parser(
        "execute", help="经批准的一次性执行(签发→launch)")
    p_exe.add_argument("--repo", required=True)
    p_exe.add_argument("--guard-repo", default=None,
                       help="签发前守卫钉死源仓库(缺省同 --repo)")
    p_exe.add_argument("--deploy-root", required=True)
    p_exe.add_argument("--project-dir", required=True)
    p_exe.add_argument("--approval-json", required=True)
    p_exe.add_argument("--regression-evidence", required=True)
    p_exe.add_argument("--admission-id", required=True)
    p_exe.add_argument("--authorization", required=True)
    p_exe.add_argument("--plan-digest", required=True)
    p_exe.add_argument("--plan-digest-method", default="git_tree_digest")
    p_exe.add_argument("--code-freeze-sha", required=True)
    p_exe.add_argument("--stop-after", default="verify-formal-logs",
                       choices=("qualify", "verify-formal-logs"))
    p_exe.add_argument("--model-update", action="store_true")
    p_exe.add_argument("--attempt", default="qaf_v2",
                       choices=QAF_ATTEMPT_IDS)
    p_exe.add_argument("--sentinel-before-chain", action="store_true")
    p_exe.add_argument("--test-domain", action="store_true",
                       help="显式声明隔离测试域(哨兵仅此域可用)")
    p_exe.add_argument("--child-timeout", type=int, default=None)
    p_exe.add_argument("--leaf-sentinel", default=None,
                       metavar="STEP",
                       help=("测试域科学叶哨兵(仅 --test-domain;"
                             "如 determinism-matrix:在该叶首个昂贵"
                             "科学调用边界停止,科学零执行)"))
    p_exe.set_defaults(fn=cmd_execute)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
