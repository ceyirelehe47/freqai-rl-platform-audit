#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QProd 工程 test authority(隔离签发角色;被验包 src 无签发能力)。

职责:初始化 authority 身份、签发 Level A/B 工程许可、依据导出
receipt 构造消费工程授权锚。本脚本位于 runner 执行面(操作员侧),
不属于被验 src 包;许可文件只写入 authority 目录(被验包的
validate_permit 要求许可位于该目录内且目录在 qprod 根之外)。

正式许可不由此产生:正式部署的许可/状态/更新计数为 0;工程 scope
改名不能取得正式权限。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rl_curriculum.curriculum261_qprod_permit import (  # noqa: E402
    permit_digest,
)

AUTHORITY_IDENTITY_NAME = "authority_identity.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cmd_init(args: argparse.Namespace) -> int:
    adir = Path(args.dir)
    adir.mkdir(parents=True, exist_ok=True)
    ident_path = adir / AUTHORITY_IDENTITY_NAME
    if ident_path.is_file():
        print(f"[authority] 已初始化: {ident_path}")
        return 0
    authority_id = args.authority_id or (
        "qprod-eng-authority-" + hashlib.sha256(
            str(adir.resolve()).encode("utf-8")).hexdigest()[:12])
    ident_path.write_text(json.dumps({
        "format": "cur261-qprod-authority-identity-v1",
        "authority_id": authority_id,
        "kind": "engineering_test_authority",
        "note": "隔离工程 test authority;只签发 engineering scope;"
                "不产生任何正式许可;正式注册表保持为空",
        "created_utc": _now(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[authority] init {authority_id} -> {ident_path}")
    return 0


def cmd_issue_permit(args: argparse.Namespace) -> int:
    adir = Path(args.dir)
    ident = json.loads(
        (adir / AUTHORITY_IDENTITY_NAME).read_text(encoding="utf-8"))
    quota = json.loads(Path(args.quota_json).read_text(
        encoding="utf-8")) if args.quota_json else {
        "max_leaf_calls_per_coordinate": 320,
        "max_successful_episodes_total": 128,
        "mc_events_per_coordinate": 4096,
        "max_native_executions": 2,
    }
    permit = {
        "format": "cur261-qprod-permit-v1",
        "permit_id": args.permit_id or (
            "qppm-auto-" + hashlib.sha256(
                (_now() + args.task_level + args.iteration_id)
                .encode("utf-8")).hexdigest()[:16]),
        "task_level": args.task_level,
        "iteration_id": args.iteration_id,
        "code_freeze_sha": args.code_freeze_sha,
        "artifact_root": str(Path(args.artifact_root).resolve()),
        "state_root": str(Path(args.state_root).resolve()),
        "preregistered_input_scope": {
            "namespaces": args.namespaces or [],
            "coordinate_ids": args.coordinate_ids or [],
        },
        "quota": quota,
        "issuer": {
            "kind": "engineering_test_authority",
            "authority_id": ident["authority_id"],
        },
        "issued_utc": _now(),
    }
    permit["permit_digest"] = permit_digest(permit)
    out = adir / f"qprod_permit_{args.task_level}_{args.iteration_id}.json"
    if out.is_file():
        print(f"[authority] 许可已存在(签发一次性): {out}")
        return 1
    out.write_text(json.dumps(permit, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(json.dumps({"permit_path": str(out),
                      "permit_id": permit["permit_id"],
                      "permit_digest": permit["permit_digest"]},
                     ensure_ascii=False))
    return 0


def cmd_issue_consumption_auth(args: argparse.Namespace) -> int:
    adir = Path(args.dir)
    json.loads((adir / AUTHORITY_IDENTITY_NAME).read_text(
        encoding="utf-8"))
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    from rl_curriculum.ppo262_qprod_export import (
        build_engineering_authorization,
    )
    authority_note = (
        f"isolated engineering test authority({str(adir.resolve())};"
        f"ENGINEERING_ONLY,非正式 admission 链)")
    auth = build_engineering_authorization(
        receipt, profile=args.profile, authority_note=authority_note)
    delivery_name = Path(args.receipt).parent.name
    out = adir / f"qprod_consumption_auth_{delivery_name}.json"
    out.write_text(json.dumps(auth, indent=2, ensure_ascii=False,
                              sort_keys=True), encoding="utf-8")
    print(json.dumps({"authorization_path": str(out),
                      "binding_digest": auth["binding_digest"]},
                     ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--dir", required=True)
    p.add_argument("--authority-id", default=None)
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("issue-permit")
    p.add_argument("--dir", required=True)
    p.add_argument("--task-level", required=True,
                   choices=("level_a", "level_b"))
    p.add_argument("--iteration-id", required=True)
    p.add_argument("--code-freeze-sha", required=True)
    p.add_argument("--artifact-root", required=True)
    p.add_argument("--state-root", required=True)
    p.add_argument("--namespaces", nargs="*", default=[])
    p.add_argument("--coordinate-ids", nargs="*", default=[])
    p.add_argument("--quota-json", default=None)
    p.add_argument("--permit-id", default=None)
    p.set_defaults(fn=cmd_issue_permit)

    p = sub.add_parser("issue-consumption-auth")
    p.add_argument("--dir", required=True)
    p.add_argument("--receipt", required=True)
    p.add_argument("--profile", default="ppo262_qprod_engineering_v1")
    p.set_defaults(fn=cmd_issue_consumption_auth)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
