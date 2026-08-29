"""Builder Run Evidence 与确定性证明(阶段 2.6.0i:v3)。

v3 语义(在 0h v2 之上):evidence 核心字段升级为密闭输入闭包——
- runtime_bundle_hash(rbm-,内容寻址运行时环境 manifest 摘要);
- deterministic_input_hash(edi-,Effective Deterministic Input
  Report:bundle/文件系统/proc/dev/clock/entropy/seccomp/线程静止/
  环境身份/探针,由 Worker 实测与 Supervisor 外部实测合并);
- thread_policy(clone 全拒;quiesce 静止实测进锁 v3);
- effective_sandbox_hash(esb-)退役:0h 报告不足以表达输入闭包,
  v3 执行器拒绝只有 esb- 的材料。

公开组装通道(mock_payload_assembly)使用确定性哨兵
(edi-public-assembly / rbm-public-assembly);私有通道必须携带真实
edi-/rbm- 且 detail.deterministic_input_report 重算哈希一致。

一致性键从六组升级为:pack / attempt log / runtime lock /
deterministic input report / access summary + 进程树计数。precommit
双跑与考试期第三次重放按同一键组对账。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.builder_provenance import (
    ACCESS_SUMMARY_FORMAT,
    BUILDER_RUN_MODE_EXECUTION,
    BUILDER_RUN_MODE_MOCK_ASSEMBLY,
    PROCESS_TREE_PUBLIC_ASSEMBLY,
    PROCESS_TREE_SINGLE,
    BuilderProvenanceError,
    access_summary_hash,
    attempt_log_hash,
    frozen_build_request_hash,
    runtime_lock_hash,
    run_mock_assembly,
)

BUILDER_RUN_EVIDENCE_FORMAT = "builder-run-evidence-v3"

#: 组装通道哨兵(公开组装无 Runner 沙箱;确定性字面量)
MOCK_EDI_HASH = "edi-public-assembly"
MOCK_BUNDLE_HASH = "rbm-public-assembly"

#: evidence 核心字段(进入 bre- 哈希与公开承诺摘要;detail 不进哈希)
EVIDENCE_CORE_FIELDS: tuple[str, ...] = (
    "format", "mode", "builder_manifest_hash", "provider_config_hash",
    "builder_protocol", "runner_code_hash", "sandbox_profile_hash",
    "staged_tree_hash", "frozen_request_hash", "runtime_lock_hash",
    "attempt_policy_hash", "attempt_log_hash", "output_pack_hash",
    "output_pack_format", "output_pack_version", "run_status",
    "deterministic",
    "deterministic_input_hash", "runtime_bundle_hash",
    "access_summary_hash",
    "process_tree_policy", "thread_policy",
    "child_process_count", "exec_count",
    "runner_isolation",
    "runs",
)


class BuilderUncertainError(RuntimeError):
    """Builder 不确定(precommit 双重运行结果不一致;不得创建承诺)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


def provider_config_hash(provider: Any) -> str:
    """Provider 配置身份(pcf-)。"""
    root = getattr(provider, "root", None)
    if root is not None:
        cfg = Path(root) / "provider_config.json"
        if cfg.is_file():
            return "pcf-" + hashlib.sha256(
                cfg.read_bytes()).hexdigest()
    payload = {"format": "mock-builder-provider", "provider": "mock"}
    return "pcf-" + _canonical_json_hash(payload)


def attempt_policy_hash(request: dict[str, Any]) -> str:
    """attempt 政策哈希(nap-):选择策略(first_pass)与上限。"""
    policy = dict(request.get("attempt_policy") or {})
    if not policy:
        policy = {
            "policy": "assembly" if int(
                request.get("max_attempts") or 0) == 0
            and request.get("mode") == BUILDER_RUN_MODE_MOCK_ASSEMBLY
            else "first_pass",
            "max_attempts": int(request.get("max_attempts") or 0),
        }
    payload = {
        "format": "builder-attempt-policy-v1",
        "max_attempts": int(policy.get("max_attempts") or 0),
        "selection": str(policy.get("policy") or "first_pass"),
    }
    return "nap-" + _canonical_json_hash(payload)


