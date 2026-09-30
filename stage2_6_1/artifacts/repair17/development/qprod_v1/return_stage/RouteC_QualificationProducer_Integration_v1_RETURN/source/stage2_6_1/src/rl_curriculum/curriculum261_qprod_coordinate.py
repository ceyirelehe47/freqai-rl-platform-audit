# -*- coding: utf-8 -*-
"""QProd 坐标锁与坐标级审计执行(显式 namespace 贯通共同核心)。

解决既有接口事实:`run_cue_contract_audit` 将显式 namespace 参数判为
非正式调用,不能与 require_locked_plan 组合。本模块不复制审计算法,
而是调用从其中抽取的共同执行核心
`_run_cue_contract_audit_core`(同一实现;旧默认 wrapper 保持原行为),
在锁定且身份匹配的坐标上下文里显式传递 namespace/seed/block_index/
attempt/sentinel/detector/审计预算,并以 report_actual_values=True
让报告记录实际 namespace/MC/block 预算(不允许"计算用新 namespace、
报告写旧常量";不允许把实际 4096 MC 写成 1e6)。

工程/正式规模合同:
- engineering:缩减设置事前入计划并显式标注 ENGINEERING_ONLY
  (blocks=2/corpus,MC=4096/坐标,global-K tier1≤2000,禁 tier2);
- formal:预算必须等于正式常量(500/1e6/50000+tier2)——正式 profile
  不因显式坐标参数偷偷降为工程规模;锁计划时即拒绝不匹配预算。

无许可反例计真实叶调用为 0(拒绝先于任何生成调用);合法工程正例
实际到达原生生成/审计内核(计数钩子逐调用记账,含 attempts 整 block
结构重试与 once/attempts 逐位一致性检查中的生成重放)。
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_QPROD_ENGINEERING_NAMESPACES,
)
from rl_curriculum.curriculum261_qprod_context import (
    QProdContext, QProdContextError, _canonical_json,
)
from rl_curriculum.curriculum261_qprod_permit import LivePermitToken
from rl_curriculum.curriculum261_qprod_plan import (
    load_research_plan, research_plan_structure_problems,
)

#: 工程/正式规模常量(正式值 = r17_cue_contract 冻结合同)。
QPROD_ENG_BLOCKS_PER_CORPUS = 2
QPROD_ENG_MC_EVENTS = 4096
QPROD_ENG_GLOBAL_K_TIER1 = 2000
QPROD_MAX_ATTEMPTS = 5
FORMAL_BLOCKS_PER_CORPUS = 500
FORMAL_MC_EVENTS = 1_000_000

QPROD_COORDINATE_AUDIT_PLAN_FORMAT = "cur261-qprod-coordinate-audit-plan-v1"
QPROD_COORDINATE_AUDIT_PLAN_PREFIX = "qcap-"
QPROD_COORDINATE_AUDIT_PLAN_NAME = "qprod_coordinate_audit_plan.json"
QPROD_COORDINATE_SEAL_NAME = "qprod_coordinate_seal.json"
QPROD_COORDINATE_INTERRUPTED_NAME = "qprod_coordinate_interrupted.json"
QPROD_BLOCK_SEED_LOG_NAME = "qprod_block_seed_log.jsonl"
QPROD_QUOTA_LEDGER_NAME = "qprod_quota_ledger.jsonl"

#: 坐标审计计划代码身份模块(冻结合同 = cue 合同模块 + 本族模块)。
QPROD_COORDINATE_CODE_MODULES = (
    "curriculum261_api.py",
    "curriculum261_c2.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r17_noise_replay.py",
    "curriculum261_r17_cue_contract.py",
    "curriculum261_r17_global_k.py",
    "curriculum261_qprod_context.py",
    "curriculum261_qprod_permit.py",
    "curriculum261_qprod_plan.py",
    "curriculum261_qprod_coordinate.py",
    "curriculum261_qprod_aggregate.py",
)


def qprod_coordinate_code_identity() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in QPROD_COORDINATE_CODE_MODULES:
        f = root / name
        out[name] = (hashlib.sha256(f.read_bytes()).hexdigest()
                     if f.is_file() else "MISSING")
    return out


def coordinate_audit_plan_digest(payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items()
            if k not in ("coordinate_audit_plan_digest", "locked_utc")}
    return QPROD_COORDINATE_AUDIT_PLAN_PREFIX + hashlib.sha256(
        _canonical_json(body).encode("utf-8")).hexdigest()


def _budgets_for(profile: str) -> dict[str, Any]:
    if profile == "engineering":
        return {
            "blocks_per_corpus": QPROD_ENG_BLOCKS_PER_CORPUS,
            "mc_events": QPROD_ENG_MC_EVENTS,
            "global_k_tier1": QPROD_ENG_GLOBAL_K_TIER1,
            "global_k_tier2": None,
            "engineering_only": True,
        }
    if profile == "formal":
        return {
            "blocks_per_corpus": FORMAL_BLOCKS_PER_CORPUS,
            "mc_events": FORMAL_MC_EVENTS,
            "global_k_tier1": None,   # 正式 tier 走核心 formal 分支
            "global_k_tier2": None,
            "engineering_only": False,
        }
    raise QProdContextError(f"未知 profile {profile!r}")


def _coordinate_from_manifest(research_plan: dict[str, Any],
                              coordinate_id: str) -> dict[str, Any]:
    for c in research_plan["coordinate_manifest"]:
        if c.get("coordinate_id") == coordinate_id:
            return c
    raise QProdContextError(
        f"坐标 {coordinate_id!r} 不在冻结研究计划清单内"
        f"(清单外输出不得进入主聚合)")


def lock_coordinate_audit_plan(
        coord_dir: Path | str, *, coordinate: dict[str, Any],
        research_plan: dict[str, Any]) -> tuple[Path, str]:
    """锁定坐标级审计计划(任何该坐标数据生成之前;create-only)。

    预算与 profile 一致性在此拒绝:engineering 必须等于显式缩减
    ENGINEERING_ONLY 值;formal 必须等于正式常量(不偷偷降级)。
    """
    coord_dir = Path(coord_dir)
    if coord_dir.name != str(coordinate.get("artifact_subdir")):
        raise QProdContextError(
            f"坐标产物目录 {coord_dir.name!r} != 计划声明 "
            f"{coordinate.get('artifact_subdir')!r}")
    profile = str(research_plan.get("profile", ""))
    budgets = _budgets_for(profile)
    settings = {
        "blocks_per_corpus": int(coordinate.get(
            "blocks_per_corpus", budgets["blocks_per_corpus"])),
        "mc_events": int(coordinate.get(
            "mc_events", budgets["mc_events"])),
        "max_attempts": int(coordinate.get(
            "max_attempts", QPROD_MAX_ATTEMPTS)),
    }
    if settings["blocks_per_corpus"] != budgets["blocks_per_corpus"] \
            or settings["mc_events"] != budgets["mc_events"]:
        raise QProdContextError(
            f"坐标预算 {settings} 与 profile={profile!r} 的合同预算 "
            f"({{'blocks_per_corpus': budgets['blocks_per_corpus'], "
            f"'mc_events': budgets['mc_events']}}) 不一致"
            f"(工程须显式缩减标注;正式不得降级)")
    for key in ("model_namespace", "validation_namespace"):
        ns = coordinate.get(key)
        if ns not in CURRICULUM261_QPROD_ENGINEERING_NAMESPACES:
            raise QProdContextError(
                f"坐标 namespace {ns!r} 未注册(QProd 工程名单;"
                f"守卫不接受任意字符串)")
    from rl_curriculum.curriculum261_r17_cue_contract import (
        C2_REFERENCE_DEFAULTS, cue_semantic_contract_digest,
    )
    thr = dict(C2_REFERENCE_DEFAULTS)
    payload = {
        "format": QPROD_COORDINATE_AUDIT_PLAN_FORMAT,
        "coordinate_id": coordinate["coordinate_id"],
        "research_plan_digest": research_plan["research_plan_digest"],
        "profile": profile,
        "budgets": {**budgets, **settings},
        "namespaces": {
            "model": coordinate["model_namespace"],
            "validation": coordinate["validation_namespace"],
        },
        "block_range": {
            "start_index": int(coordinate.get("block_start_index", 0)),
            "count": settings["blocks_per_corpus"],
        },
        "generation_mode": {"model": "once", "validation": "attempts"},
        "sentinel_ladder": "冻结 cur261-c2-v9 默认 D0-D3"
                           "(curriculum261_c2.C2_RUNG_PARAMS)",
        "frozen_detector": {
            "cue_thr": float(thr["cue_thr"]),
            "feature": "%-ret-1",
            "episode_bars": 288,
        },
        "semantic_contract_digest": cue_semantic_contract_digest(),
        "code_identity": qprod_coordinate_code_identity(),
    }
    digest = coordinate_audit_plan_digest(payload)
    payload["coordinate_audit_plan_digest"] = digest
    payload["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    coord_dir.mkdir(parents=True, exist_ok=True)
    path = coord_dir / QPROD_COORDINATE_AUDIT_PLAN_NAME
    if path.is_file():
        raise QProdContextError(
            f"坐标审计计划已锁定 {path};禁止修改/重锁(关锁或换坐标"
            f"冒充正式审计拒绝)")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    (coord_dir / "qprod_coordinate_audit_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    return path, digest


def load_coordinate_audit_plan(coord_dir: Path | str) -> dict[str, Any]:
    coord_dir = Path(coord_dir)
    path = coord_dir / QPROD_COORDINATE_AUDIT_PLAN_NAME
    if not path.is_file():
        raise QProdContextError(
            f"坐标审计计划未锁定 {path}(锁定上下文外的审计拒绝;"
            f"fail closed)")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = coordinate_audit_plan_digest(payload)
    stored = (coord_dir /
              "qprod_coordinate_audit_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    if stored != digest:
        raise QProdContextError(
            "坐标审计计划 digest 复算不一致(fail closed)")
    drift = {k: (payload["code_identity"].get(k), v) for k, v in
             qprod_coordinate_code_identity().items()
             if payload["code_identity"].get(k) != v}
    if drift:
        raise QProdContextError(
            f"坐标审计计划代码身份漂移(锁定后相关模块不得修改): "
            f"{sorted(drift)}")
    return payload


class _GenerationLedger:
    """叶调用计数钩子(once/attempts/逐位重放;逐调用记账+块归属)。

    raw_dir 给定时,每个成功正文 block 的原始 df/hidden 逐 rung/side
    落盘(E01:原始 OHLCV/hidden/trace 归档,供 reader 与 reviewer
    只读复算);完整性重放的输入即已归档正文,不重复落盘。
    """

    def __init__(self, raw_dir: Path | None = None) -> None:
        self.leaf_calls = {"once": 0, "attempts": 0,
                           "bitwise_replay": 0}
        self.block_log: list[dict[str, Any]] = []
        self._once_impl = None
        self._attempts_impl = None
        self._once_seq: dict[str, int] = {}
        self.raw_dir = Path(raw_dir) if raw_dir is not None else None

    def _archive_episodes(self, tag: str,
                          episodes: dict[str, Any]) -> None:
        if self.raw_dir is None:
            return
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        for rung, sides in episodes.items():
            for side, ep in sides.items():
                stem = f"{tag}_{rung}_{side}"
                ep.df.to_csv(self.raw_dir / f"{stem}.df.csv",
                             index=False)
                ep.hidden.to_csv(self.raw_dir / f"{stem}.hidden.csv",
                                 index=False)

    def bind(self) -> dict[str, Any]:
        from rl_curriculum.curriculum261_r6_tape import (
            generate_matched_block_once,
            generate_matched_block_with_attempts,
        )
        from rl_curriculum.curriculum261_r17_noise_replay import (
            matched_block_seed_of,
        )
        self._once_impl = generate_matched_block_once
        self._attempts_impl = generate_matched_block_with_attempts
        ledger = self

        def counting_once(ladder, seed, ns):
            ledger.leaf_calls["once"] += 1
            seq = ledger._once_seq.get(ns, 0)
            ledger._once_seq[ns] = seq + 1
            ledger.block_log.append({
                "kind": "once", "namespace": ns,
                "sequence": seq,
                "block_seed": int(seed),
                "derivation": "derive261_block_seed(ns, block_index,"
                              " attempt=0)(core 内部派生;"
                              f"sequence={seq})",
            })
            episodes = ledger._once_impl(ladder, seed, ns)
            ledger._archive_episodes(
                f"once_{ns}_s{seq}_seed{int(seed)}", episodes)
            return episodes

        def counting_attempts(ladder, *, namespace, block_index):
            ledger.leaf_calls["attempts"] += 1
            block = ledger._attempts_impl(
                ladder, namespace=namespace, block_index=block_index)
            log = block.attempt_log
            ledger.block_log.append({
                "kind": "attempts", "namespace": namespace,
                "block_index": int(block.block_index),
                "block_seed": int(matched_block_seed_of(block)),
                "selected_attempt": (
                    None if log.selected_attempt is None
                    else int(log.selected_attempt)),
                "attempts_made": len(log.attempts),
            })
            ledger._archive_episodes(
                f"attempts_{namespace}_b{int(block.block_index)}"
                f"_a{int(log.selected_attempt or 0)}",
                block.episodes)
            return block

        def counting_bitwise_replay(ladder, seed, ns):
            # 完整性检查中的生成重放计入叶调用配额(单独归类;
            # 输入=已归档正文,不重复落盘)
            ledger.leaf_calls["bitwise_replay"] += 1
            return ledger._once_impl(ladder, seed, ns)

        return {"generate_once": counting_once,
                "generate_attempts": counting_attempts,
                "generate_bitwise_once": counting_bitwise_replay}

    def totals(self) -> dict[str, Any]:
        calls = (self.leaf_calls["once"] + self.leaf_calls["attempts"]
                 + self.leaf_calls["bitwise_replay"])
        return {
            "leaf_calls_total": calls,
            "leaf_calls_by_kind": dict(self.leaf_calls),
            "episode_calls_estimate": calls * 8,
            "n_blocks_generated": (
                self.leaf_calls["once"] + self.leaf_calls["attempts"]),
        }


def _ledger_append(ledger_path: Path, record: dict[str, Any]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ledger_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False,
                            sort_keys=True) + "\n")
        fh.flush()


def _write_interrupted(coord_dir: Path, reason: str,
                        ledger: _GenerationLedger,
                        extra: dict[str, Any] | None = None) -> None:
    payload = {
        "format": "cur261-qprod-coordinate-interrupted-v1",
        "coordinate_dir": str(coord_dir),
        "reason": reason,
        "generation_at_interruption": ledger.totals(),
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "未完成不冒称完整结果;不自动重抽;重启须新坐标目录"
                "与新许可",
        **(extra or {}),
    }
    (coord_dir / QPROD_COORDINATE_INTERRUPTED_NAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8")


def run_coordinate_audit_locked(
        ctx: QProdContext, live_permit: LivePermitToken,
        coordinate_id: str, *, coord_dir: Path,
        ledger_path: Path) -> dict[str, Any]:
    """锁定坐标上下文下的坐标级审计(真实到达原生生成/审计内核)。

    前置顺序(全部先于任何生成调用):
    研究计划冻结+结构+digest+坐标在册 → 代码身份零漂移 →
    坐标审计计划锁定且与清单一致 → 许可已消费(level/scope 匹配)→
    坐标目录新鲜(无 seal/interrupted)。任一失败:拒绝记录携带
    叶调用计数快照(=0),配额账本记 refused 行。
    """
    from rl_curriculum.curriculum261_r17_cue_contract import (
        _run_cue_contract_audit_core,
    )

    coord_dir = Path(coord_dir)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    refusal = {
        "format": "cur261-qprod-coordinate-refusal-v1",
        "coordinate_id": coordinate_id,
        "leaf_calls_snapshot": {"once": 0, "attempts": 0,
                                "bitwise_replay": 0,
                                "leaf_calls_total": 0},
        "utc": now,
    }

    def _refuse(reason: str) -> QProdContextError:
        refusal["reason"] = reason
        (coord_dir.parent / f"refusal_{coordinate_id}.json"
         ).write_text(json.dumps(refusal, indent=2, ensure_ascii=False),
                      encoding="utf-8")
        _ledger_append(Path(ledger_path), {
            "action": "refused", "coordinate_id": coordinate_id,
            "reason": reason, "leaf_calls_total": 0, "utc": now})
        return QProdContextError(reason)

    # 1. 研究计划冻结 + 结构 + 层/迭代一致
    research_plan = load_research_plan(ctx.state_root)
    problems = research_plan_structure_problems(research_plan)
    if problems:
        raise _refuse(f"研究计划结构问题: {problems}")
    if research_plan.get("level") != ctx.level or research_plan.get(
            "iteration_id") != ctx.iteration_id:
        raise _refuse("研究计划层/迭代与上下文不一致(A/B 隔离)")
    try:
        coordinate = _coordinate_from_manifest(research_plan, coordinate_id)
    except QProdContextError as exc:
        raise _refuse(str(exc)) from exc
    # 2. 代码身份零漂移(计划锁定 vs 当前)
    plan_ident = dict(research_plan.get("code_identity") or {})
    current_ident = qprod_coordinate_code_identity()
    drift = {k: (plan_ident.get(k), current_ident.get(k))
             for k in current_ident
             if plan_ident.get(k) != current_ident.get(k)}
    if drift:
        raise _refuse(f"研究计划代码身份漂移: {sorted(drift)}")
    # 3. 坐标审计计划锁定且与清单一致(锁未关、身份匹配)
    try:
        cap = load_coordinate_audit_plan(coord_dir)
    except QProdContextError as exc:
        raise _refuse(f"坐标审计计划不可用: {exc}") from exc
    if cap["coordinate_id"] != coordinate_id:
        raise _refuse("坐标审计计划 id 与请求不一致")
    if cap["research_plan_digest"] != research_plan[
            "research_plan_digest"]:
        raise _refuse("坐标审计计划未绑定当前冻结研究计划")
    if (cap["namespaces"]["model"] != coordinate["model_namespace"]
            or cap["namespaces"]["validation"]
            != coordinate["validation_namespace"]):
        raise _refuse("坐标审计计划 namespace 与清单不一致")
    # 4. 许可(先于任何生成)
    if live_permit.permit.get("task_level") != "level_b":
        raise _refuse("坐标审计要求 level_b 活动许可(错层拒绝)")
    declared_ns = set(live_permit.permit["preregistered_input_scope"]
                      .get("namespaces") or [])
    for ns in (coordinate["model_namespace"],
               coordinate["validation_namespace"]):
        if ns not in declared_ns:
            raise _refuse(f"namespace {ns!r} 不在许可预注册 scope 内")
    # 5. 坐标目录新鲜(重复/终态/中断重入拒绝)
    if (coord_dir / QPROD_COORDINATE_SEAL_NAME).is_file():
        raise _refuse("坐标目录已封存(sealed);终态重入拒绝")
    if (coord_dir / QPROD_COORDINATE_INTERRUPTED_NAME).is_file():
        raise _refuse(
            "坐标目录存在中断标记;不得换参数/换目录救活已消费运行"
            "(中断保留可归属记录,不自动重抽)")

    profile = str(cap["profile"])
    formal = profile == "formal"
    ledger = _GenerationLedger(raw_dir=coord_dir / "raw_episodes")
    hooks = ledger.bind()
    _ledger_append(Path(ledger_path), {
        "action": "start", "coordinate_id": coordinate_id,
        "profile": profile,
        "namespaces": [coordinate["model_namespace"],
                       coordinate["validation_namespace"]],
        "budgets": cap["budgets"], "utc": now})
    try:
        report = _run_cue_contract_audit_core(
            coord_dir,
            n_blocks_per_corpus=int(cap["budgets"]["blocks_per_corpus"]),
            n_mc_events=int(cap["budgets"]["mc_events"]),
            model_ns=coordinate["model_namespace"],
            validation_ns=coordinate["validation_namespace"],
            formal=formal,
            report_actual_values=True,
            coordinate_context={
                "coordinate_id": coordinate_id,
                "research_plan_digest": research_plan[
                    "research_plan_digest"],
                "coordinate_audit_plan_digest": cap[
                    "coordinate_audit_plan_digest"],
                "profile": profile,
                "engineering_only": bool(
                    cap["budgets"].get("engineering_only")),
                "level": ctx.level,
                "iteration_id": ctx.iteration_id,
            },
            generation_hooks=hooks,
        )
    except BaseException as exc:  # 中断/失败:可归属记录,不自动重抽
        _write_interrupted(coord_dir, f"{type(exc).__name__}: {exc}",
                           ledger)
        (coord_dir / QPROD_BLOCK_SEED_LOG_NAME).write_text(
            "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True)
                      for e in ledger.block_log) + "\n", encoding="utf-8")
        _ledger_append(Path(ledger_path), {
            "action": "interrupted", "coordinate_id": coordinate_id,
            "error": f"{type(exc).__name__}: {exc}",
            **ledger.totals(),
            "utc": datetime.now(timezone.utc).isoformat(
                timespec="seconds")})
        raise

    # 块级 seed/attempt 归属日志(钩子逐调用捕获;once 侧 block_index
    # 由 seed 与 (ns, i, 0) 派生公式对拍还原,见聚合 reader)
    (coord_dir / QPROD_BLOCK_SEED_LOG_NAME).write_text(
        "\n".join(json.dumps(e, ensure_ascii=False, sort_keys=True)
                  for e in ledger.block_log) + "\n", encoding="utf-8")

    totals = ledger.totals()
    successful_episodes = int(cap["budgets"]["blocks_per_corpus"]) * 8 * 2
    _ledger_append(Path(ledger_path), {
        "action": "complete", "coordinate_id": coordinate_id,
        "profile": profile,
        "mc_events": int(cap["budgets"]["mc_events"]),
        "audit_pass": bool(report.get("pass")),
        "audit_digest": report.get("audit_digest"),
        "successful_episodes": successful_episodes,
        **totals,
        "utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})

    members = {}
    for name in ("cue_contract_audit.json", "cue_event_trace.jsonl",
                 QPROD_BLOCK_SEED_LOG_NAME):
        p = coord_dir / name
        members[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    seal = {
        "format": "cur261-qprod-coordinate-seal-v1",
        "coordinate_id": coordinate_id,
        "research_plan_digest": research_plan["research_plan_digest"],
        "coordinate_audit_plan_digest": cap[
            "coordinate_audit_plan_digest"],
        "audit_digest": report["audit_digest"],
        "members_sha256": members,
        "summary": {
            "recall_validation": report["direct_generator"][
                "validation"]["empirical_recall"],
            "se_validation": report["direct_generator"]["validation"][
                "block_cluster"]["se"],
            "p_contract_local": report["p_contract"],
            "audit_pass": bool(report["pass"]),
            "engineering_only": bool(
                cap["budgets"].get("engineering_only")),
        },
        "generation": totals,
        "sealed_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
    }
    (coord_dir / QPROD_COORDINATE_SEAL_NAME).write_text(
        json.dumps(seal, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"report": report, "seal": seal, "generation": totals}


__all__ = [
    "QPROD_ENG_BLOCKS_PER_CORPUS", "QPROD_ENG_MC_EVENTS",
    "QPROD_ENG_GLOBAL_K_TIER1", "QPROD_COORDINATE_SEAL_NAME",
    "QPROD_QUOTA_LEDGER_NAME", "lock_coordinate_audit_plan",
    "load_coordinate_audit_plan", "run_coordinate_audit_locked",
    "qprod_coordinate_code_identity", "coordinate_audit_plan_digest",
    "QPROD_COORDINATE_CODE_MODULES",
]
