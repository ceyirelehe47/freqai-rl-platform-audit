"""阶段 2.6.0j 测试夹具:Builder 不可逆密封计算、内核动态状态、文件
元数据与原生指令通道闭环。

自包含复用:
- 0f conftest 的私有 builder 资产生成(write_private_builder /
  private_provider_from_root);
- 0i conftest 的攻击 builder 模板(write_attack_builder,顶层纯度
  合规:body 全部位于 build_pack 函数体内)。

0j 专用:
- run_attack2j:真实生产路径单次攻击运行,支持 formal/compat 依赖
  profile 与自定义 BuilderRunnerProfile;
- hw_probe:宿主侧(无沙箱)真实执行硬件指令,记录 CPU/虚拟化能力
  (区分"CPU 不支持"与"生产机制阻断"的判定基准)。
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
TESTS = Path(__file__).resolve().parents[1]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from tests.route_c_stage2_6_0f.conftest import (  # noqa: E402
    private_provider_from_root,
    write_private_builder,
)
from tests.route_c_stage2_6_0i.conftest import (  # noqa: E402
    PACK_TMPL,
    _result_tail,
    write_attack_builder,
)


def write_attack_builder_2j(root, body, *, max_attempts=1,
                            top_imports="", label="attack-0j",
                            external_dependencies=None):
    """0j 攻击 builder 构造器:支持顶层 import 行(如包内 helper 模块;

    顶层行本身受纯度 AST 管辖)。body 归一化缩进后拼入 build_pack。
    """
    import json as _json

    root.mkdir(parents=True, exist_ok=True)
    body = _indent_body(body)
    src = (
        "'''2.6.0j 攻击 builder(测试专用)。'''\n"
        f"{top_imports}"
        "\n"
        "\n"
        "def build_pack(request):\n"
        f"{body}"
        f"{PACK_TMPL.format(notes='{}')}"
        f"{_result_tail(max_attempts=max_attempts)}"
    )
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    cfg = {
        "entrypoint_module": "builder_attack",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 2,
        "max_attempts": max_attempts,
        "root_label": label,
    }
    if external_dependencies is not None:
        cfg["external_dependencies"] = external_dependencies
    (root / "provider_config.json").write_text(
        _json.dumps(cfg), encoding="utf-8")
    return root

FAMS = ("probe_null_sign",)


@pytest.fixture(scope="session")
def seed_pack_and_dc():
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    seed = assemble_mock_hidden_pack()
    dc = derive_global_null_duration_contract(
        pack=seed, required_families=list(FAMS))
    return seed, dc


def _indent_body(body: str) -> str:
    """归一化 body 到 build_pack 函数体缩进(4 空格)。

    两种书写风格均可:顶格函数体(整体 +4,空行保持)或已带 4 空格
    的 0i 风格(原样)。判定:存在顶格非空行即视为顶格风格整体平移
    (嵌套行的相对层级保持)。
    """
    lines = body.splitlines()
    top_level = any(l.strip() and not l[0].isspace() for l in lines)
    if not top_level:
        return body
    out = [("    " + l) if l.strip() else l for l in lines]
    return "\n".join(out) + ("\n" if body.endswith("\n") else "")


@pytest.fixture()
def run_attack2j(tmp_path, seed_pack_and_dc):
    """真实生产路径单次攻击运行(2.6.0j)。

    _run(body, *, profile=None, dep_profile="formal", ...) -> 成功返回
    run record dict;失败返回 ("异常类型名", "消息")。
    """
    seed, dc = seed_pack_and_dc
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )

    def _run(body: str, *, profile=None,
             dep_profile: str = "formal",
             max_attempts: int = 1,
             label: str = "attack-0j",
             extra_files: dict | None = None,
             external_dependencies: list | None = None,
             bundle_pool=None):
        root = write_attack_builder(
            tmp_path / label, _indent_body(body),
            max_attempts=max_attempts,
            external_dependencies=external_dependencies
            if external_dependencies is not None else [],
            label=label, extra_files=extra_files)
        provider = private_provider_from_root(root)
        identity = provider.builder_identity()
        request = provider.frozen_build_request(seed, dc)
        if profile is None:
            profile = BuilderRunnerProfile(dependency_profile=dep_profile)
        try:
            return run_isolated_builder_run(
                identity, request, builder_root=root, profile=profile,
                bundle_pool=bundle_pool)
        except Exception as exc:  # noqa: BLE001
            return type(exc).__name__, str(exc)

    return _run


@pytest.fixture(scope="session")
def hw_probe():
    """宿主侧(无沙箱)硬件指令能力探测:真实执行,不做任何布尔推断。

    返回 dict:每条指令 -> {available: True/False, detail}。
    available=False 仅代表指令真实执行失败(#UD/崩溃),不得与
    "生产机制阻断"混淆。
    """
    import ctypes
    import mmap as _mmap

    results: dict[str, dict] = {}

    def _run_asm(asm: str, restype=ctypes.c_uint):
        code = bytes.fromhex(asm)
        buf = _mmap.mmap(-1, 4096,
                         prot=_mmap.PROT_READ | _mmap.PROT_WRITE
                         | _mmap.PROT_EXEC)
        buf.write(code)
        addr = ctypes.addressof(ctypes.c_char.from_buffer(buf))
        fn = ctypes.CFUNCTYPE(restype)(addr)
        return fn()

    for name, asm, rest in (
        ("cpuid", "53b80100000031c90fa289d85bc3", ctypes.c_uint),
        ("rdtsc", "0f31c3", ctypes.c_ulonglong),
        ("rdtscp", "0f310fc9c3", ctypes.c_ulonglong),
        ("rdrand", "0fc7f0c3", ctypes.c_int),
        ("rdseed", "0fc7f8c3", ctypes.c_int),
        ("rdpid", "f30fc7f8c3", ctypes.c_ulonglong),
    ):
        try:
            val = _run_asm(asm, rest)
            results[name] = {"available": True, "executed": True,
                             "value_sample": f"0x{val & 0xffffffffffffffff:x}"}
        except OSError as exc:
            results[name] = {"available": False, "executed": False,
                             "detail": f"OSError errno={exc.errno}"}
        except BaseException as exc:  # noqa: BLE001 - #UD 等崩溃
            results[name] = {"available": False, "executed": False,
                             "detail": type(exc).__name__}
    return results
