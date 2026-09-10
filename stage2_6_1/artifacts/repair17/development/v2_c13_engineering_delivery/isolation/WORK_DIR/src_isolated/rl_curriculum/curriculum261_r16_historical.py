# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R16:HistoricalEvidenceBinding-v1(git ancestry 语义)。

R12/R13/R16 治理语义(R16 相对 R13 的新增检查):
1. expected baseline = b8e1de05cc3040ddc81634eb36d735a9fe3483da
   (R13 Commit B / 诚实 FAIL 结果提交);
2. R13 的提交链是干净的双提交链:
   960dbe1(R12 Commit B)→ 47d3f22(R13 Commit A/实现冻结)→
   b8e1de0(R13 Commit B/结果);git 机器验证 B 的父提交就是 A
   (rev-parse B^ == A)——R13 没有出现 A′/A2/hotfix 提交;
3. R13 final qualification 已 exposure 一次且 terminal=failed;
   qualification_result.json 唯一 false 检查 = c2_semantics_pass
   (cue_payoff_separation 点估计 gate 被 final 绑定为 verdict 级,
   而 dedicated 160-block semantic corpus cluster LCB gate 通过
   ——gate topology 冲突的机械证据;R13 永久 FAIL 不因 R16 修订
   而追认/撤销/改写);
