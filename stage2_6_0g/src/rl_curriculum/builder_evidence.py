"""Builder Run Evidence 与确定性证明(阶段 2.6.0g 收尾:工作包 E)。

新增正式 Builder Run Evidence(builder-run-evidence-v1):把一次正式
构建的全部信任输入与产物哈希绑定进单一规范化对象:

- Builder manifest hash(npb-,Provider identity);
- Provider config hash(pcf-,评估方配置身份);
- Builder 协议版本;
- Runner code hash(rtb-,隔离 Runner 最小运行时逐文件内容);
- Runner sandbox/profile hash(brp-,沙箱配置);
- staged Builder tree hash(npb- tree,执行副本身份);
- frozen request hash(nbr-,冻结构建请求);
- runtime dependency lock hash(nrl-,Runner 实际 import 审计派生,
  不是配置自报);
- attempt policy hash(nap-,attempt 上限与选定规则);
- attempt log hash(nal-,规范化 attempt 合同);
- output canonical pack hash(np-)+ pack schema/version;
- run status + 确定性结论(两次 precommit 运行完全一致)。

确定性证明(E2/E3):

- 承诺创建前,在两个**全新、独立**的 Runner 进程中运行同一 Builder,
  要求 run1 与 run2 的 pack hash / attempt log hash / runtime lock
  hash 三组完全一致;不一致 -> Builder 不确定,不得创建承诺;
- 正式考试时第三次重放(全新 Runner),要求 exam replay == run1 ==
  run2,同时对账 request/attempt log/runtime lock/runner code/
  sandbox profile/builder staging identity。

证据绑定(E4):公开 commitment 只携带 evidence hash + 非敏感摘要
(核心字段全部是哈希与版本,不含 seed/源码内容);完整 evidence
(含 runtime lock 逐条目、attempt log 全文、access 摘要)保存在
独立评估方私有目录;正式执行器读取完整 evidence、重算 bre- 并
逐项验证——不能只信任 deterministic=true 布尔值。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.builder_provenance import (
    BUILDER_RUN_MODE_EXECUTION,
    BUILDER_RUN_MODE_MOCK_ASSEMBLY,
    BuilderProvenanceError,
    attempt_log_hash,
    frozen_build_request_hash,
    runtime_lock_hash,
    run_mock_assembly,
)

BUILDER_RUN_EVIDENCE_FORMAT = "builder-run-evidence-v1"

#: evidence 核心字段(进入 bre- 哈希与公开承诺摘要;detail 不进哈希)
EVIDENCE_CORE_FIELDS: tuple[str, ...] = (
    "format", "mode", "builder_manifest_hash", "provider_config_hash",
    "builder_protocol", "runner_code_hash", "sandbox_profile_hash",
    "staged_tree_hash", "frozen_request_hash", "runtime_lock_hash",
    "attempt_policy_hash", "attempt_log_hash", "output_pack_hash",
    "output_pack_format", "output_pack_version", "run_status",
    "deterministic", "runs",
)


class BuilderUncertainError(RuntimeError):
    """Builder 不确定(precommit 双重运行结果不一致;不得创建承诺)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


def provider_config_hash(provider: Any) -> str:
    """Provider 配置身份(pcf-)。

    private:provider_config.json 文件内容哈希;mock:公开 provider
    构造参数的确定性哈希。
    """
    root = getattr(provider, "root", None)
    if root is not None:
        cfg = Path(root) / "provider_config.json"
        if cfg.is_file():
            return "pcf-" + hashlib.sha256(
                cfg.read_bytes()).hexdigest()
    payload = {"format": "mock-builder-provider", "provider": "mock"}
    return "pcf-" + _canonical_json_hash(payload)


def attempt_policy_hash(request: dict[str, Any]) -> str:
    """attempt 政策哈希(nap-):上限与"首个通过即选定"规则。"""
    payload = {
        "format": "builder-attempt-policy-v1",
        "max_attempts": int(request.get("max_attempts") or 0),
        "selection": "first_pass",
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
            f" dict(收到 {type(evidence).__name__})")
    return "bre-" + _canonical_json_hash(
        builder_run_evidence_core(evidence))


def _run_triad(run: dict[str, Any]) -> dict[str, str]:
    """单次运行的三组一致性 hash(pack/attempt log/runtime lock)。"""
    return {
        "pack_hash": str(run["pack_hash"]),
        "attempt_log_hash": attempt_log_hash(run["attempt_log"]),
        "runtime_lock_hash": runtime_lock_hash(run["runtime_lock"]),
    }


