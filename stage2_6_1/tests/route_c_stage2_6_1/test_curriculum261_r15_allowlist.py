# -*- coding: utf-8 -*-
"""R15 §七/§十:Commit B allowlist 机器检查 + formal raw log manifest。

R15:expected 序列由权威 workflow 定义派生(expected_formal_log_prefix);
verify-formal-logs 自身不在任何 expected 前缀内(其记录由 chain
执行器在运行后追加)。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r15_cli import (
    R15_FORMAL_LOG_MANIFEST_NAME,
    cmd_commit_b_allowlist,
    cmd_formal_log_record,
    cmd_verify_formal_logs,
    commit_b_allowlist_violations,
)
from rl_curriculum.curriculum261_r15_workflow import (
    expected_formal_log_prefix,
    r15_workflow_step_names,
)


class TestCommitBAllowlistPure:
    def test_allowed_result_paths(self):
        paths = [
            "stage2_6_1/artifacts/repair15/qualification_result.json",
            "stage2_6_1/artifacts/repair15/raw_logs/audit.log",
            "stage2_6_1/report/"
            "route_c_stage2_6_1_repair15_gate_topology_clean_"
            "qualification.md",
            "README.md",
            "stage2_6_1/README.md",
        ]
        assert commit_b_allowlist_violations(paths) == []

    def test_src_tests_runner_are_violations(self):
        paths = [
            "stage2_6_1/src/rl_curriculum/curriculum261_r15_cli.py",
            "stage2_6_1/tests/route_c_stage2_6_1/test_x.py",
            "stage2_6_1/runner/r15_post_freeze_hotfix.py",
            "stage2_6_1/runner/assemble_r15_c.sh",
            "requirements.txt",
            "stage2_6_1/config.yaml",
        ]
        assert commit_b_allowlist_violations(paths) == paths

    def test_wrong_report_names_are_violations(self):
        paths = [
            "stage2_6_1/report/route_c_stage2_6_1_repair13_report.md",
            "stage2_6_1/report/notes.txt",
        ]
        assert commit_b_allowlist_violations(paths) == paths

    def test_other_repair_artifacts_are_violations(self):
        """R15 只允许 repair15/**;其他轮次产物目录是 violation。"""
        assert commit_b_allowlist_violations(
            ["stage2_6_1/artifacts/repair14/x.json"]) == [
            "stage2_6_1/artifacts/repair14/x.json"]


class TestCommitBAllowlistCommand:
    """端到端(monkeypatch git 调用;repo 发现代码路径短路)。"""

    def _run(self, tmp_path, diff_paths, monkeypatch):
        import rl_curriculum.curriculum261_r15_cli as cli_mod

        class FakeCompleted:
            def __init__(self, stdout="", returncode=0):
                self.stdout = stdout
                self.stderr = ""
                self.returncode = returncode

        def fake_run(cmd, **kwargs):
            if "diff" in cmd:
                return FakeCompleted("\n".join(diff_paths))
            if "rev-parse" in cmd:
                return FakeCompleted("f" * 40)
            return FakeCompleted()

        monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
        # repo 发现:/mnt/e 或 E:/ 的 release repo 在开发机真实存在;
        # fake_run 已拦截全部 git 调用,不会触碰真实仓库状态。

        args = argparse.Namespace(
            from_commit="a" * 40, out_dir=str(tmp_path))
        return cmd_commit_b_allowlist(args)

    def test_clean_diff_passes(self, tmp_path, monkeypatch):
        rc = self._run(tmp_path, [
            "stage2_6_1/artifacts/repair15/x.json",
            "README.md"], monkeypatch)
        assert rc == 0
        doc = json.loads(
            (tmp_path / "commit_b_allowlist_check.json").read_text(
                encoding="utf-8"))
        assert doc["pass"] is True

    def test_violation_fails(self, tmp_path, monkeypatch):
        rc = self._run(tmp_path, [
            "stage2_6_1/artifacts/repair15/x.json",
            "stage2_6_1/src/rl_curriculum/rogue.py"], monkeypatch)
        assert rc == 1
        doc = json.loads(
            (tmp_path / "commit_b_allowlist_check.json").read_text(
                encoding="utf-8"))
        assert doc["violations"] == [
            "stage2_6_1/src/rl_curriculum/rogue.py"]


def _make_manifest_record(step: str, rc: int = 0) -> dict:
    return {"step": step, "argv": ["python", "-m", "cli", step],
            "cwd": "/proj", "env": {"python": "3.11"},
            "workflow_graph_digest": "r15wg-test",
            "start_utc": "2026-01-01T00:00:00+00:00",
            "end_utc": "2026-01-01T00:01:00+00:00", "rc": rc,
            "stdout_sha256": "a" * 64, "stderr_sha256": "b" * 64,
            "stdout_path": "/logs/a.log", "stderr_path": "/logs/a.err"}


class TestFormalLogManifest:
    def test_record_appends_full_fields(self, tmp_path):
        manifest = tmp_path / R15_FORMAL_LOG_MANIFEST_NAME
        stdout = tmp_path / "audit.log"
        stdout.write_text("out", encoding="utf-8")
        stderr = tmp_path / "audit.err"
        stderr.write_text("err", encoding="utf-8")
        args = argparse.Namespace(
            step="audit",
            argv_json='["python", "-m", "cli", "audit"]',
            cwd=str(tmp_path), rc=0,
            start_utc="2026-01-01T00:00:00+00:00",
            end_utc="2026-01-01T00:01:00+00:00",
            stdout_file=str(stdout), stderr_file=str(stderr),
            input=[str(stdout)], output=[str(stderr)],
            manifest=str(manifest))
        assert cmd_formal_log_record(args) == 0
        rec = json.loads(manifest.read_text(encoding="utf-8").strip())
        assert rec["step"] == "audit"
        assert rec["env"]["python"]
        assert rec["stdout_sha256"]
        assert rec["input_artifacts"][0]["sha256"]

    def test_full_chain_manifest_passes(self, tmp_path):
        """链尾:manifest 含 1..report-read 的完整前缀(verify 自身
        记录由 chain 执行器在其运行后追加)。"""
        manifest = tmp_path / R15_FORMAL_LOG_MANIFEST_NAME
        with manifest.open("w", encoding="utf-8") as fh:
            for step in expected_formal_log_prefix("report-read"):
                fh.write(json.dumps(
                    _make_manifest_record(step)) + "\n")
        args = argparse.Namespace(
            stopped_at="report-read", manifest=str(manifest),
            out_dir=str(tmp_path))
        assert cmd_verify_formal_logs(args) == 0

    def test_verify_self_not_in_prefix(self, tmp_path):
        """verify-formal-logs 自身不在 expected 前缀;若 manifest
        已含其记录(重放场景),严格序列比较必须 FAIL(不可自证)。"""
        manifest = tmp_path / R15_FORMAL_LOG_MANIFEST_NAME
        with manifest.open("w", encoding="utf-8") as fh:
            for step in (expected_formal_log_prefix("report-read")
                         + ["verify-formal-logs"]):
                fh.write(json.dumps(
                    _make_manifest_record(step)) + "\n")
        args = argparse.Namespace(
            stopped_at="report-read", manifest=str(manifest),
            out_dir=str(tmp_path))
        assert cmd_verify_formal_logs(args) == 1

    def test_stopped_at_qualify_expects_prefix(self, tmp_path):
        manifest = tmp_path / R15_FORMAL_LOG_MANIFEST_NAME
        with manifest.open("w", encoding="utf-8") as fh:
            for step in expected_formal_log_prefix("qualify"):
                fh.write(json.dumps(
                    _make_manifest_record(step)) + "\n")
        args = argparse.Namespace(
            stopped_at="qualify", manifest=str(manifest),
            out_dir=str(tmp_path))
        assert cmd_verify_formal_logs(args) == 0

    def test_missing_step_fails(self, tmp_path):
        manifest = tmp_path / R15_FORMAL_LOG_MANIFEST_NAME
        steps = [s for s in expected_formal_log_prefix("report-read")
                 if s not in ("smoke", "full-cold")]
        with manifest.open("w", encoding="utf-8") as fh:
            for step in steps:
                fh.write(json.dumps(
                    _make_manifest_record(step)) + "\n")
        args = argparse.Namespace(
            stopped_at="report-read", manifest=str(manifest),
            out_dir=str(tmp_path))
        assert cmd_verify_formal_logs(args) == 1

    def test_nonzero_rc_step_fails(self, tmp_path):
        manifest = tmp_path / R15_FORMAL_LOG_MANIFEST_NAME
        with manifest.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(
                _make_manifest_record("determinism-matrix")) + "\n")
            fh.write(json.dumps(
                _make_manifest_record("audit", rc=1)) + "\n")
        args = argparse.Namespace(
            stopped_at="audit", manifest=str(manifest),
            out_dir=str(tmp_path))
        assert cmd_verify_formal_logs(args) == 1

    def test_unknown_stopped_at_rejected(self, tmp_path):
        args = argparse.Namespace(
            stopped_at="nonexistent", manifest=str(tmp_path / "m.jsonl"),
            out_dir=str(tmp_path))
        assert cmd_verify_formal_logs(args) == 1

    def test_chain_step_order_matches_contract(self):
        """权威流程顺序合同(§十三):provenance-verify 首位、
        preplan-smoke 位于 plan-roundtrip 之前(R14 缺陷的回归锁定)、
        verify-formal-logs 链尾。"""
        assert r15_workflow_step_names() == (
            "provenance-verify",
            "determinism-matrix", "audit", "cue-audit", "preplan-smoke",
            "plan-roundtrip",
            "design-plan-lock", "design", "calibrate", "preflight-static",
            "lock-plan", "preflight-sealed", "qualify", "smoke",
            "full-cold", "report-read", "verify-formal-logs")