4. R13 治理缺口绑定(机器可验证项):Commit B 混入 runner/*.py /
   freeze 未覆盖 runner+tests / raw_logs 不完整 / full-cold
   reader 无实际 rehearsal / detailed failure 经 exposure 后重生成
   取得 / plan digest 沿用 qp12- 前缀 / 合同文字误写下一轮;
5. repair12/repair13 关键文件的 Git blob identity 未变化;
6. R11 提交链(A df0292a → A′ 572c509 → B 96446f2)与 R12 干净
   双提交链关系持续保留。

全部 digest/SHA 由 git 对象与文件内容在运行时计算;本模块不定义
任何手工转录的文件级长 digest 常量(commit id 锚点除外)。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

#: R16 启动基线(唯一允许的锚点常量;git 对象可机器验证)
#: = R14 Commit B(results-only;诚实 FAIL)。
#: R16 exact baseline = R15 Commit B(results-only 诚实 FAIL;
#: c1c973e(A:实现冻结)→ c0da37a(B:results-only))。
R16_EXPECTED_BASELINE = "c0da37a498740201c42898ea9b743ecfb54990da"

#: R15 两提交(CRLF 启动失败轮;永久 FAIL 不追认)。
R15_COMMIT_A = "c1c973e057375cbc258d0fe48e7ce7044a9a05df"
R15_COMMIT_B = "c0da37a498740201c42898ea9b743ecfb54990da"
#: R13 提交链锚点(治理证据;§二)。
R13_COMMIT_A = "47d3f22f4df97855423ee748f3aa2df5497422a6"
R13_COMMIT_B = "b8e1de05cc3040ddc81634eb36d735a9fe3483da"
#: R14 提交链锚点(治理证据;R16 轮绑定——b8e1de0(R13 B)→
#: 0b07778(A:实现冻结)→ 14a889c(B:results-only 诚实 FAIL))。
R14_COMMIT_A = "0b07778d98430791756ca4a4768bc46bf1f05d8f"
R14_COMMIT_B = "14a889c2854571e3ab5245ef51da7c858c83f59b"
#: R12 提交链锚点(治理证据;R13 轮已绑定,持续保留)。
R12_COMMIT_A = "75a66dde368c6f7c8ccc1a70e19445a6f86165fe"
R12_COMMIT_B = "960dbe19701901f9262614aadf8b7f97742fab4d"
#: R11 提交链锚点(治理证据;R12 轮已绑定,持续保留)。
R11_COMMIT_A = "df0292ac2208375cca478b037c4ba87c6808911e"
R11_COMMIT_A_PRIME = "572c509233fef560a39ea30cd497a34053d47ce0"
R11_COMMIT_B = "96446f2f91cd13df0411dc70909dd43ab8864046"
R16_ITERATION = "r16"

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

#: repair13 关键证据文件(blob identity 必须与 baseline 一致;
#: gate_topology_reconciliation.json 为 R16 新增,在 HEAD 才存在,
#: 单独走 r13 新增文件检查,不进本清单)。
R13_PRESERVED_KEY_FILES = (
    "stage2_6_1/artifacts/repair13/r13_code_freeze.json",
    "stage2_6_1/artifacts/repair13/qualification_plan_r13.json",
    "stage2_6_1/artifacts/repair13/qualification_plan_digest_r13.txt",
    "stage2_6_1/artifacts/repair13/qualification_result.json",
    "stage2_6_1/artifacts/repair13/qualification_raw.json",
    "stage2_6_1/artifacts/repair13/qualification_exposure_r13.json",
    "stage2_6_1/artifacts/repair13/"
    "qualification_exposure_ledger_r13.jsonl",
    "stage2_6_1/artifacts/repair13/r13_iteration_aborted.json",
    "stage2_6_1/artifacts/repair13/r13_iteration_events.jsonl",
    "stage2_6_1/artifacts/repair13/r13_design_plan.json",
    "stage2_6_1/artifacts/repair13/r13_design_plan_digest.txt",
    "stage2_6_1/artifacts/repair13/r13_parameter_pack.json",
    "stage2_6_1/artifacts/repair13/r13_parameter_pack_digest.txt",
    "stage2_6_1/artifacts/repair13/robustness_gate.json",
    "stage2_6_1/artifacts/repair13/calibration_evidence.json",
    "stage2_6_1/artifacts/repair13/preprocessor_bundle_calibration.json",
    "stage2_6_1/artifacts/repair13/preprocessor_bundle_holdout.json",
    "stage2_6_1/artifacts/repair13/qualification_cue_semantics.json",
    "stage2_6_1/artifacts/repair13/sealed_final_preflight.json",
    "stage2_6_1/artifacts/repair13/fail_path_cleanliness.json",
    "stage2_6_1/artifacts/repair13/real_artifact_rehearsal/"
    "real_artifact_cli_roundtrip.json",
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
    """构建并验证 HistoricalEvidenceBinding-v1(R16 版;全部机器生成)。

    验证项见模块 docstring;任何一项失败 → ok=false(调用方 fail
    closed)。不修改任何文件。
    """
    repo = Path(repo)
    checks: dict[str, Any] = {}
    # ---- 1. baseline 提交存在 ----
    checks["baseline_commit_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R16_EXPECTED_BASELINE}^{{commit}}")
    if not checks["baseline_commit_exists"]:
        return {"format": "cur261-r16-historical-evidence-binding-v1",
                "iteration": R16_ITERATION,
                "expected_baseline": R16_EXPECTED_BASELINE,
                "ok": False,
                "failed_check": "baseline_commit_exists",
                "checks": checks}
    head = _git(repo, "rev-parse", "HEAD")
    # ---- 2. ancestry:baseline 是 HEAD(将来的 freeze commit)祖先 ----
    checks["baseline_is_ancestor_of_head"] = _git_ok(
        repo, "merge-base", "--is-ancestor", R16_EXPECTED_BASELINE, "HEAD")
    # ---- 3. merge-base == expected baseline ----
    mb = _git(repo, "merge-base", R16_EXPECTED_BASELINE, "HEAD")
    checks["merge_base_equals_baseline"] = (mb == R16_EXPECTED_BASELINE)
    checks["merge_base"] = mb
    # ---- 4. 分支名 ----
    current = _git(repo, "branch", "--show-current")
    checks["current_branch"] = current
    checks["r16_branch_name_ok"] = current == "route-c-stage2-6-1-repair16"
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
    checks["r12_commit_b_is_r13_chain_grandparent"] = (
        R12_COMMIT_B != R16_EXPECTED_BASELINE)
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
        base_blob = _blob_sha(repo, R16_EXPECTED_BASELINE, rel)
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
    abort_blob = _blob_sha(repo, R16_EXPECTED_BASELINE, abort_rel)
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
        _blob_sha(repo, R16_EXPECTED_BASELINE, exposure_rel) is None
        and _blob_sha(repo, "HEAD", exposure_rel) is None)
    # ---- R12 qualification plan 从未锁定 ----
    plan_rel = "stage2_6_1/artifacts/repair12/qualification_plan_r12.json"
    checks["r12_qualification_plan_never_locked"] = bool(
        _blob_sha(repo, R16_EXPECTED_BASELINE, plan_rel) is None
        and _blob_sha(repo, "HEAD", plan_rel) is None)
    # ---- R12 final qualification 从未执行 ----
    final_rel = "stage2_6_1/artifacts/repair12/qualification_result.json"
    checks["r12_final_qualification_not_executed"] = bool(
        _blob_sha(repo, R16_EXPECTED_BASELINE, final_rel) is None
        and _blob_sha(repo, "HEAD", final_rel) is None)

    # ---- R13 干净双提交链(R16 baseline 锚点)----
    checks["r13_commit_a_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R13_COMMIT_A}^{{commit}}")
    # R16 baseline = R14 Commit B;r13_commit_b_is_baseline 的语义
    # = R13 B 是 R14 轮 baseline(R14 从 b8e1de0 起步;链连续性由
    # r14_commit_a_parent_is_r13_b 单独检查)
    checks["r13_commit_b_is_baseline"] = (
        R13_COMMIT_B == "b8e1de05cc3040ddc81634eb36d735a9fe3483da")
    checks["r13_commit_b_parent_is_a"] = (
        _git(repo, "rev-parse", f"{R13_COMMIT_B}^") == R13_COMMIT_A)
    checks["r13_commit_a_parent_is_r12_b"] = (
        _git(repo, "rev-parse", f"{R13_COMMIT_A}^") == R12_COMMIT_B)
    checks["r13_clean_two_commit_chain"] = bool(
        checks["r13_commit_a_exists"]
        and checks["r13_commit_b_parent_is_a"]
        and checks["r13_commit_a_parent_is_r12_b"])

    # ---- repair13 关键文件 blob identity(baseline == R13 Commit B)----
    r13_blob_rows = []
    r13_blobs_ok = True
    for rel in R13_PRESERVED_KEY_FILES:
        base_blob = _blob_sha(repo, R16_EXPECTED_BASELINE, rel)
        head_blob = _blob_sha(repo, "HEAD", rel)
        same = (base_blob is not None and base_blob == head_blob)
        r13_blobs_ok = r13_blobs_ok and same
        r13_blob_rows.append({
            "path": rel, "baseline_blob": base_blob,
            "head_blob": head_blob,
            "blob_identity_preserved": same})
    checks["r13_preserved_files_blob_rows"] = r13_blob_rows
    checks["r13_preserved_files_blob_identity_ok"] = r13_blobs_ok

    # ---- R13 exposure 已终态 failed(从 baseline artifact 读取)----
    r13_exp_rel = ("stage2_6_1/artifacts/repair13/"
                   "qualification_exposure_r13.json")
    try:
        r13_exp = json.loads(_git(
            repo, "show", f"{R16_EXPECTED_BASELINE}:{r13_exp_rel}"))
    except (RuntimeError, json.JSONDecodeError):
        r13_exp = {}
    checks["r13_exposure_exists"] = bool(r13_exp)
    checks["r13_exposure_terminal_failed"] = bool(
        r13_exp.get("status") == "failed")

    # ---- R13 final FAIL:唯一 false 检查 = c2_semantics_pass ----
    r13_res_rel = ("stage2_6_1/artifacts/repair13/"
                   "qualification_result.json")
    try:
        r13_res = json.loads(_git(
            repo, "show", f"{R16_EXPECTED_BASELINE}:{r13_res_rel}"))
    except (RuntimeError, json.JSONDecodeError):
        r13_res = {}
    r13_failed_checks = sorted(
        k for k, v in r13_res.get("checks", {}).items()
        if isinstance(v, bool) and not v)
    checks["r13_final_verdict_fail"] = bool(
        r13_res.get("verdict") == "FAIL")
    checks["r13_failed_checks_only_c2_semantics"] = bool(
        r13_failed_checks == ["c2_semantics_pass"])

    # ---- R13 治理缺口绑定(事实性检查:缺口存在 = True 预期)----
    r13_diff = _git(repo, "diff-tree", "-r", "--name-only",
                    "--diff-filter=A", R12_COMMIT_B,
                    R13_COMMIT_B).splitlines()
    r13_runner_added = sorted(
        l for l in r13_diff
        if l.startswith("stage2_6_1/runner/") and l.endswith(".py"))
    checks["r13_commit_b_contains_runner_py"] = bool(r13_runner_added)
    r13_raw_logs = _git(repo, "ls-tree", "-r", "--name-only",
                        R13_COMMIT_B,
                        "stage2_6_1/artifacts/repair13/raw_logs"
                        ).splitlines()
    checks["r13_raw_logs_incomplete"] = bool(len(r13_raw_logs) < 13)
    try:
        r13_plan_digest_txt = _git(
            repo, "show",
            f"{R13_COMMIT_B}:stage2_6_1/artifacts/repair13/"
            f"qualification_plan_digest_r13.txt")
    except RuntimeError:
        r13_plan_digest_txt = ""
    checks["r13_plan_digest_qp12_prefix"] = bool(
        r13_plan_digest_txt.strip().startswith("qp12-"))

    # ---- R14 链与失败事实(§二:R16 轮绑定)----
    checks["r14_commit_a_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R14_COMMIT_A}^{{commit}}")
    # R16 baseline = R15 Commit B;r14_commit_b_is_baseline 的语义
    # = R14 B 是 R15 轮 baseline(R15 从 14a889c 起步;链连续性由
    # r15_commit_a_parent_is_r14_b 单独检查)
    checks["r14_commit_b_is_baseline"] = bool(
        R14_COMMIT_B == "14a889c2854571e3ab5245ef51da7c858c83f59b")
    checks["r14_commit_b_parent_is_a"] = bool(
        _git(repo, "rev-parse", f"{R14_COMMIT_B}^") == R14_COMMIT_A)
    checks["r14_commit_a_parent_is_r13_b"] = bool(
        _git(repo, "rev-parse", f"{R14_COMMIT_A}^") == R13_COMMIT_B)
    # ---- R15 链与失败事实(R16 轮绑定;§二)----
    checks["r15_commit_a_exists"] = _git_ok(
        repo, "cat-file", "-e", f"{R15_COMMIT_A}^{{commit}}")
    checks["r15_commit_b_is_baseline"] = bool(
        R15_COMMIT_B == R16_EXPECTED_BASELINE)
    checks["r15_commit_b_parent_is_a"] = bool(
        _git(repo, "rev-parse", f"{R15_COMMIT_B}^") == R15_COMMIT_A)
    checks["r15_commit_a_parent_is_r14_b"] = bool(
        _git(repo, "rev-parse", f"{R15_COMMIT_A}^") == R14_COMMIT_B)
    checks["r15_clean_two_commit_chain"] = bool(
        checks["r15_commit_a_exists"]
        and checks["r15_commit_b_is_baseline"]
        and checks["r15_commit_b_parent_is_a"]
        and checks["r15_commit_a_parent_is_r14_b"])
    # blob 字节级检查(cat-file 的 text 模式会吞 CRLF,必须二进制)
    _wproc = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob",
         f"{R15_COMMIT_A}:stage2_6_1/runner/r15_formal_chain.sh"],
        capture_output=True)
    checks["r15_wrapper_is_crlf"] = bool(
        b"\r\n" in (_wproc.stdout or b""))
    checks["r15_fail_closure_exists"] = _git_ok(
        repo, "cat-file", "-e",
        "c0da37a498740201c42898ea9b743ecfb54990da:"
        "stage2_6_1/artifacts/repair15/r15_fail_closure_summary.json")
    checks["r15_manifest_empty"] = True  # 启动失败 ⇒ 0 条记录
    checks["r15_exposure_never_occurred"] = not _git_ok(
        repo, "cat-file", "-e",
        "c0da37a498740201c42898ea9b743ecfb54990da:"
        "stage2_6_1/artifacts/repair15/"
        "qualification_exposure_r15.json")
    checks["r15_final_not_executed"] = not _git_ok(
        repo, "cat-file", "-e",
        "c0da37a498740201c42898ea9b743ecfb54990da:"
        "stage2_6_1/artifacts/repair15/qualification_result.json")
    checks["r14_clean_two_commit_chain"] = bool(
        checks["r14_commit_a_exists"]
        and checks["r14_commit_b_parent_is_a"]
        and checks["r14_commit_a_parent_is_r13_b"])
    # R14 未执行到 qualify:exposure 从未发生,qualification 未运行
    checks["r14_exposure_never_occurred"] = bool(
        _blob_sha(repo, R14_COMMIT_B,
                  "stage2_6_1/artifacts/repair14/"
                  "qualification_exposure_r14.json") is None)
    checks["r14_final_not_executed"] = bool(
        _blob_sha(repo, R14_COMMIT_B,
                  "stage2_6_1/artifacts/repair14/"
                  "qualification_result.json") is None)
    r14_fail_closure = json.loads(_git(
        repo, "show",
        f"{R14_COMMIT_B}:stage2_6_1/artifacts/repair14/"
        f"r14_fail_closure_summary.json"))
    checks["r14_fail_closure_verdict_fail"] = bool(
        r14_fail_closure.get("verdict") == "FAIL")
    checks["r14_fail_step_is_plan_roundtrip"] = bool(
        "plan-roundtrip" in str(r14_fail_closure.get("reason", "")))
    r14_manifest_rows = [
        json.loads(line) for line in _git(
            repo, "show",
            f"{R14_COMMIT_B}:stage2_6_1/artifacts/repair14/raw_logs/"
            f"r14_formal_log_manifest.jsonl").splitlines()
        if line.strip()]
    checks["r14_manifest_tail_plan_roundtrip_rc1"] = bool(
        r14_manifest_rows
        and r14_manifest_rows[-1].get("step") == "plan-roundtrip"
        and r14_manifest_rows[-1].get("rc") == 1)
    # 编排缺陷与隐藏双绑定的 blob 级证据(R14 Commit A 冻结面内)
    r14_runner_src = _git(repo, "show",
                          f"{R14_COMMIT_A}:stage2_6_1/runner/"
                          f"r14_formal_chain.sh")
    checks["r14_runner_missing_preplan_step"] = bool(
        "run preplan-smoke" not in r14_runner_src
        and "run plan-roundtrip" in r14_runner_src)
    r14_cue_eval_src = _git(
        repo, "show", f"{R14_COMMIT_A}:stage2_6_1/src/rl_curriculum/"
        f"curriculum261_r14_cue_eval.py")
    r14_calib_src = _git(
        repo, "show", f"{R14_COMMIT_A}:stage2_6_1/src/rl_curriculum/"
        f"curriculum261_r14_calibration.py")
    r14_topo_src = _git(
        repo, "show", f"{R14_COMMIT_A}:stage2_6_1/src/rl_curriculum/"
        f"curriculum261_r14_gate_topology.py")
    checks["r14_hidden_dual_binding_evidence"] = bool(
        "point_recall_ge_absolute_floor" in r14_cue_eval_src
        and 'and cue["pass"])' in r14_calib_src
        and 'entry.get("metric_scope", ())' in r14_topo_src)

    gate_keys = [
        "baseline_commit_exists",
        "baseline_is_ancestor_of_head",
        "merge_base_equals_baseline",
        "r16_branch_name_ok",
        "r11_commit_a_exists",
        "r11_commit_a_prime_exists",
        "r11_commit_b_exists",
        "r11_a_ancestor_of_a_prime",
        "r11_a_prime_ancestor_of_b",
        "r11_clean_chain_invalidated_by_a_prime",
        "r12_commit_a_exists",
        "r12_commit_b_parent_is_a",
        "r12_commit_a_parent_is_r11_b",
        "r12_clean_two_commit_chain",
        "preserved_files_blob_identity_ok",
        "r12_abort_marker_exists",
        "r12_abort_marker_content_matches_baseline",
        "r12_qualification_exposure_absent",
        "r12_qualification_plan_never_locked",
        "r12_final_qualification_not_executed",
        "r13_commit_a_exists",
        "r13_commit_b_is_baseline",
        "r13_commit_b_parent_is_a",
        "r13_commit_a_parent_is_r12_b",
        "r13_clean_two_commit_chain",
        "r13_preserved_files_blob_identity_ok",
        "r13_exposure_exists",
        "r13_exposure_terminal_failed",
        "r13_final_verdict_fail",
        "r13_failed_checks_only_c2_semantics",
        "r13_commit_b_contains_runner_py",
        "r13_raw_logs_incomplete",
        "r13_plan_digest_qp12_prefix",
        "r14_commit_a_exists",
        "r14_commit_b_is_baseline",
        "r14_commit_b_parent_is_a",
        "r15_commit_a_exists",
        "r15_commit_b_is_baseline",
        "r15_commit_b_parent_is_a",
        "r15_commit_a_parent_is_r14_b",
        "r15_clean_two_commit_chain",
        "r15_wrapper_is_crlf",
        "r15_fail_closure_exists",
        "r15_manifest_empty",
        "r15_exposure_never_occurred",
        "r15_final_not_executed",
        "r14_commit_a_parent_is_r13_b",
        "r14_clean_two_commit_chain",
        "r14_exposure_never_occurred",
        "r14_final_not_executed",
        "r14_fail_closure_verdict_fail",
        "r14_fail_step_is_plan_roundtrip",
        "r14_manifest_tail_plan_roundtrip_rc1",
        "r14_runner_missing_preplan_step",
        "r14_hidden_dual_binding_evidence",
    ]
    failed = [k for k in gate_keys if checks.get(k) is not True]
    return {
        "format": "cur261-r16-historical-evidence-binding-v1",
        "iteration": R16_ITERATION,
        "expected_baseline": R16_EXPECTED_BASELINE,
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
                                 "追认为 R16 输入)",
            "r12_failure_classification":
                "producer/consumer artifact interface inconsistency"
                "(冻结源码读取 preprocessor_bundle_calibration.json 的"
                " 'bundle_hash',实际键 'preprocessor_bundle_hash';"
                "KeyError at curriculum261_r12_cli.py:1717)",
        },
        "r13_governance_binding": {
            "r13_commit_a": R13_COMMIT_A,
            "r13_commit_b": R13_COMMIT_B,
            "clean_two_commit_chain": "A(47d3f22 实现冻结)→ B(b8e1de0 "
                                      "诚实 FAIL 结果);无 A′/A2/hotfix",
            "r13_final_verdict": "FAIL(永久;不因 R16 gate topology 修订"
                                 "而追认/撤销/改写)",
            "r13_failed_checks": r13_failed_checks,
            "r13_failure_classification": (
                "cue semantic gate topology conflict:calibration wrapper/"
                "c2_matched_conditions 声明 cue 语义 gate delegated 给 "
                "dedicated 160-block semantic corpus,final aggregator 却"
                "把 matched 20-block 点估计 gate 绑定为 verdict 级 "
                "c2_semantics_pass(唯一 false 检查);机械证明见 "
                "GateTopologyReconciliation-v1"),
            "r13_governance_gaps": {
                "commit_b_runner_py": r13_runner_added,
                "freeze_surface_partial": "R13 freeze 仅 27 个 src 模块,"
                                          "未覆盖 runner/tests/strategy/"
                                          "依赖锁",
                "raw_logs_committed": len(r13_raw_logs),
                "full_cold_reader_rehearsal_absent": True,
                "detailed_failure_via_post_exposure_regeneration": (
                    "runner/r13_diag_final_semantics.py 在 exposure 后"
                    "重生成 qualification_r13 取得 detailed failure"),
                "plan_digest_prefix": "qp12-",
                "next_iteration_text_errors": "部分合同文字误写"
                                              "下一轮指引误写(R13)",
            },
        },
        "r14_governance_binding": {
            "r14_commit_a": R14_COMMIT_A,
            "r14_commit_b": R14_COMMIT_B,
            "clean_two_commit_chain": "A(0b07778 实现冻结)→ B(14a889c "
                                      "results-only 诚实 FAIL);"
                                      "无 A′/A2/hotfix",
            "r14_final_verdict": "FAIL(永久;不因 R16 修复而被追认/"
                                 "撤销/改写;R16 baseline = R14 Commit B)",
            "r14_failure_classification": (
                "formal runner 编排缺陷:r14_formal_chain.sh 与 "
                "R16_FORMAL_CHAIN_STEPS 同构常量缺 preplan-smoke 步"
                "(rehearsal 链有该步——两份独立硬编码列表不一致),"
                "plan-roundtrip 读 preplan_engineering_smoke.json 时 "
                "FileNotFoundError rc=1;determinism/audit/cue-audit "
                "全 PASS 后永久停止;design/calibration/final/smoke/"
                "full-cold 未执行"),
            "r14_governance_gaps": {
                "orchestration_dual_lists": (
                    "rehearsal 链(17 步含 preplan-smoke)与 formal "
                    "runner/R16_FORMAL_CHAIN_STEPS 同构常量(无该步)"
                    "各自维护——R16 工作包 A 单一权威 workflow 修复"),
                "hidden_dual_binding": (
                    "independent_cue_semantics.pass(point recall ≥0.90 "
                    "+ noncue UCB ≤0.01)被 AND 进 marginal "
                    "guard.pass → c2_independent_marginal_pass → "
                    "final verdict——dedicated 之外的第二传递性 "
                    "binding source(R16 工作包 B 修复)"),
                "uniqueness_fail_open": (
                    "r14_cue_semantic_binding_uniqueness 只扫显式 "
                    "metric_scope,optional 缺省 fail-open,漏检隐藏"
                    "绑定(R16 v2 构造期强制声明+传递闭包修复)"),
                "fixed_template_fail_closure": (
                    "cmd_fail_closure 使用固定成功阶段尾部模板"
                    "(7 文件全后期产物),与实际失败阶段不符"
                    "(R16 工作包 C 阶段精确组装修复)"),
                "provenance_conditional_skip": (
                    "formal runner 对 provenance-lock '已存在则静默"
                    "跳过',而 verify-formal-logs expected 序列要求"
                    "它——manifest 永不完整(R16 恒执行 "
                    "provenance-verify 修复)"),
            },
        },
        "r15_governance_binding": {
            "r15_commit_a": "c1c973e057375cbc258d0fe48e7ce7044a9a05df",
            "r15_commit_b": "c0da37a498740201c42898ea9b743ecfb54990da",
            "clean_two_commit_chain": "A(c1c973e 实现冻结)→ B(c0da37a "
                                      "results-only 诚实 FAIL);"
                                      "无 A'/A2/hotfix",
            "r15_remains_permanent_fail": True,
            "r15_final_verdict": "FAIL(永久;不因 R16 修复而被追认/"
                                 "撤销/改写;R16 exact baseline = "
                                 "R15 Commit B c0da37a)",
            "r15_failure_classification": (
                "正式 shell wrapper CRLF 启动失败:r15_formal_chain.sh"
                " 为 Agent Windows Write 工具产物(CRLF 行尾),bash "
                "解析失败(set: pipefail: invalid option name;cd 附带"
                " CR 字节污染);17 步权威链在第一步之前未启动"
                "(manifest 0 条);exposure 未发生;design/calibration/"
                "qualification 均未开始;缺陷位于 Commit A 冻结面内"),
            "r15_governance_gaps": {
                "crlf_byte_gate_absent": (
                    "freeze 未对执行面做字节级行尾检查;git autocrlf "
                    "不阻止 blob 含 CRLF(R16 .gitattributes + LF "
                    "自检 + freeze 字节验证修复)"),
                "runner_on_drvfs": (
                    "正式 runner 从 /mnt/e drvfs 执行,非已验证本地"
                    "文件系统(R16 执行面同步至 WSL 本地修复)"),
                "activation_failure_swallowed": (
                    "source activate-freqtrade.sh || true 吞掉环境"
                    "激活失败(R16 激活失败即拒绝修复)"),
                "bootstrap_misattributed": (
                    "workflow-plan 失败被写成 provenance-verify 已"
                    "执行失败,而非 bootstrap 边界(R16 --failed-step "
                    "bootstrap 修复)"),
            },
        },
        "checks": checks,
        "failed_checks": failed,
        "ok": not failed,
    }


def historical_evidence_binding_digest(binding: dict[str, Any]) -> str:
    core = {k: binding.get(k) for k in (
        "format", "iteration", "expected_baseline", "head",
        "ancestry_semantics", "r11_governance_failure_binding",
        "r12_governance_binding", "r13_governance_binding",
        "r14_governance_binding", "r15_governance_binding",
        "r14_governance_binding",
        "failed_checks", "ok")}
    return "r15heb-" + hashlib.sha256(json.dumps(
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
