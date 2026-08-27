"""Builder 产物来源证明与统一 Runner 调用协议(阶段 2.6.0g 工作包 A2/B)。

2.6.0f 遗留缺陷(npb- 只证明"评估环境中存在一组被哈希的文件"):

- builder identity 只绑定 builder package tree 的文件内容与外部依赖
  身份,没有证明这组文件中的 Builder 实际生成了 commitment.pack_hash
  所绑定的 pack——私有 builder 入口返回 None,仍能与公开 mock pack
  组合后通过 formal verification(verify 只对账 manifest hash,
  从不执行 builder);
- 私有 Provider 不验证 entrypoint/attempt-loop 的存在性、callable
  类型、签名与返回值(2.6.0g A1 在 builder_identity 侧修复);
- 不存在版本化的 Builder 调用协议,构建请求与产物没有规范化合同。

本模块建立(阶段 2.6.0g):

- builder-runner-protocol-v1:私有 Builder 统一适配为单一入口
  ``build_pack(frozen_build_request) -> build_result``;
- 冻结构建请求(builder-build-request-v1):由评估方代码从 Builder
  identity + 考试 pack 派生的时间/统计框架参数,不得包含候选
  checkpoint、模型、policy、成绩或任何候选输出(黑名单 fail closed,
  顶层与嵌套键名一律拒绝);请求哈希 nbr- 进入 sealed commitment v7,
  验证端重放时输入不可被替换;
- 规范化构建结果(builder-build-result-v1):{status, pack,
  attempt_log, error};返回 None、抛异常、返回非 dict、status 非 ok、
  pack 缺失或不可解析一律 failed(fail closed);
- verify_builder_provenance:在冻结输入下实际执行 builder(经
  Provider 的受控入口),要求产物 pack_hash == commitment.pack_hash
  ——不仅证明"Builder A 的文件身份正确",还要证明"Builder A 在冻结
  输入和运行环境下实际产生的 pack,正是 commitment.pack_hash 所绑定
  的 pack"(阶段 2.6.0g 核心目标)。执行发生在 formal D1 步骤 4b,
  先于候选 checkpoint 加载与沙箱启动。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Builder Runner 调用协议(build 入口适配与结果合同)
BUILDER_RUNNER_PROTOCOL = "builder-runner-protocol-v1"
#: 冻结构建请求格式
BUILD_REQUEST_FORMAT = "builder-build-request-v1"
#: 规范化构建结果格式
BUILD_RESULT_FORMAT = "builder-build-result-v1"

#: 冻结构建请求禁止字段(候选相关性 fail closed;递归扫描键名——
#: 任何层级出现都拒绝:构建请求不得包含候选 checkpoint、模型、
#: policy、成绩或候选输出)
BUILD_REQUEST_FORBIDDEN_FIELDS = (
    "candidate", "checkpoint", "model", "policy", "score", "scores",
    "verdict", "outcome", "ranking", "result", "prediction",
)


class BuilderProvenanceError(RuntimeError):
    """产物来源证明失败(fail closed -> EXAM_INVALID)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ 冻结请求
