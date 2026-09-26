#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R25 cue-bias 开发研究薄入口(RouteC_CueBias_DevelopmentStudy_v1)。

一次性的开发估计研究执行端,不新增研究/审计框架:直接复用既有
生成叶函数(r6_tape once/attempts)、事件 trace(r17_noise_replay)、
原 block-cluster bootstrap 与解析 q(t)(r17_cue_contract),主分析
调用已接受的 v4 `classify_primary`(report/r20_design_calc_v4.py,
纯标准库)。

子命令:
  plan-create   生成数据前固定计划(11 对研究坐标 + 3 对 smoke);
  run-coordinate 按 plan 执行单坐标生成并落盘全部原件(封存后只读);
  cold-read     只读冷读:从封存事件原件重算 recall/SE → v4 主分析。

边界(任务合同):
  - 未运行项(MC 1e6 / global-K / tail integrity / 非劣效 audit
    判定)显式标 NOT_RUN,不填 PASS;
  - 统计负结果(audit 式 pass=false 等)不是研究失败,不中断批次;
  - 封存目录(write-once)不可重跑;计划 digest 数据后不可改;
  - namespace 走 api 显式 R25 开发名单,不接受任意字符串。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_STAGE = Path(__file__).resolve().parents[1]

P0_STUDY = 0.950431552876822          # v4 已公布解析参考(固定锚)
MARGIN_STUDY = 0.003                  # 开发报告分界(非正式容忍度)
ALPHA_STUDY = 0.05
R_ANALYSIS_STUDY = 1.5
PLANNED_K = 11
STUDY_BLOCKS = 500
SMOKE_BLOCKS = 4
PER_COORDINATE_MAX_SECONDS = 2700    # 45 min(合同)
TOTAL_BUDGET_SECONDS = 28800         # 8 h(合同)
FINALIZE_RESERVE_SECONDS = 2700

PLAN_FORMAT = "r25-cue-bias-dev-plan-v1"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())

