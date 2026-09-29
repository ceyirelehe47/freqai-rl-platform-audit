#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QProd Level B 入口(坐标确认性研究:计划冻结/坐标锁/坐标运行/聚合)。

用法(部署树):
  python stage2_6_1_runner/qprod_level_b_entry.py plan-freeze \
      --base-dir <隔离目录> --authority-dir <authority目录> \
      [--stop-mode collect_all_k|early_stop_on_first_negative]
  ... lock-coordinates / run-coordinate --coordinate-id c01 / aggregate /
  cold-read

工程坐标 = QPROD 工程 namespace 名单前两对(c01/c02);缩减预算
ENGINEERING_ONLY(blocks=2/corpus,MC=4096,tier1≤2000)事前入计划。
原生生成逐调用计入 --ledger 配额账本(动作前 start/完成 complete/
拒绝 refused/中断 interrupted 都结算)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEPLOY_SRC = Path(__file__).resolve().parents[1] / "src"
if DEPLOY_SRC.is_dir():
    sys.path.insert(0, str(DEPLOY_SRC))

from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
)
from rl_curriculum.curriculum261_qprod_context import (  # noqa: E402
    QProdContextError, QProdRunSession, build_engineering_context,
)
from rl_curriculum.curriculum261_qprod_permit import (  # noqa: E402
    LivePermitToken, consume_permit, load_permit,
    permit_already_consumed, validate_permit,
)
from rl_curriculum.curriculum261_qprod_coordinate import (  # noqa: E402
    QPROD_ENG_BLOCKS_PER_CORPUS, QPROD_ENG_MC_EVENTS,
    lock_coordinate_audit_plan, qprod_coordinate_code_identity,
    run_coordinate_audit_locked,
)
from rl_curriculum.curriculum261_qprod_plan import (  # noqa: E402
    QPROD_QUALIFICATION_PLAN_FORMAT, freeze_research_plan,
    load_research_plan,
)

#: 历史固定参照锚(R25 dev_plan 只读沿用;工程 scope 标注,非正式采纳)。
P0_ENGINEERING_REFERENCE = 0.950431552876822
P0_SOURCE_LABEL = (
    "R25 dev_plan.json study.p0_fixed_reference(历史开发研究参照,"
    "工程复用;非本轮新估计,非正式采纳锚)")

