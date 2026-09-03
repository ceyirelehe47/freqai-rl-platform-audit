# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R13:HistoricalEvidenceBinding-v1(git ancestry 语义)。

R12/R13 治理语义(R13 相对 R12 的新增检查):
1. expected baseline = 960dbe19701901f9262614aadf8b7f97742fab4d
   (R12 Commit B / 诚实 FAIL 结果提交);
2. R12 的提交链是干净的双提交链:
   96446f2(R11 Commit B)→ 75a66dd(R12 Commit A/实现冻结)→
   960dbe1(R12 Commit B/结果);用 git 机器验证 B 的父提交就是 A
   (rev-parse B^ == A)——R12 没有出现 A′/A2/hotfix 提交;
3. repair1–repair12 关键文件的 Git blob identity 未变化
   (baseline tree 与当前 tree 逐路径比较 blob SHA,机器生成,
   禁止手工转录长 digest);
4. R12 abort marker 存在且内容与 baseline 提交内一致;R12 的失败
   定性为 lock-plan 阶段 producer/consumer artifact 接口不一致
   (读取 'bundle_hash' 而正式 artifact 键为
   'preprocessor_bundle_hash');
5. R12 qualification exposure 不存在;R12 qualification plan 从未
   锁定;R12 final qualification 从未执行;
6. R11 提交链(A df0292a → A′ 572c509 → B 96446f2)关系完整
   (A′ 的存在本身即 R11 clean formal chain 失效的机器证据)。

全部 digest/SHA 由 git 对象与文件内容在运行时计算;本模块不定义
任何手工转录的文件级长 digest 常量(commit id 锚点除外)。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

#: R13 启动基线(唯一允许的锚点常量;git 对象可机器验证)。
R13_EXPECTED_BASELINE = "960dbe19701901f9262614aadf8b7f97742fab4d"
#: R12 提交链锚点(治理证据;§二/§六)。
R12_COMMIT_A = "75a66dde368c6f7c8ccc1a70e19445a6f86165fe"
R12_COMMIT_B = "960dbe19701901f9262614aadf8b7f97742fab4d"
#: R11 提交链锚点(治理证据;R12 轮已绑定,持续保留)。
R11_COMMIT_A = "df0292ac2208375cca478b037c4ba87c6808911e"
R11_COMMIT_A_PRIME = "572c509233fef560a39ea30cd497a34053d47ce0"
R11_COMMIT_B = "96446f2f91cd13df0411dc70909dd43ab8864046"
R13_ITERATION = "r13"

