"""工作包 C8:沙箱文件系统拒绝测试(评估工作区/项目根/隐藏包不可见)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import (  # noqa: F401
    build_probe_code,
    run_candidate_in_sandbox,
)


def _parse(proc):
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert lines, f"probe 无输出: rc={proc.returncode} err={proc.stderr[-500:]}"
    return json.loads(lines[-1])


@pytest.fixture(scope="module")
def sentinel_workspace(tmp_path_factory):
    """模拟评估工作区:含 sentinel 文件、隐藏包、manifest、registry。"""
    ws = tmp_path_factory.mktemp("eval-workspace")
    (ws / "SENTINEL").write_text("eval-workspace-secret-token")
    hidden = ws / "hidden_pack.json"
    hidden.write_text('{"hidden": "exam-content-secret"}')
    (ws / "sealed_manifest.json").write_text('{"commitment": "secret"}')
    (ws / "retired_packs.json").write_text("{}")
    (ws / "generators").mkdir()
    (ws / "generators" / "private_gen.py").write_text("# private secret")
    return ws


def test_eval_workspace_sentinel_unreadable(sandbox_checkpoint,
                                            sentinel_workspace):
    ws = sentinel_workspace
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(targets=[
            ("sentinel", str(ws / "SENTINEL")),
            ("hidden_pack", str(ws / "hidden_pack.json")),
            ("sealed_manifest", str(ws / "sealed_manifest.json")),
            ("retirement_registry", str(ws / "retired_packs.json")),
            ("private_generator", str(ws / "generators" / "private_gen.py")),
        ]))
    report = _parse(proc)
    for name in ("sentinel", "hidden_pack", "sealed_manifest",
                 "retirement_registry", "private_generator"):
        t = report["targets"][name]
        assert not t["read"]["ok"], f"{name} 可被候选读取: {t['read']}"
        assert t["read"]["err"] == "PermissionError", t["read"]


def test_project_root_not_listable(sandbox_checkpoint):
    project_root = str(Path(__file__).resolve().parents[2])
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(targets=[
            ("project_root", project_root),
            ("src", str(Path(project_root) / "src")),
            ("user_home", str(Path.home())),
        ]))
    report = _parse(proc)
    for name in ("project_root", "src", "user_home"):
        t = report["targets"][name]
        assert not t["list"]["ok"], f"{name} 可被候选列出: {t['list']}"
        assert not t["read"]["ok"], f"{name} 可被候选读取: {t['read']}"


def test_real_tmp_other_files_denied(sandbox_checkpoint, tmp_path):
    """真实 /tmp 下其他文件(非本沙箱 staging)不可读。"""
    other = tmp_path / "other_secret.txt"
    other.write_text("tmp-secret")
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(targets=[("other_tmp", str(other))]))
    report = _parse(proc)
    assert not report["targets"]["other_tmp"]["read"]["ok"]


def test_scratch_writable_but_not_others(sandbox_checkpoint, tmp_path):
    """唯一可写目录是沙箱 scratch(HOME/TMPDIR 指向的 tmpfs)。"""
    other = tmp_path / "outside.txt"
    proc = run_candidate_in_sandbox(
        sandbox_checkpoint,
        probe_code=build_probe_code(
            extra_code='''
try:
    with open(os.path.join(os.environ.get("HOME", "/"), "w_ok.txt"), "wb") as f:
        f.write(b"ok")
    report["extra"]["scratch_write"] = True
except Exception as e:
    report["extra"]["scratch_write"] = repr(e)
''',
            targets=[("outside_write", str(other))]))
    report = _parse(proc)
    assert report["extra"]["scratch_write"] is True
    assert not report["targets"]["outside_write"]["write"]["ok"]
