"""工作包 C8:沙箱隐藏包/考试上下文不可达(内容与路径双拒绝)。"""

from __future__ import annotations

import json

import pytest

from conftest import build_probe_code, run_candidate_in_sandbox


def _parse(proc):
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe 无输出: rc={proc.returncode} err={proc.stderr[-500:]}"
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def hidden_exam_files(tmp_path_factory):
    d = tmp_path_factory.mktemp("hidden-exam")
    pack = d / "mock_hidden_probe_pack.json"
    pack.write_text('{"episodes": "hidden-seeds-secret"}')
    ctx = d / "exam_context.json"
    ctx.write_text('{"charter": "secret"}')
    key = d / "issuer_private.pem"
    key.write_text("-----BEGIN PRIVATE KEY-----\nMOCK-SECRET-NEVER-REAL\n")
    return {"pack": pack, "context": ctx, "private_key": key}


def test_hidden_pack_content_unreadable(sandbox_checkpoint,
                                        hidden_exam_files):
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(targets=[
            ("pack", str(hidden_exam_files["pack"])),
            ("context", str(hidden_exam_files["context"])),
            ("private_key", str(hidden_exam_files["private_key"])),
        ]))
    report = _parse(proc)
    for name in ("pack", "context", "private_key"):
        t = report["targets"][name]
        assert not t["read"]["ok"], f"{name} 泄漏: {t['read']}"
        assert t["read"]["err"] == "PermissionError"


def test_mountinfo_does_not_leak_eval_paths(sandbox_checkpoint,
                                            hidden_exam_files):
    """/proc/self/mountinfo 不暴露评估工作区路径(checkpoint 经 staging
    副本绑定,源路径只在中性临时目录内)。"""
    from rl_curriculum.sandbox import SandboxedCandidate  # noqa: F401

    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(
            extra_code='''
try:
    with open("/proc/self/mountinfo") as f:
        info = f.read()
    report["extra"]["mountinfo_len"] = len(info)
    report["extra"]["leaks_home"] = "/home/" in info
    report["extra"]["leaks_projects"] = "projects" in info
except Exception as e:
    report["extra"]["mountinfo_error"] = repr(e)
'''))
    report = _parse(proc)
    extra = report["extra"]
    assert "mountinfo_len" in extra
    assert not extra.get("leaks_home"), f"mountinfo 泄漏 home 路径: {extra}"
    assert not extra.get("leaks_projects"), (
        f"mountinfo 泄漏项目路径: {extra}")


def test_attempt_registry_and_eval_logs_denied(sandbox_checkpoint,
                                               tmp_path):
    (tmp_path / "attempt_registry.json").write_text("{}")
    (tmp_path / "eval.log").write_text("eval secrets")
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(targets=[
            ("attempt_registry", str(tmp_path / "attempt_registry.json")),
            ("eval_log", str(tmp_path / "eval.log")),
        ]))
    report = _parse(proc)
    for name in ("attempt_registry", "eval_log"):
        assert not report["targets"][name]["read"]["ok"]