def builder_run_evidence_core(evidence: dict[str, Any]) -> dict[str, Any]:
    """evidence 的核心字段(detail 不进哈希)。"""
    return {k: evidence.get(k) for k in EVIDENCE_CORE_FIELDS}


def builder_run_evidence_hash(evidence: dict[str, Any]) -> str:
    """evidence 核心字段的 canonical hash(bre-)。"""
    if not isinstance(evidence, dict) or evidence.get(
            "format") != BUILDER_RUN_EVIDENCE_FORMAT:
        raise BuilderProvenanceError(
            f"Builder Run Evidence 必须是 {BUILDER_RUN_EVIDENCE_FORMAT!r}"
            f" dict(收到 {type(evidence).__name__}/"
            f"{(evidence or {}).get('format')!r};2.6.0h 的 v2 evidence "
            f"已被 v3 执行器拒绝)")
    return "bre-" + _canonical_json_hash(
        builder_run_evidence_core(evidence))


#: 单次运行的一致性键(edi-/rbm- 进键;不含 run 序号)
_RUN_CONSISTENCY_KEYS = (
    "pack_hash", "attempt_log_hash", "runtime_lock_hash",
    "deterministic_input_hash", "access_summary_hash",
    "child_process_count", "exec_count",
)


def _run_consistency(run: dict[str, Any]) -> dict[str, Any]:
    """单次运行的一致性视图(确定性输入报告 + 访问摘要 + 计数)。"""
    return {
        "pack_hash": str(run["pack_hash"]),
        "attempt_log_hash": attempt_log_hash(run["attempt_log"]),
        "runtime_lock_hash": runtime_lock_hash(run["runtime_lock"]),
        "deterministic_input_hash": str(
            run.get("deterministic_input_hash") or ""),
        "access_summary_hash": access_summary_hash(
            dict(run.get("access_summary") or {})),
        "child_process_count": int(run.get("child_process_count") or 0),
        "exec_count": int(run.get("exec_count") or 0),
    }


