"""阶段 2.6.0g 收尾:A1 entrypoint 静态验证(C1 精确单参 + 主进程零 import)。

- AST 静态解析:注释/字符串/赋值/不存在符号天然被拒;
- 入口类型白名单(类构造器/协程被拒);
- 精确 build_pack(request) 单参数形态:第二位置参数/可选额外参数/
  *args/**kwargs/keyword-only/候选别名参数名全部拒绝(静态层);
- 主进程不 import 私有模块(B1/C3:验证后 sys.modules 不得出现私有
  builder 模块)。
"""

from __future__ import annotations

import sys

import pytest

from tests.route_c_stage2_6_0f.conftest import (
    write_private_builder,
)

FAMILIES = ("probe_null_sign", "probe_null_volstate",
            "probe_null_stochvol")


def _write(tmp_path, source, label="entrypoint-test",
           qualname="build_pack"):
    root = tmp_path / label
    root.mkdir(parents=True, exist_ok=True)
    (root / "builder_mod.py").write_text(source, encoding="utf-8")
    import json

    (root / "provider_config.json").write_text(json.dumps({
        "entrypoint_module": "builder_mod",
        "entrypoint_qualname": qualname,
        "families": list(FAMILIES),
        "pair_count_per_family": 4,
        "max_attempts": 2,
        "root_label": label,
    }), encoding="utf-8")
    return root


def _validate(root):
    from rl_curriculum.builder_identity import (
        validate_builder_entrypoint,
    )

    return validate_builder_entrypoint(
        root, "builder_mod", "build_pack", where="test",
        require_request_protocol=True)


def test_valid_entrypoint_passes_and_reports(tmp_path):
    root = _write(tmp_path, "def build_pack(request):\n    return None\n")
    report = _validate(root)
    assert report["kind"] == "function"
    assert report["signature_params"] == ["request"]
    assert report["source_file"] == "builder_mod.py"
    assert report["source_sha256"]
    # 主进程零 import:私有模块不得出现在 sys.modules(B1/C3)
    assert "builder_mod" not in sys.modules


def test_second_positional_arg_rejected(tmp_path):
    root = _write(
        tmp_path, "def build_pack(request, extra):\n    return None\n")
    with pytest.raises(Exception, match="签名违规|参数"):
        _validate(root)


def test_optional_extra_arg_rejected(tmp_path):
    root = _write(
        tmp_path, "def build_pack(request, timeout=10):\n"
                  "    return None\n")
    with pytest.raises(Exception, match="签名违规|默认值"):
        _validate(root)


def test_default_on_single_arg_rejected(tmp_path):
    root = _write(
        tmp_path, "def build_pack(request=None):\n    return None\n")
    with pytest.raises(Exception, match="签名违规|默认值"):
        _validate(root)


def test_var_args_rejected(tmp_path):
    root = _write(tmp_path, "def build_pack(*args):\n    return None\n")
    with pytest.raises(Exception, match="签名违规|\\*args"):
        _validate(root)


def test_var_kwargs_rejected(tmp_path):
    root = _write(
        tmp_path, "def build_pack(request, **kwargs):\n"
                  "    return None\n")
    with pytest.raises(Exception, match="签名违规|\\*\\*kwargs"):
        _validate(root)


def test_keyword_only_rejected(tmp_path):
    root = _write(
        tmp_path, "def build_pack(request, *, mode):\n"
                  "    return None\n")
    with pytest.raises(Exception, match="签名违规|keyword-only"):
        _validate(root)


@pytest.mark.parametrize("name", [
    "candidate", "candidate_path", "checkpoint", "checkpoint_path",
    "model", "policy", "score", "scores", "result", "exam_result",
    "verdict", "outcome", "prediction", "ranking",
])
def test_candidate_alias_param_rejected(tmp_path, name):
    root = _write(
        tmp_path, f"def build_pack({name}):\n    return None\n")
    with pytest.raises(Exception, match="签名违规|禁止参数"):
        _validate(root)


def test_class_constructor_rejected(tmp_path):
    root = _write(tmp_path, "class build_pack:\n    pass\n")
    with pytest.raises(Exception, match="类型|class"):
        _validate(root)


def test_async_function_rejected(tmp_path):
    root = _write(
        tmp_path, "async def build_pack(request):\n"
                  "    return None\n")
    with pytest.raises(Exception, match="类型|async"):
        _validate(root)


def test_comment_only_rejected(tmp_path):
    root = _write(
        tmp_path, "# def build_pack(request):\n"
                  "#     return None\n")
    with pytest.raises(Exception, match="AST|定义"):
        _validate(root)


def test_string_literal_rejected(tmp_path):
    root = _write(
        tmp_path, "build_pack = 'def build_pack(request): ...'\n")
    with pytest.raises(Exception, match="AST|定义"):
        _validate(root)


def test_missing_symbol_rejected(tmp_path):
    root = _write(tmp_path, "def other(request):\n    return None\n")
    with pytest.raises(Exception, match="AST|定义"):
        _validate(root)


def test_staticmethod_entrypoint_accepted(tmp_path):
    root = _write(
        tmp_path, "class Runner:\n"
                  "    @staticmethod\n"
                  "    def build_pack(request):\n"
                  "        return None\n")
    from rl_curriculum.builder_identity import (
        validate_builder_entrypoint,
    )

    report = validate_builder_entrypoint(
        root, "builder_mod", "Runner.build_pack", where="test",
        require_request_protocol=True)
    assert report["kind"] == "staticfunction"
    assert "builder_mod" not in sys.modules


def test_validate_does_not_import_private_module(tmp_path):
    """B1/C3:静态验证全程不 import 私有模块(顶层副作用不进入主进程)。"""
    root = _write(
        tmp_path,
        "import sys\n"
        "open('/tmp/PRIVATE_SIDE_EFFECT', 'w').write('x')\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    return None\n")
    _validate(root)
    assert "builder_mod" not in sys.modules
    import os

    assert not os.path.exists("/tmp/PRIVATE_SIDE_EFFECT")


def test_stale_module_cache_not_polluting(tmp_path):
    """同 root 已缓存旧 module:静态验证不触发 import,缓存无影响。"""
    root = _write(tmp_path, "def build_pack(request):\n    return None\n")
    types = types_mod = __import__("types")

    class _Fake:
        __file__ = "/elsewhere/builder_mod.py"

    sys.modules["builder_mod"] = _Fake()
    try:
        report = _validate(root)
        assert report["signature_params"] == ["request"]
    finally:
        del sys.modules["builder_mod"]
    assert isinstance(types, types_mod.ModuleType)


def test_private_provider_construct_no_import(tmp_path):
    """PrivateBuilderIdentityProvider 构造期零私有 import(B1)。"""
    root = write_private_builder(tmp_path / "no_import_builder")
    from rl_curriculum.builder_identity import (
        private_provider_from_config,
    )

    provider = private_provider_from_config(root)
    identity = provider.builder_identity()
    assert identity.run_mode == "builder_execution"
    assert "builder_a" not in sys.modules
    assert "helpers" not in sys.modules
