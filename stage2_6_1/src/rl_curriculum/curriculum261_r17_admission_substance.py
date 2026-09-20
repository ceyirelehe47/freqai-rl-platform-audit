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
   (cur261-r17-candidate-regression-evidence-v2),绑定 commit_a:
   - junit 原件逐个重解析(sha256 先行比对),聚合计数与 record
     声明一致;0 failures / 0 errors;
   - skipped 测试 ID 集合 == HISTORICAL_SKIP_IDS 允许表
     (scope=="formal" 强制;差分 parent 证据同规则);
   - 多文件唯一性(F3):同一 junit 文件以路径别名或同内容重复
     引用一律拒绝;跨文件 testcase ID 重叠拒绝。合法分片 = 不重
     叠 ID 的并集;不同完整运行的相同测试属不同 record,分别
     判定,绝不叠加计数,也不静默去重掩盖错误;
   - 完整集合(F1):以候选 Git 测试源树(stage2_6_1/tests/ 递归
     .py,r17_sync basename/CR 规范化映射)为唯一权威,静态推导
     应执行测试 node-ID 全集;record 必须携带 test_files 清单、
     collection 与 execution(command/interpreter/cwd/returncode
     ==0),并满足 base(collection)==静态全集(参数化后缀保留
     在 multiset 内)、collection 文件覆盖==候选 test 文件集、
     Counter(collection)==Counter(junit 实际 testcase)。计数
     一致但 ID 被替换、遗漏任何来源测试、集合不对应均拒绝;
   - 差分协议(F2):parent 为 commit_a 祖先且 parent!=commit_a、
     parent 证据**递归经过同一完整核验**(部署面除外——parent 是
     历史提交,部署面只对当前候选执行)、delta 无 src/rl_curriculum
     统计面变更(git diff --name-only 实算比对声明清单)。父
     JUnit 缺失、有失败、被替换或未全量覆盖时子差分证据拒绝;
   - 部署面(可选维度):签发/消费端在部署机上提供 deploy_root
     时,部署 tests/route_c_stage2_6_1 扁平面字节必须与候选 Git
     树规范化映射一致。离线核验(未提供 deploy_root)无法触及
     部署面,该维度仅在提供时执行;其余维度始终执行。

职责边界(2026-09-20 澄清,防误读):
1) 的实算只完成**代码身份绑定**——在 preregistration 将
plan_digest 口径定义为 "Commit A 的 git tree digest" 的前提下,
它证明"准入所指代码 = 该 tree"。它**不构成实验计划内容绑定**:
不验证计划文档/参数与审查方所见一致,也不验证 tree 内任何计划
文本的哈希。实验计划内容的约束由各自合同承担(design 侧
plan-lock 的 plan digest 口径与链上 provenance-lock),不在本模块。
2) 的回归证据核验完成**回归绿绑定**(junit 元素级 + sha256 +
commit_a 绑定 + 完整集合/唯一性/差分链),与 1) 相互独立、
缺一不可。
杜绝"签发与消费各说各话"。

v1 record(cur261-r17-candidate-regression-evidence-v1)无完整性
字段,格式不符即拒绝(fail closed);不存在需要迁移的生产 v1
record(2026-09-20 核查:仓库内无任何 v1 record 原件)。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import stat
import subprocess
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath

#: 准入格式 v2:新增必填 substance 块(v1 无实质绑定,永久停用)。
ADMISSION_FORMAT_V2 = "cur261-r17-formal-admission-v2"
SUBSTANCE_FORMAT = "cur261-r17-admission-substance-v1"
REGRESSION_EVIDENCE_FORMAT = "cur261-r17-candidate-regression-evidence-v2"
PLAN_DIGEST_METHOD_TREE = "git_tree_digest"

#: 全量回归固定历史 skip 允许表(与 runner/r17_v2_c13_admission_guard.py
#: 的 HISTORICAL_SKIP_IDS 同值;此处为准入实质绑定的独立权威副本,
#: 两表漂移由 test_admission_substance 的交叉断言暴露)。
HISTORICAL_SKIP_IDS = frozenset({
    "tests.route_c_stage2_6_1.test_curriculum261_r12_governance_r12."
    "TestHistoricalEvidenceBinding::test_ancestry_semantics_pass",
    "tests.route_c_stage2_6_1.test_curriculum261_r13_governance."
    "TestHistoricalEvidenceBindingR13::test_ancestry_and_r12_clean_chain",
    "tests.route_c_stage2_6_1.test_curriculum261_r14_governance."
    "TestHistoricalEvidenceBindingR14::test_ancestry_and_r13_clean_chain",
    "tests.route_c_stage2_6_1.test_curriculum261_r15_governance."
    "TestHistoricalEvidenceBindingR15::test_ancestry_and_r13_clean_chain",
    "tests.route_c_stage2_6_1.test_curriculum261_r16_governance."
    "TestExecutionSurfaceBytes::test_r16_formal_wrapper_selfcheck_present",
    "tests.route_c_stage2_6_1.test_curriculum261_r16_governance."
    "TestExecutionSurfaceBytes::test_runner_shell_scripts_lf",
    "tests.route_c_stage2_6_1.test_curriculum261_r16_governance."
    "TestHistoricalEvidenceBindingR16::test_ancestry_and_r15_clean_chain",
})