def build_builder_run_evidence(
        *, identity: Any, request: dict[str, Any], runs: list[dict[str, Any]],
        provider: Any,
) -> dict[str, Any]:
    """从两次 precommit run record 组装完整 Builder Run Evidence(v3)。"""
    if len(runs) != 2:
        raise BuilderProvenanceError(
            f"Builder Run Evidence 必须绑定恰好两次 precommit 运行"
            f"(收到 {len(runs)} 次;E2)")
    views = [_run_consistency(r) for r in runs]
    if views[0] != views[1]:
        raise BuilderUncertainError(
            f"precommit 双重运行不一致:run1 {views[0]} vs run2 "
            f"{views[1]}(Builder 不确定,不得创建承诺)")
    run = runs[0]
    mode = str(run["mode"])
    pack = run["pack"]
    if mode == BUILDER_RUN_MODE_EXECUTION:
        edi_hash = str(run.get("deterministic_input_hash") or "")
        if not edi_hash.startswith("edi-") or edi_hash == MOCK_EDI_HASH:
            raise BuilderProvenanceError(
                "私有通道 evidence 缺少真实确定性输入报告哈希(edi-;"
                "组装哨兵冒充/缺失/0h esb- 材料均 fail closed;C2)")
        bundle_hash = str(run.get("runtime_bundle_hash") or "")
        if not bundle_hash.startswith("rbm-") \
                or bundle_hash == MOCK_BUNDLE_HASH:
            raise BuilderProvenanceError(
                "私有通道 evidence 缺少内容寻址 runtime bundle 哈希"
                "(rbm-;以活 conda 树为输入的 0h 材料被拒绝;A1)")
        if str(run.get("process_tree_policy") or "") != PROCESS_TREE_SINGLE:
            raise BuilderProvenanceError(
                "私有通道 run 的进程树策略必须是 "
                f"{PROCESS_TREE_SINGLE!r}(允许子进程的材料被拒绝;D1)")
        if str(run.get("thread_policy") or "") != \
                "threads_forbidden_clone_denied":
            raise BuilderProvenanceError(
                "私有通道 run 的线程策略必须是 threads_forbidden_"
                "clone_denied(2.6.0h 允许 CLONE_THREAD 的材料被拒绝;"
                "C4)")
        if isinstance(run.get("child_process_count"), int) and run.get("child_process_count") != 0 or \
                isinstance(run.get("exec_count"), int) and run.get("exec_count") != 0:
            raise BuilderProvenanceError(
                "私有通道 run 存在后代进程或 exec 计数(子进程 import "
                "不进入父 Runner 锁,唯一安全语义是零后代进程;D1)")
        process_tree = PROCESS_TREE_SINGLE
        thread_policy = "threads_forbidden_clone_denied"
        isolation = "isolated_process"
    else:
        edi_hash = MOCK_EDI_HASH
        bundle_hash = MOCK_BUNDLE_HASH
        process_tree = PROCESS_TREE_PUBLIC_ASSEMBLY
        thread_policy = "in_process_public_assembly"
        isolation = "public_assembly_process"
    core = {
        "format": BUILDER_RUN_EVIDENCE_FORMAT,
        "mode": mode,
        "builder_manifest_hash": str(identity.manifest_hash),
        "provider_config_hash": provider_config_hash(provider),
        "builder_protocol": str(identity.builder_protocol),
        "runner_code_hash": str(run["runner_code_hash"]),
        "sandbox_profile_hash": str(run["sandbox_profile_hash"]),
        "staged_tree_hash": str(
            (identity.manifest or {}).get("package_tree", {}).get(
                "tree_hash") or ""),
        "frozen_request_hash": frozen_build_request_hash(request),
        "runtime_lock_hash": views[0]["runtime_lock_hash"],
        "attempt_policy_hash": attempt_policy_hash(request),
        "attempt_log_hash": views[0]["attempt_log_hash"],
        "output_pack_hash": views[0]["pack_hash"],
        "output_pack_format": "exam-pack",
        "output_pack_version": str(getattr(pack, "version", "") or ""),
        "run_status": str(run["status"]),
        "deterministic": True,
        "deterministic_input_hash": edi_hash,
        "runtime_bundle_hash": bundle_hash,
        "access_summary_hash": views[0]["access_summary_hash"],
        "process_tree_policy": process_tree,
        "thread_policy": thread_policy,
        "child_process_count": views[0]["child_process_count"],
        "exec_count": views[0]["exec_count"],
        "runner_isolation": isolation,
        "runs": [
            {"run": 1, **views[0]}, {"run": 2, **views[1]}],
    }
    evidence = dict(core)
    evidence["detail"] = {
        "runtime_lock": dict(run["runtime_lock"]),
        "attempt_log": dict(run["attempt_log"]),
        "access_summary": dict(run.get("access_summary") or {}),
        "deterministic_input_report": dict(
            run.get("deterministic_input_report") or {}),
        "runner_isolated_process": bool(
            mode == BUILDER_RUN_MODE_EXECUTION),
    }
    evidence["evidence_hash"] = builder_run_evidence_hash(evidence)
    return evidence


