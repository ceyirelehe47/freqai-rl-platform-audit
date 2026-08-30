"""Builder Runner 调用协议与产物来源证明(阶段 2.6.0h:v3)。

v3 语义(在 0g v2 之上,本阶段修复):
- builder-runner-protocol-v3 / builder-build-request-v3 /
  builder-build-result-v3:请求新增 attempt_policy 字段(E1:
  first_pass 选择策略显式进入冻结请求/manifest/evidence/承诺);
- builder-attempt-log-v2:first_pass 硬约束——编号从 0 起严格连续
  唯一、选中之前全 reject、选中是第一个且唯一 accept、选中之后
  无条目、没有 accept 的构建必须失败不得产出 pack(E2);
- builder-runtime-lock-v2:进程树策略字段(single_builder_process
  / child_process_count / exec_count,D1)+ distribution 实际内容
  摘要(dcd-,D2:RECORD 逐文件重算实际哈希,修改 package 文件但
  保持 RECORD 不变的篡改被发现)+ native library 内容绑定(D3);
- access summary v2(acs-):事件覆盖(open/listdir/scandir/
  subprocess/os.system/dlopen)与子进程/exec 尝试计数进入 evidence
  核心(F);
- verify_builder_provenance:重放后对账 Effective Sandbox Report
  哈希(ebx-/esb-)、access summary、进程树状态与 isolated_process
  身份(C2/D1/F)。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

#: Builder Runner 调用协议(build 入口适配与结果合同)
BUILDER_RUNNER_PROTOCOL = "builder-runner-protocol-v3"
#: 冻结构建请求格式(精确字段集合)
BUILD_REQUEST_FORMAT = "builder-build-request-v3"
#: 规范化构建结果格式(精确字段集合)
BUILD_RESULT_FORMAT = "builder-build-result-v3"
#: 规范化 attempt log 格式(D4/E2)
ATTEMPT_LOG_FORMAT = "builder-attempt-log-v2"
#: 运行时依赖锁格式(2.6.0j:v4 = 0i v3 密闭输入闭包 + 不可逆密封
#: 计算边界:final filter 哈希/MDWE/fd 隔离/顶层纯度/Compute 后实测)
RUNTIME_LOCK_FORMAT = "builder-runtime-lock-v4"
#: 访问摘要格式(F)
ACCESS_SUMMARY_FORMAT = "builder-access-summary-v2"

#: 进程树策略(D1)
PROCESS_TREE_SINGLE = "single_builder_process"
PROCESS_TREE_PUBLIC_ASSEMBLY = "in_process_public_assembly"

#: 构建运行模式(D2)
BUILDER_RUN_MODE_EXECUTION = "builder_execution"
BUILDER_RUN_MODE_MOCK_ASSEMBLY = "mock_payload_assembly"
BUILDER_RUN_MODES = (
    BUILDER_RUN_MODE_EXECUTION, BUILDER_RUN_MODE_MOCK_ASSEMBLY)

#: 私有冻结构建请求的精确字段集合(D1 + E1:attempt_policy)
PRIVATE_REQUEST_FIELDS: tuple[str, ...] = (
    "format", "runner_protocol", "mode", "builder_protocol",
    "builder_manifest_hash", "pack_name", "pack_version", "pack_timeframe",
    "families", "pair_count_per_family", "max_attempts", "params_spec",
    "attempt_policy",
    "timeframe", "resolved_bars", "resolved_duration_hours",
    "duration_contract_hash",
)
MOCK_REQUEST_EXTRA_FIELDS = ("mock_pack_payload",)

BUILD_REQUEST_FORBIDDEN_FIELDS = (
    "candidate", "checkpoint", "model", "policy", "score", "scores",
    "verdict", "outcome", "ranking", "result", "prediction",
)

#: build result v3 的精确字段集合(D3)
RESULT_FIELDS: tuple[str, ...] = (
    "format", "runner_protocol", "status", "pack", "attempt_log", "error",
)

#: attempt 选择策略(E1:当前固定 first_pass;assembly 为公开组装通道)
ATTEMPT_SELECTION_POLICY = "first_pass"
ATTEMPT_POLICY_ASSEMBLY = "assembly"


class BuilderProvenanceError(RuntimeError):
    """产物来源证明失败(fail closed -> EXAM_INVALID)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------ 冻结请求
