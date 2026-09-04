# -*- coding: utf-8 -*-
"""R14 §九-5:full-cold 证据 reader 测试(与正式 full-cold 同一实现)。

rehearsal 与正式共用 read_full_cold_evidence;字段缺失 fail closed。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r14_full_cold import (
    read_full_cold_evidence,
)


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _make_artifacts(tmp_path: Path, *, verdict="PASS",
                    smoke_pass=True, exposure="qualification_exposure_"
                    "r14.json") -> Path:
    art = tmp_path / "art"
    art.mkdir(exist_ok=True)
    _write(art / "qualification_result.json", {
        "verdict": verdict,
        "checks": {"c1_strict_pass": True},
        "final_bundle_hash": "hash123",
        "plan_digest": "r14qp-abc",
        "gate_topology": {"digest": "r14gt-xyz"},
        "gate_evidence": {"gates": {"c1_strict_pass": {}}},
        "exposure_status": None,
    })
    _write(art / "qualification_preprocessor_bundle.json", {
        "preprocessor_bundle_hash": "r4pb-canonical",
    })
    _write(art / "ppo_256step_smoke.json", {
        "pass": smoke_pass,
        "checks": {"preprocessor_bundle_hash_bound": True},
    })
    _write(art / exposure, {"status": "completed"})
    return art


class TestFullColdReader:
    def test_success_path_reads_all_fields(self, tmp_path):
        art = _make_artifacts(tmp_path)
        evidence = read_full_cold_evidence(art)
        assert evidence["pass"] is True
        assert evidence["verdict"] == "PASS"
        assert evidence["preprocessor_bundle_hash"] == "r4pb-canonical"
        assert evidence["ppo_smoke_pass"] is True
        assert evidence["gate_topology_digest"] == "r14gt-xyz"
        assert all(evidence["reader_checks"].values())

    def test_missing_qualification_result_fails_closed(self, tmp_path):
        art = _make_artifacts(tmp_path)
        (art / "qualification_result.json").unlink()
        with pytest.raises(FileNotFoundError,
                           match="qualification_result.json"):
            read_full_cold_evidence(art)

    def test_missing_bundle_fails_closed(self, tmp_path):
        art = _make_artifacts(tmp_path)
        (art / "qualification_preprocessor_bundle.json").unlink()
        with pytest.raises(FileNotFoundError):
            read_full_cold_evidence(art)

    def test_non_canonical_bundle_hash_fails(self, tmp_path):
        art = _make_artifacts(tmp_path)
        _write(art / "qualification_preprocessor_bundle.json",
               {"preprocessor_bundle_hash": "not-prefixed"})
        evidence = read_full_cold_evidence(art)
        assert evidence["pass"] is False
        assert evidence["reader_checks"][
            "preprocessor_bundle_hash_canonical"] is False

    def test_fail_verdict_reader_intact_but_not_pass(self, tmp_path):
        """verdict=FAIL:reader 完整性仍全过(--expect-verdict 消费),
        但整体 pass=False(full-cold 不接受 FAIL verdict)。"""
        art = _make_artifacts(tmp_path, verdict="FAIL")
        evidence = read_full_cold_evidence(art)
        assert all(evidence["reader_checks"].values())
        assert evidence["pass"] is False
        assert evidence["verdict"] == "FAIL"

    def test_missing_gate_topology_digest_fails(self, tmp_path):
        art = _make_artifacts(tmp_path)
        result = json.loads(
            (art / "qualification_result.json").read_text(
                encoding="utf-8"))
        result["gate_topology"] = {}
        _write(art / "qualification_result.json", result)
        evidence = read_full_cold_evidence(art)
        assert evidence["reader_checks"][
            "gate_topology_digest_present"] is False

    def test_rehearsal_terminal_marker_recognized(self, tmp_path):
        """rehearsal 产物(rehearsal_exposure.json)同样满足终态识别。"""
        art = _make_artifacts(
            tmp_path, exposure="rehearsal_exposure.json")
        result = json.loads(
            (art / "qualification_result.json").read_text(
                encoding="utf-8"))
        result["exposure_status"] = "rehearsal-terminal"
        _write(art / "qualification_result.json", result)
        evidence = read_full_cold_evidence(art)
        assert evidence["reader_checks"]["exposure_terminal"] is True

    def test_cli_subprocess_reader_check(self, tmp_path):
        """独立 subprocess 通过正式 CLI 调用同一 reader(§九)。"""
        import subprocess
        import sys

        art = _make_artifacts(tmp_path)
        proj = Path(__file__).resolve().parents[2]
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(proj / "src")
        res = subprocess.run(
            [sys.executable, "-m",
             "rl_curriculum.curriculum261_r14_cli",
             "full-cold-reader-check", "--artifacts-dir", str(art),
             "--out-dir", str(art / "out")],
            capture_output=True, text=True, env=env, timeout=300)
        assert res.returncode == 0, res.stderr[-800:]
        check = json.loads(
            (art / "out" / "full_cold_reader_check.json").read_text(
                encoding="utf-8"))
        assert check["pass"] is True

    def test_cli_reader_check_detects_corruption(self, tmp_path):
        import subprocess
        import sys

        art = _make_artifacts(tmp_path, smoke_pass=False)
        proj = Path(__file__).resolve().parents[2]
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(proj / "src")
        res = subprocess.run(
            [sys.executable, "-m",
             "rl_curriculum.curriculum261_r14_cli",
             "full-cold-reader-check", "--artifacts-dir", str(art)],
            capture_output=True, text=True, env=env, timeout=300)
        # smoke fail → 整体 pass=False → rc 1(reader 完整性仍全过)
        assert res.returncode == 1
