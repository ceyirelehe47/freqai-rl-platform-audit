"""Builder Runner 调用协议与产物来源证明(阶段 2.6.0g 收尾重写:v2)。

v1(提前提交的中间版本)遗留缺陷:

- 私有 Builder 在主评估进程内受控 import 并直接调用
  ``entrypoint_fn(request)``——私有模块顶层代码进入评估主进程,
  没有进程隔离、staging TOCTOU 防护、资源限制或 Candidate 不可见
  证明(工作包 B);
- build 入口签名只检查"存在位置参数"且显式放行 ``*args``(C1);
- 冻结构建请求用候选字段黑名单而非精确字段白名单,任意未注册
  扩展字段与文件路径值可进入请求(D1);
- mock 与 private 两种通道只靠 isinstance(provider,
  MockBuilderIdentityProvider) 区分,未在承诺中绑定 mode(D2);
- attempt log 只记录条目数量,无规范化合同与哈希绑定(D4);
- 不存在 Builder Run Evidence、precommit 双重运行与考试期第三次
  重放对账(工作包 E);
- 外部依赖只有 AST 静态闭包与配置自报,没有运行时实际 import 审计
  (工作包 G)。

v2 语义:

- builder-runner-protocol-v2:私有 Builder 一律在隔离 Runner 进程
  (rl_builder_runtime)内执行;主评估进程只允许读取并哈希 Builder
  文件、AST 静态检查、创建 Runner、发送规范化 request、接收规范化
  result(B1);
- builder-build-request-v2:精确字段集合(mode 驱动;未知字段/任意
  文件路径值/候选相关字段一律拒绝)+ 黑名单深度防御(D1);
- builder-run-mode:builder_execution(私有真实构建,唯一允许进入
  正式 hidden pack 的模式)| mock_payload_assembly(公开基础设施
  组装,独立协议);mode 进入冻结构建请求与 Builder Run Evidence,
  由 Provider 派生并被 manifest 绑定,不再依赖 isinstance(D2);
- builder-build-result-v2:精确字段集合,缺 format/错 protocol/
  未知字段/伪造 status 一律失败(D3);
- builder-attempt-log-v1:规范化 attempt 合同(attempt 序号、最大
  attempt、每次结果、匿名拒绝原因、最终选中 attempt、输出 pack
  hash),canonical hash(nal-)进入 evidence(D4);
- verify_builder_provenance:读取完整 Builder Run Evidence 重算
  哈希逐项验证 + 考试期第三次重放(隔离 Runner)三组 hash 对账
  (pack/attempt log/runtime lock)与 commitment.pack_hash 对账(E3/E4)。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Builder Runner 调用协议(build 入口适配与结果合同)
BUILDER_RUNNER_PROTOCOL = "builder-runner-protocol-v2"
#: 冻结构建请求格式(精确字段集合)
BUILD_REQUEST_FORMAT = "builder-build-request-v2"
#: 规范化构建结果格式(精确字段集合)
BUILD_RESULT_FORMAT = "builder-build-result-v2"
#: 规范化 attempt log 格式(D4)
ATTEMPT_LOG_FORMAT = "builder-attempt-log-v1"
#: 运行时依赖锁格式(G2)
RUNTIME_LOCK_FORMAT = "builder-runtime-lock-v1"

#: 构建运行模式(D2:mock 与 private 是承诺中明确绑定的两种不同 mode;
#: 正式 private hidden pack 必须拒绝 mock mode)
BUILDER_RUN_MODE_EXECUTION = "builder_execution"
BUILDER_RUN_MODE_MOCK_ASSEMBLY = "mock_payload_assembly"
BUILDER_RUN_MODES = (
    BUILDER_RUN_MODE_EXECUTION, BUILDER_RUN_MODE_MOCK_ASSEMBLY)

#: 私有冻结构建请求的精确字段集合(D1:只允许预注册字段)
PRIVATE_REQUEST_FIELDS: tuple[str, ...] = (
    "format", "runner_protocol", "mode", "builder_protocol",
    "builder_manifest_hash", "pack_name", "pack_version", "pack_timeframe",
    "families", "pair_count_per_family", "max_attempts", "params_spec",
    "timeframe", "resolved_bars", "resolved_duration_hours",
    "duration_contract_hash",
)
#: mock 组装通道的请求在私有字段之外额外允许 mock pack 规范载荷
#: (mock builder 是公开验证基础设施的"组装器";载荷只属于本通道)
MOCK_REQUEST_EXTRA_FIELDS = ("mock_pack_payload",)

#: 冻结构建请求禁止字段(候选相关性黑名单,深度防御;白名单之外
#: 的未知字段本来就被拒绝,黑名单拦截白名单内字段的候选相关取值名)
BUILD_REQUEST_FORBIDDEN_FIELDS = (
    "candidate", "checkpoint", "model", "policy", "score", "scores",
    "verdict", "outcome", "ranking", "result", "prediction",
)

#: build result v2 的精确字段集合(D3)
RESULT_FIELDS: tuple[str, ...] = (
    "format", "runner_protocol", "status", "pack", "attempt_log", "error",
)


class BuilderProvenanceError(RuntimeError):
    """产物来源证明失败(fail closed -> EXAM_INVALID)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ 冻结请求
