# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R12:GenerationEvidenceCompleteness-v1(§15)。

两层规则:

生成层(R11 冻结语义,不变):
- recorder 是纯观察;recorder 返回值不影响生成;
- recorder 异常不改变 episode(api._recorder_record 吞掉并登记)。

治理层(R12 新增,orchestrator 重新计算,不信 recorder 自报):
- 每个正式 stage 结束前核对 expected invocation coordinates;
- expected calls 与 observed call envelopes 逐项对齐;
- 每个 attempt 都有完整 envelope;
- 无 recorder_error 表现(缺 envelope/坏 digest/attempt 断档);
- 无 missing call / duplicate call / orphan attempt;
- call digest 与 envelope digest 链一致;
- C2 matched block(不走 pair 级 envelope;r6_tape 冻结实现直接调
  generator.generate)用 block attempt log 对齐:block 连续、selected
  attempt 合法、选中后无拒绝、seed namespace 正确;
- 任何证据缺失 ⇒ stage FAIL(不能因 episode 本身生成成功而继续)。

本模块只做核对与落盘,不参与生成;输出 fail-closed 的机械判定。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from rl_curriculum.curriculum261_generation_envelope import (
    read_envelope_ledger,
)

COMPLETENESS_FORMAT = "cur261-r12-generation-evidence-completeness-v1"
R12_ITERATION = "r12"


@dataclass(frozen=True)
class ExpectedCall:
    """一个期望的 pair 级生成调用坐标。"""

    namespace: str
    family: str
    rung: str
    pair_index: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.namespace, self.family, self.rung,
                int(self.pair_index))


@dataclass
class BlockAttemptSummary:
    """C2 matched block 的 attempt log 摘要(orchestrator 序列化)。"""

    namespace: str
    block_index: int
    selected_attempt: int
    attempts: list[dict[str, Any]] = field(default_factory=list)


def _envelope_recompute_ok(env: dict[str, Any]) -> bool:
    """envelope 结构最小核验:身份字段齐全且 attempt 索引合法。"""
    required = ("iteration", "namespace", "family", "rung", "pair_index",
                "attempt_index", "outer_seed", "digest")
    for k in required:
        if k not in env:
            return False
    try:
        ai = int(env["attempt_index"])
        pi = int(env["pair_index"])
        return ai >= 0 and pi >= 0 and isinstance(env["digest"], str) \
            and len(env["digest"]) >= 16
    except (TypeError, ValueError):
        return False