def _scan_forbidden_fields(value: Any, prefix: str = "") -> list[str]:
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


def _check_attempt_policy_field(policy: Any, *, mode: str,
                                max_attempts: int) -> None:
    """E1:请求 attempt_policy 的精确结构。"""
    if not isinstance(policy, dict):
        raise BuilderProvenanceError(
            f"冻结构建请求的 attempt_policy 必须是 dict(收到 "
            f"{type(policy).__name__})")
    if set(policy) != {"policy", "max_attempts"}:
        raise BuilderProvenanceError(
            "attempt_policy 字段集合必须恰好是 [policy, max_attempts]")
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        if policy.get("policy") != ATTEMPT_POLICY_ASSEMBLY:
            raise BuilderProvenanceError(
                f"attempt_policy.policy 必须是 "
                f"{ATTEMPT_POLICY_ASSEMBLY!r}(收到 "
                f"{policy.get('policy')!r})")
        if policy.get("max_attempts") != 0:
            raise BuilderProvenanceError(
                "assembly 通道 attempt_policy.max_attempts 必须为 0")
        return
    expected_policy = ATTEMPT_SELECTION_POLICY
    if policy.get("policy") != expected_policy:
        raise BuilderProvenanceError(
            f"attempt_policy.policy 必须是 {expected_policy!r}(收到 "
            f"{policy.get('policy')!r};attempt 选择策略必须预注册,E1)")
    ma = policy.get("max_attempts")
    if not isinstance(ma, int) or isinstance(ma, bool) or ma < 1:
        raise BuilderProvenanceError(
            "builder_execution 的 attempt_policy.max_attempts 必须是"
            " 正整数(没有 attempt 循环的私有构建不成立)")
    if ma != int(max_attempts):
        raise BuilderProvenanceError(
            f"attempt_policy.max_attempts({ma})与请求 max_attempts"
            f"({max_attempts})不一致(attempt 上限不得漂移)")


def check_frozen_build_request(request: Any) -> None:
    """冻结构建请求的精确字段校验(fail closed;D1 + E1)。"""
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
    _check_attempt_policy_field(
        request.get("attempt_policy"), mode=mode,
        max_attempts=int(request.get("max_attempts") or 0))
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY and not isinstance(
            request.get("mock_pack_payload"), dict):
        raise BuilderProvenanceError(
            "mock_payload_assembly 请求必须携带 mock_pack_payload"
            "(dict;mode 与载荷必须自洽)")
    # attempt_policy 的子结构已由 _check_attempt_policy_field 精确
    # 校验({policy, max_attempts});黑名单的候选相关键名(policy)
    # 不适用于 attempt 选择策略子键
    scan_target = {k: v for k, v in request.items()
                   if k != "attempt_policy"}
    hits = _scan_forbidden_fields(scan_target)
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

    attempt_policy(E1)从 identity manifest 派生(manifest v5 预注册
    attempt_policy;兼容无该字段的 identity 时按 mode 推导默认:
    execution -> first_pass/max_attempts,assembly -> assembly/0)。
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
    max_attempts = int(manifest.get("max_attempts") or 0)
    registered = dict(manifest.get("attempt_policy") or {})
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        policy = {"policy": ATTEMPT_POLICY_ASSEMBLY, "max_attempts": 0}
    elif registered:
        policy = {
            "policy": str(registered.get("policy")
                          or ATTEMPT_SELECTION_POLICY),
            "max_attempts": int(
                registered.get("max_attempts") or max_attempts),
        }
    else:
        policy = {"policy": ATTEMPT_SELECTION_POLICY,
                  "max_attempts": max_attempts}
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
        "max_attempts": max_attempts,
        "params_spec": dict(manifest.get("params_spec") or {}),
        "attempt_policy": policy,
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


