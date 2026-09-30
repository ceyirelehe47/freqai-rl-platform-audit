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
    QPROD_E01_LEGACY_PLAN_DIGESTS, QPROD_STOP_MODES,
    load_research_plan, research_plan_structure_problems,
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
    """读事件表;损坏(非 JSON)由调用方分类为 technically_corrupt。"""
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

    # ---- Q3 修复:必需成员集合精确覆盖(空集/子集/多余成员均拒) ----
    from rl_curriculum.curriculum261_qprod_coordinate import (
        QPROD_COORDINATE_AUDIT_PLAN_NAME, coordinate_audit_plan_digest,
    )

    required_members = {"cue_contract_audit.json",
                        "cue_event_trace.jsonl",
                        QPROD_BLOCK_SEED_LOG_NAME}
    declared_members = set((seal.get("members_sha256") or {}).keys())
    if declared_members != required_members:
        problems.append(
            f"seal 成员集合 {sorted(declared_members)} != 必需集合 "
            f"{sorted(required_members)}(空集/子集/多余成员均不构成"
            f"有效坐标)")

    # ---- Q3 修复:冻结坐标审计计划(qcap)存在/自洽/绑定 ----
    _qcap_budgets: dict[str, Any] = {}
    qcap_path = coord_dir / QPROD_COORDINATE_AUDIT_PLAN_NAME
    if not qcap_path.is_file():
        problems.append("冻结坐标审计计划缺失(qcap;未锁定的坐标"
                        "产物不构成有效坐标)")
    else:
        qcap = None
        try:
            qcap = json.loads(qcap_path.read_text(encoding="utf-8"))
            qcap_d = coordinate_audit_plan_digest(qcap)
        except (json.JSONDecodeError, KeyError, TypeError,
                ValueError) as exc:
            problems.append(f"冻结坐标审计计划不可解析: {exc}")
        else:
            qcap_digest_file = coord_dir / (
                "qprod_coordinate_audit_plan_digest.txt")
            stored_d = (qcap_digest_file.read_text(
                encoding="utf-8").strip()
                if qcap_digest_file.is_file() else "")
            if stored_d != qcap_d:
                problems.append("冻结坐标审计计划 digest 复算不一致")
            if qcap.get("research_plan_digest") != research_plan.get(
                    "research_plan_digest"):
                problems.append("冻结坐标审计计划未绑定当前研究计划")
            if (qcap.get("namespaces", {}).get("model")
                    != coordinate["model_namespace"]
                    or qcap.get("namespaces", {}).get("validation")
                    != coordinate["validation_namespace"]):
                problems.append("冻结坐标审计计划 namespace 与清单"
                                "不一致")
            if seal.get("coordinate_audit_plan_digest") != qcap_d:
                problems.append("seal 未绑定冻结坐标审计计划 digest")
            _qcap_budgets = dict(qcap.get("budgets") or {})


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
    # Q3 修复:audit digest 公共函数复算(报告自洽 + seal 绑定)
    from rl_curriculum.curriculum261_r17_cue_contract import (
        cue_contract_audit_digest,
    )

    audit_digest_ok = None
    try:
        audit_digest_ok = (report.get("audit_digest")
                           == cue_contract_audit_digest(report))
    except (KeyError, TypeError, ValueError):
        audit_digest_ok = False
    if audit_digest_ok is not True:
        problems.append("报告 audit_digest 公共函数复算不一致"
                        "(伪 audit 摘要拒)")
    if seal.get("audit_digest") != report.get("audit_digest"):
        problems.append("seal audit_digest 与报告 audit_digest 不一致")
    # R2-Q3:qcap 预算与报告实际值对账——qcap/清单声明 500 而报告
    # 实际 2 块(或 MC 声明与执行不符)不再有效;报告必须记录并
    # 真实使用锁定预算。
    cap_blocks = int(_qcap_budgets.get("blocks_per_corpus", -1))
    cap_mc = int(_qcap_budgets.get("mc_events", -1))
    rep_blocks = int(report.get("audit_blocks_per_corpus", -1))
    rep_mc = int((report.get("monte_carlo") or {}).get("n_events", -1))
    if cap_blocks != rep_blocks:
        problems.append(
            f"qcap blocks_per_corpus={cap_blocks} != 报告实际 "
            f"{rep_blocks}(冻结预算与执行不一致)")
    if cap_mc != rep_mc:
        problems.append(
            f"qcap mc_events={cap_mc} != 报告 MC n_events "
            f"{rep_mc}(冻结预算与执行不一致)")
    # R3-Q3:清单条目↔qcap↔报告↔两语料事件**范围**贯通——
    # qcap.block_range 必须与报告 blocks 及双语料事件 block 集合
    # 一致(范围矛盾不再只看预算数字;E01 合法兼容基于计划 digest
    # 白名单身份,不构成范围矛盾豁免)。
    cap_range = ((qcap or {}).get("block_range") or {} \
                 if qcap_path.is_file() else {})
    cap_start = int(cap_range.get("start_index", -1))
    cap_count = int(cap_range.get("count", -1))
    if cap_start != 0:
        problems.append(
            f"qcap block_range.start_index={cap_start} != 0"
            f"(生成内核固定从 0 起;范围矛盾)")
    if cap_count != rep_blocks:
        problems.append(
            f"qcap block_range.count={cap_count} != 报告实际 "
            f"{rep_blocks}(清单-计划-执行范围不一致)")
    # R2-Q3:三方对账——冻结研究计划声明的 audit_budgets 与 qcap/
    # 报告一致(清单声明与执行脱节不再有效)。
    plan_ab = ((research_plan.get("rules") or {})
               .get("audit_budgets")) or {}
    plan_blocks = int(plan_ab.get("blocks_per_corpus", -1))
    plan_mc = int(plan_ab.get("mc_events", -1))
    if plan_blocks != -1 and plan_blocks != rep_blocks:
        problems.append(
            f"研究计划 audit_budgets.blocks_per_corpus={plan_blocks} "
            f"!= 报告实际 {rep_blocks}(计划声明与执行不一致)")
    if plan_mc != -1 and plan_mc != rep_mc:
        problems.append(
            f"研究计划 audit_budgets.mc_events={plan_mc} != 报告 "
            f"MC n_events {rep_mc}(计划声明与执行不一致)")

    seed_log_path = coord_dir / QPROD_BLOCK_SEED_LOG_NAME
    if not seed_log_path.is_file():
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems + [
                    "block seed 日志缺失(seed/namespace 归属不可核)"]}
    try:
        seed_log = [json.loads(ln) for ln in
                    seed_log_path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"state": COORDINATE_STATE_CORRUPT,
                "problems": [f"block seed 日志解析失败(technically "
                             f"corrupt): {exc}"]}
    n_declared_blocks = int(report["audit_blocks_per_corpus"])
    expected_once_seeds = [
        derive261_block_seed(coordinate["model_namespace"], i, 0)
        for i in range(n_declared_blocks)]
    once_entries = [e for e in seed_log if e.get("kind") == "once"]
    for e in once_entries:
        if e["namespace"] != coordinate["model_namespace"]:
            problems.append("once 块 namespace 归属错")
        if e["block_seed"] not in expected_once_seeds:
            problems.append(
                f"once 块 seed {e['block_seed']} 不在 "
                f"derive261_block_seed(model_ns, i, 0) 派生集合内")
    # R2-Q3:once(model)seeds 多重集精确对账——重复同一 seed 替代
    # 另一块(条目数相同)不再被集合包含检查放过。
    if sorted(int(e["block_seed"]) for e in once_entries) != sorted(
            int(x) for x in expected_once_seeds):
        problems.append(
            "once(model)seed 多重集与派生序列不一致(重复/缺失/"
            "替代某块:sorted seeds 对拍失败)")
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
    # Q3 修复:validation seeds 覆盖——attempts 条目数与 block 范围
    # 精确一致(缺 validation seeds 拒)
    attempts_entries = [e for e in seed_log
                        if e.get("kind") == "attempts"]
    blocks_declared = int(report["audit_blocks_per_corpus"])
    if len(attempts_entries) != blocks_declared:
        problems.append(
            f"attempts(validation seeds)条目数 {len(attempts_entries)}"
            f" != blocks_per_corpus {blocks_declared}(validation "
            f"seeds 缺失)")
    attempts_blocks = sorted({int(e["block_index"])
                              for e in attempts_entries})
    if attempts_blocks != list(range(blocks_declared)):
        problems.append(
            f"attempts block 索引集合 {attempts_blocks} != 声明范围 "
            f"[0,{blocks_declared})")

    # 事件复算(共享可靠 reader 函数;拒绝只信汇总 JSON)
    events_path = coord_dir / "cue_event_trace.jsonl"
    if not events_path.is_file():
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems + [
                    "事件原件缺失(聚合必须读实际事件,汇总 JSON "
                    "不构成有效坐标)"]}
    try:
        events = _load_events(coord_dir)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        # 技术损坏:封存成员存在但不可解析(可信性不再成立)——
        # 分类 corrupt 并触发 corrupt_stop 停止语义,不冒称无效
        # 结构也不继续不安全执行(F3 修复)
        return {"state": COORDINATE_STATE_CORRUPT,
                "problems": [f"事件表解析失败(technically corrupt): "
                             f"{exc}"]}
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
    # Q3 修复:事件 block 归属——validation 事件 block 集合必须与
    # attempts seeds 的 block 集合精确一致(换位/漂移拒)
    validation_blocks = sorted({int(e["block_index"])
                                for e in validation_events})
    if validation_blocks != attempts_blocks:
        problems.append(
            f"validation 事件 block 集合 {validation_blocks} != "
            f"attempts seeds block 集合 {attempts_blocks}"
            f"(事件 block 归属不一致)")
    # R2-Q3:model 语料事件结构核验——删 model 事件后即使攻击者
    # 同步重算 seal 摘要使其自洽也不再生效:model 语料必须有与
    # validation 相同 block 范围的非空事件(双语料范围+计数对账)。
    model_events = [e for e in events
                    if e.get("corpus") == "model"]
    model_blocks = sorted({int(e["block_index"])
                           for e in model_events})
    if not model_events:
        problems.append("model 语料事件为空(双语料对账失败)")
    elif model_blocks != attempts_blocks:
        problems.append(
            f"model 事件 block 集合 {model_blocks} != attempts "
            f"seeds block 集合 {attempts_blocks}"
            f"(model 语料缺失/漂移;双语料对账失败)")
    # R3-Q3:两语料事件范围与 qcap/report 范围贯通(事件侧证据
    # 必须落在声明的 block 范围内;范围外事件/缺块均拒)。
    declared_count = int(((research_plan.get("rules") or {})
                          .get("audit_budgets") or {})
                         .get("blocks_per_corpus", -1))
    if declared_count != -1 and attempts_blocks != list(
            range(declared_count)):
        problems.append(
            f"事件 block 集合 {attempts_blocks} != 计划声明范围 "
            f"[0,{declared_count})(双语料范围与清单声明不一致)")
    # R2-Q3:model 统计与报告对账——从 model 事件原件复算 recall,
    # 与报告 direct_generator.model 声明一致(删/改 model 事件即使
    # 重算 seal 摘要自洽,报告统计与事件复算矛盾即拒)。
    model_boot = _cluster_bootstrap(_per_block_event_counts(
        model_events))
    model_reported = ((report.get("direct_generator") or {})
                      .get("model") or {})
    model_recall_reported = model_reported.get("empirical_recall")
    if model_recall_reported is None:
        problems.append("报告缺 direct_generator.model.empirical_"
                        "recall(model 语料统计来源缺失)")
    elif abs(float(model_recall_reported)
             - float(model_boot["point"])) > 1e-12:
        problems.append(
            f"报告 model recall {model_recall_reported} != 事件"
            f"复算 {model_boot['point']}(model 语料与报告矛盾)")
    # Q3 修复:逐 (corpus, block) 事件摘要复算——事件与 block 的
    # 精确绑定;任何换位/改动改变所属 block 摘要即拒。缺失该字段
    # 的 legacy seal 只标记不强制重生成(REVIEWER_ADDENDUM #5)。
    legacy_binding = False
    sealed_pbd = seal.get("per_block_event_digests")
    if not sealed_pbd:
        # R2-Q3:legacy 容忍限定为有身份的 E01 历史原件——研究计划
        # digest 属于已知 E01 原生 run;任意新对象缺字段一律拒
        # (历史兼容不是缺字段的免检开关)。
        if seal.get("research_plan_digest") in (
                QPROD_E01_LEGACY_PLAN_DIGESTS):
            legacy_binding = True
        else:
            problems.append(
                "seal 缺 per_block_event_digests 且不属于已知 E01 "
                "历史原件身份(legacy 容忍仅限有据可核的 E01 计划 "
                "digest;新对象缺事件绑定一律无效)")
    else:
        from rl_curriculum.curriculum261_qprod_coordinate import (
            _per_block_event_digests,
        )
        recomputed_pbd = _per_block_event_digests(
            coord_dir / "cue_event_trace.jsonl")
        if recomputed_pbd != sealed_pbd:
            diff = {k: (sealed_pbd.get(k), recomputed_pbd.get(k))
                    for k in set(sealed_pbd) | set(recomputed_pbd)
                    if sealed_pbd.get(k) != recomputed_pbd.get(k)}
            problems.append(
                f"per-block 事件摘要复算不一致(换位/改动): "
                f"{dict(list(diff.items())[:3])}")

    if problems:
        return {"state": COORDINATE_STATE_INVALID,
                "problems": problems}
    # R2-Q3:audit FAIL 与 v4 偏差类别区分——结构核验通过但坐标
    # 审计合同失败(audit_pass=False)的坐标标记 audit_fail,
    # 聚合消费侧据此排除(不得静默当作正常坐标进入主分析/早停,
    # 也不得因 recall 方向"有利"忽略审计失败)。
    audit_pass = bool(summary.get("audit_pass"))
    return {
        "state": COORDINATE_STATE_VALID,
        "problems": [],
        "audit_fail": not audit_pass,
        "legacy_seal_without_event_binding": legacy_binding,
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
        # Q3 修复:早停约束**聚合消费**——早停已触发后,其后坐标
        # 即使违规生产了 seal 也不进入主分析(标记
        # post_stop_not_consumed/protocol_violation,排除出有效集);
        # 启动侧约束见 coordinate._early_stop_boundary(拒启动)。
        # R3-Q3(撤回 R2 规则):audit_pass=False 不再一律从主分析
        # 剔除——结构/来源合法的坐标即使 cue 合同统计 gate FAIL
        # 也是**有效统计负结果**,collect-all 保留进主分析并如实
        # 标注;技术无效(结构/完整性损坏、中断)由各自真实类别
        # 拒绝或停止,不冒充统计负结果。原"audit_fail_excluded"
        # 规则及相应测试撤回(历史兼容:仅识别该旧标记并忽略)。
        if (entry["state"] == COORDINATE_STATE_VALID
                and entry.get("audit_fail")):
            entry["stats_gate"] = "cue_contract_fail"
            entry["negative_result_valid"] = True
            entry["note"] = (
                "cue 合同审计 gate FAIL:有效统计负结果,保留数值"
                "进主分析(不删样凑绿;K/SE 状况由主分析如实报告)")
        if (stop_mode == "early_stop_on_first_negative"
                and early_stopped_at is not None
                and entry["state"] == COORDINATE_STATE_VALID
                and coord["coordinate_id"] != early_stopped_at):
            entry["state"] = "post_stop_not_consumed"
            entry["protocol_violation"] = (
                f"early_stop 已在 {early_stopped_at!r} 触发;本坐标"
                f" 不应被生产/不进入主分析(启动侧应被拒;此处"
                f"聚合侧排除并留痕)")
        # 早停模式:首个有效统计负结果即停(后续坐标不再要求生产)。
        # 统计负结果 = beyond_positive_margin(delta=P0-recall>margin,
        # 即实测 recall 显著偏低/解析预测高估;v4 ACTION_MAPPING 的
        # 转校准路线方向)。beyond_negative_margin 是有利方向(recall
        # 偏高),不构成负结果、不早停、不标 statistical_negative
        # (F1 修复:reviewer 探针证实旧逻辑把有利跨界误判)。
        # R3-Q3:早停触发用事前定义的统计判据(delta>margin);
        # 结构合法的有效负结果(含统计 gate FAIL)照常参与——
        # 不能因"有利"方向忽略,也不能把技术失败冒充统计触发。
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
                negative = single["magnitude"] == "beyond_positive_margin"
                if single["magnitude"] == "beyond_negative_margin":
                    entry["favorable_beyond_margin"] = True
            else:
                # SE 退化(如极小样本全中):v4 适用条件(s_k>0)
                # 不满足——不发明替代数学,不据此判统计负结果
                negative = False
                entry["degenerate_se"] = True
            if negative:
                early_stopped_at = coord["coordinate_id"]
                entry["statistical_negative"] = True

    valid = [c for c in coordinates if c["state"] == "valid"]
    stats_gate_failed = [c["coordinate_id"] for c in coordinates
                         if c["state"] == "valid"
                         and c.get("audit_fail")]
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
        # R3-Q3:有效统计负结果(含 stats gate FAIL)已在 valid 集;
        # K 不足/SE 退化走 inconclusive 分支如实不决(不删样凑绿)。
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
        "stats_gate_failed_coordinate_ids": stats_gate_failed,
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
