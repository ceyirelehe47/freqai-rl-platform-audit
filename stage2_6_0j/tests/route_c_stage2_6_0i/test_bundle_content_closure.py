"""工作包 A:runtime bundle 内容闭包(A1/A4/A5;mini_env 载体)。

- 组装键与摘要:相同内容两次组装 -> 相同 rbm-(内容寻址确定性);
- E1(RECORD 外文件):组装前新增未登记文件 -> 进入 manifest(绑定);
  组装后新增 staging 文件 -> verify 拒绝;
- A4(RECORD 解析):标准 csv;重复/绝对/../非 sha256 哈希拒绝;
  无哈希条目显式记录;URL-safe base64 校验;
- A5(符号链接/特殊文件):相对目标绑定;绝对逃逸拒绝;FIFO/设备
  拒绝;组装后内容/目标篡改 -> verify 拒绝(E10);
- E3(归属映射):namespace 包两个 distribution 的 by-path 归属;
  同一路径被两个 dist 声明 -> 多义记录。
"""

from __future__ import annotations

import json
import os
import shutil

import pytest

from rl_builder_runtime.bundle import (
    BUNDLE_MANIFEST_FILENAME,
    BundleError,
    assemble_runtime_bundle,
    bundle_manifest_digest,
    deterministic_entropy_bytes,
    dist_ownership_from_bundle,
    load_bundle_manifest,
    load_bundle_meta,
    parse_record_csv,
    verify_runtime_bundle,
)

SRC_RT = os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))) + "/src/rl_builder_runtime"


def _tiny_pkg(tmp_path, tag="bp"):
    pkg = tmp_path / f"bp-{tag}"
    pkg.mkdir()
    (pkg / "builder_x.py").write_text("def build_pack(r):\n    return 1\n")
    return pkg


def _assemble(mini_env, tmp_path, label="b1", jobs=1):
    return assemble_runtime_bundle(
        env_root=mini_env, staging_root=tmp_path / label,
        runtime_src=SRC_RT, builder_pkg_root=_tiny_pkg(tmp_path, label),
        jobs=jobs)


# ------------------------------------------------------------ A1 摘要确定性
def test_same_content_same_digest(mini_env, tmp_path):
    """相同 env 内容两次组装 -> 相同 manifest 摘要(内容寻址)。"""
    info1 = _assemble(mini_env, tmp_path, "b1")
    # 第二次:换一个 staging 目录,内容一致
    info2 = assemble_runtime_bundle(
        env_root=mini_env, staging_root=tmp_path / "b2",
        runtime_src=SRC_RT, builder_pkg_root=_tiny_pkg(tmp_path, "b2"),
        jobs=1)
    assert info1["digest"] == info2["digest"]
    assert info1["digest"].startswith("rbm-")
    assert info2["manifest"]["entries"], "manifest 必须非空"


def test_env_content_change_changes_digest(mini_env, tmp_path):
    """env 中已安装文件被修改 -> manifest 摘要变化(0h 阻塞 A 的
    '改 package 文件 RECORD 不变'攻击在 bundle 层被发现)。"""
    before = _assemble(mini_env, tmp_path, "b1")["digest"]
    target = mini_env / "lib" / "python3.11" / "site-packages" / \
        "nsp" / "a_impl.py"
    target.write_text("VALUE = 'tampered'\n")
    after = _assemble(mini_env, tmp_path, "b2")["digest"]
    assert before != after


# ------------------------------------------------------------ E1 RECORD 外文件
def test_unrecorded_file_bound_when_assembled_before(mini_env, tmp_path):
    """组装前在合法 distribution 包根新增 hidden.py(不进 RECORD):
    文件必须进入 manifest 并被绑定(可见即受承诺)。"""
    hidden = mini_env / "lib" / "python3.11" / "site-packages" / \
        "nsp" / "_hidden_builder.py"
    hidden.write_text("HIDDEN = 0xdeadbeef\n")
    info = _assemble(mini_env, tmp_path, "b1")
    paths = {e["path"] for e in info["manifest"]["entries"]}
    assert "lib/python3.11/site-packages/nsp/_hidden_builder.py" in paths
    entry = next(e for e in info["manifest"]["entries"]
                 if e["path"].endswith("_hidden_builder.py"))
    assert entry["sha256"] and len(entry["sha256"]) == 64


