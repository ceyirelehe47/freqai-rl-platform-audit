# -*- coding: utf-8 -*-
"""QProd 许可层:验证 + 一次性消费(create-only;无签发能力)。

复用现有 admission/execgov 的职责与 create-only 规则,不另建通用
授权平台:

- 许可至少绑定:预期任务层(level_a|level_b)、迭代、代码冻结 SHA、
  artifact/state 根、预注册输入范围(namespace/坐标集合)、配额
  (叶调用/成功正文/MC 预算)。错层、错根、错 SHA、错 scope、伪造、
  重放均在**任何真实生成/状态消费之前**拒绝。
- **签发不在被验包内**:本模块没有 issue/签发函数;工程许可由隔离
  的 test authority(目录在被验包写边界之外)产生,正式许可属
  未来正式 admission 链(部署正式注册表保持为空)。"外部授权不能由
  被验包自己重算哈希后获得"的实现:许可文件必须位于配置声明的
  authority 目录内,且 authority 目录不得位于本上下文 state/
  artifact root 内部(自授权拒绝);许可 digest 覆盖全部字段,
  字段改动即失配。
- 消费一次性:consume_permit 在 state root 写 append-only 消费
  日志;同 permit_id 二次消费拒绝(replay);消费发生在任何生成
  之前(坐标运行入口强制顺序)。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_qprod_context import (
    QProdContext, QProdContextError, _canonical_json, _fsync_dir,
    _is_within, _now_utc,
)

QPROD_PERMIT_FORMAT = "cur261-qprod-permit-v1"
QPROD_PERMIT_DIGEST_PREFIX = "qppm-"
QPROD_PERMIT_CONSUMED_NAME = "qprod_permit_consumed.jsonl"

#: 签发者种类(工程 test authority;正式 admission 属未来链)。
QPROD_ISSUER_KINDS = ("engineering_test_authority",)

#: 许可必备字段(缺失即拒)。
QPROD_PERMIT_REQUIRED_KEYS = (
    "format", "permit_id", "task_level", "iteration_id",
    "code_freeze_sha", "artifact_root", "state_root",
    "preregistered_input_scope", "quota", "issuer", "permit_digest",
    "issued_utc",
)

#: 配额必备字段(动作前保守预留;完成/失败/中断都结算)。
QPROD_QUOTA_REQUIRED_KEYS = (
    "max_leaf_calls_per_coordinate", "max_successful_episodes_total",
    "mc_events_per_coordinate", "max_native_executions",
)


def permit_digest(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "permit_digest"}
    return QPROD_PERMIT_DIGEST_PREFIX + hashlib.sha256(
        _canonical_json(body).encode("utf-8")).hexdigest()


def load_permit(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise QProdContextError(f"许可文件缺失: {p}")
    try:
        permit = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QProdContextError(f"许可不可解析: {exc}") from exc
    if not isinstance(permit, dict):
        raise QProdContextError("许可必须是 JSON 对象")
    return permit


def validate_permit(permit_path: Path | str, *,
                    context: QProdContext) -> dict[str, Any]:
    """许可验证(fail closed;不做任何状态写入/生成)。

    检查序:文件在 authority 目录内(非自授权)→ 结构/digest →
    字段与上下文逐项一致(任务层/迭代/冻结 SHA/两根/输入范围)→
    scope 内 namespace 均已注册 → 配额结构完整。
    """
    permit_path = Path(permit_path)
    authority = Path(context.authority_dir)
    try:
        inside = permit_path.resolve().is_relative_to(authority.resolve())
    except (OSError, ValueError):
        inside = False
    if not inside:
        raise QProdContextError(
            f"许可文件不在声明的 authority 目录 {authority} 内"
            f"(自授权/外部伪造拒绝:签发发生在被验包写边界之外)")
    permit = load_permit(permit_path)

    missing = [k for k in QPROD_PERMIT_REQUIRED_KEYS if k not in permit]
    if missing:
        raise QProdContextError(f"许可缺字段: {missing}")
    if permit["format"] != QPROD_PERMIT_FORMAT:
        raise QProdContextError(
            f"许可 format {permit['format']!r} 不识别")
    digest = permit_digest(permit)
    if permit["permit_digest"] != digest:
        raise QProdContextError(
            f"许可 digest 失配(重算 {digest} != 声明 "
            f"{permit['permit_digest']!r};字段被改或伪造)")
    if permit["task_level"] != context.level:
        raise QProdContextError(
            f"许可 task_level {permit['task_level']!r} != 上下文层 "
            f"{context.level!r}(错层拒绝:A/B 许可不可串用)")
    if permit["iteration_id"] != context.iteration_id:
        raise QProdContextError(
            f"许可 iteration {permit['iteration_id']!r} != 上下文迭代 "
            f"{context.iteration_id!r}")
    if permit["code_freeze_sha"] != context.code_freeze_sha:
        raise QProdContextError(
            f"许可绑定代码冻结 {permit['code_freeze_sha']!r} != 上下文 "
            f"{context.code_freeze_sha!r}(错 SHA 拒绝)")
    if str(permit["artifact_root"]) != str(context.artifact_root) or \
            str(permit["state_root"]) != str(context.state_root):
        raise QProdContextError(
            f"许可绑定根 ({permit['artifact_root']}, "
            f"{permit['state_root']}) != 上下文根 "
            f"({context.artifact_root}, {context.state_root})"
            f"(错根拒绝)")
    issuer = permit["issuer"]
    if not isinstance(issuer, dict) or issuer.get(
            "kind") not in QPROD_ISSUER_KINDS or not issuer.get(
            "authority_id"):
        raise QProdContextError(f"许可签发者结构非法: {issuer!r}")
    authority_identity = authority / "authority_identity.json"
    if not authority_identity.is_file():
        raise QProdContextError(
            f"authority 身份文件缺失: {authority_identity}"
            f"(无隔离 test authority 身份,不予采信)")
    ident = json.loads(authority_identity.read_text(encoding="utf-8"))
    if ident.get("authority_id") != issuer["authority_id"]:
        raise QProdContextError(
            f"许可签发者 authority_id {issuer['authority_id']!r} != "
            f"authority 身份 {ident.get('authority_id')!r}")
    scope = permit["preregistered_input_scope"]
    if not isinstance(scope, dict) or not (
            scope.get("namespaces") or scope.get("coordinate_ids")):
        raise QProdContextError(
            f"许可预注册输入范围为空/非法: {scope!r}")
    quota = permit["quota"]
    if not isinstance(quota, dict) or any(
            k not in quota for k in QPROD_QUOTA_REQUIRED_KEYS):
        raise QProdContextError(f"许可配额结构非法: {quota!r}")
    # Q2 修复:配额值必须是正整数(bool 不是 int);0 额度许可禁止
    # 进入审计——配额是叶边界执行前置,不是事后统计字段。
    for k in QPROD_QUOTA_REQUIRED_KEYS:
        v = quota[k]
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise QProdContextError(
                f"许可配额 {k}={v!r} 非法(须正整数;0 额度禁止进入"
                f"审计,不允许以 0 配额许可起跑后靠事后计数补救)")
    if context.namespaces_scope:
        declared = set(scope.get("namespaces") or [])
        unknown = declared - set(context.namespaces_scope)
        if unknown:
            raise QProdContextError(
                f"许可 scope 含上下文未声明 namespace: {sorted(unknown)}")
    return permit


def _consumed_records(context: QProdContext) -> list[dict[str, Any]]:
    path = Path(context.state_root) / QPROD_PERMIT_CONSUMED_NAME
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def permit_already_consumed(context: QProdContext,
                            permit_id: str) -> bool:
    return any(r.get("permit_id") == permit_id
               for r in _consumed_records(context))


def consume_permit(permit_path: Path | str, *,
                   context: QProdContext) -> dict[str, Any]:
    """一次性消费(先验证后消费;append-only;fsync)。

    重放拒绝;消费记录进入 state root(与 Level A/B 各自独立)。
    必须在任何真实生成/状态消费之前调用——坐标运行入口在进入
    generator 前强制本调用。
    """
    permit = validate_permit(permit_path, context=context)
    if permit_already_consumed(context, permit["permit_id"]):
        raise QProdContextError(
            f"许可 {permit['permit_id']!r} 已消费(重放拒绝;"
            f"不得重抽已消费运行)")
    path = Path(context.state_root) / QPROD_PERMIT_CONSUMED_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "permit_id": permit["permit_id"],
        "task_level": permit["task_level"],
        "iteration_id": permit["iteration_id"],
        "consumed_utc": _now_utc(),
        "pid": os.getpid(),
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False,
                            sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    _fsync_dir(path.parent)
    return record


class LivePermitToken:
    """进程内已消费许可凭据(生成入口的强制前置)。"""

    def __init__(self, permit: dict[str, Any], consumed: dict[str, Any]):
        self.permit = dict(permit)
        self.consumed = dict(consumed)

    @property
    def quota(self) -> dict[str, Any]:
        return dict(self.permit["quota"])


def acquire_live_permit(permit_path: Path | str, *,
                        context: QProdContext) -> LivePermitToken:
    """获取活动许可凭据(验证+消费;无许可则后续生成入口全部拒绝)。"""
    consumed = consume_permit(permit_path, context=context)
    permit = load_permit(permit_path)
    return LivePermitToken(permit, consumed)


__all__ = [
    "QPROD_PERMIT_FORMAT", "QPROD_PERMIT_CONSUMED_NAME",
    "QPROD_QUOTA_REQUIRED_KEYS", "permit_digest", "load_permit",
    "validate_permit", "consume_permit", "acquire_live_permit",
    "LivePermitToken", "permit_already_consumed",
]
