# -*- coding: utf-8 -*-
"""QProd K 坐标聚合 reader(固定锚 v4 合同 + 失败语义 + A/B 停止分层)。

复用已接受的 v4 classify_primary(report/r20_design_calc_v4.py,文件级
加载,不复制数学):

- 主分析合同 = 外部计划显式给定的**共同固定 P0**:
  delta_k = P0 − recall_k(validation),等权聚合,
  S_raw = sqrt(sum(s_k²))/K,s_k = 原口径 block-cluster bootstrap SE
  (未乘安全系数),S_analysis = 1.5 × S_raw,CI90 = delta_bar ±
  z_(1−α)·S_analysis,planned_k=11 不足强制 inconclusive。
- 局部审计锚 p_contract(每坐标 model corpus 位置权重估计)照真实
  算法保留于坐标报告,**不**等于共同 P0,不作为主 delta 锚,也不
  因数值不等删除坐标。
- 聚合器从冻结研究计划清单找原件:核对 seal digest、namespace/
  seed 归属(与派生公式对拍)、事件表复算 recall/SE(共享
  _per_block_event_counts + _cluster_bootstrap),不能只接受未经
  校验的 recall/SE 汇总 JSON;跨坐标事件表字节重复 = 同一 trace
  换文件名充 K 份,拒绝。
- 分类分开:数据/结构/身份无效(不补抽)、运行中断(未完成)、有效
  统计负结果(数值与失败事实保留,按事前模式处理)、少于 K(主分类
  不决)、技术损坏(可信性不再成立,即使收齐模式也停止)。
- 停止模式事前锁定:collect_all_k(统计负结果继续收齐 K)与
  early_stop_on_first_negative(首个统计负结果早停)。Level B 聚合
  结果只是附加确认结论;不得读取或修改 Level A 终态(B 不得把 A
  的 FAIL 聚合"救绿")。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import QProdContextError
from rl_curriculum.curriculum261_qprod_plan import (
    QPROD_STOP_MODES, load_research_plan,
    research_plan_structure_problems,
)
from rl_curriculum.curriculum261_qprod_coordinate import (
    QPROD_BLOCK_SEED_LOG_NAME, QPROD_COORDINATE_INTERRUPTED_NAME,
    QPROD_COORDINATE_SEAL_NAME,
)

QPROD_AGGREGATE_FORMAT = "cur261-qprod-aggregate-v1"

#: 坐标状态(分类分开;仅 valid 进入主聚合)。
COORDINATE_STATE_VALID = "valid"
COORDINATE_STATE_INVALID = "invalid_structure_identity"
COORDINATE_STATE_INTERRUPTED = "interrupted_incomplete"
COORDINATE_STATE_MISSING = "missing"
COORDINATE_STATE_CORRUPT = "technically_corrupt"


def _load_v4_module():
    """文件级加载已接受的 v4 主分析(纯标准库;不复制数学)。"""
    candidates = [
        Path(__file__).resolve().parents[2] / "report" /
        "r20_design_calc_v4.py",
        Path(__file__).resolve().parents[3] / "stage2_6_1" / "report" /
        "r20_design_calc_v4.py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location(
                "r20_design_calc_v4_loaded", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise QProdContextError(
        "r20_design_calc_v4.py 未找到(已接受 v4 数学必须复用,"
        "不得另写一套)")


def _load_events(coord_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    path = coord_dir / "cue_event_trace.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _verify_coordinate(coord_dir: Path, coordinate: dict[str, Any],
                        research_plan: dict[str, Any]) -> dict[str, Any]:
    """单坐标核验:seal/digest/namespace/seed/事件复算/汇总对拍。

    返回 {state, problems, recall, se, p_contract_local, ...};
    任何摘要/归属/复算矛盾 → invalid;seal 缺失且 interrupted 标记
    在 → interrupted;两者皆无 → missing。
    """
    from rl_curriculum.curriculum261_r17_cue_contract import (
        _cluster_bootstrap, _per_block_event_counts,
    )
    from rl_curriculum.curriculum261_r6_tape import derive261_block_seed

    problems: list[str] = []
    seal_path = coord_dir / QPROD_COORDINATE_SEAL_NAME
    if not seal_path.is_file():
        if (coord_dir / QPROD_COORDINATE_INTERRUPTED_NAME).is_file():
            return {"state": COORDINATE_STATE_INTERRUPTED,
                    "problems": ["坐标目录存在中断标记(未完成,不冒称"
                                 "完整结果)"]}
        return {"state": COORDINATE_STATE_MISSING,
                "problems": ["坐标目录无 seal(该坐标未生产)"]}
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    if seal.get("coordinate_id") != coordinate["coordinate_id"]:
        problems.append("seal coordinate_id 与清单不一致")
    if seal.get("research_plan_digest") != research_plan.get(
            "research_plan_digest"):
        problems.append("seal 未绑定当前冻结研究计划 digest")

    # 成员摘要核对(从冻结 seal 找原件并核对摘要/来源)
    for name, want in (seal.get("members_sha256") or {}).items():
        p = coord_dir / name
        if not p.is_file():
            problems.append(f"seal 成员缺失 {name}")
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got != want:
            problems.append(f"seal 成员摘要不符 {name}")

    report_path = coord_dir / "cue_contract_audit.json"
    if not report_path.is_file():
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems + [
                    "坐标审计报告原件缺失(只有汇总/seal 不构成"
                    "有效坐标;聚合必须读实际事件)"]}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # namespace 归属:报告实际 namespace 必须与清单一致
    if (report.get("audit_namespaces", {}).get("model")
            != coordinate["model_namespace"]
            or report.get("audit_namespaces", {}).get("validation")
            != coordinate["validation_namespace"]):
        problems.append("报告实际 namespace 与清单不一致")

    seed_log_path = coord_dir / QPROD_BLOCK_SEED_LOG_NAME
    if not seed_log_path.is_file():
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems + [
                    "block seed 日志缺失(seed/namespace 归属不可核)"]}
    seed_log = [json.loads(ln) for ln in
                seed_log_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()]
    expected_once_seeds = {
        derive261_block_seed(coordinate["model_namespace"], i, 0)
        for i in range(int(seal["summary"].get("blocks_per_corpus", 2))
                       if "blocks_per_corpus" in seal.get("summary", {})
                       else report["audit_blocks_per_corpus"])}
    once_entries = [e for e in seed_log if e.get("kind") == "once"]
    for e in once_entries:
        if e["namespace"] != coordinate["model_namespace"]:
            problems.append("once 块 namespace 归属错")
        if e["block_seed"] not in expected_once_seeds:
            problems.append(
                f"once 块 seed {e['block_seed']} 不在 "
                f"derive261_block_seed(model_ns, i, 0) 派生集合内")
    for e in seed_log:
        if e.get("kind") == "attempts":
            if e["namespace"] != coordinate["validation_namespace"]:
                problems.append("attempts 块 namespace 归属错")
            expected = derive261_block_seed(
                coordinate["validation_namespace"],
                int(e["block_index"]),
                int(e.get("selected_attempt") or 0))
            if e.get("block_seed") not in (
                    expected,
                    derive261_block_seed(
                        coordinate["validation_namespace"],
                        int(e["block_index"]), 0)):
                problems.append(
                    f"attempts 块 seed {e.get('block_seed')} 与派生"
                    f"公式不一致(block {e.get('block_index')})")
    if len(once_entries) != report["audit_blocks_per_corpus"]:
        problems.append("once 块数与报告 blocks_per_corpus 不一致")

    # 事件复算(共享可靠 reader 函数;拒绝只信汇总 JSON)
    events_path = coord_dir / "cue_event_trace.jsonl"
    if not events_path.is_file():
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems + [
                    "事件原件缺失(聚合必须读实际事件,汇总 JSON "
                    "不构成有效坐标)"]}
    events = _load_events(coord_dir)
    validation_events = [e for e in events
                         if e.get("corpus") == "validation"]
    per_block = _per_block_event_counts(validation_events)
    boot = _cluster_bootstrap(per_block)
    recall_recomputed = boot["point"]
    se_recomputed = boot["se"]
    summary = seal.get("summary") or {}
    if abs(float(summary.get("recall_validation", -1))
           - recall_recomputed) > 1e-12:
        problems.append(
            f"seal recall {summary.get('recall_validation')} != 事件"
            f"复算 {recall_recomputed}(汇总与原件矛盾)")
    if abs(float(summary.get("se_validation", -1))
           - se_recomputed) > 1e-12:
        problems.append(
            f"seal SE {summary.get('se_validation')} != 事件复算 "
            f"{se_recomputed}")
    # 报告内 bootstrap 与复算一致性(同函数同输入)
    report_se = report["direct_generator"]["validation"]["block_cluster"]
    if abs(float(report_se["point"]) - recall_recomputed) > 1e-12:
        problems.append("报告 validation recall 与事件复算不一致")

    if problems:
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems}
    return {
        "state": COORDINATE_STATE_VALID,
        "problems": [],
        "recall_validation": recall_recomputed,
        "se_validation": se_recomputed,
        "p_contract_local": float(summary.get("p_contract_local", 0.0)),
        "audit_pass": bool(summary.get("audit_pass")),
        "audit_digest": seal.get("audit_digest"),
        "events_sha256": hashlib.sha256(
            (coord_dir / "cue_event_trace.jsonl").read_bytes()
        ).hexdigest(),
        "engineering_only": bool(summary.get("engineering_only")),
    }


def aggregate_research(artifact_root: Path | str, *,
                       state_root: Path | str,
                       level_a_state_root: Path | str | None = None,
                       ) -> dict[str, Any]:
    """K 坐标聚合(从冻结计划清单读原件;主分类交给 v4)。

    level_a_state_root 仅只读引用核对 A 终态存在性——Level B 聚合
    不得写 Level A 状态,也不得改变其终态。
    """
    artifact_root = Path(artifact_root)
    research_plan = load_research_plan(state_root)
    problems = research_plan_structure_problems(research_plan)
    if problems:
        raise QProdContextError(f"研究计划结构问题: {problems}")
    stop_mode = research_plan.get("stop_mode")
    if stop_mode not in QPROD_STOP_MODES:
        raise QProdContextError(f"stop_mode {stop_mode!r} 未事前锁定")
    rules = research_plan["rules"]
    p0 = float(rules["p0_fixed_reference"])
    v4 = _load_v4_module()

    coordinates: list[dict[str, Any]] = []
    seen_event_hashes: dict[str, str] = {}
    corrupt_stop = False
    early_stopped_at: str | None = None
    for coord in research_plan["coordinate_manifest"]:
        coord_dir = artifact_root / str(coord["artifact_subdir"])
        verdict = _verify_coordinate(coord_dir, coord, research_plan)
        entry = {
            "coordinate_id": coord["coordinate_id"],
            **{k: v for k, v in verdict.items()
               if k not in ("events_sha256",)},
        }
        if verdict["state"] == COORDINATE_STATE_VALID:
            eh = verdict["events_sha256"]
            if eh in seen_event_hashes:
                # 同一 trace 换文件名充 K 份:两个坐标都判无效
                other = seen_event_hashes[eh]
                entry["state"] = COORDINATE_STATE_INVALID
                entry["problems"] = [
                    f"事件表与坐标 {other} 逐字节重复(同一 trace 充 "
                    f"K 份拒绝)"]
                for prev in coordinates:
                    if prev["coordinate_id"] == other:
                        prev["state"] = COORDINATE_STATE_INVALID
                        prev["problems"] = [
                            f"事件表与坐标 {entry['coordinate_id']} "
                            f"逐字节重复"]
            else:
                seen_event_hashes[eh] = coord["coordinate_id"]
        if verdict["state"] == COORDINATE_STATE_CORRUPT:
            corrupt_stop = True
        coordinates.append(entry)
        # 早停模式:首个有效统计负结果即停(后续坐标不再要求生产)
        if (stop_mode == "early_stop_on_first_negative"
                and entry["state"] == COORDINATE_STATE_VALID
                and early_stopped_at is None):
            delta_k = p0 - float(entry["recall_validation"])
            se_k = float(entry["se_validation"])
            if se_k > 0.0:
                single = v4.classify_primary(
                    delta_k, [se_k],
                    margin=float(rules["margin"]),
                    r_analysis=float(rules["r_analysis"]),
                    alpha=float(rules["alpha"]), planned_k=None)
                negative = single["magnitude"] in (
                    "beyond_positive_margin", "beyond_negative_margin")
            else:
                # SE 退化(如极小样本全中):v4 适用条件(s_k>0)
                # 不满足——不发明替代数学,不据此判统计负结果
                negative = False
                entry["degenerate_se"] = True
            if negative:
                early_stopped_at = coord["coordinate_id"]
                entry["statistical_negative"] = True

    valid = [c for c in coordinates if c["state"] == "valid"]
    deltas = [p0 - float(c["recall_validation"]) for c in valid]
    ses = [float(c["se_validation"]) for c in valid]
    planned_k = int(rules["planned_k"])
    enough = len(valid) >= planned_k and not corrupt_stop

    primary: dict[str, Any]
    if corrupt_stop:
        primary = {
            "magnitude": "halted_technically_corrupt",
            "note": "技术损坏且可信性不再成立:即使收齐模式也停止"
                    "不安全执行并保留边界",
        }
    elif deltas and enough and all(s > 0.0 for s in ses):
        delta_bar = sum(deltas) / len(deltas)
        primary = v4.classify_primary(
            delta_bar, ses, margin=float(rules["margin"]),
            r_analysis=float(rules["r_analysis"]),
            alpha=float(rules["alpha"]), planned_k=planned_k)
    elif deltas and all(s > 0.0 for s in ses):
        # 少于 K:主分类不决(不能按实际较少 K 缩小门槛);仅描述性
        delta_bar = sum(deltas) / len(deltas)
        descriptive = v4.classify_primary(
            delta_bar, ses, margin=float(rules["margin"]),
            r_analysis=float(rules["r_analysis"]),
            alpha=float(rules["alpha"]), planned_k=planned_k)
        primary = {
            "magnitude": "inconclusive",
            "not_resolved_reason": "insufficient_coordinates",
            "descriptive_only": True,
            "delta_bar_descriptive": descriptive["delta_bar"],
            "s_raw_descriptive": descriptive["s_raw"],
            "note": "有效坐标数 < planned_k:主分类不决,描述性统计"
                    "仅供参考,不冒用完整 K 推断",
        }
    elif deltas:
        # 存在 SE<=0 的退化坐标(极小工程样本 validation 全中/recall
        # 饱和):已接受 v4 数学的适用条件(每个 s_k>0)不满足——
        # 不删除坐标、不改 v4、不发明替代公式;主分类如实不决。
        primary = {
            "magnitude": "inconclusive",
            "not_resolved_reason": (
                "degenerate_se_prevents_v4_application"),
            "descriptive_only": True,
            "delta_bar_descriptive": sum(deltas) / len(deltas),
            "degenerate_se_coordinates": [
                c["coordinate_id"] for c in valid
                if float(c["se_validation"]) <= 0.0],
            "note": "退化 SE(=0)坐标在场:v4 classify_primary 要求"
                    "每个 s_k>0;坐标保留为有效数据,主分类不决,"
                    "不借此删样或另立公式(小样本统计不决是预期"
                    "工程结果,不调 seed/阈值救援)",
        }
    else:
        primary = {
            "magnitude": "inconclusive",
            "not_resolved_reason": "no_valid_coordinates",
            "note": "无有效坐标(无效/中断/缺失不补抽,不冒称完整"
                    "结果)",
        }

    level_a_terminal: dict[str, Any] = {"read_only_reference": True}
    if level_a_state_root is not None:
        journal = Path(level_a_state_root) / "qprod_run_journal.jsonl"
        if journal.is_file():
            terms = [json.loads(ln) for ln in
                     journal.read_text(encoding="utf-8").splitlines()
                     if ln.strip()]
            terminal = [e for e in terms
                        if e.get("event") == "run_terminal_recorded"]
            level_a_terminal["terminal_events"] = [
                {k: e.get(k) for k in
                 ("status", "verdict", "plan_digest", "utc")}
                for e in terminal]

    report = {
        "format": QPROD_AGGREGATE_FORMAT,
        "aggregated_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "research_plan_digest": research_plan["research_plan_digest"],
        "stop_mode": stop_mode,
        "early_stopped_at": early_stopped_at,
        "anchor": {
            "p0_fixed_reference": p0,
            "p0_source_label": rules.get("p0_source_label"),
            "delta_definition": rules.get("delta_definition"),
            "note": "主分析锚 = 外部计划显式给定的共同固定 P0;"
                    "局部 p_contract 照真实算法计算,用于其原有局部"
                    "审计,不要求等于 P0,不因不等删坐标",
        },
        "coordinates": coordinates,
        "valid_coordinate_count": len(valid),
        "planned_k": planned_k,
        "level_a_terminal": level_a_terminal,
        "primary": primary,
        "ab_separation_note": "Level B 聚合只作附加确认结论;不读取"
                              "修改 Level A 终态;A 的 FAIL 不因 B "
                              "聚合救绿(A 终态仅只读引用)",
    }
    return report


def write_aggregate_report(report: dict[str, Any],
                           out_path: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False,
                                   default=float), encoding="utf-8")
    return out_path


__all__ = [
    "aggregate_research", "write_aggregate_report",
    "COORDINATE_STATE_VALID", "COORDINATE_STATE_INVALID",
    "COORDINATE_STATE_INTERRUPTED", "COORDINATE_STATE_MISSING",
    "COORDINATE_STATE_CORRUPT", "_load_v4_module", "_load_events",
    "_verify_coordinate",
]
