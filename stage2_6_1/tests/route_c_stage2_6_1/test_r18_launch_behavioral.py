# -*- coding: utf-8 -*-
"""R18 正式启动行为级隔离验证(外部审查 §3.2;R19 处方勘误前置)。

真实面:r18_formal_chain.sh(真实部署 runner)、r17_admission_issue.py
签发、curriculum261_r17_admission 闸门/一次性消费、链步 1
provenance-verify 内容强制;隔离面:R17_PROJECT_ROOT 指向沙箱根
(独立 state root/请求根/发布仓),真实部署面全程哈希快照比对零触碰。

覆盖场景:
- 链外前置产物缺失 → 入口守卫零消费早拒(不消耗一次性准入);
- 准入文件缺失/冻结 SHA 不匹配 → 闸门拒绝,零消费、零链状态;
- 合法准入 + 无效 gate_topology({"pass": false}) → 单次消费全流程,
  链步 1 内容强制失败,沙箱 journal 终态(R18 r2 行为的定向复现);
- 第二次启动/直调 enforce_formal_admission → admission_already_
  consumed,消费日志与 journal 均不增(双消费回归)。
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SYNC = Path.home() / "projects" / "crypto_rl"
RUNNER = SYNC / "stage2_6_1_runner"
ENTRY = RUNNER / "r18_formal_chain.sh"
ISSUER = RUNNER / "r17_admission_issue.py"
DEPLOY_SRC = SYNC / "src"

requires_sync = pytest.mark.skipif(
    os.name == "nt" or not ENTRY.is_file()
    or not ISSUER.is_file() or not DEPLOY_SRC.is_dir(),
    reason="需要 WSL 部署面(真实 runner/签发器/src)")

#: 真实部署面保护区(所有拒绝路径不得触碰;哈希快照比对)。
_FACE_REGIONS = (
    SYNC / "r17_formal_requests",
    SYNC / "artifacts/route_c_stage2_6_1_repair18",
    SYNC / "artifacts/route_c_stage2_6_1_repair18_chain_logs",
    SYNC / "r17_admission_issued.jsonl",
    SYNC / ".r17_formal_admission.json",
)


def _face_snapshot() -> dict:
    snap = {}
    for region in _FACE_REGIONS:
        if region.is_file():
            snap[str(region)] = hashlib.sha256(
                region.read_bytes()).hexdigest()
        elif region.is_dir():
            for p in sorted(region.rglob("*")):
                if p.is_file():
                    snap[str(p)] = hashlib.sha256(
                        p.read_bytes()).hexdigest()
    return snap


def _run(cmd, *, cwd=None, env=None, timeout=300):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def _git(repo: Path, *args: str) -> str:
    proc = _run(["git", "-C", str(repo), *args])
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


class _Sandbox:
    """沙箱根:独立 state root/请求根 + 真实 src/激活脚本符号链接
    + 两提交发布仓(Commit A 需有 parent,满足签发器校验)。"""

    def __init__(self, base: Path):
        self.root = base / "sb_crypto_rl"
        self.root.mkdir()
        self.state = (self.root / "artifacts" /
                      "route_c_stage2_6_1_repair18" / "state")
        self.state.mkdir(parents=True)
        (self.root / "src").symlink_to(
            DEPLOY_SRC, target_is_directory=True)
        (self.root / "activate-freqtrade.sh").symlink_to(
            SYNC / "activate-freqtrade.sh")
        self.repo = self.root / "release_repo"
        self.repo.mkdir()
        _run(["git", "init", "-q", "."], cwd=self.repo)
        _git(self.repo, "config", "user.email", "r18bh@test")
        _git(self.repo, "config", "user.name", "r18bh")
        (self.repo / "base.txt").write_text("base\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        (self.repo / "cand.txt").write_text("cand\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "cand")
        self.commit_a = _git(self.repo, "rev-parse", "HEAD")
        self.admission_id = "r18bh-admission-0001"

    def issue_admission(self) -> None:
        prereg = self.root / "prereg.json"
        prereg.write_text(json.dumps({
            "admission_id": self.admission_id,
            "iteration": "r18",
            "plan_digest": "0" * 40,
            "authorization": (
                "test-harness:外部审查3.2 行为级隔离验证,"
                "沙箱签发,不触碰正式部署面")}, ensure_ascii=False))
        proc = _run([sys.executable, str(ISSUER),
                     "--repo", str(self.repo),
                     "--deploy-root", str(self.root),
                     "--state-root", str(self.state),
                     "--commit-a", self.commit_a,
                     "--preregistration", str(prereg)])
        assert proc.returncode == 0, proc.stderr

    def place_precondition(self, payload) -> None:
        (self.root / "artifacts" / "route_c_stage2_6_1_repair18"
         / "gate_topology_reconciliation.json").write_text(
            json.dumps(payload) + "\n", encoding="utf-8")

    def launch(self, sha: str | None = None, *, timeout: int = 600):
        env = {k: v for k, v in os.environ.items()
               if k not in ("R17_ART_ROOT", "R17_STATE_ROOT",
                            "CURRICULUM261_R17_STATE_ROOT",
                            "CURRICULUM261_R17_DEPLOYED_STATE_ROOT")}
        env["R17_PROJECT_ROOT"] = str(self.root)
        env["R17_RUNNER_DIR"] = str(RUNNER)
        env["R17_RELEASE_REPO"] = str(self.repo)
        env["PATH"] = (str(Path(sys.executable).parent) + ":"
                       + env.get("PATH", ""))
        return _run(["bash", str(ENTRY), sha or self.commit_a],
                    env=env, timeout=timeout)

    def consumed_lines(self) -> list:
        p = self.state / "r17_admission_consumed.jsonl"
        if not p.is_file():
            return []
        return [json.loads(x) for x in p.read_text(
            encoding="utf-8").splitlines() if x.strip()]

    def journal(self) -> list:
        p = self.state / "r17_execution_journal.jsonl"
        if not p.is_file():
            return []
        return [json.loads(x) for x in p.read_text(
            encoding="utf-8").splitlines() if x.strip()]

    def last_rejection(self) -> dict:
        reqs = sorted((self.root / "r17_formal_requests").iterdir())
        assert len(reqs) == 1, [p.name for p in reqs]
        lines = (reqs[0] / "admission_rejected.jsonl").read_text(
            encoding="utf-8").splitlines()
        return json.loads(lines[-1])


@pytest.fixture()
def sandbox(tmp_path):
    return _Sandbox(tmp_path)


@requires_sync
def test_missing_admission_refuses_zero_consumption(sandbox):
    sandbox.place_precondition({"pass": False})
    before = _face_snapshot()
    proc = sandbox.launch()
    assert proc.returncode == 96
    assert "admission_missing" in (proc.stdout + proc.stderr)
    assert sandbox.consumed_lines() == []
    assert sandbox.journal() == []
    art = sandbox.root / "artifacts/route_c_stage2_6_1_repair18"
    assert not (art / "r17_bootstrap_accepted.json").exists()
    rej = sandbox.last_rejection()
    assert rej["event"] == "admission_rejected"
    assert rej["reason"] == "admission_missing"
    assert _face_snapshot() == before


@requires_sync
def test_missing_precondition_guard_refuses_before_gate(sandbox):
    sandbox.issue_admission()
    admission_before = (
        sandbox.root / ".r17_formal_admission.json").read_bytes()
    issuance_before = (
        sandbox.root / "r17_admission_issued.jsonl").read_bytes()
    before = _face_snapshot()
    proc = sandbox.launch()
    assert proc.returncode == 96
    assert "gate_topology_reconciliation.json" in (
        proc.stdout + proc.stderr)
    rej = sandbox.last_rejection()
    assert rej["event"] == "precondition_missing"
    assert rej["freeze_sha"] == sandbox.commit_a
    # 零消费、零链状态;准入文件与签发日志原样
    assert sandbox.consumed_lines() == []
    assert sandbox.journal() == []
    assert (sandbox.root / ".r17_formal_admission.json"
            ).read_bytes() == admission_before
    assert (sandbox.root / "r17_admission_issued.jsonl"
            ).read_bytes() == issuance_before
    assert _face_snapshot() == before


@requires_sync
def test_freeze_mismatch_refuses_zero_consumption(sandbox):
    sandbox.issue_admission()
    sandbox.place_precondition({"pass": False})
    before = _face_snapshot()
    proc = sandbox.launch(sha="e" * 40)
    assert proc.returncode == 96
    assert "admission_freeze_mismatch" in (proc.stdout + proc.stderr)
    assert sandbox.consumed_lines() == []
    assert sandbox.journal() == []
    assert _face_snapshot() == before


@requires_sync
def test_single_consumption_full_flow_then_double_consume_refused(
        sandbox):
    """合法准入 + 前置存在但内容无效:单次消费全流程到链步 1 内容
    强制拒绝、沙箱终态;随后第二次启动与直调消费点均被
    admission_already_consumed 拒绝且不增记(R18 r2 行为定向复现)。"""
    sandbox.issue_admission()
    sandbox.place_precondition({"pass": False,
                                "digest": "r17gtrec-invalid"})
    before = _face_snapshot()
    proc = sandbox.launch()
    assert proc.returncode == 1, proc.stdout + proc.stderr
    consumed = sandbox.consumed_lines()
    assert len(consumed) == 1
    assert consumed[0]["admission_id"] == sandbox.admission_id
    art = sandbox.root / "artifacts/route_c_stage2_6_1_repair18"
    assert (art / "r17_bootstrap_accepted.json").is_file()
    result = json.loads((art / "r17_chain_result.json").read_text(
        encoding="utf-8"))
    assert result["ok"] is False
    assert result["failed_step"] == "provenance-verify"
    entries = sandbox.journal()
    names = [e.get("event", "") for e in entries]
    assert len(entries) == 5
    assert any(n.endswith("acquired") for n in names)
    assert sum("step_failed" in n for n in names) == 1
    assert sum("iteration_aborted" in n for n in names) == 1
    assert names[-1].endswith("released")
    failed = [e for e in entries
              if "step_failed" in e.get("event", "")][0]
    assert "provenance-verify" in json.dumps(failed,
                                             ensure_ascii=False)
    verify = json.loads(
        (art / "gate_topology_provenance_verify.json").read_text(
            encoding="utf-8"))
    assert verify["pass"] is False
    assert _face_snapshot() == before

    # 第二次启动:入口只校验(不消费),已消费 → 拒绝
    proc2 = sandbox.launch()
    assert proc2.returncode == 96
    assert "admission_already_consumed" in (
        proc2.stdout + proc2.stderr)
    assert len(sandbox.consumed_lines()) == 1
    assert len(sandbox.journal()) == 5
    assert _face_snapshot() == before

    # 直调唯一消费点:同样拒绝且不增记
    from rl_curriculum.curriculum261_r17_admission import (
        enforce_formal_admission)
    reason = enforce_formal_admission(
        state_root=sandbox.state, freeze_sha=sandbox.commit_a,
        release_repo=str(sandbox.repo))
    assert reason == "admission_already_consumed"
    assert len(sandbox.consumed_lines()) == 1
    assert _face_snapshot() == before