# ------------------------------------------------- attempt log 合同(E2)
ATTEMPT_ENTRY_FIELDS = frozenset({"attempt", "verdict", "reject_reasons"})


def check_attempt_log(
    log: Any, *, max_attempts: int | None = None,
    attempt_policy: dict[str, Any] | None = None,
) -> None:
    """attempt log v2 合同:结构 + first_pass 选择规则(fail closed)。

    - 结构:字段集合精确、条目字段精确、verdict/reject_reasons
      自洽(accept 无原因/reject 必有匿名原因);
    - attempt_policy 绑定:log.max_attempts 必须等于策略上限;
    - first_pass:编号从 0 起严格连续唯一、每个 < max_attempts、
      选中之前全部 reject、选中条目是第一个且唯一 accept、选中之后
      不得有条目、selected_attempt 必须等于该 accept 编号;
    - assembly:max_attempts=0、无条目、无选中。
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
    policy = dict(attempt_policy or {})
    if not policy:
        policy = ({"policy": ATTEMPT_POLICY_ASSEMBLY, "max_attempts": 0}
                  if ma == 0 else
                  {"policy": ATTEMPT_SELECTION_POLICY, "max_attempts": ma})
    if ma != int(policy.get("max_attempts") or 0):
        raise BuilderProvenanceError(
            f"attempt_log.max_attempts({ma})与 attempt_policy 上限"
            f"({policy.get('max_attempts')})不一致")
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
    if str(policy.get("policy") or "") == ATTEMPT_POLICY_ASSEMBLY:
        if sel is not None:
            raise BuilderProvenanceError(
                "组装模式 selected_attempt 必须为 null")
        return
    # first_pass(E2)
    numbers = [e.get("attempt") for e in attempts]
    if numbers != list(range(len(attempts))):
        raise BuilderProvenanceError(
            f"first_pass 违规:attempt 编号必须从 0 开始且严格连续唯一"
            f"(收到 {numbers})")
    for n in numbers:
        if n >= ma:
            raise BuilderProvenanceError(
                f"first_pass 违规:attempt 编号 {n} 超出 max_attempts"
                f"={ma}")
    accepts = [i for i, e in enumerate(attempts)
               if e.get("verdict") == "accept"]
    if sel is None:
        if accepts:
            raise BuilderProvenanceError(
                "first_pass 违规:存在 accept 条目但未选中(没有 accept"
                " 的构建必须失败,不得产出 pack)")
        return
    if len(accepts) != 1:
        raise BuilderProvenanceError(
            f"first_pass 违规:必须恰好一个 accept(收到 {len(accepts)}"
            f" 个;不得在多个合格 pack 中后选)")
    if accepts[0] != sel:
        raise BuilderProvenanceError(
            "first_pass 违规:selected_attempt 必须指向第一个(且唯一)"
            " accept 条目(不得跳过更早的合格 attempt 选择后者)")
    for e in attempts[:accepts[0]]:
        if e.get("verdict") != "reject":
            raise BuilderProvenanceError(
                "first_pass 违规:选中条目之前必须全部是 reject")
    if len(attempts) != accepts[0] + 1:
        raise BuilderProvenanceError(
            "first_pass 违规:选中条目之后不得再有其他条目")


def canonicalize_attempt_log(
    raw_log: Any, *, output_pack_hash: str,
    max_attempts: int | None = None,
    attempt_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 Runner/builder 侧的 attempt log 规范化为完整合同对象。"""
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
    check_attempt_log(log, max_attempts=max_attempts,
                      attempt_policy=attempt_policy)
    return log


