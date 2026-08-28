"""工作包 D:运行时分布内容锁 v2(D2/D3/D4)。

- 方案二:content digest 基于实际文件内容(RECORD 作清单);
- 修改 package 文件但保持 RECORD 不变 -> digest 变化 -> 旧锁失效;
- .so 替换同样被发现;版本号相同内容不同被发现;
- 主进程重算 content digest 与锁内记录对账;
- <missing:package> / RECORD 缺失 / 未注册包 fail closed;
- 子进程 import 的 PoC(引用 A 包)证明 v1 漏检、v2 进程树计数
  暴露。
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json

import pytest

from conftest import attack_request, write_attack_builder
from rl_curriculum.builder_provenance import (
    BuilderProvenanceError,
    check_runtime_lock_against_static,
)
from tests.route_c_stage2_6_0f.conftest import private_provider_from_root

FAMS = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def _dc(env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        env["pack"], required_families=list(FAMS))


def _fake_dist_files():
    """staging 内 fake distribution(evilpkg + dist-info + RECORD)。"""
    init = "VALUE = 'original'\n"
    record_rows = [
        ("evilpkg/__init__.py",
         "sha256=" + hashlib.sha256(init.encode()).hexdigest(), "27"),
        ("evilpkg-1.0.dist-info/METADATA",
         "sha256=" + hashlib.sha256(
             b"Metadata-Version: 2.1\nName: evilpkg\nVersion: 1.0\n"
         ).hexdigest(), "45"),
    ]
    record_text = "\n".join(",".join(r) for r in record_rows) + "\n"
    return {
        "evilpkg/__init__.py": init,
        "evilpkg-1.0.dist-info/METADATA":
            "Metadata-Version: 2.1\nName: evilpkg\nVersion: 1.0\n",
        "evilpkg-1.0.dist-info/RECORD": record_text,
    }


DIST_ENTRY = [{"module": "evilpkg", "version": "1.0"}]


def test_package_file_tamper_record_unchanged_detected(tmp_path):
    """D4 攻击:改 .py 不改 RECORD -> 实际内容摘要变化。"""
    files = _fake_dist_files()
    root = write_attack_builder(
        tmp_path / "dist_ok", "    import evilpkg\n",
        extra_files=files, external_dependencies=DIST_ENTRY,
        label="dist-ok")
    from rl_builder_runtime.runner import distribution_content_digest
    import importlib.metadata as md

    # 注册 fake dist 的路径:runner 内 staging 在 sys.path;主进程
    # 直接对 RECORD 目录计算 digest
    dist_dir = root / "evilpkg-1.0.dist-info"

    class _Dist:
        _path = str(dist_dir)

    d1 = distribution_content_digest(_Dist())
    # 篡改文件,保持 RECORD 不变
    (root / "evilpkg/__init__.py").write_text(
        "VALUE = 'tampered'\n", encoding="utf-8")
    d2 = distribution_content_digest(_Dist())
    assert d1 != d2, "RECORD 不变的文件篡改必须改变实际内容摘要"


def test_so_replacement_detected(tmp_path):
    """D4:.so 替换(内容变)被 content digest 发现。"""
    import shutil

    src = "/usr/lib/x86_64-linux-gnu/libz.so.1"
    try:
        blob = open(src, "rb").read()
    except OSError:
        pytest.skip("系统 libz 不可用")
    files = {
        "evilpkg/_native.so": blob,
        "evilpkg/__init__.py": "import evilpkg._native  # noqa\n",
        "evilpkg-1.0.dist-info/METADATA":
            "Metadata-Version: 2.1\nName: evilpkg\nVersion: 1.0\n",
    }
    root = write_attack_builder(
        tmp_path / "so_ok", "    import evilpkg\n",
        extra_files=files, external_dependencies=DIST_ENTRY,
        label="so-ok")
    from rl_builder_runtime.runner import distribution_content_digest

    record_rows = [
        ("evilpkg/__init__.py",
         "sha256=" + hashlib.sha256(
             files["evilpkg/__init__.py"].encode()).hexdigest(),
         str(len(files["evilpkg/__init__.py"]))),
        ("evilpkg/_native.so",
         "sha256=" + hashlib.sha256(blob).hexdigest(), str(len(blob))),
    ]
    (root / "evilpkg-1.0.dist-info/RECORD").write_text(
        "\n".join(",".join(r) for r in record_rows) + "\n",
        encoding="utf-8")

    class _Dist:
        _path = str(root / "evilpkg-1.0.dist-info")

    d1 = distribution_content_digest(_Dist())
    # 替换 .so(用其它内容)
    other = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    (root / "evilpkg/_native.so").write_bytes(other)
    d2 = distribution_content_digest(_Dist())
    assert d1 != d2


def test_same_version_different_content_distinguished(tmp_path):
    """版本号相同但内容不同 -> digest 不同(旧 evidence 失效)。"""
    files = _fake_dist_files()
    root_a = write_attack_builder(
        tmp_path / "ver_a", "    pass\n", extra_files=files,
        label="ver-a")
    root_b = write_attack_builder(
        tmp_path / "ver_b", "    pass\n", extra_files=files,
        label="ver-b")
    (root_b / "evilpkg/__init__.py").write_text(
        "VALUE = 'different'\n", encoding="utf-8")
    from rl_builder_runtime.runner import distribution_content_digest

    class _DA:
        _path = str(root_a / "evilpkg-1.0.dist-info")

    class _DB:
        _path = str(root_b / "evilpkg-1.0.dist-info")

    assert distribution_content_digest(_DA()) != \
        distribution_content_digest(_DB())


def test_lock_recompute_mismatch_rejected(tmp_path, monkeypatch):
    """主进程重算 content digest 与锁记录不一致 -> 拒绝。"""
    files = _fake_dist_files()
    root = write_attack_builder(
        tmp_path / "lock_ok", "    pass\n", extra_files=files,
        external_dependencies=DIST_ENTRY, label="lock-ok")
    from rl_builder_runtime.runner import distribution_content_digest

    class _Dist:
        _path = str(root / "evilpkg-1.0.dist-info")

    real = distribution_content_digest(_Dist())
    lock = {
        "format": "builder-runtime-lock-v2",
        "python_implementation": "cpython",
        "python_version": "3.11",
        "executable_prefix": "/env",
        "process_tree_policy": "single_builder_process",
        "child_process_count": 0, "exec_count": 0,
        "distributions": [{
            "module": "evilpkg", "distribution": "evilpkg",
            "version": "1.0", "record_sha256": "r" * 64,
            "content_digest": "dcd-" + "0" * 64,
            "verified_files": 2, "imported": ["evilpkg"]}],
        "native_libraries": [],
    }
    import sys
    monkeypatch.syspath_prepend(str(root))
    with pytest.raises(BuilderProvenanceError, match="内容摘要|dcd"):
        check_runtime_lock_against_static(lock, DIST_ENTRY)
    # 修正 digest -> 通过内容校验(其余对账自然通过)
    lock["distributions"][0]["content_digest"] = real
    check_runtime_lock_against_static(lock, DIST_ENTRY)


def test_missing_record_placeholder_rejected():
    lock = {
        "format": "builder-runtime-lock-v2",
        "process_tree_policy": "single_builder_process",
        "child_process_count": 0, "exec_count": 0,
        "distributions": [{
            "module": "x", "distribution": "x", "version": "<missing:x>",
            "record_sha256": "r", "content_digest": "dcd-1",
            "verified_files": 1, "imported": ["x"]}],
        "native_libraries": [],
    }
    with pytest.raises(BuilderProvenanceError, match="missing"):
        check_runtime_lock_against_static(lock, [
            {"module": "x", "version": "<missing:x>"}])


def test_native_libraries_required_in_v2():
    lock = {
        "format": "builder-runtime-lock-v2",
        "process_tree_policy": "single_builder_process",
        "child_process_count": 0, "exec_count": 0,
        "distributions": [],
    }
    with pytest.raises(BuilderProvenanceError, match="native"):
        check_runtime_lock_against_static(lock, [])


def test_runner_lock_records_native_and_tree(sealed_exam_env, tmp_path):
    """真实 Runner 锁:进程树字段 + native 绑定齐全(numpy 链)。"""
    from rl_curriculum.builder_runner import run_isolated_builder_run

    body = "    import numpy\n    assert numpy.__version__\n"
    root = write_attack_builder(
        tmp_path / "np_ok", body,
        external_dependencies=[{"module": "numpy", "version": "2.4.6"}],
        label="np-ok")
    provider = private_provider_from_root(root)
    req = attack_request(provider, sealed_exam_env["pack"],
                         _dc(sealed_exam_env))
    record = run_isolated_builder_run(
        provider.builder_identity(), req, builder_root=root)
    lock = record["runtime_lock"]
    assert lock["format"] == "builder-runtime-lock-v2"
    assert lock["process_tree_policy"] == "single_builder_process"
    assert lock["child_process_count"] == 0
    assert lock["exec_count"] == 0
    mods = {d["module"] for d in lock["distributions"]}
    assert "numpy" in mods
    for d in lock["distributions"]:
        assert d["content_digest"].startswith("dcd-")
        assert d["verified_files"] >= 1
    assert lock["native_libraries"], "native .so 必须被绑定"
    for n in lock["native_libraries"]:
        assert n["sha256"]
        assert n["origin"]


def test_poc_descendant_import_absent_from_lock(sealed_exam_env, tmp_path,
                                                descendant_demo_profile):
    """PoC(与 A 包联动):子进程 import pytest 不出现在锁内——v1
    漏检;v2 进程树计数(child>=1)暴露,evidence 拒绝。"""
    from rl_curriculum.builder_runner import run_isolated_builder_run

    body = (
        "    import subprocess, sys\n"
        "    subprocess.run(\n"
        "        [sys.executable, '-c', 'import pytest'],\n"
        "        capture_output=True, check=True)\n"
    )
    root = write_attack_builder(
        tmp_path / "poc2", body,
        external_dependencies=[{"module": "numpy", "version": "2.4.6"}],
        label="poc2")
    provider = private_provider_from_root(root)
    req = attack_request(provider, sealed_exam_env["pack"],
                         _dc(sealed_exam_env))
    record = run_isolated_builder_run(
        provider.builder_identity(), req, builder_root=root,
        profile=descendant_demo_profile)
    mods = {d["module"] for d in record["runtime_lock"]["distributions"]}
    assert "pytest" not in mods  # 漏检证明(v1 缺陷)
    assert record["child_process_count"] >= 1  # v2 暴露
