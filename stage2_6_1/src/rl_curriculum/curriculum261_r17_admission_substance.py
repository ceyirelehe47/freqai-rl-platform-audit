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
   (cur261-r17-candidate-regression-evidence-v3),绑定 commit_a:
   - junit 原件逐个重解析(sha256 先行比对),聚合计数与 record
     声明一致;0 failures / 0 errors;
   - skipped 测试 ID 集合 == HISTORICAL_SKIP_IDS 允许表
     (scope=="formal" 强制;差分 parent 证据同规则);
   - 多文件唯一性(F3):同一 junit 文件以路径别名或同内容重复
     引用一律拒绝;跨文件 testcase ID 重叠拒绝。合法分片 = 不重
     叠 ID 的并集;不同完整运行的相同测试属不同 record,分别
     判定,绝不叠加计数,也不静默去重掩盖错误;
   - 完整参数实例(F1,v3):期望全集来自 record 携带的
     collection_run 原件——同候选、受控环境下真实 pytest
     --collect-only -q 的 stdout 原件(sha256 绑定),由本模块
     自行重解析出展开后的 node-ID 全集(参数化 fixture/
     generate_tests 展开全在其中),并与 junit 实际 testcase
     multiset 精确相等;静态 AST 基础函数全集降级为旁证交叉
     核对(base(collection)==静态全集、文件覆盖==候选测试文件
     集、候选树 conftest 不得携带收集过滤 hook)。子集 collection
     与子集 JUnit 彼此一致、同数换实例、仅跑部分参数实例均拒绝;
   - 执行来源绑定(v3):collection_run 与 execution 两段各自携带
     真实 command/interpreter/cwd/returncode==0/起止时间与
     stdout/stderr 原件(sha256 绑定);execution stdout 的 pytest
     摘要行必须与 junit 元素级计数一致;两段 interpreter/cwd/
     python 版本/pytest 版本+插件清单/PYTEST_ADDOPTS/配置扫描
     必须彼此一致(full 协议 argv 不得携带任何范围筛选入口,
     提供部署面时 cwd==deploy_root、interpreter==验证进程解释器、
     配置候选文件字节与收集时一致且无过滤内容);
   - import 面(v3):record.import_surface.members 必须等于候选
     Git 树 stage2_6_1/src/rl_curriculum 全体 .py blob 的 sha256
     映射;提供部署面时逐成员字节必须与部署 src 一致,部署侧
     多出的模块必须恰为 record 声明的 deploy_extra_modules;
   - 差分协议(F2):parent 为 commit_a 祖先且 parent!=commit_a、
     parent 证据**递归经过同一完整核验**(v3;部署面除外——
     parent 是历史提交,部署面只对当前候选执行)、delta 无
     src/rl_curriculum 统计面变更(git diff --name-only 实算比对
     声明清单)。差分子记录自身的收集/执行原件按同一 v3 规则
     绑定(positionals=声明的 delta 目标)。父 JUnit 缺失、有
     失败、被替换或未全量覆盖时子差分证据拒绝;
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

v2 record(cur261-r17-candidate-regression-evidence-v2)无收集原件
与执行来源绑定,2026-09-25 起格式不符即拒绝(fail closed;仓库内
v2 原件保留为历史证据,不迁移、不倒填,不可用于新签发)。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import stat
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path, PurePosixPath

#: 准入格式 v2:新增必填 substance 块(v1 无实质绑定,永久停用)。
ADMISSION_FORMAT_V2 = "cur261-r17-formal-admission-v2"
SUBSTANCE_FORMAT = "cur261-r17-admission-substance-v1"
#: v3(2026-09-25):完整收集原件/执行来源绑定;v2 及更早 record 无
#: collection_run 原件与两段同源身份,不满足新完整实例规则,fail
#: closed(历史 v2 原件保留历史意义,不迁移、不倒填,不可用于新签发)。
REGRESSION_EVIDENCE_FORMAT = "cur261-r17-candidate-regression-evidence-v3"
PLAN_DIGEST_METHOD_TREE = "git_tree_digest"