# ------------------------------------------------------------ precommit
def _run_once_for_mode(
        provider: Any, request: dict[str, Any], *,
        builder_root: Path | str | None,
        staging_base: Path | str | None = None,
        bundle_pool: Any = None,
) -> dict[str, Any]:
    """按 mode 分派单次运行(密闭 Runner / mock 重组装)。"""
    mode = str(request.get("mode"))
    if mode == BUILDER_RUN_MODE_EXECUTION:
        from rl_curriculum.builder_runner import (
            BuilderRunnerError,
            run_isolated_builder_run,
        )

        root = builder_root if builder_root is not None else getattr(
            provider, "root", None)
        if root is None:
            raise BuilderProvenanceError(
                "builder_execution 模式需要私有 builder root"
                "(Provider 未提供)")
        kwargs = {}
        if bundle_pool is not None:
            kwargs["bundle_pool"] = bundle_pool
        try:
            return run_isolated_builder_run(
                provider.builder_identity(), request,
                builder_root=root, staging_base=staging_base,
                **kwargs)
        except BuilderRunnerError as exc:
            raise BuilderProvenanceError(
                f"隔离 Builder Runner 运行失败: {exc}") from exc
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        return run_mock_assembly(request)
    raise BuilderProvenanceError(f"未知构建运行模式 {mode!r}")