_SRC_PREFIX = "stage2_6_1/src/rl_curriculum/"
_TEST_SOURCE_ROOT = "stage2_6_1/tests/"
_DEPLOYED_TEST_ROOT = "tests/route_c_stage2_6_1/"
_COMMIT_RE = re.compile(r"[0-9a-f]{40}")


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


def _git_out(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise SubstanceError(
            "git_failed:" + " ".join(args[:2]))
    return proc.stdout


def git_tree_digest(repo: Path, commit_a: str) -> str:
    """Commit A 的 git tree digest 实算(唯一接受的 plan 身份口径)。"""
    proc = _git(repo, "rev-parse", "--verify", commit_a + "^{tree}")
    if proc.returncode != 0:
        raise SubstanceError("commit_a_tree_unavailable")
    out = proc.stdout.strip()
    if not out:
        raise SubstanceError("commit_a_tree_unavailable")
    return out


def _plan_method_supported(preregistration: dict) -> bool:
    method = str(preregistration.get("plan_digest_method", ""))
    return (method == PLAN_DIGEST_METHOD_TREE
            or ("^{tree}" in method and "rev-parse" in method))


# ----------------------------------------------------------- 测试源树映射

def candidate_test_map(repo: Path, commit_a: str) -> dict[str, dict]:
    """候选 Git 测试源树 → r17_sync 部署映射(与 runner/
    r17_v2_c13_admission_guard.candidate_test_map 同规则:递归
    stage2_6_1/tests/ 下全部 .py(含 conftest/支撑模块),basename
    展平到 tests/route_c_stage2_6_1/,CR 字节删除规范化;casefold
    碰撞与非 regular blob 拒绝。候选树——而非调用方清单——决定
    完整成员集。"""
    repo = Path(repo)
    if _COMMIT_RE.fullmatch(commit_a or "") is None:
        raise SubstanceError("test_source_mapping_invalid:commit_malformed")
    _git_out(repo, "cat-file", "-e", commit_a + "^{commit}")
    tree = _git_out(repo, "ls-tree", "-r", "-z", "--full-tree", commit_a,
                    "--", _TEST_SOURCE_ROOT.rstrip("/"))
    result: dict[str, dict] = {}
    folded: dict[str, str] = {}
    for item in tree.split(b"\0"):
        if not item:
            continue
        try:
            header, raw = item.split(b"\t", 1)
            mode, kind, oid = header.decode("ascii").split()
            source = raw.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError) as exc:
            raise SubstanceError(
                "test_source_mapping_invalid:malformed_tree") from exc
        if not source.endswith(".py"):
            continue
        parts = PurePosixPath(source).parts
        if not source.startswith(_TEST_SOURCE_ROOT) or ".." in parts \
                or any(c in source for c in ("\r", "\n", "\t", "\\")):
            raise SubstanceError(
                f"test_source_mapping_invalid:unsafe_path:{source}")
        if mode not in ("100644", "100755") or kind != "blob":
            raise SubstanceError(
                f"test_source_mapping_invalid:nonregular:{source}")
        leaf = parts[-1]
        destination = _DEPLOYED_TEST_ROOT + leaf
        key = destination.casefold()
        if key in folded:
            raise SubstanceError("test_source_collision:" + source)
        body = _git_out(repo, "cat-file", "blob", oid)
        normalized = body.replace(b"\r", b"")
        result[destination] = {
            "source_path": source,
            "deploy_path": destination,
            "deploy_sha256": hashlib.sha256(normalized).hexdigest(),
            "deploy_size": len(normalized),
            "is_test": leaf.startswith("test_"),
        }
        folded[key] = destination
    if not result or not any(r["is_test"] for r in result.values()):
        raise SubstanceError("test_source_mapping_empty")
    return dict(sorted(result.items()))


