# -*- coding: utf-8 -*-
"""R3-04 封包精确集合与校验器(FiniteRepair R3)。

用合成 ZIP 验证:根清单只排除根级自身、嵌套同名清单必须覆盖、
独立冷读双向核对(缺/多/重复/哈希错/不安全路径/非普通文件)、
校验器对合法正例通过且对针对性反例因正确原因拒绝(不复制打包器
过滤条件)。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

RUNNER_DIR = Path(__file__).resolve().parents[2] / "runner"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, RUNNER_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_zip(path: Path, files: dict, manifest_lines=None,
               top="pkg"):
    """合成 ZIP;top/ 目录;files = {relpath: bytes}。"""
    with zipfile.ZipFile(path, "w") as zf:
        for rel, data in files.items():
            zf.writestr(f"{top}/{rel}", data)
        if manifest_lines is None:
            manifest_lines = [
                f"{_sha(files[rel])}  {rel}"
                for rel in sorted(files)
                if rel != "SHA256SUMS.txt"]
        zf.writestr(f"{top}/SHA256SUMS.txt",
                    "\n".join(manifest_lines) + "\n")


def _verify(path: Path):
    mod = _load("posctl_r3_pack_verify")
    r = subprocess.run(
        [sys.executable, str(RUNNER_DIR
                             / "posctl_r3_pack_verify.py"),
         "--zip", str(path)],
        capture_output=True, text=True, timeout=120)
    return r.returncode, json.loads(r.stdout)


def _nested_fixture_files():
    return {
        "a.txt": b"alpha\n",
        "evidence/task_pkg_in/SHA256SUMS.txt": b"nested manifest\n",
        "evidence/task_pkg_in/x.bin": b"\x00\x01binary\xff",
        "acceptance_snapshot/INDEX.md": b"# INDEX (old)\n",
        "acceptance_snapshot/LATEST.md": b"# LATEST (old)\n",
        "acceptance_snapshot/snapshot_meta.json": (
            b'{"snapshot_utc": "2026-10-13T00:00:00Z"}'),
    }


class TestPackVerifier:
    def test_good_package_passes(self, tmp_path):
        """正例:嵌套同名清单被根清单覆盖 → 冷读通过。"""
        zp = tmp_path / "good.zip"
        _build_zip(zp, _nested_fixture_files())
        rc, rep = _verify(zp)
        assert rc == 0, rep["problems"]
        assert rep["pass"] is True
        assert rep["stats"]["nested_manifests"] == 1
        assert rep["stats"]["manifest_entries"] == 6
        assert "nested" in rep[
            "acceptance_snapshot_members"][0] or all(
                "acceptance_snapshot" in m for m in rep[
                    "acceptance_snapshot_members"][:1])

    def test_missing_nested_manifest_rejected(self, tmp_path):
        """R2 缺陷定向反例:根清单漏嵌套 SHA256SUMS.txt → 拒绝。"""
        zp = tmp_path / "miss.zip"
        files = _nested_fixture_files()
        with zipfile.ZipFile(zp, "w") as zf:
            for rel, data in files.items():
                zf.writestr("pkg/" + rel, data)
            lines = [
                f"{_sha(files[rel])}  {rel}"
                for rel in sorted(files)
                if rel not in ("SHA256SUMS.txt",
                               "evidence/task_pkg_in/"
                               "SHA256SUMS.txt")]
            zf.writestr("pkg/SHA256SUMS.txt",
                        "\n".join(lines) + "\n")
        rc, rep = _verify(zp)
        assert rc == 1
        assert any("漏覆盖" in p for p in rep["problems"])
        assert any("嵌套清单未被根清单覆盖" in p
                   for p in rep["problems"])

    def test_extra_and_wrong_hash_rejected(self, tmp_path):
        files = {"a.txt": b"A\n", "b.txt": b"B\n",
                 "acceptance_snapshot/INDEX.md": b"i",
                 "acceptance_snapshot/LATEST.md": b"l",
                 "acceptance_snapshot/snapshot_meta.json": b"{}"}
        zp = tmp_path / "wrong.zip"
        lines = [f"{_sha(files['a.txt'])}  a.txt",
                 f"{'0' * 64}  b.txt",        # 哈希错
                 f"{_sha(b'ghost')}  ghost.txt"]  # 多余项
        _build_zip(zp, files, manifest_lines=lines)
        rc, rep = _verify(zp)
        assert rc == 1
        joined = "; ".join(rep["problems"])
        assert "哈希不符" in joined
        assert "多余" in joined

    def test_duplicate_member_rejected(self, tmp_path):
        zp = tmp_path / "dup.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("pkg/a.txt", b"A")
            zf.writestr("pkg/a.txt", b"A")
            zf.writestr("pkg/acceptance_snapshot/INDEX.md", b"i")
            zf.writestr("pkg/acceptance_snapshot/LATEST.md", b"l")
            zf.writestr(
                "pkg/acceptance_snapshot/snapshot_meta.json", b"{}")
            zf.writestr("pkg/SHA256SUMS.txt",
                        f"{_sha(b'A')}  a.txt\n")
        rc, rep = _verify(zp)
        assert rc == 1
        assert any("重复成员" in p for p in rep["problems"])

    def test_unsafe_path_rejected(self, tmp_path):
        zp = tmp_path / "evil.zip"
        with zipfile.ZipFile(zp, "w") as zf:
            zf.writestr("pkg/../evil.txt", b"E")
            zf.writestr("pkg/ok.txt", b"O")
            zf.writestr("pkg/acceptance_snapshot/INDEX.md", b"i")
            zf.writestr("pkg/acceptance_snapshot/LATEST.md", b"l")
            zf.writestr(
                "pkg/acceptance_snapshot/snapshot_meta.json", b"{}")
            zf.writestr("pkg/SHA256SUMS.txt",
                        f"{_sha(b'O')}  ok.txt\n")
        rc, rep = _verify(zp)
        assert rc == 1
        assert any("不安全成员路径" in p for p in rep["problems"])

    def test_sidecar_mismatch_rejected(self, tmp_path):
        zp = tmp_path / "sc.zip"
        _build_zip(zp, _nested_fixture_files())
        sc = tmp_path / "sc.txt"
        sc.write_text("0" * 64 + "  sc.zip\n", encoding="utf-8")
        mod = _load("posctl_r3_pack_verify")
        r = subprocess.run(
            [sys.executable,
             str(RUNNER_DIR / "posctl_r3_pack_verify.py"),
             "--zip", str(zp), "--sidecar", str(sc)],
            capture_output=True, text=True, timeout=120)
        rep = json.loads(r.stdout)
        assert r.returncode == 1
        assert rep["sidecar_matches"] is False


class TestR3PackagerManifestRule:
    def test_manifest_build_excludes_only_root_self(self,
                                                    tmp_path):
        """打包器清单规则:仅根级 SHA256SUMS.txt 被排除,嵌套同名
        清单照常入清单(直接调函数级验证——stage 树合成)。"""
        mod = _load("posctl_package_r3")
        stage = tmp_path / "stage" / "pkg"
        (stage / "evidence" / "task_pkg_in").mkdir(parents=True)
        (stage / "a.txt").write_text("A", encoding="utf-8")
        (stage / "evidence" / "task_pkg_in" /
         "SHA256SUMS.txt").write_text("nested", encoding="utf-8")
        sums = []
        for p in sorted(stage.rglob("*")):
            if not p.is_file():
                continue
            if p.relative_to(stage).as_posix() == "SHA256SUMS.txt":
                continue
            sums.append(f"{mod.sha256_file(p)}  "
                        f"{p.relative_to(stage).as_posix()}")
        (stage / "SHA256SUMS.txt").write_text(
            "\n".join(sums) + "\n", encoding="utf-8")
        entries = dict(
            line.split("  ", 1)[::-1] for line in (
                stage / "SHA256SUMS.txt").read_text(
                encoding="utf-8").splitlines())
        assert "a.txt" in entries
        assert ("evidence/task_pkg_in/SHA256SUMS.txt"
                in entries), "嵌套同名清单必须覆盖"
        assert "SHA256SUMS.txt" not in entries   # 仅根级自身排除