def _scan_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    """递归收集出现在任何层级的禁止键名(含 list 内 dict)。

    键名等于禁止名或以其为前缀(candidate_score / model_path 等
    候选相关派生字段一并拒绝)。
    """
    hits: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            if any(key == f or key.startswith(f + "_")
                   for f in BUILD_REQUEST_FORBIDDEN_FIELDS):
                hits.append(f"{prefix}{key}" if not prefix
                            else f"{prefix}.{key}")
            hits.extend(_scan_forbidden_fields(
                v, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            hits.extend(_scan_forbidden_fields(
                item, f"{prefix}[{i}]"))
    return hits


def check_frozen_build_request(request: Any) -> None:
    """冻结构建请求的格式与黑名单校验(fail closed)。"""
    if not isinstance(request, dict):
        raise BuilderProvenanceError(
            f"冻结构建请求必须是 dict(收到 {type(request)!r};"
            f"builder-runner-protocol-v1)")
    if request.get("format") != BUILD_REQUEST_FORMAT:
        raise BuilderProvenanceError(
            f"冻结构建请求格式必须是 {BUILD_REQUEST_FORMAT!r}"
            f"(收到 {request.get('format')!r})")
    if request.get("runner_protocol") != BUILDER_RUNNER_PROTOCOL:
        raise BuilderProvenanceError(
            f"冻结构建请求的 runner 协议必须是 "
            f"{BUILDER_RUNNER_PROTOCOL!r}(收到 "
            f"{request.get('runner_protocol')!r})")
    required = ("builder_manifest_hash", "families", "pair_count_per_family",
                "max_attempts", "params_spec", "timeframe", "resolved_bars",
                "duration_contract_hash")
    missing = [f for f in required
               if request.get(f) in (None, "", [], {}, 0)]
    if missing:
        raise BuilderProvenanceError(
            f"冻结构建请求缺少必填字段 {missing}(builder 重放的冻结输入"
            f"不完整;EXAM_INVALID)")
    hits = _scan_forbidden_fields(request)
    if hits:
        raise BuilderProvenanceError(
            f"冻结构建请求包含禁止字段 {sorted(set(hits))}:构建请求"
            f"不得包含候选 checkpoint/model/policy/成绩或任何候选输出"
            f"(fail closed;EXAM_INVALID)")


def build_frozen_build_request(
    identity: Any, *,
    pack: Any, duration_contract: dict[str, Any],
    include_mock_pack_payload: bool = False,
) -> dict[str, Any]:
    """从 Builder identity + 考试 pack + 全局时长合同派生冻结构建请求。

    统一由评估方代码构造(Provider 只提供身份输入,不能自行放水):
    请求内容 = builder 身份(npb-/协议/params_spec/families/pair 数/
    attempt 上限)+ pack 公开自由度(name/version/timeframe)+
    duration contract 的 timeframe/resolved_bars/ndc-。隐藏 seed 不
    进请求(私有 builder 从自身冻结的 seed namespace 重放)。

    include_mock_pack_payload 仅用于公开 mock 通道:mock builder 是
    公开验证基础设施的"组装器",其冻结构建输入就是 pack 的公开
    规范(name/version/visibility/charter_hash/spec_versions/
    episodes 的规范化 JSON)——mock_build_pack 按该载荷确定性重建
    ExamPack。私有 builder 的请求**永不携带**该载荷(重放必须是
    真实构建,不得照抄 pack 内容);verify_builder_provenance 的
    allow_mock_pack_payload 闸对非 mock 通道 fail closed。
    """
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash as _ndc_hash,
    )

    manifest = identity.manifest or {}
    request = {
        "format": BUILD_REQUEST_FORMAT,
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "builder_protocol": str(identity.builder_protocol),
        "builder_manifest_hash": str(identity.manifest_hash),
        "pack_name": str(getattr(pack, "name", "") or ""),
        "pack_version": str(getattr(pack, "version", "") or ""),
        "pack_timeframe": str(getattr(pack, "timeframe", "") or ""),
        "families": list(manifest.get("families") or []),
        "pair_count_per_family": int(
            manifest.get("pair_count_per_family") or 0),
        "max_attempts": int(manifest.get("max_attempts") or 0),
        "params_spec": dict(manifest.get("params_spec") or {}),
        "timeframe": str(duration_contract["timeframe"]),
        "resolved_bars": int(duration_contract["resolved_bars"]),
        "resolved_duration_hours": float(
            duration_contract["resolved_duration_hours"]),
        "duration_contract_hash": str(_ndc_hash(duration_contract)),
    }
    if include_mock_pack_payload:
        import json as _json

        request["mock_pack_payload"] = _json.loads(pack.to_json())
    check_frozen_build_request(request)
    return request


def frozen_build_request_hash(request: dict[str, Any]) -> str:
    """冻结构建请求哈希(nbr-;canonical JSON,排序稳定)。"""
    check_frozen_build_request(request)
    return "nbr-" + _canonical_json_hash(request)


# ------------------------------------------------------------ 执行协议
def _coerce_pack(raw: Any) -> Any:
    """构建结果中的 pack 必须是 ExamPack 实例或可解析的规范化文件。"""
    from rl_curriculum.exam_pack import ExamPack

    if isinstance(raw, ExamPack):
        return raw
    if isinstance(raw, dict):
        return ExamPack.from_json(json.dumps(raw))
    if isinstance(raw, str):
        return ExamPack.from_json(raw)
    raise BuilderProvenanceError(
        f"构建结果中的 pack 无法解析(类型 {type(raw)!r};必须是 "
        f"ExamPack 实例或规范化 pack 文件 dict/JSON)")


def run_builder_entrypoint(entrypoint_fn: Any, request: dict[str, Any]) \
        -> dict[str, Any]:
    """A2:执行 builder 入口并规范化结果(builder-runner-protocol-v1)。

    调用形态固定为 ``entrypoint_fn(request)``;返回规范化 dict:
    {format, runner_protocol, status: ok|failed, pack, attempt_log,
    error}。返回 None、抛异常、返回非 dict、status 非 ok、pack 缺失
    或不可解析一律 failed——正式路径不存在"builder 失败但仍采信
    pack"的通道。
    """
    def _failed(error: str, attempt_log: Any = None) -> dict[str, Any]:
        return {
            "format": BUILD_RESULT_FORMAT,
            "runner_protocol": BUILDER_RUNNER_PROTOCOL,
            "status": "failed",
            "pack": None,
            "attempt_log": list(attempt_log or []),
            "error": str(error),
        }

    check_frozen_build_request(request)
    if not callable(entrypoint_fn):
        return _failed(
            f"builder 入口不可调用({type(entrypoint_fn)!r});入口必须"
            f"是 builder package 内真实的函数定义")
    try:
        raw = entrypoint_fn(dict(request))
    except Exception as exc:  # noqa: BLE001 - builder 异常即 failed
        return _failed(
            f"builder 入口执行抛出 {type(exc).__name__}: {exc}")
    if raw is None:
        return _failed(
            "builder 入口返回 None(2.6.0g P2:入口必须真实构造 ExamPack"
            " 并返回规范化结果;None 不能与任何 pack 组合通过正式验证)")
    if not isinstance(raw, dict):
        return _failed(
            f"builder 入口返回类型 {type(raw)!r} 不是规范化结果 dict"
            f"(builder-build-result-v1:{{status, pack, attempt_log}})")
    unknown = sorted(set(raw) - {"format", "runner_protocol", "status",
                                 "pack", "attempt_log", "error"})
    if unknown:
        return _failed(
            f"builder 结果含未知字段 {unknown}(builder-build-result-v1)")
    status = raw.get("status")
    attempt_log = raw.get("attempt_log") or []
    if not isinstance(attempt_log, (list, tuple)):
        return _failed("builder 结果的 attempt_log 必须是 list")
    if status != "ok":
        return _failed(
            f"builder 自报失败 status={status!r}: "
            f"{str(raw.get('error'))[:300]}", attempt_log)
    if "pack" not in raw or raw.get("pack") is None:
        return _failed(
            "builder 结果缺少 pack(status=ok 但未携带实际构造的 "
            "ExamPack;EXAM_INVALID)", attempt_log)
    try:
        pack = _coerce_pack(raw.get("pack"))
    except BuilderProvenanceError as exc:
        return _failed(str(exc), attempt_log)
    except Exception as exc:  # noqa: BLE001 - 解析失败即 failed
        return _failed(f"builder 结果的 pack 解析失败: {exc}", attempt_log)
    try:
        pack_hash = pack.pack_hash()
    except Exception as exc:  # noqa: BLE001 - hash 不可算即 failed
        return _failed(f"builder 产物 pack_hash 无法计算: {exc}",
                       attempt_log)
    return {
        "format": BUILD_RESULT_FORMAT,
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "status": "ok",
        "pack": pack,
        "pack_hash": pack_hash,
        "attempt_log": list(attempt_log),
        "error": None,
    }


# ------------------------------------------------------------ 证明入口
def verify_builder_provenance(
    provider: Any, commitment: Any, *,
    pack: Any, duration_contract: dict[str, Any],
    allow_mock_pack_payload: bool = False,
) -> dict[str, Any]:
    """P1:builder 产物来源证明(在冻结输入下实际执行 builder)。

    验证链(fail closed,全部异常转为 BuilderProvenanceError):
    1. Provider 必须实现 builder_entrypoint() / frozen_build_request();
    2. 冻结请求哈希 nbr- 必须与 commitment.builder_build_request_hash
       一致(重放输入不可被替换);
    3. 实际执行 builder 入口(runner 协议 v1):None/异常/错误类型/
       无法解析的 pack 一律失败(P2);
    4. 重放产物的 pack_hash 必须等于 commitment.pack_hash——
       "Builder A 在冻结输入和运行环境下实际产生的 pack,正是
       commitment.pack_hash 所绑定的 pack"(阶段 2.6.0g 核心目标)。

    allow_mock_pack_payload 仅在公开 mock 通道为真(mock builder 是
    公开组装器,冻结构建输入含 pack 公开规范载荷);私有 builder 的
    请求携带 mock_pack_payload 时一律拒绝(重放不得照抄 pack 内容,
    必须真实构建)。

    返回非敏感证明报告(进入考试输出 evidence;不含隐藏 seed 与
    私有源码内容)。
    """
    try:
        entrypoint_fn = provider.builder_entrypoint()
        request = provider.frozen_build_request(
            pack, duration_contract)
    except Exception as exc:  # noqa: BLE001 - Provider 失败即 fail closed
        raise BuilderProvenanceError(
            f"Builder Provider 无法提供可执行入口/冻结构建请求: "
            f"{type(exc).__name__}: {exc}") from exc
    if "mock_pack_payload" in request and not allow_mock_pack_payload:
        raise BuilderProvenanceError(
            "私有 builder 的冻结构建请求携带了 mock_pack_payload"
            "(pack 规范重放载荷):私有通道的重放必须是真实构建,"
            "不得照抄 pack 内容;载荷只属于公开 mock 组装通道"
            "(EXAM_INVALID)")
    request_hash = frozen_build_request_hash(request)
    committed_hash = str(
        getattr(commitment, "builder_build_request_hash", "") or "")
    if committed_hash != request_hash:
        raise BuilderProvenanceError(
            f"冻结构建请求哈希与承诺不一致(现算 {request_hash} vs 承诺 "
            f"{committed_hash or '<缺失>'}):builder 重放的输入被替换"
            f"或承诺未绑定本 builder 的构建请求(EXAM_INVALID)")
    result = run_builder_entrypoint(entrypoint_fn, request)
    if result["status"] != "ok":
        raise BuilderProvenanceError(
            f"builder 重放失败(产物来源无法证明;EXAM_INVALID): "
            f"{result['error']}")
    replay_hash = str(result["pack_hash"])
    if replay_hash != str(commitment.pack_hash):
        raise BuilderProvenanceError(
            f"builder 重放产物 pack_hash 与承诺不一致(现算 {replay_hash}"
            f" vs 承诺 {commitment.pack_hash}):commitment 绑定的 pack "
            f"并非由本 builder 在冻结输入下实际生成(文件身份正确但"
            f"产物来源不成立;EXAM_INVALID)")
    return {
        "format": "builder-provenance-report-v1",
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "build_request_hash": request_hash,
        "replay_mode": ("mock_payload_assembly"
                        if "mock_pack_payload" in request
                        else "builder_execution"),
        "replay_pack_hash": replay_hash,
        "committed_pack_hash": str(commitment.pack_hash),
        "pack_hash_match": True,
        "attempt_log_entries": len(result["attempt_log"]),
        "status": "ok",
    }
