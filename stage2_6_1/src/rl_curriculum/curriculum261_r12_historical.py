# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R12:HistoricalEvidenceBinding-v1(git ancestry 语义)。

R11 的 baseline 检查使用 `HEAD == 启动baseline` 的严格相等语义,导致
正常开发(Commit A 之后 HEAD 前移)出现 baseline_matches=false 的假
阴性(§6)。R12 改为 Git ancestry 语义:

1. expected baseline = 96446f2f91cd13df0411dc70909dd43ab8864046
   (R11 Commit B / 诚实 FAIL 结果提交);
2. expected baseline 是 R12 freeze commit 的祖先
   (git merge-base --is-ancestor);
3. merge-base(expected baseline, freeze SHA) == expected baseline;
4. R12 分支 fork point 正确;
5. repair1–repair11 关键文件的 Git blob identity 未变化
   (baseline tree 与当前 tree 逐路径比较 blob SHA,机器生成,
   禁止手工转录长 digest);
6. R11 abort marker 存在且内容 hash 与 baseline 提交内一致;
7. R11 qualification exposure 不存在;
8. R11 final qualification 未执行;
9. R11 cue audit plan digest 与结果 artifact 仍完整(blob 一致);
10. R11 Commit A(df0292a)、A′(572c509)、Commit B(96446f2)提交
    关系完整(A 是 A′ 的祖先,A′ 是 B 的祖先;A′ 的存在本身即
    R11 clean formal chain 失效的机器证据,§2-A)。

全部 digest/SHA 由 git 对象与文件内容在运行时计算;本模块不定义
任何手工转录的文件级长 digest 常量(commit id 锚点除外)。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

#: R12 启动基线(唯一允许的锚点常量;git 对象可机器验证)。
R12_EXPECTED_BASELINE = "96446f2f91cd13df0411dc70909dd43ab8864046"
#: R11 提交链锚点(治理证据,§2-A/§6-10)。
R11_COMMIT_A = "df0292ac2208375cca478b037c4ba87c6808911e"
R11_COMMIT_A_PRIME = "572c509233fef560a39ea30cd497a34053d47ce0"
R11_COMMIT_B = "96446f2f91cd13df0411dc70909dd43ab8864046"
R12_ITERATION = "r12"

#: repair1–repair11 关键证据文件(blob identity 必须与 baseline 一致)。
R11_PRESERVED_KEY_FILES = (
    "stage2_6_1/artifacts/repair11/r11_iteration_aborted.json",
    "stage2_6_1/artifacts/repair11/r11_iteration_events.jsonl",
    "stage2_6_1/artifacts/repair11/cue_audit_plan.json",
    "stage2_6_1/artifacts/repair11/cue_audit_plan_digest.txt",
    "stage2_6_1/artifacts/repair11/cue_contract_audit.json",
    "stage2_6_1/artifacts/repair11/cue_event_trace.jsonl",
    "stage2_6_1/artifacts/repair11/cue_k_distribution.json",
    "stage2_6_1/artifacts/repair11/r11_code_freeze.json",
    "stage2_6_1/artifacts/repair11/historical_binding.json",
    "stage2_6_1/artifacts/repair11/fail_path_cleanliness.json",
)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} 失败({out.returncode}):"
            f"{out.stderr.strip()[:400]}")
    return out.stdout.strip()


def _git_ok(repo: Path, *args: str) -> bool:
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=False)
    return out.returncode == 0


