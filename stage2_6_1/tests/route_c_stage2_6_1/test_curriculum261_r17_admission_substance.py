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
    AUDIT_MANIFEST_FORMAT,
    FILTERING_HOOKS,
    GENERATION_HOOKS,
    HISTORICAL_SKIP_IDS,
    SubstanceError,
    candidate_hook_bindings,
    candidate_test_map,
    scan_hook_bindings,
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
    runner_repo_path,
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


def _proc_env() -> dict:
    """直驱执行器子进程的环境:剥离 pytest harness 自身的
    PYTEST_* 键(真实部署从 shell/监护入口启动时无这些键;
    执行器据此拒绝任何 PYTEST_* 环境污染)。"""
    return {k: v for k, v in os.environ.items()
            if not k.startswith("PYTEST_")}


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
                                 "mismatch|audit_collected_count_mismatch"):
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
                                 "mismatch|"
                                 "regression_audit_collected_count_"
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
                           match="regression_collection_static_mismatch|"
                                 "regression_audit_collected_count_"
                                 "mismatch"):
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
                               "-p", "r21_collection_auditor",
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
                5, "-k")
            doc["collection_run"]["runs"][0]["command"].insert(
                6, "ok")
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
                           match="regression_config_scan_mismatch|"
                                 "child_env_pythonpath_not_runner"):
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
                           match="regression_config_addopts_filter|"
                                 "child_env_pythonpath_not_runner"):
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
            capture_output=True, text=True, timeout=300,
            env=_proc_env())
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
            capture_output=True, text=True, timeout=300,
            env=_proc_env())
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
                         other=("cand.txt",),
                         run_dir: Path | None = None) -> None:
        """把 full record 原地改写为形状自洽的差分 record
        (protocol/差分块/两段 argv positionals=delta 目标;
        run_dir 在场时同步改写各 run 审计原件的 pytest_args,
        保持 v4 审计-argv 绑定自洽)。"""
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
                tail = []
                expect_value = False
                for tok in command[3:]:
                    if expect_value:
                        tail.append(tok)
                        expect_value = False
                    elif tok.startswith("-"):
                        tail.append(tok)
                        if tok.split("=", 1)[0] == "-p" \
                                and "=" not in tok:
                            expect_value = True
                entry["command"] = head + targets + tail
                if run_dir is not None and isinstance(
                        entry.get("audit"), dict):
                    audit_path = Path(run_dir) / entry["audit"]["path"]
                    audit_doc = json.loads(
                        audit_path.read_text(encoding="utf-8"))
                    audit_doc["pytest_args"] = entry["command"][3:]
                    audit_path.write_text(
                        json.dumps(audit_doc, indent=1, sort_keys=True,
                                   ensure_ascii=False) + "\n",
                        encoding="utf-8")
                    entry["audit"]["sha256"] = hashlib.sha256(
                        audit_path.read_bytes()).hexdigest()

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
                doc, run.parent, fake, [self._DELTA_TARGET],
                run_dir=copied)
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
                doc, run.parent, v2rec, [self._DELTA_TARGET],
                run_dir=copied)
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
                [self._DELTA_TARGET], other=("cand.txt",),
                run_dir=copied)
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


# ------------- R22:有效收集环境(A01-A09) -------------

def _audit_manifest(deploy: Path, approved: dict | None = None) -> dict:
    """手工构造运行期审计器用的 manifest(与执行器生成同形)。"""
    import hashlib as _hl
    auditor = deploy / "stage2_6_1_runner" / (
        "r21_collection_auditor.py")
    return {
        "format": AUDIT_MANIFEST_FORMAT,
        "filtering_hooks": sorted(FILTERING_HOOKS),
        "generation_hooks": sorted(GENERATION_HOOKS),
        "test_root": "tests/route_c_stage2_6_1",
        "auditor": {
            "module": "r21_collection_auditor",
            "sha256": _hl.sha256(auditor.read_bytes()).hexdigest()},
        "approved_generate_tests": approved or {},
    }


def _auditor_run_env(deploy: Path, manifest_path: Path,
                     out_path: Path, **extra: str) -> dict:
    """直接驱动 pytest + 审计器(不经执行器预检)的最小环境。"""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("PYTEST_")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONPATH"] = str(deploy / "stage2_6_1_runner")
    env["R21_AUDIT_MANIFEST"] = str(manifest_path)
    env["R21_AUDIT_OUT"] = str(out_path)
    env.update(extra)
    return env


