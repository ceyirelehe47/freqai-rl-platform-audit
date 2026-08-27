"""A1/P3/P4:私有 Builder EntryPoint 真实存在性验证。

Provider 不得只接受 module/qualname 字符串与 manifest 自我声明:
构造期必须用 AST 静态解析 + 受控 import 双重验证入口真实存在、
类型属于预注册允许范围、签名合规且不含禁止参数。
"""

from __future__ import annotations

import pytest


def _write(root: "pytest.TempPathFactory", files: dict) -> "object":
    from pathlib import Path

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


def _provider(root, **kw):
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    defaults = dict(entrypoint_module="builder_x",
                    entrypoint_qualname="build_pack")
    defaults.update(kw)
    return PrivateBuilderIdentityProvider(root, **defaults)


GOOD_ENTRY = {
    "builder_x.py": (
        "def build_pack(request):\n"
        "    return None\n"
    ),
}


def test_module_source_missing_rejected(tmp_path):
    """module 拼写错误/入口文件缺失 -> 构造期拒绝。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b1", dict(GOOD_ENTRY))
    with pytest.raises(BuilderIdentityError, match="源文件不存在"):
        _provider(root, entrypoint_module="builder_missing")


def test_module_path_escape_rejected(tmp_path):
    """module 含路径逃逸成分 -> 拒绝(源文件必须位于受信 root 内)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b2", dict(GOOD_ENTRY))
    with pytest.raises(BuilderIdentityError):
        _provider(root, entrypoint_module="../builder_x")


def test_qualname_missing_rejected(tmp_path):
    """qualname 指向不存在的符号 -> 拒绝(不以字符串搜索判定)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b3", dict(GOOD_ENTRY))
    with pytest.raises(BuilderIdentityError, match="不是.*真实的函数定义"):
        _provider(root, entrypoint_qualname="build_pack_typo")


def test_qualname_string_literal_rejected(tmp_path):
    """qualname 指向模块级字符串变量 -> 拒绝(不是函数定义)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b4", {
        "builder_x.py": (
            "BUILD_PACK = 'def build_pack(request): ...'\n"
            "\n"
            "\n"
            "def real_entry(request):\n"
            "    return None\n"
        ),
    })
    with pytest.raises(BuilderIdentityError, match="不是.*真实的函数定义"):
        _provider(root, entrypoint_qualname="BUILD_PACK")


def test_qualname_comment_only_rejected(tmp_path):
    """入口只存在于注释中 -> 拒绝(注释不是 AST 函数定义节点)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b5", {
        "builder_x.py": (
            "# def build_pack(request):\n"
            "#     return None\n"
            "X = 1\n"
        ),
    })
    with pytest.raises(BuilderIdentityError, match="不是.*真实的函数定义"):
        _provider(root)


def test_qualname_class_constructor_rejected(tmp_path):
    """qualname 指向类(构造器) -> 拒绝(类型白名单)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b6", {
        "builder_x.py": (
            "class build_pack:\n"
            "    def __init__(self, request):\n"
            "        pass\n"
        ),
    })
    with pytest.raises(BuilderIdentityError,
                       match="类型.*不在预注册允许范围|类构造器"):
        _provider(root)


