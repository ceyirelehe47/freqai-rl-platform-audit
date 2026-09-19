# -*- coding: utf-8 -*-
"""R17 准入实质绑定(§4.2 收口)的行为级单元测试。

覆盖:
- 签发端 verify_preregistration_substance:plan digest 实算比对
  (声明 ≠ Commit A tree digest ⇒ 拒)、回归证据 junit 重解析计数
  比对、0 failures/errors、skip 恰为历史允许表、差分协议
  (parent 祖先 + 全量绿绑定 + src 零变更 + 未声明文件拒);
- 消费端 verify_admission_substance:digest 篡改拒、证据原件替换拒;
- HISTORICAL_SKIP_IDS 与 runner/r17_v2_c13_admission_guard.py 权威
  副本零漂移(两表漂移在此暴露);
- 签发器(v2)对无实质绑定/错误 plan_digest 的 preregistration
  拒绝且零文件副作用。
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r17_admission_substance import (
    HISTORICAL_SKIP_IDS,
    SubstanceError,
    verify_admission_substance,
    verify_preregistration_substance,
    verify_regression_evidence)
from r17_admission_substance_test_support import (
    git_repo_with_candidate,
    substance_fields,
    write_evidence_record,
    write_junit,
    write_preregistration)

_TESTS_DIR = Path(__file__).resolve().parent
_REPO_RUNNER = _TESTS_DIR.parents[1] / "runner" / (
    "r17_v2_c13_admission_guard.py")
_DEPLOY_RUNNER = _TESTS_DIR.parents[1] / "stage2_6_1" / "runner" / (
    "r17_v2_c13_admission_guard.py")
_EXEC_RUNNER = _TESTS_DIR.parents[1] / "stage2_6_1_runner" / (
    "r17_v2_c13_admission_guard.py")
_ISSUER_CANDIDATES = (
    _TESTS_DIR.parents[1] / "runner" / "r17_admission_issue.py",
    _TESTS_DIR.parents[1] / "stage2_6_1" / "runner" / (
        "r17_admission_issue.py"),
    _TESTS_DIR.parents[1] / "stage2_6_1_runner" / (
        "r17_admission_issue.py"),
)


def _guard_module():
    for path in (_REPO_RUNNER, _DEPLOY_RUNNER, _EXEC_RUNNER):
        if path.is_file():
            spec = importlib.util.spec_from_file_location(
                "r17_v2_c13_admission_guard", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    pytest.skip("runner/r17_v2_c13_admission_guard.py 不可达")


def _issuer() -> Path:
    for path in _ISSUER_CANDIDATES:
        if path.is_file():
            return path
    pytest.skip("runner/r17_admission_issue.py 不可达")


@pytest.fixture()
def sandbox(tmp_path):
    repo, commit_a, parent = git_repo_with_candidate(tmp_path)
    junit = write_junit(tmp_path / "ev" / "junit.xml", passed=3)
    evidence = write_evidence_record(
        tmp_path / "ev" / "regression_evidence.json", repo, commit_a,
        [junit])
    prereg = write_preregistration(
        tmp_path / "prereg.json", repo, commit_a, evidence)
    return tmp_path, repo, commit_a, parent, junit, evidence, prereg


class TestPreregistrationSubstance:
    def test_happy_path_full_protocol(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        doc = json.loads(prereg.read_text(encoding="utf-8"))
        substance = verify_preregistration_substance(
            repo, commit_a, doc)
        assert substance["plan_digest_recomputed"] == doc["plan_digest"]
        assert substance["regression_evidence"]["counts"]["failures"] == 0
        assert substance["regression_evidence"]["counts"]["skipped"] == 7
        assert len(HISTORICAL_SKIP_IDS) == 7

    def test_plan_digest_mismatch_refused(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        bad = write_preregistration(
            tmp / "prereg_bad.json", repo, commit_a, _e,
            plan_digest="0" * 40)
        doc = json.loads(bad.read_text(encoding="utf-8"))
        with pytest.raises(SubstanceError, match="plan_digest_mismatch"):
            verify_preregistration_substance(repo, commit_a, doc)

    def test_v1_dummy_digest_method_refused(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        doc = json.loads(prereg.read_text(encoding="utf-8"))
        del doc["plan_digest_method"]
        with pytest.raises(SubstanceError,
                           match="plan_digest_method_unsupported"):
            verify_preregistration_substance(repo, commit_a, doc)

    def test_missing_evidence_refused(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        doc = json.loads(prereg.read_text(encoding="utf-8"))
        doc.pop("regression_evidence")
        with pytest.raises(SubstanceError,
                           match="regression_evidence_not_preregistered"):
            verify_preregistration_substance(repo, commit_a, doc)

    def test_count_mismatch_refused(self, sandbox):
        tmp, repo, commit_a, _p, junit, evidence, prereg = sandbox
        write_evidence_record(
            tmp / "ev2" / "rec.json", repo, commit_a, [junit],
            counts_override={"tests": 99, "failures": 0, "errors": 0,
                             "skipped": 7})
        with pytest.raises(SubstanceError,
                           match="regression_count_mismatch:tests"):
            verify_regression_evidence(
                tmp / "ev2" / "rec.json", repo, commit_a)

    def test_extra_skip_outside_allowed_table_refused(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        junit = write_junit(
            tmp / "ev3" / "junit.xml", passed=1,
            skipped_ids=list(HISTORICAL_SKIP_IDS) + [
                "tests.x.TestY::test_outside"])
        write_evidence_record(
            tmp / "ev3" / "rec.json", repo, commit_a, [junit],
            skip_ids_override=list(HISTORICAL_SKIP_IDS) + [
                "tests.x.TestY::test_outside"])
        with pytest.raises(SubstanceError,
                           match="regression_skip_ids_outside_"
                                 "allowed_table"):
            verify_regression_evidence(
                tmp / "ev3" / "rec.json", repo, commit_a)

    def test_junit_bytes_swapped_refused(self, sandbox):
        tmp, repo, commit_a, _p, junit, evidence, prereg = sandbox
        write_junit(junit, passed=4)  # 同名覆写 ⇒ sha 漂移
        with pytest.raises(SubstanceError,
                           match="regression_junit_sha_mismatch"):
            verify_regression_evidence(evidence, repo, commit_a)

    def test_differential_src_change_refused(self, sandbox):
        tmp, repo, commit_a, parent, junit, evidence, prereg = sandbox
        # parent 之上的候选提交再改 src(违反差分协议边界)
        src = repo / "stage2_6_1" / "src" / "rl_curriculum" / "m.py"
        src.parent.mkdir(parents=True)
        src.write_text("x = 1\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"],
                       check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "src"],
                       check=True)
        new_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        parent_ev = write_evidence_record(
            tmp / "evp" / "rec.json", repo, parent, [
                write_junit(tmp / "evp" / "junit.xml", passed=5)])
        rec = write_evidence_record(
            tmp / "evd" / "rec.json", repo, new_head, [
                write_junit(tmp / "evd" / "junit.xml", passed=5)],
            protocol="differential")
        doc = json.loads(rec.read_text(encoding="utf-8"))
        import hashlib
        doc["differential"] = {
            "parent_commit": parent,
            "parent_evidence": {
                "path": str(parent_ev),
                "sha256": hashlib.sha256(
                    parent_ev.read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [],
                            "runner_files": ["cand.txt"],
                            "other_files": []}}
        rec.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        with pytest.raises(SubstanceError,
                           match="differential_src_changed"):
            verify_regression_evidence(rec, repo, new_head)


class TestAdmissionSubstanceConsumer:
    def test_valid_then_tampered_then_replaced(self, sandbox):
        tmp, repo, commit_a, _p, junit, evidence, prereg = sandbox
        fields = substance_fields(repo, commit_a, prereg)
        admission = {
            "format": "cur261-r17-formal-admission-v2",
            "commit_a_sha": commit_a,
            "plan_digest": fields["substance"][
                "plan_digest_recomputed"],
            **fields}
        assert verify_admission_substance(admission, repo) == (
            True, "ok")
        tampered = json.loads(json.dumps(admission))
        swapped = json.loads(json.dumps(admission))
        tampered["substance"]["plan_digest_claimed"] = "0" * 40
        assert verify_admission_substance(tampered, repo) == (
            False, "admission_substance_digest_mismatch")
        write_junit(junit, passed=9)  # 证据原件被替换
        ok, reason = verify_admission_substance(swapped, repo)
        assert ok is False
        assert "regression_junit_sha_mismatch" in reason

    def test_v1_without_substance_refused(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        assert verify_admission_substance(
            {"commit_a_sha": commit_a}, repo) == (
            False, "admission_substance_missing")


class TestSkipTableNoDrift:
    def test_matches_runner_guard_table(self):
        guard = _guard_module()
        assert frozenset(guard.HISTORICAL_SKIP_IDS) == \
            frozenset(HISTORICAL_SKIP_IDS)


class TestIssuerV2RequiresSubstance:
    """签发器(真实子进程):无实质绑定/错 plan_digest ⇒ 拒 + 零副作用。"""

    def test_refuses_and_zero_side_effects(self, sandbox):
        tmp, repo, commit_a, _p, _j, _e, prereg = sandbox
        issuer = _issuer()
        real_src = None
        for cand in (_TESTS_DIR.parents[1] / "src",
                     _TESTS_DIR.parents[2] / "src"):
            if (cand / "rl_curriculum" / (
                    "curriculum261_r17_admission_substance.py")
                    ).is_file():
                real_src = cand
                break
        if real_src is None:
            pytest.skip("发布仓 src 包不可达")
        # 签发器要求发布仓内存在实质绑定模块(同源实现)
        (repo / "stage2_6_1").mkdir(exist_ok=True)
        (repo / "stage2_6_1" / "src").symlink_to(
            real_src, target_is_directory=True)
        state = (tmp / "deploy" / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True)
        # 声明错的 plan_digest(v1 时代的占位口径)
        bad = write_preregistration(
            tmp / "prereg_bad.json", repo, commit_a, _e,
            plan_digest="0" * 40)
        proc = subprocess.run(
            [sys.executable, str(issuer), "--repo", str(repo),
             "--deploy-root", str(tmp / "deploy"),
             "--state-root", str(state), "--commit-a", commit_a,
             "--preregistration", str(bad)],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert "plan_digest_mismatch" in proc.stdout + proc.stderr
        assert not (tmp / "deploy" / ".r17_formal_admission.json"
                    ).exists()
        assert not (tmp / "deploy" / "r17_admission_issued.jsonl"
                    ).exists()
