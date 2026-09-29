# -*- coding: utf-8 -*-
"""QProd 两阶段计划:数据前研究/运行计划 + 校准后资格计划。

NEXT_GOAL §2 的两种计划必须区分:

1. **数据前的运行/研究计划**(Level B 主用;Level A 链前段同构):
   绑定坐标清单、规则(固定锚/边界/alpha/r_analysis/planned_k/
   停止模式)与预算;在任何该批数据生成之前冻结(create-only);
   重复坐标、相同抽样空间冒充不同坐标、清单外输出不得进入主聚合。
2. **design/calibration 后才可形成的最终资格计划**(Level A):
   绑定所选 pack、fit/bundle 与一次性资格输入;其输入是真实
   calibration 产物 digest,不为"数据前绑定"要求尚未产生的结果。

两个计划 digest 前缀不同(qbpl- vs qapl-),衔接由实际产物/日志
完成(资格计划携带 prior_plan_digest + calibration 产物 digest
清单),不能用同名 plan_digest 混为一件。锁定文件 create-only:
已存在即拒绝重锁/修改;装载时 digest 复算 + 代码身份零漂移。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import (
    QProdContextError, _canonical_json, _fsync_dir,
)

QPROD_RESEARCH_PLAN_FORMAT = "cur261-qprod-research-plan-v1"
QPROD_RESEARCH_PLAN_PREFIX = "qbpl-"
QPROD_RESEARCH_PLAN_NAME = "qprod_research_plan.json"
QPROD_RESEARCH_PLAN_DIGEST_NAME = "qprod_research_plan_digest.txt"

QPROD_QUALIFICATION_PLAN_FORMAT = "cur261-qprod-qualification-plan-v1"
QPROD_QUALIFICATION_PLAN_PREFIX = "qapl-"
QPROD_QUALIFICATION_PLAN_NAME = "qprod_qualification_plan.json"
QPROD_QUALIFICATION_PLAN_DIGEST_NAME = "qprod_qualification_plan_digest.txt"

#: 停止模式(NEXT_GOAL §4:两个事前可选;正式采用留待批准)。
QPROD_STOP_MODES = ("collect_all_k", "early_stop_on_first_negative")


def research_plan_digest(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items()
            if k not in ("research_plan_digest", "locked_utc")}
    return QPROD_RESEARCH_PLAN_PREFIX + hashlib.sha256(
        _canonical_json(body).encode("utf-8")).hexdigest()


def qualification_plan_digest(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items()
            if k not in ("qualification_plan_digest", "locked_utc")}
    return QPROD_QUALIFICATION_PLAN_PREFIX + hashlib.sha256(
        _canonical_json(body).encode("utf-8")).hexdigest()


def _freeze(path: Path, digest_path: Path, payload: dict[str, Any],
            digest_value: str) -> None:
    if path.is_file() or digest_path.is_file():
        raise QProdContextError(
            f"计划已锁定 {path.name};禁止修改/重锁(须形成新计划并"
            f"重新核验,不得改写已冻结计划)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    digest_path.write_text(digest_value + "\n", encoding="utf-8")
    _fsync_dir(path.parent)


def freeze_research_plan(state_root: Path | str,
                         payload: dict[str, Any],
                         ) -> tuple[Path, str]:
    """冻结数据前研究/运行计划(Level B 坐标清单+规则+预算)。"""
    if payload.get("format") != QPROD_RESEARCH_PLAN_FORMAT:
        raise QProdContextError(
            f"研究计划 format {payload.get('format')!r} 非法")
    if payload.get("stop_mode") not in QPROD_STOP_MODES:
        raise QProdContextError(
            f"stop_mode {payload.get('stop_mode')!r} 必须事前选定"
            f"(两种模式之一;正式采用留待批准)")
    body = dict(payload)
    digest = research_plan_digest(body)
    body["research_plan_digest"] = digest
    body["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    state_root = Path(state_root)
    path = state_root / QPROD_RESEARCH_PLAN_NAME
    digest_path = state_root / QPROD_RESEARCH_PLAN_DIGEST_NAME
    _freeze(path, digest_path, body, digest)
    return path, digest


def load_research_plan(state_root: Path | str) -> dict[str, Any]:
    state_root = Path(state_root)
    path = state_root / QPROD_RESEARCH_PLAN_NAME
    digest_path = state_root / QPROD_RESEARCH_PLAN_DIGEST_NAME
    if not path.is_file() or not digest_path.is_file():
        raise QProdContextError(
            "研究计划未冻结(任何该批数据生成前必须先冻结;"
            "fail closed)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = research_plan_digest(payload)
    if digest_path.read_text(encoding="utf-8").strip() != digest:
        raise QProdContextError(
            "研究计划 digest 复算不一致(fail closed;冻结后不得修改)")
    return payload


def freeze_qualification_plan(state_root: Path | str,
                              payload: dict[str, Any],
                              ) -> tuple[Path, str]:
    """冻结校准后资格计划(pack/fit/bundle + 一次性资格输入)。

    payload 必须携带 prior_plan_digest(与前段计划的真实衔接)与
    calibration_artifacts(实际产物 digest 清单)——两种计划不能
    用同名 digest 混为一件。
    """
    if payload.get("format") != QPROD_QUALIFICATION_PLAN_FORMAT:
        raise QProdContextError(
            f"资格计划 format {payload.get('format')!r} 非法")
    if not payload.get("prior_plan_digest"):
        raise QProdContextError(
            "资格计划必须携带 prior_plan_digest(与前段计划/链的"
            "真实衔接;两种计划不得混为一件)")
    if not payload.get("calibration_artifacts"):
        raise QProdContextError(
            "资格计划必须绑定实际 calibration 产物 digest 清单"
            "(数据前计划不得要求尚未产生的结果;数据后资格计划"
            "必须有真实校准依据)")
    body = dict(payload)
    digest = qualification_plan_digest(body)
    body["qualification_plan_digest"] = digest
    body["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    state_root = Path(state_root)
    path = state_root / QPROD_QUALIFICATION_PLAN_NAME
    digest_path = state_root / QPROD_QUALIFICATION_PLAN_DIGEST_NAME
    _freeze(path, digest_path, body, digest)
    return path, digest


def load_qualification_plan(state_root: Path | str) -> dict[str, Any]:
    state_root = Path(state_root)
    path = state_root / QPROD_QUALIFICATION_PLAN_NAME
    digest_path = state_root / QPROD_QUALIFICATION_PLAN_DIGEST_NAME
    if not path.is_file() or not digest_path.is_file():
        raise QProdContextError("资格计划未锁定(fail closed)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = qualification_plan_digest(payload)
    if digest_path.read_text(encoding="utf-8").strip() != digest:
        raise QProdContextError(
            "资格计划 digest 复算不一致(fail closed)")
    return payload


#: 研究计划必需结构(结构问题清单外输出不得进入主聚合)。
QPROD_RESEARCH_PLAN_REQUIRED_KEYS = (
    "format", "level", "iteration_id", "profile",
    "code_freeze_sha", "rules", "quota",
    "code_identity", "stop_mode",
)


def research_plan_structure_problems(
        payload: dict[str, Any]) -> list[str]:
    """研究/运行计划结构校验(按层分支;结构问题清单外不得进主聚合)。"""
    problems: list[str] = []
    for k in QPROD_RESEARCH_PLAN_REQUIRED_KEYS:
        if k not in payload:
            problems.append(f"缺字段 {k}")
    if problems:
        return problems
    level = payload.get("level")
    if level == "level_b":
        return _structure_problems_level_b(payload)
    if level == "level_a":
        return _structure_problems_level_a(payload)
    problems.append(f"level {level!r} 非法(须 level_a|level_b)")
    return problems


def _structure_problems_level_a(payload: dict[str, Any]) -> list[str]:
    """Level A 运行计划:绑定运行范围/门集/预算(数据前)。"""
    problems: list[str] = []
    scope = payload.get("run_scope")
    if not isinstance(scope, dict):
        problems.append("run_scope 必须是对象(绑定入口/门集/预算)")
        return problems
    for k in ("entry", "gate_set", "budget", "exposure_policy"):
        if k not in scope:
            problems.append(f"run_scope 缺 {k}")
    rules = payload.get("rules")
    if not isinstance(rules, dict) or not rules.get("gate_semantics_ref"):
        problems.append("rules.gate_semantics_ref 缺(判定语义来源)")
    return problems


def _structure_problems_level_b(
        payload: dict[str, Any]) -> list[str]:
    """Level B 研究计划:坐标清单唯一性/规则完整性。"""
    problems: list[str] = []
    manifest = payload.get("coordinate_manifest")
    if not isinstance(manifest, list) or not manifest:
        problems.append("coordinate_manifest 必须是非空列表")
        return problems
    ids = [c.get("coordinate_id") for c in manifest]
    if len(set(ids)) != len(ids):
        problems.append("坐标 id 重复")
    namespaces: list[str] = []
    for c in manifest:
        for key in ("model_namespace", "validation_namespace"):
            ns = c.get(key)
            if not ns:
                problems.append(
                    f"坐标 {c.get('coordinate_id')!r} 缺 {key}")
            else:
                namespaces.append(ns)
        if c.get("model_namespace") and c.get(
                "model_namespace") == c.get("validation_namespace"):
            problems.append(
                f"坐标 {c.get('coordinate_id')!r} model/validation "
                f"namespace 相同(相同抽样空间冒充不同坐标拒绝)")
        if not c.get("artifact_subdir"):
            problems.append(
                f"坐标 {c.get('coordinate_id')!r} 缺独立产物位置")
    if len(set(namespaces)) != len(namespaces):
        problems.append("namespace 跨坐标重复(同一 trace 换文件名"
                        "充 K 份拒绝)")
    rules = payload["rules"]
    for k in ("p0_fixed_reference", "p0_source_label", "delta_definition",
              "margin", "alpha", "r_analysis", "planned_k"):
        if k not in rules:
            problems.append(f"rules 缺 {k}")
    if str(rules.get("delta_definition", "")).replace(" ", "") not in (
            "P0-recall(validation)", "P0-recall_k"):
        problems.append(
            f"delta_definition {rules.get('delta_definition')!r} 非法"
            f"(主 delta = 固定共同锚 − validation recall)")
    return problems


__all__ = [
    "QPROD_RESEARCH_PLAN_FORMAT", "QPROD_RESEARCH_PLAN_NAME",
    "QPROD_QUALIFICATION_PLAN_FORMAT", "QPROD_QUALIFICATION_PLAN_NAME",
    "QPROD_STOP_MODES", "research_plan_digest",
    "qualification_plan_digest", "freeze_research_plan",
    "load_research_plan", "freeze_qualification_plan",
    "load_qualification_plan", "research_plan_structure_problems",
    "QPROD_RESEARCH_PLAN_REQUIRED_KEYS",
]