def static_collection_ids(repo: Path, commit_a: str) -> set[str]:
    """从候选 Git 树静态推导应收集测试的 node-ID 全集(模块级
    test_* 函数 + Test* 类一级 test_* 方法;与该仓 pytest 收集
    语义一致——2026-09-20 在真实树 b2c345e 活体验证:
    base(2303 个收集 ID)==静态 1840 全集,零幻影/零遗漏)。
    参数化维度([...] 后缀)由 multiset 精确匹配承载,不在此展开。"""
    mapping = candidate_test_map(repo, commit_a)
    ids: set[str] = set()
    for row in mapping.values():
        if not row["is_test"]:
            continue
        blob = _git_out(repo, "show", f"{commit_a}:{row['source_path']}")
        try:
            module = ast.parse(blob)
        except SyntaxError as exc:
            raise SubstanceError(
                f"test_source_unparseable:{row['source_path']}") from exc
        prefix = row["deploy_path"] + "::"
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("test_"):
                ids.add(prefix + node.name)
            elif isinstance(node, ast.ClassDef) \
                    and node.name.startswith("Test"):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef,
                                        ast.AsyncFunctionDef)) \
                            and sub.name.startswith("test_"):
                        ids.add(prefix + node.name + "::" + sub.name)
    if not ids:
        raise SubstanceError("static_collection_empty")
    return ids


def junit_nodeid(classname: str, name: str) -> str:
    """junit classname::name → pytest node-ID(与 runner/
    r17_v2_c13_admission_guard.junit_nodeid 同转换;两实现漂移由
    test_admission_substance 交叉断言暴露)。"""
    parts = classname.split(".")
    if parts[:2] != ["tests", "route_c_stage2_6_1"] or len(parts) < 3 \
            or not parts[2].startswith("test_"):
        raise SubstanceError(
            f"regression_junit_classname_unknown:{classname}")
    return "/".join(parts[:3]) + ".py::" + "::".join(parts[3:] + [name])


def _param_base(node_id: str) -> str:
    head, sep, last = node_id.rpartition("::")
    if "[" in last:
        last = last[:last.index("[")]
    return head + sep + last if sep else last


def verify_deployment_surface(deploy_root: Path, mapping: dict) -> None:
    """部署测试面只读核验:tests/route_c_stage2_6_1 扁平面成员与
    字节必须等于候选映射(与 guard.deployment_test_errors 同规则;
    不一致即 SubstanceError)。"""
    directory = Path(deploy_root) / _DEPLOYED_TEST_ROOT
    if not directory.is_dir():
        raise SubstanceError(
            "regression_deployment_surface_mismatch:missing_dir")
    found: dict[str, Path] = {}
    for path in sorted(directory.iterdir()):
        st = path.lstat()
        if path.name == "__pycache__" and stat.S_ISDIR(st.st_mode):
            continue
        if path.suffix == ".py":
            found[_DEPLOYED_TEST_ROOT + path.name] = path
        elif stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode):
            raise SubstanceError(
                "regression_deployment_surface_mismatch:unexpected:"
                + path.name)
    if set(found) != set(mapping):
        raise SubstanceError(
            "regression_deployment_surface_mismatch:"
            + json.dumps({
                "missing": sorted(set(mapping) - set(found))[:3],
                "extra": sorted(set(found) - set(mapping))[:3]},
                ensure_ascii=False))
    for dp, path in found.items():
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != mapping[dp]["deploy_sha256"] \
                or len(body) != mapping[dp]["deploy_size"]:
            raise SubstanceError(
                f"regression_deployment_surface_mismatch:bytes:{dp}")


# ----------------------------------------------------------- junit 解析