#: v3 全量运行 argv 过滤面:任何会改变测试范围/收集语义的入口
#: 出现在 full 协议 command 中即拒绝(fail closed;targeted 定向
#: 开发测试不经过本模块 full 路径)。
_ARGV_FORBIDDEN = frozenset({
    "-k", "-m", "-M", "--marker", "--deselect", "--ignore",
    "--ignore-glob", "--lf", "--last-failed", "--ff", "--failed-first",
    "-x", "--exitfirst", "--maxfail", "--stepwise", "--sw", "-p",
    "--rootdir", "--pyargs",
})
#: 允许出现的非过滤旗标(执行段 --collect-only 出现即拒绝)。
_VALUE_FLAGS = frozenset({"--junitxml", "--timeout", "-n"})
_CONFT_HOOKS = frozenset({"pytest_collection_modifyitems",
                          "pytest_ignore_collect"})
_CONFIG_CANDIDATES = ("pytest.ini", "pyproject.toml", "tox.ini",
                     "setup.cfg", "conftest.py")
_ENV_IDENTITY_KEYS = ("python_version", "pytest_version_output",
                      "pytest_addopts", "pytest_plugins_env",
                      "config_scan")
_COLLECTED_ID_RE = re.compile(
    r"^tests/route_c_stage2_6_1/\S+\.py::\S+$")
_OUT_OF_ROOT_ID_RE = re.compile(r"^\s*\S+\.py::\S+")
_COLLECT_SUMMARY_RE = re.compile(r"^(\d+) tests? collected in ")
_PASSED_SUMMARY_RE = re.compile(
    r"(\d+) passed(?:, (\d+) skipped)?[^\n]*\bin\b")

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
    if record.get("scope") == "formal":
        # full:skip 恰为历史允许表;差分:delta 内允许的 skip 必须
        # 仍在表内(差分子集不含全部历史 skip 属正常)。
        if record.get("protocol") == "full":
            if allowed != HISTORICAL_SKIP_IDS:
                raise SubstanceError(
                    f"{label}_skip_ids_outside_allowed_table")
        elif allowed - HISTORICAL_SKIP_IDS:
            raise SubstanceError(
                f"{label}_skip_ids_outside_allowed_table")


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


def parse_collection_stdout(text: str) -> list[str]:
    """真实 ``pytest --collect-only -q`` stdout 原件 → 展开 node-ID。

    只接受本项目测试根(``tests/route_c_stage2_6_1/``)下合法的
    node-ID 行;要求恰好一行 ``N tests collected in ...`` 且 N 与
    ID 行数一致;根外 ``*.py::`` 行视为收集范围泄漏直接拒绝。
    参数化 fixture / pytest_generate_tests 的展开实例全部体现为
    各自的 node-ID 行——这就是 v3 期望全集的权威来源,不再接受
    调用方自报 ID 列表。
    """
    ids: list[str] = []
    counts: list[int] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r").strip()
        if not line:
            continue
        matched = _COLLECT_SUMMARY_RE.match(line)
        if matched:
            counts.append(int(matched.group(1)))
            continue
        if _COLLECTED_ID_RE.match(line):
            ids.append(line)
            continue
        if _OUT_OF_ROOT_ID_RE.match(line):
            raise SubstanceError(
                "regression_collection_scope_leak:" + line[:160])
    if len(counts) != 1:
        raise SubstanceError(
            "regression_collection_summary_lines:" + str(len(counts)))
    if counts[0] != len(ids):
        raise SubstanceError(
            f"regression_collection_count_mismatch"
            f"({counts[0]}!={len(ids)})")
    if not ids:
        raise SubstanceError("regression_collection_empty")
    if len(set(ids)) != len(ids):
        raise SubstanceError("regression_collection_duplicate")
    return ids


def _artifact_bytes(record_path: Path, block, label: str) -> bytes:
    """record 内 {path, sha256} 原件引用:存在 + 字节重算一致。"""
    if not (isinstance(block, dict)
            and isinstance(block.get("path"), str) and block["path"]
            and isinstance(block.get("sha256"), str)):
        raise SubstanceError(f"{label}_artifact_invalid")
    path = _resolve(record_path, block["path"])
    if not path.is_file():
        raise SubstanceError(f"{label}_artifact_missing")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != block["sha256"]:
        raise SubstanceError(f"{label}_artifact_sha_mismatch")
    return data