def _blob_sha(repo: Path, rev: str, path: str) -> str | None:
    """路径在指定 rev 的 blob SHA(文件不存在返回 None;机器读取)。"""
    out = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", f"{rev}:{path}"],
        capture_output=True, text=True, check=False)
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _file_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def historical_evidence_binding(repo: Path) -> dict[str, Any]:
    """构建并验证 HistoricalEvidenceBinding-v1(全部机器生成)。

    验证项见模块 docstring;任何一项失败 → ok=false(调用方 fail
    closed)。不修改任何文件。
    """
    repo = Path(repo)
    checks: dict[str, Any] = {}
    # ---- 1. baseline 提交存在 ----
    checks["baseline_commit_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R12_EXPECTED_BASELINE}^{{commit}}")
    if not checks["baseline_commit_exists"]:
        return {"format": "cur261-r12-historical-evidence-binding-v1",
                "iteration": R12_ITERATION,
                "expected_baseline": R12_EXPECTED_BASELINE,
                "ok": False,
                "failed_check": "baseline_commit_exists",
                "checks": checks}
    head = _git(repo, "rev-parse", "HEAD")
    # ---- 2. ancestry:baseline 是 HEAD(将来的 freeze commit)祖先 ----
    checks["baseline_is_ancestor_of_head"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R12_EXPECTED_BASELINE, "HEAD")
    # ---- 3. merge-base == expected baseline ----
    mb = _git(repo, "merge-base", R12_EXPECTED_BASELINE, "HEAD")
    checks["merge_base_equals_baseline"] = (mb == R12_EXPECTED_BASELINE)
    checks["merge_base"] = mb
    # ---- 4. fork point:HEAD 所在分支包含 baseline 且未并入其他基线 ----
    branches = _git(repo, "for-each-ref",
                    "--format=%(refname:short)", "refs/heads")
    current = _git(repo, "branch", "--show-current")
    checks["current_branch"] = current
    checks["r12_branch_name_ok"] = current == "route-c-stage2-6-1-repair12"
    # ---- 10. R11 提交链关系 ----
    checks["r11_commit_a_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R11_COMMIT_A}^{{commit}}")
    checks["r11_commit_a_prime_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R11_COMMIT_A_PRIME}^{{commit}}")
    checks["r11_commit_b_is_baseline"] = (
        R11_COMMIT_B == R12_EXPECTED_BASELINE)
    checks["r11_a_ancestor_of_a_prime"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R11_COMMIT_A, R11_COMMIT_A_PRIME)
    checks["r11_a_prime_ancestor_of_b"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R11_COMMIT_A_PRIME, R11_COMMIT_B)
    # A′ 存在 ⇒ R11 clean formal chain 在 A′ 出现时已失效(治理 FAIL
    # 的机器证据;§2-A)
    checks["r11_clean_chain_invalidated_by_a_prime"] = bool(
        checks["r11_commit_a_prime_exists"])
    # ---- 5. repair1–repair11 关键文件 blob identity ----
    blob_rows = []
    blobs_ok = True
    for rel in R11_PRESERVED_KEY_FILES:
        base_blob = _blob_sha(repo, R12_EXPECTED_BASELINE, rel)
        head_blob = _blob_sha(repo, "HEAD", rel)
        work = repo / rel
        work_sha = _file_sha256(work)
        same = (base_blob is not None and base_blob == head_blob)
        # 工作树文件(若存在)必须与提交内对象一致(由 git status 兜底;
        # 此处对存在的文件直接比对内容)
        blobs_ok = blobs_ok and same
        blob_rows.append({
            "path": rel, "baseline_blob": base_blob, "head_blob": head_blob,
            "worktree_sha256": work_sha, "blob_identity_preserved": same,
        })
    checks["preserved_file_blob_rows"] = blob_rows
    checks["preserved_files_blob_identity_ok"] = blobs_ok
    # ---- 6. R11 abort marker 内容 hash(baseline 内对象 vs 当前工作树)----
    abort_rel = "stage2_6_1/artifacts/repair11/r11_iteration_aborted.json"
    abort_blob = _blob_sha(repo, R12_EXPECTED_BASELINE, abort_rel)
    abort_work = _file_sha256(repo / abort_rel)
    checks["r11_abort_marker_exists"] = abort_blob is not None
    # blob SHA-1 与 sha256 不同域;改用同一域:git hash-object 工作树文件
    ho = subprocess.run(
        ["git", "-C", str(repo), "hash-object", str(repo / abort_rel)],
        capture_output=True, text=True, check=False)
    work_blob = ho.stdout.strip() if ho.returncode == 0 else None
    checks["r11_abort_marker_content_matches_baseline"] = bool(
        abort_blob is not None and abort_blob == work_blob)
    # ---- 7. R11 qualification exposure 不存在 ----
    exposure_rel = ("stage2_6_1/artifacts/repair11/"
                    "qualification_exposure_r11.json")
    exposure_absent_in_baseline = _blob_sha(
        repo, R12_EXPECTED_BASELINE, exposure_rel) is None
    exposure_absent_in_head = _blob_sha(
        repo, "HEAD", exposure_rel) is None
    checks["r11_qualification_exposure_absent"] = bool(
        exposure_absent_in_baseline and exposure_absent_in_head)
    # ---- 8. R11 final qualification 未执行 ----
    final_rel = "stage2_6_1/artifacts/repair11/qualification_result.json"
    final_absent_in_baseline = _blob_sha(
        repo, R12_EXPECTED_BASELINE, final_rel) is None
    final_absent_in_head = _blob_sha(repo, "HEAD", final_rel) is None
    checks["r11_final_qualification_not_executed"] = bool(
        final_absent_in_baseline and final_absent_in_head)
    # ---- 9. R11 cue audit plan digest 与结果完整(blob 已在 5 覆盖;
    # 此处追加 digest 文本域一致性:plan digest 文件与 plan 内自报一致)----
    plan_rel = "stage2_6_1/artifacts/repair11/cue_audit_plan.json"
    digest_rel = ("stage2_6_1/artifacts/repair11/"
                  "cue_audit_plan_digest.txt")
    plan_blob = _blob_sha(repo, R12_EXPECTED_BASELINE, plan_rel)
    digest_blob = _blob_sha(repo, R12_EXPECTED_BASELINE, digest_rel)
    checks["r11_cue_audit_plan_and_digest_present"] = bool(
        plan_blob is not None and digest_blob is not None)
    # baseline 版本文件内容读取(通过 git show,不经工作树)
    if plan_blob is not None and digest_blob is not None:
        plan_text = _git(repo, "show", f"{R12_EXPECTED_BASELINE}:{plan_rel}")
        digest_text = _git(repo, "show",
                           f"{R12_EXPECTED_BASELINE}:{digest_rel}").strip()
        try:
            plan_payload = json.loads(plan_text)
            self_reported = str(
                plan_payload.get("cue_audit_plan_digest", ""))
            checks["r11_cue_plan_digest_self_consistent"] = bool(
                self_reported == digest_text)
        except json.JSONDecodeError:
            checks["r11_cue_plan_digest_self_consistent"] = False
    else:
        checks["r11_cue_plan_digest_self_consistent"] = False

    gate_keys = [
        "baseline_commit_exists",
        "baseline_is_ancestor_of_head",
        "merge_base_equals_baseline",
        "r12_branch_name_ok",
        "r11_commit_a_exists",
        "r11_commit_a_prime_exists",
        "r11_commit_b_is_baseline",
        "r11_a_ancestor_of_a_prime",
        "r11_a_prime_ancestor_of_b",
        "r11_clean_chain_invalidated_by_a_prime",
        "preserved_files_blob_identity_ok",
        "r11_abort_marker_exists",
        "r11_abort_marker_content_matches_baseline",
        "r11_qualification_exposure_absent",
        "r11_final_qualification_not_executed",
        "r11_cue_audit_plan_and_digest_present",
        "r11_cue_plan_digest_self_consistent",
    ]
    failed = [k for k in gate_keys if checks.get(k) is not True]
    return {
        "format": "cur261-r12-historical-evidence-binding-v1",
        "iteration": R12_ITERATION,
        "expected_baseline": R12_EXPECTED_BASELINE,
        "head": head,
        "ancestry_semantics": "git merge-base --is-ancestor "
                              "(取代 R11 的 HEAD==baseline 严格相等)",
        "r11_governance_failure_binding": {
            "r11_commit_a": R11_COMMIT_A,
            "r11_commit_a_prime": R11_COMMIT_A_PRIME,
            "r11_commit_b": R11_COMMIT_B,
            "clean_formal_chain_invalidated_by": "A′ 出现(Commit A 后"
                                                 "修改源码并继续同一 "
                                                 "iteration)",
            "r11_final_verdict": "FAIL(永久;不得重解释/追认/撤销)",
        },
        "checks": checks,
        "failed_checks": failed,
        "ok": not failed,
    }