def precommit_builder_runs(
        provider: Any, request: dict[str, Any], *,
        builder_root: Path | str | None = None,
        bundle_pool: Any = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """E2:承诺创建前的双重运行(两个独立 Worker,共享链内 bundle)。"""
    from rl_curriculum.builder_provenance import check_frozen_build_request

    check_frozen_build_request(request)
    identity = provider.builder_identity()
    pool = bundle_pool
    if pool is None and str(request.get("mode")) == \
            BUILDER_RUN_MODE_EXECUTION:
        from rl_curriculum.builder_runner import shared_bundle_pool

        pool = shared_bundle_pool()
    runs = [
        _run_once_for_mode(provider, request, builder_root=builder_root,
                           bundle_pool=pool),
        _run_once_for_mode(provider, request, builder_root=builder_root,
                           bundle_pool=pool),
    ]
    views = [_run_consistency(r) for r in runs]
    if views[0] != views[1]:
        raise BuilderUncertainError(
            f"precommit 双重运行不一致:run1 {views[0]} vs run2 "
            f"{views[1]}(读取系统时间/未冻结随机种子/网络响应/文件"
            f"目录顺序等不确定性来源;Builder 不得进入正式承诺)")
    evidence = build_builder_run_evidence(
        identity=identity, request=request, runs=runs, provider=provider)
    return evidence, runs


# ------------------------------------------------------------ 验证(E3/E4)
def verify_builder_run_evidence(
        evidence: dict[str, Any], *,
        commitment: Any, identity: Any, request_hash: str,
) -> None:
    """E4/F:读取完整 evidence、重算 bre- 并逐项验证(fail closed)。"""
    summary = dict(getattr(
        commitment, "builder_run_evidence", {}) or {})
    if not summary:
        raise BuilderProvenanceError(
            "承诺缺少 builder_run_evidence 绑定(v10 承诺必须绑定 "
            "Builder Run Evidence 摘要;EXAM_INVALID)")
    recomputed = builder_run_evidence_hash(evidence)
    if recomputed != str(summary.get("evidence_hash") or ""):
        raise BuilderProvenanceError(
            f"Builder Run Evidence 哈希不一致(重算 {recomputed} vs 承诺 "
            f"{summary.get('evidence_hash')!r}):evidence 被改写或与承诺"
            f"不对应(EXAM_INVALID)")
    if recomputed != str(evidence.get("evidence_hash") or ""):
        raise BuilderProvenanceError(
            "evidence 自身携带的 evidence_hash 与重算值不一致"
            "(EXAM_INVALID)")
    core = builder_run_evidence_core(evidence)
    for key in ("mode", "runner_code_hash", "sandbox_profile_hash",
                "runtime_lock_hash", "attempt_log_hash",
                "output_pack_hash", "staged_tree_hash", "deterministic",
                "deterministic_input_hash", "runtime_bundle_hash",
                "access_summary_hash",
                "process_tree_policy", "thread_policy",
                "child_process_count", "exec_count", "runner_isolation"):
        if core.get(key) != summary.get(key):
            raise BuilderProvenanceError(
                f"evidence 核心字段 {key!r} 与承诺摘要不一致"
                f"(evidence={core.get(key)!r} vs 承诺="
                f"{summary.get(key)!r};EXAM_INVALID)")
    if core.get("run_status") != "ok" or core.get("deterministic") \
            is not True:
        raise BuilderProvenanceError(
            "evidence 的 run_status/deterministic 不满足正式要求"
            "(必须 ok + True;EXAM_INVALID)")
    mode = str(core.get("mode") or "")
    if mode not in (BUILDER_RUN_MODE_EXECUTION,
                    BUILDER_RUN_MODE_MOCK_ASSEMBLY):
        raise BuilderProvenanceError(
            f"evidence 的 mode {mode!r} 不在预注册范围(EXAM_INVALID)")
    if mode == BUILDER_RUN_MODE_EXECUTION:
        if not str(core.get("deterministic_input_hash") or "").startswith(
                "edi-"):
            raise BuilderProvenanceError(
                "私有通道 evidence 缺少真实确定性输入报告哈希"
                "(edi-;0h esb- 材料被拒绝;C2;EXAM_INVALID)")
        if not str(core.get("runtime_bundle_hash") or "").startswith(
                "rbm-"):
            raise BuilderProvenanceError(
                "私有通道 evidence 缺少内容寻址 runtime bundle 哈希"
                "(rbm-;A1;EXAM_INVALID)")
        if core.get("process_tree_policy") != PROCESS_TREE_SINGLE:
            raise BuilderProvenanceError(
                f"私有通道 evidence 的进程树策略必须是 "
                f"{PROCESS_TREE_SINGLE!r}(允许子进程的材料被拒绝;"
                f"EXAM_INVALID)")
        if core.get("thread_policy") != "threads_forbidden_clone_denied":
            raise BuilderProvenanceError(
                "私有通道 evidence 的线程策略必须是 threads_forbidden"
                "_clone_denied(允许线程的 0h 材料被拒绝;EXAM_INVALID)")
        def _core_int(v):
            return v if isinstance(v, int) and not isinstance(v, bool) \
                else -1
        if _core_int(core.get("child_process_count")) != 0 or \
                _core_int(core.get("exec_count")) != 0:
            raise BuilderProvenanceError(
                "私有通道 evidence 存在后代进程或 exec 计数(D1;"
                "EXAM_INVALID)")
        if core.get("runner_isolation") != "isolated_process":
            raise BuilderProvenanceError(
                "私有通道 evidence 缺少 isolated_process 身份(F;"
                "EXAM_INVALID)")
    else:
        if core.get("deterministic_input_hash") != MOCK_EDI_HASH:
            raise BuilderProvenanceError(
                "组装通道 evidence 的确定性输入哨兵不符(EXAM_INVALID)")
        if core.get("runtime_bundle_hash") != MOCK_BUNDLE_HASH:
            raise BuilderProvenanceError(
                "组装通道 evidence 的 bundle 哨兵不符(EXAM_INVALID)")
    runs = list(core.get("runs") or [])
    if len(runs) != 2 or any(
            runs[0].get(k) != runs[1].get(k)
            for k in _RUN_CONSISTENCY_KEYS):
        raise BuilderProvenanceError(
            f"precommit 双跑记录不完整或不一致(runs={runs!r};"
            f"E2 违规;EXAM_INVALID)")
    tree_hash = str((identity.manifest or {}).get("package_tree",
                                                  {}).get("tree_hash")
                    or "")
    if str(core.get("staged_tree_hash") or "") != tree_hash:
        raise BuilderProvenanceError(
            "evidence 的 staged_tree_hash 与 Provider identity 不一致"
            "(npb- tree 对账失败;EXAM_INVALID)")
    if str(core.get("builder_manifest_hash") or "") != str(
            identity.manifest_hash):
        raise BuilderProvenanceError(
            "evidence 的 builder_manifest_hash 与 Provider identity 不"
            "一致(npb- 对账失败;EXAM_INVALID)")
    if str(core.get("frozen_request_hash") or "") != str(request_hash):
        raise BuilderProvenanceError(
            "evidence 的 frozen_request_hash 与冻结构建请求重算哈希"
            "不一致(nbr- 对账失败;EXAM_INVALID)")
    if str(core.get("output_pack_hash") or "") != str(
            commitment.pack_hash):
        raise BuilderProvenanceError(
            "evidence 的 output_pack_hash 与承诺 pack_hash 不一致"
            "(EXAM_INVALID)")
    # detail 内容逐项验证(E4 + F):attempt log/runtime lock/access
    # 摘要/确定性输入报告全部重算哈希对账(篡改 detail 绕过 bre- 的
    # 攻击被拒绝)
    detail = evidence.get("detail") or {}
    if not isinstance(detail, dict):
        raise BuilderProvenanceError(
            "evidence 缺少 detail(完整运行证据:runtime_lock/attempt_"
            "log/access 摘要/确定性输入报告;不能只信任核心摘要)")
    try:
        detail_log_hash = attempt_log_hash(detail.get("attempt_log"))
    except BuilderProvenanceError as exc:
        raise BuilderProvenanceError(
            f"evidence.detail.attempt_log 不合法: {exc}") from exc
    if detail_log_hash != str(core.get("attempt_log_hash") or ""):
        raise BuilderProvenanceError(
            f"evidence.detail.attempt_log 重算哈希({detail_log_hash})"
            f"与核心 attempt_log_hash({core.get('attempt_log_hash')!r})"
            f"不一致(detail 被改写;EXAM_INVALID)")
    try:
        detail_lock_hash = runtime_lock_hash(detail.get("runtime_lock"))
    except BuilderProvenanceError as exc:
        raise BuilderProvenanceError(
            f"evidence.detail.runtime_lock 不合法: {exc}") from exc
    if detail_lock_hash != str(core.get("runtime_lock_hash") or ""):
        raise BuilderProvenanceError(
            f"evidence.detail.runtime_lock 重算哈希({detail_lock_hash})"
            f"与核心 runtime_lock_hash({core.get('runtime_lock_hash')!r})"
            f"不一致(detail 被改写;EXAM_INVALID)")
    if access_summary_hash(dict(detail.get("access_summary") or {})) != \
            str(core.get("access_summary_hash") or ""):
        raise BuilderProvenanceError(
            "evidence.detail.access_summary 重算哈希与核心"
            " access_summary_hash 不一致(detail 被改写;EXAM_INVALID)")
    if mode == BUILDER_RUN_MODE_EXECUTION:
        from rl_curriculum.builder_runner import (
            BuilderRunnerProfile,
            check_effective_deterministic_input_report,
            deterministic_input_report_hash,
        )

        report = dict(detail.get("deterministic_input_report") or {})
        if not report:
            raise BuilderProvenanceError(
                "私有通道 evidence.detail 缺少确定性输入报告(没有"
                "密闭输入证明的材料被拒绝;EXAM_INVALID)")
        try:
            detail_edi_hash = deterministic_input_report_hash(report)
        except Exception as exc:  # noqa: BLE001
            raise BuilderProvenanceError(
                f"evidence.detail.deterministic_input_report 无法规范"
                f"化: {type(exc).__name__}: {exc}") from exc
        if detail_edi_hash != str(
                core.get("deterministic_input_hash") or ""):
            raise BuilderProvenanceError(
                "evidence.detail.deterministic_input_report 重算哈希"
                "与核心 deterministic_input_hash 不一致(detail 被改写;"
                "EXAM_INVALID)")
        bundle_hash = str(core.get("runtime_bundle_hash") or "")
        try:
            check_effective_deterministic_input_report(
                report, BuilderRunnerProfile(),
                bundle_digest=bundle_hash
                if bundle_hash != MOCK_BUNDLE_HASH else None)
        except Exception as exc:  # noqa: BLE001
            raise BuilderProvenanceError(
                f"evidence 的确定性输入报告未通过不变量校验(隔离降级"
                f"或输入闭包缺失;C2/D2;EXAM_INVALID): {exc}") from exc


def replay_builder_for_evidence(
        provider: Any, *, request: dict[str, Any],
        builder_evidence: dict[str, Any],
        builder_root: Path | str | None = None,
        bundle_pool: Any = None,
) -> dict[str, Any]:
    """E3:考试期第三次重放(全新 Worker)并对账 evidence(v3)。"""
    run = _run_once_for_mode(
        provider, request, builder_root=builder_root,
        bundle_pool=bundle_pool)
    view = _run_consistency(run)
    core = builder_run_evidence_core(builder_evidence)
    expected = {
        "pack_hash": str(core.get("output_pack_hash") or ""),
        "attempt_log_hash": str(core.get("attempt_log_hash") or ""),
        "runtime_lock_hash": str(core.get("runtime_lock_hash") or ""),
        "deterministic_input_hash": str(
            core.get("deterministic_input_hash") or ""),
        "access_summary_hash": str(
            core.get("access_summary_hash") or ""),
        "child_process_count": int(core.get("child_process_count") or 0),
        "exec_count": int(core.get("exec_count") or 0),
    }
    if view != expected:
        raise BuilderProvenanceError(
            f"考试期第三次重放与 precommit evidence 不一致:replay "
            f"{view} vs evidence {expected}(读取系统时间/未冻结随机"
            f"种子/依赖漂移/bundle 漂移等不确定性;Builder 确定性或"
            f"密闭输入状态不成立;EXAM_INVALID)")
    if str(run["runner_code_hash"]) != str(
            core.get("runner_code_hash") or ""):
        raise BuilderProvenanceError(
            "重放的 Runner code hash 与 evidence 不一致(rtb-/组装器"
            "代码漂移;EXAM_INVALID)")
    if str(run["sandbox_profile_hash"]) != str(
            core.get("sandbox_profile_hash") or ""):
        raise BuilderProvenanceError(
            "重放的 sandbox/profile hash 与 evidence 不一致(brp-;"
            "EXAM_INVALID)")
    if str(run.get("runtime_bundle_hash") or "") != str(
            core.get("runtime_bundle_hash") or ""):
        raise BuilderProvenanceError(
            "重放的 runtime bundle 哈希与 evidence 不一致(rbm-;"
            "运行环境内容漂移;EXAM_INVALID)")
    return run


def write_builder_run_evidence(path: Path | str, evidence: dict) -> str:
    """完整 evidence 写入评估方私有目录(E4)。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(evidence, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return str(p)


def load_builder_run_evidence(path: Path | str) -> dict[str, Any]:
    """读取完整 evidence 并做格式/自洽基础校验。"""
    p = Path(path)
    if not p.is_file():
        raise BuilderProvenanceError(
            f"Builder Run Evidence 文件不存在: {p.name}(已脱敏;"
            f"评估方私有目录必须提供完整 evidence)")
    try:
        evidence = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise BuilderProvenanceError(
            f"Builder Run Evidence 无法解析: {exc}") from exc
    if not isinstance(evidence, dict) or evidence.get(
            "format") != BUILDER_RUN_EVIDENCE_FORMAT:
        raise BuilderProvenanceError(
            f"Builder Run Evidence 必须是 {BUILDER_RUN_EVIDENCE_FORMAT!r}"
            f" dict(收到 {type(evidence).__name__};2.6.0h 的 v2 "
            f"evidence 已被 v3 执行器拒绝)")
    if builder_run_evidence_hash(evidence) != str(
            evidence.get("evidence_hash") or ""):
        raise BuilderProvenanceError(
            "Builder Run Evidence 自身哈希不自洽(被改写;EXAM_INVALID)")
    return evidence
