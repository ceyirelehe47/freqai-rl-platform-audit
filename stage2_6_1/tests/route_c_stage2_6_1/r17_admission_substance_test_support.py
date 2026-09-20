# -*- coding: utf-8 -*-
"""准入实质绑定(v2)测试支撑:沙箱 git 仓库 / junit 原件 / 回归证据
record / preregistration 构造器。全部经被测包的真实函数生成摘要,
不复制实现。

2026-09-20 完整性收敛升级:沙箱仓携带真实测试源树
(stage2_6_1/tests/route_c_stage2_6_1/,含 sandbox 通过测试与 7 个
历史 skip 桩模块);record 为 cur261-r17-candidate-regression-
evidence-v2(完整集合:候选树映射清单 + collection + execution)。
默认构造的 record 是"合法完整证据";负例经 *_override 注入失配。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from rl_curriculum.curriculum261_r17_admission_substance import (
    HISTORICAL_SKIP_IDS,
    REGRESSION_EVIDENCE_FORMAT,
    candidate_test_map,
    junit_nodeid,
    parse_junit,
    verify_preregistration_substance,
)

_SANDBOX_MODULE = "test_sandbox"
_SANDBOX_PASSING = 3


def _sandbox_module_source(n: int) -> str:
    lines = ["# sandbox test module (generated)", ""]
    for i in range(n):
        lines += [f"def test_case_{i}():", "    assert True", ""]
    return "\n".join(lines) + "\n"


def _skip_module_sources() -> dict[str, str]:
    """由 HISTORICAL_SKIP_IDS 权威表生成 7 个历史 skip 桩模块源
    (模块/类/方法名与表内 classname 逐字一致;不手抄防漂移)。"""
    modules: dict[str, dict[str | None, list[str]]] = {}
    for cid in HISTORICAL_SKIP_IDS:
        classname, name = cid.rsplit("::", 1)
        parts = classname.split(".")
        module, cls = parts[2], (parts[3] if len(parts) > 3 else None)
        modules.setdefault(module, {}).setdefault(cls, []).append(name)
    sources = {}
    for module, classes in sorted(modules.items()):
        lines = ["# sandbox historical-skip stub (generated)", ""]
        for cls, methods in classes.items():
            if cls is None:
                for m in methods:
                    lines += [f"def {m}():",
                              "    raise AssertionError(",
                              "        'sandbox historical skip stub')", ""]
            else:
                lines.append(f"class {cls}:")
                for m in methods:
                    lines += [f"    def {m}(self):",
                              "        raise AssertionError(",
                              "            'sandbox historical skip stub')"]
                lines.append("")
        sources[f"{module}.py"] = "\n".join(lines) + "\n"
    return sources


def write_sandbox_test_tree(repo: Path, *, sandbox_tests: int = _SANDBOX_PASSING) -> None:
    """把沙箱测试源树写入仓工作区(调用方负责 git add/commit)。"""
    test_dir = repo / "stage2_6_1" / "tests" / "route_c_stage2_6_1"
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / f"{_SANDBOX_MODULE}.py").write_text(
        _sandbox_module_source(sandbox_tests), encoding="utf-8")
    (test_dir / "conftest.py").write_text(
        "# sandbox conftest\n", encoding="utf-8")
    for leaf, source in _skip_module_sources().items():
        (test_dir / leaf).write_text(source, encoding="utf-8")


def git_repo_with_candidate(tmp: Path, *,
                            sandbox_tests: int = _SANDBOX_PASSING
                            ) -> tuple[Path, str, str]:
    """两提交沙箱仓(Commit A 需有 parent,满足签发器校验)。

    base 提交携带完整测试源树(sandbox 模块 + conftest + 历史
    skip 桩),cand 提交为候选。静态全集 = sandbox_tests 个通过
    测试 + 7 个历史 skip,与 write_junit(passed=sandbox_tests) 对应。
    """
    repo = tmp / "relrepo"
    repo.mkdir(parents=True)
    for args in (
        ("git", "init", "-q", "."),
        ("git", "config", "user.email", "sandbox@test.invalid"),
        ("git", "config", "user.name", "sandbox"),
    ):
        subprocess.run(args, cwd=str(repo), check=True)
    (repo / "base.txt").write_text("base\n")
    write_sandbox_test_tree(repo, sandbox_tests=sandbox_tests)
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=str(repo),
                   check=True)
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True).stdout.strip()
    (repo / "cand.txt").write_text("cand\n")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-qm", "cand"], cwd=str(repo),
                   check=True)
    commit_a = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        capture_output=True, text=True, check=True).stdout.strip()
    return repo, commit_a, parent


def sync_deploy_surface(repo: Path, commit_a: str, deploy_root: Path) -> Path:
    """把候选树测试面按映射同步到沙箱部署根(字节=CR 规范化 blob)。
    只写沙箱,永不触真实部署面。"""
    mapping = candidate_test_map(repo, commit_a)
    target = Path(deploy_root) / "tests" / "route_c_stage2_6_1"
    target.mkdir(parents=True, exist_ok=True)
    for row in mapping.values():
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit_a}:{row['source_path']}"],
            capture_output=True, check=True).stdout
        (target / Path(row["deploy_path"]).name).write_bytes(
            blob.replace(b"\r", b""))
    return target


def write_junit(path: Path, passed: int,
                skipped_ids=HISTORICAL_SKIP_IDS) -> Path:
    """生成与 parse_junit 兼容的最小 junit 原件(计数自洽)。

    通过用例 = tests.route_c_stage2_6_1.test_sandbox 模块的
    test_case_0..N-1(须存在于沙箱树);skip = 历史允许表 ID。
    """
    skipped_ids = list(skipped_ids)
    suites = ET.Element("testsuites")
    s = ET.SubElement(
        suites, "testsuite", {
            "name": "sandbox",
            "tests": str(passed + len(skipped_ids)),
            "failures": "0", "errors": "0",
            "skipped": str(len(skipped_ids))})
    for i in range(passed):
        ET.SubElement(s, "testcase", {
            "classname": f"tests.route_c_stage2_6_1.{_SANDBOX_MODULE}",
            "name": f"test_case_{i}"})
    for cid in skipped_ids:
        cls, name = cid.rsplit("::", 1)
        tc = ET.SubElement(s, "testcase", {
            "classname": cls, "name": name})
        ET.SubElement(tc, "skipped")
    ET.indent(suites)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(suites).write(path, encoding="utf-8",
                                 xml_declaration=True)
    return path


def write_evidence_record(record_path: Path, repo: Path, commit_a: str,
                          junit_paths: list[Path], *,
                          protocol: str = "full",
                          counts_override: dict | None = None,
                          skip_ids_override=None,
                          historical_skip_ids=None,
                          collection_override=None,
                          test_files_override=None,
                          execution_override=None,
                          differential: dict | None = None,
                          drop_fields: tuple = ()) -> Path:
    """构造 cur261-r17-candidate-regression-evidence-v2 record。

    计数/跳过集合由真实 parse_junit 从生成的 junit 原件重算;
    test_files 清单由真实 candidate_test_map 从候选树重算;
    collection 默认 = junit 实际执行 node-ID(合法完整证据下与
    静态全集一致);*_override/drop_fields 供负例注入失配。
    """
    aggregate = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skipped_ids: list[str] = []
    executed: list[str] = []
    entries = []
    for jp in junit_paths:
        parsed = parse_junit(jp)
        for key in aggregate:
            aggregate[key] += parsed[key]
        skipped_ids.extend(parsed["skipped_ids"])
        for cid in parsed["case_ids"]:
            classname, _, name = cid.partition("::")
            executed.append(junit_nodeid(classname, name))
        entries.append({
            "path": str(jp),
            "sha256": hashlib.sha256(
                jp.read_bytes()).hexdigest()})
    counts = counts_override or aggregate
    skip_ids = (historical_skip_ids
                if historical_skip_ids is not None else sorted(
                    set(skipped_ids)))
    if skip_ids_override is not None:
        skip_ids = skip_ids_override
    mapping = candidate_test_map(repo, commit_a)
    if test_files_override is not None:
        test_files = test_files_override
    else:
        test_files = [
            {"source_path": row["source_path"],
             "deploy_path": row["deploy_path"],
             "deploy_sha256": row["deploy_sha256"],
             "deploy_size": row["deploy_size"],
             "is_test": row["is_test"]}
            for row in mapping.values()]
    if collection_override is not None:
        collection = collection_override
    else:
        collection = sorted(executed)
    if execution_override is not None:
        execution = execution_override
    else:
        execution = {
            "command": ["pytest", "tests/route_c_stage2_6_1", "-q",
                        "--junitxml=junit.xml"],
            "interpreter": sys.executable,
            "cwd": "/sandbox",
            "returncode": 0,
        }
    record = {
        "format": REGRESSION_EVIDENCE_FORMAT,
        "scope": "formal",
        "protocol": protocol,
        "commit_a_sha": commit_a,
        "junit": entries,
        "counts": counts,
        "historical_skip_ids": skip_ids,
        "test_files": test_files,
        "collection": collection,
        "execution": execution,
        "bound_utc": "2026-09-20T00:00:00Z",
        "notes": "test-harness sandbox evidence",
    }
    if differential is not None:
        record["differential"] = differential
    for key in drop_fields:
        record.pop(key, None)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return record_path


def write_preregistration(path: Path, repo: Path, commit_a: str,
                          evidence_path: Path, *,
                          plan_digest: str | None = None,
                          admission_id: str = "sandbox-aid-0001",
                          iteration: str = "r18",
                          drop_keys: tuple = ()) -> Path:
    """构造带实质绑定字段的 preregistration(plan_digest 默认实算)。"""
    if plan_digest is None:
        plan_digest = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", commit_a + "^{tree}"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
    prereg = {
        "admission_id": admission_id,
        "iteration": iteration,
        "plan_digest": plan_digest,
        "plan_digest_method": (
            "git tree digest of Commit A "
            "(git rev-parse <sha>^{tree})"),
        "regression_evidence": str(evidence_path),
        "authorization": (
            "test-harness:沙箱实质绑定验证,不触碰正式部署面"),
        "commit_a_sha": commit_a,
    }
    for key in drop_keys:
        prereg.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prereg, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def substance_fields(repo: Path, commit_a: str,
                     prereg_path: Path) -> dict:
    """经真实签发端验证路径生成 admission 的 substance 两字段。"""
    prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    substance = verify_preregistration_substance(
        repo, commit_a, prereg)
    from rl_curriculum.curriculum261_r17_admission_substance import (
        substance_digest)
    return {"substance": substance,
            "substance_digest": substance_digest(substance)}