def _locate_v4() -> Path:
    """定位 v4 主分析脚本:仓库布局(report/)或部署布局(同目录)。"""
    candidates = [
        REPO_STAGE / "report" / "r20_design_calc_v4.py",
        Path(__file__).resolve().parent / "r20_design_calc_v4.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit("r20_design_calc_v4.py 未找到(report/ 或入口"
                     "同目录)")


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _load_v4_module():
    """文件级加载已接受的 v4 主分析(纯标准库,不 import 生成器)。"""
    v4_path = _locate_v4()
    spec = importlib.util.spec_from_file_location(
        "r20_design_calc_v4_loaded", v4_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan_digest(plan: dict) -> str:
    body = {k: v for k, v in plan.items() if k != "plan_digest"}
    return "r25dp-" + _sha256_bytes(
        _canonical_json(body).encode("utf-8"))


def _load_plan(path: Path) -> dict:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("format") != PLAN_FORMAT:
        raise SystemExit(f"plan format 不符: {plan.get('format')!r}")
    if _plan_digest(plan) != plan.get("plan_digest"):
        raise SystemExit("plan digest 不一致(计划数据后不可改)")
    return plan


def _coordinate_table(plan: dict) -> dict[str, dict]:
    return {row["id"]: row for row in
            plan["coordinates"] + plan["smoke_coordinates"]}


def _project_paths():
    src = REPO_STAGE / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from rl_curriculum import curriculum261_r6_tape as tape
    from rl_curriculum import curriculum261_r17_cue_contract as contract
    from rl_curriculum import curriculum261_r17_noise_replay as replay
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R25_DEV_NAMESPACES)
    return tape, contract, replay, CURRICULUM261_R25_DEV_NAMESPACES


# ----------------------------------------------------------- plan-create
def cmd_plan_create(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refused: plan 已存在 {out}")
    tape, contract, replay, dev_names = _project_paths()
    coordinates = [{
        "id": f"c{idx:02d}",
        "model_namespace": f"cue_dev_r25_c{idx:02d}_model",
        "validation_namespace": f"cue_dev_r25_c{idx:02d}_validation",
        "blocks_per_corpus": STUDY_BLOCKS,
        "role": "study",
    } for idx in range(1, PLANNED_K + 1)]
    smoke = [{
        "id": f"s{idx}",
        "model_namespace": f"cue_dev_smoke_s{idx}_model",
        "validation_namespace": f"cue_dev_smoke_s{idx}_validation",
        "blocks_per_corpus": SMOKE_BLOCKS,
        "role": "engineering_smoke",
    } for idx in (1, 2, 3)]
    plan = {
        "format": PLAN_FORMAT,
        "created_utc": _utc(),
        "task": "RouteC_CueBias_DevelopmentStudy_v1",
        "interpreter": sys.executable,
        "argv0": str(Path(sys.argv[0]).resolve()),
        "entry_sha256": _sha256_file(Path(__file__).resolve()),
        "generation_code_identity": contract.cue_audit_code_identity_r17(),
        "study": {
            "p0_fixed_reference": p0,
        "margin": margin, "alpha": alpha,
        "r_analysis": r_analysis,
            "delta_definition": "P0 - recall(validation)",
            "planned_k": planned_k_plan,
            "margin": MARGIN_STUDY,
            "alpha": ALPHA_STUDY,
            "r_analysis": R_ANALYSIS_STUDY,
            "aggregation": "delta_k 等权平均; S_raw=sqrt(sum(s_k^2))/K; "
                            "CI90=delta_bar±z_(1-alpha)×r_analysis×S_raw "
                            "(v4 classify_primary)",
            "main_analysis_entry": "report/r20_design_calc_v4.py::"
                                   "classify_primary",
        },
        "generation": {
            "model_mode": "once",
            "validation_mode": "attempts(first_pass, max_attempts=5 "
                               "整 block 重试)",
            "block_seed": "derive261_block_seed(namespace, block_index, "
                          "AUDIT_ATTEMPT=0)",
            "canonical_observation": "D0/A unique positive cue event",
            "cluster_unit": "matched_block",
            "bootstrap": {"n_boot": int(contract.AUDIT_BOOTSTRAP_RESAMPLES),
                          "seed": int(contract.AUDIT_BOOTSTRAP_SEED)},
            "sentinel": "冻结 cur261-c2-v9 默认 D0-D3(candidate-"
                        "independent;不调参)",
            "detector": dict(contract.C2_REFERENCE_DEFAULTS),
            "episode_bars": int(contract.CURRICULUM261_EPISODE_BARS),
        },
        "not_run_diagnostic_items": [
            "monte_carlo_1e6", "global_k_audit", "tail_mirror_bound_"
            "integrity", "noninferiority_gate", "cue_contract_audit_"
            "pass_verdict"],
        "budget": {
            "per_coordinate_max_seconds": PER_COORDINATE_MAX_SECONDS,
            "total_wall_clock_seconds": TOTAL_BUDGET_SECONDS,
            "finalize_reserve_seconds": FINALIZE_RESERVE_SECONDS},
        "namespaces_authority": "curriculum261_api.CURRICULUM261_R25_"
                                "DEV_NAMESPACES",
        "namespaces_registered": list(dev_names),
        "coordinates": coordinates,
        "smoke_coordinates": smoke,
    }
    plan["plan_digest"] = _plan_digest(plan)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps({"plan": str(out), "plan_digest": plan["plan_digest"],
                      "coordinates": PLANNED_K,
                      "smoke": len(smoke)}))
    return 0


# ---------------------------------------------------------- run-coordinate
def cmd_run_coordinate(args: argparse.Namespace) -> int:
    plan = _load_plan(Path(args.plan))
    row = _coordinate_table(plan).get(args.coordinate)
    if row is None:
        raise SystemExit(f"coordinate {args.coordinate!r} 不在计划名单")
    if args.coordinate.startswith("s") and not args.allow_smoke:
        raise SystemExit("smoke 坐标需要 --allow-smoke(研究数据永不"
                         "计入;smoke 名称与 c01..c11 完全独立)")
    tape, contract, replay, dev_names = _project_paths()
    for key in ("model_namespace", "validation_namespace"):
        if row[key] not in dev_names:
            raise SystemExit(f"{key}={row[key]!r} 未在 api 开发名单")

    out_dir = Path(args.out_root) / f"coord_{row['id']}"
    if out_dir.exists():
        sealed = out_dir / "SEALED.json"
        state = "sealed" if sealed.exists() else "unsealed-interrupted"
        raise SystemExit(
            f"refused: {out_dir} 已存在({state});封存坐标只读,中断"
            "坐标不重采(合同 §6)")
    out_dir.mkdir(parents=True)

    n_blocks = int(row["blocks_per_corpus"])
    ladder = contract._sentinel_ladder()
    manifest = {
        "format": "r25-cue-bias-dev-coordinate-v1",
        "started_utc": _utc(),
        "plan_digest": plan["plan_digest"],
        "coordinate": row["id"],
        "role": row["role"],
        "model_namespace": row["model_namespace"],
        "validation_namespace": row["validation_namespace"],
        "blocks_per_corpus": n_blocks,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "not_run_diagnostic_items": plan["not_run_diagnostic_items"],
        "generation_code_identity": plan["generation_code_identity"],
        "entry_sha256": plan["entry_sha256"],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    started = time.monotonic()
    print(f"[{row['id']}] start blocks={n_blocks} "
          f"model=once validation=attempts", flush=True)

    # ---- model corpus(once)--------------------------------------------
    weights: dict[int, int] = {}
    model_rows = 0
    with open(out_dir / "model_events.jsonl", "w",
              encoding="utf-8") as ev_fh, \
         open(out_dir / "model_block_seeds.jsonl", "w",
              encoding="utf-8") as seed_fh:
        for block_index in range(n_blocks):
            block_seed = tape.derive261_block_seed(
                row["model_namespace"], block_index,
                int(contract.AUDIT_ATTEMPT))
            episodes = tape.generate_matched_block_once(
                ladder, block_seed, row["model_namespace"])
            trace = replay.cue_event_trace(
                episodes, ladder, block_seed, block_index)
            seed_fh.write(json.dumps({
                "block_index": block_index,
                "block_seed": int(block_seed),
                "n_events": trace["n_events"],
                "replay_ok": trace["replay_ok"],
                "bounds_ok": trace["bounds_ok"],
                "max_replay_abs_error": trace["max_replay_abs_error"],
            }, ensure_ascii=False) + "\n")
            for event in trace["events"]:
                ev_fh.write(json.dumps(
                    {"corpus": "model", "block_seed": int(block_seed),
                     **event}, ensure_ascii=False) + "\n")
                weights[event["cue_bar"]] = (
                    weights.get(event["cue_bar"], 0) + 1)
                model_rows += 1
            if not trace["replay_ok"] or not trace["bounds_ok"]:
                raise SystemExit(
                    f"model block {block_index} 结构校验失败:"
                    f" {trace['bound_violations'][:3]}")
            if (block_index + 1) % 50 == 0:
                print(f"[{row['id']}] model {block_index + 1}/{n_blocks}"
                      f" elapsed={time.monotonic() - started:.0f}s",
                      flush=True)

    # ---- validation corpus(attempts)-----------------------------------
    validation_events: list[dict] = []
    with open(out_dir / "validation_events.jsonl", "w",
              encoding="utf-8") as ev_fh, \
         open(out_dir / "validation_block_attempts.jsonl", "w",
              encoding="utf-8") as att_fh:
        blocks = []
        for block_index in range(n_blocks):
            block = tape.generate_matched_block_with_attempts(
                ladder, namespace=row["validation_namespace"],
                block_index=block_index)
            blocks.append(block)
            att_fh.write(json.dumps(block.attempt_log.canonical(),
                                    ensure_ascii=False) + "\n")
            block_seed = replay.matched_block_seed_of(block)
            trace = replay.cue_event_trace(
                block.episodes, ladder, block_seed, block_index)
            for event in trace["events"]:
                row_out = {"corpus": "validation",
                           "block_seed": int(block_seed), **event}
                ev_fh.write(json.dumps(row_out, ensure_ascii=False)
                            + "\n")
                validation_events.append(event)
            if not trace["replay_ok"] or not trace["bounds_ok"]:
                raise SystemExit(
                    f"validation block {block_index} 结构校验失败:"
                    f" {trace['bound_violations'][:3]}")
            if (block_index + 1) % 50 == 0:
                print(f"[{row['id']}] validation "
                      f"{block_index + 1}/{n_blocks} "
                      f"elapsed={time.monotonic() - started:.0f}s",
                      flush=True)
        attempt_hist = tape.block_attempt_statistics(blocks)
        once_bitwise = contract._once_vs_attempts_bitwise_check_r17(
            blocks, ladder, row["validation_namespace"])

    # ---- 原组件统计 + 诊断 ----------------------------------------------
    per_block = contract._per_block_event_counts(validation_events)
    boot = contract._cluster_bootstrap(per_block)
    n = int(contract.CURRICULUM261_EPISODE_BARS)
    thr = dict(contract.C2_REFERENCE_DEFAULTS)
    d0 = ladder["D0"]
    vol = float(d0["vol_bps"]) * 1e-4
    pulse = float(d0["pulse_bps"]) * 1e-4
    q_by_t = {t: contract.q_recall_at_position(
        t, n, pulse=pulse, cue_thr=float(thr["cue_thr"]),
        vol=vol)["q"] for t in weights}
    p_contract_local = contract._analytic_at_weights(weights, q_by_t)

    summary = {
        "format": "r25-cue-bias-dev-coordinate-summary-v1",
        "coordinate": row["id"],
        "model": {"n_events": model_rows,
                  "mode": "once",
                  "position_weights": {str(t): c for t, c in
                                       sorted(weights.items())},
                  "local_p_contract_diagnostic": p_contract_local},
        "validation": {"n_events": len(validation_events),
                       "n_detected": sum(1 for e in validation_events
                                         if e["detected"]),
                       "recall": boot["point"],
                       "block_cluster_bootstrap": boot,
                       "attempt_histogram": attempt_hist,
                       "first_pass_bitwise_check": once_bitwise},
        "not_run": plan["not_run_diagnostic_items"],
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")

    elapsed = time.monotonic() - started
    members = sorted(
        p.relative_to(out_dir).as_posix()
        for p in out_dir.rglob("*") if p.is_file()
        and p.name != "SEALED.json")
    sealed = {
        "format": "r25-cue-bias-dev-coordinate-sealed-v1",
        "coordinate": row["id"],
        "ended_utc": _utc(),
        "elapsed_seconds": round(elapsed, 3),
        "ok": True,
        "members": {name: _sha256_file(out_dir / name)
                    for name in members},
    }
    (out_dir / "SEALED.json").write_text(
        json.dumps(sealed, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "coordinate": row["id"], "ok": True,
        "recall_validation": boot["point"],
        "se_validation": boot["se"],
        "n_events": {"model": model_rows,
                     "validation": len(validation_events)},
        "elapsed_seconds": round(elapsed, 1),
        "local_p_contract_diagnostic": p_contract_local,
        "once_bitwise_ok": once_bitwise["bitwise_ok"]},
        ensure_ascii=False))
    return 0


# --------------------------------------------------------------- cold-read
def cmd_cold_read(args: argparse.Namespace) -> int:
    plan = _load_plan(Path(args.plan))
    study = plan["study"]
    p0 = float(study["p0_fixed_reference"])
    margin = float(study["margin"])
    alpha = float(study["alpha"])
    r_analysis = float(study["r_analysis"])
    planned_k_plan = int(study["planned_k"])
    v4 = _load_v4_module()
    tape, contract, replay, dev_names = _project_paths()  # noqa: F841
    out_root = Path(args.out_root)
    rows = []
    problems = []
    for row in plan["coordinates"]:
        coord_dir = out_root / f"coord_{row['id']}"
        sealed = coord_dir / "SEALED.json"
        if not sealed.is_file():
            problems.append(f"{row['id']}: 未封存(缺 SEALED.json)")
            continue
        seal = json.loads(sealed.read_text(encoding="utf-8"))
        if not seal.get("ok"):
            problems.append(f"{row['id']}: SEALED.ok=false")
        # 成员哈希复验(原件字节与封存时一致)
        for name, digest in seal.get("members", {}).items():
            actual = _sha256_file(coord_dir / name)
            if actual != digest:
                problems.append(
                    f"{row['id']}: {name} 封存后字节变化")
        events = []
        block_ids = set()
        with open(coord_dir / "validation_events.jsonl",
                  encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("corpus") != "validation":
                    problems.append(f"{row['id']}: validation 文件混入"
                                    " 非 validation 事件")
                    continue
                events.append(event)
                block_ids.add(int(event["block_index"]))
        expect_blocks = int(row["blocks_per_corpus"])
        if block_ids != set(range(expect_blocks)):
            problems.append(
                f"{row['id']}: block 覆盖不全/越界 "
                f"({len(block_ids)}/{expect_blocks})")
        seen = set()
        for event in events:
            key = (event["block_index"], event["cue_bar"])
            if key in seen:
                problems.append(
                    f"{row['id']}: 重复事件身份 {key}")
            seen.add(key)
        per_block = contract._per_block_event_counts(events)
        boot = contract._cluster_bootstrap(per_block)
        recall = boot["point"]
        delta_k = p0 - recall
        rows.append({
            "coordinate": row["id"],
            "namespace": row["validation_namespace"],
            "n_events": boot["n_events"],
            "n_detected": sum(1 for e in events if e["detected"]),
            "recall_validation": recall,
            "delta_k": delta_k,
            "se_k": boot["se"],
            "ci95_block_cluster": boot["ci95"],
        })
    complete = (len(rows) == PLANNED_K and not problems)
    result: dict = {
        "format": "r25-cue-bias-dev-cold-read-v1",
        "created_utc": _utc(),
        "plan_digest": plan["plan_digest"],
        "p0_fixed_reference": p0,
        "margin": margin, "alpha": alpha,
        "r_analysis": r_analysis,
        "coordinates": rows,
        "k_available": len(rows),
        "planned_k": planned_k_plan,
        "integrity_problems": problems,
    }
    if rows:
        delta_bar = sum(r["delta_k"] for r in rows) / len(rows)
        ses = [r["se_k"] for r in rows]
        result["primary"] = v4.classify_primary(
            delta_bar, ses, margin,
            r_analysis=r_analysis, alpha=alpha,
            planned_k=planned_k_plan)
        result["contrast_r1"] = v4.classify_primary(
            delta_bar, ses, margin, r_analysis=1.0,
            alpha=alpha, planned_k=planned_k_plan)
    result["complete_k"] = bool(complete)
    out = Path(args.result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False)
                   + "\n", encoding="utf-8")
    print(json.dumps({
        "result": str(out), "k_available": len(rows),
        "complete_k": complete,
        "problems": problems[:5],
        "primary": result.get("primary")}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser(
        "plan-create", help="生成数据前固定开发计划")
    p_create.add_argument("--out", required=True)
    p_create.set_defaults(func=cmd_plan_create)

    p_run = sub.add_parser("run-coordinate", help="执行单坐标并封存")
    p_run.add_argument("--plan", required=True)
    p_run.add_argument("--coordinate", required=True)
    p_run.add_argument("--out-root", required=True)
    p_run.add_argument("--allow-smoke", action="store_true")
    p_run.set_defaults(func=cmd_run_coordinate)

    p_read = sub.add_parser("cold-read", help="只读冷读 + v4 主分析")
    p_read.add_argument("--plan", required=True)
    p_read.add_argument("--out-root", required=True)
    p_read.add_argument("--result", required=True)
    p_read.set_defaults(func=cmd_cold_read)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
