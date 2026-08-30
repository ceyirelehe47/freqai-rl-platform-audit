"""工作包 B3/E2/G5:native FFI 与执行路径攻击矩阵。

ctypes 各变体在其余矩阵覆盖;本文件覆盖 cffi、自带 native
extension、bundle 内恶意 .so、ExtensionFileLoader、scratch native
文件、预加载函数指针与 native allowlist 边界。
"""

from __future__ import annotations


def test_ctypes_cdll_file_rejected(run_attack2j):
    """G5:ctypes.CDLL(文件路径)加载 .so——Compute 内 open 被拒。"""
    outcome = run_attack2j(
        "    import ctypes\n"
        "    try:\n"
        "        lib = ctypes.CDLL('libm.so.6')\n"
        "        notes = {'loaded': True}\n"
        "    except OSError as exc:\n"
        "        notes = {'errno': exc.errno}\n",
        label="cdll-file")
    assert not isinstance(outcome, dict), "CDLL 文件加载未被拒绝"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_ctypes_cdll_none_syscall_rejected(run_attack2j):
    """G5/B3:CDLL(None)(已加载 libc 句柄)构造 raw syscall——
    final filter 拒未列 syscall(sysinfo 探针)。"""
    outcome = run_attack2j(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    libc.syscall.restype = ctypes.c_long\n"
        "    rc = libc.syscall(179, 0)\n"
        "    notes = {'sysinfo_rc': rc}\n",
        label="cdll-none-syscall")
    assert not isinstance(outcome, dict), "raw syscall 未被拒绝"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_cffi_rejected_if_present(run_attack2j):
    """G5:cffi(沙箱 bundle 不含 cffi;import 必须被拒——
    无论经 sys.modules 命中还是文件加载)。"""
    outcome = run_attack2j(
        "    import cffi\n"
        "    notes = {'cffi': cffi.__version__}\n",
        label="cffi-import")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_mmap_module_rejected(run_attack2j):
    """G5:mmap 模块(Python 层可执行映射 API)。"""
    outcome = run_attack2j(
        "    import mmap\n"
        "    buf = mmap.mmap(-1, 4096,\n"
        "                    prot=mmap.PROT_READ | mmap.PROT_WRITE)\n"
        "    notes = {'mmapped': True}\n",
        label="mmap-module")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_extensionfileloader_rejected(run_attack2j):
    """G5:ExtensionFileLoader 加载 .so 为模块。"""
    outcome = run_attack2j(
        "    from importlib.machinery import ExtensionFileLoader\n"
        "    m = ExtensionFileLoader(\n"
        "        'evil', '/lib/python3.11/lib-dynload/math."
        "cpython-311-x86_64-linux-gnu.so').load_module()\n"
        "    notes = {'m': m.__name__}\n",
        label="extfileloader")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_scratch_native_file_rejected(run_attack2j, tmp_path):
    """G5:scratch 内预置 .so 并 dlopen(Compute 内 open/dlopen 拒)。"""
    outcome = run_attack2j(
        "    import ctypes\n"
        "    lib = ctypes.CDLL('/scratch/evil.so')\n"
        "    notes = {'loaded': True}\n",
        label="scratch-so",
        extra_files={})
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_bundle_native_helper_undeclared_rejected(run_attack2j):
    """G5:bundle 内未声明 native helper(/lib 下 .so)——顶层 import
    只允许 allowlist;Compute 内 open 拒。"""
    outcome = run_attack2j(
        "    import ctypes\n"
        "    lib = ctypes.CDLL(\n"
        "        '/lib/python3.11/lib-dynload/_sha256."
        "cpython-311-x86_64-linux-gnu.so')\n"
        "    notes = {'loaded': True}\n",
        label="bundle-so")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_preloaded_function_pointer_cannot_escalate(run_attack2j):
    """E2:从已映射 native 地址构造 callable 调 mmap RWX——
    函数指针可构造,但 RWX mmap 本身被 final filter 参数过滤拒绝。"""
    outcome = run_attack2j(
        "    import ctypes\n"
        "    libc = ctypes.CDLL(None, use_errno=True)\n"
        "    libc.mmap.restype = ctypes.c_void_p\n"
        "    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int,\n"
        "                          ctypes.c_size_t, ctypes.c_int,\n"
        "                          ctypes.c_int, ctypes.c_int,\n"
        "                          ctypes.c_long)(libc.mmap)\n"
        "    page = fn(0, 4096, 7, 0x22, -1, 0)\n"
        "    notes = {'page': -1 if not page else 'LEAKED'}\n",
        label="fnptr-rwx")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_native_allowlist_modules_deterministic():
    """A3/B3:受审计 native allowlist 的确定性与非暴露性声明。"""
    from rl_builder_runtime.sealed_compute import (
        FORMAL_NATIVE_MODULES,
        FORMAL_PURE_MODULES,
    )

    for m in ("ctypes", "cffi", "mmap", "_ctypes"):
        assert m not in FORMAL_NATIVE_MODULES
        assert m not in FORMAL_PURE_MODULES
    # math/hashlib 是任务书允许的小型确定性 native 模块
    assert "math" in FORMAL_NATIVE_MODULES
    assert "hashlib" in FORMAL_NATIVE_MODULES
