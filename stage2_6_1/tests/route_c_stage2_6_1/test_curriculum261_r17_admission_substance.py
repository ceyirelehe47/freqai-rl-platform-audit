# -*- coding: utf-8 -*-
"""R17 准入实质绑定(§4.2 收口)的行为级单元测试。

覆盖:
- 签发端 verify_preregistration_substance:plan digest 实算比对
  (声明 ≠ Commit A tree digest ⇒ 拒)、回归证据 junit 重解析计数
  比对、0 failures/errors、skip 恰为历史允许表、差分协议
  (parent 祖先 + 全量绿绑定 + src 零变更 + 未声明文件拒);
- 完整性收敛(2026-09-20,v2 record):F1 完整集合(候选树静态
  全集/清单/收集/执行溯源/部署面)、F2 差分父证据递归同规则、
  F3 多文件唯一性与合法分片;审查 probe 三负例迁移至真实层;
  签发/消费沙箱端到端(真实子进程);
- HISTORICAL_SKIP_IDS 与 runner 权威副本零漂移;
  candidate_test_map/junit_nodeid 与 guard 同源零漂移。
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
    REGRESSION_EVIDENCE_FORMAT,
    SubstanceError,
    candidate_test_map,
    junit_nodeid,
    static_collection_ids,
    verify_admission_substance,
    verify_deployment_surface,
    verify_preregistration_substance,
    verify_regression_evidence)
from r17_admission_substance_test_support import (
    git_repo_with_candidate,
    substance_fields,
    sync_deploy_surface,
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
                "tests.route_c_stage2_6_1.test_sandbox::test_outside"])
        write_evidence_record(
            tmp / "ev3" / "rec.json", repo, commit_a, [junit],
            skip_ids_override=list(HISTORICAL_SKIP_IDS) + [
                "tests.route_c_stage2_6_1.test_sandbox::test_outside"])
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

# ------------- parse_junit 元素级核验(2026-09-20 加固) -------------

def _write_raw_junit(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestParseJunitElementLevel:
    """计数必须来自 testcase 元素并与 suite 属性交叉核对。"""

    def test_attribute_green_but_failure_element_rejected(self,
                                                          tmp_path):
        """负例:汇总属性 failures=0 但某 testcase 含 <failure>。"""
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit
        jp = _write_raw_junit(tmp_path / "forged.xml", (
            '<?xml version="1.0"?>'
            '<testsuites><testsuite name="s" tests="2" failures="0"'
            ' errors="0" skipped="0">'
            '<testcase classname="t" name="a"/>'
            '<testcase classname="t" name="b"><failure type="AssertionError"/>'
            "</testcase>"
            "</testsuite></testsuites>"))
        with pytest.raises(SubstanceError, match=(
                "element_attribute_mismatch:failures")):
            parse_junit(jp)

    def test_error_element_rejected(self, tmp_path):
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit
        jp = _write_raw_junit(tmp_path / "forged_err.xml", (
            '<?xml version="1.0"?>'
            '<testsuites><testsuite name="s" tests="1" failures="0"'
            ' errors="0" skipped="0">'
            '<testcase classname="t" name="a"><error/></testcase>'
            "</testsuite></testsuites>"))
        with pytest.raises(SubstanceError, match=(
                "element_attribute_mismatch:errors")):
            parse_junit(jp)

    def test_skipped_attribute_inflation_rejected(self, tmp_path):
        """负例:skipped 属性虚报(声明 1,元素 0)。"""
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit
        jp = _write_raw_junit(tmp_path / "forged_skip.xml", (
            '<?xml version="1.0"?>'
            '<testsuites><testsuite name="s" tests="1" failures="0"'
            ' errors="0" skipped="1">'
            '<testcase classname="t" name="a"/>'
            "</testsuite></testsuites>"))
        with pytest.raises(SubstanceError, match=(
                "element_attribute_mismatch:skipped")):
            parse_junit(jp)

    def test_duplicate_testcase_id_rejected(self, tmp_path):
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit
        jp = _write_raw_junit(tmp_path / "dup.xml", (
            '<?xml version="1.0"?>'
            '<testsuites><testsuite name="s" tests="2" failures="0"'
            ' errors="0" skipped="0">'
            '<testcase classname="t" name="a"/>'
            '<testcase classname="t" name="a"/>'
            "</testsuite></testsuites>"))
        with pytest.raises(SubstanceError, match=(
                "regression_junit_duplicate_testcase")):
            parse_junit(jp)

    def test_malformed_testcase_rejected(self, tmp_path):
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit
        jp = _write_raw_junit(tmp_path / "mal.xml", (
            '<?xml version="1.0"?>'
            '<testsuites><testsuite name="s" tests="1" failures="0"'
            ' errors="0" skipped="0">'
            '<testcase classname="t"/>'
            "</testsuite></testsuites>"))
        with pytest.raises(SubstanceError, match=(
                "regression_junit_testcase_malformed")):
            parse_junit(jp)

    def test_normal_green_junit_compatible(self, tmp_path):
        """兼容验证:正常自洽 junit 计数正确、跳过 ID 全量提取。"""
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit
        jp = write_junit(tmp_path / "ok.xml", passed=3)
        parsed = parse_junit(jp)
        assert parsed["tests"] == 3 + len(HISTORICAL_SKIP_IDS)
        assert parsed["failures"] == 0 and parsed["errors"] == 0
        assert parsed["skipped"] == len(HISTORICAL_SKIP_IDS)
        assert set(parsed["skipped_ids"]) == set(HISTORICAL_SKIP_IDS)

    def test_forged_junit_rejected_end_to_end(self, sandbox, tmp_path):
        """端到端:record 声明全绿且属性自洽文案,但原件含 failure
        元素 => verify_regression_evidence 必须拒绝。"""
        from rl_curriculum.curriculum261_r17_admission_substance \
            import parse_junit, _sha256_file
        jp = _write_raw_junit(tmp_path / "ev_forge" / "j.xml", (
            '<?xml version="1.0"?>'
            '<testsuites><testsuite name="s" tests="1" failures="0"'
            ' errors="0" skipped="0">'
            '<testcase classname="t" name="a"><failure/></testcase>'
            "</testsuite></testsuites>"))
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        import hashlib
        import json as _json
        sha = hashlib.sha256(jp.read_bytes()).hexdigest()
        rec = tmp / "ev_forge" / "rec.json"
        rec.write_text(_json.dumps({
            "format": REGRESSION_EVIDENCE_FORMAT,
            "commit_a_sha": commit_a, "scope": "formal",
            "junit": [{"path": jp.name, "sha256": sha}],
            "counts": {"tests": 1, "failures": 0, "errors": 0,
                       "skipped": 0},
            "historical_skip_ids": [], "protocol": "full",
        }), encoding="utf-8")
        with pytest.raises(SubstanceError, match=(
                "element_attribute_mismatch:failures")):
            verify_regression_evidence(rec, repo, commit_a)


# ------------- 回归证据完整性(F1/F2/F3,2026-09-20 收敛轮) -------------

def _read_doc(rec: Path) -> dict:
    return json.loads(Path(rec).read_text(encoding="utf-8"))


def _write_doc(rec: Path, doc: dict) -> Path:
    Path(rec).write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return rec


class TestFullSetCompleteness:
    """F1:protocol=full 的证据必须覆盖候选 Git 测试源树全集。

    审查负例迁移(RouteC_Review_b2c345e_Evidence probe):
    25 测试树 + 1 无关通过 + 7 历史 skip 标 full 曾被接受。"""

    def test_probe_f1_incomplete_set_mislabeled_full_refused(self,
                                                             sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        junit = write_junit(tmp / "evf1" / "junit.xml", passed=1)
        rec = write_evidence_record(
            tmp / "evf1" / "rec.json", repo, commit_a, [junit])
        with pytest.raises(SubstanceError,
                           match="regression_collection_static_mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_v1_format_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        rec = write_evidence_record(
            tmp / "evv1" / "rec.json", repo, commit_a, [sandbox[4]])
        doc = _read_doc(rec)
        doc["format"] = "cur261-r17-candidate-regression-evidence-v1"
        _write_doc(rec, doc)
        with pytest.raises(SubstanceError,
                           match="regression_evidence_format_mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_missing_v2_fields_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        for field, word in (("collection", "regression_collection_missing"),
                            ("test_files", "regression_test_files_missing"),
                            ("execution",
                             "regression_execution_provenance_invalid")):
            rec = write_evidence_record(
                tmp / f"evdrop_{field}" / "rec.json", repo, commit_a,
                [sandbox[4]], drop_fields=(field,))
            with pytest.raises(SubstanceError, match=word):
                verify_regression_evidence(rec, repo, commit_a)

    def test_count_match_id_substitution_refused(self, sandbox):
        """计数一致但 testcase ID 被替换:multiset 失配必拒。"""
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        # junit 内 test_case_1 被改名为 test_case_77(计数不变)
        raw = (tmp / "evsub" / "junit.xml")
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(
            sandbox[4].read_bytes().replace(
                b'name="test_case_1"', b'name="test_case_77"'))
        static = static_collection_ids(repo, commit_a)
        rec = write_evidence_record(
            tmp / "evsub" / "rec.json", repo, commit_a, [raw],
            collection_override=sorted(static))
        with pytest.raises(SubstanceError,
                           match="regression_collection_execution_"
                                 "mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_missing_root_level_test_refused(self, sandbox, tmp_path):
        """新增根目录级测试文件未覆盖:静态全集增长必拒。"""
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        old_static = static_collection_ids(repo, commit_a)
        root_test = repo / "stage2_6_1" / "tests" / "test_root_extra.py"
        root_test.parent.mkdir(parents=True, exist_ok=True)
        root_test.write_text(
            "def test_root_a():\n    assert True\n\n\n"
            "def test_root_b():\n    assert True\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "root"],
                       check=True)
        new_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        # record 的清单/收集仍按旧全集构造(caller 自选子集)
        old_mapping = candidate_test_map(repo, commit_a)
        junit = write_junit(tmp / "evroot" / "junit.xml", passed=3)
        rec = write_evidence_record(
            tmp / "evroot" / "rec.json", repo, new_head, [junit],
            test_files_override=[
                {"source_path": r["source_path"],
                 "deploy_path": r["deploy_path"],
                 "deploy_sha256": r["deploy_sha256"],
                 "deploy_size": r["deploy_size"],
                 "is_test": r["is_test"]}
                for r in old_mapping.values()],
            collection_override=sorted(old_static))
        with pytest.raises(SubstanceError,
                           match="regression_test_files_mismatch|"
                                 "regression_collection_static_mismatch"):
            verify_regression_evidence(rec, repo, new_head)
        _ = tmp_path

    def test_manifest_row_tampered_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        mapping = candidate_test_map(repo, commit_a)
        rows = [{"source_path": r["source_path"],
                 "deploy_path": r["deploy_path"],
                 "deploy_sha256": r["deploy_sha256"],
                 "deploy_size": r["deploy_size"],
                 "is_test": r["is_test"]}
                for r in mapping.values()]
        rows[0]["deploy_sha256"] = "0" * 64
        rec = write_evidence_record(
            tmp / "evman" / "rec.json", repo, commit_a, [sandbox[4]],
            test_files_override=rows)
        with pytest.raises(SubstanceError,
                           match="regression_test_files_mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_new_module_test_skipped_refused(self, sandbox):
        """新增关键测试被 skip 后算通过:skip 集合超出允许表必拒。"""
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        new_mod = (repo / "stage2_6_1" / "tests" /
                   "route_c_stage2_6_1" / "test_new_critical.py")
        new_mod.write_text(
            "def test_new_guard():\n    assert True\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "new"],
                       check=True)
        new_head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        extra_skip = ("tests.route_c_stage2_6_1.test_new_critical"
                      "::test_new_guard")
        junit = write_junit(
            tmp / "evskip" / "junit.xml", passed=3,
            skipped_ids=list(HISTORICAL_SKIP_IDS) + [extra_skip])
        rec = write_evidence_record(
            tmp / "evskip" / "rec.json", repo, new_head, [junit],
            skip_ids_override=list(HISTORICAL_SKIP_IDS) + [extra_skip])
        with pytest.raises(SubstanceError,
                           match="regression_skip_ids_outside_allowed_"
                                 "table"):
            verify_regression_evidence(rec, repo, new_head)

    def test_valid_complete_evidence_accepted(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        rec = write_evidence_record(
            tmp / "evok" / "rec.json", repo, commit_a, [sandbox[4]])
        out = verify_regression_evidence(rec, repo, commit_a)
        assert out["aggregate"]["tests"] == 3 + len(HISTORICAL_SKIP_IDS)
        assert out["aggregate"]["skipped"] == len(HISTORICAL_SKIP_IDS)
        assert out["collection_tests"] == out["static_tests"]


class TestMultiFileUniqueness:
    """F3:同一 junit(路径别名/同内容)与跨文件 testcase 重叠
    不得重复累计;合法分片=不重叠并集=全集。"""

    def test_probe_f3_same_junit_twice_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        junit = sandbox[4]
        rec = write_evidence_record(
            tmp / "evdup" / "rec.json", repo, commit_a, [junit, junit],
            counts_override={"tests": 20, "failures": 0, "errors": 0,
                             "skipped": 14})
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_path"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_alias_path_reference_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        rec = write_evidence_record(
            tmp / "evalias" / "rec.json", repo, commit_a, [sandbox[4]])
        doc = _read_doc(rec)
        doc["junit"].append({
            "path": "../ev/" + sandbox[4].name,
            "sha256": doc["junit"][0]["sha256"]})
        doc["counts"] = {"tests": 20, "failures": 0, "errors": 0,
                         "skipped": 14}
        _write_doc(rec, doc)
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_path"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_identical_bytes_second_file_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        import hashlib as _h
        copy = tmp / "evcopy" / "junit_copy.xml"
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(sandbox[4].read_bytes())
        rec = write_evidence_record(
            tmp / "evcopy" / "rec.json", repo, commit_a,
            [sandbox[4], copy])
        doc = _read_doc(rec)
        assert doc["junit"][1]["sha256"] == _h.sha256(
            copy.read_bytes()).hexdigest()
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_content"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_cross_file_testcase_overlap_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        skip_list = sorted(HISTORICAL_SKIP_IDS)
        shard_a = write_junit(tmp / "evsh" / "a.xml", passed=3,
                              skipped_ids=skip_list[:4])
        shard_b = write_junit(tmp / "evsh" / "b.xml", passed=1,
                              skipped_ids=skip_list[4:])
        rec = write_evidence_record(
            tmp / "evsh" / "rec.json", repo, commit_a,
            [shard_a, shard_b])
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_testcase_"
                                 "across_files"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_legal_shards_accepted(self, sandbox):
        skip_list = sorted(HISTORICAL_SKIP_IDS)
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        shard_a = write_junit(tmp / "evls" / "a.xml", passed=3,
                              skipped_ids=skip_list[:4])
        shard_b = write_junit(tmp / "evls" / "b.xml", passed=0,
                              skipped_ids=skip_list[4:])
        rec = write_evidence_record(
            tmp / "evls" / "rec.json", repo, commit_a,
            [shard_a, shard_b])
        out = verify_regression_evidence(rec, repo, commit_a)
        assert out["aggregate"]["tests"] == 3 + len(HISTORICAL_SKIP_IDS)
        assert out["collection_tests"] == out["static_tests"]


class TestDifferentialParentChain:
    """F2:父证据必须递归通过同一完整核验(部署面除外)。"""

    def test_probe_f2_invalid_parent_refused(self, sandbox):
        """审查负例迁移:父 record 声明 full+失败计数、无 junit,
        形状满足旧实现 ⇒ 现必须拒绝。"""
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        parent = sandbox[3]
        import hashlib as _h
        parent_rec = tmp / "evp" / "parent.json"
        parent_rec.parent.mkdir(parents=True, exist_ok=True)
        parent_rec.write_text(json.dumps({
            "protocol": "full", "commit_a_sha": parent,
            "counts": {"tests": 1, "failures": 1, "errors": 0,
                       "skipped": 0}}), encoding="utf-8")
        differential = {
            "parent_commit": parent,
            "parent_evidence": {
                "path": str(parent_rec),
                "sha256": _h.sha256(
                    parent_rec.read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [], "runner_files": [],
                            "other_files": ["cand.txt"]}}
        rec = write_evidence_record(
            tmp / "evd" / "rec.json", repo, commit_a, [sandbox[4]],
            protocol="differential", differential=differential)
        with pytest.raises(
                SubstanceError,
                match="differential_parent_evidence_rejected:"
                      "regression_evidence_format_mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_parent_green_but_incomplete_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        parent = sandbox[3]
        parent_ev = write_evidence_record(
            tmp / "evpi" / "parent.json", repo, parent,
            [write_junit(tmp / "evpi" / "junit.xml", passed=1)])
        import hashlib as _h
        differential = {
            "parent_commit": parent,
            "parent_evidence": {
                "path": str(parent_ev),
                "sha256": _h.sha256(
                    parent_ev.read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [], "runner_files": [],
                            "other_files": ["cand.txt"]}}
        rec = write_evidence_record(
            tmp / "evpi" / "rec.json", repo, commit_a, [sandbox[4]],
            protocol="differential", differential=differential)
        with pytest.raises(
                SubstanceError,
                match="differential_parent_evidence_rejected:"
                      "regression_collection_static_mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_parent_junit_swapped_refused(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        parent = sandbox[3]
        parent_junit = write_junit(tmp / "evps" / "junit.xml", passed=3)
        parent_ev = write_evidence_record(
            tmp / "evps" / "parent.json", repo, parent, [parent_junit])
        write_junit(parent_junit, passed=2)  # 原件被替换
        import hashlib as _h
        differential = {
            "parent_commit": parent,
            "parent_evidence": {
                "path": str(parent_ev),
                "sha256": _h.sha256(
                    parent_ev.read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [], "runner_files": [],
                            "other_files": ["cand.txt"]}}
        rec = write_evidence_record(
            tmp / "evps" / "rec.json", repo, commit_a, [sandbox[4]],
            protocol="differential", differential=differential)
        with pytest.raises(
                SubstanceError,
                match="differential_parent_evidence_rejected:"
                      "regression_junit_sha_mismatch"):
            verify_regression_evidence(rec, repo, commit_a)

    def test_doc_only_delta_accepted(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        parent = sandbox[3]
        parent_ev = write_evidence_record(
            tmp / "evdo" / "parent.json", repo, parent,
            [write_junit(tmp / "evdo" / "punit.xml", passed=3)])
        import hashlib as _h
        differential = {
            "parent_commit": parent,
            "parent_evidence": {
                "path": str(parent_ev),
                "sha256": _h.sha256(
                    parent_ev.read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [], "runner_files": [],
                            "other_files": ["cand.txt"]}}
        rec = write_evidence_record(
            tmp / "evdo" / "rec.json", repo, commit_a, [sandbox[4]],
            protocol="differential", differential=differential)
        out = verify_regression_evidence(rec, repo, commit_a)
        assert out["record"]["protocol"] == "differential"
        assert out["collection_tests"] == out["static_tests"]


class TestDeploymentSurface:
    """部署面(可选维度):提供 deploy_root 时字节必须匹配候选映射。"""

    def test_surface_drift_refused_then_clean_accepted(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        rec = write_evidence_record(
            tmp / "evdp" / "rec.json", repo, commit_a, [sandbox[4]])
        surface = sync_deploy_surface(repo, commit_a, tmp / "deploy")
        target = surface / "test_sandbox.py"
        target.write_bytes(target.read_bytes() + b"\n# drift\n")
        with pytest.raises(SubstanceError,
                           match="regression_deployment_surface_mismatch"):
            verify_regression_evidence(rec, repo, commit_a,
                                       deploy_root=tmp / "deploy")
        sync_deploy_surface(repo, commit_a, tmp / "deploy")
        out = verify_regression_evidence(rec, repo, commit_a,
                                         deploy_root=tmp / "deploy")
        assert out["collection_tests"] == out["static_tests"]

    def test_surface_helper_writes_exact_mapping(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        surface = sync_deploy_surface(repo, commit_a, tmp / "deploy2")
        verify_deployment_surface(
            tmp / "deploy2", candidate_test_map(repo, commit_a))
        assert (surface / "conftest.py").is_file()


class TestSameSourceNoDrift:
    """同源零漂移:映射与 node-ID 转换必须与 runner 侧权威一致。"""

    def test_candidate_test_map_equals_guard(self, sandbox):
        guard = _guard_module()
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
        mine = candidate_test_map(repo, commit_a)
        theirs = guard.candidate_test_map(repo, commit_a)
        assert set(mine) == set(theirs)
        for key, row in mine.items():
            other = theirs[key]
            assert row["source_path"] == other["source_path"]
            assert row["deploy_path"] == other["deploy_path"]
            assert row["deploy_sha256"] == other["deploy_sha256"]
            assert row["deploy_size"] == other["deploy_size"]
            assert row["is_test"] == other["is_test"]
            assert other["normalization"] == (
                "delete-all-CR-bytes/r17_sync.sh")

    def test_junit_nodeid_equals_guard(self):
        guard = _guard_module()
        samples = [
            ("tests.route_c_stage2_6_1.test_x",
             "test_plain"),
            ("tests.route_c_stage2_6_1.test_x.TestC",
             "test_method[param-1]"),
        ]
        for classname, name in samples:
            assert junit_nodeid(classname, name) == guard.junit_nodeid(
                {"classname": classname, "name": name})
        with pytest.raises(SubstanceError,
                           match="regression_junit_classname_unknown"):
            junit_nodeid("unknown.module.TestC", "test_x")
        with pytest.raises(Exception):
            guard.junit_nodeid({"classname": "unknown.module.TestC",
                                "name": "test_x"})


class TestIssuerConsumerEndToEnd:
    """A3 沙箱:真实签发器子进程 + 真实消费端闸门,两端同源;
    无效证据不能获得或消费有效许可;正式部署面零触碰。"""

    @staticmethod
    def _sandbox_deploy(tmp: Path, repo: Path, commit_a: str) -> tuple:
        deploy = tmp / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        state = (deploy / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True)
        return deploy, state

    def test_issue_then_consume_roundtrip(self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
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
        (repo / "stage2_6_1").mkdir(exist_ok=True)
        (repo / "stage2_6_1" / "src").symlink_to(
            real_src, target_is_directory=True)
        deploy, state = self._sandbox_deploy(tmp, repo, commit_a)
        rec = write_evidence_record(
            tmp / "e2e" / "rec.json", repo, commit_a, [sandbox[4]])
        prereg = write_preregistration(
            tmp / "e2e" / "prereg.json", repo, commit_a, rec,
            admission_id="e2e-aid-0001")
        proc = subprocess.run(
            [sys.executable, str(issuer), "--repo", str(repo),
             "--deploy-root", str(deploy), "--state-root", str(state),
             "--commit-a", commit_a, "--preregistration", str(prereg)],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        adm_path = deploy / ".r17_formal_admission.json"
        assert adm_path.is_file()
        from rl_curriculum.curriculum261_r17_admission import (
            enforce_formal_admission, validate_admission)
        ok, reason, adm = validate_admission(
            deploy, state, commit_a, str(repo))
        assert ok, reason
        # 证据原件替换(消费前):同源复验必拒
        original = sandbox[4].read_bytes()
        write_junit(sandbox[4], passed=2)
        ok2, reason2, _ = validate_admission(
            deploy, state, commit_a, str(repo))
        assert ok2 is False
        assert "regression_junit_sha_mismatch" in reason2
        sandbox[4].write_bytes(original)  # 还原后走正式消费路径
        assert enforce_formal_admission(state, commit_a, str(repo)) is None
        assert enforce_formal_admission(
            state, commit_a, str(repo)) == "admission_already_consumed"

    def test_issuer_refuses_incomplete_evidence_zero_side_effects(
            self, sandbox):
        tmp, repo, commit_a = sandbox[0], sandbox[1], sandbox[2]
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
        (repo / "stage2_6_1").mkdir(exist_ok=True)
        (repo / "stage2_6_1" / "src").symlink_to(
            real_src, target_is_directory=True)
        deploy, state = self._sandbox_deploy(tmp, repo, commit_a)
        junit = write_junit(tmp / "e2eneg" / "junit.xml", passed=1)
        rec = write_evidence_record(
            tmp / "e2eneg" / "rec.json", repo, commit_a, [junit])
        prereg = write_preregistration(
            tmp / "e2eneg" / "prereg.json", repo, commit_a, rec,
            admission_id="e2e-aid-neg")
        proc = subprocess.run(
            [sys.executable, str(issuer), "--repo", str(repo),
             "--deploy-root", str(deploy), "--state-root", str(state),
             "--commit-a", commit_a, "--preregistration", str(prereg)],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert "regression_collection_static_mismatch" in (
            proc.stdout + proc.stderr)
        assert not (deploy / ".r17_formal_admission.json").exists()
        assert not (deploy / "r17_admission_issued.jsonl").exists()