def parse_junit(path: Path) -> dict:
    """junit XML 元素级重解析(不信 record 声明,也不信 suite 汇总属性)。

    计数全部从 <testcase> 子元素逐个清点(failure/error/skipped),
    再与 testsuite 聚合属性交叉核对:两边不一致 => 拒绝(捕捉
    "属性为绿但实际含 failure/error"的伪造/损坏 junit)。
    skipped 测试 ID、用例 ID 唯一性与非空性一并核验;
    返回 case_id 列表(classname::name,保序)供多文件唯一性与
    执行 multiset 核验。
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
    case_ids: list[str] = []
    seen_cases: set[str] = set()
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
            if cid in seen_cases:
                raise SubstanceError(
                    f"regression_junit_duplicate_testcase:{cid}")
            seen_cases.add(cid)
            case_ids.append(cid)
            element_totals["failures"] += len(case.findall("failure"))
            element_totals["errors"] += len(case.findall("error"))
            if case.find("skipped") is not None:
                element_totals["skipped"] += 1
                skipped_ids.append(cid)
    element_totals["tests"] = len(seen_cases)
    if element_totals["tests"] == 0:
        raise SubstanceError(f"regression_junit_empty:{path.name}")
    for key in ("tests", "failures", "errors", "skipped"):
        if attr_totals[key] != element_totals[key]:
            raise SubstanceError(
                f"regression_junit_element_attribute_mismatch:{key}"
                f"({element_totals[key]}!={attr_totals[key]})")
    return {**element_totals, "skipped_ids": skipped_ids,
            "case_ids": case_ids}


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


def _verify_test_files_manifest(record: dict, mapping: dict) -> None:
    rows = record.get("test_files")
    if not isinstance(rows, list) or not rows:
        raise SubstanceError("regression_test_files_missing")
    by_deploy: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SubstanceError("regression_test_files_missing:row")
        dp = row.get("deploy_path")
        if not isinstance(dp, str) or not dp or dp in by_deploy:
            raise SubstanceError(
                "regression_test_files_mismatch:duplicate_or_bad_row")
        by_deploy[dp] = row
    if set(by_deploy) != set(mapping):
        raise SubstanceError(
            "regression_test_files_mismatch:"
            + json.dumps({
                "missing": sorted(set(mapping) - set(by_deploy))[:3],
                "extra": sorted(set(by_deploy) - set(mapping))[:3],
                "missing_n": len(set(mapping) - set(by_deploy)),
                "extra_n": len(set(by_deploy) - set(mapping))},
                ensure_ascii=False))
    for dp, row in by_deploy.items():
        if row != mapping[dp]:
            raise SubstanceError(f"regression_test_files_mismatch:{dp}")


def _verify_collection(record: dict, mapping: dict,
                       static_ids: set[str],
                       executed: Counter) -> list[str]:
    collection = record.get("collection")
    if not isinstance(collection, list) or not collection \
            or any(not isinstance(c, str) or "::" not in c
                   for c in collection):
        raise SubstanceError("regression_collection_missing")
    if len(set(collection)) != len(collection):
        raise SubstanceError("regression_collection_duplicate")
    bases = {_param_base(c) for c in collection}
    if bases != static_ids:
        raise SubstanceError(
            "regression_collection_static_mismatch:"
            + json.dumps({
                "static": len(static_ids), "collected_bases": len(bases),
                "not_collected": sorted(static_ids - bases)[:3],
                "unknown": sorted(bases - static_ids)[:3]},
                ensure_ascii=False))
    expected_files = {dp for dp, r in mapping.items() if r["is_test"]}
    represented = {c.split("::", 1)[0] for c in collection}
    if represented != expected_files:
        raise SubstanceError("regression_collection_file_coverage_mismatch")
    if Counter(collection) != executed:
        raise SubstanceError("regression_collection_execution_mismatch")
    return collection


def _verify_execution_provenance(record: dict) -> None:
    ex = record.get("execution")
    if not isinstance(ex, dict):
        raise SubstanceError("regression_execution_provenance_invalid")
    cmd = ex.get("command")
    if not (isinstance(cmd, list) and cmd
            and all(isinstance(a, str) and a for a in cmd)):
        raise SubstanceError("regression_execution_provenance_invalid")
    if not (isinstance(ex.get("interpreter"), str) and ex["interpreter"]
            and isinstance(ex.get("cwd"), str) and ex["cwd"]
            and type(ex.get("returncode")) is int):
        raise SubstanceError("regression_execution_provenance_invalid")
    if ex["returncode"] != 0:
        raise SubstanceError("regression_execution_provenance_invalid")


def verify_regression_evidence(record_path: Path, repo: Path,
                               commit_a: str, *,
                               deploy_root: Path | None = None) -> dict:
    """核验候选回归证据原件(v2;F1/F2/F3 完整收敛)。

    junit 逐个重解析计数比对 + 多文件唯一性 + 候选树完整集合 +
    (差分)父证据同一完整核验;可选 deploy_root 时加部署面字节
    核验。任何维度不符 => SubstanceError(fail closed)。
    """
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
    executed: Counter = Counter()
    seen_paths: set[Path] = set()
    seen_shas: set[str] = set()
    case_owner: dict[str, str] = {}
    for entry in junit_files:
        if not isinstance(entry, dict) or "path" not in entry:
            raise SubstanceError("regression_evidence_junit_entry_invalid")
        jp = _resolve(record_path, entry["path"])
        resolved = jp.resolve()
        if resolved in seen_paths:
            raise SubstanceError(
                f"regression_junit_duplicate_path:{jp.name}")
        seen_paths.add(resolved)
        if not jp.is_file():
            raise SubstanceError(f"regression_junit_missing:{jp.name}")
        sha = _sha256_file(jp)
        if sha != entry.get("sha256"):
            raise SubstanceError(f"regression_junit_sha_mismatch:{jp.name}")
        if sha in seen_shas:
            raise SubstanceError(
                f"regression_junit_duplicate_content:{sha[:12]}")
        seen_shas.add(sha)
        parsed = parse_junit(jp)
        for key in aggregate:
            aggregate[key] += parsed[key]
        skipped_ids.extend(parsed["skipped_ids"])
        for cid in parsed["case_ids"]:
            if cid in case_owner:
                raise SubstanceError(
                    "regression_junit_duplicate_testcase_across_files:"
                    + cid)
            case_owner[cid] = jp.name
            classname, _, name = cid.partition("::")
            executed[junit_nodeid(classname, name)] += 1
    _verify_counts(record, aggregate, skipped_ids, "regression")

    protocol = record.get("protocol")
    if protocol == "differential":
        diff_scope = record.get("differential", {})
        parent = diff_scope.get("parent_commit", "")
        if not parent:
            raise SubstanceError("differential_parent_missing")
        if parent == commit_a:
            raise SubstanceError("differential_parent_is_candidate")
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

    # ---- 完整集合(F1):候选树为权威,静态全集 + 清单 + collection
    mapping = candidate_test_map(repo, commit_a)
    _verify_test_files_manifest(record, mapping)
    static_ids = static_collection_ids(repo, commit_a)
    collection = _verify_collection(record, mapping, static_ids, executed)
    _verify_execution_provenance(record)
    if deploy_root is not None:
        verify_deployment_surface(deploy_root, mapping)

    # ---- 差分父证据(F2):递归同一完整核验(部署面除外——历史提交)
    if protocol == "differential":
        try:
            verify_regression_evidence(parent_path, repo, parent)
        except SubstanceError as exc:
            raise SubstanceError(
                f"differential_parent_evidence_rejected:{exc}") from None
    return {"record": record, "record_sha256": record_sha,
            "aggregate": aggregate,
            "collection_tests": len(collection),
            "static_tests": len(static_ids),
            "test_files": len(mapping)}


def verify_preregistration_substance(repo: Path, commit_a: str,
                                     preregistration: dict, *,
                                     deploy_root: Path | None = None
                                     ) -> dict:
    """签发端实质验证:plan digest 实算 + 回归证据核验 → substance。"""
    if not _plan_method_supported(preregistration):
        raise SubstanceError("plan_digest_method_unsupported")
    tree = git_tree_digest(repo, commit_a)
    if preregistration.get("plan_digest") != tree:
        raise SubstanceError("plan_digest_mismatch")
    raw_ev = preregistration.get("regression_evidence")
    if not raw_ev:
        raise SubstanceError("regression_evidence_not_preregistered")
    evidence = verify_regression_evidence(Path(raw_ev), repo, commit_a,
                                          deploy_root=deploy_root)
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
            "collection_tests": evidence["collection_tests"],
            "test_files": evidence["test_files"],
        },
        "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime()),
    }


def verify_admission_substance(admission: dict, repo: Path, *,
                               deploy_root: Path | None = None
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
            Path(ev_path), repo, admission["commit_a_sha"],
            deploy_root=deploy_root)
    except SubstanceError as exc:
        return False, f"admission_substance_invalid:{exc}"
    if evidence["record_sha256"] != ev.get("sha256"):
        return False, "admission_evidence_replaced"
    return True, "ok"


def main(argv: list[str] | None = None) -> int:
    """签发器子进程入口:verify --repo R --commit-a SHA
    --preregistration P [--deploy-root D]

    成功打印 substance JSON(rc=0);失败打印 SubstanceError 原因(rc=2)。
    --deploy-root 提供时执行部署测试面字节核验(签发端在部署机上)。
    """
    import argparse

    ap = argparse.ArgumentParser(description="R17 准入实质绑定验证(同源)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--repo", type=Path, required=True)
    v.add_argument("--commit-a", required=True)
    v.add_argument("--preregistration", type=Path, required=True)
    v.add_argument("--deploy-root", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        prereg = json.loads(
            args.preregistration.read_text(encoding="utf-8"))
        substance = verify_preregistration_substance(
            args.repo, args.commit_a, prereg,
            deploy_root=args.deploy_root)
    except SubstanceError as exc:
        print(str(exc))
        return 2
    print(json.dumps({"substance": substance,
                      "substance_digest": substance_digest(substance)},
                     ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