ITERATION_ID = "qprod_b_eng_v1"
#: 本轮固定 2 个工程坐标(事前;清单先于任何该批数据生成冻结)。
ENGINEERING_COORDINATES = (
    {"coordinate_id": "c01",
     "model_namespace": "cue_qprod_v1_c01_model",
     "validation_namespace": "cue_qprod_v1_c01_validation",
     "blocks_per_corpus": QPROD_ENG_BLOCKS_PER_CORPUS,
     "mc_events": QPROD_ENG_MC_EVENTS,
     "max_attempts": 5,
     "artifact_subdir": "coord_c01"},
    {"coordinate_id": "c02",
     "model_namespace": "cue_qprod_v1_c02_model",
     "validation_namespace": "cue_qprod_v1_c02_validation",
     "blocks_per_corpus": QPROD_ENG_BLOCKS_PER_CORPUS,
     "mc_events": QPROD_ENG_MC_EVENTS,
     "max_attempts": 5,
     "artifact_subdir": "coord_c02"},
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _code_freeze_sha() -> str:
    ident = qprod_coordinate_code_identity()
    blob = json.dumps(ident, sort_keys=True).encode("utf-8")
    return "qprod-eng-" + hashlib.sha256(blob).hexdigest()[:16]


def _context(args: argparse.Namespace):
    return build_engineering_context(
        level="level_b", iteration_id=ITERATION_ID,
        base_dir=args.base_dir, code_freeze_sha=_code_freeze_sha(),
        authority_dir=args.authority_dir,
        namespaces_scope=CURRICULUM261_QPROD_ENGINEERING_NAMESPACES)


def _ledger_path(ctx) -> Path:
    return ctx.artifact_root.parent / "qprod_quota_ledger.jsonl"


def cmd_plan_freeze(args: argparse.Namespace) -> int:
    ctx = _context(args)
    for ns in [n for c in ENGINEERING_COORDINATES for n in (
            c["model_namespace"], c["validation_namespace"])]:
        if ns not in CURRICULUM261_QPROD_ENGINEERING_NAMESPACES:
            print(f"[plan-freeze] namespace 未注册: {ns}")
            return 2
    payload = {
        "format": "cur261-qprod-research-plan-v1",
        "level": "level_b",
        "iteration_id": ITERATION_ID,
        "profile": "engineering",
        "code_freeze_sha": ctx.code_freeze_sha,
        "coordinate_manifest": [
            dict(c) for c in ENGINEERING_COORDINATES],
        "rules": {
            "p0_fixed_reference": P0_ENGINEERING_REFERENCE,
            "p0_source_label": P0_SOURCE_LABEL,
            "delta_definition": "P0 - recall(validation)",
            "margin": 0.003,
            "alpha": 0.05,
            "r_analysis": 1.5,
            "planned_k": 11,
            "anchor_policy": "固定共同 P0(外部计划显式给定);局部"
                             " p_contract 照真实算法计算,不因数值不等"
                             "删坐标",
        },
        "quota": {
            "max_leaf_calls_total": 640,
            "max_leaf_calls_per_execution": 320,
            "max_successful_episodes_total": 128,
            "mc_events_per_coordinate": QPROD_ENG_MC_EVENTS,
            "max_native_executions": 2,
        },
        "code_identity": qprod_coordinate_code_identity(),
        "stop_mode": args.stop_mode,
        "engineering_note": "2 工程坐标烟测(< planned_k=11 ⇒ 聚合"
                            "主分类预期不决,不足 K 不缩小门槛)",
    }
    _, digest = freeze_research_plan(ctx.state_root, payload)
    print(json.dumps({"research_plan_digest": digest,
                      "state_root": str(ctx.state_root)},
                     ensure_ascii=False))
    return 0


def cmd_lock_coordinates(args: argparse.Namespace) -> int:
    ctx = _context(args)
    plan = load_research_plan(ctx.state_root)
    out = {}
    for coord in plan["coordinate_manifest"]:
        coord_dir = ctx.artifact_root / coord["artifact_subdir"]
        _, digest = lock_coordinate_audit_plan(
            coord_dir, coordinate=coord, research_plan=plan)
        out[coord["coordinate_id"]] = digest
    print(json.dumps({"coordinate_audit_plan_digests": out},
                     ensure_ascii=False))
    return 0


def cmd_consume_permit(args: argparse.Namespace) -> int:
    """一次性消费本执行集的许可(整批坐标共用一次消费;
    先于任何坐标生成;E01 缺陷修复:逐坐标重复消费会把第二批
    坐标错拒为重放)。"""
    ctx = _context(args)
    try:
        rec = consume_permit(ctx.permit_path, context=ctx)
    except QProdContextError as exc:
        already = permit_already_consumed(
            ctx, _permit_id_of(ctx))
        if already:
            print(json.dumps({
                "permit": "already-consumed(本执行集已消费;"
                          "run-coordinate 直接验证)",
                "permit_id": _permit_id_of(ctx)}, ensure_ascii=False))
            return 0
        print(f"[consume-permit] 拒绝: {exc}")
        return 96
    print(json.dumps({"consumed_permit_id": rec["permit_id"]},
                     ensure_ascii=False))
    return 0


def _permit_id_of(ctx) -> str:
    permit = load_permit(ctx.permit_path)
    return str(permit["permit_id"])


def cmd_run_coordinate(args: argparse.Namespace) -> int:
    ctx = _context(args)
    plan = load_research_plan(ctx.state_root)
    coord = next((c for c in plan["coordinate_manifest"]
                  if c["coordinate_id"] == args.coordinate_id), None)
    if coord is None:
        print(f"[run-coordinate] 坐标不在计划清单: {args.coordinate_id}")
        return 2
    coord_dir = ctx.artifact_root / coord["artifact_subdir"]
    # 许可已在 consume-permit(执行集开始)一次性消费;这里只验证
    # (字段/digest/scope)+要求本执行集消费记录在场,不再重复消费。
    try:
        permit = validate_permit(ctx.permit_path, context=ctx)
    except QProdContextError as exc:
        print(f"[run-coordinate] 许可拒绝(零叶调用): {exc}")
        return 96
    if not permit_already_consumed(ctx, str(permit["permit_id"])):
        print("[run-coordinate] 许可未消费(先 consume-permit;"
              "零叶调用)")
        return 96
    live = LivePermitToken(permit, {"consumed_via": "consume-permit"})
    out = run_coordinate_audit_locked(
        ctx, live, args.coordinate_id, coord_dir=coord_dir,
        ledger_path=_ledger_path(ctx))
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

    ctx = _context(args)
    report = aggregate_research(
        ctx.artifact_root, state_root=ctx.state_root)
    out_path = ctx.artifact_root / "qprod_aggregate_report.json"
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

    ctx = _context(args)
    stored = json.loads(
        (ctx.artifact_root / "qprod_aggregate_report.json").read_text(
            encoding="utf-8"))
    fresh = aggregate_research(ctx.artifact_root,
                               state_root=ctx.state_root)
    same = (
        stored["primary"].get("magnitude")
        == fresh["primary"].get("magnitude")
        and stored["valid_coordinate_count"]
        == fresh["valid_coordinate_count"]
        and all(
            (a.get("state"), round(float(a.get("recall_validation", 0)
                                         or 0), 12))
            == (b.get("state"),
                round(float(b.get("recall_validation", 0) or 0), 12))
            for a, b in zip(stored["coordinates"], fresh["coordinates"])))
    print(json.dumps({"cold_read_reproduces": same,
                      "coordinates": len(fresh["coordinates"])},
                     ensure_ascii=False))
    return 0 if same else 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan-freeze", "lock-coordinates", "consume-permit",
                 "run-coordinate", "aggregate", "cold-read"):
        p = sub.add_parser(name)
        p.add_argument("--base-dir", required=True)
        p.add_argument("--authority-dir", required=True)
        if name == "plan-freeze":
            p.add_argument("--stop-mode", default="collect_all_k",
                           choices=("collect_all_k",
                                    "early_stop_on_first_negative"))
        if name == "run-coordinate":
            p.add_argument("--coordinate-id", required=True)
        p.set_defaults(fn=globals()[f"cmd_{name.replace('-', '_')}"])
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