def test_extra_file_after_assembly_rejected(mini_env, tmp_path):
    """组装后在 staging 新增文件 -> verify 结构拒绝(bundle 建立后
    新增即 TOCTOU 拒绝)。"""
    info = _assemble(mini_env, tmp_path, "b1")
    (tmp_path / "b1" / "lib" / "python3.11" / "os.py.hidden").write_text(
        "x = 2\n")
    core = {k: v for k, v in info["manifest"].items()
            if k != "manifest_digest"}
    with pytest.raises(BundleError, match="额外"):
        verify_runtime_bundle(tmp_path / "b1", core, jobs=1)


def test_content_tamper_after_assembly_rejected(mini_env, tmp_path):
    """组装后 staging 文件内容被改(同尺寸也行) -> verify 哈希拒绝。"""
    info = _assemble(mini_env, tmp_path, "b1")
    target = tmp_path / "b1" / "lib" / "python3.11" / "os.py"
    target.write_text(target.read_text() + "# t\n")
    core = {k: v for k, v in info["manifest"].items()
            if k != "manifest_digest"}
    with pytest.raises(BundleError, match="内容与 manifest 不一致"):
        verify_runtime_bundle(tmp_path / "b1", core, jobs=1)


def test_missing_file_after_assembly_rejected(mini_env, tmp_path):
    info = _assemble(mini_env, tmp_path, "b1")
    (tmp_path / "b1" / "lib" / "python3.11" / "os.py").unlink()
    core = {k: v for k, v in info["manifest"].items()
            if k != "manifest_digest"}
    with pytest.raises(BundleError, match="缺失"):
        verify_runtime_bundle(tmp_path / "b1", core, jobs=1)


# ------------------------------------------------------------ A5 链接与特殊文件
def test_relative_symlink_bound_and_tamper_detected(mini_env, tmp_path):
    """相对符号链接被绑定(链接+目标);组装后替换目标 -> 拒绝。"""
    env_bin = mini_env / "bin"
    os.symlink("python3.11", env_bin / "python")
    info = _assemble(mini_env, tmp_path, "b1")
    entry = next(e for e in info["manifest"]["entries"]
                 if e["path"] == "bin/python")
    assert entry["type"] == "symlink" and entry["target"] == "python3.11"
    # 篡改链接目标
    (tmp_path / "b1" / "bin" / "python").unlink()
    os.symlink("nonexistent", tmp_path / "b1" / "bin" / "python")
    core = {k: v for k, v in info["manifest"].items()
            if k != "manifest_digest"}
    with pytest.raises(BundleError, match="符号链接目标变化"):
        verify_runtime_bundle(tmp_path / "b1", core, jobs=1)


def test_absolute_escaping_symlink_rejected(mini_env, tmp_path):
    """绝对路径逃逸 env 根的符号链接在组装期拒绝(A5)。"""
    os.symlink("/etc/hostname", mini_env / "bin" / "evil")
    with pytest.raises(BundleError, match="逃逸"):
        _assemble(mini_env, tmp_path, "b1")


def test_fifo_rejected(mini_env, tmp_path):
    """FIFO/设备/socket 等特殊文件拒绝进入 bundle(A5)。"""
    os.mkfifo(mini_env / "lib" / "python3.11" / "pipe")
    with pytest.raises(BundleError, match="非普通文件"):
        _assemble(mini_env, tmp_path, "b1")


# ------------------------------------------------------------ A4 RECORD 解析
def test_record_csv_rejects_duplicate_paths():
    text = ("a.py,sha256=" + "A" * 43 + ",10\n"
            "a.py,sha256=" + "B" * 43 + ",10\n")
    with pytest.raises(BundleError, match="重复路径"):
        parse_record_csv(text, label="t")


def test_record_csv_rejects_absolute_and_flags_traversal():
    """绝对路径无条件拒绝;../ 层级(pip 脚本惯例)保留并标记
    traversal(由归属映射保证最终解析仍在 bundle 内,越界记入
    escape 标志——等强度:越界路径不进入归属映射)。"""
    with pytest.raises(BundleError, match="绝对"):
        parse_record_csv("/etc/passwd,sha256=" + "A" * 43 + ",1\n",
                         label="t")
    entries = parse_record_csv(
        "../../bin/f2py,sha256=" + "A" * 43 + ",1\n", label="t")
    assert entries[0]["traversal"] is True
    flat = parse_record_csv("plain/x.py,sha256=" + "A" * 43 + ",1\n",
                            label="t")
    assert flat[0]["traversal"] is False


