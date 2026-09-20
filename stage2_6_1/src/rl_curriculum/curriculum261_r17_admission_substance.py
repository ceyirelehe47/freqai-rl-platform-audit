# -*- coding: utf-8 -*-
"""R17 正式准入实质绑定(外部审查 RouteC_R18_Report_Review_4a5d2fd
§4.2 收口;erratum 开放门 §4.2)。

签发端(runner/r17_admission_issue.py)与消费端
(curriculum261_r17_admission.py)共用的**唯一**验证实现(同源核验):

1. plan 身份实算:preregistration.plan_digest 必须等于 Commit A 的
   git tree digest 复算值(git rev-parse <sha>^{tree};现行
   preregistration 口径)。只接受该口径;未知口径 fail closed。
   签发时写一个 digest 字段本身不构成验证——必须重算比对。
2. 候选回归证据核验:机读 regression evidence record
   (cur261-r17-candidate-regression-evidence-v1),绑定 commit_a:
   - junit 原件逐个重解析(sha256 先行比对),聚合计数与 record
     声明一致;0 failures / 0 errors;
   - skipped 测试 ID 集合 == HISTORICAL_SKIP_IDS 允许表
     (scope=="formal" 强制;差分 parent 证据同规则);
   - protocol=="differential"(erratum 勘误三)另需:parent 为
     commit_a 祖先、parent 证据为全量绿(scope=="formal" 的
     protocol=="full")、delta 无 src/rl_curriculum 统计面变更
     (git diff --name-only 实算比对声明清单)。

职责边界(2026-09-20 澄清,防误读):
1) 的实算只完成**代码身份绑定**——在 preregistration 将
plan_digest 口径定义为 "Commit A 的 git tree digest" 的前提下,
它证明"准入所指代码 = 该 tree"。它**不构成实验计划内容绑定**:
不验证计划文档/参数与审查方所见一致,也不验证 tree 内任何计划
文本的哈希。实验计划内容的约束由各自合同承担(design 侧
plan-lock 的 plan digest 口径与链上 provenance-lock),不在本模块。
2) 的回归证据核验完成**回归绿绑定**(junit 元素级 + sha256 +
commit_a 绑定),与 1) 相互独立、缺一不可。
杜绝"签发与消费各说各话"。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

#: 准入格式 v2:新增必填 substance 块(v1 无实质绑定,永久停用)。
ADMISSION_FORMAT_V2 = "cur261-r17-formal-admission-v2"
SUBSTANCE_FORMAT = "cur261-r17-admission-substance-v1"
REGRESSION_EVIDENCE_FORMAT = "cur261-r17-candidate-regression-evidence-v1"
PLAN_DIGEST_METHOD_TREE = "git_tree_digest"

#: 全量回归固定历史 skip 允许表(与 runner/r17_v2_c13_admission_guard.py
#: 的 HISTORICAL_SKIP_IDS 同值;此处为准入实质绑定的独立权威副本,
#: 两表漂移由 test_admission_substance 的交叉断言暴露)。
HISTORICAL_SKIP_IDS = frozenset({
    'tests.route_c_stage2_6_1.test_curriculum261_r12_governance_r12.'
    'TestHistoricalEvidenceBinding::test_ancestry_semantics_pass',
    'tests.route_c_stage2_6_1.test_curriculum261_r13_governance.'
    'TestHistoricalEvidenceBindingR13::test_ancestry_and_r12_clean_chain',
    'tests.route_c_stage2_6_1.test_curriculum261_r14_governance.'
    'TestHistoricalEvidenceBindingR14::test_ancestry_and_r13_clean_chain',
    'tests.route_c_stage2_6_1.test_curriculum261_r15_governance.'
    'TestHistoricalEvidenceBindingR15::test_ancestry_and_r13_clean_chain',
    'tests.route_c_stage2_6_1.test_curriculum261_r16_governance.'
    'TestExecutionSurfaceBytes::test_runner_shell_scripts_lf',
    'tests.route_c_stage2_6_1.test_curriculum261_r16_governance.'
    'TestExecutionSurfaceBytes::test_r16_formal_wrapper_selfcheck_present',
    'tests.route_c_stage2_6_1.test_curriculum261_r16_governance.'
    'TestHistoricalEvidenceBindingR16::test_ancestry_and_r15_clean_chain',
})

_SRC_PREFIX = "stage2_6_1/src/rl_curriculum/"


class SubstanceError(RuntimeError):
    """实质绑定失败(fail closed;message 即拒绝原因)。"""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def substance_digest(substance: dict) -> str:
    return "r17sub-" + hashlib.sha256(
        _canonical(substance).encode("utf-8")).hexdigest()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=120)


def git_tree_digest(repo: Path, commit_a: str) -> str:
    """Commit A 的 git tree digest 实算(唯一接受的 plan 身份口径)。"""
    proc = _git(repo, "rev-parse", commit_a + "^{tree}")
    if proc.returncode != 0:
        raise SubstanceError("plan_digest_repo_unreadable")
    out = proc.stdout.strip()
    if not out:
        raise SubstanceError("plan_digest_repo_unreadable")
    return out


def _plan_method_supported(preregistration: dict) -> bool:
    method = str(preregistration.get("plan_digest_method", ""))
    return (method == PLAN_DIGEST_METHOD_TREE
            or ("^{tree}" in method and "rev-parse" in method))


def parse_junit(path: Path) -> dict:
    """junit XML 元素级重解析(不信 record 声明,也不信 suite 汇总属性)。

    计数全部从 <testcase> 子元素逐个清点(failure/error/skipped),
    再与 testsuite 聚合属性交叉核对:两边不一致 => 拒绝(捕捉
    "属性为绿但实际含 failure/error"的伪造/损坏 junit)。
    skipped 测试 ID 与用例 ID 唯一性一并核验。
    """
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise SubstanceError(
            f"regression_junit_unreadable:{path.name}") from exc

    def _int(el, key) -> int:
        raw = el.get(key, "0") or "0"
        try:
            return int(float(raw))
        except ValueError:
            return 0

    attr_totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    element_totals = {"tests": 0, "failures": 0, "errors": 0,
                      "skipped": 0}
    skipped_ids: list[str] = []
    case_ids: set[str] = set()
    suites = [root] if root.tag == "testsuite" else []
    suites.extend(root.iter("testsuite"))
    seen_roots = set()
    for suite in suites:
        if id(suite) in seen_roots:
            continue
        seen_roots.add(id(suite))
        for key in attr_totals:
            attr_totals[key] += _int(suite, key)
        for case in suite.iter("testcase"):
            cid = case.get("classname", "") + "::" + case.get("name", "")
            if not case.get("name"):
                raise SubstanceError(
                    f"regression_junit_testcase_malformed:{path.name}")
            if cid in case_ids:
                raise SubstanceError(
                    f"regression_junit_duplicate_testcase:{cid}")
            case_ids.add(cid)
            element_totals["failures"] += len(case.findall("failure"))
            element_totals["errors"] += len(case.findall("error"))
            if case.find("skipped") is not None:
                element_totals["skipped"] += 1
                skipped_ids.append(cid)
    element_totals["tests"] = len(case_ids)
    for key in ("tests", "failures", "errors", "skipped"):
        if attr_totals[key] != element_totals[key]:
            raise SubstanceError(
                f"regression_junit_element_attribute_mismatch:{key}"
                f"({element_totals[key]}!={attr_totals[key]})")
    return {**element_totals, "skipped_ids": skipped_ids}


def _resolve(record_path: Path, raw: str) -> Path:
    p = Path(raw)
    return p if p.is_absolute() else (record_path.parent / p)


def _verify_counts(record: dict, aggregate: dict, skipped_ids: list[str],
                   label: str) -> None:
    declared = record.get("counts", {})
    for key in ("tests", "failures", "errors", "skipped"):
        if aggregate[key] != declared.get(key):
            raise SubstanceError(
                f"{label}_count_mismatch:{key}"
                f"({aggregate[key]}!={declared.get(key)})")
    if aggregate["failures"] != 0 or aggregate["errors"] != 0:
        raise SubstanceError(f"{label}_not_green")
    allowed = set(record.get("historical_skip_ids", []))
    if len(allowed) != len(record.get("historical_skip_ids", [])):
        raise SubstanceError(f"{label}_skip_ids_duplicated")
    if set(skipped_ids) != allowed:
        raise SubstanceError(f"{label}_skip_ids_mismatch")
    if record.get("scope") == "formal" and allowed != HISTORICAL_SKIP_IDS:
        raise SubstanceError(f"{label}_skip_ids_outside_allowed_table")


def verify_regression_evidence(record_path: Path, repo: Path,
                               commit_a: str) -> dict:
    """核验候选回归证据原件;junit 逐个重解析计数比对。"""
    record_path = Path(record_path)
    if not record_path.is_file():
        raise SubstanceError("regression_evidence_missing")
    record_sha = _sha256_file(record_path)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SubstanceError("regression_evidence_unreadable") from exc
    if not isinstance(record, dict) \
            or record.get("format") != REGRESSION_EVIDENCE_FORMAT:
        raise SubstanceError("regression_evidence_format_mismatch")
    if record.get("commit_a_sha") != commit_a:
        raise SubstanceError("regression_evidence_commit_unbound")
    if record.get("scope") != "formal":
        raise SubstanceError("regression_evidence_scope_not_formal")
    junit_files = record.get("junit")
    if not isinstance(junit_files, list) or not junit_files:
        raise SubstanceError("regression_evidence_junit_empty")
    aggregate = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skipped_ids: list[str] = []
    for entry in junit_files:
        if not isinstance(entry, dict) or "path" not in entry:
            raise SubstanceError("regression_evidence_junit_entry_invalid")
        jp = _resolve(record_path, entry["path"])
        if not jp.is_file():
            raise SubstanceError(f"regression_junit_missing:{jp.name}")
        if _sha256_file(jp) != entry.get("sha256"):
            raise SubstanceError(f"regression_junit_sha_mismatch:{jp.name}")
        parsed = parse_junit(jp)
        for key in aggregate:
            aggregate[key] += parsed[key]
        skipped_ids.extend(parsed["skipped_ids"])
    _verify_counts(record, aggregate, skipped_ids, "regression")

    protocol = record.get("protocol")
    if protocol == "differential":
        diff_scope = record.get("differential", {})
        parent = diff_scope.get("parent_commit", "")
        if not parent:
            raise SubstanceError("differential_parent_missing")
        anc = _git(repo, "merge-base", "--is-ancestor", parent, commit_a)
        if anc.returncode != 0:
            raise SubstanceError("differential_parent_not_ancestor")
        parent_ev = diff_scope.get("parent_evidence", {})
        parent_path = _resolve(record_path, parent_ev.get("path", ""))
        if not parent_path.is_file() \
                or _sha256_file(parent_path) != parent_ev.get("sha256"):
            raise SubstanceError("differential_parent_evidence_invalid")
        parent_rec = json.loads(parent_path.read_text(encoding="utf-8"))
        if parent_rec.get("protocol") != "full" \
                or parent_rec.get("commit_a_sha") != parent:
            raise SubstanceError("differential_parent_not_full_green_bound")
        name_only = _git(repo, "diff", "--name-only", parent, commit_a)
        if name_only.returncode != 0:
            raise SubstanceError("differential_diff_unreadable")
        changed = [ln for ln in name_only.stdout.splitlines() if ln]
        declared = diff_scope.get("delta_scope", {})
        src_changed = [f for f in changed if f.startswith(_SRC_PREFIX)]
        if src_changed:
            raise SubstanceError("differential_src_changed")
        for region in ("tests_files", "runner_files", "other_files"):
            declared_list = declared.get(region, [])
            if not isinstance(declared_list, list):
                raise SubstanceError("differential_delta_scope_invalid")
        declared_all = set(declared.get("tests_files", [])
                           + declared.get("runner_files", [])
                           + declared.get("other_files", []))
        undeclared = [f for f in changed
                      if not f.startswith(_SRC_PREFIX)
                      and f not in declared_all]
        if undeclared:
            raise SubstanceError("differential_undeclared_files")
    elif protocol != "full":
        raise SubstanceError("regression_evidence_protocol_invalid")
    return {"record": record, "record_sha256": record_sha,
            "aggregate": aggregate}


def verify_preregistration_substance(repo: Path, commit_a: str,
                                     preregistration: dict) -> dict:
    """签发端实质验证:plan digest 实算 + 回归证据核验 → substance。"""
    if not _plan_method_supported(preregistration):
        raise SubstanceError("plan_digest_method_unsupported")
    tree = git_tree_digest(repo, commit_a)
    if preregistration.get("plan_digest") != tree:
        raise SubstanceError("plan_digest_mismatch")
    raw_ev = preregistration.get("regression_evidence")
    if not raw_ev:
        raise SubstanceError("regression_evidence_not_preregistered")
    evidence = verify_regression_evidence(Path(raw_ev), repo, commit_a)
    rec = evidence["record"]
    return {
        "format": SUBSTANCE_FORMAT,
        "plan_digest_method": PLAN_DIGEST_METHOD_TREE,
        "plan_digest_claimed": preregistration["plan_digest"],
        "plan_digest_recomputed": tree,
        "regression_evidence": {
            "path": str(Path(raw_ev)),
            "sha256": evidence["record_sha256"],
            "protocol": rec.get("protocol"),
            "counts": rec.get("counts", {}),
            "scope": rec.get("scope"),
        },
        "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime()),
    }


def verify_admission_substance(admission: dict, repo: Path,
                               ) -> tuple[bool, str]:
    """消费端同源复验:同一实现重算比对 admission 携带的 substance。"""
    substance = admission.get("substance")
    if not isinstance(substance, dict) \
            or substance.get("format") != SUBSTANCE_FORMAT:
        return False, "admission_substance_missing"
    if admission.get("substance_digest") != substance_digest(substance):
        return False, "admission_substance_digest_mismatch"
    try:
        tree = git_tree_digest(repo, admission["commit_a_sha"])
    except SubstanceError as exc:
        return False, f"admission_substance_invalid:{exc}"
    if tree != substance.get("plan_digest_recomputed") \
            or tree != admission.get("plan_digest"):
        return False, "admission_plan_digest_mismatch"
    ev = substance.get("regression_evidence", {})
    ev_path = ev.get("path", "")
    if not ev_path:
        return False, "admission_substance_invalid:evidence_path_missing"
    try:
        evidence = verify_regression_evidence(
            Path(ev_path), repo, admission["commit_a_sha"])
    except SubstanceError as exc:
        return False, f"admission_substance_invalid:{exc}"
    if evidence["record_sha256"] != ev.get("sha256"):
        return False, "admission_evidence_replaced"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    """签发器子进程入口:verify --repo R --commit-a SHA --preregistration P

    成功打印 substance JSON(rc=0);失败打印 SubstanceError 原因(rc=2)。
    """
    import argparse

    ap = argparse.ArgumentParser(description="R17 准入实质绑定验证(同源)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--repo", type=Path, required=True)
    v.add_argument("--commit-a", required=True)
    v.add_argument("--preregistration", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        prereg = json.loads(
            args.preregistration.read_text(encoding="utf-8"))
        substance = verify_preregistration_substance(
            args.repo, args.commit_a, prereg)
    except SubstanceError as exc:
        print(str(exc))
        return 2
    print(json.dumps({"substance": substance,
                      "substance_digest": substance_digest(substance)},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