def _scan_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
    """递归收集出现在任何层级的禁止键名(含 list 内 dict)。"""
    hits: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            key = str(k)
            if any(key == f or key.startswith(f + "_")
                   for f in BUILD_REQUEST_FORBIDDEN_FIELDS):
                hits.append(f"{prefix}.{key}" if prefix else key)
            hits.extend(_scan_forbidden_fields(
                v, f"{prefix}.{key}" if prefix else key))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            hits.extend(_scan_forbidden_fields(item, f"{prefix}[{i}]"))
    return hits


def _scan_path_values(value: Any, prefix: str = "") -> list[str]:
    """递归收集路径样式字符串值(D1:请求不得携带任意文件路径)。

    路径样式 = 只由路径安全字符组成且包含 "/"(绝对路径或
    a/b/c 形态;普通描述文本含中文/分号等自然不会命中,避免误伤
    pack notes 等合法文本)。
    """
    import re

    hits: list[str] = []
    if isinstance(value, dict):
        for k, v in value.items():
            hits.extend(_scan_path_values(
                v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            hits.extend(_scan_path_values(item, f"{prefix}[{i}]"))
    elif isinstance(value, str) and "/" in value and re.fullmatch(
            r"[A-Za-z0-9._~\-/]+", value):
        hits.append(f"{prefix}={value[:80]}")
    return hits


def check_frozen_build_request(request: Any) -> None:
    """冻结构建请求的精确字段校验(fail closed;D1)。

    - 必须是 dict,format/runner_protocol/mode 必须精确匹配;
    - 字段集合必须是 mode 对应白名单的**精确集合**(多一个字段、
      少一个字段均拒绝;不再只用候选字段黑名单);
    - 必填字段非空;
    - 递归黑名单(候选相关键名)与递归路径值扫描(字符串值不得
      包含 "/",请求不得携带任何文件路径)。
    """
    if not isinstance(request, dict):
        raise BuilderProvenanceError(
            f"冻结构建请求必须是 dict(收到 {type(request).__name__};"
            f"{BUILD_REQUEST_FORMAT})")
    if request.get("format") != BUILD_REQUEST_FORMAT:
        raise BuilderProvenanceError(
            f"冻结构建请求格式必须是 {BUILD_REQUEST_FORMAT!r}"
            f"(收到 {request.get('format')!r})")
    if request.get("runner_protocol") != BUILDER_RUNNER_PROTOCOL:
        raise BuilderProvenanceError(
            f"冻结构建请求的 runner 协议必须是 "
            f"{BUILDER_RUNNER_PROTOCOL!r}(收到 "
            f"{request.get('runner_protocol')!r})")
    mode = request.get("mode")
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        allowed = set(PRIVATE_REQUEST_FIELDS) | set(
            MOCK_REQUEST_EXTRA_FIELDS)
    elif mode == BUILDER_RUN_MODE_EXECUTION:
        allowed = set(PRIVATE_REQUEST_FIELDS)
    else:
        raise BuilderProvenanceError(
            f"冻结构建请求的 mode 必须是 {BUILDER_RUN_MODES} 之一"
            f"(收到 {mode!r};mock 与 private 是承诺中明确绑定的两种"
            f"不同通道,D2)")
    actual = set(request)
    unknown = sorted(actual - allowed)
    missing = sorted(allowed - actual)
    if unknown:
        raise BuilderProvenanceError(
            f"冻结构建请求含未注册字段 {unknown}:请求只能包含预注册"
            f"字段集合(白名单;未知扩展字段 fail closed)")
    if missing:
        raise BuilderProvenanceError(
            f"冻结构建请求缺少必填字段 {missing}(字段集合必须与 mode "
            f"白名单精确一致)")
    required_nonempty = ("builder_manifest_hash", "families",
                         "pair_count_per_family", "max_attempts",
                         "timeframe", "resolved_bars",
                         "duration_contract_hash")
    empty = [f for f in required_nonempty
             if request.get(f) in (None, "", [], {}, 0)]
    if empty:
        raise BuilderProvenanceError(
            f"冻结构建请求必填字段为空 {empty}(builder 重放的冻结输入"
            f"不完整;EXAM_INVALID)")
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY and not isinstance(
            request.get("mock_pack_payload"), dict):
        raise BuilderProvenanceError(
            "mock_payload_assembly 请求必须携带 mock_pack_payload"
            "(dict;mode 与载荷必须自洽)")
    hits = _scan_forbidden_fields(request)
    if hits:
        raise BuilderProvenanceError(
            f"冻结构建请求包含禁止字段 {sorted(set(hits))}:构建请求"
            f"不得包含候选 checkpoint/model/policy/成绩或任何候选输出"
            f"(fail closed;EXAM_INVALID)")
    paths = _scan_path_values(request)
    if paths:
        raise BuilderProvenanceError(
            f"冻结构建请求携带路径值 {paths[:5]}:请求不得包含任何"
            f"文件路径(私有 builder 的输入只有冻结参数,不是文件引用;"
            f"D1 fail closed)")


def build_frozen_build_request(
    identity: Any, *,
    pack: Any, duration_contract: dict[str, Any],
    mode: str,
    include_mock_pack_payload: bool = False,
) -> dict[str, Any]:
    """从 Builder identity + 考试 pack + 全局时长合同派生冻结构建请求。

    mode 必须显式给定(D2:mock 与 private 是承诺中明确绑定的两种
    不同通道):builder_execution(私有真实构建)或
    mock_payload_assembly(公开组装)。请求内容 = builder 身份
    (npb-/协议/params_spec/families/pair 数/attempt 上限)+ pack 公开
    自由度(name/version/timeframe)+ duration contract 的
    timeframe/resolved_bars/ndc-。隐藏 seed 不进请求(私有 builder
    从自身冻结的 seed namespace 重放)。

    include_mock_pack_payload 仅在 mock_payload_assembly 模式合法:
    mock builder 是公开验证基础设施的"组装器",其冻结构建输入就是
    pack 的公开规范(ExamPack 规范化 JSON)——确定性重组装。私有
    builder 的请求**永不携带**该载荷(重放必须是真实构建)。
    """
    from rl_curriculum.null_duration_contract import (
        null_duration_contract_hash as _ndc_hash,
    )

    if mode not in BUILDER_RUN_MODES:
        raise BuilderProvenanceError(
            f"构建请求 mode 必须是 {BUILDER_RUN_MODES} 之一(收到 "
            f"{mode!r})")
    if include_mock_pack_payload and mode != BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        raise BuilderProvenanceError(
            "mock_pack_payload 只属于 mock_payload_assembly 通道:"
            "builder_execution(私有真实构建)的请求携带 pack 规范载荷"
            "即拒绝(重放不得照抄 pack 内容;D2 硬闸)")
    manifest = identity.manifest or {}
    request = {
        "format": BUILD_REQUEST_FORMAT,
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "mode": str(mode),
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
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        if not include_mock_pack_payload:
            raise BuilderProvenanceError(
                "mock_payload_assembly 请求必须包含 mock_pack_payload"
                "(mode 与载荷必须自洽)")
        request["mock_pack_payload"] = json.loads(pack.to_json())
    check_frozen_build_request(request)
    return request


def frozen_build_request_hash(request: dict[str, Any]) -> str:
    """冻结构建请求哈希(nbr-;canonical JSON,排序稳定)。"""
    check_frozen_build_request(request)
    return "nbr-" + _canonical_json_hash(request)


# ------------------------------------------------- attempt log 合同(D4)
ATTEMPT_ENTRY_FIELDS = frozenset({"attempt", "verdict", "reject_reasons"})


def check_attempt_log(log: Any, *, max_attempts: int | None = None) -> None:
    """规范化 attempt log 的结构合同(值级 fail closed)。

    合同字段:format / max_attempts / attempts[{attempt, verdict,
    reject_reasons}] / selected_attempt / output_pack_hash。组装模式
    (max_attempts=0)不得携带 attempt 条目;selected_attempt 必须
    指向一个 verdict=accept 的条目。
    """
    if not isinstance(log, dict):
        raise BuilderProvenanceError(
            f"attempt_log 必须是规范化 dict(收到 {type(log).__name__})")
    if set(log) != {"format", "max_attempts", "attempts",
                    "selected_attempt", "output_pack_hash"}:
        raise BuilderProvenanceError(
            "attempt_log 字段集合必须恰好是 [format, max_attempts, "
            "attempts, selected_attempt, output_pack_hash]")
    if log.get("format") != ATTEMPT_LOG_FORMAT:
        raise BuilderProvenanceError(
            f"attempt_log.format 必须是 {ATTEMPT_LOG_FORMAT!r}(收到 "
            f"{log.get('format')!r})")
    ma = log.get("max_attempts")
    if not isinstance(ma, int) or isinstance(ma, bool) or ma < 0:
        raise BuilderProvenanceError("attempt_log.max_attempts 必须是非负 int")
    if max_attempts is not None and ma != int(max_attempts):
        raise BuilderProvenanceError(
            f"attempt_log.max_attempts({ma})与冻结请求的 "
            f"max_attempts({max_attempts})不一致(attempt 上限不得漂移)")
    attempts = log.get("attempts")
    if not isinstance(attempts, list):
        raise BuilderProvenanceError("attempt_log.attempts 必须是 list")
    for entry in attempts:
        if not isinstance(entry, dict) or set(entry) != ATTEMPT_ENTRY_FIELDS:
            raise BuilderProvenanceError(
                f"attempt 条目字段必须恰好是 {sorted(ATTEMPT_ENTRY_FIELDS)}")
        if not isinstance(entry.get("attempt"), int) \
                or isinstance(entry.get("attempt"), bool) \
                or entry.get("attempt") < 0:
            raise BuilderProvenanceError("attempt 条目的 attempt 必须是非负 int")
        if entry.get("verdict") not in ("accept", "reject"):
            raise BuilderProvenanceError(
                f"attempt 条目的 verdict 必须是 accept|reject(收到 "
                f"{entry.get('verdict')!r})")
        reasons = entry.get("reject_reasons")
        if not isinstance(reasons, list) or \
                not all(isinstance(r, str) for r in reasons):
            raise BuilderProvenanceError(
                "attempt 条目的 reject_reasons 必须是字符串列表(匿名"
                "拒绝原因)")
        if entry.get("verdict") == "accept" and reasons:
            raise BuilderProvenanceError(
                "accept 条目不得携带拒绝原因(不自洽)")
        if entry.get("verdict") == "reject" and not reasons:
            raise BuilderProvenanceError(
                "reject 条目必须携带匿名拒绝原因(不得只记条目数量)")
    if ma == 0 and attempts:
        raise BuilderProvenanceError(
            "max_attempts=0(组装模式)不得携带 attempt 条目")
    if ma > 0 and len(attempts) > ma:
        raise BuilderProvenanceError(
            f"attempt 条目数({len(attempts)})超过 max_attempts({ma})")
    sel = log.get("selected_attempt")
    if ma == 0:
        if sel is not None:
            raise BuilderProvenanceError(
                "组装模式 selected_attempt 必须为 null")
    elif sel is None:
        raise BuilderProvenanceError(
            "构建模式必须选定最终 attempt(selected_attempt 不得为空)")
    elif not any(e.get("attempt") == sel and e.get("verdict") == "accept"
                 for e in attempts):
        raise BuilderProvenanceError(
            "selected_attempt 必须指向一个 verdict=accept 的条目")


def canonicalize_attempt_log(
    raw_log: Any, *, output_pack_hash: str,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """把 Runner/builder 侧的 attempt log 规范化为完整合同对象。

    Runner 侧结构校验通过后,主进程补 output_pack_hash(pack 解析与
    哈希只发生在主进程)并强制全部值级合同。
    """
    if not isinstance(raw_log, dict):
        raise BuilderProvenanceError(
            f"attempt_log 必须是 dict(收到 {type(raw_log).__name__})")
    log = {
        "format": ATTEMPT_LOG_FORMAT,
        "max_attempts": raw_log.get("max_attempts"),
        "attempts": [
            {
                "attempt": int(e["attempt"]),
                "verdict": str(e["verdict"]),
                "reject_reasons": [str(r) for r in (e.get("reject_reasons")
                                                    or [])],
            }
            for e in (raw_log.get("attempts") or [])
        ],
        "selected_attempt": raw_log.get("selected_attempt"),
        "output_pack_hash": str(output_pack_hash),
    }
    check_attempt_log(log, max_attempts=max_attempts)
    return log


def attempt_log_hash(log: dict[str, Any]) -> str:
    """规范化 attempt log 的 canonical hash(nal-;进入 evidence)。"""
    check_attempt_log(log)
    return "nal-" + _canonical_json_hash(log)


def runtime_lock_hash(lock: dict[str, Any]) -> str:
    """运行时依赖锁的 canonical hash(nrl-;进入 evidence)。

    lock 由隔离 Runner 的实际 import 审计派生(G2),不是配置自报。
    """
    if not isinstance(lock, dict) or lock.get(
            "format") != RUNTIME_LOCK_FORMAT:
        raise BuilderProvenanceError(
            f"运行时依赖锁必须是 {RUNTIME_LOCK_FORMAT!r} dict(收到 "
            f"{type(lock).__name__})")
    return "nrl-" + _canonical_json_hash(lock)


# ------------------------------------------------- 静态预检对账(G1/G3)
def check_runtime_lock_against_static(
    lock: dict[str, Any], static_dependencies: list[dict[str, Any]],
) -> None:
    """实际运行时锁与静态闭包预检的对账(G3)。

    config/manifest 中的 external_dependencies 只是静态 AST 闭包
    (预检与 allowlist 候选),不是正式依赖身份来源;实际身份必须由
    Runner 的 import 审计重新派生。对账规则(fail closed):
    - 运行时实际加载的每个第三方模块必须在静态 allowlist 中
      (动态/条件/插件式 import 的新依赖被拒绝);
    - allowlist 允许比实际运行宽(函数级 import 未触发属正常);
    - 版本不一致拒绝;<missing:...> 静态记录不得出现在对账通过的
      位置(缺失即 fail closed)。
    """
    if not isinstance(lock, dict) or lock.get(
            "format") != RUNTIME_LOCK_FORMAT:
        raise BuilderProvenanceError(
            "运行时依赖锁格式无效(必须是 Runner 派生的 "
            f"{RUNTIME_LOCK_FORMAT!r})")
    static_versions: dict[str, str] = {}
    for dep in static_dependencies or []:
        if not isinstance(dep, dict):
            continue
        module = str(dep.get("module") or "")
        version = str(dep.get("version") or "")
        if module and version:
            static_versions[module] = version
    actual = {e["module"]: str(e["version"])
              for e in lock.get("distributions") or []}
    for module, version in sorted(actual.items()):
        if version.startswith("<missing"):
            raise BuilderProvenanceError(
                f"运行时锁包含缺失依赖 {module!r}({version}):"
                f"<missing:package> 不是合法正式依赖记录(fail closed)")
        if module not in static_versions:
            raise BuilderProvenanceError(
                f"Builder 运行时实际加载了未注册第三方依赖 {module!r}"
                f"(动态/条件/插件式 import 的新依赖必须 fail closed;"
                f"静态闭包只是预检,实际锁由 Runner 重新派生)")
        if static_versions[module].startswith("<missing"):
            raise BuilderProvenanceError(
                f"静态预检对 {module!r} 的记录是 <missing>:package>"
                f"(无法验证的依赖身份,正式路径拒绝)")
        if static_versions[module] != version:
            raise BuilderProvenanceError(
                f"依赖 {module!r} 运行时版本({version})与静态预检"
                f"({static_versions[module]})不一致(依赖环境漂移,"
                f"fail closed)")


# ------------------------------------------------------------ mock 组装
def run_mock_assembly(request: dict[str, Any]) -> dict[str, Any]:
    """mock_payload_assembly 通道的确定性重组装(公开代码,主进程)。

    mock builder 是公开验证基础设施的组装器(rl_curriculum 内公开
    源码,manifest v4 绑定):按请求携带的 mock_pack_payload 确定性
    重建 ExamPack。本函数真实执行公开 mock 入口
    (mock_build_pack,manifest 绑定的 entrypoint)并对其结果做 v2
    合同校验,返回规范化 run record(与隔离 Runner 的 run record
    同构,mode 标注 mock_payload_assembly)。

    本函数只服务公开 mock 通道;私有 builder 的重放必须走隔离 Runner
    (verify_builder_provenance 按 mode 分派,不存在跨通道回退)。
    """
    import time

    from rl_curriculum import mock_sealed_exam
    from rl_curriculum.exam_pack import ExamPack

    check_frozen_build_request(request)
    if request.get("mode") != BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        raise BuilderProvenanceError(
            "run_mock_assembly 只接受 mock_payload_assembly 请求"
            "(builder_execution 请求必须经隔离 Runner 真实构建;不存在"
            "主进程执行私有 Builder 的通道)")
    started = time.monotonic()
    try:
        raw = mock_sealed_exam.mock_build_pack(dict(request))
    except Exception as exc:  # noqa: BLE001 - 组装异常即 failed
        raise BuilderProvenanceError(
            f"mock 组装入口执行失败: {type(exc).__name__}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BuilderProvenanceError(
            f"mock 组装入口返回类型 {type(raw).__name__} 不是 dict")
    unknown = sorted(set(raw) - set(RESULT_FIELDS))
    if unknown:
        raise BuilderProvenanceError(
            f"mock 组装结果含未知字段 {unknown}(builder-build-result-v2)")
    if raw.get("format") != BUILD_RESULT_FORMAT:
        raise BuilderProvenanceError(
            f"mock 组装结果 format 必须是 {BUILD_RESULT_FORMAT!r}"
            f"(收到 {raw.get('format')!r})")
    if raw.get("runner_protocol") != BUILDER_RUNNER_PROTOCOL:
        raise BuilderProvenanceError(
            f"mock 组装结果 runner 协议必须是 "
            f"{BUILDER_RUNNER_PROTOCOL!r}(收到 "
            f"{raw.get('runner_protocol')!r})")
    if raw.get("status") != "ok":
        raise BuilderProvenanceError(
            f"mock 组装自报失败: {str(raw.get('error'))[:300]}")
    try:
        pack = ExamPack.from_json(json.dumps(raw.get("pack")))
        pack_hash = pack.pack_hash()
    except Exception as exc:  # noqa: BLE001 - 解析失败即 failed
        raise BuilderProvenanceError(
            f"mock 组装产物无法解析为 ExamPack: "
            f"{type(exc).__name__}: {exc}") from exc
    log = canonicalize_attempt_log(
        raw.get("attempt_log"), output_pack_hash=pack_hash)
    # mock 组装通道的"运行时锁":确定性伪锁(主进程公开组装,无第三方
    # import 面);与私有 Runner 的真实锁区分(mode 绑定)
    lock = {
        "format": RUNTIME_LOCK_FORMAT,
        "python_implementation": "mock-payload-assembly",
        "python_version": "0",
        "executable_prefix": "mock-payload-assembly",
        "distributions": [],
    }
    from rl_curriculum.sealed_exam import module_code_hash

    return {
        "mode": BUILDER_RUN_MODE_MOCK_ASSEMBLY,
        "status": "ok",
        "pack": pack,
        "pack_hash": pack_hash,
        "attempt_log": log,
        "runtime_lock": lock,
        "runner_code_hash": module_code_hash(mock_sealed_exam),
        "sandbox_profile_hash": _mock_assembly_profile_hash(),
        "access_summary": {"open_count": 0, "outside_allowlist": []},
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "error": None,
    }


def _mock_assembly_profile_hash() -> str:
    """mock 组装通道的确定性 profile 身份(brp-;主进程公开组装)。"""
    payload = {"format": "mock-assembly-profile-v1",
               "execution": "in_process_public_assembly"}
    return "brp-" + _canonical_json_hash(payload)


# ------------------------------------------------------------ 证明入口
def verify_builder_provenance(
    provider: Any, commitment: Any, *,
    pack: Any, duration_contract: dict[str, Any],
    builder_evidence: dict[str, Any] | None = None,
    builder_root: Path | str | None = None,
) -> dict[str, Any]:
    """builder 产物来源证明(考试期第三次重放;E3/E4)。

    验证链(fail closed,全部异常转为 BuilderProvenanceError):
    1. Provider 必须实现 builder_identity() / frozen_build_request() /
       builder_run_mode()(D2:mode 由 Provider 派生并被 manifest 绑定,
       不再依赖 isinstance 判定 payload 许可);
    2. mode 硬闸:builder_execution 请求携带 mock_pack_payload 一律
       拒绝;mock_payload_assembly 请求必须携带载荷;正式 hidden pack
       的 evidence.mode 必须与请求 mode 一致;
    3. 冻结请求哈希 nbr- 必须与 commitment.builder_build_request_hash
       一致(重放输入不可被替换);
    4. 读取完整 Builder Run Evidence 并逐项验证(E4:重算 bre- 与
       承诺摘要对账;precommit 双跑三组 hash 一致;runner code/
       sandbox profile/staged tree/runtime lock 全部绑定);
    5. 第三次重放:
       - builder_execution:启动全新隔离 Runner(私有 Builder 不在
         主评估进程 import 或执行),三组 hash(pack/attempt log/
         runtime lock)必须与 precommit run1 == run2 == 本次完全一致,
         且 pack_hash == commitment.pack_hash;
       - mock_payload_assembly:主进程确定性重组装(公开代码),同构
         对账;
    6. 实际运行时锁与静态闭包预检对账(G3:未注册/版本漂移拒绝)。

    返回非敏感证明报告(进入考试输出 evidence;不含隐藏 seed 与
    私有源码内容)。
    """
    from pathlib import Path as _P

    try:
        identity = provider.builder_identity()
        provider_mode = str(provider.builder_run_mode())
        request = provider.frozen_build_request(
            pack, duration_contract)
    except Exception as exc:  # noqa: BLE001 - Provider 失败即 fail closed
        raise BuilderProvenanceError(
            f"Builder Provider 无法提供身份/运行模式/冻结构建请求: "
            f"{type(exc).__name__}: {exc}") from exc
    if provider_mode not in BUILDER_RUN_MODES:
        raise BuilderProvenanceError(
            f"Provider 声明的运行模式 {provider_mode!r} 不在预注册范围 "
            f"{BUILDER_RUN_MODES}")
    check_frozen_build_request(request)
    mode = str(request.get("mode"))
    if mode != provider_mode:
        raise BuilderProvenanceError(
            f"冻结构建请求 mode({mode!r})与 Provider 运行模式"
            f"({provider_mode!r})不一致(mode 必须由 Provider 派生并被"
            f"manifest 绑定;D2)")
    if mode == BUILDER_RUN_MODE_EXECUTION and \
            "mock_pack_payload" in request:
        raise BuilderProvenanceError(
            "私有 builder 的冻结构建请求携带了 mock_pack_payload"
            "(pack 规范重放载荷):builder_execution 通道的重放必须是"
            "真实构建,不得照抄 pack 内容;载荷只属于公开 mock 组装通道"
            "(D2 硬闸;EXAM_INVALID)")
    request_hash = frozen_build_request_hash(request)
    committed_hash = str(
        getattr(commitment, "builder_build_request_hash", "") or "")
    if committed_hash != request_hash:
        raise BuilderProvenanceError(
            f"冻结构建请求哈希与承诺不一致(现算 {request_hash} vs 承诺 "
            f"{committed_hash or '<缺失>'}):builder 重放的输入被替换"
            f"或承诺未绑定本 builder 的构建请求(EXAM_INVALID)")
    # ---- E4:完整 Builder Run Evidence 逐项验证 + 第三次重放
    from rl_curriculum.builder_evidence import (
        replay_builder_for_evidence,
        verify_builder_run_evidence,
    )

    if builder_evidence is None:
        raise BuilderProvenanceError(
            "缺少 Builder Run Evidence(v8 承诺必须绑定 builder_run_"
            "evidence;完整 evidence 由评估方私有目录提供,执行器读取、"
            "重算 hash 并逐项验证——不能只信任 deterministic 布尔值;"
            "EXAM_INVALID)")
    verify_builder_run_evidence(
        builder_evidence, commitment=commitment, identity=identity,
        request_hash=request_hash)
    replay = replay_builder_for_evidence(
        provider, request=request, builder_evidence=builder_evidence,
        builder_root=builder_root if builder_root is not None
        else getattr(provider, "root", None))
    replay_pack_hash = str(replay["pack_hash"])
    if replay_pack_hash != str(commitment.pack_hash):
        raise BuilderProvenanceError(
            f"builder 重放产物 pack_hash 与承诺不一致(现算 "
            f"{replay_pack_hash} vs 承诺 {commitment.pack_hash}):"
            f"commitment 绑定的 pack 并非由本 builder 在冻结输入下"
            f"实际生成(产物来源不成立;EXAM_INVALID)")
    if replay_pack_hash != str(
            builder_evidence.get("output_pack_hash") or ""):
        raise BuilderProvenanceError(
            "考试期第三次重放 pack_hash 与 evidence 记录的 precommit "
            "pack_hash 不一致(Builder 不确定;EXAM_INVALID)")
    # G3:实际运行时锁与静态闭包预检对账
    static_deps = list(
        (identity.manifest or {}).get("external_dependencies") or [])
    check_runtime_lock_against_static(replay["runtime_lock"], static_deps)
    return {
        "format": "builder-provenance-report-v2",
        "runner_protocol": BUILDER_RUNNER_PROTOCOL,
        "build_request_hash": request_hash,
        "mode": mode,
        "evidence_hash": str(
            builder_evidence.get("evidence_hash") or ""),
        "replay_pack_hash": replay_pack_hash,
        "committed_pack_hash": str(commitment.pack_hash),
        "replay_attempt_log_hash": attempt_log_hash(
            replay["attempt_log"]),
        "replay_runtime_lock_hash": runtime_lock_hash(
            replay["runtime_lock"]),
        "runner_code_hash": str(replay["runner_code_hash"]),
        "sandbox_profile_hash": str(replay["sandbox_profile_hash"]),
        "replay_isolated_process": bool(
            mode == BUILDER_RUN_MODE_EXECUTION),
        "pack_hash_match": True,
        "status": "ok",
    }