def attempt_log_hash(log: dict[str, Any]) -> str:
    """规范化 attempt log 的 canonical hash(nal-;进入 evidence)。"""
    check_attempt_log(log)
    return "nal-" + _canonical_json_hash(log)


def runtime_lock_hash(lock: dict[str, Any]) -> str:
    """运行时依赖锁 v3 的 canonical hash(nrl-;进入 evidence)。"""
    if not isinstance(lock, dict) or lock.get(
            "format") != RUNTIME_LOCK_FORMAT:
        raise BuilderProvenanceError(
            f"运行时依赖锁必须是 {RUNTIME_LOCK_FORMAT!r} dict(收到 "
            f"{type(lock).__name__}/{(lock or {}).get('format')!r};"
            f"2.6.0h 的 v2 锁不再被接受)")
    return "nrl-" + _canonical_json_hash(lock)


def access_summary_hash(access: dict[str, Any]) -> str:
    """访问摘要 v2 的 canonical hash(acs-;进入 evidence 核心)。"""
    if not isinstance(access, dict) or access.get(
            "format") != ACCESS_SUMMARY_FORMAT:
        access = dict(access or {})
        access["format"] = ACCESS_SUMMARY_FORMAT
    return "acs-" + _canonical_json_hash(access)


# ------------------------------------------------- 静态预检对账(G1/G3)
def check_runtime_lock_against_static(
    lock: dict[str, Any], static_dependencies: list[dict[str, Any]],
    *, require_single_process: bool = True,
    verify_content: bool = True,
) -> None:
    """实际运行时锁与静态闭包预检的对账(G3 + D1/D2;2.6.0i v3)。

    v3 语义(密闭输入闭包,替代 0h 的 dcd-/RECORD 通道):
    - 进程树:require_single_process 时 process_tree_policy 必须是
      single_builder_process 且 child_process_count==exec_count==0,
      thread_policy 必须是线程禁止且 quiesce 实测恰 1 任务,
      worker_pidns_pid 必须为 1;
    - runtime_bundle:必须绑定内容寻址 manifest 摘要(rbm-)与文件数
      (内容权威从 RECORD/dcd- 迁移到 bundle manifest);
    - clock/entropy 策略:vDSO 冻结 stub(或无 vDSO)+ 行为冻结
      (time==0/datetime 1970)+ raw syscall EPERM + getrandom EPERM
      + 确定性虚拟熵;
    - 导入闭包 import_closure:每条 file 条目必须绑定 bundle 内路径
      与字节 sha256;loader 白名单;bundle 外/多义归属由 Runner 侧
      fail closed(此处结构复核);
    - native library:必须携带 bundle 绑定条目(D3);
    - distribution:静态闭包对账(版本一致)且逐条绑定实际文件字节。
    """
    if not isinstance(lock, dict) or lock.get(
            "format") != RUNTIME_LOCK_FORMAT:
        raise BuilderProvenanceError(
            "运行时依赖锁格式无效(必须是 Runner 派生的 "
            f"{RUNTIME_LOCK_FORMAT!r};2.6.0h 的 v2 锁不再被接受)")
    if require_single_process:
        if lock.get("process_tree_policy") != PROCESS_TREE_SINGLE:
            raise BuilderProvenanceError(
                f"运行行锁的进程树策略必须是 {PROCESS_TREE_SINGLE!r}"
                f"(收到 {lock.get('process_tree_policy')!r};存在后代"
                f"进程的构建不被采信)")
        def _lock_int(v):
            return v if isinstance(v, int) and not isinstance(v, bool) \
                else -1
        if _lock_int(lock.get("child_process_count")) != 0 or \
                _lock_int(lock.get("exec_count")) != 0:
            raise BuilderProvenanceError(
                f"进程树违规:child={lock.get('child_process_count')},"
                f"exec={lock.get('exec_count')}(子进程 import 不进入"
                f"父 Runner 锁,唯一安全语义是零后代进程)")
        if str(lock.get("thread_policy") or "") != \
                "threads_forbidden_clone_denied":
            raise BuilderProvenanceError(
                "运行时锁缺少线程禁止策略(clone 全拒;2.6.0h 允许 "
                "CLONE_THREAD 的锁不再被接受)")
        thread_state = lock.get("thread_state") or {}
        if _lock_int(thread_state.get("thread_count_at_quiesce")) != 1:
            raise BuilderProvenanceError(
                f"线程静止实测失败:quiesce 任务数 "
                f"{thread_state.get('thread_count_at_quiesce')!r}"
                f"(必须恰为 1)")
        if _lock_int(lock.get("worker_pidns_pid")) != 1:
            raise BuilderProvenanceError(
                "Worker 不是 pidns 内 pid 1(隔离身份未被外部实测)")
        bundle = lock.get("runtime_bundle") or {}
        digest = str(bundle.get("manifest_digest") or "")
        if not digest.startswith("rbm-") \
                or _lock_int(bundle.get("file_count")) is None \
                or int(bundle.get("file_count")) <= 0:
            raise BuilderProvenanceError(
                "运行时锁缺少内容寻址 runtime bundle 绑定(rbm-;"
                "0h 以活 conda 树为输入的锁不再被接受)")
        clock = lock.get("clock_policy") or {}
        vdso = clock.get("vdso") or {}
        if vdso.get("mode") not in ("frozen-stub", "no-vdso"):
            raise BuilderProvenanceError(
                "运行时锁缺少 vDSO 冻结策略(真实时钟路径必须死亡)")
        behavior = clock.get("behavior") or {}
        if behavior.get("time_time") != 0.0 \
                or behavior.get("datetime_now_year") != 1970:
            raise BuilderProvenanceError(
                "运行时锁的时钟行为探针不满足冻结纪元(time==0 且 "
                "datetime 1970)")
        for key, val in (clock.get("raw_syscall") or {}).items():
            if val != "ERRNO1":
                raise BuilderProvenanceError(
                    f"时钟 raw syscall {key} 未被拒绝({val!r})")
        entropy = lock.get("entropy_policy") or {}
        if entropy.get("getrandom") != "ERRNO1" \
                or entropy.get("dev_urandom_deterministic") is not True:
            raise BuilderProvenanceError(
                "运行时锁缺少确定性熵策略(getrandom 必须被拒绝,"
                "/dev/urandom 必须是受承诺确定性文件)")
        closure = lock.get("import_closure")
        if not isinstance(closure, list):
            raise BuilderProvenanceError(
                "运行时锁缺少实际导入闭包 import_closure(A2)")
        for entry in closure:
            kind = str(entry.get("origin_kind") or "")
            if kind == "file":
                f = str(entry.get("file") or "")
                sha = str(entry.get("sha256") or "")
                if not f.startswith("/") or len(sha) != 64:
                    raise BuilderProvenanceError(
                        "导入闭包存在未绑定 bundle 字节的文件条目"
                        "(fail closed;模块名已脱敏)")
        # ---- 2.6.0j v4:不可逆密封计算边界 ----
        sc = lock.get("sealed_compute") or {}
        if not sc:
            raise BuilderProvenanceError(
                "运行时锁 v4 缺少 sealed_compute 块(Prepare->Seal->"
                "Compute 边界未被证明;0i 的 v3 锁不再被接受)")
        if sc.get("phase_plan") != "prepare->seal->compute":
            raise BuilderProvenanceError(
                f"sealed_compute 阶段计划异常:{sc.get('phase_plan')!r}")
        if not str(sc.get("final_seccomp_filter_hash") or ""
                   ).startswith("scf-"):
            raise BuilderProvenanceError(
                "sealed_compute 缺少 final compute filter 哈希"
                "(default deny 边界未被绑定)")
        purity = sc.get("top_level_purity") or {}
        if purity.get("all_ok") is not True or not purity.get("digest"):
            raise BuilderProvenanceError(
                "sealed_compute 缺少模块顶层纯度验证摘要(拒绝)")
        mdwe = sc.get("mdwe") or {}
        if mdwe.get("enabled") is not True \
                and mdwe.get("supported") is not False:
            raise BuilderProvenanceError(
                "sealed_compute 缺少 MDWE 生效证明或不支持声明(拒绝)")
        fd_iso = sc.get("fd_isolation") or {}
        if fd_iso.get("stdin") != "closed" \
                or fd_iso.get("result_fd") != 87:
            raise BuilderProvenanceError(
                "sealed_compute 的 fd 隔离状态未被证明(stdin 关闭 + "
                "RESULT_FD=87;拒绝)")
        after = sc.get("compute_after") or {}
        if _lock_int(after.get("thread_count")) != 1:
            raise BuilderProvenanceError(
                f"Compute 后二次实测线程数 {after.get('thread_count')!r}"
                f"(必须为 1;拒绝)")
        if _lock_int(after.get("child_process_count")) != 0:
            raise BuilderProvenanceError(
                "Compute 后二次实测存在后代进程(拒绝)")
        if _lock_int(after.get("seccomp_filter_count")) < 2:
            raise BuilderProvenanceError(
                "Compute 后 seccomp filter 数量 < 2(final compute "
                "filter 未叠加;拒绝)")
        if after.get("exec_mapping_growth") not in (0, None):
            growth = after.get("exec_mapping_growth")
            raise BuilderProvenanceError(
                f"Compute 后 exec 映射增长 {growth!r}"
                f"(可执行内存新增;拒绝)")
        dep_pro = str(sc.get("dependency_profile") or "")
        if dep_pro not in ("formal", "compat"):
            raise BuilderProvenanceError(
                f"sealed_compute 依赖策略异常:{dep_pro!r}"
                f"(formal/compat;兼容运行可完成 run record,但 "
                f"evidence 层拒绝其形成可信材料)")
        violations = sc.get("phase_violations")
        if violations:
            raise BuilderProvenanceError(
                f"Compute/toplevel 阶段违规 {violations[:4]}"
                f"(import/open/exec/compile/native 通道;拒绝)")
    if not isinstance(lock.get("native_libraries"), list):
        raise BuilderProvenanceError(
            "运行时依赖锁缺少 native_libraries 内容绑定(D3:实际加载"
            "的 .so 必须全部绑定内容与归属)")
    for entry in lock.get("native_libraries") or []:
        if len(str(entry.get("sha256") or "")) != 64 \
                or not str(entry.get("path") or "").startswith("/"):
            raise BuilderProvenanceError(
                "native_libraries 条目缺少内容绑定(D3)")
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
    if verify_content:
        for entry in lock.get("distributions") or []:
            dist_name = str(entry.get("distribution") or "")
            f = str(entry.get("file") or "")
            sha = str(entry.get("sha256") or "")
            if not dist_name or not f.startswith("/") or len(sha) != 64:
                raise BuilderProvenanceError(
                    f"运行时锁的 distribution {dist_name!r} 缺少实际"
                    "文件字节绑定(2.6.0i:A2 按实际文件路径归属并绑定"
                    "bundle manifest 字节;dcd-/RECORD 通道已废除)")


