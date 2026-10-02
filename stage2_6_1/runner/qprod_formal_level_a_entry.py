#!/usr/bin/env python3
"""QProd 正式 Level A 启动入口(RouteC_FormalLaunch_Preparation_v1)。

子命令:
- draft-plan:把正式 run-plan 草案(含 digest、命令清单、预算表)
  写入准备工作目录(不触正式根;草案身份即冻结身份——digest 排除
  locked_utc,冻结与草案逐字节同 digest);
- preflight:只读预检(部署配置/根形态/admission 在场/链排程/
  校准后依赖产出映射;重复执行内容身份不变);
- launch:门禁(批准原件+正式许可+admission+根新鲜+停止边界一致)
  全部通过后才产生受控副作用;--sentinel-before-chain 在权威链
  执行器调用边界前记录真实解析产物并诚实中断(零步骤执行)。

真实正式资格链仍 NOT_RUN:launch 需要 formal_ready 部署配置、
用户批准原件、正式许可与 r17 admission,四者当前都不存在。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rl_curriculum.curriculum261_qprod_coordinate import (  # noqa: E402
    qprod_coordinate_code_identity)
from rl_curriculum.curriculum261_qprod_formal import (  # noqa: E402
    QPROD_FORMAL_LEVEL_A_ITERATION_ID)
from rl_curriculum.curriculum261_qprod_formal_budget import (  # noqa: E402
    authorization_face as _budget_face,
)
from rl_curriculum.curriculum261_qprod_formal_levela import (  # noqa: E402
    QPROD_FORMAL_STOP_CHOICES,
    FormalLaunchRefused, build_formal_level_a_plan,
    launch_formal_level_a, preflight_formal_level_a)
from rl_curriculum.curriculum261_qprod_plan import (  # noqa: E402
    research_plan_digest)


def _code_identity() -> dict[str, str]:
    return qprod_coordinate_code_identity()


def cmd_draft_plan(args: argparse.Namespace) -> int:
    if args.stop_after == "verify-formal-logs" \
            and not args.model_update:
        print("[draft-plan] 完整链含 smoke(模型更新):须 "
              "--model-update 且批准同口径")
        return 2
    if args.stop_after == "qualify" and args.model_update:
        print("[draft-plan] stop-after=qualify 与 --model-update "
              "口径不一致")
        return 2
    payload = build_formal_level_a_plan(
        code_freeze_sha=args.code_freeze_sha or "",
        code_identity=_code_identity(),
        authorized_stop_after=args.stop_after,
        model_update_authorized=args.model_update)
    digest = research_plan_digest(payload)
    prep = Path(args.prep_dir)
    prep.mkdir(parents=True, exist_ok=True)
    out = {
        "format": "cur261-qprod-formal-draft-plan-v1",
        "level": "level_a",
        "iteration_id": QPROD_FORMAL_LEVEL_A_ITERATION_ID,
        "status": "DRAFT_PENDING_USER_APPROVAL",
        "code_freeze_sha_binding": (
            "草案绑定当前已验代码身份与冻结程序;最终 Commit A "
            "SHA 在 provenance-lock→Commit A 后产生,批准/签发/"
            "launch 全部绑定该真实 SHA(草案不得用伪 SHA 启动)"),
        "code_freeze_sha": args.code_freeze_sha or "",
        "research_plan_digest": digest,
        "payload": payload,
        "budget": _budget_face(stop_after=args.stop_after),
        "commands": {
            "preflight": (
                "python stage2_6_1/runner/qprod_formal_level_a_entry.py"
                f" preflight --deploy-root <DEPLOY_ROOT> --stop-after "
                f"{args.stop_after}" + (" --model-update"
                                        if args.model_update else "")),
            "launch": (
                "python stage2_6_1/runner/qprod_formal_level_a_entry.py"
                " launch --deploy-root <DEPLOY_ROOT> --project-dir "
                "<TRUSTED_PROJECT> --code-freeze-sha <COMMIT_A> "
                f"--stop-after {args.stop_after}"
                + (" --model-update" if args.model_update else "")),
        },
    }
    path = prep / "qprod_formal_level_a_draft_plan.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(json.dumps({"draft_plan": str(path),
                      "research_plan_digest": digest},
                     ensure_ascii=False))
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    report = preflight_formal_level_a(
        args.deploy_root, code_freeze_sha=args.code_freeze_sha or "",
        code_identity=_code_identity(),
        authorized_stop_after=args.stop_after)
    print(json.dumps(report, ensure_ascii=False, indent=2,
                     default=str))
    return 0 if report["status"] == "PREPARED_PENDING_USER_APPROVAL" \
        else 1


def cmd_launch(args: argparse.Namespace) -> int:
    if args.stop_after == "verify-formal-logs" \
            and not args.model_update:
        print("[launch] 完整链含 smoke(模型更新):须 --model-update")
        return 2
    if args.stop_after == "qualify" and args.model_update:
        print("[launch] stop-after=qualify 与 --model-update 口径"
              "不一致")
        return 2
    try:
        result = launch_formal_level_a(
            deploy_root=args.deploy_root, project_dir=args.project_dir,
            code_freeze_sha=args.code_freeze_sha,
            code_identity=_code_identity(),
            authorized_stop_after=args.stop_after,
            model_update_authorized=args.model_update,
            sentinel_before_chain=args.sentinel_before_chain,
            child_timeout_s=args.child_timeout)
    except FormalLaunchRefused as exc:
        print(json.dumps({
            "refused": str(exc),
            "phase": "before_first_controlled_side_effect",
            "business_leaf_calls": 0,
        }, ensure_ascii=False))
        return 96
    print(json.dumps(result, ensure_ascii=False, indent=2,
                     default=str))
    if result["sentinel_stopped"]:
        return 0
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="qprod-formal-level-a", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_draft = sub.add_parser(
        "draft-plan", help="写 run-plan 草案到准备工作目录")
    p_draft.add_argument("--prep-dir", required=True)
    p_draft.add_argument("--code-freeze-sha", default="")
    p_draft.add_argument("--stop-after", default="qualify",
                         choices=QPROD_FORMAL_STOP_CHOICES)
    p_draft.add_argument("--model-update", action="store_true")
    p_draft.set_defaults(fn=cmd_draft_plan)
    p_pre = sub.add_parser("preflight", help="只读预检")
    p_pre.add_argument("--deploy-root", required=True)
    p_pre.add_argument("--code-freeze-sha", default="")
    p_pre.add_argument("--stop-after", default="qualify",
                       choices=QPROD_FORMAL_STOP_CHOICES)
    p_pre.set_defaults(fn=cmd_preflight)
    p_launch = sub.add_parser("launch", help="正式启动(门禁→受控写→链)")
    p_launch.add_argument("--deploy-root", required=True)
    p_launch.add_argument("--project-dir", required=True,
                          help="受信任部署树根(链子进程 cwd/PYTHONPATH)")
    p_launch.add_argument("--code-freeze-sha", required=True)
    p_launch.add_argument("--stop-after", required=True,
                          choices=QPROD_FORMAL_STOP_CHOICES)
    p_launch.add_argument("--model-update", action="store_true")
    p_launch.add_argument("--sentinel-before-chain", action="store_true",
                          help="边界哨兵:链执行器调用前停止(验证用;"
                               "诚实中断,零步骤执行)")
    p_launch.add_argument("--child-timeout", type=int, default=None)
    p_launch.set_defaults(fn=cmd_launch)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