class TestEffectiveCollectionA01:
    """审查反例迁移:导入式 pytest_pycollect_makeitem +
    LOCAL_QUICK_TESTS 门控(收集/执行一致缩减仍全绿)。"""

    @staticmethod
    def _hook_tree(tmp_path: Path):
        repo, commit_a, parent = git_repo_with_candidate(
            tmp_path, imported_hook=True)
        deploy = tmp_path / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        return repo, commit_a, deploy

    def test_counterexample_reproduced_without_defense(self, tmp_path):
        """无防护基线(审查数字迁移):同树同完整目录命令,门控
        使真实收集/执行 10 项含 1 失败 → 9 项全绿。"""
        _, _, deploy = self._hook_tree(tmp_path)

        def _collect(gated: bool):
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith("PYTEST_")}
            if gated:
                env["LOCAL_QUICK_TESTS"] = "1"
            proc = subprocess.run(
                [sys.executable, "-m", "pytest",
                 "tests/route_c_stage2_6_1", "--collect-only", "-q"],
                cwd=str(deploy), env=env, capture_output=True,
                text=True, timeout=300)
            return proc.stdout

        def _execute(gated: bool):
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith("PYTEST_")}
            if gated:
                env["LOCAL_QUICK_TESTS"] = "1"
            return subprocess.run(
                [sys.executable, "-m", "pytest",
                 "tests/route_c_stage2_6_1", "-q"],
                cwd=str(deploy), env=env, capture_output=True,
                text=True, timeout=300)

        full, gate = _collect(False), _collect(True)
        # 反例树 = 审查 probe_worktree + test_probe_plain_ok:
        # 11 项(1 failed/3 passed/7 skipped)→ 门控移除 [1] 后 10 项全绿。
        assert "11 tests collected" in full
        assert "10 tests collected" in gate
        proc_full = _execute(False)
        assert proc_full.returncode == 1
        assert "1 failed" in proc_full.stdout
        proc_gate = _execute(True)
        assert proc_gate.returncode == 0
        assert "failed" not in proc_gate.stdout

    def test_executor_preflight_rejects_imported_hook(self, tmp_path):
        """静态层:候选树 import 式钩子绑定在运行前被拒
        (regression_static_hook_binding, kind=import)。"""
        repo, commit_a, deploy = self._hook_tree(tmp_path)
        proc = subprocess.run(
            [sys.executable, str(executor_path()),
             "--repo", str(repo), "--commit-a", commit_a,
             "--deploy-root", str(deploy),
             "--out-dir", str(tmp_path / "refused"),
             "--substance-src", str(substance_src())],
            capture_output=True, text=True, timeout=300,
            env=_proc_env())
        assert proc.returncode != 0
        assert "regression_static_hook_binding" in (
            proc.stdout + proc.stderr)
        assert "import" in (proc.stdout + proc.stderr)
        assert not (tmp_path / "refused" / "summary.json").exists()

    def test_runtime_auditor_rejects_imported_hook(self, tmp_path):
        """运行期层(独立于预检):直接 -p 审计器 + 门控环境,
        实际注册的钩子实现来源分类失败 ⇒ 非 rc + 审计违规
        (来源归因到真实定义模块 selection_support.py)。"""
        _, _, deploy = self._hook_tree(tmp_path / "rt")
        manifest = tmp_path / "rt" / "manifest.json"
        manifest.write_text(json.dumps(_audit_manifest(deploy)),
                            encoding="utf-8")
        audit_out = tmp_path / "rt" / "audit.json"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-p",
             "r21_collection_auditor",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(deploy),
            env=_auditor_run_env(deploy, manifest, audit_out,
                                 LOCAL_QUICK_TESTS="1"),
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        document = json.loads(audit_out.read_text(encoding="utf-8"))
        assert document["verdict"] == "violations"
        kinds = {row["kind"] for row in document["violations"]}
        assert "guarded_hook_origin_unapproved" in kinds
        assert any("selection_support.py" in row.get("origin", "")
                   for row in document["violations"])

    def test_auditor_control_run_green(self, tmp_path):
        """对照正例:canonical 树 + 合法 generate_tests 批准,
        同一运行期审计全绿(动态参数化不受影响)。"""
        repo, commit_a, parent = git_repo_with_candidate(tmp_path)
        deploy = tmp_path / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        import hashlib as _hl
        conf = "tests/route_c_stage2_6_1/conftest.py"
        approved = {conf: _hl.sha256(
            (deploy / conf).read_bytes()).hexdigest()}
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(_audit_manifest(deploy, approved)),
                            encoding="utf-8")
        audit_out = tmp_path / "audit.json"
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-p",
             "r21_collection_auditor",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(deploy),
            env=_auditor_run_env(deploy, manifest, audit_out),
            capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0
        assert "8 passed" in proc.stdout and "7 skipped" in proc.stdout
        document = json.loads(audit_out.read_text(encoding="utf-8"))
        assert document["verdict"] == "pass"


class TestEffectiveCollectionA03:
    """A03:别名/包装/赋值/setattr/外部注册不得因非顶层同名 def 漏过。"""

    @pytest.mark.parametrize("source,kind", [
        ("from .sel import wrapped as pytest_pycollect_makeitem\n",
         "import"),
        ("pytest_pycollect_makeitem = _wrapper\n", "assign"),
        ("import sys\n"
         "setattr(sys.modules[__name__], "
         "'pytest_collection_modifyitems', fn)\n", "setattr"),
        ("class Plugin:\n"
         "    def pytest_ignore_collect(self, path, config):\n"
         "        return False\n", "def"),
    ])
    def test_binding_forms_detected(self, source, kind):
        rows = scan_hook_bindings(source.encode("utf-8"), "unit")
        assert rows and all(row["kind"] == kind for row in rows)

    def test_string_template_not_false_positive(self):
        """字符串模板内的 hook 名不是绑定(沙箱支撑模块合法)。"""
        rows = scan_hook_bindings(
            b'_T = """\ndef pytest_pycollect_makeitem(x):\n    pass\n"""\n',
            "unit")
        assert rows == []

    def test_generate_tests_requires_manifest_approval(self):
        """未批准的 pytest_generate_tests 在无 manifest 批准时
        被拒(fail closed);批准必须对应真实绑定。"""
        from rl_curriculum.curriculum261_r17_admission_substance \
            import evaluate_static_hook_policy
        source = b"def pytest_generate_tests(metafunc):\n    pass\n"
        rows = scan_hook_bindings(source, "unit")
        assert [r["hook"] for r in rows] == ["pytest_generate_tests"]
        with pytest.raises(SubstanceError,
                           match="generate_tests_unapproved"):
            evaluate_static_hook_policy(
                {"tests/route_c_stage2_6_1/conftest.py": rows}, {})

    def test_external_plugin_registration_rejected(self, tmp_path):
        """conftest 声明 pytest_plugins 加载树外模块(静态扫描
        干净)⇒ 运行期审计在真实链路拒绝(执行器非零 rc,审计
        plugin_unapproved,summary fail-closed)。"""
        repo, commit_a, parent = git_repo_with_candidate(tmp_path / "x")
        test_dir = repo / "stage2_6_1" / "tests" / "route_c_stage2_6_1"
        rogue = tmp_path / "rogue_plugin.py"
        rogue.write_text(
            "def pytest_pycollect_makeitem(collector, name, obj):\n"
            "    return None\n", encoding="utf-8")
        (test_dir / "conftest.py").write_text(
            "pytest_plugins = ['rogue_plugin']\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm",
                        "rogue"], check=True)
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        deploy = tmp_path / "x" / "deploy"
        sync_deploy_surface(repo, head, deploy)
        command = [sys.executable, str(executor_path()),
                   "--repo", str(repo), "--commit-a", head,
                   "--deploy-root", str(deploy),
                   "--out-dir", str(tmp_path / "x" / "run"),
                   "--substance-src", str(substance_src())]
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PYTEST_")}
        env["PYTHONPATH"] = str(tmp_path) + os.pathsep +             env.get("PYTHONPATH", "")
        proc = subprocess.run(command, capture_output=True, text=True,
                              timeout=300, env=env)
        assert proc.returncode != 0
        run_dir = tmp_path / "x" / "run"
        summary = json.loads(
            (run_dir / "summary.json").read_text(encoding="utf-8"))
        assert not summary.get("ok")
        audit_path = run_dir / "audit_collection.json"
        if audit_path.is_file():
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            assert audit["verdict"] == "violations"
            kinds = {row["kind"] for row in audit["violations"]}
            assert "plugin_unapproved" in kinds or \
                "guarded_hook_origin_unapproved" in kinds


