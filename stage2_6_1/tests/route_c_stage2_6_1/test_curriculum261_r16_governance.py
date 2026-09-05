# -*- coding: utf-8 -*-
"""R16 治理测试:分支上下文 + 历史 binding(r15 永久 FAIL 绑定)
+ 执行治理权威(journal/投影)的发布仓库级检查。"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r16_historical import (
    historical_evidence_binding,
    historical_evidence_binding_digest,
)
from rl_curriculum.curriculum261_r16_cli import (
    R15_COMMIT_A,
    R15_COMMIT_B,
)

R16_EXPECTED_BASELINE = (
    "c0da37a498740201c42898ea9b743ecfb54990da")  # R15 Commit B


def _release_repo():
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),):
        if cand.is_dir():
            return cand
    return None


def _on_r16_branch() -> bool:
    repo = _release_repo()
    if repo is None:
        return False
    out = subprocess.run(
        ["git", "branch", "--show-current"], cwd=str(repo),
        capture_output=True, text=True)
    return out.stdout.strip() == "route-c-stage2-6-1-repair16"


@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestHistoricalEvidenceBindingR16:
    @pytest.mark.skipif(not _on_r16_branch(),
                        reason="非 repair16 分支:R16 binding 的分支检查"
                               "仅在 R16 iteration 上下文有效")
    def test_ancestry_and_r15_clean_chain(self):
        repo = _release_repo()
        binding = historical_evidence_binding(repo)
        assert binding["expected_baseline"] == R16_EXPECTED_BASELINE
        assert R15_COMMIT_A == (
            "c1c973e057375cbc258d0fe48e7ce7044a9a05df")
        assert R15_COMMIT_B == R16_EXPECTED_BASELINE
        # R15 链与失败事实绑定(§二;永久 FAIL 不追认)
        assert binding["checks"]["r14_clean_two_commit_chain"] is True
        gov15 = binding.get("r15_governance_binding") or {}
        assert gov15.get("r15_commit_a") == R15_COMMIT_A
        assert gov15.get("r15_commit_b") == R15_COMMIT_B
        assert gov15.get("r15_remains_permanent_fail") is True
        assert gov15.get("r15_failure_classification")
        # digest 覆盖 r15_governance_binding(防静默剔除)
        d1 = historical_evidence_binding_digest(binding)
        tampered = dict(binding)
        tampered["r15_governance_binding"] = {}
        assert historical_evidence_binding_digest(tampered) != d1

    def test_binding_deterministic(self):
        repo = _release_repo()
        b1 = historical_evidence_binding(repo)
        b2 = historical_evidence_binding(repo)
        assert (historical_evidence_binding_digest(b1)
                == historical_evidence_binding_digest(b2))


@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达")
class TestExecutionSurfaceBytes:
    """§5.2:执行面字节检查(工作树;LF)——R15 CRLF 事故的回归。"""

    @pytest.mark.skipif(not _on_r16_branch(),
                        reason="非 repair16 分支")
    def test_runner_shell_scripts_lf(self):
        repo = _release_repo()
        offenders = []
        for p in (repo / "stage2_6_1" / "runner").glob("r16_*.sh"):
            raw = p.read_bytes()
            if b"\r" in raw:
                offenders.append(p.name)
        for p in (repo / "stage2_6_1" / "runner").glob("assemble_r16_*.sh"):
            raw = p.read_bytes()
            if b"\r" in raw:
                offenders.append(p.name)
        assert not offenders, f"CRLF 执行面: {offenders}"

    def test_gitattributes_pins_lf(self):
        repo = _release_repo()
        attrs = repo / ".gitattributes"
        assert attrs.is_file(), ".gitattributes 缺失"
        text = attrs.read_text(encoding="utf-8")
        assert "stage2_6_1/runner/*.sh text eol=lf" in text

    @pytest.mark.skipif(not _on_r16_branch(),
                        reason="非 repair16 分支")
    def test_r16_formal_wrapper_selfcheck_present(self):
        repo = _release_repo()
        wrapper = (repo / "stage2_6_1" / "runner"
                   / "r16_formal_chain.sh").read_text(encoding="utf-8")
        # 自检在真实 set 语句之前(R15 实证:全 CRLF 死于
        # set: pipefail 解析错误,后置自检执行不到;按行首匹配
        # 避免命中注释字样)
        lines = wrapper.splitlines()
        selfcheck_line = next(
            i for i, ln in enumerate(lines)
            if "grep -q $'" in ln and "\\r" in ln)
        set_line = next(
            i for i, ln in enumerate(lines)
            if ln.startswith("set -euo pipefail"))
        assert selfcheck_line < set_line
        # bootstrap 边界:workflow-plan 失败用 --failed-step bootstrap
        assert "--failed-step bootstrap" in wrapper
        # 激活失败即拒(不 || true)
        assert "|| true" not in wrapper.split(
            "activate-freqtrade.sh")[1].split("\n")[0]


class TestJournalProjectionContract:
    """§8.2:marker 是 journal 的投影(无独立真相地位)。"""

    def test_marker_absence_does_not_unexpose(self, tmp_path,
                                              monkeypatch):
        import json

        from rl_curriculum.curriculum261_r16_execgov import (
            R16FormalSession,
            exposure_state,
            r16_exposure_marker_path,
        )

        monkeypatch.setenv("CURRICULUM261_R16_STATE_ROOT",
                           str(tmp_path / "st"))
        s = R16FormalSession.acquire(binding={"t": 1})
        s.record_exposure_started("d-1")
        marker = r16_exposure_marker_path()
        assert marker.is_file()
        marker.unlink()  # 删除投影
        state = exposure_state()
        assert state["exposed"] is True  # journal 仍判定已暴露
        s.commit_qualification_terminal("crashed", "d-1")
        s.release()

    def test_session_events_are_replayable_facts(self, tmp_path,
                                                 monkeypatch):
        from rl_curriculum.curriculum261_r16_execgov import (
            R16FormalSession,
            journal_entries,
        )

        monkeypatch.setenv("CURRICULUM261_R16_STATE_ROOT",
                           str(tmp_path / "st"))
        s = R16FormalSession.acquire(binding={"t": 2})
        s.record_exposure_started("d-2")
        s.issue_generation_grant()
        s.revoke_generation_grant()
        s.commit_qualification_terminal("completed", "d-2")
        s.release()
        seq = [e["seq"] for e in journal_entries()]
        assert seq == list(range(1, len(seq) + 1))  # 连续无空洞