def build_builder_run_evidence(
    *, identity: Any, request: dict[str, Any], runs: list[dict[str, Any]],
    provider: Any,
) -> dict[str, Any]:
    """从两次 precommit run record 组装完整 Builder Run Evidence。

    runs 必须恰好两次(两个全新独立 Runner 进程/组装运行),三组
    hash 必须完全一致(不一致应已在 precommit 阶段抛出
    BuilderUncertainError;此处再防御性断言)。
    """
    if len(runs) != 2:
        raise BuilderProvenanceError(
            f"Builder Run Evidence 必须绑定恰好两次 precommit 运行"
            f"(收到 {len(runs)} 次;E2)")
    triads = [_run_triad(r) for r in runs]
    if triads[0] != triads[1]:
        raise BuilderUncertainError(
            f"precommit 双重运行不一致:run1 {triads[0]} vs run2 "
            f"{triads[1]}(Builder 不确定,不得创建承诺)")
    run = runs[0]
    mode = str(run["mode"])
    pack = run["pack"]
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
        "runtime_lock_hash": triads[0]["runtime_lock_hash"],
        "attempt_policy_hash": attempt_policy_hash(request),
        "attempt_log_hash": triads[0]["attempt_log_hash"],
        "output_pack_hash": triads[0]["pack_hash"],
        "output_pack_format": "exam-pack",
        "output_pack_version": str(getattr(pack, "version", "") or ""),
        "run_status": str(run["status"]),
        "deterministic": True,
        "runs": [
            {"run": 1, **triads[0]}, {"run": 2, **triads[1]}],
    }
    evidence = dict(core)
    evidence["detail"] = {
        "runtime_lock": dict(run["runtime_lock"]),
        "attempt_log": dict(run["attempt_log"]),
        "access_summary": dict(run.get("access_summary") or {}),
        "runner_isolated_process": bool(
            run.get("isolated_process", mode == BUILDER_RUN_MODE_EXECUTION)),
    }
    evidence["evidence_hash"] = builder_run_evidence_hash(evidence)
    return evidence


# ------------------------------------------------------------ precommit
def _run_once_for_mode(
    provider: Any, request: dict[str, Any], *,
    builder_root: Path | str | None,
    staging_base: Path | str | None = None,
) -> dict[str, Any]:
    """按 mode 分派单次运行(隔离 Runner / mock 重组装)。"""
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
        try:
            return run_isolated_builder_run(
                provider.builder_identity(), request,
                builder_root=root, staging_base=staging_base)
        except BuilderRunnerError as exc:
            raise BuilderProvenanceError(
                f"隔离 Builder Runner 运行失败: {exc}") from exc
    if mode == BUILDER_RUN_MODE_MOCK_ASSEMBLY:
        return run_mock_assembly(request)
    raise BuilderProvenanceError(f"未知构建运行模式 {mode!r}")