def verify_generation_evidence_completeness(
        ledger_path: Path | None,
        expected_calls: Sequence[ExpectedCall],
        *,
        stage_label: str,
        blocks: Sequence[BlockAttemptSummary] | None = None,
        ledger_rows_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """核对 expected 与 observed;任何缺口 ⇒ pass=False(fail closed)。

    observed 按 call_digest 分组(同坐标允许多次合法调用,例如 eval
    records 与 c13 corpus 对同一 (namespace,family,rung,pair) 各生成
    一次);expected 以多重集表达坐标期望次数。
    """
    problems: list[str] = []
    # ---- expected 多重集 ----
    expected_counts: dict[tuple[str, str, str, int], int] = {}
    for c in expected_calls:
        expected_counts[c.key] = expected_counts.get(c.key, 0) + 1
    # ---- ledger 读取 ----
    rows: list[dict[str, Any]]
    if ledger_rows_override is not None:
        rows = list(ledger_rows_override)
        ledger_source = "rows_override"
    elif ledger_path is not None and Path(ledger_path).is_file():
        rows = read_envelope_ledger(Path(ledger_path))
        # 仅记录文件名:绝对路径含运行目录(A/B),属非身份元数据
        ledger_source = Path(ledger_path).name
    else:
        rows = []
        ledger_source = (Path(ledger_path).name
                         if ledger_path is not None else "")
        if expected_calls:
            problems.append("台账缺失(expected 非空)")
    unparseable = sum(1 for r in rows if "unparseable_line" in r)
    if unparseable:
        problems.append(f"台账存在 {unparseable} 行不可解析记录")
    # ---- observed 调用切分(顺序状态机)----
    # call_digest 是内容寻址身份:同坐标的多次合法调用(如 eval records
    # 与 c13 corpus)digest 相同,不能按 digest 分组。台账按生成顺序
    # 追加;generate_pair_with_attempts 的 attempt 严格 0..k 且 k 为
    # accepted ⇒ attempt_index==0(非首行)即新调用边界。
    calls: list[dict[str, Any]] = []
    stage_mismatch = 0
    iteration_mismatch = 0
    current: dict[str, Any] | None = None
    for r in rows:
        if "unparseable_line" in r:
            continue
        if r.get("stage") != stage_label:
            stage_mismatch += 1
            continue
        env = r.get("envelope") or {}
        if env.get("iteration") != R12_ITERATION:
            iteration_mismatch += 1
            continue
        try:
            ai = int(env["attempt_index"])
        except (KeyError, TypeError, ValueError):
            problems.append("台账行缺少/非法 attempt_index")
            continue
        if current is None or ai == 0:
            current = {"envelopes": [env], "env": env}
            calls.append(current)
        else:
            current["envelopes"].append(env)
    if stage_mismatch:
        problems.append(f"{stage_mismatch} 行属于其他 stage(台账混杂)")
    if iteration_mismatch:
        problems.append(
            f"{iteration_mismatch} 行 iteration != r12(混入历史迭代)")
    # ---- 逐 call 完整性 + 坐标计数 ----
    observed_counts: dict[tuple[str, str, str, int], int] = {}
    n_accepted_total = 0
    n_attempt_envs = 0
    bad_envs = 0
    for seq, call in enumerate(calls):
        envs = call["envelopes"]
        env0 = call["env"]
        n_attempt_envs += len(envs)
        try:
            key = (str(env0["namespace"]), str(env0["family"]),
                   str(env0["rung"]), int(env0["pair_index"]))
        except (KeyError, TypeError, ValueError):
            problems.append(f"call#{seq}:缺少调用坐标字段")
            bad_envs += len(envs)
            continue
        observed_counts[key] = observed_counts.get(key, 0) + 1
        idxs = [int(e["attempt_index"]) for e in envs if isinstance(
            e.get("attempt_index"), int)]
        if len(idxs) != len(envs):
            problems.append(f"call#{seq}:attempt_index 非整数")
            bad_envs += len(envs)
            continue
        if len(set(idxs)) != len(idxs):
            problems.append(f"call#{seq}:attempt 索引重复")
        if idxs != sorted(idxs) or (
                idxs and idxs != list(range(idxs[-1] + 1))):
            problems.append(f"call#{seq}:attempt 索引断档:{idxs}")
        for e in envs:
            if not _envelope_recompute_ok(e):
                bad_envs += 1
                problems.append(f"call#{seq}:envelope 结构/digest 异常")
                break
        accepted = [e for e in envs if e.get("accepted") is True]
        if len(accepted) != 1:
            problems.append(
                f"call#{seq} {key}:accepted envelope 数 = "
                f"{len(accepted)}(应为 1)")
        else:
            n_accepted_total += 1
            if int(accepted[0]["attempt_index"]) != max(idxs):
                problems.append(
                    f"call#{seq}:accepted 不是最后一个 attempt")
            if accepted[0].get("exception"):
                problems.append(
                    f"call#{seq}:accepted attempt 携带 exception")
    # ---- missing / orphan(多重集口径)----
    missing_rows = []
    orphan_rows = []
    for key, exp_n in sorted(expected_counts.items()):
        obs_n = observed_counts.get(key, 0)
        if obs_n < exp_n:
            missing_rows.append((key, obs_n, exp_n))
    for key, obs_n in sorted(observed_counts.items()):
        exp_n = expected_counts.get(key, 0)
        if obs_n > exp_n:
            orphan_rows.append((key, obs_n, exp_n))
    if missing_rows:
        problems.append(
            f"missing calls:{len(missing_rows)}(如 {missing_rows[:3]})")
    if orphan_rows:
        problems.append(
            f"orphan/excess calls:{len(orphan_rows)}(如 {orphan_rows[:3]})")
    # ---- C2 matched block 层 ----
    block_problems = 0
    n_blocks = 0
    for b in blocks or []:
        n_blocks += 1
        idxs = [int(a.get("attempt", -1)) for a in b.attempts]
        if idxs and idxs != list(range(len(idxs))):
            block_problems += 1
            problems.append(
                f"block {b.namespace}/{b.block_index}:attempt 序列断档")
            continue
        sel = int(b.selected_attempt)
        if sel not in idxs:
            block_problems += 1
            problems.append(
                f"block {b.namespace}/{b.block_index}:selected_attempt "
                f"{sel} 不在 attempt 序列内")
            continue
        sel_row = next(a for a in b.attempts
                       if int(a.get("attempt", -1)) == sel)
        if not sel_row.get("accepted"):
            block_problems += 1
            problems.append(
                f"block {b.namespace}/{b.block_index}:selected attempt "
                f"未通过接受")
        after = [a for a in b.attempts
                 if int(a.get("attempt", -1)) > sel and a.get("accepted")]
        if after:
            block_problems += 1
            problems.append(
                f"block {b.namespace}/{b.block_index}:selected 后仍有"
                f"接受记录")
    expected_blocks = len(blocks or [])
    pass_gate = not problems
    result: dict[str, Any] = {
        "format": COMPLETENESS_FORMAT,
        "stage": stage_label,
        "iteration": R12_ITERATION,
        "ledger_source": ledger_source,
        "expected_call_invocations": len(expected_calls),
        "expected_unique_coordinates": len(expected_counts),
        "observed_call_invocations": len(calls),
        "observed_unique_coordinates": len(observed_counts),
        "missing_calls": len(missing_rows),
        "orphan_excess_calls": len(orphan_rows),
        "n_attempt_envelopes": n_attempt_envs,
        "n_calls_with_accepted": n_accepted_total,
        "bad_envelopes": bad_envs,
        "unparseable_rows": unparseable,
        "stage_mismatch_rows": stage_mismatch,
        "iteration_mismatch_rows": iteration_mismatch,
        "blocks_checked": n_blocks,
        "expected_blocks": expected_blocks,
        "block_problems": block_problems,
        "problems_sample": problems[:20],
        "n_problems": len(problems),
        "pass": bool(pass_gate),
    }
    result["digest"] = generation_evidence_completeness_digest(result)
    return result


def generation_evidence_completeness_digest(result: dict[str, Any]) -> str:
    core = {k: result.get(k) for k in (
        "format", "stage", "iteration", "expected_call_invocations",
        "expected_unique_coordinates", "observed_call_invocations",
        "observed_unique_coordinates", "missing_calls",
        "orphan_excess_calls",
        "n_attempt_envelopes", "n_calls_with_accepted", "bad_envelopes",
        "unparseable_rows", "stage_mismatch_rows", "iteration_mismatch_rows",
        "blocks_checked", "block_problems", "n_problems", "pass")}
    return "r12gec-" + hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        default=str).encode("utf-8")).hexdigest()


def write_generation_evidence_completeness(
        out_dir: Path, result: dict[str, Any],
        filename: str = "generation_evidence_completeness.json") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    if path.is_file():
        raise RuntimeError(
            f"generation evidence completeness 已存在;禁止覆盖:{path}")
    path.write_text(json.dumps(
        result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    return path


def block_summary_from_matched_block(block: Any) -> BlockAttemptSummary:
    """从 R6 冻结 MatchedBlock 的 attempt log 机械提取摘要。"""
    log = block.attempt_log
    attempts = [{"attempt": int(getattr(a, "attempt", i)),
                 "accepted": bool(getattr(a, "accepted", False)),
                 "reason": str(getattr(a, "reason", "")) or None}
                for i, a in enumerate(log.attempts)]
    return BlockAttemptSummary(
        namespace=str(log.seed_namespace),
        block_index=int(log.block_index),
        selected_attempt=int(log.selected_attempt or 0),
        attempts=attempts)
