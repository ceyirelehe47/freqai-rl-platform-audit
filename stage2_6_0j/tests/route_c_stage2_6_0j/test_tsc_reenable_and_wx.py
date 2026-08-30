"""工作包 B1/G1:TSC 重新开启攻击与不可逆 W^X(MDWE)。

- G1:Builder 先 PR_TSC_ENABLE 再 RDTSC 用结果构造 pack——必须在
  prctl 步骤或更早 fail closed(不允许依赖后续 RDTSC 崩溃兜底);
- B2:PR_SET_MDWE 生效证明 + mmap RWX/mprotect W->X/memfd 执行映射
  攻击全部失败。
"""

from __future__ import annotations

import pytest


def test_tsc_reenable_then_rdtsc_attack(run_attack2j):
    """G1 核心:PR_SET_TSC=PR_TSC_ENABLE -> RDTSC -> notes。

    期望:final filter 拒绝 prctl(EPERM),Builder 无法重新开启 TSC;
    即便 Builder 忽略 prctl 失败继续 RDTSC,也已死于 SIGSEGV/prctl
    异常,绝不形成可信 pack。
    """
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "re_rc = libc.prctl(26, 1, 0, 0, 0)\n"   # PR_SET_TSC/ENABLE
        "re_errno = ctypes.get_errno()\n"
        "page = libc.mmap(0, 4096, 3, 0x22, -1, 0)\n"  # RW(无 exec)
        "code = b'\\x0f\\x31\\xc3'\n"
        "ctypes.memmove(page, code, 3)\n"
        "libc.mprotect(page, 4096, 5)\n"          # -> RX(必须被拒)
        "fn = ctypes.CFUNCTYPE(ctypes.c_uint64)(page)\n"
        "tsc = fn()\n"
        "notes = {'prctl_rc': re_rc, 'prctl_errno': re_errno, 'tsc': tsc}\n"
    )
    outcome = run_attack2j(body, label="tsc-reenable")
    assert not isinstance(outcome, dict), \
        "TSC 重新开启攻击产出了可信 pack(严重)"
    name, msg = outcome
    assert name in ("BuilderRunnerError", "BuilderProvenanceError"), \
        (name, msg)


def test_tsc_reenable_via_prctl_wrapper(run_attack2j):
    """G1 变体:经 prctl 包装库重开 TSC(不同调用路径同一防线)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.prctl(26, 1, 0, 0, 0)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "rc = libc.syscall(ctypes.c_long(157), ctypes.c_long(26),\n"
        "                  ctypes.c_long(1), 0, 0, 0)\n"  # raw prctl
        "notes = {'raw_prctl_rc': rc}\n"
    )
    outcome = run_attack2j(body, label="tsc-reenable-raw")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_mmap_rwx_attack_fails(run_attack2j):
    """B2/E2:匿名 RWX mmap + 写机器码 + 执行。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
        "notes = {'mmap_rwx': -1 if not page else 'LEAKED'}\n"
    )
    outcome = run_attack2j(body, label="mmap-rwx")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_mprotect_w_to_x_attack_fails(run_attack2j):
    """B2/E2:mmap RW -> mprotect RX(两步)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.mmap.restype = ctypes.c_void_p\n"
        "page = libc.mmap(None, 4096, 3, 0x22, -1, 0)\n"
        "ctypes.memmove(page, b'\\x0f\\x31\\xc3', 3)\n"
        "rc = libc.mprotect(page, 4096, 5)\n"
        "notes = {'mprotect_rc': rc}\n"
    )
    outcome = run_attack2j(body, label="mprotect-wx")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_memfd_exec_attack_fails(run_attack2j):
    """B2/E2:memfd_create + 写机器码 + mmap RX。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "fd = libc.syscall(ctypes.c_long(319), 0, 0)\n"
        "notes = {'memfd_fd': fd}\n"
    )
    outcome = run_attack2j(body, label="memfd")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_pkey_mprotect_attack_fails(run_attack2j):
    """B2/E2:pkey_mprotect 绕过尝试(nr 329)。"""
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.syscall.restype = ctypes.c_long\n"
        "rc = libc.syscall(ctypes.c_long(329), ctypes.c_long(0),\n"
        "                  ctypes.c_long(4096), ctypes.c_long(7),\n"
        "                  ctypes.c_long(-1))\n"
        "notes = {'pkey_mprotect_rc': rc}\n"
    )
    outcome = run_attack2j(body, label="pkey-mprotect")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")


def test_mdwe_enabled_in_real_run(tmp_path, seed_pack_and_dc):
    """B2:真实链路中 PR_SET_MDWE 生效证明进入锁 v4。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
        write_private_builder,
    )

    root = write_private_builder(tmp_path / "mdwe-builder")
    provider = private_provider_from_root(root)
    seed, dc = seed_pack_and_dc
    run = run_isolated_builder_run(
        provider.builder_identity(),
        provider.frozen_build_request(seed, dc),
        builder_root=root, profile=BuilderRunnerProfile())
    mdwe = run["runtime_lock"]["sealed_compute"]["mdwe"]
    assert mdwe["enabled"] is True
    assert mdwe["mode"] == "PR_SET_MDWE_REFUSE_EXEC_GAIN"
    after = run["runtime_lock"]["sealed_compute"]["compute_after"]
    assert after["exec_mapping_growth"] == 0
    assert after["seccomp_filter_count"] >= 2


def test_preexisting_exec_page_call_attack_fails(run_attack2j):
    """E2 变体:从已映射 native 地址构造 callable(不新建 exec 页)。

    libc 内已存在的函数地址可被 CFUNCTYPE 包装——但它只能调用已有
    libc 函数(syscall 层仍被 final filter 管辖);该攻击本身经
    libc.syscall(nr=179 sysinfo) 读内核状态,必须失败。
    """
    body = (
        "import ctypes\n"
        "libc = ctypes.CDLL(None, use_errno=True)\n"
        "libc.sysinfo.restype = ctypes.c_long\n"
        "class SI(ctypes.Structure):\n"
        "    _fields_ = [('uptime', ctypes.c_long)]\n"
        "si = SI()\n"
        "fn = ctypes.CFUNCTYPE(ctypes.c_long,\n"
        "                      ctypes.c_void_p)(libc.sysinfo)\n"
        "rc = fn(ctypes.byref(si))\n"
        "notes = {'uptime_via_fnptr': si.uptime, 'rc': rc}\n"
    )
    outcome = run_attack2j(body, label="fnptr-preexisting")
    assert not isinstance(outcome, dict)
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError")