def precommit_builder_runs(
    provider: Any, request: dict[str, Any], *,
    builder_root: Path | str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """E2:承诺创建前的双重运行(两个全新独立 Runner 进程)。

    run1 与 run2 的 pack hash / attempt log hash / runtime lock hash
    必须完全一致;不一致 -> BuilderUncertainError(Builder 不确定,
    不能创建承诺)。返回 (evidence, run_records)。
    """
    from rl_curriculum.builder_provenance import check_frozen_build_request

    check_frozen_build_request(request)
    identity = provider.builder_identity()
    runs = [
        _run_once_for_mode(provider, request, builder_root=builder_root),
        _run_once_for_mode(provider, request, builder_root=builder_root),
    ]
    triads = [_run_triad(r) for r in runs]
    if triads[0] != triads[1]:
        raise BuilderUncertainError(
            f"precommit 双重运行不一致:run1 {triads[0]} vs run2 "
            f"{triads[1]}(读取系统时间/未冻结随机种子/网络响应/文件"
            f"目录顺序等不确定性来源;Builder 不得进入正式承诺)")
    evidence = build_builder_run_evidence(
        identity=identity, request=request, runs=runs, provider=provider)
    return evidence, runs


# ------------------------------------------------------------ 验证(E3/E4)
def verify_builder_run_evidence(
    evidence: dict[str, Any], *,
    commitment: Any, identity: Any, request_hash: str,
) -> None:
    """E4:读取完整 evidence、重算 bre- 并逐项验证(fail closed)。

    - evidence 格式/哈希自洽(重算 bre- == evidence.evidence_hash ==
      commitment 摘要中的 evidence_hash);
    - 核心字段与承诺摘要逐项一致(mode/三组 hash/runner/sandbox/
      staged tree/deterministic);
    - precommit 双跑三组 hash 完全一致(runs[0] == runs[1]);
    - staged_tree_hash == identity.package_tree.tree_hash;
    - builder_manifest_hash == identity.manifest_hash(npb- 对账);
    - frozen_request_hash == 重算 nbr-(与 verify_builder_provenance
      传入值一致);
    - output_pack_hash == commitment.pack_hash;
    - deterministic 必须为 True 且 run_status == ok。
    """
    summary = dict(getattr(
        commitment, "builder_run_evidence", {}) or {})
    if not summary:
        raise BuilderProvenanceError(
            "承诺缺少 builder_run_evidence 绑定(v8 承诺必须绑定 "
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
                "output_pack_hash", "staged_tree_hash", "deterministic"):
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
    runs = list(core.get("runs") or [])
    triad_keys = ("pack_hash", "attempt_log_hash", "runtime_lock_hash")
    if len(runs) != 2 or any(
            runs[0].get(k) != runs[1].get(k) for k in triad_keys):
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
            "evidence 的 builder_manifest_hash 与 Provider identity "
            "不一致(npb- 对账失败;EXAM_INVALID)")
    if str(core.get("frozen_request_hash") or "") != str(request_hash):
        raise BuilderProvenanceError(
            "evidence 的 frozen_request_hash 与冻结构建请求重算哈希"
            "不一致(nbr- 对账失败;EXAM_INVALID)")
    if str(core.get("output_pack_hash") or "") != str(
            commitment.pack_hash):
        raise BuilderProvenanceError(
            "evidence 的 output_pack_hash 与承诺 pack_hash 不一致"
            "(EXAM_INVALID)")
    mode = str(core.get("mode") or "")
    if mode not in (BUILDER_RUN_MODE_EXECUTION,
                    BUILDER_RUN_MODE_MOCK_ASSEMBLY):
        raise BuilderProvenanceError(
            f"evidence 的 mode {mode!r} 不在预注册范围(EXAM_INVALID)")
    # E4:完整 evidence 的 detail 内容逐项验证——detail.attempt_log 与
    # detail.runtime_lock 是"完整 evidence"的实质内容,重算哈希必须与
    # 核心字段的 nal-/nrl- 一致(篡改 detail 绕过 bre- 的攻击被拒绝)
    detail = evidence.get("detail") or {}
    if not isinstance(detail, dict):
        raise BuilderProvenanceError(
            "evidence 缺少 detail(完整运行证据:runtime_lock/attempt_"
            "log/access 摘要;不能只信任核心摘要)")
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


def replay_builder_for_evidence(
    provider: Any, *, request: dict[str, Any],
    builder_evidence: dict[str, Any],
    builder_root: Path | str | None = None,
) -> dict[str, Any]:
    """E3:考试期第三次重放(全新 Runner/组装)并对账 evidence。

    三组 hash(pack/attempt log/runtime lock)必须与 precommit
    run1 == run2 == 本次完全一致;runner code/sandbox profile 同步
    对账(代码或配置漂移即拒绝)。
    """
    run = _run_once_for_mode(
        provider, request, builder_root=builder_root)
    triad = _run_triad(run)
    core = builder_run_evidence_core(builder_evidence)
    expected = {
        "pack_hash": str(core.get("output_pack_hash") or ""),
        "attempt_log_hash": str(core.get("attempt_log_hash") or ""),
        "runtime_lock_hash": str(core.get("runtime_lock_hash") or ""),
    }
    if triad != expected:
        raise BuilderProvenanceError(
            f"考试期第三次重放与 precommit evidence 不一致:replay "
            f"{triad} vs evidence {expected}(读取系统时间/未冻结随机"
            f"种子/依赖漂移等不确定性;Builder 确定性不成立;"
            f"EXAM_INVALID)")
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
            f" dict(收到 {type(evidence).__name__})")
    if builder_run_evidence_hash(evidence) != str(
            evidence.get("evidence_hash") or ""):
        raise BuilderProvenanceError(
            "Builder Run Evidence 自身哈希不自洽(被改写;EXAM_INVALID)")
    return evidence