def test_record_csv_urlsafe_base64_and_no_hash_entries():
    import base64
    import hashlib

    good = base64.urlsafe_b64encode(
        hashlib.sha256(b"x").digest()).rstrip(b"=").decode()
    entries = parse_record_csv(
        f"m.py,sha256={good},1\nplain.txt,,0\n", label="t")
    assert entries[0]["sha256"] == hashlib.sha256(b"x").hexdigest()
    assert entries[1]["sha256"] is None  # 无哈希条目显式记录
    with pytest.raises(BundleError, match="base64"):
        parse_record_csv("m.py,sha256=NOT_BASE64_!!,1\n", label="t")
    with pytest.raises(BundleError, match="字段不足"):
        parse_record_csv("only-path\n", label="t")


def test_record_csv_handles_comma_quoted_filenames():
    """文件名含逗号/引号:标准 csv 正确解析(0h split(",") 的缺陷)。"""
    import base64
    import hashlib

    good = base64.urlsafe_b64encode(
        hashlib.sha256(b"x").digest()).rstrip(b"=").decode()
    entries = parse_record_csv(
        f'"weird,name.py",sha256={good},3\n', label="t")
    assert entries[0]["path"] == "weird,name.py"


# ------------------------------------------------------------ E3 归属映射
def test_namespace_package_by_path_ownership(mini_env, tmp_path):
    """namespace 包 nsp 的模块按**实际文件路径**归属到两个 distribution
    (不再按名称排序取第一个);同路径多声明进入多义记录。"""
    info = _assemble(mini_env, tmp_path, "b1")
    meta = load_bundle_meta(tmp_path / "b1")
    owners = meta["dist_ownership"]
    a = "lib/python3.11/site-packages/nsp/a_impl.py"
    b = "lib/python3.11/site-packages/nsp/b_impl.py"
    assert owners.get(a) == ["nspkg_a"]
    assert owners.get(b) == ["nspkg_b"]
    # 同一路径被两个 dist 的 RECORD 声明 -> 多义(RECORD 路径相对
    # site-packages)
    di = mini_env / "lib" / "python3.11" / "site-packages" / \
        "nspkg_a.dist-info" / "RECORD"
    di.write_text(di.read_text() + "nsp/b_impl.py,,\n")
    _assemble(mini_env, tmp_path, "b2")
    meta2 = load_bundle_meta(tmp_path / "b2")
    assert any(x.get("path") == b for x in meta2["ambiguous_dist_paths"])


# ------------------------------------------------------------ 熵源/自洽
def test_deterministic_entropy_stable():
    e1 = deterministic_entropy_bytes()
    e2 = deterministic_entropy_bytes()
    assert e1 == e2 and len(e1) == 65536


def test_manifest_self_consistency_and_files(mini_env, tmp_path):
    info = _assemble(mini_env, tmp_path, "b1")
    manifest = load_bundle_manifest(tmp_path / "b1")
    assert manifest["manifest_digest"] == info["digest"]
    # 自身被改 -> 拒绝
    p = tmp_path / "b1" / BUNDLE_MANIFEST_FILENAME
    data = json.loads(p.read_text())
    data["entries"][0]["sha256"] = "0" * 64
    p.write_text(json.dumps(data))
    with pytest.raises(BundleError, match="不自洽"):
        load_bundle_manifest(tmp_path / "b1")


def test_syslib_closure_resolved(mini_env, tmp_path):
    """mini env 的 python ELF 依赖进入系统库闭包(libc 等)。"""
    info = _assemble(mini_env, tmp_path, "b1")
    sonames = set(info["manifest"]["syslib_sonames"])
    assert "libc.so.6" in sonames or "ld-linux-x86-64.so.2" in sonames
    staged = (tmp_path / "b1" / "lib64" / "ld-linux-x86-64.so.2")
    assert staged.is_file(), "动态链接器必须进入 bundle"
