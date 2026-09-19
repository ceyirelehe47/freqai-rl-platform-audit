# -*- coding: utf-8 -*-
"""准入实质绑定(v2)测试支撑:沙箱 git 仓库 / junit 原件 / 回归证据
record / preregistration 构造器。全部经被测包的真实函数生成摘要,
不复制实现。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from rl_curriculum.curriculum261_r17_admission_substance import (
    HISTORICAL_SKIP_IDS,
    REGRESSION_EVIDENCE_FORMAT,
    parse_junit,
    verify_preregistration_substance,
)


def git_repo_with_candidate(tmp: Path) -> tuple[Path, str, str]:
    """两提交沙箱仓(Commit A 需有 parent,满足签发器校验)。

    返回 (repo, commit_a, parent)。
    """
    repo = tmp / "relrepo"
    repo.mkdir(parents=True)
    for args in (
            ["git", "init", "-q", "."],
            ["git", "config", "user.email", "t@example.invalid"],
            ["git", "config", "user.name", "t"],
    ):
        subprocess.run(args, cwd=str(repo), check=True)
    (repo / "base.txt").write_text("base\n")
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


def write_junit(path: Path, passed: int,
                skipped_ids=HISTORICAL_SKIP_IDS) -> Path:
    """生成与 parse_junit 兼容的最小 junit 原件(计数自洽)。"""
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
            "classname": "tests.route_c_stage2_6_1.test_sandbox",
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
                          historical_skip_ids=None) -> Path:
    """构造 cur261-r17-candidate-regression-evidence-v1 record。

    默认计数/跳过集合由真实 parse_junit 从生成的 junit 原件重算,
    保证自洽;*_override 参数供负例测试注入失配。
    """
    aggregate = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    skipped_ids: list[str] = []
    entries = []
    for jp in junit_paths:
        parsed = parse_junit(jp)
        for key in aggregate:
            aggregate[key] += parsed[key]
        skipped_ids.extend(parsed["skipped_ids"])
        import hashlib
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
    record = {
        "format": REGRESSION_EVIDENCE_FORMAT,
        "scope": "formal",
        "protocol": protocol,
        "commit_a_sha": commit_a,
        "junit": entries,
        "counts": counts,
        "historical_skip_ids": skip_ids,
        "bound_utc": "2026-09-20T00:00:00Z",
        "notes": "test-harness sandbox evidence",
    }
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
