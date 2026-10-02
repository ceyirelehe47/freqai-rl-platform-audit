#!/usr/bin/env python3
"""QProd 正式 Level B 入口(RouteC_FormalLaunch_Preparation_v1)。

子命令:
- draft-plan:把 11 坐标正式研究计划草案写入准备工作目录(零生成;
  namespace/seed/预算逐项可预检);
- preflight:只读预检(重复执行内容身份不变);
- plan-freeze:门禁(部署配置 formal_ready+批准原件+正式许可校验)
  通过后把计划 create-only 冻结进正式 state root;
- lock-coordinates:11 坐标逐一传入现有坐标锁
  (lock_coordinate_audit_plan;formal 预算 500/1e6 不可降级);
- consume-permit:整批一次性消费正式许可;
- run-coordinate:原生预算硬门 + 已消费验证 + 现有坐标审计执行核心
  (run_coordinate_audit_locked → _run_cue_contract_audit_core,
  formal=True);
- aggregate / cold-read:现有 v4 聚合 reader(负结果保留;collect_all_k)。

真实正式研究仍 NOT_RUN:以上全部需要 formal_ready 部署配置、
用户批准原件与正式许可,当前都不存在。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rl_curriculum.curriculum261_qprod_context import (  # noqa: E402
    QProdContextError, harden_root)
from rl_curriculum.curriculum261_qprod_coordinate import (  # noqa: E402
    QPROD_NATIVE_BUDGET_NAME, assert_no_dangling_started,
    assert_no_technical_interruption,
    check_native_budget, lock_coordinate_audit_plan,
    mark_native_completed, qprod_coordinate_code_identity,
    reserve_native_execution, run_coordinate_audit_locked)
from rl_curriculum.curriculum261_qprod_formal import (  # noqa: E402
    QPROD_FORMAL_LEVEL_B_ITERATION_ID, _read_formal_roots,
    build_formal_context, build_formal_level_b_plan,
    load_formal_approval, preflight_formal_level_b,
    validate_formal_approval, validate_formal_permit)
from rl_curriculum.curriculum261_qprod_permit import (  # noqa: E402
    LivePermitToken, consume_permit, load_permit,
    permit_already_consumed)
from rl_curriculum.curriculum261_qprod_plan import (  # noqa: E402
    freeze_research_plan, load_research_plan, research_plan_digest)


def _code_identity() -> dict[str, str]:
    return qprod_coordinate_code_identity()


def _plan_payload(code_freeze_sha: str) -> dict:
    return build_formal_level_b_plan(
        code_freeze_sha=code_freeze_sha,
        code_identity=_code_identity())


def _gated_roots_and_permit(deploy_root: Path, code_freeze_sha: str):
    """门禁:根解析(拒绝即返回错误信息)+批准+许可校验(只读)。"""
    art, state, authority = _read_formal_roots(
        deploy_root, level="level_b",
        iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID)
    payload = _plan_payload(code_freeze_sha)
    digest = research_plan_digest(payload)
    approval = load_formal_approval(
        authority, level="level_b",
        iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID)
    validate_formal_approval(
        approval, level="level_b",
        iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
        artifact_root=art, state_root=state, authority_dir=authority,
        code_freeze_sha=code_freeze_sha, research_plan_digest=digest,
        namespaces=[c["model_namespace"] for c in
                    payload["coordinate_manifest"]]
        + [c["validation_namespace"] for c in
           payload["coordinate_manifest"]],
        coordinate_ids=[c["coordinate_id"] for c in
                        payload["coordinate_manifest"]],
        quota=payload["quota"], authorized_stop_after=None,
        model_update_authorized=False)
    ctx = build_formal_context(
        deploy_root, level="level_b",
        iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID,
        code_freeze_sha=code_freeze_sha,
        research_plan_digest=digest,
        approval_digest=approval["approval_digest"])
    permit = validate_formal_permit(ctx.permit_path, context=ctx)
    return ctx, payload, digest, permit


def cmd_draft_plan(args: argparse.Namespace) -> int:
    payload = _plan_payload(args.code_freeze_sha or "")
    digest = research_plan_digest(payload)
    prep = Path(args.prep_dir)
    prep.mkdir(parents=True, exist_ok=True)
    out = {
        "format": "cur261-qprod-formal-draft-plan-v1",
        "level": "level_b",
        "iteration_id": QPROD_FORMAL_LEVEL_B_ITERATION_ID,
        "status": "DRAFT_PENDING_USER_APPROVAL",
        "code_freeze_sha_binding": (
            "批准/签发/冻结绑定最终 Commit A 真实 SHA;空 SHA 草案"
            "仅用于准备审阅,不可进入批准/签发"),
        "code_freeze_sha": args.code_freeze_sha or "",
        "research_plan_digest": digest,
        "payload": payload,
    }
    path = prep / "qprod_formal_level_b_draft_plan.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(json.dumps({"draft_plan": str(path),
                      "research_plan_digest": digest,
                      "coordinates": len(payload["coordinate_manifest"])
                      }, ensure_ascii=False))
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    report = preflight_formal_level_b(
        args.deploy_root, code_freeze_sha=args.code_freeze_sha or "",
        code_identity=_code_identity())
    print(json.dumps(report, ensure_ascii=False, indent=2,
                     default=str))
    return 0 if report["status"] == "PREPARED_PENDING_USER_APPROVAL" \
        else 1


def cmd_plan_freeze(args: argparse.Namespace) -> int:
    try:
        ctx, payload, digest, _permit = _gated_roots_and_permit(
            Path(args.deploy_root).resolve(), args.code_freeze_sha)
    except QProdContextError as exc:
        print(json.dumps({
            "refused": str(exc),
            "phase": "before_first_controlled_side_effect",
        }, ensure_ascii=False))
        return 96
    harden_root(ctx.state_root, label="state_root", create=True)
    harden_root(ctx.artifact_root, label="artifact_root", create=True)
    _, digest = freeze_research_plan(ctx.state_root, payload)
    print(json.dumps({"research_plan_digest": digest,
                      "state_root": str(ctx.state_root)},
                     ensure_ascii=False))
    return 0


def cmd_lock_coordinates(args: argparse.Namespace) -> int:
    try:
        ctx, _payload, _digest, _permit = _gated_roots_and_permit(
            Path(args.deploy_root).resolve(), args.code_freeze_sha)
    except QProdContextError as exc:
        print(f"[lock-coordinates] 拒绝: {exc}")
        return 96
    plan = load_research_plan(ctx.state_root)
    out = {}
    for coord in plan["coordinate_manifest"]:
        coord_dir = ctx.artifact_root / coord["artifact_subdir"]
        _, cap_digest = lock_coordinate_audit_plan(
            coord_dir, coordinate=coord, research_plan=plan)
        out[coord["coordinate_id"]] = cap_digest
    print(json.dumps({"coordinate_audit_plan_digests": out},
                     ensure_ascii=False))
    return 0


def cmd_consume_permit(args: argparse.Namespace) -> int:
    try:
        ctx, _payload, _digest, _permit = _gated_roots_and_permit(
            Path(args.deploy_root).resolve(), args.code_freeze_sha)
    except QProdContextError as exc:
        print(f"[consume-permit] 拒绝(门禁/许可校验未过): {exc}")
        return 96
    try:
        rec = consume_permit(ctx.permit_path, context=ctx)
    except QProdContextError as exc:
        if permit_already_consumed(ctx, _permit_id_of(ctx)):
            print(json.dumps({
                "permit": "already-consumed(本执行集已消费)",
                "permit_id": _permit_id_of(ctx)}, ensure_ascii=False))
            return 0
        print(f"[consume-permit] 拒绝: {exc}")
        return 96
    print(json.dumps({"consumed_permit_id": rec["permit_id"]},
                     ensure_ascii=False))
    return 0


def _permit_id_of(ctx) -> str:
    return str(load_permit(ctx.permit_path)["permit_id"])


def cmd_run_coordinate(args: argparse.Namespace) -> int:
    try:
        ctx, _payload, _digest, permit = _gated_roots_and_permit(
            Path(args.deploy_root).resolve(), args.code_freeze_sha)
    except QProdContextError as exc:
        print(f"[run-coordinate] 拒绝(零叶调用): {exc}")
        return 96
    plan = load_research_plan(ctx.state_root)
    coord = next((c for c in plan["coordinate_manifest"]
                  if c["coordinate_id"] == args.coordinate_id), None)
    if coord is None:
        print(f"[run-coordinate] 坐标不在计划清单: {args.coordinate_id}")
        return 2
    if not permit_already_consumed(ctx, str(permit["permit_id"])):
        print("[run-coordinate] 许可未消费(先 consume-permit;"
              "零叶调用)")
        return 96
    # 原生执行预算:持久预占(修复轮 R3/F08)。剩余=max−len(started);
    # 进入受控动作**前**原子落盘——异常/KeyboardInterrupt/进程退出
    # 后已开始执行不回收额度;文件缺失拒绝;同坐标重复不双记。
    budget_path = ctx.state_root / QPROD_NATIVE_BUDGET_NAME
    try:
        assert_no_technical_interruption(
            ctx.artifact_root, plan["coordinate_manifest"])
        assert_no_dangling_started(
            budget_path, ctx.artifact_root,
            plan["coordinate_manifest"])
        check_native_budget(budget_path, needed=1)
        reserve_native_execution(
            budget_path, coordinate_id=args.coordinate_id,
            artifact_root=ctx.artifact_root,
            coordinate_manifest=plan["coordinate_manifest"])
    except QProdContextError as exc:
        print(f"[run-coordinate] 原生预算/后继门拒绝(零叶调用):"
              f" {exc}")
        return 96
    live = LivePermitToken(permit, {"consumed_via": "consume-permit"})
    coord_dir = ctx.artifact_root / coord["artifact_subdir"]
    ledger_path = ctx.artifact_root.parent / "qprod_quota_ledger.jsonl"
    out = run_coordinate_audit_locked(
        ctx, live, args.coordinate_id, coord_dir=coord_dir,
        ledger_path=ledger_path)
    # 正常返回后的观测记账(额度判定不依赖;中断路径由 started
    # 预占 + interrupted 标记保守保留)。
    try:
        mark_native_completed(budget_path,
                              coordinate_id=args.coordinate_id)
    except QProdContextError:
        pass
    seal = out["seal"]
    print(json.dumps({
        "coordinate_id": seal["coordinate_id"],
        "audit_pass": seal["summary"]["audit_pass"],
        "recall_validation": seal["summary"]["recall_validation"],
        "se_validation": seal["summary"]["se_validation"],
        "p_contract_local": seal["summary"]["p_contract_local"],
        "generation": out["generation"],
    }, ensure_ascii=False))
    return 0


def cmd_aggregate(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_qprod_aggregate import (
        aggregate_research, write_aggregate_report,
    )
    try:
        art, state, _authority = _read_formal_roots(
            Path(args.deploy_root).resolve(), level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID)
    except QProdContextError as exc:
        print(f"[aggregate] 拒绝: {exc}")
        return 96
    report = aggregate_research(art, state_root=state)
    out_path = art / "qprod_aggregate_report.json"
    write_aggregate_report(report, out_path)
    print(json.dumps({
        "report": str(out_path),
        "valid_coordinate_count": report["valid_coordinate_count"],
        "planned_k": report["planned_k"],
        "primary": report["primary"],
    }, ensure_ascii=False, default=str))
    return 0


def cmd_cold_read(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_qprod_aggregate import (
        aggregate_research,
    )
    try:
        art, state, _authority = _read_formal_roots(
            Path(args.deploy_root).resolve(), level="level_b",
            iteration_id=QPROD_FORMAL_LEVEL_B_ITERATION_ID)
    except QProdContextError as exc:
        print(f"[cold-read] 拒绝: {exc}")
        return 96
    stored = json.loads(
        (art / "qprod_aggregate_report.json").read_text(
            encoding="utf-8"))
    fresh = aggregate_research(art, state_root=state)
    same = (
        stored["primary"].get("magnitude")
        == fresh["primary"].get("magnitude")
        and stored["valid_coordinate_count"]
        == fresh["valid_coordinate_count"]
        and len(stored["coordinates"]) == len(fresh["coordinates"]))
    print(json.dumps({"cold_read_reproduces": same,
                      "coordinates": len(fresh["coordinates"])},
                     ensure_ascii=False))
    return 0 if same else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qprod-formal-level-b", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_draft = sub.add_parser("draft-plan")
    p_draft.add_argument("--prep-dir", required=True)
    p_draft.add_argument("--code-freeze-sha", default="")
    p_draft.set_defaults(fn=cmd_draft_plan)
    p_pre = sub.add_parser("preflight")
    p_pre.add_argument("--deploy-root", required=True)
    p_pre.add_argument("--code-freeze-sha", default="")
    p_pre.set_defaults(fn=cmd_preflight)
    for name, fn in (
            ("plan-freeze", cmd_plan_freeze),
            ("lock-coordinates", cmd_lock_coordinates),
            ("consume-permit", cmd_consume_permit),
            ("run-coordinate", cmd_run_coordinate)):
        p = sub.add_parser(name)
        p.add_argument("--deploy-root", required=True)
        p.add_argument("--code-freeze-sha", required=True)
        if name == "run-coordinate":
            p.add_argument("--coordinate-id", required=True)
        p.set_defaults(fn=fn)
    p_agg = sub.add_parser("aggregate")
    p_agg.add_argument("--deploy-root", required=True)
    p_agg.set_defaults(fn=cmd_aggregate)
    p_cold = sub.add_parser("cold-read")
    p_cold.add_argument("--deploy-root", required=True)
    p_cold.set_defaults(fn=cmd_cold_read)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