def test_qualname_async_function_rejected(tmp_path):
    """协程函数 -> 拒绝(协议 v1 是同步 build_pack)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b7", {
        "builder_x.py": (
            "async def build_pack(request):\n"
            "    return None\n"
        ),
    })
    with pytest.raises(BuilderIdentityError, match="不在预注册允许范围"):
        _provider(root)


def test_class_method_entrypoint_accepted(tmp_path):
    """Class.method 形态(预注册允许范围) -> 通过,kind=classfunction。"""
    root = _write(tmp_path / "b8", {
        "builder_x.py": (
            "class Runner:\n"
            "    @classmethod\n"
            "    def build_pack(cls, request):\n"
            "        return None\n"
        ),
    })
    prov = _provider(root, entrypoint_qualname="Runner.build_pack")
    identity = prov.builder_identity()
    ep = identity.manifest["entrypoints_validated"]["entrypoint"]
    assert ep["kind"] == "classfunction"
    assert ep["qualname"] == "Runner.build_pack"


def test_forbidden_signature_rejected_at_construction(tmp_path):
    """P4:签名含 candidate/checkpoint/model/policy -> 构造期动态拒绝
    (不再是 manifest 自我声明)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    for bad in ("candidate", "checkpoint", "model", "policy"):
        root = _write(tmp_path / f"b9_{bad}", {
            "builder_x.py": (
                f"def build_pack(request, {bad}=None):\n"
                f"    return None\n"
            ),
        })
        with pytest.raises(BuilderIdentityError,
                           match=f"禁止参数.*{bad}"):
            _provider(root)


def test_request_protocol_no_positional_rejected(tmp_path):
    """build 入口不接受 request 位置参数 -> 拒绝(runner 协议合同)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b10", {
        "builder_x.py": (
            "def build_pack():\n"
            "    return None\n"
        ),
    })
    with pytest.raises(BuilderIdentityError, match="不接受.*构建请求"):
        _provider(root)


def test_good_entrypoint_report(tmp_path):
    """真实函数入口 -> 通过并生成验证报告(进入 manifest v3)。"""
    root = _write(tmp_path / "b11", dict(GOOD_ENTRY))
    prov = _provider(root)
    identity = prov.builder_identity()
    ep = identity.manifest["entrypoints_validated"]["entrypoint"]
    assert ep["kind"] == "function"
    assert ep["qualname"] == "build_pack"
    assert ep["signature_params"] == ["request"]
    assert ep["request_protocol"] is True
    assert len(ep["source_sha256"]) == 64
    # 入口可执行且与 AST 定位一致
    assert callable(prov.builder_entrypoint())
    assert prov.builder_entrypoint().__name__ == "build_pack"


def test_attempt_loop_also_validated(tmp_path):
    """attempt-loop 同样通过真实存在性验证(缺失即拒绝)。"""
    from rl_curriculum.builder_identity import BuilderIdentityError

    root = _write(tmp_path / "b12", dict(GOOD_ENTRY))
    with pytest.raises(BuilderIdentityError):
        _provider(root, attempt_loop_module="builder_x",
                  attempt_loop_qualname="attempt_loop_missing")
    prov = _provider(root, attempt_loop_module="builder_x",
                     attempt_loop_qualname="build_pack")
    report = prov.builder_identity().manifest["entrypoints_validated"]
    assert "attempt_loop" in report


def test_mock_provider_entrypoint_validated(mock_identity):
    """mock Provider 的入口同样走 A1 验证链(runner 协议单参数)。"""
    m = mock_identity.manifest
    ep = m["entrypoints_validated"]["entrypoint"]
    assert ep["qualname"] == "mock_build_pack"
    assert ep["kind"] == "function"
    assert ep["request_protocol"] is True
    assert m["format"] == "null-pack-builder-manifest-v3"
    assert "gymnasium" in [d["module"]
                           for d in m["external_dependencies"]]


def test_stale_module_cache_not_reused(tmp_path):
    """同名 module 的陈旧缓存(其他 root 遗留)不得被复用:两个不同
    root 各有 builder_x(内容不同),第二个 Provider 必须导入本 root
    的代码(tree hash 不同可证)。"""
    root1 = _write(tmp_path / "c1", dict(GOOD_ENTRY))
    root2 = _write(tmp_path / "c2", {
        "builder_x.py": (
            "MARKER = 'second-root'\n"
            "\n"
            "\n"
            "def build_pack(request):\n"
            "    return None\n"
        ),
    })
    p1 = _provider(root1)
    p2 = _provider(root2)
    assert (p1.builder_identity().manifest_hash
            != p2.builder_identity().manifest_hash)
    obj = p2.builder_entrypoint()
    assert obj.__globals__.get("MARKER") == "second-root"