# ------------------------------------------------------------ mock 组装
def run_mock_assembly(request: dict[str, Any]) -> dict[str, Any]:
    """mock_payload_assembly 通道的确定性重组装(公开代码,主进程)。

    返回与隔离 Runner 同构的 run record(v2 字段:access summary
    hash/进程树哨兵/公开组装 isolation 身份)。"""
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
            f"mock 组装结果含未知字段 {unknown}({BUILD_RESULT_FORMAT})")
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
    except Exception as exc:  # noqa: BLE001
        raise BuilderProvenanceError(
            f"mock 组装产物无法解析为 ExamPack: "
            f"{type(exc).__name__}: {exc}") from exc
    log = canonicalize_attempt_log(
        raw.get("attempt_log"), output_pack_hash=pack_hash,
        attempt_policy=dict(request.get("attempt_policy") or {}))
    access = {
        "format": ACCESS_SUMMARY_FORMAT,
        "open_count": 0,
        "outside_allowlist": [],
        "covered_events": [],
        "child_process_attempts": 0,
        "exec_attempts": 0,
        "dlopen_targets": [],
    }
    lock = {
        "format": RUNTIME_LOCK_FORMAT,
        "python_implementation": "mock-payload-assembly",
        "python_version": "0",
        "executable_prefix": "mock-payload-assembly",
        "process_tree_policy": PROCESS_TREE_PUBLIC_ASSEMBLY,
        "thread_policy": "in_process_public_assembly",
        "child_process_count": 0,
        "child_process_attempts": 0,
        "exec_count": 0,
        "exec_attempts": 0,
        "worker_pidns_pid": 0,
        "runtime_bundle": {
            "manifest_digest": "rbm-public-assembly",
            "file_count": 0,
            "syslib_sonames": [],
            "hostname": "public-assembly",
        },
        "clock_policy": {
            "vdso": {"mode": "public-assembly"},
            "pr_set_tsc_rc": 0,
            "raw_syscall": {},
            "behavior": {},
        },
        "entropy_policy": {
            "getrandom": "public-assembly",
            "dev_urandom_deterministic": True,
        },
        "distributions": [],
        "import_closure": [],
        "native_libraries": [],
        "thread_state": {"policy": "in_process_public_assembly",
                         "thread_count_at_quiesce": 0, "tasks": []},
        "seccomp_policy": None,
        "seccomp_filter_hash": None,
        "sealed_compute": {
            "phase_plan": "public-assembly",
            "dependency_profile": "public-assembly",
            "final_seccomp_filter_hash": None,
            "mdwe": {"enabled": False, "supported": False,
                     "mode": "public-assembly"},
            "fd_isolation": {"stdin": "public-assembly",
                             "result_fd": None},
            "compute_after": {},
            "phase_violations": [],
        },
        "environment_identity": {"environ": {}, "cwd":
                                 "public-assembly"},
    }
    from rl_curriculum.sealed_exam import module_code_hash

    return {
        "mode": BUILDER_RUN_MODE_MOCK_ASSEMBLY,
        "status": "ok",
        "pack": pack,
        "pack_hash": pack_hash,
        "attempt_log": log,
        "attempt_log_hash": attempt_log_hash(log),
        "runtime_lock": lock,
        "runtime_lock_hash": runtime_lock_hash(lock),
        "runner_code_hash": module_code_hash(mock_sealed_exam),
        "sandbox_profile_hash": _mock_assembly_profile_hash(),
        "staged_tree_hash": "",
        "access_summary": access,
        "access_summary_hash": access_summary_hash(access),
        "deterministic_input_report": {
            "format": "builder-deterministic-input-report-v1",
            "mode": "public-assembly-sentinel",
        },
        "deterministic_input_hash": "edi-public-assembly",
        "runtime_bundle_hash": "rbm-public-assembly",
        "final_seccomp_filter_hash": "scf-public-assembly",
        "dependency_profile": "public-assembly",
        "effective_sandbox_hash": "esb-public-assembly",
        "process_tree_policy": PROCESS_TREE_PUBLIC_ASSEMBLY,
        "child_process_count": 0,
        "child_process_attempts": 0,
        "exec_count": 0,
        "runner_isolation": "public_assembly_process",
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "error": None,
    }


