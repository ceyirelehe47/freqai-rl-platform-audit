#!/usr/bin/env python3
"""QProd 正式 admission authority(操作员侧签发边界;非被验包)。

职责(与工程 test authority qprod_eng_authority.py 严格分离):
- init:创建 formal_admission_authority 身份(create-only);
- record-approval:把用户批准原件(按 cur261-qprod-formal-
  approval-v1 结构、绑定 statement_digest 的用户原文)create-only
  记录进 authority 目录;
- issue-permit:只依在场批准原件签发正式许可——许可字段全部取自
  批准绑定(候选/计划 digest/两根/authority/范围/配额/停止边界/
  模型更新授权),并与受信任部署配置(formal_ready)交叉核对;
  无批准、批准被改、根不一致、重复签发一律拒绝。

本工具不写部署配置、不创建正式根、不消费许可、不运行业务链。
测试域使用时 authority/批准/许可只落在隔离测试目录,不得指向
生产部署。签发能力不在被验 src(permit 模块仍只有验证/消费)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rl_curriculum.curriculum261_qprod_context import (  # noqa: E402
    QProdContextError, load_deploy_config)
from rl_curriculum.curriculum261_qprod_permit import (  # noqa: E402
    permit_digest)
from rl_curriculum.curriculum261_qprod_formal import (  # noqa: E402
    QPROD_FORMAL_AUTHORITY_KIND, QPROD_FORMAL_LEVEL_A_ITERATION_ID,
    QPROD_FORMAL_LEVEL_B_ITERATION_ID, formal_approval_digest,
    formal_approval_name)
from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF_ATTEMPT_IDS, qaf_iteration_id_for_attempt)

AUTHORITY_IDENTITY_FORMAT = "cur261-qprod-authority-identity-v1"
FORMAL_LEVELS = ("level_a", "level_b")
ITERATIONS = {
    "level_a": QPROD_FORMAL_LEVEL_A_ITERATION_ID,
    "level_b": QPROD_FORMAL_LEVEL_B_ITERATION_ID,
}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_init(args: argparse.Namespace) -> int:
    adir = Path(args.dir)
    adir.mkdir(parents=True, exist_ok=True)
    ident_path = adir / "authority_identity.json"
    if ident_path.is_file():
        existing = json.loads(ident_path.read_text(encoding="utf-8"))
        if existing.get("kind") == QPROD_FORMAL_AUTHORITY_KIND:
            print(json.dumps({
                "authority_id": existing["authority_id"],
                "note": "already-initialized(create-only)"},
                ensure_ascii=False))
            return 0
        print(f"[init] 目录已含非正式 authority 身份: {ident_path}")
        return 1
    authority_id = args.authority_id or (
        "qprod-formal-authority-"
        + hashlib.sha256(str(adir.resolve()).encode("utf-8")
                         ).hexdigest()[:12])
    ident_path.write_text(json.dumps({
        "format": AUTHORITY_IDENTITY_FORMAT,
        "authority_id": authority_id,
        "kind": QPROD_FORMAL_AUTHORITY_KIND,
        "note": ("正式许可签发边界:只依用户批准原件签发;工程 "
                 "authority/测试 authority 不可签正式许可"),
        "created_utc": _now(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"authority_id": authority_id,
                      "identity": str(ident_path)}, ensure_ascii=False))
    return 0


def _validate_approval_internal(approval: dict) -> list[str]:
    problems: list[str] = []
    level = approval.get("task_level")
    if level not in FORMAL_LEVELS:
        problems.append(f"task_level {level!r} 非法")
        return problems
    _legal_iters = (
        {qaf_iteration_id_for_attempt(a) for a in QAF_ATTEMPT_IDS}
        if level == "level_a" else {ITERATIONS[level]})
    if approval.get("iteration_id") not in _legal_iters:
        problems.append(
            f"iteration_id {approval.get('iteration_id')!r} != 正式"
            f"迭代(合法: {sorted(_legal_iters)})")
    approved = approval.get("approved") or {}
    stop = approved.get("authorized_stop_after")
    model_update = bool(approved.get("model_update_authorized"))
    if level == "level_a":
        if stop not in ("qualify", "verify-formal-logs"):
            problems.append(f"authorized_stop_after {stop!r} 非法")
        elif stop == "verify-formal-logs" and not model_update:
            problems.append(
                "完整链含第 14 步 smoke(模型更新):必须"
                " model_update_authorized=true")
        elif stop == "qualify" and model_update:
            problems.append(
                "stop=qualify 而 model_update_authorized=true:"
                "授权与停止边界不一致")
    else:
        if stop is not None:
            problems.append(
                "level_b 无 authorized_stop_after(停止政策在研究"
                "计划 stop_mode)")
        if model_update:
            problems.append("level_b 不含模型更新授权")
    quota = approved.get("quota")
    if not isinstance(quota, dict) or not quota:
        problems.append("quota 缺/非法")
    if approval.get("approval_digest") != formal_approval_digest(
            approval):
        problems.append("approval_digest 失配(须由提供方按 canonical"
                        " 规则重算后写入)")
    return problems


def cmd_record_approval(args: argparse.Namespace) -> int:
    adir = Path(args.dir)
    src = Path(args.approval_json)
    if not src.is_file():
        print(f"[record-approval] 批准原件文件缺失: {src}")
        return 1
    try:
        approval = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[record-approval] 批准原件不可解析: {exc}")
        return 1
    problems = _validate_approval_internal(approval)
    if problems:
        print(f"[record-approval] 批准原件结构/一致性拒绝: {problems}")
        return 1
    level = approval["task_level"]
    target = adir / formal_approval_name(level,
                                         approval["iteration_id"])
    if target.is_file():
        print(f"[record-approval] 批准原件已存在(create-only): "
              f"{target}")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(approval, ensure_ascii=False,
                                 indent=2), encoding="utf-8")
    print(json.dumps({
        "recorded_approval": str(target),
        "approval_id": approval.get("approval_id"),
        "approval_digest": approval.get("approval_digest"),
    }, ensure_ascii=False))
    return 0


def cmd_issue_permit(args: argparse.Namespace) -> int:
    adir = Path(args.dir)
    level = args.task_level
    if level not in FORMAL_LEVELS:
        print(f"[issue-permit] task-level 非法: {level}")
        return 2
    attempt = getattr(args, "attempt", None) or "qaf_v1"
    if level == "level_a":
        iteration_id = qaf_iteration_id_for_attempt(attempt)
    else:
        iteration_id = ITERATIONS[level]
    # A2-R2 签发前硬门:新尝试(qaf_v2)的许可签发在第一次一次性写
    # 之前必须通过 provenance 守卫(固定 Git 源/实际目标/同源
    # verifier/新鲜度);绕过统一入口直接调用本命令同样过此门。
    if level == "level_a" and attempt != "qaf_v1":
        repo = getattr(args, "repo", None)
        project_dir = getattr(args, "project_dir", None)
        if not repo or not project_dir:
            print(json.dumps({
                "refused": (
                    f"attempt={attempt} 签发必须提供 --repo 与 "
                    f"--project-dir(签发前 provenance 守卫;不得以"
                    f"缺参绕过前置检查)"),
                "one_shot_writes": 0,
            }, ensure_ascii=False))
            return 96
        from rl_curriculum.curriculum261_qaf_provenance_guard import (
            ProvenanceGuardError, preissue_gate,
        )
        try:
            gate = preissue_gate(
                repo=Path(repo), deploy_root=Path(args.deploy_root),
                project_dir=Path(project_dir), attempt=attempt)
        except ProvenanceGuardError as exc:
            print(json.dumps({"refused": f"签发前守卫拒绝: {exc}",
                              "one_shot_writes": 0},
                             ensure_ascii=False))
            return 96
        if not gate.get("ok"):
            print(json.dumps({
                "refused": (
                    "签发前守卫拒绝(首一次性写前): "
                    + str(gate.get("refusal"))),
                "guard_report": gate.get("checks"),
                "one_shot_writes": 0,
            }, ensure_ascii=False))
            return 96
    approval_path = adir / formal_approval_name(level, iteration_id)
    if not approval_path.is_file():
        print(f"[issue-permit] 用户批准原件缺失: {approval_path}"
              f"(没有批准不签发;不得以工程 authority/自写 PASS "
              f"替代)")
        return 96
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    problems = _validate_approval_internal(approval)
    if problems:
        print(f"[issue-permit] 批准原件无效: {problems}")
        return 96
    approved = approval["approved"]
    # 受信任部署配置交叉核对:批准绑定根必须与 formal_ready 配置
    # 一致(签发不接受批准指向未登记/不一致部署)。
    try:
        cfg = load_deploy_config(args.deploy_root)
    except QProdContextError as exc:
        print(f"[issue-permit] 受信任部署配置拒绝: {exc}")
        return 96
    entry = (cfg.get("formal_roots") or {}).get(iteration_id) or {}
    for key in ("artifact_root", "state_root", "authority_dir"):
        want = str(Path(str(entry.get(key, ""))).resolve()
                   ) if entry.get(key) else ""
        have = str(Path(str(approved.get(key))).resolve())
        if not want or want != have:
            print(f"[issue-permit] 批准绑定 {key}={have!r} 与受信任"
                  f"部署配置 {want!r} 不一致(签发拒绝)")
            return 96
    ident_path = adir / "authority_identity.json"
    if not ident_path.is_file():
        print(f"[issue-permit] authority 身份缺失(先 init): "
              f"{ident_path}")
        return 96
    ident = json.loads(ident_path.read_text(encoding="utf-8"))
    if ident.get("kind") != QPROD_FORMAL_AUTHORITY_KIND:
        print(f"[issue-permit] authority 身份种类 "
              f"{ident.get('kind')!r} 非正式(不签发)")
        return 96
    permit_id = args.permit_id or (
        "qppm-formal-" + hashlib.sha256(
            (approval["approval_digest"] + "|"
             + iteration_id).encode("utf-8")).hexdigest()[:16])
    permit = {
        "format": "cur261-qprod-permit-v1",
        "permit_id": permit_id,
        "task_level": level,
        "iteration_id": iteration_id,
        "code_freeze_sha": approved["code_freeze_sha"],
        "artifact_root": str(Path(approved["artifact_root"]).resolve()),
        "state_root": str(Path(approved["state_root"]).resolve()),
        "preregistered_input_scope": {
            "namespaces": list(approved["namespaces"] or []),
            "coordinate_ids": list(approved["coordinate_ids"] or []),
        },
        "quota": dict(approved["quota"]),
        "issuer": {
            "kind": QPROD_FORMAL_AUTHORITY_KIND,
            "authority_id": ident["authority_id"],
            "approval_id": approval["approval_id"],
        },
        "research_plan_digest": approved["research_plan_digest"],
        "approval_digest": approval["approval_digest"],
        "authorized_stop_after": approved["authorized_stop_after"],
        "model_update_authorized": bool(
            approved["model_update_authorized"]),
        "issued_utc": _now(),
    }
    permit["permit_digest"] = permit_digest(permit)
    out_path = adir / f"qprod_permit_{level}_{iteration_id}.json"
    if out_path.is_file():
        print(f"[issue-permit] 许可已存在(签发一次性): {out_path}")
        return 1
    out_path.write_text(json.dumps(permit, ensure_ascii=False,
                                   indent=2), encoding="utf-8")
    print(json.dumps({"permit_path": str(out_path),
                      "permit_id": permit_id,
                      "permit_digest": permit["permit_digest"],
                      "bound_approval_digest":
                          approval["approval_digest"]},
                     ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qprod-formal-authority", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init", help="创建正式 authority 身份")
    p_init.add_argument("--dir", required=True)
    p_init.add_argument("--authority-id", default=None)
    p_init.set_defaults(fn=cmd_init)
    p_appr = sub.add_parser(
        "record-approval", help="create-only 记录用户批准原件")
    p_appr.add_argument("--dir", required=True)
    p_appr.add_argument("--approval-json", required=True)
    p_appr.set_defaults(fn=cmd_record_approval)
    p_issue = sub.add_parser(
        "issue-permit", help="依批准原件签发正式许可(一次性)")
    p_issue.add_argument("--dir", required=True)
    p_issue.add_argument("--deploy-root", required=True)
    p_issue.add_argument("--task-level", required=True,
                         choices=FORMAL_LEVELS)
    p_issue.add_argument("--permit-id", default=None)
    p_issue.add_argument("--attempt", default="qaf_v1",
                         choices=QAF_ATTEMPT_IDS,
                         help="level_a 尝试;qaf_v2 触发签发前"
                              "provenance 守卫(强制)")
    p_issue.add_argument("--repo", default=None,
                         help="签发前守卫用 Git 仓库(qaf_v2 必填)")
    p_issue.add_argument("--project-dir", default=None,
                         help="签发前守卫同源验证用部署树"
                              "(qaf_v2 必填)")
    p_issue.set_defaults(fn=cmd_issue_permit)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
