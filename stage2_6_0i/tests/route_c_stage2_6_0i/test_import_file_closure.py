"""工作包 A2/A3/E4:实际导入文件闭包(真实生产路径 + 单元语义)。

- 真实 Runner:numpy 导入的每个模块进入 import_closure,文件在
  bundle 内且字节绑定 sha256;分布归属 by-path(file+sha256);
- E4:从 scratch 动态加载代码 / SourceFileLoader 指向 manifest 外
  文件 / 自定义 import hook -> fail closed(构建失败);
- A2 单元语义:zipimport(bundled zip 允许/外部拒绝)、namespace
  package search location 校验、多义归属拒绝(复用 runner 的
  _module_entry 与 manifest 结构)。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

pytestmark = pytest.mark.stage2_6_0i

TESTS = Path(__file__).resolve().parents[1]


def test_real_numpy_import_closure(run_attack):
    """真实链路:builder import numpy -> 闭包覆盖 numpy 子模块,
  文件+sha256+归属齐备;native 库进入锁(quiesce 外部实测)。"""
    import numpy

    run = run_attack(
        "    import numpy as np\n"
        "    v = float(np.random.default_rng(7).random())\n"
        "    notes = {'v': v}\n",
        external_dependencies=[{"module": "numpy",
                                "version": numpy.__version__}],
        label="np-closure", max_attempts=1)
    assert isinstance(run, dict), run
    lock = run["runtime_lock"]
    closure = lock["import_closure"]
    numpy_entries = [e for e in closure
                     if e["module"] == "numpy" or
                     e["module"].startswith("numpy.")]
    assert numpy_entries, "numpy 未进入导入闭包"
    for e in numpy_entries:
        if e["origin_kind"] == "file":
            assert e["file"].startswith("/lib/python3.11/site-packages/")
            assert len(e["sha256"]) == 64
            assert e["owner"] == "distribution"
            assert e["distribution"] == "numpy"
    dist = next(d for d in lock["distributions"] if d["module"] == "numpy")
    assert dist["file"] and len(dist["sha256"]) == 64
    # native:quiesce 外部实测的 .so 绑定
    assert lock["native_libraries"]
    for n in lock["native_libraries"]:
        assert n["path"].startswith("/lib"), n["path"]
        assert n["origin"] == "runtime-bundle"
        assert len(n["sha256"]) == 64


def test_scratch_dynamic_load_rejected(run_attack):
    """E4:builder 在 scratch 写代码并动态导入 -> 该文件不在 manifest
  -> fail closed。"""
    outcome = run_attack(
        "    import importlib\n"
        "    with open('/scratch/hidden_mod.py', 'w') as fh:\n"
        "        fh.write('X = 1\\n')\n"
        "    import sys\n"
        "    sys.path.insert(0, '/scratch')\n"
        "    import hidden_mod\n"
        "    notes = {'x': hidden_mod.X}\n",
        label="scratch-load", max_attempts=1)
    assert not isinstance(outcome, dict), "scratch 动态加载未被拒绝"
    name, msg = outcome
    assert "闭包" in msg or "manifest" in msg or "fail closed" in msg, \
        outcome


def test_custom_import_hook_rejected(run_attack):
    """E4:自定义 meta_path hook 注入模块 -> loader 不在白名单 ->
  fail closed。"""
    outcome = run_attack(
        "    import importlib.abc, importlib.util, sys, types\n"
        "    class EvilFinder(importlib.abc.MetaPathFinder):\n"
        "        def find_spec(self, fullname, path=None, target=None):\n"
        "            if fullname == 'evil_mod':\n"
        "                spec = importlib.util.spec_from_loader(\n"
        "                    fullname, EvilLoader())\n"
        "                return spec\n"
        "    class EvilLoader(importlib.abc.Loader):\n"
        "        def create_module(self, spec):\n"
        "            m = types.ModuleType(spec.name)\n"
        "            m.X = 1\n"
        "            return m\n"
        "        def exec_module(self, module):\n"
        "            pass\n"
        "    sys.meta_path.insert(0, EvilFinder())\n"
        "    import evil_mod\n"
        "    notes = {'x': evil_mod.X}\n",
        label="custom-hook", max_attempts=1)
    assert not isinstance(outcome, dict), "自定义 loader 未被拒绝"


# ------------------------------------------------------------ A2 单元语义
def _closure_for_module(name, mod, manifest, meta, root="/"):
    _closure_for_module._root = root
    from rl_builder_runtime.runner import _module_entry

    manifest_files = {e["path"]: e["sha256"]
                      for e in manifest["entries"] if e.get("type") == "file"}
    manifest_dirs = {e["path"] for e in manifest["entries"]
                     if e.get("type") == "dir"}
    owners = dict(meta.get("dist_ownership") or {})
    ambiguous = {a["path"] for a in (meta.get("ambiguous_dist_paths") or [])
                 if "path" in a}
    import sys as _sys

    root = getattr(_closure_for_module, "_root", "/")
    return _module_entry(
        name, mod, manifest_files=manifest_files,
        manifest_dirs=manifest_dirs, owners=owners,
        ambiguous_paths=ambiguous,
        stdlib_names=frozenset(_sys.stdlib_module_names),
        root=root)


def _mini_manifest_meta(tmp_path, *, with_zip: bool = False):
    """mini env 组装 bundle,返回 (staging, manifest, meta)。

    with_zip:在 site-packages 放一个 zip 归档(进入 manifest,
    用于 bundled zip 语义)。
    """
    from rl_builder_runtime.bundle import assemble_runtime_bundle

    sys.path.insert(0, str(TESTS))
    sys.path.insert(0, str(TESTS / "route_c_stage2_6_0i"))
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "cf0i", TESTS / "route_c_stage2_6_0i" / "conftest.py")
    cf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cf)
    env = cf.make_mini_env(tmp_path)
    if with_zip:
        import zipfile

        with zipfile.ZipFile(
                env / "lib/python3.11/site-packages/zmod.zip", "w") as zf:
            zf.writestr("zmod.py", "X = 1\n")
    pkg = tmp_path / "pkgx"
    pkg.mkdir()
    (pkg / "b.py").write_text("pass\n")
    info = assemble_runtime_bundle(
        env_root=env, staging_root=tmp_path / "stg",
        runtime_src=TESTS.parent / "src" / "rl_builder_runtime",
        builder_pkg_root=pkg, jobs=1)
    return tmp_path / "stg", info["manifest"], info["meta"]


def test_bundled_zip_allowed_external_rejected(tmp_path):
    """E4:bundled zip(zip 文件本身在 manifest)允许并绑定;zip 外
  归档拒绝。"""
    staging, manifest, meta = _mini_manifest_meta(tmp_path, with_zip=True)
    zpath = str(staging / "lib/python3.11/site-packages/zmod.zip")
    mod = types.ModuleType("zmod")
    mod.__file__ = zpath
    spec = types.SimpleNamespace(
        loader=type("zipimporter", (), {})(), origin=zpath)
    mod.__spec__ = spec
    entry = _closure_for_module("zmod", mod, manifest, meta,
                                root=str(staging))
    assert entry["origin_kind"] == "zip-bundled"
    assert len(entry["sha256"]) == 64
    # bundle 外 zip -> 拒绝
    mod2 = types.ModuleType("zmod2")
    mod2.__file__ = "/tmp/evil.zip"
    mod2.__spec__ = types.SimpleNamespace(
        loader=type("zipimporter", (), {})(), origin="/tmp/evil.zip")
    from rl_builder_runtime.runner import _ClosureError

    with pytest.raises(_ClosureError, match="bundle 外"):
        _closure_for_module("zmod2", mod2, manifest, meta)


def test_namespace_search_locations_validated(tmp_path):
    """A2:namespace package 的 search location 必须是 manifest 目录。"""
    staging, manifest, meta = _mini_manifest_meta(tmp_path)
    staging_path = str(staging / "lib/python3.11/site-packages/nsp")
    good = types.ModuleType("nsp")
    spec = types.SimpleNamespace(
        loader=None, origin=None,
        submodule_search_locations=[staging_path])
    good.__spec__ = spec
    entry = _closure_for_module("nsp", good, manifest, meta,
                                root=str(staging))
    assert entry["origin_kind"] == "namespace-package"
    bad = types.ModuleType("nsp2")
    bad.__spec__ = types.SimpleNamespace(
        loader=None, origin=None,
        submodule_search_locations=["/definitely_not_in_bundle"])
    from rl_builder_runtime.runner import _ClosureError

    with pytest.raises(_ClosureError, match="search location"):
        _closure_for_module("nsp2", bad, manifest, meta,
                            root=str(staging))


def test_ambiguous_owner_rejected(tmp_path):
    """A2:模块文件被多个 distribution 声明 -> fail closed。"""
    staging, manifest, meta = _mini_manifest_meta(tmp_path)
    # 手工注入多义声明
    meta = dict(meta)
    target = "lib/python3.11/site-packages/nsp/b_impl.py"
    meta["dist_ownership"] = {target: ["nspkg_a", "nspkg_b"]}
    meta["ambiguous_dist_paths"] = [{"path": target,
                                     "distributions": ["nspkg_a",
                                                       "nspkg_b"]}]
    mod = types.ModuleType("nsp.b_impl")
    mod.__file__ = str(staging / "lib/python3.11/site-packages/"
                                 "nsp/b_impl.py")
    mod.__spec__ = types.SimpleNamespace(loader=None, origin=mod.__file__)
    from rl_builder_runtime.runner import _ClosureError

    with pytest.raises(_ClosureError, match="多义|多个"):
        _closure_for_module("nsp.b_impl", mod, manifest, meta,
                            root=str(staging))