class TestEffectiveCollectionA02A05:
    """v5 record 的审计/环境/生命周期受控面正反例(canonical
    真实 run)。"""

    def test_v5_blocks_env_and_audit_format(self, r17_canonical_full_run):
        run = r17_canonical_full_run
        doc = read_record(run.run_dir)
        assert doc["format"] == (
            "cur261-r17-candidate-regression-evidence-v6")
        manifest_sha = hashlib.sha256(
            (run.run_dir / doc["audit_manifest"]["path"]).read_bytes()
        ).hexdigest()
        assert manifest_sha == doc["audit_manifest"]["sha256"]
        face = doc["run"]["executor_face"]
        assert face["executor"]["source_path"] == (
            "stage2_6_1/runner/r21_full_collection_regression.py")
        assert face["auditor"]["source_path"] == (
            "stage2_6_1/runner/r21_collection_auditor.py")
        for block in (doc["collection_run"]["runs"]
                      + doc["execution"]["runs"]):
            audit = json.loads(
                (run.run_dir / block["audit"]["path"]).read_text(
                    encoding="utf-8"))
            assert audit["format"] == (
                "cur261-r24-collection-audit-v3")
            assert audit["verdict"] == "pass"
            assert [s["stage"] for s in audit["stages"]] == [
                "configure", "collection_finish", "sessionfinish"]
            child = block["env"]["child_env"]
            assert "PYTEST_ADDOPTS" not in child
            assert "PYTEST_PLUGINS" not in child
            assert child["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
            assert child["PYTHONPATH"].replace("\\", "/").endswith(
                "stage2_6_1_runner")
            policy = block["env"]["child_env_policy"]
            assert set(policy["forced"]) == {
                "PYTHONDONTWRITEBYTECODE",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONPATH",
                "R21_AUDIT_OUT", "R21_AUDIT_MANIFEST"}

    def test_unknown_env_keys_not_inherited(
            self, r17_canonical_full_run, monkeypatch, tmp_path):
        """环境控制:ambient LOCAL_QUICK_TESTS 不进入子进程环境,
        运行不受影响(白名单继承)。"""
        run = r17_canonical_full_run
        monkeypatch.setenv("LOCAL_QUICK_TESTS", "1")
        run_dir, summary, rc = run_executor(
            tmp_path / "env_run", run.repo, run.commit_a, run.deploy,
            expect_rc=(0,))
        assert rc == 0 and summary["ok"]
        doc = read_record(run_dir)
        for block in (doc["collection_run"]["runs"]
                      + doc["execution"]["runs"]):
            assert "LOCAL_QUICK_TESTS" not in block["env"]["child_env"]
            assert "LOCAL_QUICK_TESTS" in block["env"][
                "child_env_policy"]["dropped_keys"]

    def test_ambient_pytest_env_refused(self, r17_canonical_full_run,
                                        tmp_path):
        run = r17_canonical_full_run
        env = _proc_env()
        env["PYTEST_ADDOPTS"] = "-k ok"
        proc = subprocess.run(
            [sys.executable, str(executor_path()),
             "--repo", str(run.repo), "--commit-a", run.commit_a,
             "--deploy-root", str(run.deploy),
             "--out-dir", str(tmp_path / "refused"),
             "--substance-src", str(substance_src())],
            capture_output=True, text=True, timeout=300, env=env)
        assert proc.returncode != 0
        assert "PYTEST_" in (proc.stdout + proc.stderr)

    def test_audit_block_removed_refused(self, r17_canonical_full_run,
                                         tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "noaudit")

        def _fix(doc):
            del doc["collection_run"]["runs"][0]["audit"]
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="regression_collection_run_audit_"
                                 "block_missing"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_audit_verdict_violations_refused(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "vd")
        path = copied / "audit_collection.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["verdict"] = "violations"
        document["violations"] = [{"kind": "forged"}]
        path.write_text(json.dumps(document, indent=1, sort_keys=True),
                        encoding="utf-8")
        rehash_artifact(copied, "audit_collection.json")
        with pytest.raises(SubstanceError,
                           match="regression_collection_run_audit_"
                                 "verdict_not_pass"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_audit_stage_missing_refused(self, r17_canonical_full_run,
                                         tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "stage")
        path = copied / "audit_execution.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["stages"] = document["stages"][:2]
        path.write_text(json.dumps(document, indent=1, sort_keys=True),
                        encoding="utf-8")
        rehash_artifact(copied, "audit_execution.json")
        with pytest.raises(SubstanceError,
                           match="regression_execution_run0_audit_"
                                 "stages_invalid"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_manifest_phantom_approval_refused(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "ph")
        path = copied / "audit_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["approved_generate_tests"][
            "tests/route_c_stage2_6_1/test_sandbox.py"] = "0" * 64
        path.write_text(json.dumps(manifest, indent=1, sort_keys=True),
                        encoding="utf-8")
        rehash_artifact(copied, "audit_manifest.json")
        with pytest.raises(SubstanceError, match="phantom_approval"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)


class TestEffectiveCollectionA06:
    """新签发必须绑定 v5(有效收集环境受控 + 插件生命周期覆盖)
    证据;v4/v3 历史 record 可核验但不可用于新签发。"""

    @staticmethod
    def _issuer_run(run, deploy, evidence, tmp_path, tag):
        state = deploy / "artifacts" / "route_c_stage2_6_1_repair18" \
            / "state"
        state.mkdir(parents=True, exist_ok=True)
        prereg = tmp_path / f"prereg_{tag}.json"
        write_preregistration(prereg, run.repo, run.commit_a, evidence)
        return subprocess.run(
            [sys.executable, str(_issuer()), "--repo", str(run.repo),
             "--deploy-root", str(deploy), "--state-root", str(state),
             "--commit-a", run.commit_a,
             "--preregistration", str(prereg)],
            capture_output=True, text=True, timeout=300)

    def test_issuer_refuses_v3_format_record(
            self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "v3")

        def _fix(doc):
            doc["format"] = "cur261-r17-candidate-regression-evidence-v3"
            doc["run"].pop("executor_face", None)
            doc["run"].pop("supervision", None)
            doc.pop("audit_manifest", None)
            for block_key in ("collection_run", "execution"):
                for entry in doc[block_key]["runs"]:
                    entry.pop("audit", None)
                    entry.pop("audit_lifecycle", None)
                    entry["env"].pop("child_env", None)
                    entry["env"].pop("child_env_policy", None)
                    kept = []
                    skip = False
                    for tok in entry["command"][3:]:
                        if skip:
                            skip = False
                            continue
                        if tok == "-p":
                            skip = True
                            continue
                        kept.append(tok)
                    entry["command"] = entry["command"][:3] + kept
        edit_record(copied, _fix)
        # v3 历史核验面仍可核验(父链递归用途;不可用于新签发)
        verify_regression_evidence(
            record_path(copied), run.repo, run.commit_a)
        proc = self._issuer_run(run, run.deploy, record_path(copied),
                                tmp_path, "v3")
        assert proc.returncode != 0
        assert "format v6" in (proc.stdout + proc.stderr)
        assert not (run.deploy / ".r17_formal_admission.json").exists()

    def test_issuer_refuses_v4_format_record_for_new_issuance(
            self, r17_canonical_full_run, tmp_path):
        """v4(无生命周期段)历史形状:同源核验器按 v4 历史面接受
        不可;此处只证明签发器对"新签发"要求 v6——把 record 格式
        字段改为 v4 即拒,零副作用。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "v4")

        def _fix(doc):
            doc["format"] = "cur261-r17-candidate-regression-evidence-v4"
        edit_record(copied, _fix)
        proc = self._issuer_run(run, run.deploy, record_path(copied),
                                tmp_path, "v4")
        assert not (run.deploy / "r17_admission_issued.jsonl").exists()


class TestPluginLifecycleR23:
    """R23/102e9b2 审查反例迁移(A01-A05):sessionstart 注册
    specname 别名临时插件 → 实际过滤 → collection_finish tryfirst
    注销;v5 注册通知使违规事实不可清除,签发/消费链继承拒绝。"""

    @staticmethod
    def _scoped_tree(tmp: Path):
        repo, commit_a, parent = git_repo_with_candidate(
            tmp, scoped=True)
        deploy = tmp / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        return repo, commit_a, deploy

    def test_no_defense_baseline_reproduced(self, tmp_path):
        """无防护基线(审查对照形状):同测试正文、无插件 conftest
        的对照树 11 项含 1 失败;scoped 树(sessionstart 注册临时
        插件)收集/执行一致 10 项全绿(rc=0)。"""
        repo, commit_a, _ = git_repo_with_candidate(tmp_path, probe=True)
        control = tmp_path / "control"
        sync_deploy_surface(repo, commit_a, control)
        env = _proc_env()
        collect = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "--collect-only", "-q"],
            cwd=str(control), env=env, capture_output=True, text=True,
            timeout=300)
        assert "11 tests collected" in collect.stdout
        control_run = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(control), env=env, capture_output=True, text=True,
            timeout=300)
        assert control_run.returncode == 1
        assert "1 failed" in control_run.stdout

        _, _, scoped_deploy = self._scoped_tree(tmp_path / "scoped")
        scoped_collect = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "--collect-only", "-q"],
            cwd=str(scoped_deploy), env=env, capture_output=True,
            text=True, timeout=300)
        assert "10 tests collected" in scoped_collect.stdout
        scoped_run = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(scoped_deploy), env=env, capture_output=True,
            text=True, timeout=300)
        assert scoped_run.returncode == 0
        assert "3 passed" in scoped_run.stdout
        assert "failed" not in scoped_run.stdout
        events = [
            json.loads(line) for line in
            (scoped_deploy / "scoped_plugin_events.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
        assert [row["event"] for row in events][-3:] == [
            "registered", "filtered", "unregistered"]

    def test_executor_refuses_scoped_temp_plugin(self, tmp_path):
        """真实执行器 + 审计器:收集 rc=0(10 项全绿)但审计
        verdict=violations ⇒ summary fail-closed、rc=3、核验器拒。
        "测试 rc=0 但审计不合格"不得被写成 full PASS。"""
        repo, commit_a, deploy = self._scoped_tree(tmp_path)
        run_dir, summary, rc = run_executor(
            tmp_path / "run", repo, commit_a, deploy, expect_rc=(3,))
        assert rc == 3
        assert summary["ok"] is False
        assert "audit_verdict_not_pass" in summary.get("error", "")
        collection = (run_dir / "collection.stdout.txt").read_text(
            encoding="utf-8")
        assert "10 tests collected" in collection  # 过滤确实生效
        audit = json.loads(
            (run_dir / "audit_collection.json").read_text(
                encoding="utf-8"))
        assert audit["verdict"] == "violations"
        lifecycle = audit["lifecycle"]
        kinds = {row["kind"] for row in lifecycle["violations"]}
        assert "lifecycle_guarded_hook_registration" in kinds
        events = lifecycle["events"]
        scoped = [event for event in events
                  if event["plugin_name"] == "scoped_collection"]
        assert len(scoped) == 1
        assert scoped[0]["classification"] == "unapproved"
        assert "pytest_pycollect_makeitem" in scoped[0]["guarded_hooks"]
        stream = [
            json.loads(line) for line in
            (run_dir / "audit_collection.json.lifecycle.jsonl"
             ).read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(row.get("kind") == "violation"
                   and row.get("violation", {}).get("plugin_name")
                   == "scoped_collection"
                   for row in stream)
        with pytest.raises(SubstanceError,
                           match="audit_verdict_not_pass"):
            verify_regression_evidence(
                record_path(run_dir), repo, commit_a)

    def test_violation_facts_unclearable_from_document(
            self, r17_canonical_full_run, tmp_path):
        """A02(文档侧清除):向 append-only 流水注入一条违规(并重绑
        流水 sha),再把审计文档保持"干净"——文档与流水不一致 ⇒
        核验器拒。等价于 scoped 运行后从文档删违规:流水为真。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "streaminject")
        stream_path = copied / "audit_collection.json.lifecycle.jsonl"
        injected = {"kind": "violation",
                    "type": "lifecycle_guarded_hook_registration",
                    "plugin_name": "scoped_collection"}
        with open(stream_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(injected, sort_keys=True,
                                    ensure_ascii=False) + "\n")
        rehash_artifact(copied, "audit_collection.json.lifecycle.jsonl")
        with pytest.raises(SubstanceError,
                           match="lifecycle_stream_violations_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_document_violation_without_stream_refused(
            self, r17_canonical_full_run, tmp_path):
        """A02(反向):只在文档里补违规、流水没有 ⇒ 同样拒——
        两侧必须严格一致,不存在单向补写通道。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "docinject")
        audit_path = copied / "audit_collection.json"
        doc = json.loads(audit_path.read_text(encoding="utf-8"))
        doc["lifecycle"]["violations"].append({
            "kind": "lifecycle_unapproved_registration",
            "plugin_name": "scoped_collection", "origin": "x"})
        audit_path.write_text(
            json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n", encoding="utf-8")
        rehash_artifact(copied, "audit_collection.json")
        with pytest.raises(SubstanceError,
                           match="audit_lifecycle_violations"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_scoped_run_final_snapshot_clean_but_refused(
            self, tmp_path):
        """A02(原件路径):scoped 运行的 sessionfinish 快照中已无
        临时插件(注销生效),仍拒绝;直接读运行原件断言。"""
        repo, commit_a, deploy = self._scoped_tree(tmp_path / "x")
        run_dir, summary, rc = run_executor(
            tmp_path / "x" / "run", repo, commit_a, deploy,
            expect_rc=(3,))
        audit = json.loads(
            (run_dir / "audit_collection.json").read_text(
                encoding="utf-8"))
        final = audit["stages"][-1]["snapshot"]["plugins"]
        names = [row.get("plugin_name") for row in final]
        assert "scoped_collection" not in names
        assert audit["verdict"] == "violations"
        assert any(event["plugin_name"] == "scoped_collection"
                   for event in audit["lifecycle"]["events"])

    def test_lifecycle_events_cover_early_and_late(
            self, r17_canonical_full_run):
        """A03:监测经 historic 重放覆盖启动前注册(核心插件全量
        事件),configure 对账 uncovered 为空;晚注册(session 等
        核心对象)亦分类为 core,不误拒。"""
        run = r17_canonical_full_run
        doc = read_record(run.run_dir)
        audit = json.loads(
            (run.run_dir / doc["collection_run"]["runs"][0]["audit"][
                "path"]).read_text(encoding="utf-8"))
        lifecycle = audit["lifecycle"]
        events = lifecycle["events"]
        assert events, "monitor must be established"
        assert lifecycle["monitor"]["hook"] == \
            "pytest_plugin_registered"
        assert lifecycle["reconcile"]["uncovered"] == []
        classes = {event["classification"] for event in events}
        assert classes <= {"core", "auditor", "conftest"}
        assert "core" in classes and "conftest" in classes
        conftest_seq = max(event["seq"] for event in events
                           if event["classification"] == "conftest")
        assert any(event["classification"] == "core"
                   and event["seq"] > conftest_seq
                   for event in events), "late core registration covered"
        # 判定与流水一致
        assert audit["verdict"] == "pass"
        stream = [
            json.loads(line) for line in
            (run.run_dir / (doc["collection_run"]["runs"][0][
                "audit"]["path"] + ".lifecycle.jsonl")).read_text(
                encoding="utf-8").splitlines() if line.strip()]
        assert stream[0]["kind"] == "monitor"
        assert len([row for row in stream
                    if row["kind"] == "event"]) == len(events)

    def test_missing_lifecycle_section_refused(
            self, r17_canonical_full_run, tmp_path):
        """A03(fail closed):v5 record 的审计原件缺生命周期段
        ⇒ 核验器拒绝(兼容入口不为新候选提供本轮保证)。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "nolc")
        audit_path = copied / "audit_collection.json"
        doc = json.loads(audit_path.read_text(encoding="utf-8"))
        doc.pop("lifecycle", None)
        audit_path.write_text(
            json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n", encoding="utf-8")
        rehash_artifact(copied, "audit_collection.json")
        with pytest.raises(SubstanceError,
                           match="lifecycle_missing"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_audit_format_v1_refused_for_v5_record(
            self, r17_canonical_full_run, tmp_path):
        """v5 record 内审计原件必须是 v2 格式(旧 v1 快照式审计
        不能为新候选供证)。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "v1fmt")
        audit_path = copied / "audit_collection.json"
        doc = json.loads(audit_path.read_text(encoding="utf-8"))
        doc["format"] = "cur261-r22-collection-audit-v1"
        audit_path.write_text(
            json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n", encoding="utf-8")
        rehash_artifact(copied, "audit_collection.json")
        with pytest.raises(SubstanceError,
                           match="audit_format_invalid"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_record_format_v5_and_stream_bound(
            self, r17_canonical_full_run):
        """A05 前置:canonical 真实运行的 record/审计原件/流水
        绑定面(合法路径全绿——动态参数化、已批准生成钩子、正常
        核心晚注册不受影响)。"""
        run = r17_canonical_full_run
        doc = read_record(run.run_dir)
        assert doc["format"] == (
            "cur261-r17-candidate-regression-evidence-v6")
        for block in (doc["collection_run"]["runs"]
                      + doc["execution"]["runs"]):
            stream = block.get("audit_lifecycle")
            assert isinstance(stream, dict)
            path = run.run_dir / stream["path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == \
                stream["sha256"]



class TestPartialRegistrationR24:
    """R24/d872f41 审查反例迁移(A01-A06):register() 抛异常但
    先前 hookimpl 已装入(部分安装)——v5 成功通知零事件;v6
    注册边界守卫按实际对象核查并粘住违规,早拒/清理/回滚不可清除,
    真实前置失败如实留痕不阻断。"""

    @staticmethod
    def _partial_tree(tmp: Path, variant: str):
        repo, commit_a, parent = git_repo_with_candidate(
            tmp, partial=variant)
        deploy = tmp / "deploy"
        sync_deploy_surface(repo, commit_a, deploy)
        return repo, commit_a, deploy

    def test_no_defense_baseline_reproduced(self, tmp_path):
        """A01(审查原件迁移,目标环境):对照树 11 项含 1 失败;
        partial 树 register 抛 PluginValidationError 被捕获后对象
        仍在册、filter 仍活跃,收集/执行一致 10 项全绿(rc=0);
        conftest 事件原件复刻审查 plugin_events 形状。"""
        env = _proc_env()
        repo, commit_a, _ = git_repo_with_candidate(tmp_path, probe=True)
        control = tmp_path / "control"
        sync_deploy_surface(repo, commit_a, control)
        collect = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "--collect-only", "-q"],
            cwd=str(control), env=env, capture_output=True, text=True,
            timeout=300)
        assert "11 tests collected" in collect.stdout
        _, _, deploy = self._partial_tree(tmp_path / "late", "late")
        partial_collect = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "--collect-only", "-q"],
            cwd=str(deploy), env=env, capture_output=True, text=True,
            timeout=300)
        assert "10 tests collected" in partial_collect.stdout
        partial_run = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(deploy), env=env, capture_output=True, text=True,
            timeout=300)
        assert partial_run.returncode == 0
        assert "3 passed" in partial_run.stdout
        assert "failed" not in partial_run.stdout
        events = [
            json.loads(line) for line in
            (deploy / "partial_plugin_events.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
        kinds = [row["event"] for row in events]
        caught = next(row for row in events
                      if row["event"] == "registration_exception_caught")
        assert caught["error_type"] == "PluginValidationError"
        assert caught["remains_registered"] is True
        assert caught["active_filter"] is True
        assert kinds[-3:] == [
            "registration_exception_caught", "filter_called",
            "unregistered"]

    def test_executor_refuses_partial_registration(self, tmp_path):
        """A02(迁移到真实执行链):收集 rc=0(10 项全绿)但审计
        verdict=violations ⇒ summary fail-closed、rc=3、同源核验器
        拒;违规含部分装入的两个实际 hook 与异常类型。"""
        repo, commit_a, deploy = self._partial_tree(tmp_path, "late")
        run_dir, summary, rc = run_executor(
            tmp_path / "run", repo, commit_a, deploy, expect_rc=(3,))
        assert rc == 3
        assert summary["ok"] is False
        assert "audit_verdict_not_pass" in summary.get("error", "")
        collection = (run_dir / "collection.stdout.txt").read_text(
            encoding="utf-8")
        assert "10 tests collected" in collection  # 过滤确实生效
        audit = json.loads(
            (run_dir / "audit_collection.json").read_text(
                encoding="utf-8"))
        assert audit["verdict"] == "violations"
        assert [s["stage"] for s in audit["stages"]] == [
            "configure", "collection_finish", "sessionfinish"]
        violations = audit["lifecycle"]["violations"]
        assert any(v["kind"] ==
                   "lifecycle_registration_exception_partial_install"
                   and set(v["hooks"]) == {
                       "pytest_pycollect_makeitem",
                       "pytest_collection_finish"}
                   and v["error_type"] == "PluginValidationError"
                   for v in violations)
        exc_events = [event for event in audit["lifecycle"]["events"]
                      if event.get("phase") == "registration_exception"]
        assert len(exc_events) == 1
        assert exc_events[0]["classification"] == "unapproved"
        assert exc_events[0]["remains_registered"] is True
        stream = [
            json.loads(line) for line in
            (run_dir / "audit_collection.json.lifecycle.jsonl"
             ).read_text(encoding="utf-8").splitlines() if line.strip()]
        assert any(row.get("kind") == "violation"
                   and row["violation"]["kind"] ==
                   "lifecycle_registration_exception_partial_install"
                   for row in stream)
        assert sum(1 for row in stream
                   if row.get("kind") == "register_guard") == 1
        with pytest.raises(SubstanceError,
                           match="audit_verdict_not_pass"):
            verify_regression_evidence(
                record_path(run_dir), repo, commit_a)

    def test_immediate_cleanup_violation_stuck(self, tmp_path):
        """A03(异常后立即清理):捕获后立刻公开注销,过滤从未
        发生(收集完整、失败实例如实在场)——已发生的"未获准
        实现曾装入"事实不可被清理抹掉;执行器按实际形状拒绝,
        审计违规仍在。"""
        repo, commit_a, deploy = self._partial_tree(
            tmp_path, "immediate")
        env = _proc_env()
        raw = subprocess.run(
            [sys.executable, "-m", "pytest",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(deploy), env=env, capture_output=True, text=True,
            timeout=300)
        assert raw.returncode == 1  # 过滤未发生:失败参数实例在场
        assert "1 failed" in raw.stdout
        run_dir, summary, rc = run_executor(
            tmp_path / "run", repo, commit_a, deploy, expect_rc=(3, 4))
        assert rc != 0 and summary["ok"] is False
        audit = json.loads(
            (run_dir / "audit_collection.json").read_text(
                encoding="utf-8"))
        assert audit["verdict"] == "violations"
        kinds = {v["kind"] for v in audit["lifecycle"]["violations"]}
        assert "lifecycle_registration_exception_partial_install" \
            in kinds
        events = [
            json.loads(line) for line in
            (deploy / "partial_plugin_events.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
        assert [row["event"] for row in events][-2:] == [
            "registration_exception_caught", "cleaned_up"]
        with pytest.raises(SubstanceError):
            verify_regression_evidence(
                record_path(run_dir), repo, commit_a)

    def test_zero_install_residue_refused(self, tmp_path):
        """A03(零装入残留):树本身全绿,唯一异常是未获准对象
        注册失败后残留注册表——unclean 违规,rc=3,不因"没装入
        任何实现"放行。"""
        repo, commit_a, deploy = self._partial_tree(tmp_path, "zero")
        run_dir, summary, rc = run_executor(
            tmp_path / "run", repo, commit_a, deploy, expect_rc=(3,))
        assert rc == 3
        assert summary["ok"] is False
        audit = json.loads(
            (run_dir / "audit_collection.json").read_text(
                encoding="utf-8"))
        violations = audit["lifecycle"]["violations"]
        assert any(v["kind"] ==
                   "lifecycle_registration_exception_unclean"
                   and v["remains_registered"] is True
                   for v in violations)
        exc_events = [event for event in audit["lifecycle"]["events"]
                      if event.get("phase") == "registration_exception"]
        assert exc_events[0]["installed_hooks"] == []  # 不伪造参与

    def test_pre_insertion_failure_eligible(self, tmp_path):
        """A03(真实前置失败,不阻断不伪造):重名 ValueError 在写
        注册表前抛出 ⇒ rejected 事件(未入册/零装入)如实留痕,
        树保持合法,full 运行与核验全绿——守卫不无差别打击一切
        注册异常。"""
        repo, commit_a, deploy = self._partial_tree(
            tmp_path, "rejected")
        run_dir, summary, rc = run_executor(
            tmp_path / "run", repo, commit_a, deploy, expect_rc=(0,))
        assert rc == 0 and summary["ok"] is True
        for stem in ("audit_collection.json", "audit_execution.json"):
            audit = json.loads(
                (run_dir / stem).read_text(encoding="utf-8"))
            assert audit["verdict"] == "pass"
            exc_events = [event
                          for event in audit["lifecycle"]["events"]
                          if event.get("phase")
                          == "registration_exception"]
            assert len(exc_events) == 1
            assert exc_events[0]["classification"] == "rejected"
            assert exc_events[0]["remains_registered"] is False
            assert exc_events[0]["installed_hooks"] == []
        result = verify_regression_evidence(
            record_path(run_dir), repo, commit_a)
        assert result["collection_tests"] > 0

    def test_v6_guard_bound_in_canonical_run(
            self, r17_canonical_full_run):
        """A04/A05 正例:合法 canonical 运行的每段审计都携带
        register_guard 证明段(文档+流水一致),核心/合法参数化
        不受守卫影响。"""
        run = r17_canonical_full_run
        doc = read_record(run.run_dir)
        assert doc["format"] == (
            "cur261-r17-candidate-regression-evidence-v6")
        for block in (doc["collection_run"]["runs"]
                      + doc["execution"]["runs"]):
            audit = json.loads(
                (run.run_dir / block["audit"]["path"]).read_text(
                    encoding="utf-8"))
            guard = audit["lifecycle"]["register_guard"]
            assert isinstance(guard, dict)
            assert guard["wrapped_hook"] == "register"
            assert guard["manager_class"] == "PytestPluginManager"
            assert guard["installed_utc"]
            stream = [
                json.loads(line) for line in
                (run.run_dir / (block["audit"]["path"]
                                + ".lifecycle.jsonl")).read_text(
                    encoding="utf-8").splitlines() if line.strip()]
            guard_rows = [row for row in stream
                          if row.get("kind") == "register_guard"]
            assert len(guard_rows) == 1
            assert {key: value for key, value
                    in guard_rows[0].items() if key != "kind"} == guard

    def test_guard_missing_from_document_refused(
            self, r17_canonical_full_run, tmp_path):
        """A05(守卫缺失):从审计文档删 register_guard 段 ⇒
        v6 核验拒绝;不能回退成仅旧成功注册事件/末尾快照通过。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "noguard")
        audit_path = copied / "audit_collection.json"
        doc = json.loads(audit_path.read_text(encoding="utf-8"))
        doc["lifecycle"]["register_guard"] = None
        audit_path.write_text(
            json.dumps(doc, indent=1, ensure_ascii=False, sort_keys=True)
            + "\n", encoding="utf-8")
        rehash_artifact(copied, "audit_collection.json")
        with pytest.raises(SubstanceError,
                           match="register_guard_invalid"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_guard_stream_mismatch_refused(
            self, r17_canonical_full_run, tmp_path):
        """A05(证明不一致):文档 guard 保留、流水补写第二条
        register_guard 行 ⇒ 两侧不一致拒(单侧补写无通道)。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "guarddup")
        stream_path = copied / "audit_collection.json.lifecycle.jsonl"
        with open(stream_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(
                {"kind": "register_guard", "wrapped_hook": "register",
                 "manager_class": "PytestPluginManager",
                 "installed_utc": "1970-01-01T00:00:00Z", "pid": 1},
                sort_keys=True, ensure_ascii=False) + "\n")
        rehash_artifact(
            copied, "audit_collection.json.lifecycle.jsonl")
        with pytest.raises(SubstanceError,
                           match="register_guard_stream_mismatch"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_old_v5_shape_historical_face_only(
            self, r17_canonical_full_run, tmp_path):
        """A05(兼容边界):v5 形状(record v5+审计 v2)仍走历史
        核验面可核验(父链递归用),但缺新防线证明不可为新候选
        供证——新签发要求 v6(见签发侧测试)。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "v5shape")

        def _downgrade(record: dict) -> None:
            record["format"] = (
                "cur261-r17-candidate-regression-evidence-v5")
        edit_record(copied, _downgrade)
        for stem in ("audit_collection.json", "audit_execution.json"):
            audit_path = copied / stem
            doc = json.loads(audit_path.read_text(encoding="utf-8"))
            doc["format"] = "cur261-r23-collection-audit-v2"
            audit_path.write_text(
                json.dumps(doc, indent=1, ensure_ascii=False,
                           sort_keys=True) + "\n", encoding="utf-8")
            rehash_artifact(copied, stem)
        result = verify_regression_evidence(
            record_path(copied), run.repo, run.commit_a)
        assert result["collection_tests"] > 0  # 历史核验面

    def test_auditor_write_failure_fails_closed(self, tmp_path):
        """A05(记录写失败):R21_AUDIT_OUT 指向不存在目录 ⇒
        无 verdict=pass 文档、运行非零(fail closed,不静默)。"""
        _, _, deploy = self._partial_tree(tmp_path / "c", "rejected")
        manifest = tmp_path / "c" / "manifest.json"
        manifest.write_text(
            json.dumps(_audit_manifest(deploy)), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-p",
             "r21_collection_auditor",
             "tests/route_c_stage2_6_1", "-q"],
            cwd=str(deploy),
            env=_auditor_run_env(
                deploy, manifest,
                tmp_path / "missing_dir" / "audit.json"),
            capture_output=True, text=True, timeout=300)
        assert proc.returncode != 0
        assert not (tmp_path / "missing_dir" / "audit.json").exists()

    def test_guard_not_installable_violation(self, tmp_path):
        """A05(守卫不可装):管理器实例拒绝属性写入 ⇒
        register_guard_not_installable 违规(fail closed 分支)。"""
        import importlib.util as _ilu
        auditor = runner_repo_path("r21_collection_auditor.py")
        spec = _ilu.spec_from_file_location(
            "r21_auditor_unit", auditor)
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)

        class RigidManager:
            __slots__ = ()

        guard = module._install_register_guard(RigidManager())
        assert guard is None
        kinds = [v["kind"] for v in module._STATE["violations"]]
        assert "register_guard_not_installable" in kinds

    def test_independent_manager_not_polluted(self):
        """A04(隔离):测试自建的独立 pluggy 管理器触发同类
        PluginValidationError 不触碰父运行收集管理器(守卫仅包
        本次运行的实际管理器实例);受监护全量中父审计保持零
        违规即为本测试通过的前提。"""
        import pluggy
        from _pytest.config import PytestPluginManager

        class Independent:
            @pytest.hookimpl(specname="pytest_configure")
            def pytest_z_invalid(self, not_a_pytest_argument):
                pass

        manager = PytestPluginManager()  # 独立实例,非父运行管理器
        with pytest.raises(pluggy.PluginValidationError):
            manager.register(Independent(), "independent_bad")
        auditor = sys.modules.get("r21_collection_auditor")
        if auditor is not None:  # 受监护运行中在进程内可直接核验
            assert not auditor._STATE["violations"]
            guard = auditor._STATE["lifecycle"]["register_guard"]
            assert guard and guard["wrapped_hook"] == "register"

    def _issuer_neg(self, repo, commit_a, deploy, record, tmp,
                    admission_id):
        """A06 公共负例驱动:真签发器子进程 + 前后沙箱状态。"""
        state = (deploy / "artifacts" /
                 "route_c_stage2_6_1_repair18" / "state")
        state.mkdir(parents=True, exist_ok=True)
        try:
            prereg = write_preregistration(
                tmp / "prereg.json", repo, commit_a, record,
                admission_id=admission_id)
            proc = subprocess.run(
                [sys.executable, str(_issuer()), "--repo", str(repo),
                 "--deploy-root", str(deploy),
                 "--state-root", str(state),
                 "--commit-a", commit_a,
                 "--preregistration", str(prereg)],
                capture_output=True, text=True, timeout=300)
            side = {
                "admission_file":
                    (deploy / ".r17_formal_admission.json").exists(),
                "issuance_log":
                    (deploy / "r17_admission_issued.jsonl").exists(),
            }
            return proc, side
        finally:
            for path in (deploy / ".r17_formal_admission.json",
                         deploy / "r17_admission_issued.jsonl",
                         state / "r17_admission_consumed.jsonl"):
                path.unlink(missing_ok=True)

    def test_issuer_refuses_partial_registration_evidence(
            self, tmp_path):
        """A06:部分注册异常产生的坏材料(真实执行器 rc=3 产物)
        被真签发器拒,零许可写入/零成功签发副作用。"""
        repo, commit_a, deploy = self._partial_tree(
            tmp_path / "late", "late")
        run_dir, summary, rc = run_executor(
            tmp_path / "late" / "run", repo, commit_a, deploy,
            expect_rc=(3,))
        assert rc == 3 and summary["ok"] is False
        proc, side = self._issuer_neg(
            repo, commit_a, deploy, record_path(run_dir),
            tmp_path / "late", "r24-partial-neg")
        assert proc.returncode != 0
        message = proc.stdout + proc.stderr
        assert ("audit_verdict_not_pass" in message
                or "substance verification failed" in message), message
        assert side == {"admission_file": False,
                                       "issuance_log": False}

    def test_issuer_refuses_v5_shape_for_new_issuance(
            self, r17_canonical_full_run, tmp_path):
        """A06(版本边界):v5 形状(缺注册守卫证明)可历史核验
        但不可为新候选供证——真签发器拒,零副作用。"""
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "v5issue")

        def _downgrade(record: dict) -> None:
            record["format"] = (
                "cur261-r17-candidate-regression-evidence-v5")
        edit_record(copied, _downgrade)
        for stem in ("audit_collection.json", "audit_execution.json"):
            audit_path = copied / stem
            doc = json.loads(audit_path.read_text(encoding="utf-8"))
            doc["format"] = "cur261-r23-collection-audit-v2"
            audit_path.write_text(
                json.dumps(doc, indent=1, ensure_ascii=False,
                           sort_keys=True) + "\n", encoding="utf-8")
            rehash_artifact(copied, stem)
        verify_regression_evidence(
            record_path(copied), run.repo, run.commit_a)  # 历史面过
        proc, side = self._issuer_neg(
            run.repo, run.commit_a, run.deploy, record_path(copied),
            tmp_path / "v5issue", "r24-v5shape-neg")
        assert proc.returncode != 0
        assert "evidence format v6" in (proc.stdout + proc.stderr)
        assert side == {"admission_file": False,
                                       "issuance_log": False}



class TestSupervisionLinkA08:
    """v4 外层监护关联:声明的 run 必须能在 run_supervision
    运行史中按 argv token 定位;伪造关联拒。"""

    def test_bogus_link_refused(self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "bogus")

        def _fix(doc):
            doc["run"]["supervision"] = {
                "present": True, "run_id": "r22_fake",
                "run_dir": str(run.repo / "nope" / "r22_fake"),
                "argv_token": str(run.run_dir)}
        edit_record(copied, _fix)
        with pytest.raises(SubstanceError,
                           match="supervision_run_dir_unbound"):
            verify_regression_evidence(
                record_path(copied), run.repo, run.commit_a)

    def test_valid_link_accepted(self, r17_canonical_full_run, tmp_path):
        run = r17_canonical_full_run
        copied = copy_run(run.run_dir, tmp_path / "ok")
        runs_root = run.repo / "stage2_6_1" / "artifacts" / (
            "repair17") / "development" / "run_supervision" / "runs"
        run_dir = runs_root / "r22_supervised_0001"
        run_dir.mkdir(parents=True)
        (run_dir / "run_record.json").write_text(json.dumps({
            "schema": "r17-run-record-v1",
            "run_id": "r22_supervised_0001",
            "argv": ["python", "executor", "--out-dir",
                     str(run.run_dir)],
            "started_utc": "2026-09-25T00:00:00Z",
            "ended_utc": "2026-09-25T00:01:00Z"}), encoding="utf-8")

        def _fix(doc):
            doc["run"]["supervision"] = {
                "present": True, "run_id": "r22_supervised_0001",
                "run_dir": str(run_dir),
                "argv_token": str(run.run_dir)}
        edit_record(copied, _fix)
        result = verify_regression_evidence(
            record_path(copied), run.repo, run.commit_a)
        assert result["collection_tests"] > 0


class TestSyncScriptA09:
    """r21_sync.sh 隔离同步:临时 RELEASE_DEST,逐文件 CR 规范化
    字节校验(auditor/executor/issuer/substance/tests 全覆盖)。"""

    def test_sync_bytes_isolated(self, tmp_path):
        if shutil.which("bash") is None:
            pytest.skip("bash 不可达")
        import re as _re

        def _bash_path(path):
            text_ = str(path.resolve()).replace("\\", "/")
            matched = _re.match(r"^([A-Za-z]):/(.*)$", text_)
            if matched:
                return "/mnt/%s/%s" % (matched.group(1).lower(),
                                       matched.group(2))
            return text_

        candidates = [
            _TESTS_DIR.parents[2],
            Path("/mnt/f/trading/freqai-rl-audit"),
        ]
        repo_root = next(
            (c for c in candidates
             if (c / "stage2_6_1" / "runner" / "r21_sync.sh").is_file()),
            None)
        if repo_root is None:
            pytest.skip("发布仓布局不可达(仓库与部署树均无 runner)")
        script = repo_root / "stage2_6_1" / "runner" / "r21_sync.sh"
        dest = tmp_path / "deploy_sync"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PYTEST_")}
        # wsl.exe/bash.exe 经 subprocess 传参不稳定(坑 #54 同族):
        # 路径直接内嵌 -c 脚本串,位置参数只用于 bash -s 的 REPO/DEST。
        inner = (f'tr -d "\\r" < "{_bash_path(script)}" '
                 f'| bash -s -- "{_bash_path(repo_root)}" '
                 f'"{_bash_path(dest)}"')
        proc = subprocess.run(["bash", "-c", inner],
                              capture_output=True, text=True, timeout=300,
                              env=env)
        assert proc.returncode == 0, proc.stderr
        import glob as _glob
        expected = []
        for src in sorted(_glob.glob(
                str(repo_root / "stage2_6_1" / "src" / (
                    "rl_curriculum") / "*.py"))):
            expected.append(
                (Path(src),
                 dest / "src" / "rl_curriculum" / Path(src).name))
        for leaf in ("r21_full_collection_regression.py",
                     "r21_collection_auditor.py",
                     "r17_admission_issue.py",
                     "r23_plugin_lifecycle_probe.py"):
            expected.append(
                (repo_root / "stage2_6_1" / "runner" / leaf,
                 dest / "stage2_6_1_runner" / leaf))
        for leaf in ("conftest.py",
                     "r17_admission_substance_test_support.py",
                     "test_curriculum261_r17_admission_substance.py",
                     "test_curriculum261_r20_design_math.py",
                     "test_curriculum261_r20_design_math_v4.py",
                     "test_curriculum261_r17_supervision_unit.py",
                     "test_r18_launch_behavioral.py"):
            expected.append(
                (repo_root / "stage2_6_1" / "tests" / (
                    "route_c_stage2_6_1") / leaf,
                 dest / "tests" / "route_c_stage2_6_1" / leaf))
        assert expected
        for src, dst in expected:
            assert dst.is_file(), dst
            assert dst.read_bytes() == src.read_bytes().replace(
                b"\r", b""), dst