#: repair12 关键证据文件(blob identity 必须与 baseline 一致)。
R12_PRESERVED_KEY_FILES = (
    "stage2_6_1/artifacts/repair12/r12_iteration_aborted.json",
    "stage2_6_1/artifacts/repair12/r12_iteration_events.jsonl",
    "stage2_6_1/artifacts/repair12/r12_code_freeze.json",
    "stage2_6_1/artifacts/repair12/r12_design_plan.json",
    "stage2_6_1/artifacts/repair12/r12_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair12/r12_parameter_pack.json",
    "stage2_6_1/artifacts/repair12/r12_parameter_pack_digest.txt",
    "stage2_6_1/artifacts/repair12/cue_audit_plan.json",
    "stage2_6_1/artifacts/repair12/cue_audit_plan_digest.txt",
    "stage2_6_1/artifacts/repair12/cue_contract_audit.json",
    "stage2_6_1/artifacts/repair12/cue_event_trace.jsonl",
    "stage2_6_1/artifacts/repair12/robustness_gate.json",
    "stage2_6_1/artifacts/repair12/calibration_evidence.json",
    "stage2_6_1/artifacts/repair12/preprocessor_bundle_calibration.json",
    "stage2_6_1/artifacts/repair12/preprocessor_bundle_holdout.json",
    "stage2_6_1/artifacts/repair12/lock_plan_failure_traceback.json",
    "stage2_6_1/artifacts/repair12/fail_path_cleanliness.json",
    "stage2_6_1/artifacts/repair12/historical_evidence_binding.json",
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
    """构建并验证 HistoricalEvidenceBinding-v1(R13 版;全部机器生成)。

    验证项见模块 docstring;任何一项失败 → ok=false(调用方 fail
    closed)。不修改任何文件。
    """
    repo = Path(repo)
    checks: dict[str, Any] = {}
    # ---- 1. baseline 提交存在 ----
    checks["baseline_commit_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R13_EXPECTED_BASELINE}^{{commit}}")
    if not checks["baseline_commit_exists"]:
        return {"format": "cur261-r13-historical-evidence-binding-v1",
                "iteration": R13_ITERATION,
                "expected_baseline": R13_EXPECTED_BASELINE,
                "ok": False,
                "failed_check": "baseline_commit_exists",
                "checks": checks}
    head = _git(repo, "rev-parse", "HEAD")
    # ---- 2. ancestry:baseline 是 HEAD(将来的 freeze commit)祖先 ----
    checks["baseline_is_ancestor_of_head"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R13_EXPECTED_BASELINE, "HEAD")
    # ---- 3. merge-base == expected baseline ----
    mb = _git(repo, "merge-base", R13_EXPECTED_BASELINE, "HEAD")
    checks["merge_base_equals_baseline"] = (mb == R13_EXPECTED_BASELINE)
    checks["merge_base"] = mb
    # ---- 4. 分支名 ----
    current = _git(repo, "branch", "--show-current")
    checks["current_branch"] = current
    checks["r13_branch_name_ok"] = current == "route-c-stage2-6-1-repair13"
    # ---- R11 提交链关系(持续保留)----
    checks["r11_commit_a_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R11_COMMIT_A}^{{commit}}")
    checks["r11_commit_a_prime_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R11_COMMIT_A_PRIME}^{{commit}}")
    checks["r11_commit_b_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R11_COMMIT_B}^{{commit}}")
    checks["r11_a_ancestor_of_a_prime"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R11_COMMIT_A, R11_COMMIT_A_PRIME)
    checks["r11_a_prime_ancestor_of_b"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R11_COMMIT_A_PRIME, R11_COMMIT_B)
    checks["r11_clean_chain_invalidated_by_a_prime"] = bool(
        checks["r11_commit_a_prime_exists"])
    # ---- R12 干净双提交链(无 A′;B 的父提交就是 A)----
    checks["r12_commit_a_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R12_COMMIT_A}^{{commit}}")
    checks["r12_commit_b_is_baseline"] = (
        R12_COMMIT_B == R13_EXPECTED_BASELINE)
    checks["r12_commit_b_parent_is_a"] = (
        _git(repo, "rev-parse", f"{R12_COMMIT_B}^") == R12_COMMIT_A)
    checks["r12_commit_a_parent_is_r11_b"] = (
        _git(repo, "rev-parse", f"{R12_COMMIT_A}^") == R11_COMMIT_B)
    checks["r12_clean_two_commit_chain"] = bool(
        checks["r12_commit_a_exists"]
        and checks["r12_commit_b_parent_is_a"]
        and checks["r12_commit_a_parent_is_r11_b"])
    # ---- repair12 关键文件 blob identity ----
    blob_rows = []
    blobs_ok = True
    for rel in R12_PRESERVED_KEY_FILES:
        base_blob = _blob_sha(repo, R13_EXPECTED_BASELINE, rel)
        head_blob = _blob_sha(repo, "HEAD", rel)
        work = repo / rel
        work_sha = _file_sha256(work)
        same = (base_blob is not None and base_blob == head_blob)
        blobs_ok = blobs_ok and same
        blob_rows.append({
            "path": rel, "baseline_blob": base_blob, "head_blob": head_blob,
            "worktree_sha256": work_sha, "blob_identity_preserved": same,
        })
    checks["preserved_file_blob_rows"] = blob_rows
    checks["preserved_files_blob_identity_ok"] = blobs_ok
    # ---- R12 abort marker 内容一致(git hash-object 同域比较)----
    abort_rel = "stage2_6_1/artifacts/repair12/r12_iteration_aborted.json"
    abort_blob = _blob_sha(repo, R13_EXPECTED_BASELINE, abort_rel)
    ho = subprocess.run(
        ["git", "-C", str(repo), "hash-object", str(repo / abort_rel)],
        capture_output=True, text=True, check=False)
    work_blob = ho.stdout.strip() if ho.returncode == 0 else None
    checks["r12_abort_marker_exists"] = abort_blob is not None
    checks["r12_abort_marker_content_matches_baseline"] = bool(
        abort_blob is not None and abort_blob == work_blob)
    # ---- R12 qualification exposure 不存在 ----
    exposure_rel = ("stage2_6_1/artifacts/repair12/"
                    "qualification_exposure_r12.json")
    checks["r12_qualification_exposure_absent"] = bool(
        _blob_sha(repo, R13_EXPECTED_BASELINE, exposure_rel) is None
        and _blob_sha(repo, "HEAD", exposure_rel) is None)
    # ---- R12 qualification plan 从未锁定 ----
    plan_rel = "stage2_6_1/artifacts/repair12/qualification_plan_r12.json"
    checks["r12_qualification_plan_never_locked"] = bool(
        _blob_sha(repo, R13_EXPECTED_BASELINE, plan_rel) is None
        and _blob_sha(repo, "HEAD", plan_rel) is None)
    # ---- R12 final qualification 从未执行 ----
    final_rel = "stage2_6_1/artifacts/repair12/qualification_result.json"
    checks["r12_final_qualification_not_executed"] = bool(
        _blob_sha(repo, R13_EXPECTED_BASELINE, final_rel) is None
        and _blob_sha(repo, "HEAD", final_rel) is None)

    gate_keys = [
        "baseline_commit_exists",
        "baseline_is_ancestor_of_head",
        "merge_base_equals_baseline",
        "r13_branch_name_ok",
        "r11_commit_a_exists",
        "r11_commit_a_prime_exists",
        "r11_commit_b_exists",
        "r11_a_ancestor_of_a_prime",
        "r11_a_prime_ancestor_of_b",
        "r11_clean_chain_invalidated_by_a_prime",
        "r12_commit_a_exists",
        "r12_commit_b_is_baseline",
        "r12_commit_b_parent_is_a",
        "r12_commit_a_parent_is_r11_b",
        "r12_clean_two_commit_chain",
        "preserved_files_blob_identity_ok",
        "r12_abort_marker_exists",
        "r12_abort_marker_content_matches_baseline",
        "r12_qualification_exposure_absent",
        "r12_qualification_plan_never_locked",
        "r12_final_qualification_not_executed",
    ]
    failed = [k for k in gate_keys if checks.get(k) is not True]
    return {
        "format": "cur261-r13-historical-evidence-binding-v1",
        "iteration": R13_ITERATION,
        "expected_baseline": R13_EXPECTED_BASELINE,
        "head": head,
        "ancestry_semantics": "git merge-base --is-ancestor "
                              "(R12 起取代 HEAD==baseline 严格相等)",
        "r11_governance_failure_binding": {
            "r11_commit_a": R11_COMMIT_A,
            "r11_commit_a_prime": R11_COMMIT_A_PRIME,
            "r11_commit_b": R11_COMMIT_B,
            "clean_formal_chain_invalidated_by": "A′ 出现(Commit A 后"
                                                 "修改源码并继续同一 "
                                                 "iteration)",
            "r11_final_verdict": "FAIL(永久;不得重解释/追认/撤销)",
        },
        "r12_governance_binding": {
            "r12_commit_a": R12_COMMIT_A,
            "r12_commit_b": R12_COMMIT_B,
            "clean_two_commit_chain": "A(75a66dd 实现冻结)→ B(960dbe1 "
                                      "诚实 FAIL 结果);无 A′/A2/hotfix",
            "r12_final_verdict": "FAIL(永久;lock-plan 阶段 artifact "
                                 "接口缺陷;统计链 cue/global K/design/"
                                 "calibration/holdout 全部 PASS 但不被"
                                 "追认为 R13 输入)",
            "r12_failure_classification":
                "producer/consumer artifact interface inconsistency"
                "(冻结源码读取 preprocessor_bundle_calibration.json 的"
                " 'bundle_hash',实际键 'preprocessor_bundle_hash';"
                "KeyError at curriculum261_r12_cli.py:1717)",
        },
        "checks": checks,
        "failed_checks": failed,
        "ok": not failed,
    }


def historical_evidence_binding_digest(binding: dict[str, Any]) -> str:
    core = {k: binding.get(k) for k in (
        "format", "iteration", "expected_baseline", "head",
        "ancestry_semantics", "r11_governance_failure_binding",
        "r12_governance_binding", "failed_checks", "ok")}
    return "r13heb-" + hashlib.sha256(json.dumps(
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