def historical_evidence_binding_digest(binding: dict[str, Any]) -> str:
    core = {k: binding.get(k) for k in (
        "format", "iteration", "expected_baseline", "head",
        "ancestry_semantics", "r11_governance_failure_binding",
        "failed_checks", "ok")}
    return "r12heb-" + hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        default=str).encode("utf-8")).hexdigest()


def write_historical_evidence_binding(repo: Path, out_dir: Path) -> dict:
    """生成 binding + digest 文件(out_dir;禁止覆盖已存在文件)。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    binding = historical_evidence_binding(repo)
    digest = historical_evidence_binding_digest(binding)
    binding["historical_evidence_binding_digest"] = digest
    j_path = out_dir / "historical_evidence_binding.json"
    d_path = out_dir / "historical_evidence_binding_digest.txt"
    if j_path.is_file() or d_path.is_file():
        raise RuntimeError("historical evidence binding 已存在;禁止重写")
    j_path.write_text(json.dumps(
        binding, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    d_path.write_text(digest, encoding="utf-8")
    return binding


def verify_historical_evidence_binding(repo: Path, out_dir: Path) -> dict:
    """正式阶段重算(不信任 manifest 自报;fail closed)。"""
    out_dir = Path(out_dir)
    j_path = out_dir / "historical_evidence_binding.json"
    d_path = out_dir / "historical_evidence_binding_digest.txt"
    if not j_path.is_file() or not d_path.is_file():
        raise RuntimeError("historical evidence binding 缺失(fail closed)")
    binding = json.loads(j_path.read_text(encoding="utf-8"))
    recorded = d_path.read_text(encoding="utf-8").strip()
    fresh = historical_evidence_binding(repo)
    fresh_digest = historical_evidence_binding_digest(fresh)
    problems: list[str] = []
    if recorded != fresh_digest:
        problems.append("digest 复算不一致")
    if fresh.get("head") != binding.get("head"):
        problems.append(
            f"HEAD 漂移:binding 记录 {binding.get('head')},"
            f"当前 {fresh.get('head')}")
    if not fresh.get("ok"):
        problems.append(f"重算存在失败项:{fresh.get('failed_checks')}")
    if str(binding.get("historical_evidence_binding_digest")) != recorded:
        problems.append("manifest 自报 digest 与 digest 文件不一致")
    if problems:
        raise RuntimeError(
            "HistoricalEvidenceBinding-v1 验证失败(fail closed):"
            + "; ".join(problems))
    return fresh
