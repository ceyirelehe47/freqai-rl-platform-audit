"""P6:builder 运行依赖的完整 import 闭包。

手工少数包清单(python/numpy/pandas)升级为 AST 静态扫描的
实际 import 闭包:rl_curriculum + rl_platform + builder root 内
全部 .py 的 import 语句(模块级与函数级一视同仁),自动覆盖
gymnasium 等第三方依赖。
"""

from __future__ import annotations


def test_closure_covers_gymnasium_and_friends(mock_identity):
    """经 rl_platform.env 模块级 import 进入 builder 验证链的
    gymnasium 必须被依赖闭包覆盖(numpy/pandas 仍被覆盖)。"""
    deps = {d["module"]: d for d in mock_identity.manifest[
        "external_dependencies"]}
    for must in ("rl_platform", "python", "numpy", "pandas",
                 "gymnasium", "cryptography"):
        assert must in deps, must
    for name in ("numpy", "pandas", "gymnasium"):
        v = deps[name]["version"]
        assert v and not v.startswith("<missing"), (name, v)


def test_internal_packages_not_external_entries(mock_identity):
    """内部源码包不作为外部版本条目(rl_platform 用 tree hash,
    rl_candidate_runtime 由 candidate runtime manifest 独立绑定)。"""
    mods = [d["module"]
            for d in mock_identity.manifest["external_dependencies"]]
    assert "rl_curriculum" not in mods
    assert "rl_candidate_runtime" not in mods
    # rl_platform 条目必须是 tree hash 形态而非 package_version
    rl = [d for d in mock_identity.manifest["external_dependencies"]
          if d["module"] == "rl_platform"]
    assert rl and rl[0]["kind"] == "package_tree"
    assert len(rl[0]["tree_hash"]) == 64


def test_private_root_imports_reach_closure(tmp_path):
    """私有 builder root 自己的 import 也进入闭包扫描。"""
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    root = tmp_path / "pb_closure"
    root.mkdir()
    (root / "entry.py").write_text(
        "def build_pack(request):\n"
        "    import hashlib\n"
        "    from rl_curriculum.mock_sealed_exam import (\n"
        "        build_mock_hidden_pack)\n"
        "    import json\n"
        "    return None\n",
        encoding="utf-8")
    prov = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="build_pack")
    mods = [d["module"]
            for d in prov.builder_identity().manifest[
                "external_dependencies"]]
    # stdlib(hashlib/json)不进闭包;rl_curriculum 内部包不进
    assert "hashlib" not in mods and "json" not in mods
    assert "rl_curriculum" not in mods
    assert "numpy" in mods  # 经 rl_curriculum 链


def test_dependency_change_changes_npb(tmp_path):
    """依赖清单内容变化 -> npb- 变化(手动构造两个不同依赖清单的
    Provider,同 root 同入口)。"""
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    root = tmp_path / "pb_deps"
    root.mkdir()
    (root / "entry.py").write_text(
        "def build_pack(request):\n    return None\n", encoding="utf-8")
    deps_a = [
        {"module": "rl_platform", "kind": "package_tree",
         "tree_hash": "0" * 64},
        {"module": "python", "kind": "runtime_version", "version": "3"},
        {"module": "numpy", "kind": "package_version", "version": "1"},
    ]
    deps_b = list(deps_a)
    deps_b.append({"module": "gymnasium", "kind": "package_version",
                   "version": "0.29"})
    h_a = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="build_pack",
        external_dependencies=deps_a).builder_identity().manifest_hash
    h_b = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="build_pack",
        external_dependencies=deps_b).builder_identity().manifest_hash
    assert h_a != h_b


def test_lazy_import_also_covered(tmp_path):
    """函数级(懒)import 属于"实际 import"文本,同样进入闭包
    (fingerprint 的 sklearn/ccxt 懒导入因此被版本绑定)。"""
    from rl_curriculum.builder_identity import _static_import_closure

    root = tmp_path / "lazy"
    root.mkdir()
    (root / "m.py").write_text(
        "X = 1\n"
        "\n"
        "\n"
        "def f():\n"
        "    import some_lazy_pkg\n"
        "    return some_lazy_pkg\n",
        encoding="utf-8")
    out = _static_import_closure([("lazy", root)])
    assert "some_lazy_pkg" in out


def test_stdlib_excluded(tmp_path):
    from rl_curriculum.builder_identity import _static_import_closure

    root = tmp_path / "std"
    root.mkdir()
    (root / "m.py").write_text(
        "import json\nimport hashlib\n", encoding="utf-8")
    out = _static_import_closure([("std", root)])
    # stdlib 不进闭包;rl_platform 链自动并入(builder 总依赖其
    # versions/fingerprint),其外部包(numpy 等)仍出现
    assert "json" not in out and "hashlib" not in out
    assert "numpy" in out
