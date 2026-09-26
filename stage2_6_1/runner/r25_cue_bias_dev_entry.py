#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R25 cue-bias 开发研究薄入口(RouteC_CueBias_DevelopmentStudy_v1;
本文件为 RouteC_R25_EntryProvenance_ReadbackClosure_v1 轮修复版)。

一次性的开发估计研究执行端,不新增研究/审计框架:直接复用既有
生成叶函数(r6_tape once/attempts)、事件 trace(r17_noise_replay)、
原 block-cluster bootstrap 与解析 q(t)(r17_cue_contract),主分析
调用已接受的 v4 `classify_primary`(report/r20_design_calc_v4.py,
纯标准库)。

子命令:
  plan-create        生成数据前固定计划(11 对研究坐标 + 3 对 smoke);
  execution-binding  运行前冻结预定执行绑定(入口/生成模块/启动器实测身份);
  run-coordinate     按 plan 执行单坐标生成并落盘全部原件(封存后只读);
  cold-read          只读冷读:计划→manifest→seal→语料→seed/attempt→
                     事件→统计全链核对后重算 recall/SE → v4 主分析。

源码身份三角色(本轮修复核心,不可混同):
  - creator:计划创建时的入口身份(plan.entry_sha256,声明式历史记录);
  - execution:本次实际执行生成时实测的身份(manifest.execution,
    来自实际文件与实际加载模块的路径/字节,不是 plan 字段复制);
  - reader:冷读方自己的身份(result.reader,新 reader 读旧数据时
    如实记录自身,绝不倒填为历史生成身份)。

run-coordinate 在首次生成前核对 --execution-binding 预定绑定;
不符则拒绝:留 refusal 日志、零生成边界调用、不建坐标目录、不封存。
cold-read 的行为三分类:
  1. integrity 无效 → CLI 失败(rc=1),不发 within/beyond 主分类;
  2. 有效但不足计划 K → 仅描述性结果与未完成状态;
  3. 有效完整但历史执行来源未证明(如 v1 manifest 仅 creator 声明)
     → 可输出明确标注"新 reader 对旧事件的条件数值复算"的主结果,
     同时保留来源限制;不把来源不足伪装成数据损坏,反之亦然。

边界(任务合同):
  - 未运行项(MC 1e6 / global-K / tail integrity / 非劣效 audit
    判定)显式标 NOT_RUN,不填 PASS;
  - 统计负结果(audit 式 pass=false 等)不是研究失败,不中断批次;
  - 封存目录(write-once)不可重跑;计划 digest 数据后不可改;
  - namespace 走 api 显式 R25 开发名单,不接受任意字符串;
  - engineering 标记计划永不启动 c01—c11 研究坐标。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

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
COORDINATE_FORMATS = ("r25-cue-bias-dev-coordinate-v1",
                      "r25-cue-bias-dev-coordinate-v2")
#: 坐标目录必需成员(封存清单必须恰为该集合;普通文件、安全相对路径)。
REQUIRED_MEMBERS = ("manifest.json", "model_events.jsonl",
                    "model_block_seeds.jsonl", "validation_events.jsonl",
                    "validation_block_attempts.jsonl", "summary.json")
DATA_MEMBERS = ("model_events.jsonl", "model_block_seeds.jsonl",
                "validation_events.jsonl", "validation_block_attempts.jsonl")

#: 生成边界计数器:唯一允许触发 episode 生成的叶函数调用计数。
#: 拒绝路径必须证明该计数为 0(而非仅比较函数返回 false)。
_GENERATION_BOUNDARY_CALLS = {
    "generate_matched_block_once": 0,
    "generate_matched_block_with_attempts": 0,
    "total": 0,
}


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



def _load_modules():
    """导入并返回实际加载的生成/统计模块(用于实测身份)。"""
    src = REPO_STAGE / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    from rl_curriculum import curriculum261_r6_tape as tape
    from rl_curriculum import curriculum261_r17_cue_contract as contract
    from rl_curriculum import curriculum261_r17_noise_replay as replay
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R25_DEV_NAMESPACES)
    return tape, contract, replay, CURRICULUM261_R25_DEV_NAMESPACES




def _module_identity(module) -> dict:
    """实际加载模块的路径 + 字节身份(实测,不来自任何计划字段)。"""
    path = Path(getattr(module, "__file__", "")).resolve()
    return {"path": str(path),
            "sha256": _sha256_file(path) if path.is_file() else "MISSING"}


def _measured_code_identity(contract) -> dict:
    """生成/统计模块族的实测身份(cue_audit_code_identity_r17)。"""
    return dict(contract.cue_audit_code_identity_r17())


def _gen_once(tape, ladder, block_seed, namespace):
    """生成边界:model once 叶函数(计数后转发)。"""
    _GENERATION_BOUNDARY_CALLS["generate_matched_block_once"] += 1
    _GENERATION_BOUNDARY_CALLS["total"] += 1
    return tape.generate_matched_block_once(ladder, block_seed, namespace)


def _gen_attempts(tape, ladder, *, namespace, block_index):
    """生成边界:validation attempts 叶函数(计数后转发)。"""
    _GENERATION_BOUNDARY_CALLS[
        "generate_matched_block_with_attempts"] += 1
    _GENERATION_BOUNDARY_CALLS["total"] += 1
    return tape.generate_matched_block_with_attempts(
        ladder, namespace=namespace, block_index=block_index)


