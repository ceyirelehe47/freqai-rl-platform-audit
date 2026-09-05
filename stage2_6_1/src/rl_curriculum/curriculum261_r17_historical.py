# -*- coding: utf-8 -*-
"""R17 历史证据绑定(薄层:复用 r16_historical 的历史链检查)。

R17 只新增 R16 链段检查(baseline 核验);R15 及更早的历史事实由
curriculum261_r16_historical.historical_evidence_binding 夹带,
不再机械重写(任务书 §3:优先复用既有实现)。

R16 链事实(锚定):
    c0da37a(R15 Commit B,= R16 baseline)
      → 4a42f6b(R16 Commit A:实现冻结)
      → d2ee974(R16 Commit B:results-only;R17 exact baseline)
R16 正式运行诚实 FAIL 于 calibrate(main curriculum gate 统计;
WP0 归因:C2 matched main D3 0.989x κ×SE——C1/C3 全过,
R16 主报告的"C1/C3 未达门槛"为错误归因,已在 R17 诊断区举证)。
R16 qualification 未 exposure;R16 永久 FAIL 不变。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r16_historical import (
    R15_COMMIT_A,
    R15_COMMIT_B,
    historical_evidence_binding as _r16_binding,
    historical_evidence_binding_digest as _r16_digest,
)

#: R17 exact baseline = R16 Commit B。
R17_EXPECTED_BASELINE = "d2ee974a5bb6573b4dfaa0d09288d20a74a91c87"
#: R16 提交链锚点。
R16_COMMIT_A = "4a42f6b4bf1bdd1468d7ae899d331be756e6deec"
R16_COMMIT_B = "d2ee974a5bb6573b4dfaa0d09288d20a74a91c87"
R17_ITERATION = "r17"


def _git(repo: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True,
                          check=True).stdout.strip()


def _git_ok(repo: Path, *args: str) -> bool:
    import subprocess

    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True).returncode == 0


def historical_evidence_binding(repo: Path) -> dict[str, Any]:
    """R17 绑定 = R16 全部历史检查 + R16 链段检查。

    R17 分支语境调整:R16 binding 的 r16_branch_name_ok 在 R17
    分支上按设计为 False(R16 分支检查不适用于 R17 轮;先例:
    r15_governance 在 R16 轮的同处理);R17 gate 重算 = R16 检查
    全集(除分支键)+ R17 分支键 + R16 链段键。
    """
    binding = _r16_binding(repo)
    checks: dict[str, Any] = binding.setdefault("checks", {})
    # R17 分支键(取代 r16_branch_name_ok 在本轮 gate 的位置)
    current = _git(repo, "branch", "--show-current")
    checks["current_branch"] = current
    checks["r17_branch_name_ok"] = bool(
        current == "route-c-stage2-6-1-repair17")
    # R16 链段:父链、A/B 内容、正式产物存在性
    head = _git(repo, "rev-parse", "HEAD")
    checks["r17_baseline_is_r16_commit_b"] = bool(
        head == R16_COMMIT_B) or _git_ok(
        repo, "merge-base", "--is-ancestor", R16_COMMIT_B, head)
    checks["r16_commit_a_parent_is_r15_b"] = _git(
        repo, "rev-parse", f"{R16_COMMIT_A}^") == R15_COMMIT_B
    checks["r16_commit_b_parent_is_r16_a"] = _git(
        repo, "rev-parse", f"{R16_COMMIT_B}^") == R16_COMMIT_A
    # R16 正式链产物(诚实 FAIL 证据)
    checks["r16_fail_closure_exists"] = _git_ok(
        repo, "cat-file", "-e",
        f"{R16_COMMIT_B}:stage2_6_1/artifacts/repair16/"
        "r16_fail_closure_summary.json")
    checks["r16_journal_exists"] = _git_ok(
        repo, "cat-file", "-e",
        f"{R16_COMMIT_B}:stage2_6_1/artifacts/repair16/"
        "r16_execution_journal.jsonl")
    # R16 wrapper LF(R15 事故防线在 R16 生效的回执)
    checks["r16_wrapper_is_lf"] = "\r" not in _git(
        repo, "cat-file", "blob",
        f"{R16_COMMIT_A}:stage2_6_1/runner/r16_formal_chain.sh")
    checks["r16_remains_permanent_fail"] = True
    binding["r16_iteration_record"] = {
        "commit_a": R16_COMMIT_A,
        "commit_b": R16_COMMIT_B,
        "formal_outcome": "honest FAIL at calibrate(main curriculum "
                          "gate statistical;WP0 attribution: C2 "
                          "matched main D3 = 0.989x kappa*SE;C1/C3 "
                          "all numeric conditions passed)",
        "qualification_exposure": False,
        "r17_note": "R16 报告的 C1/C3 归因错误已在 R17 只读诊断区"
                    "举证(wp0_r16_readonly_attribution);R16 FAIL "
                    "本身维持,不追认",
    }
    binding["iteration"] = R17_ITERATION
    binding["baseline"] = R17_EXPECTED_BASELINE
    # R17 gate 重算:R16 检查全集(除 r16 分支键)+ R17 键
    gate_ok = all(
        v for k, v in checks.items()
        if isinstance(v, bool) and k != "r16_branch_name_ok")
    binding["pass"] = bool(gate_ok)
    binding["ok"] = bool(gate_ok)
    return binding


def historical_evidence_binding_digest(binding: dict[str, Any]) -> str:
    import hashlib
    import json

    return "r17heb-" + hashlib.sha256(json.dumps(
        binding, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def write_historical_evidence_binding(repo: Path,
                                       out_dir: Path) -> dict[str, Any]:
    binding = historical_evidence_binding(repo)
    import json

    (out_dir / "historical_evidence_binding.json").write_text(
        json.dumps(binding, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    (out_dir / "historical_evidence_binding_digest.txt").write_text(
        historical_evidence_binding_digest(binding) + "\n",
        encoding="utf-8")
    return binding


__all__ = [
    "R17_EXPECTED_BASELINE", "R16_COMMIT_A", "R16_COMMIT_B",
    "historical_evidence_binding",
    "historical_evidence_binding_digest",
    "write_historical_evidence_binding",
]
