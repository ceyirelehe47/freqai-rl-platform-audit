# -*- coding: utf-8 -*-
"""R17 准入实质绑定(v3)行为级测试。

2026-09-25 v3 轮(RouteC_FullCollection_ResearchDesign_NextGoal_v1
工作 A):完整参数实例与实际执行的同源绑定。合法完整证据一律来自
真实执行器(runner/r21_full_collection_regression.py)在沙箱部署面
上的真实 pytest 收集/执行原件;负例 = 复制运行目录后定向改造,经
被测包真实函数核验。覆盖验收矩阵 A01-A10:

- A01 子集冒充 full(probe 树真实全跑失败 + 真实子集 JUnit);
- A02 合法全绿参数树完整签发→消费→重复消费拒绝;
- A03 参数化 fixture / pytest_generate_tests 真实展开 + 遗漏负例;
- A04 同数换实例 / collection-JUnit 同漏实例拒绝;
- A05 argv/环境/配置筛选面(-k、node-ID、PYTEST_ADDOPTS、
  pytest.ini addopts、conftest 收集 hook)不能获得 full;
- A06 收集/执行身份漂移(解释器、python 版本、借用 stdout);
- A07 封口后原件替换(junit/收集 stdout);
- A08 既有防线不回退(元素级 junit、父证据递归、多文件唯一性、
  合法分片、skip 允许表);
- 签发/消费沙箱 e2e 全程隔离,不触正式部署面。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r17_admission_substance import (
    HISTORICAL_SKIP_IDS,
    SubstanceError,
    candidate_test_map,
    junit_nodeid,
    parse_junit,
    verify_preregistration_substance,
    substance_digest,
    verify_admission_substance,
    verify_regression_evidence,
)
from r17_admission_substance_test_support import (
    copy_run,
    edit_record,
    executor_path,
    git_repo_with_candidate,
    read_record,
    record_path,
    rehash_artifact,
    rewrite_collection_stdout,
    run_executor,
    substance_src,
    sync_deploy_surface,
    write_preregistration,
)

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

_CANONICAL_TOTAL = 15          # 8 通过实例 + 7 历史 skip
_CANONICAL_STATIC_BASES = 11   # 4 canonical 函数 + 7 桩函数


def _guard_module():
    for path in (_REPO_RUNNER, _DEPLOY_RUNNER, _EXEC_RUNNER):
        if path.is_file():
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "r17_v2_c13_admission_guard_sandbox", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    pytest.skip("runner/r17_v2_c13_admission_guard.py 不可达")


def _issuer() -> Path:
    for path in _ISSUER_CANDIDATES:
        if path.is_file():
            return path
    pytest.skip("runner/r17_admission_issue.py 不可达")


def _read_doc(rec: Path) -> dict:
    return json.loads(Path(rec).read_text(encoding="utf-8"))


def _write_doc(rec: Path, doc: dict) -> Path:
    Path(rec).write_text(json.dumps(doc, indent=1, ensure_ascii=False),
                         encoding="utf-8")
    return rec


def _remove_testcase(text: str, marker: str) -> str:
    """从 junit 文本删除一个 testcase 元素(自闭合与子元素两种形态)。"""
    start = text.index(marker)
    self_end = text.find("/>", start)
    close_end = text.find("</testcase>", start)
    ends = [e for e in (self_end + 2 if self_end != -1 else -1,
                        close_end + len("</testcase>")
                        if close_end != -1 else -1) if e > start]
    return text[:start] + text[min(ends):]


def _collected_ids(run_dir: Path) -> list[str]:
    from rl_curriculum.curriculum261_r17_admission_substance import (
        parse_collection_stdout)
    return parse_collection_stdout(
        (Path(run_dir) / "collection.stdout.txt").read_text(
            encoding="utf-8"))


def _sandbox_of(shared) -> tuple:
    return shared.tmp, shared.repo, shared.commit_a


class TestPreregistrationSubstance:
    def test_happy_path_full_protocol(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        prereg = write_preregistration(
            run.base / "prereg.json", run.repo, run.commit_a, run.record)
        doc = _read_doc(prereg)
        substance = verify_preregistration_substance(
            run.repo, run.commit_a, doc)
        assert substance["plan_digest_recomputed"] == doc["plan_digest"]
        counts = substance["regression_evidence"]["counts"]
        assert counts["failures"] == 0 and counts["errors"] == 0
        assert counts["skipped"] == len(HISTORICAL_SKIP_IDS) == 7
        assert substance["regression_evidence"][
            "collection_tests"] == _CANONICAL_TOTAL

    def test_plan_digest_mismatch_refused(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        bad = write_preregistration(
            run.base / "prereg_bad.json", run.repo, run.commit_a,
            run.record, plan_digest="0" * 40)
        with pytest.raises(SubstanceError, match="plan_digest_mismatch"):
            verify_preregistration_substance(
                run.repo, run.commit_a, _read_doc(bad))

    def test_v1_dummy_digest_method_refused(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        prereg = write_preregistration(
            run.base / "prereg.json", run.repo, run.commit_a, run.record)
        doc = _read_doc(prereg)
        del doc["plan_digest_method"]
        with pytest.raises(SubstanceError,
                           match="plan_digest_method_unsupported"):
            verify_preregistration_substance(run.repo, run.commit_a, doc)

    def test_missing_evidence_refused(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        prereg = write_preregistration(
            run.base / "prereg.json", run.repo, run.commit_a, run.record)
        doc = _read_doc(prereg)
        doc.pop("regression_evidence")
        with pytest.raises(SubstanceError,
                           match="regression_evidence_not_preregistered"):
            verify_preregistration_substance(run.repo, run.commit_a, doc)

    def test_count_mismatch_refused(self, r17_canonical_full_run,
                                    tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "ev2")
        edit_record(copied, lambda doc: doc["counts"].__setitem__(
            "tests", 99))
        with pytest.raises(SubstanceError,
                           match="regression_count_mismatch:tests"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_extra_skip_outside_allowed_table_refused(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "ev3")
        junit = copied / "junit.xml"
        text = junit.read_text(encoding="utf-8")
        extra = ('<testcase classname='
                 '"tests.route_c_stage2_6_1.test_sandbox"'
                 ' name="test_outside"><skipped/></testcase>')
        text = text.replace("</testsuite>", extra + "</testsuite>")
        text = text.replace('tests="15"', 'tests="16"')
        text = text.replace('skipped="7"', 'skipped="8"')
        junit.write_text(text, encoding="utf-8")
        rehash_artifact(copied, "junit.xml")

        def _fix(doc):
            doc["counts"]["tests"] = 16
            doc["counts"]["skipped"] = 8
            doc["historical_skip_ids"] = sorted(HISTORICAL_SKIP_IDS) + [
                "tests.route_c_stage2_6_1.test_sandbox::test_outside"]
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_skip_ids_outside_"
                                 "allowed_table"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_junit_bytes_swapped_refused(self, r17_canonical_full_run,
                                         tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "ev4")
        (copied / "junit.xml").write_text(
            (copied / "junit.xml").read_text(encoding="utf-8")
            + "<!-- drift -->", encoding="utf-8")
        with pytest.raises(SubstanceError,
                           match="regression_junit_sha_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_differential_src_change_refused(self, r17_canonical_full_run,
                                             tmp_path):
        run = r17_canonical_full_run
        src = run.repo / "stage2_6_1" / "src" / "rl_curriculum" / (
            "curriculum261_r17_admission_substance.py")
        src.write_text(src.read_text(encoding="utf-8") + "\n# drift\n",
                       encoding="utf-8")
        subprocess.run(["git", "-C", str(run.repo), "add", "-A"],
                       check=True)
        subprocess.run(["git", "-C", str(run.repo), "commit", "-qm",
                        "src"], check=True)
        new_head = subprocess.run(
            ["git", "-C", str(run.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        copied = copy_run(run.run_dir, tmp_path / "evd")

        def _fix(doc):
            doc["commit_a_sha"] = new_head
            doc["protocol"] = "differential"
            doc["differential"] = {
                "parent_commit": run.commit_a,
                "parent_evidence": {
                    "path": str(run.record),
                    "sha256": hashlib.sha256(
                        run.record.read_bytes()).hexdigest()},
                "delta_scope": {"tests_files": [],
                                "runner_files": [],
                                "other_files": ["cand.txt", "src"]},
                "delta_targets": [
                    "tests/route_c_stage2_6_1/test_sandbox.py"]}
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="differential_src_changed"):
            verify_regression_evidence(
                record_path(copied), run.repo, new_head)


class TestAdmissionSubstanceConsumer:
    def test_valid_then_tampered_then_replaced(self,
                                               r17_canonical_full_run):
        run = r17_canonical_full_run
        prereg = write_preregistration(
            run.base / "prereg.json", run.repo, run.commit_a, run.record)
        fields = {
            "substance": verify_preregistration_substance(
                run.repo, run.commit_a, _read_doc(prereg))}
        fields["substance_digest"] = substance_digest(
            fields["substance"])
        admission = {
            "format": "cur261-r17-formal-admission-v2",
            "commit_a_sha": run.commit_a,
            "plan_digest": fields["substance"][
                "plan_digest_recomputed"],
            **fields}
        assert verify_admission_substance(admission, run.repo) == (
            True, "ok")
        tampered = json.loads(json.dumps(admission))
        tampered["substance"]["plan_digest_recomputed"] = "0" * 40
        assert verify_admission_substance(tampered, run.repo)[0] is False
        v1 = json.loads(json.dumps(admission))
        v1.pop("substance")
        assert verify_admission_substance(v1, run.repo) == (
            False, "admission_substance_missing")

    def test_replaced_evidence_refused(self, r17_canonical_full_run,
                                       tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "c2")
        prereg = write_preregistration(
            tmp_path / "prereg2.json", run.repo, run.commit_a,
            record_path(copied))
        substance = verify_preregistration_substance(
            run.repo, run.commit_a, _read_doc(prereg))
        # 签发后、消费前:原件被替换
        (copied / "junit.xml").write_text(
            (copied / "junit.xml").read_text(encoding="utf-8")
            + " ", encoding="utf-8")
        admission = {
            "format": "cur261-r17-formal-admission-v2",
            "commit_a_sha": run.commit_a,
            "plan_digest": substance["plan_digest_recomputed"],
            "substance": substance,
            "substance_digest": substance_digest(substance)}
        # 消费时原件已被替换:同源复验必拒
        ok, reason = verify_admission_substance(admission, run.repo)
        assert ok is False and "regression_junit_sha_mismatch" in reason


class TestSkipTableNoDrift:
    def test_matches_runner_guard_table(self):
        guard = _guard_module()
        assert frozenset(guard.HISTORICAL_SKIP_IDS) == frozenset(
            HISTORICAL_SKIP_IDS)


class TestIssuerV2RequiresSubstance:
    """签发器(真实子进程):无实质绑定/错 plan_digest ⇒ 拒 + 零副作用。"""

    def test_refuses_and_zero_side_effects(self, r17_canonical_full_run,
                                           tmp_path):
        run = r17_canonical_full_run
        deploy = tmp_path / "deploy"
        shutil.copytree(run.deploy, deploy)
        state = (deploy / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True)
        bad = write_preregistration(
            tmp_path / "prereg_bad.json", run.repo, run.commit_a,
            run.record, plan_digest="0" * 40,
            admission_id="issuer-neg-aid")
        proc = subprocess.run(
            [sys.executable, str(_issuer()), "--repo", str(run.repo),
             "--deploy-root", str(deploy), "--state-root", str(state),
             "--commit-a", run.commit_a,
             "--preregistration", str(bad)],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert "plan_digest_mismatch" in (proc.stdout + proc.stderr)
        assert not (deploy / ".r17_formal_admission.json").exists()
        assert not (deploy / "r17_admission_issued.jsonl").exists()


# ------------- parse_junit 元素级核验(A08 既有防线) -------------

def _write_raw_junit(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class TestParseJunitElementLevel:
    """计数必须来自 testcase 元素并与 suite 属性交叉核对。"""

    def test_attribute_green_but_failure_element_rejected(self,
                                                          tmp_path):
        jp = _write_raw_junit(tmp_path / "a.xml",
                              '<?xml version="1.0"?><testsuite tests="1"'
                              ' failures="0" errors="0" skipped="0">'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_a"><failure/></testcase>'
                              "</testsuite>")
        with pytest.raises(SubstanceError,
                           match="regression_junit_element_attribute_"
                                 "mismatch:failures"):
            parse_junit(jp)

    def test_error_element_counted(self, tmp_path):
        """error 元素被如实计数;not_green 拒绝发生在 record 层
        (parse_junit 自身只做元素/属性交叉核对)。"""
        jp = _write_raw_junit(tmp_path / "b.xml",
                              '<?xml version="1.0"?><testsuite tests="1"'
                              ' failures="0" errors="1" skipped="0">'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_a"><error/></testcase>'
                              "</testsuite>")
        doc = parse_junit(jp)
        assert doc["errors"] == 1 and doc["tests"] == 1

    def test_skipped_attribute_inflation_rejected(self, tmp_path):
        jp = _write_raw_junit(tmp_path / "c.xml",
                              '<?xml version="1.0"?><testsuite tests="2"'
                              ' failures="0" errors="0" skipped="2">'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_a"><skipped/></testcase>'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_b"/></testsuite>')
        with pytest.raises(SubstanceError,
                           match="regression_junit_element_attribute_"
                                 "mismatch:skipped"):
            parse_junit(jp)

    def test_duplicate_testcase_id_rejected(self, tmp_path):
        jp = _write_raw_junit(tmp_path / "d.xml",
                              '<?xml version="1.0"?><testsuite tests="2"'
                              ' failures="0" errors="0" skipped="0">'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_a"/>'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_a"/></testsuite>')
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_testcase"):
            parse_junit(jp)

    def test_malformed_testcase_rejected(self, tmp_path):
        jp = _write_raw_junit(tmp_path / "e.xml",
                              '<?xml version="1.0"?><testsuite tests="1"'
                              ' failures="0" errors="0" skipped="0">'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"/>'
                              "</testsuite>")
        with pytest.raises(SubstanceError,
                           match="regression_junit_testcase_malformed"):
            parse_junit(jp)

    def test_normal_green_junit_compatible(self, tmp_path):
        jp = _write_raw_junit(tmp_path / "f.xml",
                              '<?xml version="1.0"?><testsuite tests="1"'
                              ' failures="0" errors="0" skipped="0">'
                              '<testcase classname='
                              '"tests.route_c_stage2_6_1.test_x"'
                              ' name="test_a"/></testsuite>')
        doc = parse_junit(jp)
        assert doc["tests"] == 1 and doc["case_ids"] == [
            "tests.route_c_stage2_6_1.test_x::test_a"]


# ------------- 完整参数实例(F1 v3;A01/A03/A04) -------------

class TestParametricFullCollection:
    """期望全集 = 真实 --collect-only 原件重解析;参数实例齐全。"""

    def test_canonical_collection_expands_all_param_kinds(
            self, r17_canonical_full_run):
        run = r17_canonical_full_run
        ids = _collected_ids(run.run_dir)
        prefix = "tests/route_c_stage2_6_1/test_sandbox.py::"
        for node_id in (f"{prefix}test_parameter[0]",
                        f"{prefix}test_parameter[1]",
                        f"{prefix}test_parameter[2]",
                        f"{prefix}test_fixture_param[fa]",
                        f"{prefix}test_fixture_param[fb]",
                        f"{prefix}test_generated[g1]",
                        f"{prefix}test_generated[g2]",
                        f"{prefix}test_plain_ok"):
            assert node_id in ids, node_id
        assert len(ids) == _CANONICAL_TOTAL
        out = verify_regression_evidence(
            run.record, run.repo, run.commit_a)
        assert out["collection_tests"] == _CANONICAL_TOTAL
        assert out["static_tests"] == _CANONICAL_STATIC_BASES
        assert out["aggregate"]["skipped"] == 7

    def test_v1_and_v2_format_refused(self, r17_canonical_full_run,
                                      tmp_path):
        run = r17_canonical_full_run
        for old in ("cur261-r17-candidate-regression-evidence-v1",
                    "cur261-r17-candidate-regression-evidence-v2"):
            copied = copy_run(run.run_dir, tmp_path / f"fmt_{old[-6:]}")

            def _fix(doc, _old=old):
                doc["format"] = _old
            edit_record(copied, _fix)
            with pytest.raises(SubstanceError,
                               match="regression_evidence_format_"
                                     "mismatch"):
                verify_regression_evidence(
                    record_path(copied), run.repo, run.commit_a)

    def test_missing_v3_blocks_refused(self, r17_canonical_full_run,
                                       tmp_path):
        run = r17_canonical_full_run
        for field, word in (
                ("collection_run", "regression_collection_run_runs_"
                                   "invalid"),
                ("execution", "regression_execution_runs_invalid"),
                ("test_files", "regression_test_files_missing"),
                ("import_surface", "regression_import_surface_missing"),
        ):
            copied = copy_run(run.run_dir, tmp_path / f"drop_{field}")

            def _fix(doc, _f=field):
                doc.pop(_f, None)
            edit_record(copied, _fix)
            with pytest.raises(SubstanceError, match=word):
                verify_regression_evidence(
                    record_path(copied), run.repo, run.commit_a)

    def test_single_instance_omitted_from_junit_refused(
            self, r17_canonical_full_run, tmp_path):
        """A04:collection 与 JUnit 同漏一个参数实例 ⇒ multiset 失配。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "omit1")
        junit = copied / "junit.xml"
        text = junit.read_text(encoding="utf-8")
        marker = ('<testcase classname='
                  '"tests.route_c_stage2_6_1.test_sandbox"'
                  ' name="test_parameter[1]"')
        text = _remove_testcase(text, marker)
        text = text.replace('tests="15"', 'tests="14"')
        junit.write_text(text, encoding="utf-8")
        rehash_artifact(copied, "junit.xml")

        def _fix(doc):
            doc["counts"]["tests"] = 14
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_collection_execution_"
                                 "mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_same_count_instance_swap_refused(self,
                                              r17_canonical_full_run,
                                              tmp_path):
        """A04:计数不变,把 [1] 换成不存在的 [7] ⇒ multiset 失配。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "swap")
        junit = copied / "junit.xml"
        raw = junit.read_bytes().replace(
            b'name="test_parameter[1]"', b'name="test_parameter[7]"')
        junit.write_bytes(raw)
        rehash_artifact(copied, "junit.xml")
        with pytest.raises(SubstanceError,
                           match="regression_collection_execution_"
                                 "mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_dynamic_instance_omitted_from_collection_refused(
            self, r17_canonical_full_run, tmp_path):
        """A03:收集原件遗漏 generate_tests 展开实例(计数行同步
        修正以越过计数层)⇒ 与 junit multiset 失配。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "dyn")
        ids = [i for i in _collected_ids(copied)
               if i != ("tests/route_c_stage2_6_1/test_sandbox.py::"
                        "test_generated[g2]")]
        assert len(ids) == _CANONICAL_TOTAL - 1
        rewrite_collection_stdout(copied, ids)
        rehash_artifact(copied, "collection.stdout.txt")
        with pytest.raises(SubstanceError,
                           match="regression_collection_execution_"
                                 "mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_dynamic_function_omitted_from_collection_refused(
            self, r17_canonical_full_run, tmp_path):
        """A03:整个动态函数从收集原件消失 ⇒ 静态全集失配。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "dyn2")
        ids = [i for i in _collected_ids(copied)
               if "::test_generated[" not in i]
        rewrite_collection_stdout(copied, ids)
        rehash_artifact(copied, "collection.stdout.txt")
        with pytest.raises(SubstanceError,
                           match="regression_collection_static_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_scope_leak_in_collection_refused(self, r17_canonical_full_run,
                                              tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "leak")
        (copied / "collection.stdout.txt").write_text(
            "other_dir/test_x.py::test_evil\n1 tests collected in 0.1s\n",
            encoding="utf-8")
        rehash_artifact(copied, "collection.stdout.txt")
        with pytest.raises(SubstanceError,
                           match="regression_collection_scope_leak"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)


# ------------- A01:子集冒充 full(真实反例树) -------------

class TestSubsetMimickingFull:
    """probe 树(三参数实例之一有意失败):真实全跑失败留痕;
    只跑通过实例的真实子集 JUnit 与完整收集组装成 record 冒充
    full ⇒ 同源核验与真实签发器都拒绝。"""

    @pytest.fixture()
    def probe_run(self, tmp_path):
        repo, commit_a, parent = git_repo_with_candidate(
            tmp_path, probe=True)
        deploy = tmp_path / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        run_dir, summary, rc = run_executor(
            tmp_path / "run", repo, commit_a, deploy, expect_rc=(3, 4))
        return tmp_path, repo, commit_a, parent, deploy, run_dir, summary

    @staticmethod
    def _subset_junit(deploy: Path, out: Path) -> Path:
        node = ("tests/route_c_stage2_6_1/test_sandbox.py::"
                "test_parameter[0]")
        node2 = ("tests/route_c_stage2_6_1/test_sandbox.py::"
                 "test_parameter[2]")
        stubs = sorted(
            "tests/route_c_stage2_6_1/" + p.name
            for p in (deploy / "tests" / "route_c_stage2_6_1").glob(
                "test_curriculum261_*.py"))
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", node, node2, *stubs,
             "-q", f"--junitxml={out.resolve()}"],
            cwd=str(deploy), capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stdout
        return out

    def test_full_run_failure_recorded_and_refused(self, probe_run):
        tmp, repo, commit_a, parent, deploy, run_dir, summary = probe_run
        record = read_record(run_dir)
        assert record["execution"]["runs"][0]["returncode"] == 1
        assert record["counts"]["failures"] == 1
        assert summary["ok"] is False
        with pytest.raises(SubstanceError,
                           match="regression_not_green|returncode_nonzero"):
            verify_regression_evidence(
                record_path(run_dir), repo, commit_a)

    def test_subset_junit_cannot_mimic_full(self, probe_run, tmp_path):
        tmp, repo, commit_a, parent, deploy, run_dir, summary = probe_run
        subset = self._subset_junit(deploy, tmp_path / "subset_junit.xml")
        subset_stdout = tmp_path / "subset.stdout.txt"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1/test_sandbox.py::"
             "test_parameter[0]",
             "tests/route_c_stage2_6_1/test_sandbox.py::"
             "test_parameter[2]",
             *sorted("tests/route_c_stage2_6_1/" + p.name
                     for p in (deploy / "tests" / "route_c_stage2_6_1"
                               ).glob("test_curriculum261_*.py")),
             "-q"],
            cwd=str(deploy), capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0
        subset_stdout.write_text(proc.stdout, encoding="utf-8")
        forged = copy_run(run_dir, tmp_path / "forged")
        shutil.copyfile(subset, forged / "junit.xml")
        shutil.copyfile(subset_stdout, forged / "execution.stdout.txt")

        def _fix(doc):
            import hashlib as _h
            doc["junit"][0]["sha256"] = _h.sha256(
                (forged / "junit.xml").read_bytes()).hexdigest()
            parsed = parse_junit(forged / "junit.xml")
            doc["counts"] = {"tests": parsed["tests"],
                             "failures": 0, "errors": 0,
                             "skipped": parsed["skipped"]}
            doc["historical_skip_ids"] = sorted(
                set(HISTORICAL_SKIP_IDS))
            run0 = doc["execution"]["runs"][0]
            run0["stdout"]["sha256"] = _h.sha256(
                (forged / "execution.stdout.txt").read_bytes()
            ).hexdigest()
            run0["returncode"] = 0
            # 表面命令伪装成 full 目录目标
            run0["command"] = [run0["command"][0], "-m", "pytest",
                               "tests/route_c_stage2_6_1", "-q",
                               "--junitxml=junit.xml"]
        edit_record(forged, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_collection_execution_"
                                 "mismatch"):
            verify_regression_evidence(
                record_path(forged), repo, commit_a)

    def test_honest_subset_command_refused(self,
                                           r17_canonical_full_run,
                                           tmp_path):
        """argv 如实携带 node-ID 目标(full 协议)⇒ 目标失配拒。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "honest")

        def _fix(doc):
            run0 = doc["execution"]["runs"][0]
            run0["command"] = [run0["command"][0], "-m", "pytest",
                               "tests/route_c_stage2_6_1/test_sandbox.py"
                               "::test_parameter[0]",
                               "-q", "--junitxml=junit.xml"]
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_run_argv_target_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)
    def test_issuer_refuses_forged_subset_evidence(self, probe_run,
                                                   tmp_path):
        tmp, repo, commit_a, parent, deploy, run_dir, summary = probe_run
        subset = self._subset_junit(deploy, tmp_path / "subset2.xml")
        forged = copy_run(run_dir, tmp_path / "forged2")
        shutil.copyfile(subset, forged / "junit.xml")

        def _fix(doc):
            import hashlib as _h
            doc["junit"][0]["sha256"] = _h.sha256(
                (forged / "junit.xml").read_bytes()).hexdigest()
            parsed = parse_junit(forged / "junit.xml")
            doc["counts"] = {"tests": parsed["tests"],
                             "failures": 0, "errors": 0,
                             "skipped": parsed["skipped"]}
            doc["historical_skip_ids"] = sorted(set(HISTORICAL_SKIP_IDS))
            doc["execution"]["runs"][0]["returncode"] = 0
        edit_record(forged, _fix)
        state = (deploy / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True)
        prereg = write_preregistration(
            tmp_path / "prereg_neg.json", repo, commit_a,
            record_path(forged), admission_id="a01-neg-aid")
        proc = subprocess.run(
            [sys.executable, str(_issuer()), "--repo", str(repo),
             "--deploy-root", str(deploy), "--state-root", str(state),
             "--commit-a", commit_a, "--preregistration", str(prereg)],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert "regression_collection_execution_mismatch" in (
            proc.stdout + proc.stderr)
        assert not (deploy / ".r17_formal_admission.json").exists()
        assert not (deploy / "r17_admission_issued.jsonl").exists()


# ------------- 运行来源绑定(A05/A06/A07) -------------

class TestRunProvenanceBinding:
    """收集原件与执行原件必须同源同环境;筛选入口一律 fail closed。"""

    def test_argv_k_filter_refused(self, r17_canonical_full_run,
                                   tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "k")

        def _fix(doc):
            doc["collection_run"]["runs"][0]["command"].insert(
                4, "-k")
            doc["collection_run"]["runs"][0]["command"].insert(
                5, "ok")
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_run_argv_filter:-k"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_argv_deselect_refused(self, r17_canonical_full_run,
                                   tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "dsel")

        def _fix(doc):
            doc["execution"]["runs"][0]["command"].append(
                "--deselect=tests/route_c_stage2_6_1/test_sandbox.py")
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_run_argv_filter:"
                                 "--deselect"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_env_addopts_recorded_refused(self, r17_canonical_full_run,
                                          tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "addopts")

        def _fix(doc):
            doc["collection_run"]["runs"][0]["env"][
                "pytest_addopts"] = "-k ok"
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_collection_run_env_"
                                 "filtered:pytest_addopts"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_collect_only_missing_refused(self, r17_canonical_full_run,
                                          tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "noco")

        def _fix(doc):
            cmd = doc["collection_run"]["runs"][0]["command"]
            cmd.remove("--collect-only")
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_run_collect_only_missing"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_execution_identity_drift_refused(self, r17_canonical_full_run,
                                              tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "iddrift")

        def _fix(doc):
            doc["execution"]["runs"][0]["env"][
                "python_version"] = "2.7.18"
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_run_identity_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_borrowed_stdout_refused(self, r17_canonical_full_run,
                                     tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "borrow")
        shutil.copyfile(copied / "collection.stdout.txt",
                        copied / "execution.stdout.txt")
        rehash_artifact(copied, "execution.stdout.txt")
        with pytest.raises(SubstanceError,
                           match="regression_execution_stdout_summary_"
                                 "missing"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_collection_artifact_replaced_after_seal_refused(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "seal")
        (copied / "collection.stdout.txt").write_text(
            (copied / "collection.stdout.txt").read_text(
                encoding="utf-8") + "# drift\n", encoding="utf-8")
        with pytest.raises(SubstanceError,
                           match="regression_collection_run_stdout_"
                                 "artifact_sha_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_deploy_config_filter_refused_at_verify_and_executor(
            self, r17_canonical_full_run, tmp_path):
        """A05:表面命令无筛选但部署面 pytest.ini addopts 实际筛选:
        同源核验(配置扫描失配/内容过滤)与执行器预检双双拒绝。"""
        run = r17_canonical_full_run
        poisoned = tmp_path / "deploy_poisoned"
        shutil.copytree(run.deploy, poisoned)
        (poisoned / "pytest.ini").write_text(
            "[pytest]\naddopts = -k ok\n", encoding="utf-8")
        # (a) record 未声明该 ini ⇒ 部署面复扫不一致即拒
        scan_mismatch = copy_run(run.run_dir, tmp_path / "ini_scan")
        conftest_sha = hashlib.sha256(
            (poisoned / "tests" / "route_c_stage2_6_1" / "conftest.py"
             ).read_bytes()).hexdigest()

        def _cwd_a(doc):
            for block in (doc["collection_run"]["runs"]
                          + doc["execution"]["runs"]):
                block["cwd"] = str(poisoned)
                block["env"]["config_scan"] = [{
                    "path": str(poisoned / "tests" / "route_c_stage2_6_1"
                               / "conftest.py"),
                    "sha256": conftest_sha}]
        edit_record(scan_mismatch, _cwd_a)
        with pytest.raises(SubstanceError,
                           match="regression_config_scan_mismatch"):
            verify_regression_evidence(
                record_path(scan_mismatch), run.repo, run.commit_a,
                deploy_root=poisoned)
        # (b) record 声明了该 ini(扫描一致)⇒ 内容过滤层拒绝
        copied = copy_run(run.run_dir, tmp_path / "ini")
        ini_sha = hashlib.sha256(
            (poisoned / "pytest.ini").read_bytes()).hexdigest()

        def _fix(doc):
            for block in (doc["collection_run"]["runs"]
                          + doc["execution"]["runs"]):
                block["cwd"] = str(poisoned)
                block["env"]["config_scan"] = [
                    {"path": str(poisoned / "tests" / "route_c_stage2_6_1"
                                / "conftest.py"),
                     "sha256": conftest_sha},
                    {"path": str(poisoned / "pytest.ini"),
                     "sha256": ini_sha}]
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_config_addopts_filter"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a,
                deploy_root=poisoned)
        # 执行器预检:运行前即拒(rc=2,不产生 run)
        proc = subprocess.run(
            [sys.executable, str(executor_path()),
             "--repo", str(run.repo), "--commit-a", run.commit_a,
             "--deploy-root", str(poisoned),
             "--out-dir", str(tmp_path / "refused_run"),
             "--substance-src", str(substance_src())],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert "refused" in (proc.stdout + proc.stderr)
        assert not (tmp_path / "refused_run" / "summary.json").exists()

    def test_candidate_conftest_collect_hook_refused(self, tmp_path):
        """A05:候选树 conftest 携带收集修改 hook ⇒ 执行器预检
        (运行前 fail closed)直接拒绝,不产生任何 run。"""
        repo, commit_a, parent = git_repo_with_candidate(tmp_path)
        conftest = (repo / "stage2_6_1" / "tests" /
                    "route_c_stage2_6_1" / "conftest.py")
        conftest.write_text(
            conftest.read_text(encoding="utf-8")
            + "\n\ndef pytest_collection_modifyitems(items):\n"
              "    pass\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm",
                        "hook"], check=True)
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        deploy = tmp_path / "deploy"
        sync_deploy_surface(repo, head, deploy)
        proc = subprocess.run(
            [sys.executable, str(executor_path()),
             "--repo", str(repo), "--commit-a", head,
             "--deploy-root", str(deploy),
             "--out-dir", str(tmp_path / "refused_run"),
             "--substance-src", str(substance_src())],
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert "regression_config_filter_hook" in (proc.stdout
                                                   + proc.stderr)
        assert not (tmp_path / "refused_run" / "summary.json").exists()


# ------------- A08:合法分片 + 多文件唯一性(既有防线) -------------

class TestShardedFullRun:
    def test_legal_shards_accepted(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        test_dir = run.deploy / "tests" / "route_c_stage2_6_1"
        sandbox = f"tests/route_c_stage2_6_1/test_sandbox.py"
        stubs = sorted(
            f"tests/route_c_stage2_6_1/{p.name}"
            for p in test_dir.glob("test_curriculum261_*.py"))
        run_dir, summary, rc = run_executor(
            run.base / "sharded", run.repo, run.commit_a, run.deploy,
            shards=[sandbox] + stubs, expect_rc=(0,))
        assert rc == 0 and summary["ok"], summary
        out = verify_regression_evidence(
            record_path(run_dir), run.repo, run.commit_a)
        assert out["collection_tests"] == _CANONICAL_TOTAL
        assert out["aggregate"]["tests"] == _CANONICAL_TOTAL

    def test_overlapping_shards_refused(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        sandbox = "tests/route_c_stage2_6_1/test_sandbox.py"
        run_dir, summary, rc = run_executor(
            run.base / "overlap", run.repo, run.commit_a, run.deploy,
            shards=[sandbox, sandbox], expect_rc=(3,))
        assert "duplicate" in json.dumps(summary)


class TestMultiFileUniqueness:
    """F3:同一 junit(路径别名/同内容)与跨文件 testcase 重叠
    不得重复累计。"""

    def test_same_junit_twice_refused(self, r17_canonical_full_run,
                                      tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "dup")

        def _fix(doc):
            doc["junit"].append(dict(doc["junit"][0]))
            doc["counts"]["tests"] *= 2
            doc["counts"]["skipped"] *= 2
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_path"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_alias_path_reference_refused(self, r17_canonical_full_run,
                                          tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "alias")

        def _fix(doc):
            doc["junit"].append({
                "path": "./junit.xml",
                "sha256": doc["junit"][0]["sha256"]})
            doc["counts"]["tests"] *= 2
            doc["counts"]["skipped"] *= 2
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_path"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_identical_bytes_second_file_refused(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "samebytes")
        shutil.copyfile(copied / "junit.xml", copied / "junit_b.xml")

        def _fix(doc):
            doc["junit"].append({
                "path": "junit_b.xml",
                "sha256": doc["junit"][0]["sha256"]})
            doc["counts"]["tests"] *= 2
            doc["counts"]["skipped"] *= 2
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_junit_duplicate_content"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)


# ------------- F2:差分父证据链(v3) -------------
@pytest.fixture(scope="module")
def parent_run(r17_canonical_full_run):
    """base 提交(=真祖先)上的真实 full 运行,作为差分父证据。"""
    run = r17_canonical_full_run
    run_dir, summary, rc = run_executor(
        run.base / "parent_run", run.repo, run.parent, run.deploy,
        expect_rc=(0,))
    assert rc == 0 and summary["ok"], summary
    return run_dir


class TestDifferentialParentChain:
    """父证据必须递归通过同一完整 v3 核验(部署面除外)。"""

    _DELTA_TARGET = "tests/route_c_stage2_6_1/test_sandbox.py"

    @staticmethod
    def _to_differential(doc: dict, parent_commit: str,
                         parent_rec: Path, targets: list[str],
                         other=("cand.txt",)) -> None:
        """把 full record 原地改写为形状自洽的差分 record
        (protocol/差分块/两段 argv positionals=delta 目标)。"""
        doc["protocol"] = "differential"
        doc["differential"] = {
            "parent_commit": parent_commit,
            "parent_evidence": {
                "path": str(parent_rec),
                "sha256": hashlib.sha256(
                    parent_rec.read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [], "runner_files": [],
                            "other_files": list(other)},
            "delta_targets": targets}
        for block_key in ("collection_run", "execution"):
            for entry in doc[block_key]["runs"]:
                command = entry["command"]
                head = command[:3]
                tail = [tok for tok in command[3:]
                        if tok.startswith("-")]
                entry["command"] = head + targets + tail

    def test_invalid_parent_refused(self, r17_canonical_full_run,
                                    tmp_path):
        run = r17_canonical_full_run
        fake = tmp_path / "fake_parent.json"
        fake.write_text(json.dumps({
            "protocol": "full", "commit_a_sha": run.parent,
            "counts": {"tests": 1, "failures": 1}}), encoding="utf-8")
        copied = copy_run(run.run_dir, tmp_path / "dp")

        def _fix(doc):
            self._to_differential(
                doc, run.parent, fake, [self._DELTA_TARGET])
        edit_record(copied, _fix)
        with pytest.raises(
                SubstanceError,
                match="differential_parent_evidence_rejected"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_v2_parent_not_grandfathered(self, r17_canonical_full_run,
                                         tmp_path):
        run = r17_canonical_full_run
        v2rec = tmp_path / "parent_v2.json"
        v2rec.write_text(json.dumps({
            "format": "cur261-r17-candidate-regression-evidence-v2",
            "protocol": "full", "commit_a_sha": run.parent,
            "scope": "formal"}), encoding="utf-8")
        copied = copy_run(run.run_dir, tmp_path / "dp2")

        def _fix(doc):
            self._to_differential(
                doc, run.parent, v2rec, [self._DELTA_TARGET])
        edit_record(copied, _fix)
        with pytest.raises(
                SubstanceError,
                match="differential_parent_evidence_rejected:"
                      "regression_evidence_format_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_parent_green_but_incomplete_refused(self,
                                                 r17_canonical_full_run,
                                                 tmp_path):
        run = r17_canonical_full_run
        parent_copy = copy_run(run.run_dir, tmp_path / "parent_bad")
        junit = parent_copy / "junit.xml"
        text = junit.read_text(encoding="utf-8")
        marker = ('<testcase classname='
                  '"tests.route_c_stage2_6_1.test_sandbox"'
                  ' name="test_parameter[1]"')
        text = _remove_testcase(text, marker).replace(
            'tests="15"', 'tests="14"')
        junit.write_text(text, encoding="utf-8")
        rehash_artifact(parent_copy, "junit.xml")

        def _pfix(doc):
            doc["counts"]["tests"] = 14
        edit_record(parent_copy, _pfix)
        # 父 record 自身已不完整:直接核验拒绝(不依赖子差分形态)
        with pytest.raises(SubstanceError,
                           match="regression_collection_execution_"
                                 "mismatch"):
            verify_regression_evidence(
                record_path(parent_copy), run.repo, run.commit_a)

    def test_parent_junit_swapped_refused(self, r17_canonical_full_run,
                                          parent_run, tmp_path):
        run = r17_canonical_full_run
        parent_copy = copy_run(parent_run, tmp_path / "parent_swap")
        (parent_copy / "junit.xml").write_text(
            (parent_copy / "junit.xml").read_text(encoding="utf-8")
            + "<!-- x -->", encoding="utf-8")
        copied = copy_run(run.run_dir, tmp_path / "ds")

        def _fix(doc):
            self._to_differential(
                doc, run.parent, record_path(parent_copy),
                [self._DELTA_TARGET], other=("cand.txt",))
        edit_record(copied, _fix)
        with pytest.raises(
                SubstanceError,
                match="differential_parent_evidence_rejected:"
                      "regression_junit_sha_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_doc_only_delta_accepted(self, tmp_path):
        """真实差分执行(独立仓,不受会话仓其他提交污染):候选仅
        新增文档文件;父 = 真实 full 运行。"""
        repo, commit_a, parent = git_repo_with_candidate(tmp_path)
        deploy = tmp_path / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        parent_dir, summary, rc = run_executor(
            tmp_path / "parent_run", repo, parent, deploy,
            expect_rc=(0,))
        assert rc == 0 and summary["ok"], summary
        (repo / "notes.txt").write_text("doc only\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "doc"],
                       check=True)
        child = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        child_run = tmp_path / "delta_run"
        differential = {
            "parent_commit": parent,
            "parent_evidence": {
                "path": os.path.relpath(
                    record_path(parent_dir), child_run),
                "sha256": hashlib.sha256(
                    record_path(parent_dir).read_bytes()).hexdigest()},
            "delta_scope": {"tests_files": [], "runner_files": [],
                            "other_files": ["cand.txt", "notes.txt"]},
            "delta_targets": [self._DELTA_TARGET]}
        diff_path = tmp_path / "differential.json"
        diff_path.write_text(json.dumps(differential), encoding="utf-8")
        run_dir, summary2, rc2 = run_executor(
            child_run, repo, child, deploy,
            protocol="differential", differential=diff_path,
            expect_rc=(0,))
        assert rc2 == 0 and summary2["ok"], summary2
        out = verify_regression_evidence(
            record_path(run_dir), repo, child)
        assert out["record"]["protocol"] == "differential"
        assert out["collection_tests"] < _CANONICAL_TOTAL


# ------------- 部署面 / import 面 / 清单(A06/A10) -------------

class TestDeploymentSurface:
    def test_surface_drift_refused_then_clean_accepted(
            self, r17_canonical_full_run):
        run = r17_canonical_full_run
        target = run.deploy / "tests" / "route_c_stage2_6_1" / (
            "test_sandbox.py")
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"\n# drift\n")
            with pytest.raises(
                    SubstanceError,
                    match="regression_deployment_surface_mismatch"):
                verify_regression_evidence(
                    run.record, run.repo, run.commit_a,
                    deploy_root=run.deploy)
        finally:
            target.write_bytes(original)
        out = verify_regression_evidence(
            run.record, run.repo, run.commit_a, deploy_root=run.deploy)
        assert out["collection_tests"] == _CANONICAL_TOTAL

    def test_surface_helper_writes_exact_mapping(self, tmp_path):
        repo, commit_a, _parent = git_repo_with_candidate(tmp_path)
        surface = sync_deploy_surface(repo, commit_a, tmp_path / "deploy2")
        from rl_curriculum.curriculum261_r17_admission_substance import (
            verify_deployment_surface)
        verify_deployment_surface(
            tmp_path / "deploy2", candidate_test_map(repo, commit_a))
        assert (surface / "conftest.py").is_file()
        assert ((tmp_path / "deploy2" / "src" / "rl_curriculum" / (
            "curriculum261_r17_admission_substance.py")).is_file())


class TestImportSurface:
    def test_record_member_tampered_refused(self, r17_canonical_full_run,
                                            tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "imp")

        def _fix(doc):
            members = doc["import_surface"]["members"]
            key = sorted(members)[0]
            members[key] = "0" * 64
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_import_surface_"
                                 "candidate_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_deploy_src_drift_refused(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        target = (run.deploy / "src" / "rl_curriculum" / "__init__.py")
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"# drift\n")
            with pytest.raises(
                    SubstanceError,
                    match="regression_import_surface_deploy_mismatch"):
                verify_regression_evidence(
                    run.record, run.repo, run.commit_a,
                    deploy_root=run.deploy)
        finally:
            target.write_bytes(original)

    def test_deploy_extra_module_undeclared_refused(
            self, r17_canonical_full_run):
        run = r17_canonical_full_run
        extra = (run.deploy / "src" / "rl_curriculum" / (
            "zzz_undeclared.py"))
        extra.write_text("# sneaky\n", encoding="utf-8")
        try:
            with pytest.raises(
                    SubstanceError,
                    match="regression_import_surface_extra_drift"):
                verify_regression_evidence(
                    run.record, run.repo, run.commit_a,
                    deploy_root=run.deploy)
        finally:
            extra.unlink()

    def test_declared_extra_module_accepted(self, r17_canonical_full_run):
        """部署侧既有共享模块(如 generator_api)如实声明后放行。"""
        run = r17_canonical_full_run
        extra = (run.deploy / "src" / "rl_curriculum" / (
            "generator_api.py"))
        extra.write_text("# deploy-only shared module\n", encoding="utf-8")
        copied = copy_run(run.run_dir, run.base / "declared_extra")

        def _fix(doc):
            doc["import_surface"]["deploy_extra_modules"] = [
                "generator_api.py"]
        edit_record(copied, _fix)
        try:
            out = verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a,
                deploy_root=run.deploy)
            assert out["collection_tests"] == _CANONICAL_TOTAL
        finally:
            extra.unlink()


class TestManifest:
    def test_manifest_row_tampered_refused(self, r17_canonical_full_run,
                                           tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "man")

        def _fix(doc):
            doc["test_files"][0]["deploy_sha256"] = "0" * 64
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_test_files_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_new_tree_candidate_refused_against_old_record(
            self, r17_canonical_full_run):
        run = r17_canonical_full_run
        root_test = run.repo / "stage2_6_1" / "tests" / "test_root.py"
        root_test.parent.mkdir(parents=True, exist_ok=True)
        root_test.write_text(
            "def test_root_a():\n    assert True\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(run.repo), "add", "-A"],
                       check=True)
        subprocess.run(["git", "-C", str(run.repo), "commit", "-qm",
                        "root"], check=True)
        new_head = subprocess.run(
            ["git", "-C", str(run.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        with pytest.raises(SubstanceError,
                           match="regression_evidence_commit_unbound"):
            verify_regression_evidence(
                run.record, run.repo, new_head)


# ------------- 同源零漂移(A08 既有防线) -------------

class TestSameSourceNoDrift:
    def test_candidate_test_map_equals_guard(self, tmp_path):
        guard = _guard_module()
        repo, commit_a, _parent = git_repo_with_candidate(tmp_path)
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


# ------------- 签发/消费端到端(A02/A07) -------------

class TestIssuerConsumerEndToEnd:
    """真实签发器子进程 + 真实消费端闸门,两端同源;运行目录为
    真实执行器产物;测试后清理许可副作用,不触正式部署面。"""

    def _cleanup(self, deploy: Path, state: Path) -> None:
        for path in (deploy / ".r17_formal_admission.json",
                     deploy / "r17_admission_issued.jsonl",
                     state / "r17_admission_consumed.jsonl"):
            path.unlink(missing_ok=True)

    def test_issue_then_consume_roundtrip(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        state = (run.deploy / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True, exist_ok=True)
        try:
            prereg = write_preregistration(
                run.base / "e2e_prereg.json", run.repo, run.commit_a,
                run.record, admission_id="e2e-aid-0001")
            proc = subprocess.run(
                [sys.executable, str(_issuer()), "--repo", str(run.repo),
                 "--deploy-root", str(run.deploy),
                 "--state-root", str(state),
                 "--commit-a", run.commit_a,
                 "--preregistration", str(prereg)],
                capture_output=True, text=True, timeout=300)
            assert proc.returncode == 0, proc.stdout + proc.stderr
            adm_path = run.deploy / ".r17_formal_admission.json"
            assert adm_path.is_file()
            from rl_curriculum.curriculum261_r17_admission import (
                enforce_formal_admission, validate_admission)
            ok, reason, adm = validate_admission(
                run.deploy, state, run.commit_a, str(run.repo))
            assert ok, reason
            # A07:证据原件替换(消费前)⇒ 同源复验必拒
            junit = run.run_dir / "junit.xml"
            original = junit.read_bytes()
            junit.write_bytes(original + b" ")
            ok2, reason2, _ = validate_admission(
                run.deploy, state, run.commit_a, str(run.repo))
            assert ok2 is False
            assert "regression_junit_sha_mismatch" in reason2
            junit.write_bytes(original)  # 还原后走正式消费路径
            assert enforce_formal_admission(
                state, run.commit_a, str(run.repo)) is None
            assert enforce_formal_admission(
                state, run.commit_a, str(run.repo)) == (
                "admission_already_consumed")
        finally:
            self._cleanup(run.deploy, state)

    def test_issuer_refuses_tampered_evidence_zero_side_effects(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "e2eneg")
        (copied / "junit.xml").write_bytes(
            (copied / "junit.xml").read_bytes() + b" ")
        state = (run.deploy / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True, exist_ok=True)
        try:
            prereg = write_preregistration(
                tmp_path / "e2eneg_prereg.json", run.repo,
                run.commit_a, record_path(copied),
                admission_id="e2e-aid-neg")
            proc = subprocess.run(
                [sys.executable, str(_issuer()),
                 "--repo", str(run.repo),
                 "--deploy-root", str(run.deploy),
                 "--state-root", str(state),
                 "--commit-a", run.commit_a,
                 "--preregistration", str(prereg)],
                capture_output=True, text=True, timeout=300)
            assert proc.returncode != 0
            assert "regression_junit_sha_mismatch" in (
                proc.stdout + proc.stderr)
            assert not (run.deploy /
                        ".r17_formal_admission.json").exists()
            assert not (run.deploy /
                        "r17_admission_issued.jsonl").exists()
        finally:
            self._cleanup(run.deploy, state)