# ----------------------------------------------------------- plan-create
def cmd_plan_create(args: argparse.Namespace) -> int:
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refused: plan 已存在 {out}")
    tape, contract, replay, dev_names = _load_modules()
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
        "task": ("RouteC_R25_EntryProvenance_ReadbackClosure_v1"
                 "_engineering_test" if args.engineering
                 else "RouteC_CueBias_DevelopmentStudy_v1"),
        "engineering_use": bool(args.engineering),
        "interpreter": sys.executable,
        "argv0": str(Path(sys.argv[0]).resolve()),
        "entry_sha256": _sha256_file(Path(__file__).resolve()),
        "generation_code_identity": _measured_code_identity(contract),
        "study": {
            "p0_fixed_reference": P0_STUDY,
            "delta_definition": "P0 - recall(validation)",
            "planned_k": PLANNED_K,
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
    # 写后即以真实加载路径复验(内容摘要校验,防 IO 损坏)
    reloaded = _load_plan(out)
    if reloaded["plan_digest"] != plan["plan_digest"]:
        raise SystemExit("refused: plan 写后复验 digest 不一致")
    print(json.dumps({"plan": str(out), "plan_digest": plan["plan_digest"],
                      "coordinates": PLANNED_K,
                      "smoke": len(smoke),
                      "engineering_use": bool(args.engineering)}))
    return 0


# ----------------------------------------------------- execution-binding
BINDING_FORMAT = "r25-execution-binding-v1"
BINDING_SCOPE_NOTE = (
    "有界名单:入口文件 + 7 个生成/trace/统计模块"
    "(cue_audit_code_identity_r17)+ 启动器(提供时)。分析入口由"
    " cold-read 在读取时实测。该名单不声称已证明全传递闭包;真实"
    "导入路径见 loaded_modules/entry.path。")


def cmd_execution_binding(args: argparse.Namespace) -> int:
    """运行前冻结预定执行绑定:对本机实际文件实测,写成 write-once。"""
    out = Path(args.out)
    if out.exists():
        raise SystemExit(f"refused: binding 已存在 {out}")
    tape, contract, replay, dev_names = _load_modules()
    binding: dict = {
        "format": BINDING_FORMAT,
        "created_utc": _utc(),
        "entry": {"path": str(Path(__file__).resolve()),
                  "sha256": _sha256_file(Path(__file__).resolve())},
        "code_identity": _measured_code_identity(contract),
        "loaded_modules": {
            "curriculum261_r6_tape.py": _module_identity(tape),
            "curriculum261_r17_cue_contract.py": _module_identity(contract),
            "curriculum261_r17_noise_replay.py": _module_identity(replay),
        },
        "launcher": None,
        "scope_note": BINDING_SCOPE_NOTE,
    }
    if args.launcher:
        launcher_path = Path(args.launcher).resolve()
        binding["launcher"] = {"path": str(launcher_path),
                               "sha256": _sha256_file(launcher_path)}
    if args.plan:
        plan = _load_plan(Path(args.plan))
        binding["plan_digest"] = plan["plan_digest"]
    binding["binding_sha256"] = _sha256_bytes(
        _canonical_json(
            {k: v for k, v in binding.items()
             if k != "binding_sha256"}).encode("utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(binding, indent=1, ensure_ascii=False)
                   + "\n", encoding="utf-8")
    print(json.dumps({"binding": str(out),
                      "entry_sha256": binding["entry"]["sha256"],
                      "launcher": binding["launcher"]}))
    return 0


def _verify_execution_binding(binding_path: Path, measured: dict) -> \
        tuple[bool, list[str], dict]:
    """实测身份 vs 预定绑定;返回(ok, 差异清单, binding 原文)。"""
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if binding.get("format") != BINDING_FORMAT:
        problems.append(f"binding format 不符: {binding.get('format')!r}")
        return False, problems, binding
    body = {k: v for k, v in binding.items()
            if k != "binding_sha256"}
    recomputed = _sha256_bytes(_canonical_json(body).encode("utf-8"))
    if recomputed != binding.get("binding_sha256"):
        problems.append("binding_sha256 不一致(绑定文件被改动)")
    if binding["entry"]["sha256"] != measured["entry_sha256"]:
        problems.append(
            "入口身份不符: binding="
            f"{binding['entry']['sha256'][:12]}… 实测="
            f"{measured['entry_sha256'][:12]}…")
    for name, digest in binding.get("code_identity", {}).items():
        actual = measured["code_identity"].get(name, "MISSING")
        if actual != digest:
            problems.append(f"生成模块身份不符: {name} binding="
                            f"{str(digest)[:12]}… 实测={str(actual)[:12]}…")
    extra = set(measured["code_identity"]) - set(
        binding.get("code_identity", {}))
    if extra:
        problems.append(f"实测存在绑定未覆盖的模块: {sorted(extra)}")
    launcher = binding.get("launcher")
    if launcher:
        lp = Path(launcher["path"])
        if not lp.is_file():
            problems.append(f"启动器文件缺失: {lp}")
        elif _sha256_file(lp) != launcher["sha256"]:
            problems.append(
                f"启动器身份不符: {lp}(binding="
                f"{str(launcher['sha256'])[:12]}…)")
    return (not problems), problems, binding


# ---------------------------------------------------------- run-coordinate
def cmd_run_coordinate(args: argparse.Namespace) -> int:
    plan = _load_plan(Path(args.plan))
    row = _coordinate_table(plan).get(args.coordinate)
    if row is None:
        raise SystemExit(f"coordinate {args.coordinate!r} 不在计划名单")
    if args.coordinate.startswith("s") and not args.allow_smoke:
        raise SystemExit("smoke 坐标需要 --allow-smoke(研究数据永不"
                         "计入;smoke 名称与 c01..c11 完全独立)")
    if plan.get("engineering_use") and row["role"] != "engineering_smoke":
        raise SystemExit(
            f"engineering 标记计划不允许启动研究坐标 "
            f"{row['id']!r}(仅 smoke)")
    tape, contract, replay, dev_names = _load_modules()
    for key in ("model_namespace", "validation_namespace"):
        if row[key] not in dev_names:
            raise SystemExit(f"{key}={row[key]!r} 未在 api 开发名单")

    out_root = Path(args.out_root)
    # ---- 首次生成前核对预定执行绑定(实测,非 plan 字段复制) ----
    binding_record = None
    if args.execution_binding:
        measured = {
            "entry_sha256": _sha256_file(Path(__file__).resolve()),
            "code_identity": _measured_code_identity(contract),
        }
        ok, mismatches, binding = _verify_execution_binding(
            Path(args.execution_binding), measured)
        binding_record = {
            "file": str(Path(args.execution_binding).resolve()),
            "sha256": _sha256_file(Path(args.execution_binding)),
            "verified_ok": ok,
        }
        if not ok:
            refusal = {
                "format": "r25-execution-refusal-v1",
                "refused_utc": _utc(),
                "coordinate": row["id"],
                "plan_digest": plan["plan_digest"],
                "reasons": mismatches,
                "measured": measured,
                "generation_boundary_calls": dict(
                    _GENERATION_BOUNDARY_CALLS),
                "note": "在首次生成前拒绝;未创建坐标目录、未生成 "
                        "episode、未推进坐标、未写成功封存。",
            }
            refusal_dir = out_root / "refusals"
            refusal_dir.mkdir(parents=True, exist_ok=True)
            refusal_path = (refusal_dir /
                            f"coord_{row['id']}_"
                            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')[:-3]}.json")
            refusal_path.write_text(
                json.dumps(refusal, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8")
            print(json.dumps(refusal, ensure_ascii=False))
            print(f"REFUSED coord {row['id']}: 执行绑定不符,零生成拒绝",
                  file=sys.stderr)
            return 3

    out_dir = out_root / f"coord_{row['id']}"
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
        "format": "r25-cue-bias-dev-coordinate-v2",
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
        "creator": {
            "entry_sha256": plan["entry_sha256"],
            "generation_code_identity":
                plan["generation_code_identity"],
            "source": "plan 声明(计划创建时身份;历史角色,非本次"
                      "执行实测)",
        },
        "execution": {
            "entry_path": str(Path(__file__).resolve()),
            "entry_sha256": _sha256_file(Path(__file__).resolve()),
            "interpreter": sys.executable,
            "argv": list(sys.argv),
            "code_identity_measured": _measured_code_identity(contract),
            "loaded_modules": {
                "curriculum261_r6_tape.py": _module_identity(tape),
                "curriculum261_r17_cue_contract.py":
                    _module_identity(contract),
                "curriculum261_r17_noise_replay.py":
                    _module_identity(replay),
            },
            "execution_binding": binding_record,
            "generation_boundary_calls_at_manifest": dict(
                _GENERATION_BOUNDARY_CALLS),
        },
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
            episodes = _gen_once(tape, ladder, block_seed,
                                 row["model_namespace"])
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
            block = _gen_attempts(tape, ladder,
                                  namespace=row["validation_namespace"],
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
        "once_bitwise_ok": once_bitwise["bitwise_ok"],
        "execution_entry_sha256":
            manifest["execution"]["entry_sha256"],
        "creator_entry_sha256":
            manifest["creator"]["entry_sha256"],
        "generation_boundary_calls": dict(
            _GENERATION_BOUNDARY_CALLS),
        }, ensure_ascii=False))
    return 0


# --------------------------------------------------------------- cold-read
def _safe_member_path(name: str) -> bool:
    p = PurePosixPath(name)
    return (not p.is_absolute() and ".." not in p.parts
            and str(p) == name)


def _plan_structure_problems(plan: dict) -> list[str]:
    """计划级结构核对(坐标集合/唯一性/smoke 隔离)。"""
    problems: list[str] = []
    coords = plan.get("coordinates", [])
    smoke = plan.get("smoke_coordinates", [])
    planned_k = int(plan["study"]["planned_k"])
    ids = [r.get("id") for r in coords]
    if len(ids) != len(set(ids)):
        problems.append(f"计划坐标 id 重复: {ids}")
    if len(coords) != planned_k:
        problems.append(
            f"计划坐标数 {len(coords)} != planned_k {planned_k}")
    smoke_ids = [r.get("id") for r in smoke]
    if len(smoke_ids) != len(set(smoke_ids)):
        problems.append(f"smoke id 重复: {smoke_ids}")
    if set(ids) & set(smoke_ids):
        problems.append(
            f"研究/smoke 坐标 id 交集非空: {set(ids) & set(smoke_ids)}")
    ns_pairs = [(r.get("model_namespace"), r.get("validation_namespace"))
                for r in coords + smoke]
    flat = [ns for pair in ns_pairs for ns in pair]
    if len(flat) != len(set(flat)):
        dup = sorted({ns for ns in flat if flat.count(ns) > 1})
        problems.append(f"计划 namespace 重复: {dup}")
    study_namespaces = {ns for r in coords for ns in
                        (r.get("model_namespace"),
                         r.get("validation_namespace"))}
    smoke_namespaces = {ns for r in smoke for ns in
                        (r.get("model_namespace"),
                         r.get("validation_namespace"))}
    if study_namespaces & smoke_namespaces:
        problems.append("研究/smoke namespace 交集非空: "
                        f"{sorted(study_namespaces & smoke_namespaces)}")
    for r in coords:
        if r.get("role") != "study":
            problems.append(f"研究坐标 {r.get('id')} role 非 study: "
                            f"{r.get('role')!r}")
    return problems


def _check_events_file(path: Path, *, corpus: str, n_blocks: int,
                       cue_thr: float, episode_bars: int,
                       problems: list[str], tag: str) -> list[dict]:
    """单语料事件文件核对:类型/有限值/唯一身份/检出关系/块范围。"""
    events: list[dict] = []
    seen: set = set()
    per_block_n: dict[int, int] = {}
    seeds_by_block: dict[int, set] = {}
    if not path.is_file():
        problems.append(f"{tag}: 数据文件缺失 {path.name}")
        return []
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                problems.append(f"{tag}: 行 {lineno} JSON 解析失败:"
                                f" {exc}")
                continue
            if event.get("corpus") != corpus:
                problems.append(f"{tag}: 行 {lineno} corpus="
                                f"{event.get('corpus')!r} 与文件角色"
                                f" {corpus!r} 不符")
                continue
            bi = event.get("block_index")
            cue = event.get("cue_bar")
            if not isinstance(bi, int) or isinstance(bi, bool) \
                    or not 0 <= bi < n_blocks:
                problems.append(f"{tag}: 行 {lineno} block_index 非法:"
                                f" {bi!r}")
                continue
            if not isinstance(cue, int) or isinstance(cue, bool) \
                    or not 0 <= cue < episode_bars:
                problems.append(f"{tag}: 行 {lineno} cue_bar 非法:"
                                f" {cue!r}")
                continue
            key = (bi, cue)
            if key in seen:
                problems.append(f"{tag}: 重复事件身份 {key}")
            seen.add(key)
            bad_numeric = False
            cue_read = event.get("cue_read")
            cue_read_ok = isinstance(cue_read, (int, float)) \
                and not isinstance(cue_read, bool) \
                and math.isfinite(float(cue_read))
            for field in ("cue_read", "actual_noise",
                          "effective_sigma_bps"):
                v = event.get(field)
                if not isinstance(v, (int, float)) \
                        or isinstance(v, bool) \
                        or not math.isfinite(float(v)):
                    problems.append(f"{tag}: 行 {lineno} {field} 非有限"
                                    f"数值: {v!r}")
                    bad_numeric = True
            detected = event.get("detected")
            if not isinstance(detected, bool):
                problems.append(f"{tag}: 行 {lineno} detected 非布尔:"
                                f"{detected!r}")
                bad_numeric = True
            elif cue_read_ok and \
                    detected != (float(cue_read) > cue_thr):
                problems.append(
                    f"{tag}: 行 {lineno} detected={detected} 与 "
                    f"cue_read={cue_read}>{cue_thr} 关系不符")
                bad_numeric = True
            mirrors = event.get("mirror_positions")
            k_actual = event.get("k_actual")
            if not isinstance(mirrors, list) or \
                    not all(isinstance(m, int) and not isinstance(m, bool)
                            for m in mirrors) or \
                    k_actual != len(mirrors):
                problems.append(f"{tag}: 行 {lineno} mirror/k_actual "
                                f"关系不符: k={k_actual!r} "
                                f"mirrors={mirrors!r}")
            if event.get("primary_present") not in (0, 1):
                problems.append(f"{tag}: 行 {lineno} primary_present "
                                f"非法: {event.get('primary_present')!r}")
            seed = event.get("block_seed")
            if not isinstance(seed, int) or isinstance(seed, bool):
                problems.append(f"{tag}: 行 {lineno} block_seed 非整数:"
                                f" {seed!r}")
                continue
            seeds_by_block.setdefault(bi, set()).add(seed)
            per_block_n[bi] = per_block_n.get(bi, 0) + 1
            if not bad_numeric:
                events.append(event)
    if per_block_n and set(per_block_n) != set(range(n_blocks)):
        missing = sorted(set(range(n_blocks)) - set(per_block_n))
        problems.append(f"{tag}: block 覆盖不全/越界 "
                        f"({len(per_block_n)}/{n_blocks};缺 {missing[:8]})")
    multi = {bi: s for bi, s in seeds_by_block.items() if len(s) > 1}
    if multi:
        problems.append(f"{tag}: 单 block 内出现多个 block_seed: "
                        f"{ {k: sorted(v) for k, v in multi.items()} }")
    return events


def _verify_coordinate(coord_dir: Path, row: dict, plan: dict, *,
                       tape, contract, replay, dev_names,
                       cue_thr: float) -> tuple[dict | None, list[str]]:
    """单坐标全链核对:seal→manifest→双语料日程→事件→summary 对拍。

    返回 (坐标行或 None, 问题清单)。统计一律由事件累计;summary 只做
    交叉对拍,不作为统计来源。所有期望值来自实际文件与计划交叉核对,
    不从计划复制标签冒充验证结果。
    """
    cid = row["id"]
    problems: list[str] = []
    tag0 = f"{cid}"
    n_blocks = int(row["blocks_per_corpus"])
    episode_bars = int(plan["generation"]["episode_bars"])

    sealed = coord_dir / "SEALED.json"
    if not sealed.is_file():
        return None, [f"{tag0}: 未封存(缺 SEALED.json)"]
    if sealed.is_symlink():
        return None, [f"{tag0}: SEALED.json 是符号链接(拒绝)"]
    try:
        seal = json.loads(sealed.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{tag0}: SEALED.json 解析失败: {exc}"]
    if not seal.get("ok"):
        problems.append(f"{tag0}: SEALED.ok=false")
    if seal.get("coordinate") not in (None, cid):
        problems.append(f"{tag0}: SEALED.coordinate={seal.get('coordinate')!r}"
                        " 与目录/计划坐标不符")
    members = seal.get("members", {})
    if set(members) != set(REQUIRED_MEMBERS):
        problems.append(f"{tag0}: 封存成员集合不符(缺 "
                        f"{sorted(set(REQUIRED_MEMBERS) - set(members))};"
                        f" 多 {sorted(set(members) - set(REQUIRED_MEMBERS))})")
    for name in members:
        if not _safe_member_path(name):
            problems.append(f"{tag0}: 非安全成员路径 {name!r}(拒绝)")
            continue
        member_path = coord_dir / name
        if member_path.is_symlink() or not member_path.is_file():
            problems.append(f"{tag0}: 成员 {name} 非普通文件(拒绝)")
            continue
        if _sha256_file(member_path) != members[name]:
            problems.append(f"{tag0}: {name} 封存后字节变化")
    # 成员层问题不短路:继续完整诊断(坐标最终仍因 problems 被拒)


    # ---- manifest:实际文件 vs 计划行交叉核对 ----
    try:
        manifest = json.loads((coord_dir / "manifest.json").read_text(
            encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{tag0}: manifest 解析失败: {exc}"]
    if manifest.get("format") not in COORDINATE_FORMATS:
        problems.append(f"{tag0}: manifest format 不符: "
                        f"{manifest.get('format')!r}")
        return None, problems
    if manifest.get("coordinate") != cid:
        problems.append(f"{tag0}: manifest.coordinate="
                        f"{manifest.get('coordinate')!r} 与计划坐标不符"
                        "(目录名不代表坐标身份)")
    for key in ("model_namespace", "validation_namespace"):
        declared = manifest.get(key)
        if declared != row[key]:
            problems.append(
                f"{tag0}: manifest.{key}={declared!r} 与计划行 "
                f"{row[key]!r} 不符(实际文件身份优先,拒绝)")
        elif declared not in dev_names:
            problems.append(f"{tag0}: manifest.{key}={declared!r} 未在 "
                            "api 开发名单")
    if manifest.get("plan_digest") != plan["plan_digest"]:
        problems.append(f"{tag0}: manifest.plan_digest 与计划不符")
    if manifest.get("blocks_per_corpus") != n_blocks:
        problems.append(f"{tag0}: manifest.blocks_per_corpus="
                        f"{manifest.get('blocks_per_corpus')!r} 与计划 "
                        f"{n_blocks} 不符")
    if manifest.get("role") != row.get("role"):
        problems.append(f"{tag0}: manifest.role={manifest.get('role')!r}"
                        f" 与计划 {row.get('role')!r} 不符")
    provenance = "creator_declared_only"
    if manifest.get("format").endswith("v2"):
        execution = manifest.get("execution") or {}
        if execution.get("entry_sha256") and \
                execution.get("code_identity_measured"):
            provenance = "execution_declared"
        else:
            problems.append(f"{tag0}: v2 manifest 缺 execution 实测身份")
    # manifest 关联问题不短路;后续日程/事件核对以 manifest 实际
    # 声明的 namespace 为准(实际文件身份优先),计划关联问题已记录
    mn_ns = manifest.get("model_namespace")
    mv_ns = manifest.get("validation_namespace")
    if not isinstance(mn_ns, str) or not mn_ns:
        return None, problems
    if not isinstance(mv_ns, str) or not mv_ns:
        return None, problems

    # ---- model 语料:seed 日程 + 事件 ----
    seed_rows: dict[int, dict] = {}
    if (coord_dir / "model_block_seeds.jsonl").is_file():
        with open(coord_dir / "model_block_seeds.jsonl",
                  encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    problems.append(f"{tag0}: model seed 行 {lineno} 解"
                                    f"析失败: {exc}")
                    continue
                bi = rec.get("block_index")
                if bi in seed_rows:
                    problems.append(f"{tag0}: model seed 日程重复 block "
                                    f"{bi}")
                seed_rows[bi] = rec
    else:
        problems.append(f"{tag0}: 数据文件缺失 "
                        "model_block_seeds.jsonl")
    if set(seed_rows) != set(range(n_blocks)):
        problems.append(f"{tag0}: model seed 日程覆盖不符 "
                        f"({len(seed_rows)}/{n_blocks})")
    for bi, rec in sorted(seed_rows.items()):
        if not rec.get("replay_ok") or not rec.get("bounds_ok"):
            problems.append(f"{tag0}: model block {bi} 重放/边界校验"
                            "标记非 true")
        expected = tape.derive261_block_seed(
            mn_ns, bi, int(contract.AUDIT_ATTEMPT))
        if rec.get("block_seed") != expected:
            problems.append(
                f"{tag0}: model block {bi} seed 日程不符:文件="
                f"{rec.get('block_seed')!r} 派生公式={expected}")
    model_events = _check_events_file(
        coord_dir / "model_events.jsonl", corpus="model",
        n_blocks=n_blocks, cue_thr=cue_thr, episode_bars=episode_bars,
        problems=problems, tag=f"{tag0}/model")
    model_n_by_block: dict[int, int] = {}
    for event in model_events:
        model_n_by_block[event["block_index"]] = \
            model_n_by_block.get(event["block_index"], 0) + 1
    for bi, rec in sorted(seed_rows.items()):
        if rec.get("n_events") != model_n_by_block.get(bi, 0):
            problems.append(
                f"{tag0}: model block {bi} n_events 日程="
                f"{rec.get('n_events')!r} 事件累计="
                f"{model_n_by_block.get(bi, 0)}")
    model_seed_by_block = {bi: {e["block_seed"] for e in model_events
                                if e["block_index"] == bi}
                           for bi in range(n_blocks)}
    for bi in range(n_blocks):
        expected = tape.derive261_block_seed(
            mn_ns, bi, int(contract.AUDIT_ATTEMPT))
        if model_seed_by_block.get(bi) not in ({expected},):
            problems.append(
                f"{tag0}: model block {bi} 事件 seed 与派生公式不符: "
                f"{model_seed_by_block.get(bi)!r} vs {expected}")

    # ---- validation 语料:attempt 日程 + 事件 ----
    att_rows: dict[int, dict] = {}
    if (coord_dir / "validation_block_attempts.jsonl").is_file():
        with open(coord_dir / "validation_block_attempts.jsonl",
                  encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    problems.append(f"{tag0}: attempt 行 {lineno} 解析"
                                    f"失败: {exc}")
                    continue
                bi = rec.get("block_index")
                if bi in att_rows:
                    problems.append(f"{tag0}: attempt 日程重复 block "
                                    f"{bi}")
                att_rows[bi] = rec
    else:
        problems.append(f"{tag0}: 数据文件缺失 "
                        "validation_block_attempts.jsonl")
    if set(att_rows) != set(range(n_blocks)):
        problems.append(f"{tag0}: attempt 日程覆盖不符 "
                        f"({len(att_rows)}/{n_blocks})")
    selected_by_block: dict[int, int] = {}
    for bi, rec in sorted(att_rows.items()):
        if rec.get("format") != "cur261-r6-block-attempt-log-v1":
            problems.append(f"{tag0}: block {bi} attempt log format 不符:"
                            f" {rec.get('format')!r}")
        if rec.get("seed_namespace") != mv_ns:
            problems.append(
                f"{tag0}: block {bi} attempt seed_namespace="
                f"{rec.get('seed_namespace')!r} 与 manifest "
                f"{mv_ns!r} 不符")
        max_att = rec.get("max_attempts")
        selected = rec.get("selected_attempt")
        attempts = rec.get("attempts")
        if max_att != int(tape.C2_BLOCK_MAX_ATTEMPTS):
            problems.append(f"{tag0}: block {bi} max_attempts="
                            f"{max_att!r} 非合同值 "
                            f"{tape.C2_BLOCK_MAX_ATTEMPTS}")
        if not isinstance(selected, int) or isinstance(selected, bool) \
                or not 0 <= selected < max_att:
            problems.append(f"{tag0}: block {bi} selected_attempt 非法:"
                            f" {selected!r}")
            continue
        selected_by_block[bi] = selected
        if not isinstance(attempts, list) or \
                len(attempts) != selected + 1 or \
                not attempts or not attempts[-1].get("accepted") or \
                any(a.get("accepted") for a in attempts[:-1]):
            problems.append(
                f"{tag0}: block {bi} attempt 语义不符(first-pass/最多 "
                f"{max_att} 次:期望前 {selected} 次拒绝后第 "
                f"{selected + 1} 次接受,实际 attempts={attempts!r})")
    validation_events = _check_events_file(
        coord_dir / "validation_events.jsonl", corpus="validation",
        n_blocks=n_blocks, cue_thr=cue_thr, episode_bars=episode_bars,
        problems=problems, tag=f"{tag0}/validation")
    for bi in range(n_blocks):
        if bi not in selected_by_block:
            continue
        expected = tape.derive261_block_seed(
            mv_ns, bi, selected_by_block[bi])
        actual = {e["block_seed"] for e in validation_events
                  if e["block_index"] == bi}
        if actual not in ({expected},):
            problems.append(
                f"{tag0}: validation block {bi} 事件 seed 与 "
                "(namespace, block, selected_attempt) 派生公式不符: "
                f"{actual!r} vs {expected}")

    if problems:
        return None, problems

    # ---- 统计:由事件累计;summary 仅交叉对拍 ----
    per_block = contract._per_block_event_counts(validation_events)
    boot = contract._cluster_bootstrap(per_block)
    try:
        summary = json.loads((coord_dir / "summary.json").read_text(
            encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, [f"{tag0}: summary 解析失败: {exc}"]
    if summary.get("coordinate") != cid:
        problems.append(f"{tag0}: summary.coordinate="
                        f"{summary.get('coordinate')!r} 不符")
    sv = summary.get("validation", {})
    if sv.get("n_events") != len(validation_events):
        problems.append(f"{tag0}: summary n_events={sv.get('n_events')!r}"
                        f" 与事件累计 {len(validation_events)} 不符")
    n_detected = sum(1 for e in validation_events if e["detected"])
    if sv.get("n_detected") != n_detected:
        problems.append(f"{tag0}: summary n_detected="
                        f"{sv.get('n_detected')!r} 与事件累计 "
                        f"{n_detected} 不符")
    if sv.get("recall") != boot["point"]:
        problems.append(f"{tag0}: summary recall={sv.get('recall')!r} "
                        f"与重算 {boot['point']} 不符")
    sm = summary.get("model", {})
    if sm.get("n_events") != len(model_events):
        problems.append(f"{tag0}: summary model n_events="
                        f"{sm.get('n_events')!r} 与事件累计 "
                        f"{len(model_events)} 不符")
    if problems:
        return None, problems

    recall = boot["point"]
    return {
        "coordinate": cid,
        "namespace": manifest["validation_namespace"],
        "role": row["role"],
        "n_events": {"model": len(model_events),
                     "validation": len(validation_events)},
        "n_detected": n_detected,
        "recall_validation": recall,
        "delta_k": None,  # 由调用方按 P0 计算
        "se_k": boot["se"],
        "ci95_block_cluster": boot["ci95"],
        "provenance": provenance,
    }, problems


def cmd_cold_read(args: argparse.Namespace) -> int:
    plan = _load_plan(Path(args.plan))
    study = plan["study"]
    p0 = float(study["p0_fixed_reference"])
    margin = float(study["margin"])
    alpha = float(study["alpha"])
    r_analysis = float(study["r_analysis"])
    planned_k_plan = int(study["planned_k"])
    v4 = _load_v4_module()
    v4_path = _locate_v4()
    tape, contract, replay, dev_names = _load_modules()
    reader_identity = {
        "read_utc": _utc(),
        "entry_path": str(Path(__file__).resolve()),
        "entry_sha256": _sha256_file(Path(__file__).resolve()),
        "interpreter": sys.executable,
        "analysis_entry": {"path": str(v4_path),
                           "sha256": _sha256_file(v4_path)},
        "loaded_modules": {
            "curriculum261_r6_tape.py": _module_identity(tape),
            "curriculum261_r17_cue_contract.py": _module_identity(contract),
            "curriculum261_r17_noise_replay.py": _module_identity(replay),
        },
        "note": "reader 自身身份(实测);不是历史生成身份,不倒填",
    }
    cue_thr = float(plan["generation"]["detector"]["cue_thr"])
    out_root = Path(args.out_root)
    problems = list(_plan_structure_problems(plan))
    rows = []
    member_digests: dict[str, list[str]] = {m: [] for m in DATA_MEMBERS}
    for row in plan["coordinates"]:
        coord_dir = out_root / f"coord_{row['id']}"
        if not coord_dir.is_dir():
            # 坐标目录整体缺失 = 覆盖不足(行为 2:valid_insufficient_k),
            # 不是数据损坏;存在但不完整才构成 integrity 问题
            continue
        verified, coord_problems = _verify_coordinate(
            coord_dir, row, plan, tape=tape, contract=contract,
            replay=replay, dev_names=dev_names, cue_thr=cue_thr)
        problems.extend(coord_problems)
        if verified is not None:
            verified["delta_k"] = p0 - verified["recall_validation"]
            rows.append(verified)
        for member in DATA_MEMBERS:
            member_path = coord_dir / member
            if member_path.is_file():
                member_digests[member].append(
                    f"{row['id']}:{_sha256_file(member_path)}")
    # 跨坐标语料重复(字节级;不以统计值碰巧相同作为判断)
    seen_digest: dict[str, str] = {}
    for member, entries in member_digests.items():
        digests = [e.split(":", 1)[1] for e in entries]
        if len(digests) != len(set(digests)):
            dup = sorted({d for d in digests
                          if digests.count(d) > 1})
            dup_entries = [e for e in entries
                           if e.split(":", 1)[1] in dup]
            problems.append(
                f"跨坐标语料字节重复({member}): {dup_entries}")
        for e in entries:
            cid, digest = e.split(":", 1)
            if digest in seen_digest and seen_digest[digest] != cid:
                problems.append(
                    f"语料跨坐标复用: {member} {seen_digest[digest]} "
                    f"与 {cid} 字节相同")
            seen_digest[digest] = cid

    provenance_level = (
        "execution_declared" if rows and
        all(r["provenance"] == "execution_declared" for r in rows)
        else "creator_declared_only")

    complete = (len(rows) == planned_k_plan and not problems)
    result: dict = {
        "format": "r25-cue-bias-dev-cold-read-v2",
        "created_utc": _utc(),
        "plan_digest": plan["plan_digest"],
        "reader": reader_identity,
        "plan_declared_creator": {
            "entry_sha256": plan.get("entry_sha256"),
            "generation_code_identity":
                plan.get("generation_code_identity")},
        "p0_fixed_reference": p0,
        "margin": margin, "alpha": alpha,
        "r_analysis": r_analysis,
        "coordinates": rows,
        "k_available": len(rows),
        "planned_k": planned_k_plan,
        "integrity_problems": problems,
        "complete_k": bool(complete),
    }
    if rows:
        delta_bar = sum(r["delta_k"] for r in rows) / len(rows)
        ses = [r["se_k"] for r in rows]
        if problems:
            # 行为 1:完整性无效 → 不发任何主分类
            result["integrity"] = "invalid"
            result["behavior"] = ("integrity_invalid:CLI 失败;不输出"
                                  " within/beyond 主分类,不声称完整 K;"
                                  "旧已存分类作为历史保留,不在此重算")
        elif len(rows) < planned_k_plan:
            # 行为 2:有效但不足 K → 仅描述性结果
            result["integrity"] = "valid_insufficient_k"
            result["descriptive"] = {
                "delta_bar_available": delta_bar,
                "s_raw_available": (sum(s * s for s in ses) ** 0.5)
                / len(ses),
                "note": "不足计划 K,只有描述性结果;不采用完整 K "
                        "推断,不输出主分类",
            }
        else:
            # 行为 3 分支:数值有效;来源证明程度决定标注
            primary = v4.classify_primary(
                delta_bar, ses, margin,
                r_analysis=r_analysis, alpha=alpha,
                planned_k=planned_k_plan)
            contrast = v4.classify_primary(
                delta_bar, ses, margin, r_analysis=1.0,
                alpha=alpha, planned_k=planned_k_plan)
            result["integrity"] = "valid"
            if provenance_level == "creator_declared_only":
                result["historical_execution_provenance"] = {
                    "status": "not_established",
                    "manifest_provenance": "creator_declared_only",
                    "note": "manifest 只有计划创建时的声明身份"
                            "(entry_sha256=creator);未证明历史执行"
                            "时实际加载的源码与该声明一致。数值复算"
                            "基于已存事件,不受此影响。",
                }
                primary = dict(primary)
                primary["interpretation"] = (
                    "conditional_numeric_recompute_by_new_reader:"
                    " 新 reader 对旧事件的条件数值复算;历史执行来源"
                    "未完全证明,不构成对历史生成过程的验证")
                contrast = dict(contrast)
                contrast["interpretation"] = (
                    "conditional_numeric_recompute_by_new_reader")
            result["primary"] = primary
            result["contrast_r1"] = contrast
    else:
        result["integrity"] = "invalid" if problems else "empty"
        if problems:
            result["behavior"] = ("integrity_invalid:CLI 失败;不输出"
                                  "主分类")
    out = Path(args.result)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False)
                   + "\n", encoding="utf-8")
    print(json.dumps({
        "result": str(out), "k_available": len(rows),
        "complete_k": complete,
        "integrity": result.get("integrity"),
        "problems": problems[:5],
        "primary": result.get("primary")},
        ensure_ascii=False))
    if problems:
        print("COLD_READ_FAILED: integrity 无效,不发主分类",
              file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser(
        "plan-create", help="生成数据前固定开发计划")
    p_create.add_argument("--out", required=True)
    p_create.add_argument("--engineering", action="store_true",
                          help="工程用途标记:该计划永不启动研究坐标")
    p_create.set_defaults(func=cmd_plan_create)

    p_bind = sub.add_parser(
        "execution-binding", help="运行前冻结预定执行绑定(实测身份)")
    p_bind.add_argument("--out", required=True)
    p_bind.add_argument("--plan", default=None,
                        help="可选:记录对应计划 digest")
    p_bind.add_argument("--launcher", default=None,
                        help="可选:启动器脚本路径(实测其字节身份)")
    p_bind.set_defaults(func=cmd_execution_binding)

    p_run = sub.add_parser("run-coordinate", help="执行单坐标并封存")
    p_run.add_argument("--plan", required=True)
    p_run.add_argument("--coordinate", required=True)
    p_run.add_argument("--out-root", required=True)
    p_run.add_argument("--allow-smoke", action="store_true")
    p_run.add_argument("--execution-binding", default=None,
                       help="预定执行绑定 JSON;不符则在首次生成前拒绝")
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