def _mock_assembly_profile_hash() -> str:
    payload = {"format": "mock-assembly-profile-v1",
               "execution": "in_process_public_assembly"}
    return "brp-" + _canonical_json_hash(payload)


# ------------------------------------------------------------ 证明入口
def verify_builder_provenance(
    provider: Any, commitment: Any, *,
    pack: Any, duration_contract: dict[str, Any],
    builder_evidence: dict[str, Any] | None = None,
    builder_root: "Path | str | None" = None,
) -> dict[str, Any]:
    """builder 产物来源证明(考试期第三次重放;E3/E4 + C/D/F)。

    v3 新增对账:重放的 Effective Sandbox Report 哈希、access
    summary 哈希、进程树状态(child/exec 计数)与 isolated_process
    身份必须与 evidence 记录一致(F)。
    """
    from pathlib import Path as _P

    try:
        identity = provider.builder_identity()
        provider_mode = str(provider.builder_run_mode())
        request = provider.frozen_build_request(
            pack, duration_contract)
    except Exception as exc:  # noqa: BLE001
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
    from rl_curriculum.builder_evidence import (
        replay_builder_for_evidence,
        verify_builder_run_evidence,
    )

    if builder_evidence is None:
        raise BuilderProvenanceError(
            "缺少 Builder Run Evidence(v10 承诺必须绑定 builder_run_"
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
    # G3 + D1/D2:锁对账(私有通道要求单进程 + 内容重算)
    static_deps = list(
        (identity.manifest or {}).get("external_dependencies") or [])
    check_runtime_lock_against_static(
        replay["runtime_lock"], static_deps,
        require_single_process=mode == BUILDER_RUN_MODE_EXECUTION,
        verify_content=mode == BUILDER_RUN_MODE_EXECUTION)
    # F:重放的密闭输入/访问/进程树身份与 evidence 对账(2.6.0i:
    # edi- 确定性输入报告 + rbm- runtime bundle 取代 0h esb-)
    if str(replay.get("deterministic_input_hash") or "") != str(
            builder_evidence.get("deterministic_input_hash") or ""):
        raise BuilderProvenanceError(
            "重放的确定性输入报告哈希与 evidence 不一致(密闭输入"
            "状态漂移;C2/D2/F;EXAM_INVALID)")
    if str(replay.get("runtime_bundle_hash") or "") != str(
            builder_evidence.get("runtime_bundle_hash") or ""):
        raise BuilderProvenanceError(
            "重放的 runtime bundle 哈希与 evidence 不一致(rbm-;"
            "运行环境内容漂移;A1/F;EXAM_INVALID)")
    if str(replay.get("access_summary_hash") or "") != str(
            builder_evidence.get("access_summary_hash") or ""):
        raise BuilderProvenanceError(
            "重放的 access summary 哈希与 evidence 不一致(F;"
            "EXAM_INVALID)")
    if mode == BUILDER_RUN_MODE_EXECUTION:
        if replay.get("runner_isolation") != "isolated_process":
            raise BuilderProvenanceError(
                "重放不是隔离进程执行(runner_isolation 身份缺失;"
                "EXAM_INVALID)")
        if int(replay.get("child_process_count") or 0) != 0 or \
                int(replay.get("exec_count") or 0) != 0:
            raise BuilderProvenanceError(
                "重放存在后代进程或 exec(D1;EXAM_INVALID)")
    return {
        "format": "builder-provenance-report-v3",
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
        "replay_deterministic_input_hash": str(
            replay.get("deterministic_input_hash") or ""),
        "replay_runtime_bundle_hash": str(
            replay.get("runtime_bundle_hash") or ""),
        "replay_thread_policy": str(replay.get("thread_policy") or ""),
        "replay_access_summary_hash": str(
            replay.get("access_summary_hash") or ""),
        "runner_code_hash": str(replay["runner_code_hash"]),
        "sandbox_profile_hash": str(replay["sandbox_profile_hash"]),
        "process_tree_policy": str(replay.get("process_tree_policy") or ""),
        "child_process_count": int(replay.get("child_process_count") or 0),
        "exec_count": int(replay.get("exec_count") or 0),
        "replay_isolated_process": bool(
            mode == BUILDER_RUN_MODE_EXECUTION),
        "pack_hash_match": True,
        "status": "ok",
    }
