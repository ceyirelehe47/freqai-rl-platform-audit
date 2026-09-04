# -*- coding: utf-8 -*-
"""R15 §六:全 freeze surface(递归 manifest + Git tree identity)测试。

fail closed 检出:modified / added / removed(renamed)/ untracked
executable/source / symlink target drift / exec bit drift / runner
脚本漂移 / tests 漂移 / HEAD 漂移。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r15_dependencies import (
    R15_FREEZE_DEV_DIRS,
    R15_FREEZE_DEV_FILES,
    R15_FREEZE_REPO_PATHS,
    freeze_surface_manifest_r15,
    write_r15_code_freeze,
    verify_r15_code_freeze,
    _freeze_dev_root,
    _freeze_release_repo,
)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def _build_dev_tree(root: Path) -> None:
    for d in R15_FREEZE_DEV_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "src/rl_curriculum/mod_a.py").write_text(
        "# a\n", encoding="utf-8")
    sub = root / "src/rl_curriculum/sub"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "mod_b.py").write_text("# b\n", encoding="utf-8")
    (root / "tests/route_c_stage2_6_1/test_x.py").write_text(
        "# t\n", encoding="utf-8")
    for f in R15_FREEZE_DEV_FILES:
        target = root / f
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# frozen file\n", encoding="utf-8")
    # 运行副产品目录(应被排除)
    (root / "src/rl_curriculum/__pycache__").mkdir(exist_ok=True)
    (root / "src/rl_curriculum/__pycache__/mod_a.pyc").write_text(
        "pyc", encoding="utf-8")


def _build_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    for p in ("stage2_6_1/src/x.py", "stage2_6_1/tests/route_c_stage2_6_1"
              "/t.py", "stage2_6_1/runner/run.sh"):
        target = repo / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# repo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "commit A")
    dev = tmp_path / "dev"
    dev.mkdir()
    _build_dev_tree(dev)
    return repo, dev


@pytest.fixture()
def freeze_env(tmp_path, monkeypatch):
    repo, dev = _build_repo(tmp_path)
    monkeypatch.setattr(
        "rl_curriculum.curriculum261_r15_dependencies._freeze_dev_root",
        lambda: dev)
    monkeypatch.setattr(
        "rl_curriculum.curriculum261_r15_dependencies"
        "._freeze_release_repo",
        lambda: repo)
    out = tmp_path / "artifacts"
    out.mkdir()
    head = _git(repo, "rev-parse", "HEAD")
    return repo, dev, out, head


class TestFreezeSurfaceManifest:
    def test_manifest_structure(self, freeze_env):
        repo, dev, out, head = freeze_env
        manifest = freeze_surface_manifest_r15()
        assert manifest["repo_head_commit"] == head
        assert manifest["missing_required"] == []
        names = set(manifest["dev_files"])
        assert "src/rl_curriculum/mod_a.py" in names
        assert "src/rl_curriculum/sub/mod_b.py" in names
        assert "tests/route_c_stage2_6_1/test_x.py" in names
        assert "user_data/strategies/RouteCStrategy.py" in names
        assert "requirements-lock.txt" in names
        # __pycache__ 排除
        assert not any("__pycache__" in n for n in names)
        # repo tracked 覆盖 runner
        assert any(p.startswith("stage2_6_1/runner/")
                   for p in manifest["repo_tracked"])
        assert manifest["freeze_surface_digest"].startswith("r15fs-")

    def test_write_freeze_binds_commit_a(self, freeze_env):
        repo, dev, out, head = freeze_env
        payload = write_r15_code_freeze(out, code_freeze_sha=head)
        assert payload["code_freeze_sha"] == head
        assert (out / "r15_code_freeze.json").is_file()

    def test_write_freeze_rejects_wrong_sha(self, freeze_env):
        repo, dev, out, head = freeze_env
        with pytest.raises(RuntimeError, match="code_freeze_sha 与 "
                                              "repo HEAD 不一致"):
            write_r15_code_freeze(out, code_freeze_sha="0" * 40)

    def test_write_freeze_rejects_dirty_repo(self, freeze_env):
        repo, dev, out, head = freeze_env
        (repo / "stage2_6_1/src/x.py").write_text(
            "# modified uncommitted\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="未提交变化"):
            write_r15_code_freeze(out, code_freeze_sha=head)

    def test_write_freeze_once_only(self, freeze_env):
        repo, dev, out, head = freeze_env
        write_r15_code_freeze(out, code_freeze_sha=head)
        with pytest.raises(RuntimeError, match="一次且仅一次"):
            write_r15_code_freeze(out, code_freeze_sha=head)


class TestFreezeVerifyDriftDetection:
    def _freeze(self, freeze_env):
        repo, dev, out, head = freeze_env
        write_r15_code_freeze(out, code_freeze_sha=head)
        return repo, dev, out, head

    def test_no_drift_passes(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        result = verify_r15_code_freeze(out)
        assert result["pass"] is True, result
        assert result["head_matches_commit_a"] is True
        assert result["drift_types"] == []

    def test_modified_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        (dev / "src/rl_curriculum/mod_a.py").write_text(
            "# tampered\n", encoding="utf-8")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "modified" in result["drift_types"]
        assert "src/rl_curriculum/mod_a.py" in result["modified_files"]

    def test_added_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        (dev / "src/rl_curriculum/rogue_new.py").write_text(
            "# new\n", encoding="utf-8")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "added" in result["drift_types"]

    def test_removed_and_renamed_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        # renamed = 旧路径删除 + 新路径出现
        (dev / "src/rl_curriculum/mod_b_renamed.py").write_text(
            "# b\n", encoding="utf-8")
        (dev / "src/rl_curriculum/sub/mod_b.py").unlink()
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "removed/renamed" in result["drift_types"]
        assert result["removed_files"] == [
            "src/rl_curriculum/sub/mod_b.py"]

    def test_untracked_runner_script_detected(self, freeze_env):
        """Commit A 后 runner/ 新增脚本(repo 侧 untracked)被检出。"""
        repo, dev, out, head = self._freeze(freeze_env)
        (repo / "stage2_6_1/runner/post_freeze_hotfix.py").write_text(
            "# hotfix\n", encoding="utf-8")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert ("uncommitted_or_untracked_in_freeze_roots"
                in result["drift_types"])

    def test_runner_drift_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        (repo / "stage2_6_1/runner/run.sh").write_text(
            "# changed\n", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "rogue commit B")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "repo_git_identity_drift" in result["drift_types"]
        assert result["head_matches_commit_a"] is False

    def test_tests_drift_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        (repo / "stage2_6_1/tests/route_c_stage2_6_1/tamper_test.py"
         ).write_text("# t\n", encoding="utf-8")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False

    def test_symlink_drift_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        link = dev / "src/rl_curriculum/mod_a.py"
        link.unlink()
        link.symlink_to(dev / "src/rl_curriculum/mod_b.py")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "symlink_target_drift" in result["drift_types"] or (
            "removed/renamed" in result["drift_types"])

    def test_exec_bit_drift_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        target = dev / "requirements-lock.txt"
        target.chmod(0o755)
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "exec_bit_drift" in result["drift_types"]

    def test_missing_freeze_fails_closed(self, freeze_env):
        repo, dev, out, head = freeze_env
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "error" in result

    def test_strategy_file_drift_detected(self, freeze_env):
        repo, dev, out, head = self._freeze(freeze_env)
        (dev / "user_data/strategies/RouteCStrategy.py").write_text(
            "# tampered strategy\n", encoding="utf-8")
        result = verify_r15_code_freeze(out)
        assert result["pass"] is False
        assert "user_data/strategies/RouteCStrategy.py" in (
            result["modified_files"])