def _verify_run_argv(command, *, collect_only: bool,
                     positionals_rule) -> None:
    """argv 过滤面:任何范围筛选入口即拒;positionals 必须与规则
    精确一致——完整目录(单 run full)、根内分片/差分目标
    ("under_root" 时仅要求全部落在测试根下,成员完整性由
    collection/junit 并集规则承载)。"""
    if not (isinstance(command, list) and len(command) >= 3
            and all(isinstance(a, str) and a for a in command)
            and command[1] == "-m" and command[2] == "pytest"):
        raise SubstanceError("regression_run_command_shape_invalid")
    args = command[3:]
    positionals: list[str] = []
    expect_value = False
    for tok in args:
        if expect_value:
            expect_value = False
            continue
        if tok.startswith("-"):
            name = tok.split("=", 1)[0]
            if name in _ARGV_FORBIDDEN:
                raise SubstanceError(f"regression_run_argv_filter:{name}")
            if "=" not in tok and name in _VALUE_FLAGS:
                expect_value = True
            continue
        positionals.append(tok)
    if collect_only and "--collect-only" not in args:
        raise SubstanceError("regression_run_collect_only_missing")
    if not collect_only and "--collect-only" in args:
        raise SubstanceError("regression_run_collect_only_unexpected")
    if positionals_rule == "under_root":
        if not positionals:
            raise SubstanceError("regression_run_shard_targets_missing")
        for target in positionals:
            if not target.startswith(_DEPLOYED_TEST_ROOT):
                raise SubstanceError(
                    "regression_run_target_outside_root:" + target)
    else:
        if positionals != list(positionals_rule):
            raise SubstanceError(
                "regression_run_argv_target_mismatch:"
                + json.dumps(positionals[:3]))


def _scan_config_files(root: Path, target_dir: str) -> list[Path]:
    """cwd(root) → 测试目录链上的 pytest 配置候选文件(只读)。"""
    base = (root / target_dir).resolve()
    chain = [base]
    top = Path(root).resolve()
    guard = 0
    while chain[-1] != top:
        parent = chain[-1].parent
        if parent == chain[-1] or guard > 64:
            raise SubstanceError("regression_config_scan_failed")
        chain.append(parent)
        guard += 1
    files: list[Path] = []
    for directory in chain:
        for name in _CONFIG_CANDIDATES:
            candidate = directory / name
            if candidate.is_file():
                files.append(candidate)
    return sorted(files)


def _reject_config_filters(path: Path, data: bytes) -> None:
    """配置候选文件内容过滤面:addopts 携带筛选旗标或 conftest 定义
    收集修改 hook 即拒绝(full fail closed)。"""
    if path.name == "conftest.py":
        try:
            module = ast.parse(data)
        except SyntaxError as exc:
            raise SubstanceError(
                f"regression_config_unparseable:{path.name}") from exc
        for node in module.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name in _CONFT_HOOKS:
                raise SubstanceError(
                    "regression_config_filter_hook:" + node.name)
        return
    for raw in data.replace(b"\r", b"").splitlines():
        line = raw.strip().decode("utf-8", "replace")
        key = line.split("=", 1)[0].split(":", 1)[0].strip()
        if key not in ("addopts", "-addopts"):
            continue
        value = line.split("=", 1)[-1] if "=" in line else line
        for token in value.replace(":", " ").split():
            if token.split("=", 1)[0] in _ARGV_FORBIDDEN:
                raise SubstanceError(
                    "regression_config_addopts_filter:" + token)


def _verify_run_entry(record_path: Path, entry, label: str, *,
                      collect_only: bool, positionals_rule,
                      deploy_root: Path | None) -> bytes:
    """单个运行条目(command/interpreter/cwd/rc/起止/stdout/stderr/env)
    的原件绑定与过滤面核验;返回 stdout 原件字节。"""
    if not isinstance(entry, dict):
        raise SubstanceError(f"{label}_entry_invalid")
    _verify_run_argv(entry.get("command"), collect_only=collect_only,
                     positionals_rule=positionals_rule)
    for key in ("interpreter", "cwd", "started_utc", "finished_utc"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            raise SubstanceError(f"{label}_field_invalid:{key}")
    if type(entry.get("returncode")) is not int or entry["returncode"] != 0:
        raise SubstanceError(f"{label}_returncode_nonzero")
    if deploy_root is not None:
        if entry["cwd"] != str(deploy_root):
            raise SubstanceError(f"{label}_cwd_not_deploy_root")
        if Path(entry["interpreter"]).resolve() != \
                Path(sys.executable).resolve():
            raise SubstanceError(f"{label}_interpreter_mismatch")
    env = entry.get("env")
    if not isinstance(env, dict):
        raise SubstanceError(f"{label}_env_missing")
    for key in ("python_version", "pytest_version_output"):
        if not isinstance(env.get(key), str) or not env[key]:
            raise SubstanceError(f"{label}_env_field_invalid:{key}")
    for key in ("pytest_addopts", "pytest_plugins_env"):
        if env.get(key) not in (None, ""):
            raise SubstanceError(f"{label}_env_filtered:{key}")
    scan = env.get("config_scan")
    if not isinstance(scan, list) or not scan \
            or any(not (isinstance(row, dict)
                        and isinstance(row.get("path"), str) and row["path"]
                        and isinstance(row.get("sha256"), str))
                   for row in scan):
        raise SubstanceError(f"{label}_config_scan_invalid")
    stdout = _artifact_bytes(record_path, entry.get("stdout"),
                             label + "_stdout")
    _artifact_bytes(record_path, entry.get("stderr"), label + "_stderr")
    return stdout


def _verify_config_surface(deploy_root: Path, scan_rows) -> None:
    """部署面在场时:配置候选文件集合与字节必须与运行时扫描一致,
    且当前内容不含过滤入口(封口后配置被替换在此暴露)。"""
    found = _scan_config_files(Path(deploy_root),
                               _DEPLOYED_TEST_ROOT.rstrip("/"))
    want = {row["path"]: row["sha256"] for row in scan_rows}
    got = {str(p): _sha256_file(p) for p in found}
    if want != got:
        raise SubstanceError("regression_config_scan_mismatch")
    for path in found:
        _reject_config_filters(path, path.read_bytes())


def _verify_run_identity(entries: list, reference: dict, label: str) -> None:
    """collection_run 与全部 execution runs 必须共享同一执行身份
    (interpreter/cwd/python/pytest 版本+插件/配置扫描/PYTEST_* 环境)。
    收集与执行来自不同环境(借用运行)在此暴露。"""
    for entry in entries:
        for key in ("interpreter", "cwd"):
            if entry.get(key) != reference.get(key):
                raise SubstanceError(f"regression_run_identity_mismatch:{key}")
        for key in _ENV_IDENTITY_KEYS:
            if entry.get("env", {}).get(key) != \
                    reference.get("env", {}).get(key):
                raise SubstanceError(
                    f"regression_run_identity_mismatch:{key}")


def _verify_collection_run(record_path: Path, record: dict,
                           *, full: bool,
                           deploy_root: Path | None) -> list[str]:
    """collection_run(单进程)核验:期望全集 = stdout 原件重解析。"""
    block = record.get("collection_run")
    label = "regression_collection_run"
    if not isinstance(block, dict) \
            or not isinstance(block.get("runs"), list) \
            or len(block["runs"]) != 1:
        raise SubstanceError(f"{label}_runs_invalid")
    delta_targets = (None if full else
                     record.get("differential", {}).get("delta_targets"))
    if not full and not isinstance(delta_targets, list):
        raise SubstanceError("regression_run_delta_targets_invalid")
    stdout = _verify_run_entry(
        record_path, block["runs"][0], label, collect_only=True,
        positionals_rule=(["tests/route_c_stage2_6_1"] if full
                          else delta_targets),
        deploy_root=deploy_root)
    if deploy_root is not None:
        _verify_config_surface(
            deploy_root, block["runs"][0]["env"]["config_scan"])
    ids = parse_collection_stdout(
        stdout.decode("utf-8", errors="replace"))
    if not full:
        for node_id in ids:
            if not node_id.startswith(_DEPLOYED_TEST_ROOT):
                raise SubstanceError(
                    "regression_run_delta_target_outside_root:" + node_id)
    return ids


def _verify_execution_runs(record_path: Path, record: dict, *,
                           full: bool, junit_paths: list[Path],
                           shard_aggregates: list[dict],
                           deploy_root: Path | None) -> None:
    """execution runs 核验:每 run 绑定自身 junit(sha 已在外层核验)
    与 stdout 摘要;full 单 run 必须指向完整目录,sharded run 各自
    指向根内分片目标;全部 run 与 collection_run 同执行身份。"""
    block = record.get("execution")
    label = "regression_execution"
    runs = block.get("runs") if isinstance(block, dict) else None
    if not isinstance(runs, list) or not runs:
        raise SubstanceError(f"{label}_runs_invalid")
    if len(runs) != len(junit_paths) or len(runs) != len(shard_aggregates):
        raise SubstanceError(f"{label}_runs_junit_count_mismatch")
    delta_targets = (None if full else
                     record.get("differential", {}).get("delta_targets"))
    all_positionals: list[str] = []
    for index, entry in enumerate(runs):
        if full and len(runs) == 1:
            rule = [_DEPLOYED_TEST_ROOT.rstrip("/")]
        else:
            rule = "under_root"
        stdout = _verify_run_entry(
            record_path, entry, f"{label}_run{index}",
            collect_only=False, positionals_rule=rule,
            deploy_root=deploy_root)
        _verify_execution_summary(stdout, shard_aggregates[index])
        command = entry.get("command")
        positionals = [tok for tok in command[3:]
                       if not tok.startswith("-")]
        if rule == "under_root":
            for target in positionals:
                if not target.startswith(_DEPLOYED_TEST_ROOT) \
                        or target == _DEPLOYED_TEST_ROOT.rstrip("/"):
                    raise SubstanceError(
                        f"{label}_shard_target_invalid:{target}")
        all_positionals.extend(positionals)
    if not full:
        if sorted(all_positionals) != sorted(delta_targets):
            raise SubstanceError("regression_run_delta_target_mismatch")
    collection_ref = record.get("collection_run", {}).get("runs", [None])[0]
    _verify_run_identity(runs, collection_ref, label)


def _verify_execution_summary(stdout: bytes, aggregate: dict) -> None:
    """execution stdout 摘要行必须与该 run 的 junit 元素级聚合计数
    一致(借来的运行日志与 junit 错配在此暴露)。全 skipped 的分片
    stdout 只有 "N skipped in ..." 摘要,同样要求计数一致。"""
    text = stdout.decode("utf-8", errors="replace")
    found = _PASSED_SUMMARY_RE.findall(text)
    want = (aggregate["tests"] - aggregate["failures"]
            - aggregate["errors"] - aggregate["skipped"],
            aggregate["skipped"])
    if found:
        passed, skipped = (int(found[-1][0]), int(found[-1][1] or "0"))
    else:
        skipped_only = re.findall(r"(\d+) skipped[^\n]*\bin\b", text)
        if not skipped_only:
            raise SubstanceError(
                "regression_execution_stdout_summary_missing")
        passed, skipped = 0, int(skipped_only[-1])
    if (passed, skipped) != want:
        raise SubstanceError(
            "regression_execution_stdout_summary_mismatch:"
            + json.dumps({"stdout": [passed, skipped], "junit": want}))

def _verify_import_surface(record: dict, repo: Path, commit_a: str,
                           deploy_root: Path | None) -> None:
    """候选 src/rl_curriculum 全体成员 blob sha 必须与 record 一致;
    提供部署面时逐成员与部署 src 字节比对,部署侧多余模块必须恰为
    声明的 deploy_extra_modules(import 身份漂移即拒)。"""
    surface = record.get("import_surface")
    if not (isinstance(surface, dict)
            and isinstance(surface.get("members"), dict) and surface["members"]
            and isinstance(surface.get("deploy_extra_modules"), list)
            and all(isinstance(n, str) for n in surface["deploy_extra_modules"])):
        raise SubstanceError("regression_import_surface_missing")
    tree = _git_out(repo, "ls-tree", "-r", "--name-only", commit_a,
                    "--", _SRC_PREFIX.rstrip("/"))
    rels = [ln for ln in tree.decode("utf-8").splitlines()
            if ln.endswith(".py")]
    if not rels:
        raise SubstanceError("regression_import_surface_empty_tree")
    want = {}
    for rel in rels:
        blob = _git_out(repo, "show", f"{commit_a}:{rel}")
        want[rel] = hashlib.sha256(blob).hexdigest()
    members = {str(k): str(v) for k, v in surface["members"].items()}
    if members != want:
        raise SubstanceError(
            "regression_import_surface_candidate_mismatch:"
            + json.dumps({
                "missing": sorted(set(want) - set(members))[:3],
                "extra": sorted(set(members) - set(want))[:3]},
                ensure_ascii=False))
    if deploy_root is not None:
        deploy_dir = Path(deploy_root) / "src" / "rl_curriculum"
        if not deploy_dir.is_dir():
            raise SubstanceError("regression_import_surface_deploy_missing")
        deploy_names = {p.name for p in deploy_dir.glob("*.py")}
        for rel, sha in want.items():
            path = deploy_dir / rel.rsplit("/", 1)[-1]
            if not path.is_file() \
                    or _sha256_file(path) != sha:
                raise SubstanceError(
                    "regression_import_surface_deploy_mismatch:" + rel)
        extra = sorted(deploy_names
                       - {rel.rsplit("/", 1)[-1] for rel in want})
        if extra != sorted(surface["deploy_extra_modules"]):
            raise SubstanceError(
                "regression_import_surface_extra_drift:"
                + json.dumps(extra[:3]))


def _verify_conftest_hooks(repo: Path, commit_a: str, mapping: dict) -> None:
    """候选测试树内 conftest.py 不得定义收集修改 hook(候选侧权威;
    部署侧同字节由部署面核验承载)。"""
    for row in mapping.values():
        if row["source_path"].rsplit("/", 1)[-1] != "conftest.py":
            continue
        blob = _git_out(repo, "show", f"{commit_a}:{row['source_path']}")
        _reject_config_filters(Path(row["source_path"]), blob)


def verify_regression_evidence(record_path: Path, repo: Path,
                               commit_a: str, *,
                               deploy_root: Path | None = None) -> dict:
    """核验候选回归证据原件(v3;F1/F2/F3 + 收集原件/执行来源绑定)。

    junit 逐个重解析计数比对 + 多文件唯一性 + 独立完整收集原件
    重解析期望全集 + 两段运行身份/过滤面 + (差分)父证据同一
    完整核验;可选 deploy_root 时加部署面/配置面/import 面字节
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
    junit_paths: list[Path] = []
    shard_aggregates: list[dict] = []
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
        junit_paths.append(jp)
        shard_aggregates.append(
            {key: parsed[key] for key in aggregate})
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

    # ---- 完整集合(F1,v3):收集原件为期望全集权威,静态全集旁证
    mapping = candidate_test_map(repo, commit_a)
    _verify_test_files_manifest(record, mapping)
    static_ids = static_collection_ids(repo, commit_a)
    _verify_conftest_hooks(repo, commit_a, mapping)
    full = protocol == "full"
    collection = _verify_collection_run(record_path, record, full=full,
                                        deploy_root=deploy_root)
    bases = {_param_base(c) for c in collection}
    if full:
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
            raise SubstanceError(
                "regression_collection_file_coverage_mismatch")
    else:
        unknown = bases - static_ids
        if unknown:
            raise SubstanceError(
                "regression_collection_static_mismatch:"
                + json.dumps({"unknown": sorted(unknown)[:3]},
                             ensure_ascii=False))
        expected_files = {dp for dp, r in mapping.items() if r["is_test"]}
        represented = {c.split("::", 1)[0] for c in collection}
        if not represented <= expected_files:
            raise SubstanceError(
                "regression_collection_file_coverage_mismatch")
    if Counter(collection) != executed:
        raise SubstanceError("regression_collection_execution_mismatch")
    _verify_execution_runs(record_path, record, full=full,
                           junit_paths=junit_paths,
                           shard_aggregates=shard_aggregates,
                           deploy_root=deploy_root)
    _verify_import_surface(record, repo, commit_a, deploy_root)
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
